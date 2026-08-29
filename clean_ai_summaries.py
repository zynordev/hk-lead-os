"""Normalize stored Gemini envelopes into concise dashboard summaries."""
from lead_system.store import LeadStore
from website_ai_worker import _clean_summary


def main() -> None:
    store = LeadStore()
    for lead in store.list():
        raw = str(lead.get("ai_summary") or "")
        if raw.startswith("###") or "HK-Agents Multi-Agent Execution Summary" in raw or "Research analysis completed" in raw or "strictly examining" in raw:
            store.update(lead["lead_id"], ai_summary=_clean_summary(raw, lead), ai_summary_source="gemini_worker_maps_instagram")
    print("AI özetleri temiz kullanıcı formatına dönüştürüldü.")


if __name__ == "__main__":
    main()
