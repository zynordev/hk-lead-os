import 'dotenv/config';
import crypto from 'node:crypto';
import { createServer } from 'node:http';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import makeWASocket, { Browsers, DisconnectReason, useMultiFileAuthState } from '@whiskeysockets/baileys';
import P from 'pino';
import qrcode from 'qrcode-terminal';

const authDir = resolve(process.env.WHATSAPP_AUTH_DIR || './auth');
const stateFile = resolve(process.env.WHATSAPP_STATE_FILE || './state/sent.json');
const host = process.env.WHATSAPP_HOST || '127.0.0.1';
const port = Number(process.env.WHATSAPP_PORT || 8787);
const enabled = process.env.WHATSAPP_OUTBOUND_ENABLED === '1';
const approvalToken = process.env.WHATSAPP_APPROVAL_TOKEN || '';
const minDelay = Number(process.env.WHATSAPP_SEND_DELAY_MIN_MS || 900);
const maxDelay = Number(process.env.WHATSAPP_SEND_DELAY_MAX_MS || 2600);
const logger = P({ level: process.env.LOG_LEVEL || 'warn' });
let sock;
let connection = 'starting';
let sent = {};
const pendingAcks = new Map();

async function loadState() { try { sent = JSON.parse(await readFile(stateFile, 'utf8')); } catch { sent = {}; } }
async function saveState() {
  await mkdir(dirname(stateFile), { recursive: true });
  const temp = `${stateFile}.tmp`;
  await writeFile(temp, JSON.stringify(sent, null, 2), 'utf8');
  await rename(temp, stateFile);
}
function normalizePhone(value) {
  const digits = String(value || '').replace(/\D/g, '');
  if (digits.length < 10 || digits.length > 15) throw new Error('Geçersiz telefon numarası');
  return `${digits}@s.whatsapp.net`;
}
const sleep = (ms) => new Promise((resolvePromise) => setTimeout(resolvePromise, ms));

async function connect() {
  await mkdir(authDir, { recursive: true });
  const { state, saveCreds } = await useMultiFileAuthState(authDir);
  sock = makeWASocket({ auth: state, browser: Browsers.ubuntu('HK Yazilim'), logger });
  sock.ev.on('creds.update', saveCreds);
  sock.ev.on('messages.update', updates => {
    for (const item of updates) {
      const id = item?.key?.id;
      const status = Number(item?.update?.status || 0);
      const pending = id && pendingAcks.get(id);
      if (!pending) continue;
      if (status >= 2) { clearTimeout(pending.timer); pendingAcks.delete(id); pending.resolve(status); }
      else if (status === 0) { clearTimeout(pending.timer); pendingAcks.delete(id); pending.reject(new Error('WhatsApp mesajı sunucu tarafından reddedildi')); }
    }
  });
  sock.ev.on('connection.update', ({ connection: next, lastDisconnect, qr }) => {
    connection = next || connection;
    if (qr) { console.log('\nWhatsApp QR kodu — Bağlı Cihazlar > Cihaz Bağla ile okut:\n'); qrcode.generate(qr, { small: true }); }
    if (next === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode;
      if (code !== DisconnectReason.loggedOut) setTimeout(connect, 5000);
    }
    if (next === 'open') console.log(`[whatsapp] bağlı; outbound=${enabled ? 'enabled' : 'disabled'}`);
  });
}
function waitForServerAck(messageId, timeoutMs = 10000) {
  return new Promise((resolvePromise, rejectPromise) => {
    const timer = setTimeout(() => { pendingAcks.delete(messageId); const error = new Error('WhatsApp sunucu onayı alınamadı'); error.code = 'ACK_TIMEOUT'; rejectPromise(error); }, timeoutMs);
    pendingAcks.set(messageId, { resolve: resolvePromise, reject: rejectPromise, timer });
  });
}
async function readBody(req) {
  let text = '';
  for await (const chunk of req) text += chunk;
  if (text.length > 20000) throw new Error('İstek gövdesi çok büyük');
  return JSON.parse(text || '{}');
}
function reply(res, status, data) { res.writeHead(status, { 'content-type': 'application/json; charset=utf-8' }); res.end(JSON.stringify(data)); }
function tokensMatch(provided, expected) {
  const a = Buffer.from(String(provided || ''));
  const b = Buffer.from(String(expected || ''));
  return a.length > 0 && a.length === b.length && crypto.timingSafeEqual(a, b);
}
async function handle(req, res) {
  if (req.method === 'GET' && req.url === '/health') return reply(res, 200, { ok: true, connection, outbound_enabled: enabled, sent_count: Object.keys(sent).length });
  if (req.method !== 'POST' || req.url !== '/send') return reply(res, 404, { error: 'not_found' });
  try {
    const body = await readBody(req);
    if (!enabled) return reply(res, 423, { error: 'outbound_disabled' });
    if (!approvalToken || !tokensMatch(body.approval_token, approvalToken) || body.approved !== true) return reply(res, 403, { error: 'manual_approval_required' });
    if (!body.lead_id || !body.message) return reply(res, 400, { error: 'lead_id_and_message_required' });
    const jid = normalizePhone(body.phone);
    const key = `${body.lead_id}:${jid}`;
    if (sent[key]) return reply(res, 409, { error: 'already_sent', sent_at: sent[key].sent_at });
    if (connection !== 'open') return reply(res, 503, { error: 'whatsapp_not_connected', connection });
    const registration = await sock.onWhatsApp(jid);
    if (!registration?.[0]?.exists) return reply(res, 422, { error: 'phone_not_registered_on_whatsapp' });
    await sleep(minDelay + Math.random() * Math.max(0, maxDelay - minDelay));
    const result = await sock.sendMessage(jid, { text: String(body.message).slice(0, 4000) });
    const messageId = result?.key?.id;
    if (!messageId) throw new Error('WhatsApp mesaj kimliği alınamadı');
    await waitForServerAck(messageId);
    sent[key] = { lead_id: body.lead_id, jid, sent_at: new Date().toISOString(), message_id: messageId };
    await saveState();
    return reply(res, 200, { ok: true, key, sent_at: sent[key].sent_at });
  } catch (error) { return reply(res, error.code === 'ACK_TIMEOUT' ? 504 : 400, { error: error.message || 'bad_request' }); }
}

await loadState();
await connect();
createServer((req, res) => handle(req, res).catch((error) => reply(res, 500, { error: error.message }))).listen(port, host, () => console.log(`[whatsapp] local sender: http://${host}:${port}`));
