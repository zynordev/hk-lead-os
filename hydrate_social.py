import json
from pathlib import Path
from lead_system.store import LeadStore, canonical_url
from website_ai_worker import summarize_lead

store = LeadStore()
runs = sorted(Path('lead_runs').glob('*/instagram.json'), reverse=True)
if runs:
    profiles = json.loads(runs[0].read_text(encoding='utf-8'))
    for lead in store.list():
        profile = next((p for p in profiles if canonical_url(p.get('url') or p.get('inputUrl')) == canonical_url(lead.get('instagram_url'))), None)
        if not profile:
            continue
        posts = profile.get('latestPosts') or profile.get('latestIgtvVideos') or []
        store.update(lead['lead_id'], instagram_status='active' if posts else 'profile_found', instagram_activity_summary=f"{profile.get('postsCount') or 0} gönderi, {profile.get('followersCount') or 0} takipçi; son içerikler Gemini analizine aktarıldı.", instagram_evidence={'username': profile.get('username'), 'biography': str(profile.get('biography') or '')[:1000], 'followers': profile.get('followersCount'), 'posts_count': profile.get('postsCount'), 'latest_posts': [{'caption': str(p.get('caption') or '')[:800], 'likes': p.get('likesCount'), 'timestamp': p.get('timestamp')} for p in posts[:5]]})
        summary = summarize_lead(store.get(lead['lead_id']))
        if summary:
            store.update(lead['lead_id'], ai_summary=summary, ai_summary_source='gemini_worker_maps_instagram')
print('Instagram profilleri ve AI özetleri güncellendi.')
