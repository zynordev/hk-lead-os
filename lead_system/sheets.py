from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]
DEFAULT_HEADERS = ["lead_id", "business_name", "business_type", "district", "address", "phone", "website_url", "instagram_url", "google_maps_url", "decision", "ai_score", "approval_status", "send_status", "ai_summary", "message_draft", "latest_run_id"]


class GoogleSheetsAdapter:
    """Google Sheets OAuth adapter with a local encrypted-at-rest boundary left to the host filesystem permissions."""

    def __init__(self) -> None:
        self.data_dir = Path(os.getenv("GOOGLE_AUTH_DIR", "/opt/public-relations/secrets/google"))
        self.client_file = Path(os.getenv("GOOGLE_OAUTH_CLIENT_JSON", str(self.data_dir / "client_secret.json")))
        self.token_file = self.data_dir / "token.json"
        self.config_file = self.data_dir / "config.json"
        self.spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")
        try:
            self.spreadsheet_id = self.spreadsheet_id or json.loads(self.config_file.read_text(encoding="utf-8")).get("spreadsheet_id", "")
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    @property
    def configured(self) -> bool:
        return bool(self.spreadsheet_id and self.token_file.exists() and self.client_file.exists())

    @property
    def oauth_ready(self) -> bool:
        return self.client_file.exists()

    def _flow(self, redirect_uri: str, state: str | None = None):
        from google_auth_oauthlib.flow import Flow  # type: ignore
        flow = Flow.from_client_secrets_file(str(self.client_file), scopes=SCOPES, state=state)
        flow.redirect_uri = redirect_uri
        return flow

    def authorization_url(self, redirect_uri: str) -> tuple[str, str, str]:
        state = secrets.token_urlsafe(32)
        flow = self._flow(redirect_uri, state)
        url, returned_state = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent", state=state)
        return url, returned_state, flow.code_verifier

    def finish_oauth(self, redirect_uri: str, code: str, state: str, expected_state: str, code_verifier: str) -> dict[str, Any]:
        if not secrets.compare_digest(state, expected_state):
            raise ValueError("Google OAuth state doğrulanamadı")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        flow = self._flow(redirect_uri, state)
        flow.code_verifier = code_verifier
        flow.fetch_token(code=code)
        self.token_file.write_text(flow.credentials.to_json(), encoding="utf-8")
        self.token_file.chmod(0o600)
        if not self.spreadsheet_id:
            import gspread  # type: ignore
            sheet = gspread.authorize(flow.credentials).create("HK LeadOS İşletme Havuzu")
            self.spreadsheet_id = sheet.id
            self.config_file.write_text(json.dumps({"spreadsheet_id": self.spreadsheet_id}, indent=2), encoding="utf-8")
            self.config_file.chmod(0o600)
        return {"spreadsheet_id": self.spreadsheet_id, "synced": False}

    def _credentials(self):
        from google.oauth2.credentials import Credentials  # type: ignore
        from google.auth.transport.requests import Request  # type: ignore
        credentials = Credentials.from_authorized_user_file(str(self.token_file), SCOPES)
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            self.token_file.write_text(credentials.to_json(), encoding="utf-8")
            self.token_file.chmod(0o600)
        return credentials

    def sync(self, leads: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.configured:
            return {"synced": False, "reason": "Google Sheets OAuth bağlantısı yapılmadı", "count": 0}
        import gspread  # type: ignore
        sheet = gspread.authorize(self._credentials()).open_by_key(self.spreadsheet_id).sheet1
        rows = [[json.dumps(lead.get(header, ""), ensure_ascii=False) if isinstance(lead.get(header, ""), (dict, list)) else lead.get(header, "") for header in DEFAULT_HEADERS] for lead in leads]
        sheet.clear()
        sheet.update([DEFAULT_HEADERS] + rows)
        return {"synced": True, "count": len(leads), "spreadsheet_id": self.spreadsheet_id}
