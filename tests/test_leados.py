from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from unittest.mock import patch
from urllib.error import URLError

import lead_automation
import website_ai_worker
from lead_automation import check_website, discovery_searches, is_in_turkey, location_query_for
from lead_system.preview_generator import generate_demo_html
from lead_system.scoring import score_lead
from lead_system.store import LeadStore
from lead_system.wacli_bridge import _format_tr_e164
from lead_system.web_search import _match_official_website


class TestLeadOS(unittest.TestCase):
    def test_turkey_geo_lock_and_district_expansion(self):
        self.assertEqual(location_query_for("istanbul burgerci"), "İstanbul, Turkey")
        self.assertEqual(location_query_for("samsun fastfood"), "Samsun, Turkey")
        self.assertEqual(location_query_for("oto yıkama"), "Turkey")

        ist = discovery_searches("istanbul burgerci")
        self.assertEqual(len(ist), 5)
        self.assertTrue(any("Kadıköy" in q for q in ist))

        self.assertTrue(is_in_turkey({"countryCode": "TR", "address": "Atakum/Samsun, Türkiye", "phone": "+90 532 111 22 33"}))
        self.assertFalse(is_in_turkey({"countryCode": "GB", "address": "London, United Kingdom", "phone": "+44 20 7946 0000"}))
        self.assertFalse(is_in_turkey({"address": "Berlin, Almanya", "phone": "493033607223"}))
        self.assertFalse(is_in_turkey({"location": {"lat": 51.5074, "lng": -0.1278}, "address": "Istanbul Grill"}))

    def test_ssrf_blocks_loopback_and_private_ips(self):
        res = check_website("http://127.0.0.1:8790/")
        self.assertEqual(res["status"], "broken")
        self.assertIn("engellendi", res["findings"][0])

        res2 = check_website("http://169.254.169.254/latest/meta-data/")
        self.assertEqual(res2["status"], "broken")

    def test_sqlite_store_migration_crm_and_csv(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            legacy = tmp_path / "leads.json"
            legacy.write_text(json.dumps([{
                "lead_id": "place-abc",
                "dedupe_key": "place:abc",
                "business_name": "Test Burger",
                "business_type": "Burgerci",
                "phone": "905301112233",
                "approval_status": "needs_review",
                "delivery_platforms": ["Yemeksepeti"],
                "online_platforms": ["Yemeksepeti", "Instagram"],
            }]), encoding="utf-8")

            store = LeadStore(tmp_path / "leads.db")
            leads = store.list()
            self.assertEqual(len(leads), 1)
            self.assertEqual(leads[0]["business_name"], "Test Burger")
            self.assertEqual(leads[0]["crm_stage"], "new")

            updated = store.set_crm_stage("place-abc", "negotiating")
            self.assertEqual(updated["crm_stage"], "negotiating")

            approved = store.approve("place-abc", "Merhaba!")
            self.assertEqual(approved["approval_status"], "approved")
            self.assertEqual(approved["crm_stage"], "reviewed")

            csv_text = store.export_csv()
            self.assertIn("Test Burger", csv_text)
            self.assertIn("Yemeksepeti", csv_text)

            store.opt_out("place-abc")
            self.assertEqual(store.list(), [])
            self.assertEqual(store.upsert_places([{"placeId": "abc", "title": "Test Burger", "phone": "+905301112233"}], "run-2"), 0)

    def test_scoring_delivery_and_redesign_bonuses(self):
        no_site_delivery = score_lead({
            "website_url": "",
            "website_status": "missing",
            "delivery_platforms": ["Yemeksepeti", "GetirYemek"],
            "phone": "905301112233",
        })
        self.assertEqual(no_site_delivery["decision"], "ÖNER")
        self.assertGreaterEqual(no_site_delivery["ai_score"], 80)

        redesign = score_lead({
            "website_url": "http://eski-site.com",
            "website_status": "redesign",
            "website_findings": ["SSL (HTTPS) yok, mobil viewport etiketi yok"],
            "phone": "905301112233",
        })
        self.assertGreaterEqual(redesign["ai_score"], 55)

        opted = score_lead({"opt_out_status": True})
        self.assertEqual(opted["decision"], "ELE")
        self.assertEqual(opted["ai_score"], 0)

    def test_web_search_official_matching(self):
        self.assertTrue(_match_official_website("The Amazon Coffee", "https://theamazoncoffee.com.tr/", "The Amazon Coffee", ""))
        self.assertFalse(_match_official_website("The Amazon Coffee", "https://www.yemeksepeti.com/restaurant/amazon", "Amazon", ""))
        self.assertFalse(_match_official_website("The Amazon Coffee", "https://www.instagram.com/theamazoncoffee/", "Amazon", ""))

    def test_preview_generator_escapes_xss(self):
        html = generate_demo_html({
            "business_name": '<script>alert("xss")</script> Burger',
            "business_type": "Burgerci",
            "google_maps_url": "javascript:alert(1)",
            "delivery_platforms": ["Yemeksepeti"],
        })
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("javascript:alert", html)
        self.assertIn("Yemeksepeti", html)

    def test_wacli_e164_validation(self):
        self.assertEqual(_format_tr_e164("0532 111 22 33"), "+905321112233")
        self.assertEqual(_format_tr_e164("905321112233"), "+905321112233")
        with self.assertRaises(ValueError):
            _format_tr_e164("+44 20 1234 5678")

    def test_check_website_probes_https_first_for_http_urls(self):
        """An http:// Google Maps URL that supports valid HTTPS must be classified as live."""
        html_ok = (
            "<!doctype html><html><head><meta name='viewport' content='width=device-width'>"
            "<title>Bambam Burger | Taş Devri Burger Restoranı</title></head>"
            "<body><h1>Bambam Burger</h1><p>Smash ve red burgerlerimizle Kadıköy Moda'da "
            "hizmetinizdeyiz. Menümüz, soslarımız ve franchise başvurusu burada.</p></body></html>"
        )
        seen_urls: list[str] = []

        def fake_fetch(target_url: str, user_agent: str = ""):
            seen_urls.append(target_url)
            return 200, target_url, html_ok, 45

        with patch.object(lead_automation, "_validate_public_url", side_effect=lambda u: (True, u, "")), \
             patch.object(lead_automation, "_fetch_public_page", side_effect=fake_fetch):
            res = check_website("http://www.bambamburger.com.tr/")

        self.assertEqual(seen_urls, ["https://www.bambamburger.com.tr/"])
        self.assertEqual(res["status"], "live")
        self.assertTrue(res["has_ssl"])
        self.assertEqual(res["final_url"], "https://www.bambamburger.com.tr/")
        self.assertFalse(res["needs_redesign"])

    def test_check_website_falls_back_to_http_when_https_fails(self):
        html_ok = (
            "<!doctype html><html><head><meta name='viewport' content='width=device-width'>"
            "<title>Eski Restoran</title></head>"
            "<body><p>Geleneksel lezzetlerimiz ve adres bilgilerimiz bu sayfada yer almaktadır. "
            "Bizi arayarak rezervasyon yapabilirsiniz.</p></body></html>"
        )

        def fake_fetch(target_url: str, user_agent: str = ""):
            if target_url.startswith("https://"):
                raise URLError("SSL handshake failed")
            return 200, target_url, html_ok, 120

        with patch.object(lead_automation, "_validate_public_url", side_effect=lambda u: (True, u, "")), \
             patch.object(lead_automation, "_fetch_public_page", side_effect=fake_fetch):
            res = check_website("http://eski-restoran.example.com/")

        self.assertEqual(res["status"], "redesign")
        self.assertFalse(res["has_ssl"])
        self.assertTrue(res["needs_redesign"])

    def test_check_website_spa_vs_parked_and_coming_soon(self):
        spa_html = (
            "<!doctype html><html><head><meta name='viewport' content='width=device-width'>"
            "<title>Zapata Burger | Craft Burgers — Kadıköy</title>"
            "<meta name='description' content='Kadıköy zanaatkâr burger restoranı resmi sitesi'>"
            "</head><body><div id='root'>Fresh. Natural.</div>"
            + ("<script>/* bundle */</script>" * 3)
            + (" " * 4200)
            + "</body></html>"
        )
        coming_soon = "<!doctype html><html><head><title>Coming Soon</title></head><body><h1>Coming Soon</h1></body></html>"
        tiny_logo = "<html><head><title>example.com.tr</title></head><body><img src='logo.jpg'></body></html>"

        with patch.object(lead_automation, "_validate_public_url", side_effect=lambda u: (True, u, "")):
            with patch.object(lead_automation, "_fetch_public_page", return_value=(200, "https://zapataburger.com/", spa_html, 150)):
                self.assertEqual(check_website("https://zapataburger.com/")["status"], "live")
            with patch.object(lead_automation, "_fetch_public_page", return_value=(200, "https://zeo.example/", coming_soon, 100)):
                self.assertEqual(check_website("https://zeo.example/")["status"], "poor")
            with patch.object(lead_automation, "_fetch_public_page", return_value=(200, "https://example.com.tr/", tiny_logo, 100)):
                self.assertEqual(check_website("https://example.com.tr/")["status"], "poor")

    def test_gemini_key_loader_and_message_fallback_without_workers_root(self):
        self.assertEqual(
            website_ai_worker._extract_api_key_from_text("API Key\nAQ.Ab8RN6Kx9ExampleKeyValue1234567890\n"),
            "AQ.Ab8RN6Kx9ExampleKeyValue1234567890",
        )
        self.assertEqual(
            website_ai_worker._extract_api_key_from_text("GEMINI_API_KEY='AIzaSyDummyKeyValue123456789012345'\n"),
            "AIzaSyDummyKeyValue123456789012345",
        )

        lead = {
            "business_name": "Eski Site Kafe",
            "website_url": "http://eskisitekafe.com",
            "website_status": "redesign",
        }
        with patch.object(website_ai_worker, "_generate_message_direct", return_value=""), \
             patch.object(website_ai_worker, "audit_leads", return_value=([], "")), \
             patch.object(website_ai_worker, "WORKERS_ROOT", Path("/nonexistent/hk-workers-dir")):
            msg = website_ai_worker.generate_message(lead)
        self.assertIn("Eski Site Kafe", msg)
        self.assertIn("http://eskisitekafe.com", msg)
        self.assertIn("HK Yazılım", msg)


if __name__ == "__main__":
    unittest.main()
