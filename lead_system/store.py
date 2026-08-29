from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


_STORE_LOCK = threading.RLock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_phone(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def is_turkish_mobile(value: str | None) -> bool:
    """Only Turkish GSM lines can receive a WhatsApp proposal."""
    digits = normalize_phone(value)
    if digits.startswith("90") and len(digits) == 12:
        digits = digits[2:]
    return len(digits) == 10 and digits.startswith("5")


def is_social_url(value: str | None) -> bool:
    host = (urlparse(value or "").hostname or "").lower().removeprefix("www.")
    return host in {"instagram.com", "facebook.com", "tiktok.com", "youtube.com", "x.com", "twitter.com", "linkedin.com"}


def is_directory_url(value: str | None) -> bool:
    host = (urlparse(value or "").hostname or "").lower().removeprefix("www.")
    return host in {"firmasec.com", "buldum.com", "yellowpages.com.tr", "find.com.tr", "iyifirma.com", "foursquare.com", "tripadvisor.com.tr", "yelp.com"}


def canonical_url(value: str | None) -> str:
    parsed = urlparse(value or "")
    return f"{(parsed.hostname or '').lower().removeprefix('www.')}{parsed.path.rstrip('/')}"


MUNICIPAL_TERMS = ("belediye", "büyükşehir", "buyuksehir", "anakent", "samsun kültür", "samsun kultur")
MUNICIPAL_DOMAINS = ("samsun.bel.tr", "samsunanakent.com", "samsunkulturturizm.com")


def is_municipal_business(name: str | None, url: str | None = "") -> bool:
    haystack = f"{name or ''} {url or ''}".lower()
    host = (urlparse(url or "").hostname or "").lower()
    return any(term in haystack for term in MUNICIPAL_TERMS) or any(domain in host for domain in MUNICIPAL_DOMAINS)


def safe_ai_summary(lead: dict[str, Any], value: Any) -> str:
    """Never expose the orchestrator envelope or English role boilerplate in UI."""
    text = str(value or "").strip()
    bad = ("Research analysis", "Researcher:", "HK-Agents Multi-Agent Execution Summary", "Tamamlanan Worker", "strictly examining", "analysis completed", "provided evidence", "audit task", "execution summary", "worker completed")
    if text and not any(marker.lower() in text.lower() for marker in bad):
        return text[:2000]
    details = lead.get("source_details") or {}
    instagram = lead.get("instagram_evidence") or {}
    parts = [f"{lead.get('business_name', 'İşletme')} için Maps ve Instagram verileri incelendi."]
    if details.get("rating") is not None or details.get("reviews_count") is not None:
        parts.append(f"Google Maps puanı {details.get('rating', 'bilinmiyor')}, yorum sayısı {details.get('reviews_count', 'bilinmiyor')}.")
    else:
        parts.append("Google Maps yorum/puan ayrıntısı alınamadı.")
    if instagram:
        parts.append(f"Instagram @{instagram.get('username', '')} profilinde {instagram.get('followers', 'bilinmeyen')} takipçi ve {instagram.get('posts_count', 'bilinmeyen')} gönderi bulundu.")
    elif lead.get("instagram_url"):
        parts.append("Instagram hesabı bulundu ancak profil ayrıntıları alınamadı.")
    else:
        parts.append("Instagram profili bulunamadı.")
    return " ".join(parts)


class LeadStore:
    """Small atomic JSON state store; replaceable by Google Sheets/Postgres later."""

    def __init__(self, path: Path | None = None):
        self.path = path or Path("lead_system/data/leads.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.suppression_path = self.path.parent / "suppression.json"

    def _read(self) -> list[dict[str, Any]]:
        with _STORE_LOCK:
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                return []

    def _write(self, leads: list[dict[str, Any]]) -> None:
        with _STORE_LOCK:
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(leads, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.path)

    def _suppressed(self) -> set[str]:
        with _STORE_LOCK:
            try:
                return set(json.loads(self.suppression_path.read_text(encoding="utf-8")))
            except (FileNotFoundError, json.JSONDecodeError):
                return set()

    def _write_suppressed(self, values: set[str]) -> None:
        with _STORE_LOCK:
            temp = self.suppression_path.with_suffix(".tmp")
            temp.write_text(json.dumps(sorted(values), ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.suppression_path)

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        leads = self._read()
        return [x for x in leads if not status or x.get("approval_status") == status]

    def upsert_places(self, places: list[dict[str, Any]], run_id: str) -> int:
        leads = self._read()
        index = {x.get("dedupe_key"): x for x in leads}
        added = 0
        for place in places:
            phone = normalize_phone(place.get("phone") or place.get("phoneUnformatted"))
            place_id = str(place.get("placeId") or "").strip()
            website = place.get("website") or ""
            social_url = website if is_social_url(website) else ""
            directory_url = website if is_directory_url(website) else ""
            if social_url or directory_url:
                website = ""
            name = place.get("title") or place.get("name") or ""
            if is_municipal_business(name, website):
                continue
            key = f"place:{place_id}" if place_id else f"phone:{phone}" if phone else f"name:{name.lower()}:{place.get('address','').lower()}"
            if not key or key == "name::":
                continue
            suppressed = self._suppressed()
            if any(str(value).lower() in suppressed for value in (key, phone, name) if value):
                continue
            existing = index.get(key)
            if existing:
                existing["last_seen_at"] = now()
                existing["latest_run_id"] = run_id
                continue
            lead = {
                "lead_id": key.replace(":", "-"),
                "dedupe_key": key,
                "business_name": name,
                "business_type": place.get("categoryName") or (place.get("categories") or [""])[0],
                "address": place.get("address") or "",
                "district": place.get("neighborhood") or place.get("subTitle") or "",
                "phone": phone,
                "google_maps_url": place.get("url") or "",
                "website_url": website,
                "instagram_url": social_url if "instagram.com" in social_url.lower() else "",
                "directory_url": directory_url,
                "website_status": "unknown" if website else "missing",
                "website_findings": [],
                "instagram_status": "unknown",
                "instagram_activity_summary": "",
                "online_platforms": list(place.get("online_platforms") or []),
                "delivery_platforms": list(place.get("delivery_platforms") or []),
                "platform_links": dict(place.get("platform_links") or {}),
                "web_search_evidence": place.get("web_search_evidence") or {},
                "ai_summary": "",
                "source_details": {
                    "rating": place.get("totalScore"),
                    "reviews_count": place.get("reviewsCount"),
                    "categories": place.get("categories") or [],
                    "description": place.get("description") or "",
                    "reviews": place.get("reviews") or [],
                    "opening_hours": place.get("openingHours") or [],
                    "menu_url": place.get("menu") or "",
                    "is_permanently_closed": place.get("permanentlyClosed", False),
                    "is_temporarily_closed": place.get("temporarilyClosed", False),
                },
                "ai_score": None,
                "decision": "İNCELE",
                "decision_reasons": ["Yeni aday; enrichment ve AI analizi bekleniyor."],
                "risk_flags": [],
                "recommended_service": "Mobil uyumlu tanıtım sitesi veya komisyonsuz online satış sitesi",
                "message_draft": f"Merhaba {name},\n\nİşletmeniz için mobil uyumlu bir tanıtım sitesi ya da ürünlerinizi aracı komisyonu olmadan doğrudan satabileceğiniz online sipariş sitesi konusunda kısa bir taslak hazırlayabiliriz. Uygun olursanız paylaşmak isteriz.\n\nHK Yazılım",
                "approval_status": "needs_review",
                "send_status": "not_sent",
                "opt_out_status": False,
                "latest_run_id": run_id,
                "created_at": now(),
                "last_seen_at": now(),
            }
            lead["ai_summary"] = f"{lead['business_name']} için ilk değerlendirme: {lead['decision_reasons'][0]} Teklif seviyesi: {lead['decision']}."
            leads.append(lead)
            index[key] = lead
            added += 1
        self._write(leads)
        return added

    def update(self, lead_id: str, **changes: Any) -> dict[str, Any]:
        leads = self._read()
        for lead in leads:
            if lead.get("lead_id") == lead_id:
                if lead.get("opt_out_status") and changes.get("approval_status") == "approved":
                    raise ValueError("Opt-out kaydı olan aday onaylanamaz")
                if "ai_summary" in changes:
                    changes["ai_summary"] = safe_ai_summary(lead, changes["ai_summary"])
                lead.update(changes, updated_at=now())
                self._write(leads)
                return lead
        raise KeyError(lead_id)

    def approve(self, lead_id: str, message: str | None = None) -> dict[str, Any]:
        lead = self.get(lead_id)
        if lead.get("opt_out_status"):
            raise ValueError("Bu aday iletişim dışı bırakılmış")
        return self.update(lead_id, approval_status="approved", approved_at=now(), **({"message_draft": message} if message is not None else {}))

    def skip(self, lead_id: str) -> dict[str, Any]:
        return self.update(lead_id, approval_status="skipped", skipped_at=now())

    def remove(self, lead_id: str) -> dict[str, Any]:
        with _STORE_LOCK:
            leads = self._read()
            for index, lead in enumerate(leads):
                if lead.get("lead_id") == lead_id:
                    removed = leads.pop(index)
                    self._write(leads)
                    return removed
            raise KeyError(lead_id)

    def opt_out(self, lead_id: str) -> dict[str, Any]:
        lead = self.get(lead_id)
        suppressed = self._suppressed()
        for value in (lead.get("lead_id"), lead.get("phone"), lead.get("business_name")):
            if value:
                suppressed.add(str(value).lower())
        self._write_suppressed(suppressed)
        return self.remove(lead_id)

    def get(self, lead_id: str) -> dict[str, Any]:
        for lead in self._read():
            if lead.get("lead_id") == lead_id:
                return lead
        raise KeyError(lead_id)
