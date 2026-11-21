from __future__ import annotations

from typing import Any
from .store import is_directory_url, is_social_url


def score_lead(lead: dict[str, Any]) -> dict[str, Any]:
    """Deterministic safety fallback; AI may enrich but cannot bypass these rules."""
    score = 35
    reasons: list[str] = []
    if not lead.get("website_url") or is_social_url(lead.get("website_url")) or is_directory_url(lead.get("website_url")):
        score += 35
        reasons.append("Web sitesi bulunamadı.")
    elif lead.get("website_status") == "redesign":
        score += 22
        findings = "; ".join(lead.get("website_findings") or [])
        reasons.append(findings or "Mevcut web sitesi mobil uyumsuz / SSL eksik / yavaş; yeniden tasarım fırsatı.")
    elif lead.get("website_status") in {"broken", "insecure", "poor"}:
        score += 25
        reasons.append("Mevcut web sitesinde kalite/erişilebilirlik sorunu var.")
    else:
        score -= 15
        reasons.append("Mevcut web sitesi bulundu; yeniden tasarım/SEO ayrıca incelenmeli.")
    if lead.get("instagram_status") == "active":
        score += 15
        reasons.append("Instagram aktif görünüyor.")
    delivery = lead.get("delivery_platforms") or []
    if delivery and (not lead.get("website_url") or lead.get("website_status") in {"missing", "broken", "poor"}):
        score += 12
        reasons.append(f"Komisyonlu sipariş platformlarında aktif ({', '.join(delivery[:3])}); kendi komisyonsuz online sipariş sitesi için yüksek fırsat.")
    elif lead.get("online_platforms"):
        reasons.append(f"Web aramasında bulunan kanallar: {', '.join(lead['online_platforms'][:5])}.")
    if not lead.get("phone"):
        score -= 25
        reasons.append("Doğrulanabilir telefon numarası yok.")
    if lead.get("opt_out_status"):
        return {"ai_score": 0, "decision": "ELE", "decision_reasons": ["Opt-out kaydı mevcut."], "risk_flags": ["opt_out"]}
    score = max(0, min(100, score))
    decision = "ÖNER" if score >= 65 else "İNCELE" if score >= 40 else "ELE"
    return {"ai_score": score, "decision": decision, "decision_reasons": reasons, "risk_flags": []}
