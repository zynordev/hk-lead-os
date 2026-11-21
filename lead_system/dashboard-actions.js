(() => {
  'use strict';

  const state = { leads: [], scans: { active: {}, history: [] }, selected: null, toastTimer: null, dragId: null };
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const CRM_COLUMNS = [
    ['new', '🆕 Yeni'],
    ['reviewed', '✓ Onaylandı'],
    ['contacted', '↗ Mesaj Atıldı'],
    ['negotiating', '💬 Görüşülüyor'],
    ['won', '🏆 Satış'],
  ];

  // Theme initialization
  const savedTheme = localStorage.getItem('leados_theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  document.documentElement.dataset.theme = savedTheme;
  function toggleTheme() {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    localStorage.setItem('leados_theme', next);
  }

  async function request(path, options = {}) {
    const response = await fetch(path, { cache: 'no-store', ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } });
    const raw = await response.text();
    let data = {};
    try { data = raw ? JSON.parse(raw) : {}; }
    catch { throw new Error(response.status >= 500 ? 'Sunucu geçici olarak erişilemiyor. Lütfen tekrar deneyin.' : `Sunucudan geçersiz yanıt geldi (${response.status}).`); }
    if (!response.ok) throw new Error(data.error || `İşlem başarısız (${response.status})`);
    return data;
  }
  const get = (path) => request(path, { headers: {} });
  const post = (path, body) => request(path, { method: 'POST', body: JSON.stringify(body) });

  function toast(message, error = false) {
    const node = $('toast');
    node.textContent = message;
    node.classList.toggle('error', error);
    node.classList.add('show');
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => node.classList.remove('show'), 4500);
  }
  function pill(value) {
    const kind = value === 'ÖNER' || value === 'sent' || value === 'Gönderildi' || value === 'completed' ? 'green'
      : value === 'ELE' || value === 'skipped' || value === 'failed' ? 'red'
      : value === 'redesign' ? 'purple' : 'amber';
    const labels = { needs_review: 'Onay bekliyor', approved: 'Onaylandı', sent: 'Gönderildi', failed: 'Gönderim sorunu', skipped: 'Atlandı', redesign: 'Yeniden Tasarım' };
    return `<span class="pill ${kind}">${esc(labels[value] || value || 'İNCELE')}</span>`;
  }
  function mobilePhone(value) { let digits = String(value || '').replace(/\D/g, ''); if (digits.startsWith('90') && digits.length === 12) digits = digits.slice(2); return digits.length === 10 && digits.startsWith('5'); }
  function dialNumber(value) { const digits = String(value || '').replace(/\D/g, ''); return digits ? `tel:+${digits.startsWith('90') ? digits : `90${digits}`}` : ''; }
  function safeHref(value) { try { const parsed = new URL(String(value || '')); return ['http:', 'https:'].includes(parsed.protocol) ? parsed.href : ''; } catch { return ''; } }
  function platformBadges(lead) {
    const delivery = new Set(lead.delivery_platforms || []);
    const items = (lead.online_platforms || []).slice(0, 6);
    return items.map((name) => `<span class="pill ${delivery.has(name) ? 'amber' : ''}">${esc(name)}</span>`).join('');
  }
  function detailButton(id, label = 'Detay') { return `<button class="btn" data-action="detail" data-id="${esc(id)}">${label}</button>`; }
  function demoButton(id) { return `<a class="btn demo" href="/preview/${encodeURIComponent(id)}" target="_blank" rel="noopener noreferrer">🎨 Demo Site</a>`; }

  function leadCard(lead, sent = false) {
    const status = lead.approval_status || 'needs_review';
    const call = !mobilePhone(lead.phone) && lead.phone ? `<a class="btn" href="${dialNumber(lead.phone)}">☎ Ara</a>` : '';
    const actions = sent
      ? `${detailButton(lead.lead_id, 'Detayı aç')}${demoButton(lead.lead_id)}`
      : `${detailButton(lead.lead_id, mobilePhone(lead.phone) ? 'Detay / mesaj' : 'Detay / ara')}${demoButton(lead.lead_id)}${mobilePhone(lead.phone) ? `<button class="btn primary" data-action="approve" data-id="${esc(lead.lead_id)}">${status === 'approved' ? '✓ Onaylandı' : status === 'failed' ? '↻ Yeniden onayla' : '✓ Onayla'}</button>` : call}<button class="btn" data-action="skip" data-id="${esc(lead.lead_id)}">Atla</button><button class="btn danger" data-action="opt-out" data-id="${esc(lead.lead_id)}">Opt-out</button>`;
    const badges = platformBadges(lead);
    const redesignBadge = lead.website_status === 'redesign' ? pill('redesign') : '';
    return `<article class="lead"><div class="lead-top"><span class="lead-name">${esc(lead.business_name || 'İsimsiz işletme')}</span>${pill(lead.business_type || 'işletme')}${pill(lead.decision)}${redesignBadge}${status === 'failed' ? pill('failed') : ''}${status === 'skipped' ? pill('skipped') : ''}<strong class="score">${lead.ai_score ?? '—'}</strong></div><div class="meta">${esc(lead.district || lead.address || 'Adres yok')} · ${esc(lead.phone || 'Telefon yok')}</div>${badges ? `<div class="lead-top" style="margin:6px 0">${badges}</div>` : ''}<div class="reason">${esc((lead.decision_reasons || []).join(' ') || lead.send_error || 'Analiz gerekçesi bulunmuyor.')}</div><div class="lead-actions">${actions}</div></article>`;
  }

  function activeLeads() { return state.leads.filter((lead) => !['sent', 'skipped'].includes(lead.approval_status)); }
  function sentLeads() { return state.leads.filter((lead) => lead.approval_status === 'sent' || lead.send_status === 'sent'); }

  function renderLeads() {
    const term = $('search').value.trim().toLocaleLowerCase('tr');
    const decision = $('decision').value;
    const approval = $('approval').value;
    const pool = approval === 'skipped' ? state.leads.filter((lead) => lead.approval_status === 'skipped') : activeLeads();
    const list = pool.filter((lead) => (!term || JSON.stringify(lead).toLocaleLowerCase('tr').includes(term)) && (!decision || lead.decision === decision) && (!approval || lead.approval_status === approval));
    $('lead-count').textContent = `${list.length} aday`;
    $('all-leads').innerHTML = list.length ? list.map((lead) => leadCard(lead)).join('') : '<div class="empty">Filtreye uygun aktif aday yok.</div>';
    const sent = sentLeads();
    $('sent-count').textContent = `${sent.length} mesaj`;
    $('sent-leads').innerHTML = sent.length ? sent.map((lead) => leadCard(lead, true)).join('') : '<div class="empty">Henüz doğrulanmış gönderim yok.</div>';
    const priority = activeLeads().filter((lead) => lead.decision === 'ÖNER' || lead.approval_status === 'needs_review').sort((a, b) => (b.ai_score || 0) - (a.ai_score || 0)).slice(0, 4);
    $('priority').innerHTML = priority.length ? priority.map((lead) => leadCard(lead)).join('') : '<div class="empty">Öncelikli aday yok.</div>';
  }

  function renderKanban() {
    const board = $('kanban-board');
    if (!board) return;
    const visible = state.leads.filter((l) => l.approval_status !== 'skipped');
    board.innerHTML = CRM_COLUMNS.map(([stage, title], idx) => {
      const items = visible.filter((l) => (l.crm_stage || 'new') === stage);
      const nextStage = CRM_COLUMNS[idx + 1]?.[0];
      const cards = items.map((l) => `
        <div class="k-card" draggable="true" data-lead-id="${esc(l.lead_id)}">
          <strong>${esc(l.business_name || 'İsimsiz')}</strong>
          <div class="meta">${esc(l.district || l.business_type || '')} · Skor ${l.ai_score ?? '—'}</div>
          <div class="k-card-actions">
            <button class="btn" data-action="detail" data-id="${esc(l.lead_id)}">Detay</button>
            <a class="btn demo" href="/preview/${encodeURIComponent(l.lead_id)}" target="_blank" rel="noopener noreferrer">🎨</a>
            ${nextStage ? `<button class="btn primary" data-action="move-stage" data-id="${esc(l.lead_id)}" data-stage="${nextStage}">→ İleri</button>` : ''}
          </div>
        </div>`).join('');
      return `<div class="kanban-col" data-stage="${stage}"><div class="kanban-head"><span>${title}</span><span class="pill">${items.length}</span></div>${cards || '<div class="empty" style="padding:18px 6px">Boş</div>'}</div>`;
    }).join('');
  }

  function renderStats(stats, health) {
    $('m-total').textContent = stats.total ?? 0; $('m-rec').textContent = stats.recommended ?? 0; $('m-pending').textContent = stats.pending ?? 0; $('m-sent').textContent = stats.sent ?? 0; $('m-replies').textContent = stats.replies ?? 0;
    $('system-text').textContent = `${health.leads ?? 0} aday · ${health.storage || 'sqlite'} · ${health.wacli_configured ? 'wacli aktif' : 'manuel onay'}`;
    const values = [['ÖNER', stats.recommended || 0, 'var(--green)'], ['İNCELE', stats.review || 0, 'var(--amber)'], ['ELE', stats.rejected || 0, 'var(--red)']];
    const max = Math.max(1, ...values.map((value) => value[1]));
    $('bars').innerHTML = values.map(([label, count, color]) => `<div class="bar-row"><span>${label}</span><div class="bar"><i style="width:${count / max * 100}%;background:${color}"></i></div><strong>${count}</strong></div>`).join('');
  }

  function renderScans() {
    const history = state.scans.history || [];
    $('scan-history').innerHTML = history.length ? history.map((item) => `<div class="history-item" data-action="scan-detail" data-id="${esc(item.scan_id)}"><strong>${esc(item.query)} · ${pill(item.status)}</strong><small>${esc(item.started_at || '')} · limit ${item.limit || '—'}</small></div>`).join('') : '<div class="empty">Henüz scan yok.</div>';
    const active = state.scans.active || {};
    const logs = (active.logs || []).slice(-8).reverse().map((item) => `<div class="meta">${esc(item.text || '')}</div>`).join('');
    $('active-scan').innerHTML = ['running', 'stopping'].includes(active.status) ? `<div class="scan-progress"><strong>${esc(active.stage || active.status)} · ${Number(active.progress || 0)}%</strong><i style="width:${Math.max(0, Math.min(100, Number(active.progress || 0)))}%"></i><span class="meta">${esc(active.query || '')}<br>${esc(active.last_event || '')}</span></div><div style="margin-top:12px;padding:10px;border:1px solid var(--line);border-radius:9px;max-height:210px;overflow:auto"><strong>Canlı işlem günlüğü</strong>${logs || '<div class="meta">İşlem günlüğü bekleniyor…</div>'}</div><button class="btn danger" data-action="stop-scan" style="margin-top:12px">Taramayı durdur</button>` : '<div class="empty">Aktif tarama yok.</div>';
  }

  function renderReplies(replies) {
    $('reply-count').textContent = `${replies.length} kayıt`;
    $('reply-list').innerHTML = replies.length ? replies.map((item) => `<div class="reply"><strong>${esc(item.business_name || item.lead_id)} ${pill(item.status)}</strong><small>${esc(item.received_at || '')}</small><p>${esc(item.message || '')}</p></div>`).join('') : '<div class="empty">Henüz geri dönüş kaydı yok.</div>';
  }

  function renderSettings(health) {
    $('settings-body').innerHTML = `
      <p><span class="dot"></span>Dashboard API aktif · Depolama: <strong>${esc(health.storage || 'sqlite').toUpperCase()}</strong></p>
      <p>WhatsApp Gönderim Hattı: <strong>${health.wacli_configured ? 'Raspberry Pi wacli köprüsü aktif' : 'Yerel Baileys köprüsü (port 8787 · manuel onaylı)'}</strong></p>
      <p>Google Sheets: <strong>${health.sheets_configured ? 'Bağlı' : 'Yapılandırılmadı'}</strong></p>
      <div class="top-actions" style="margin-top:14px">
        <button class="btn primary" data-action="sheets">Google Sheets’e bağlan</button>
        <a class="btn" href="/api/export.csv" download="hk-leados-leads.csv">📥 Tüm Adayları CSV İndir</a>
      </div>`;
  }

  async function refresh() {
    try {
      const [stats, leads, scans, replies, health] = await Promise.all([get('/api/stats'), get('/api/leads'), get('/api/scans'), get('/api/replies'), get('/api/health')]);
      state.leads = leads; state.scans = scans;
      renderStats(stats, health); renderLeads(); renderKanban(); renderScans(); renderReplies(replies); renderSettings(health);
      if (state.selected) { const updated = state.leads.find((lead) => lead.lead_id === state.selected.lead_id); if (updated) state.selected = updated; }
    } catch (error) { toast(error.message || 'Dashboard verisi alınamadı.', true); }
  }

  function showView(view) {
    document.querySelectorAll('.view').forEach((node) => node.classList.toggle('active', node.id === view));
    document.querySelectorAll('.nav button').forEach((node) => node.classList.toggle('active', node.dataset.view === view));
    $('page-title').textContent = ({ overview: 'Genel Bakış', leads: 'İşletmeler', kanban: 'CRM Kanban', sent: 'Gönderilenler', scans: 'Scan geçmişi', replies: 'Geri dönüşler', settings: 'Ayarlar' })[view] || 'LeadOS';
    closeSidebar();
  }
  function openModal(id) { $(id).classList.add('open'); $(id).setAttribute('aria-hidden', 'false'); }
  function closeModal(id) { $(id).classList.remove('open'); $(id).setAttribute('aria-hidden', 'true'); }

  function openDetail(id) {
    const lead = state.leads.find((item) => item.lead_id === id); if (!lead) return;
    state.selected = lead;
    const details = lead.source_details || {};
    const adLib = lead.ad_library_url || `https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=TR&q=${encodeURIComponent(lead.business_name || '')}`;
    const platformEntries = Object.entries(lead.platform_links || {});
    const linkPairs = [['Web sitesi', lead.website_url], ['Instagram', lead.instagram_url], ['Google Maps', lead.google_maps_url], ['📣 Meta Reklam Kütüphanesi', adLib], ...platformEntries];
    const seenHref = new Set();
    const links = linkPairs
      .map(([label, url]) => [label, safeHref(url)])
      .filter(([, href]) => href && !seenHref.has(href) && seenHref.add(href))
      .map(([label, href]) => `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>`)
      .join(' · ') || 'Bağlantı bulunamadı.';
    const platformsHtml = platformBadges(lead) || '<span class="meta">Web aramasında platform kaydı bulunamadı.</span>';
    const wc = lead.website_check || {};
    const techNote = wc.response_time_ms != null
      ? `<p class="meta">Teknik Denetim: ${wc.has_ssl ? '🔒 HTTPS' : '⚠️ SSL Yok'} · ${wc.has_mobile_viewport ? '📱 Mobil Uyumlu' : '⚠️ Mobil Uyumsuz'} · ⏱ ${wc.response_time_ms} ms</p>`
      : '';
    $('detail-title').textContent = lead.business_name || 'İşletme detayı';
    $('detail-demo-btn').href = `/preview/${encodeURIComponent(lead.lead_id)}`;
    const landline = !mobilePhone(lead.phone) && lead.phone;
    $('detail-body').innerHTML = `<div class="notice ${lead.send_error ? 'error' : ''}" style="display:${lead.send_error ? 'block' : 'none'}">${esc(lead.send_error || '')}</div><div class="detail-grid"><div class="detail-block full"><h3>AI özeti</h3><p>${esc(lead.ai_summary || (lead.decision_reasons || []).join(' ') || 'Özet henüz hazır değil.')}</p>${techNote}</div><div class="detail-block"><h3>Karar ve fırsat</h3><p>${pill(lead.decision)} ${lead.website_status === 'redesign' ? pill('redesign') : ''} · Skor: <strong>${lead.ai_score ?? '—'}/100</strong></p><p>${esc((lead.decision_reasons || []).join(' ') || 'Gerekçe yok')}</p></div><div class="detail-block"><h3>İletişim</h3><p>${esc(lead.phone || 'Telefon yok')}</p><p>${esc(lead.address || 'Adres yok')}</p>${landline ? `<p><a class="btn primary" href="${dialNumber(lead.phone)}">☎ Bu işletmeyi ara</a></p>` : ''}</div><div class="detail-block"><h3>Maps bilgileri</h3><p>Puan: ${esc(details.rating ?? '—')} · Yorum: ${esc(details.reviews_count ?? '—')}</p><p>${esc((details.categories || []).join(', ') || 'Kategori yok')}</p></div><div class="detail-block"><h3>Dijital varlıklar & Platformlar</h3><p>${links}</p><div class="lead-top" style="margin-top:8px">${platformsHtml}</div></div>${landline ? '<div class="detail-block full"><h3>İletişim yöntemi</h3><p>Bu numara yerel sabit hat olarak algılandı. WhatsApp mesajı hazırlanmıyor; telefondan arayarak iletişime geçebilirsin.</p></div>' : `<div class="detail-block full"><h3>Teklif mesajı</h3><textarea id="detail-message" class="textarea">${esc(lead.message_draft || '')}</textarea></div>`}</div>`;
    const sent = lead.approval_status === 'sent' || lead.send_status === 'sent';
    $('approve-save-btn').hidden = sent || landline; $('send-btn').hidden = lead.approval_status !== 'approved' || landline;
    openModal('detail-modal');
  }

  async function saveApproval() {
    const lead = state.selected; if (!lead) return;
    const button = $('approve-save-btn'); button.disabled = true; button.textContent = 'Kaydediliyor…';
    try { await post('/api/approve', { lead_id: lead.lead_id, message: $('detail-message').value }); toast('Onay kaydedildi. Mesaj göndermeye hazır.'); closeModal('detail-modal'); await refresh(); }
    catch (error) { toast(error.message || 'Onay kaydedilemedi.', true); }
    finally { button.disabled = false; button.textContent = '✓ Onayla ve kaydet'; }
  }
  async function sendMessage() {
    const lead = state.selected; if (!lead) return;
    const button = $('send-btn'); button.disabled = true; button.textContent = 'Gönderiliyor…';
    try { await post('/api/send', { lead_id: lead.lead_id }); toast('Mesaj WhatsApp onayıyla gönderildi.'); closeModal('detail-modal'); await refresh(); }
    catch (error) { toast(error.message || 'Mesaj gönderilemedi.', true); await refresh(); }
    finally { button.disabled = false; button.textContent = '↗ Mesaj gönder'; }
  }
  async function moveStage(id, stage) {
    try { await post('/api/crm-stage', { lead_id: id, stage }); toast('CRM aşaması güncellendi.'); await refresh(); }
    catch (error) { toast(error.message, true); }
  }
  async function act(action, id) { try { await post(`/api/${action}`, { lead_id: id }); toast(action === 'opt-out' ? 'İşletme opt-out listesine alındı.' : 'İşletme atlandı.'); await refresh(); } catch (error) { toast(error.message, true); } }
  async function showScanLeads(scanId) { try { const rows = await get(`/api/scans/${encodeURIComponent(scanId)}/leads`); $('scan-leads-detail').innerHTML = rows.length ? `<h3>Bu scan’den gelen işletmeler</h3>${rows.map((lead) => leadCard(lead)).join('')}` : '<div class="empty">Bu scan’de aktif işletme yok.</div>'; } catch (error) { toast(error.message, true); } }
  async function startScan() { const button = $('start-scan-btn'); button.disabled = true; try { await post('/api/scan/start', { query: $('scan-query').value, limit: Number($('scan-limit').value), workers: 5, concurrency: 2 }); closeModal('scan-modal'); showView('scans'); toast('Scan başlatıldı. İlerleme anlık güncelleniyor.'); await refresh(); } catch (error) { toast(error.message, true); } finally { button.disabled = false; } }
  async function stopScan() { try { await post('/api/scan/stop', {}); toast('Tarama durduruluyor.'); await refresh(); } catch (error) { toast(error.message, true); } }
  function openSidebar() { $('sidebar').classList.add('open'); $('sidebar-backdrop').classList.add('open'); }
  function closeSidebar() { $('sidebar').classList.remove('open'); $('sidebar-backdrop').classList.remove('open'); }

  // Drag & drop for CRM Kanban
  document.addEventListener('dragstart', (e) => { const card = e.target.closest('.k-card'); if (card) state.dragId = card.dataset.leadId; });
  document.addEventListener('dragover', (e) => { const col = e.target.closest('.kanban-col'); if (col && state.dragId) { e.preventDefault(); col.classList.add('drag-over'); } });
  document.addEventListener('dragleave', (e) => { const col = e.target.closest('.kanban-col'); if (col) col.classList.remove('drag-over'); });
  document.addEventListener('drop', (e) => {
    const col = e.target.closest('.kanban-col');
    if (col && state.dragId) { e.preventDefault(); col.classList.remove('drag-over'); const id = state.dragId; state.dragId = null; moveStage(id, col.dataset.stage); }
  });

  document.addEventListener('click', (event) => {
    const target = event.target.closest('[data-action]');
    if (!target) { if (event.target.id === 'detail-modal') closeModal('detail-modal'); if (event.target.id === 'scan-modal') closeModal('scan-modal'); return; }
    const { action, id, stage } = target.dataset;
    if (action === 'detail' || action === 'approve') openDetail(id);
    else if (action === 'move-stage') moveStage(id, stage);
    else if (action === 'skip' || action === 'opt-out') act(action, id);
    else if (action === 'scan-detail') showScanLeads(id);
    else if (action === 'stop-scan') stopScan();
    else if (action === 'close-detail') closeModal('detail-modal');
    else if (action === 'close-scan') closeModal('scan-modal');
    else if (action === 'scan') openModal('scan-modal');
    else if (action === 'view-leads') showView('leads');
    else if (action === 'sheets') location.href = '/api/sheets/connect';
  });
  document.querySelectorAll('.nav button').forEach((button) => button.addEventListener('click', () => showView(button.dataset.view)));
  $('theme-btn').addEventListener('click', toggleTheme);
  $('refresh-btn').addEventListener('click', refresh); $('new-scan-btn').addEventListener('click', () => openModal('scan-modal')); $('start-scan-btn').addEventListener('click', startScan); $('approve-save-btn').addEventListener('click', saveApproval); $('send-btn').addEventListener('click', sendMessage); $('menu-btn').addEventListener('click', openSidebar); $('sidebar-backdrop').addEventListener('click', closeSidebar); ['search', 'decision', 'approval'].forEach((id) => $(id).addEventListener(id === 'search' ? 'input' : 'change', renderLeads));
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') { closeModal('detail-modal'); closeModal('scan-modal'); closeSidebar(); } });
  refresh(); setInterval(refresh, 10000);
})();
