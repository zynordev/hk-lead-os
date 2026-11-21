"""One-click responsive HTML5 demo landing page generator for any LeadOS business."""

from __future__ import annotations

import html
import re
from typing import Any


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _wa_link(phone: str, business_name: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10 and digits.startswith("5"):
        digits = f"90{digits}"
    if not digits:
        return "#"
    msg = f"Merhaba {business_name}, menü ve sipariş hakkında bilgi almak istiyorum."
    from urllib.parse import quote
    return f"https://wa.me/{digits}?text={quote(msg)}"


def _theme_for_category(business_type: str) -> tuple[str, str, str]:
    """Return (accent_hex, accent_dark_hex, emoji) tailored to the business sector."""
    low = (business_type or "").lower()
    if any(k in low for k in ("burger", "fast", "pizza", "kebap", "döner", "doner", "restoran", "lokanta")):
        return "#e63946", "#9d0208", "🍔"
    if any(k in low for k in ("kafe", "cafe", "kahve", "coffee", "pastane", "patisserie", "tatlı")):
        return "#b45309", "#78350f", "☕"
    if any(k in low for k in ("kuaför", "kuafor", "berber", "güzellik", "beauty", "hair", "salon")):
        return "#9333ea", "#581c87", "✂️"
    if any(k in low for k in ("oto", "servis", "lastik", "tamir", "galeri")):
        return "#2563eb", "#1e3a8a", "🚗"
    return "#0f766e", "#134e4a", "✨"


def generate_demo_html(lead: dict[str, Any]) -> str:
    """Render a self-contained, XSS-safe single-page demo website for a business."""
    name = str(lead.get("business_name") or "İşletmeniz").strip()
    btype = str(lead.get("business_type") or "Yerel İşletme").strip()
    address = str(lead.get("address") or "Türkiye").strip()
    district = str(lead.get("district") or "").strip()
    phone = str(lead.get("phone") or "").strip()
    details = lead.get("source_details") or {}
    rating = details.get("rating")
    reviews_count = details.get("reviews_count")
    hours_list = details.get("opening_hours") or []
    hours_text = " · ".join(str(h) for h in hours_list[:3]) if hours_list else "Her gün hizmetinizdeyiz"
    maps_url = str(lead.get("google_maps_url") or "#")
    if not maps_url.startswith(("http://", "https://")):
        maps_url = "#"
    delivery = lead.get("delivery_platforms") or []
    accent, accent_dark, icon = _theme_for_category(btype)
    wa_href = _wa_link(phone, name)
    tel_digits = re.sub(r"\D", "", phone)
    tel_href = f"tel:+{tel_digits}" if tel_digits else "#"

    rating_badge = (
        f'<span class="badge">⭐ {_esc(rating)} / 5 ({_esc(reviews_count or 0)} Google yorumu)</span>'
        if rating is not None else f'<span class="badge">{icon} {_esc(btype)}</span>'
    )
    delivery_note = (
        f"Şu anda <strong>{_esc(', '.join(delivery))}</strong> üzerinden de hizmet veriyorsunuz — "
        "bu özel site ile müşterilerinizden <strong>%0 komisyonla</strong> doğrudan sipariş alabilirsiniz."
        if delivery else
        "Müşterileriniz Google'da sizi aradığında tek tıkla menünüze, konumunuza ve WhatsApp sipariş hattınıza ulaşır."
    )

    return f"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(name)} — Resmi Web Sitesi Taslağı</title>
<style>
:root{{--accent:{accent};--accent2:{accent_dark};--bg:#0b1120;--card:#111827;--ink:#f8fafc;--muted:#94a3b8;--line:#1e293b}}
*{{box-sizing:border-box}}body{{margin:0;font-family:Inter,system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--ink);line-height:1.6}}
.banner{{background:linear-gradient(90deg,var(--accent2),var(--accent));color:#fff;text-align:center;padding:10px 16px;font-size:13px;font-weight:600}}
.wrap{{max-width:1040px;margin:0 auto;padding:24px 20px 64px}}
.hero{{background:radial-gradient(circle at top right,color-mix(in srgb,var(--accent) 28%,transparent),transparent 55%),var(--card);border:1px solid var(--line);border-radius:24px;padding:48px 36px;margin-top:16px;box-shadow:0 24px 60px #0006}}
.badge{{display:inline-flex;align-items:center;gap:6px;background:#ffffff14;border:1px solid #ffffff22;padding:6px 14px;border-radius:999px;font-size:13px;font-weight:600;margin-bottom:18px}}
h1{{margin:0 0 14px;font-size:clamp(30px,5vw,48px);line-height:1.12;letter-spacing:-1px}}
.lead{{color:var(--muted);font-size:17px;max-width:660px;margin:0 0 28px}}
.cta{{display:flex;flex-wrap:wrap;gap:12px}}
.btn{{display:inline-flex;align-items:center;gap:8px;padding:13px 22px;border-radius:12px;text-decoration:none;font-weight:700;font-size:15px;border:1px solid var(--line);color:#fff;background:#1e293b}}
.btn.primary{{background:var(--accent);border-color:var(--accent)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;margin-top:24px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:24px}}
.card h3{{margin:0 0 10px;font-size:16px}}
.card p{{margin:0;color:var(--muted);font-size:14px}}
.promo{{margin-top:24px;padding:22px 24px;border-radius:18px;background:color-mix(in srgb,var(--accent) 12%,var(--card));border:1px solid color-mix(in srgb,var(--accent) 40%,var(--line));font-size:14px}}
footer{{text-align:center;color:var(--muted);font-size:12px;margin-top:40px}}
</style>
</head>
<body>
<div class="banner">✨ HK Yazılım Canlı Ön Taslak · {_esc(name)} için özel oluşturuldu</div>
<div class="wrap">
  <section class="hero">
    {rating_badge}
    <h1>{icon} {_esc(name)}</h1>
    <p class="lead">{_esc(district + ' bölgesinde ' if district else '')}kaliteli {_esc(btype.lower())} deneyimi. Hızlı iletişim, güncel menü ve komisyonsuz doğrudan sipariş hattı tek sayfada.</p>
    <div class="cta">
      <a class="btn primary" href="{_esc(wa_href)}" target="_blank" rel="noopener noreferrer">💬 WhatsApp’tan Sipariş / İletişim</a>
      <a class="btn" href="{_esc(tel_href)}">☎ Hemen Ara ({_esc(phone or 'Telefon')})</a>
      <a class="btn" href="{_esc(maps_url)}" target="_blank" rel="noopener noreferrer">📍 Google Maps Yol Tarifi</a>
    </div>
  </section>
  <div class="promo">💡 {delivery_note}</div>
  <section class="grid">
    <div class="card"><h3>📍 Adres & Konum</h3><p>{_esc(address)}</p></div>
    <div class="card"><h3>🕒 Çalışma Saatleri</h3><p>{_esc(hours_text)}</p></div>
    <div class="card"><h3>📱 Mobil & SEO Uyumlu</h3><p>Google aramalarında üst sıralara uygun, 1 saniyenin altında açılan SSL korumalı modern vitrin.</p></div>
  </section>
  <footer>Bu önizleme <strong>HK LeadOS</strong> tarafından {_esc(name)} için hazırlanmıştır.</footer>
</div>
</body>
</html>"""
