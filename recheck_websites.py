"""Recheck stored business websites without running a new Maps scan."""
from lead_automation import check_website
from lead_system.scoring import score_lead
from lead_system.store import LeadStore, canonical_url, is_directory_url, is_social_url
from website_ai_worker import audit_leads, summarize_lead
import argparse
import os
from lead_automation import discover_google_sites
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Kayıtlı işletmelerin resmi sitelerini yeniden denetle")
    parser.add_argument("--remove-live", action="store_true", help="HTTP/içerik kontrolünden geçen resmi web siteli adayları kaldır")
    parser.add_argument("--google-search", action="store_true", help="Maps'te sitesi olmayan adayları Apify Google sonuçlarında da ara")
    args = parser.parse_args()
    store = LeadStore()
    runs = sorted((Path("lead_runs")).glob("*/places.json"), reverse=True)
    if runs:
        places = json.loads(runs[0].read_text(encoding="utf-8"))
        profiles_path = runs[0].parent / "instagram.json"
        profiles = json.loads(profiles_path.read_text(encoding="utf-8")) if profiles_path.exists() else []
        for lead in store.list():
            place_id = str(lead.get("lead_id", "")).removeprefix("place-")
            place = next((p for p in places if str(p.get("placeId")) == place_id), None)
            profile = next((p for p in profiles if canonical_url(p.get("url") or p.get("inputUrl")) == canonical_url(lead.get("instagram_url"))), None)
            changes = {}
            if place:
                details = dict(lead.get("source_details") or {})
                details.update({"description": place.get("description") or details.get("description", ""), "reviews": (place.get("reviews") or details.get("reviews") or [])[:10]})
                changes["source_details"] = details
            if profile:
                posts = profile.get("latestPosts") or profile.get("latestIgtvVideos") or []
                changes.update({"instagram_status": "active" if posts else "profile_found", "instagram_evidence": {"username": profile.get("username"), "biography": str(profile.get("biography") or "")[:1000], "followers": profile.get("followersCount"), "posts_count": profile.get("postsCount"), "latest_posts": [{"caption": str(p.get("caption") or "")[:800], "likes": p.get("likesCount"), "timestamp": p.get("timestamp")} for p in posts[:5]]}})
            if changes:
                store.update(lead["lead_id"], **changes)
    if args.google_search:
        token = os.environ.get("APIFY_API_TOKEN", "").strip()
        if not token:
            raise SystemExit("APIFY_API_TOKEN gerekli")
        original = store.list()
        records = [{"lead_id": lead["lead_id"], "title": lead.get("business_name"), "address": lead.get("address"), "district": lead.get("district"), "website": lead.get("website_url") or ""} for lead in original]
        remaining, checks, found_live, findings = discover_google_sites(records, token, lambda _p, text: print(text, flush=True))
        remaining_ids = {item["lead_id"] for item in remaining}
        for lead in original:
            if lead["lead_id"] not in remaining_ids:
                store.remove(lead["lead_id"])
        for item in remaining:
            website = str(item.get("website") or "")
            check = checks.get(website.rstrip("/").lower()) if website else None
            if check:
                store.update(item["lead_id"], website_url=website, website_status=check.get("status"), website_findings=check.get("findings") or [], website_check=check, website_discovery_source="apify_google_search")
        print(f"Apify Google sonuçlarında çalışan resmi sitesi bulunan {found_live} aday kaldırıldı.")

    checked = 0
    removed = 0
    for lead in store.list():
        url = str(lead.get("website_url") or "").strip()
        if is_social_url(url):
            lead = store.update(lead["lead_id"], website_url="", instagram_url=url if "instagram.com" in url.lower() else lead.get("instagram_url", ""), website_status="missing", website_findings=["Sosyal medya hesabı web sitesi olarak sayılmadı."])
            url = ""
        if is_directory_url(url):
            lead = store.update(lead["lead_id"], website_url="", directory_url=url, website_status="missing", website_findings=["Firma rehberi/dizin bağlantısı; işletmenin kendi web sitesi değildir."])
            url = ""
        if not url:
            updated = store.update(lead["lead_id"], website_status="missing", website_findings=lead.get("website_findings") or ["Web sitesi URL'si bulunamadı."])
            decision = score_lead(updated)
            store.update(lead["lead_id"], **decision, ai_summary=f"{updated.get('business_name', 'İşletme')} için otomatik ön değerlendirme: {decision['decision_reasons'][0]} Teklif seviyesi: {decision['decision']}.")
            continue
        result = check_website(url)
        if args.remove_live and result.get("status") == "live":
            store.remove(lead["lead_id"])
            removed += 1
            checked += 1
            continue
        updates = {"website_status": result["status"], "website_findings": result["findings"], "website_check": result}
        if result.get("final_url") and str(result["final_url"]).lower().startswith("https://"):
            updates["website_url"] = result["final_url"]
        updated = store.update(lead["lead_id"], **updates)
        decision = score_lead(updated)
        store.update(lead["lead_id"], **decision, ai_summary=f"{updated.get('business_name', 'İşletme')} için otomatik ön değerlendirme: {decision['decision_reasons'][0]} Teklif seviyesi: {decision['decision']}.")
        checked += 1
    if args.remove_live:
        print(f"{checked} web adresi kontrol edildi; çalışan resmi sitesi olan {removed} aday kaldırıldı.")
        return
    candidates = store.list()
    results, raw = audit_leads(candidates, workers=1)
    recheck_out = store.db_path.parent.parent.parent / "lead_runs" / "website_ai_recheck.md"
    recheck_out.parent.mkdir(parents=True, exist_ok=True)
    recheck_out.write_text(raw, encoding="utf-8")
    for item in results:
        lead_id = item.get("lead_id")
        if not lead_id:
            continue
        changes = {"ai_summary": str(item.get("summary") or "")[:2000], "ai_confidence": str(item.get("confidence") or "")[:100], "ai_evidence": item.get("reasons") if isinstance(item.get("reasons"), list) else []}
        if item.get("decision") in {"ÖNER", "İNCELE", "ELE"}:
            changes["decision"] = item["decision"]
        if isinstance(item.get("score"), (int, float)):
            changes["ai_score"] = max(0, min(100, int(item["score"])))
        if isinstance(item.get("reasons"), list) and item["reasons"]:
            changes["decision_reasons"] = [str(x)[:500] for x in item["reasons"][:8]]
        store.update(lead_id, **changes)
    for lead in store.list():
        if lead.get("website_status") in {"missing", "broken", "poor"} or lead.get("instagram_evidence"):
            summary = summarize_lead(store.get(lead["lead_id"]))
            if summary:
                store.update(lead["lead_id"], ai_summary=summary, ai_summary_source="gemini_worker_maps_instagram")
    print(f"{checked} web adresi gerçek HTTP ile kontrol edildi.")


if __name__ == "__main__":
    main()
