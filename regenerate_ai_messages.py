"""Regenerate WhatsApp drafts with an isolated Gemini worker per eligible lead."""
from __future__ import annotations

from lead_system.store import LeadStore
from website_ai_worker import generate_message


store = LeadStore()
completed = 0
skipped = 0
for lead in store.list():
    if not lead.get("phone") or lead.get("decision") == "ELE" or lead.get("opt_out_status"):
        skipped += 1
        continue
    message = generate_message(lead)
    if message:
        try:
            store.update(lead["lead_id"], message_draft=message, message_source="gemini_worker_business_specific")
            completed += 1
            print(f"OK {lead.get('business_name', lead['lead_id'])}", flush=True)
        except KeyError:
            print(f"SKIP {lead.get('business_name', lead['lead_id'])}: kayıt artık mevcut değil", flush=True)
    else:
        print(f"SKIP {lead.get('business_name', lead['lead_id'])}: worker mesaj üretmedi", flush=True)
print(f"Tamamlandı: {completed} mesaj yenilendi; {skipped} aday güvenlik/iletişim koşulları nedeniyle atlandı.")
