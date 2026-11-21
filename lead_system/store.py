from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


_STORE_LOCK = threading.RLock()
VALID_CRM_STAGES = ("new", "reviewed", "contacted", "negotiating", "won", "lost")


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
    """SQLite-backed atomic lead store with automatic one-time JSON migration."""

    def __init__(self, path: Path | None = None):
        base = path or Path("lead_system/data/leads.db")
        if base.suffix == ".json":
            self.legacy_json_path = base
            self.db_path = base.with_suffix(".db")
        else:
            self.db_path = base
            self.legacy_json_path = base.parent / "leads.json"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.suppression_path = self.db_path.parent / "suppression.json"
        self._init_db()
        self._migrate_legacy_json()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with _STORE_LOCK, self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS leads (
                    lead_id TEXT PRIMARY KEY,
                    dedupe_key TEXT UNIQUE,
                    approval_status TEXT DEFAULT 'needs_review',
                    crm_stage TEXT DEFAULT 'new',
                    latest_run_id TEXT DEFAULT '',
                    created_at TEXT DEFAULT '',
                    updated_at TEXT DEFAULT '',
                    payload TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(approval_status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_crm ON leads(crm_stage)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_run ON leads(latest_run_id)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS suppression (
                    value TEXT PRIMARY KEY,
                    added_at TEXT NOT NULL
                )
            """)

    def _migrate_legacy_json(self) -> None:
        with _STORE_LOCK, self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
            if count == 0 and self.legacy_json_path.exists():
                try:
                    legacy = json.loads(self.legacy_json_path.read_text(encoding="utf-8"))
                    if isinstance(legacy, list):
                        for item in legacy:
                            if isinstance(item, dict) and item.get("lead_id"):
                                item.setdefault("crm_stage", self._infer_crm_stage(item))
                                self._upsert_row(conn, item)
                except (OSError, json.JSONDecodeError):
                    pass
            sup_count = conn.execute("SELECT COUNT(*) FROM suppression").fetchone()[0]
            if sup_count == 0 and self.suppression_path.exists():
                try:
                    values = json.loads(self.suppression_path.read_text(encoding="utf-8"))
                    if isinstance(values, list):
                        ts = now()
                        conn.executemany(
                            "INSERT OR IGNORE INTO suppression(value, added_at) VALUES (?, ?)",
                            [(str(v).lower(), ts) for v in values if v],
                        )
                except (OSError, json.JSONDecodeError):
                    pass

    @staticmethod
    def _infer_crm_stage(lead: dict[str, Any]) -> str:
        existing = lead.get("crm_stage")
        if existing in VALID_CRM_STAGES:
            return existing
        status = lead.get("approval_status")
        if status == "sent" or lead.get("send_status") == "sent":
            return "contacted"
        if status == "approved":
            return "reviewed"
        return "new"

    @staticmethod
    def _upsert_row(conn: sqlite3.Connection, lead: dict[str, Any]) -> None:
        stage = LeadStore._infer_crm_stage(lead)
        lead["crm_stage"] = stage
        conn.execute(
            """
            INSERT INTO leads (lead_id, dedupe_key, approval_status, crm_stage, latest_run_id, created_at, updated_at, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(lead_id) DO UPDATE SET
                dedupe_key=excluded.dedupe_key,
                approval_status=excluded.approval_status,
                crm_stage=excluded.crm_stage,
                latest_run_id=excluded.latest_run_id,
                updated_at=excluded.updated_at,
                payload=excluded.payload
            """,
            (
                lead["lead_id"],
                lead.get("dedupe_key") or lead["lead_id"],
                lead.get("approval_status") or "needs_review",
                stage,
                lead.get("latest_run_id") or "",
                lead.get("created_at") or now(),
                lead.get("updated_at") or now(),
                json.dumps(lead, ensure_ascii=False),
            ),
        )

    def _suppressed(self) -> set[str]:
        with _STORE_LOCK, self._connect() as conn:
            return {row[0] for row in conn.execute("SELECT value FROM suppression").fetchall()}

    def _add_suppressed(self, values: list[str]) -> None:
        with _STORE_LOCK, self._connect() as conn:
            ts = now()
            conn.executemany(
                "INSERT OR IGNORE INTO suppression(value, added_at) VALUES (?, ?)",
                [(str(v).lower(), ts) for v in values if v],
            )

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        with _STORE_LOCK, self._connect() as conn:
            if status:
                rows = conn.execute("SELECT payload FROM leads WHERE approval_status = ? ORDER BY rowid ASC", (status,)).fetchall()
            else:
                rows = conn.execute("SELECT payload FROM leads ORDER BY rowid ASC").fetchall()
            result = []
            for (raw,) in rows:
                item = json.loads(raw)
                item.setdefault("crm_stage", self._infer_crm_stage(item))
                result.append(item)
            return result

    def upsert_places(self, places: list[dict[str, Any]], run_id: str) -> int:
        added = 0
        with _STORE_LOCK, self._connect() as conn:
            suppressed = {row[0] for row in conn.execute("SELECT value FROM suppression").fetchall()}
            existing_rows = {
                row[0]: json.loads(row[1])
                for row in conn.execute("SELECT dedupe_key, payload FROM leads").fetchall()
            }
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
                if any(str(value).lower() in suppressed for value in (key, phone, name) if value):
                    continue
                existing = existing_rows.get(key)
                if existing:
                    existing["last_seen_at"] = now()
                    existing["latest_run_id"] = run_id
                    if place.get("online_platforms"):
                        existing["online_platforms"] = list(place.get("online_platforms") or [])
                        existing["delivery_platforms"] = list(place.get("delivery_platforms") or [])
                        existing["platform_links"] = dict(place.get("platform_links") or {})
                        existing["ad_library_url"] = place.get("ad_library_url") or existing.get("ad_library_url") or ""
                    self._upsert_row(conn, existing)
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
                    "instagram_url": social_url if "instagram.com" in social_url.lower() else str(place.get("discovered_instagram") or ""),
                    "directory_url": directory_url,
                    "website_status": "unknown" if website else "missing",
                    "website_findings": [],
                    "instagram_status": "unknown",
                    "instagram_activity_summary": "",
                    "online_platforms": list(place.get("online_platforms") or []),
                    "delivery_platforms": list(place.get("delivery_platforms") or []),
                    "platform_links": dict(place.get("platform_links") or {}),
                    "ad_library_url": str(place.get("ad_library_url") or ""),
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
                    "crm_stage": "new",
                    "send_status": "not_sent",
                    "opt_out_status": False,
                    "latest_run_id": run_id,
                    "created_at": now(),
                    "last_seen_at": now(),
                }
                lead["ai_summary"] = f"{lead['business_name']} için ilk değerlendirme: {lead['decision_reasons'][0]} Teklif seviyesi: {lead['decision']}."
                self._upsert_row(conn, lead)
                existing_rows[key] = lead
                added += 1
        return added

    def update(self, lead_id: str, **changes: Any) -> dict[str, Any]:
        with _STORE_LOCK, self._connect() as conn:
            row = conn.execute("SELECT payload FROM leads WHERE lead_id = ?", (lead_id,)).fetchone()
            if not row:
                raise KeyError(lead_id)
            lead = json.loads(row[0])
            if lead.get("opt_out_status") and changes.get("approval_status") == "approved":
                raise ValueError("Opt-out kaydı olan aday onaylanamaz")
            if "ai_summary" in changes:
                changes["ai_summary"] = safe_ai_summary(lead, changes["ai_summary"])
            if "crm_stage" in changes and changes["crm_stage"] not in VALID_CRM_STAGES:
                raise ValueError(f"Geçersiz CRM aşaması: {changes['crm_stage']}")
            lead.update(changes, updated_at=now())
            self._upsert_row(conn, lead)
            return lead

    def approve(self, lead_id: str, message: str | None = None) -> dict[str, Any]:
        lead = self.get(lead_id)
        if lead.get("opt_out_status"):
            raise ValueError("Bu aday iletişim dışı bırakılmış")
        extra: dict[str, Any] = {"crm_stage": "reviewed"}
        if message is not None:
            extra["message_draft"] = message
        return self.update(lead_id, approval_status="approved", approved_at=now(), **extra)

    def set_crm_stage(self, lead_id: str, stage: str) -> dict[str, Any]:
        if stage not in VALID_CRM_STAGES:
            raise ValueError(f"Geçersiz CRM aşaması: {stage}")
        return self.update(lead_id, crm_stage=stage)

    def skip(self, lead_id: str) -> dict[str, Any]:
        return self.update(lead_id, approval_status="skipped", skipped_at=now())

    def remove(self, lead_id: str) -> dict[str, Any]:
        with _STORE_LOCK, self._connect() as conn:
            row = conn.execute("SELECT payload FROM leads WHERE lead_id = ?", (lead_id,)).fetchone()
            if not row:
                raise KeyError(lead_id)
            conn.execute("DELETE FROM leads WHERE lead_id = ?", (lead_id,))
            return json.loads(row[0])

    def opt_out(self, lead_id: str) -> dict[str, Any]:
        lead = self.get(lead_id)
        self._add_suppressed([v for v in (lead.get("lead_id"), lead.get("phone"), lead.get("business_name")) if v])
        return self.remove(lead_id)

    def get(self, lead_id: str) -> dict[str, Any]:
        with _STORE_LOCK, self._connect() as conn:
            row = conn.execute("SELECT payload FROM leads WHERE lead_id = ?", (lead_id,)).fetchone()
            if not row:
                raise KeyError(lead_id)
            item = json.loads(row[0])
            item.setdefault("crm_stage", self._infer_crm_stage(item))
            return item

    def export_csv(self) -> str:
        """Export all leads as UTF-8 BOM CSV for Excel/Google Sheets."""
        buf = io.StringIO()
        buf.write("\ufeff")
        fields = [
            "lead_id", "business_name", "business_type", "district", "address",
            "phone", "website_url", "website_status", "instagram_url",
            "delivery_platforms", "online_platforms", "ai_score", "decision",
            "approval_status", "crm_stage", "send_status", "google_maps_url",
            "ai_summary", "message_draft",
        ]
        writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for lead in self.list():
            row = dict(lead)
            row["delivery_platforms"] = ", ".join(lead.get("delivery_platforms") or [])
            row["online_platforms"] = ", ".join(lead.get("online_platforms") or [])
            writer.writerow(row)
        return buf.getvalue()
