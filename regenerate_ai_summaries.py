"""Replace every stored lead summary with a fresh isolated Gemini Worker summary."""
from lead_system.store import LeadStore
from website_ai_worker import summarize_lead


def main() -> None:
    store = LeadStore()
    leads = store.list()
    for lead in leads:
        store.update(lead["lead_id"], ai_summary="", ai_summary_source="pending_gemini_worker")
    completed = 0
    for lead in leads:
        current = store.get(lead["lead_id"])
        summary = summarize_lead(current)
        store.update(lead["lead_id"], ai_summary=summary or "AI özeti üretilemedi; kanıtlar manuel inceleme bekliyor.", ai_summary_source="gemini_worker_maps_instagram")
        completed += 1
        print(f"{completed}/{len(leads)} {lead.get('business_name', 'İşletme')}", flush=True)
    print(f"Tamamlandı: {completed} işletmenin özeti güncel Gemini Worker ile yenilendi.")


if __name__ == "__main__":
    main()
