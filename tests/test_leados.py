from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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


if __name__ == "__main__":
    unittest.main()
