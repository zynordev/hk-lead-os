from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .scoring import score_lead
from .sheets import GoogleSheetsAdapter
from .store import LeadStore


ROOT = Path(__file__).resolve().parent
store = LeadStore()
DATA_DIR = ROOT / "data"
SCANS_FILE = DATA_DIR / "scans.json"
REPLIES_FILE = DATA_DIR / "replies.json"
scan_lock = threading.Lock()
scan_process: subprocess.Popen | None = None
scan_record: dict = {"status": "idle"}
oauth_state: str | None = None
oauth_code_verifier: str | None = None
SHEETS_REDIRECT_URI = os.getenv("GOOGLE_SHEETS_REDIRECT_URI", "https://hky.bilgicoderteam.tr/api/sheets/oauth/callback")


def read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return fallback


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def sync_sheets_safely() -> dict:
    """Sync in the background path without making dashboard actions fail."""
    try:
        return GoogleSheetsAdapter().sync(store.list())
    except Exception as exc:
        print(f"Google Sheets sync failed: {exc}", flush=True)
        return {"synced": False, "reason": str(exc), "count": 0}


def scan_history() -> list[dict]:
    return read_json(SCANS_FILE, [])


def monitor_scan(record: dict, process: subprocess.Popen) -> None:
    global scan_process, scan_record
    output: list[str] = []
    if process.stdout:
        for line in process.stdout:
            line = line.rstrip()
            output.append(line)
            with scan_lock:
                logs = list(record.get("logs") or [])
                logs.append({"at": datetime.now(timezone.utc).isoformat(), "text": line[:500]})
                record["logs"] = logs[-60:]
            if line.startswith("PROGRESS "):
                parts = line.split(" ", 2)
                if len(parts) == 3:
                    with scan_lock:
                        record.update({"progress": int(parts[1]), "stage": parts[2], "last_event": datetime.now(timezone.utc).isoformat()})
    process.wait()
    record.update({"status": "completed" if process.returncode == 0 else "failed", "finished_at": datetime.now(timezone.utc).isoformat(), "exit_code": process.returncode, "output": "\n".join(output)[-4000:]})
    history = scan_history(); history.insert(0, record); write_json(SCANS_FILE, history[:100])
    sync_sheets_safely()
    with scan_lock:
        scan_process = None
        scan_record = record


def start_scan(data: dict) -> dict:
    global scan_process, scan_record
    with scan_lock:
        if scan_process and scan_process.poll() is None:
            raise ValueError("Bir tarama zaten çalışıyor")
        query = str(data.get("query") or "kafe Samsun").strip()[:200]
        limit = max(1, min(int(data.get("limit", 20)), 100))
        workers = max(1, min(int(data.get("workers", 5)), 10))
        concurrency = max(1, min(int(data.get("concurrency", 2)), 5))
        token_path = ROOT.parent / "apifytoken.txt"
        if not token_path.exists(): raise ValueError("apifytoken.txt bulunamadı")
        env = os.environ.copy(); env["APIFY_API_TOKEN"] = token_path.read_text(encoding="utf-8").strip()
        command = [sys.executable, "-u", str(ROOT.parent / "lead_automation.py"), "--query", query, "--limit", str(limit), "--workers", str(workers), "--concurrency", str(concurrency)]
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        process = subprocess.Popen(command, cwd=ROOT.parent, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", creationflags=creationflags)
        record = {"scan_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), "query": query, "limit": limit, "workers": workers, "concurrency": concurrency, "status": "running", "progress": 0, "stage": "Başlatılıyor", "started_at": datetime.now(timezone.utc).isoformat(), "logs": [{"at": datetime.now(timezone.utc).isoformat(), "text": "Scan kuyruğa alındı; Apify ve AI worker'lar hazırlanıyor."}]}
        scan_process = process; scan_record = record
        threading.Thread(target=monitor_scan, args=(record, process), daemon=True).start()
        return record


def stop_scan() -> dict:
    global scan_process, scan_record
    with scan_lock:
        if not scan_process or scan_process.poll() is not None: return scan_record
        scan_process.terminate(); scan_record = {**scan_record, "status": "stopping"}; return scan_record


def api_leads() -> list[dict]:
    """Return backward-compatible lead records with display-safe hours."""
    result = []
    for lead in store.list():
        copy = dict(lead)
        details = dict(copy.get("source_details") or {})
        hours = details.get("opening_hours") or []
        display_hours = " · ".join(
            f"{item.get('day') or item.get('name') or ''}: {item.get('hours') or item.get('time') or item.get('value') or ''}" if isinstance(item, dict) else str(item)
            for item in hours
        ) or "Çalışma saati yok"
        details["opening_hours_display"] = display_hours
        details["opening_hours"] = [display_hours]
        copy["source_details"] = details
        result.append(copy)
    return result


class Handler(BaseHTTPRequestHandler):
    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; connect-src 'self'")

    def _json(self, status: int, value: object) -> None:
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 100_000:
            raise ValueError("request too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self) -> None:
        global oauth_state, oauth_code_verifier
        path = urlparse(self.path).path
        if path == "/api/sheets/connect":
            adapter = GoogleSheetsAdapter()
            if not adapter.oauth_ready:
                self._json(503, {"error": "Google OAuth client JSON bulunamadı"}); return
            url, oauth_state, oauth_code_verifier = adapter.authorization_url(SHEETS_REDIRECT_URI)
            self.send_response(302); self.send_header("Location", url); self.end_headers(); return
        elif path == "/api/sheets/oauth/callback":
            query = parse_qs(urlparse(self.path).query)
            if query.get("error"): self._json(400, {"error": query["error"][0]}); return
            if not oauth_state or not query.get("code") or not query.get("state"):
                self._json(400, {"error": "OAuth oturumu bulunamadı veya eksik"}); return
            if not oauth_code_verifier:
                self._json(400, {"error": "OAuth code verifier bulunamadı; bağlantıyı yeniden başlatın"}); return
            try:
                result = GoogleSheetsAdapter().finish_oauth(SHEETS_REDIRECT_URI, query["code"][0], query["state"][0], oauth_state, oauth_code_verifier)
            except Exception as exc:
                oauth_state = None
                oauth_code_verifier = None
                self._json(400, {"error": f"Google OAuth tamamlanamadı: {exc}"}); return
            oauth_state = None
            oauth_code_verifier = None
            sync = sync_sheets_safely()
            html = f"<!doctype html><meta charset='utf-8'><title>Google Sheets bağlandı</title><style>body{{font:16px system-ui;display:grid;place-items:center;min-height:100vh;background:#f5f7fb}}main{{background:#fff;padding:28px;border-radius:16px;box-shadow:0 15px 50px #0001}}</style><main><h1>Google Sheets bağlandı</h1><p>HK LeadOS işletme havuzu oluşturuldu ve {sync.get('count', 0)} aday senkronize edildi.</p><a href='/'>Dashboard’a dön</a></main>"
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(html.encode()))); self.end_headers(); self.wfile.write(html.encode()); return
        elif path == "/api/health":
            self._json(200, {"ok": True, "leads": len(store.list()), "sheets_configured": GoogleSheetsAdapter().configured, "scan": scan_record})
        elif path == "/api/leads":
            self._json(200, api_leads())
        elif path == "/api/stats":
            leads = store.list(); decisions = {}; statuses = {}
            for lead in leads:
                decisions[lead.get("decision", "İNCELE")] = decisions.get(lead.get("decision", "İNCELE"), 0) + 1
                statuses[lead.get("approval_status", "needs_review")] = statuses.get(lead.get("approval_status", "needs_review"), 0) + 1
            self._json(200, {"total": len(leads), "recommended": decisions.get("ÖNER", 0), "review": decisions.get("İNCELE", 0), "rejected": decisions.get("ELE", 0), "sent": statuses.get("sent", 0), "approved": statuses.get("approved", 0), "pending": statuses.get("needs_review", 0), "replies": len(read_json(REPLIES_FILE, [])), "decisions": decisions, "statuses": statuses})
        elif path == "/api/scans":
            self._json(200, {"active": scan_record, "history": scan_history()})
        elif path.startswith("/api/scans/") and path.endswith("/leads"):
            scan_id = path.removeprefix("/api/scans/").removesuffix("/leads")
            self._json(200, [lead for lead in api_leads() if lead.get("latest_run_id") == scan_id])
        elif path == "/api/replies":
            self._json(200, read_json(REPLIES_FILE, []))
        elif path == "/dashboard-actions.js":
            script = (ROOT / "dashboard-actions.js").read_bytes()
            self.send_response(200); self._security_headers(); self.send_header("Content-Type", "application/javascript; charset=utf-8"); self.send_header("Cache-Control", "no-store, max-age=0"); self.send_header("Content-Length", str(len(script))); self.end_headers(); self.wfile.write(script)
        elif path == "/":
            html = (ROOT / "dashboard.html").read_bytes()
            self.send_response(200); self._security_headers(); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Cache-Control", "no-store, max-age=0"); self.send_header("Content-Length", str(len(html))); self.end_headers(); self.wfile.write(html)
        else:
            self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        try:
            path = urlparse(self.path).path
            data = self._body()
            lead_id = data.get("lead_id", "")
            if path == "/api/approve":
                lead = store.approve(lead_id, data.get("message")); sync_sheets_safely()
                self._json(200, lead); return
            if path == "/api/skip":
                result = store.skip(lead_id); sync_sheets_safely(); self._json(200, result); return
            if path == "/api/opt-out":
                result = store.opt_out(lead_id); sync_sheets_safely(); self._json(200, result); return
            if path == "/api/score":
                lead = store.get(lead_id); result = score_lead(lead); updated = store.update(lead_id, **result); sync_sheets_safely(); self._json(200, updated); return
            if path == "/api/send":
                lead = store.get(lead_id)
                if lead.get("approval_status") != "approved": raise ValueError("Önce manuel onay gerekli")
                if lead.get("opt_out_status") or lead.get("send_status") == "sent": raise ValueError("Gönderim engellendi veya zaten gönderildi")
                token = os.getenv("WHATSAPP_APPROVAL_TOKEN", "")
                payload = {"lead_id": lead_id, "phone": lead.get("phone"), "message": lead.get("message_draft"), "approved": True, "approval_token": token}
                req = Request("http://127.0.0.1:8787/send", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
                with urlopen(req, timeout=30) as response: result = json.loads(response.read())
                updated = store.update(lead_id, send_status="sent", sent_at=result.get("sent_at"), approval_status="sent"); sync_sheets_safely(); self._json(200, updated); return
            if path == "/api/scan/start":
                self._json(202, start_scan(data)); return
            if path == "/api/scan/stop":
                self._json(200, stop_scan()); return
            if path == "/api/replies":
                replies = read_json(REPLIES_FILE, []); reply = {"reply_id": datetime.now(timezone.utc).strftime("reply-%Y%m%d%H%M%S"), "lead_id": lead_id, "business_name": data.get("business_name", ""), "phone": data.get("phone", ""), "message": data.get("message", ""), "received_at": datetime.now(timezone.utc).isoformat(), "status": "new"}; replies.insert(0, reply); write_json(REPLIES_FILE, replies[:500]); self._json(201, reply); return
            if path == "/api/sheets/sync":
                self._json(200, sync_sheets_safely()); return
            self._json(404, {"error": "not_found"})
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            print(f"WhatsApp gönderim hatası HTTP {exc.code}: {detail}", flush=True)
            # Do not expose a 5xx from the dashboard: Cloudflare replaces 5xx
            # bodies with an HTML error page, which breaks the JSON client.
            self._json(422, {"error": f"WhatsApp gönderimi başarısız ({exc.code}): {detail}", "delivery_failed": True})
        except Exception as exc:
            print(f"Dashboard işlem hatası: {exc}", flush=True)
            self._json(400, {"error": str(exc)})


def main() -> None:
    host = os.getenv("LEAD_DASHBOARD_HOST", "127.0.0.1")
    port = int(os.getenv("LEAD_DASHBOARD_PORT", "8790"))
    print(f"Lead dashboard: http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
