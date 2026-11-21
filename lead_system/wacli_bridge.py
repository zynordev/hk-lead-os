"""Optional Raspberry Pi wacli WhatsApp transport for LeadOS.

Allows LeadOS to send manually approved messages via the synced wacli CLI
running on the Raspberry Pi over SSH when WHATSAPP_TRANSPORT=wacli (or when
the local Baileys bridge on port 8787 is not running and WACLI_ENABLED=1).
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone
from typing import Any


def _format_tr_e164(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 11 and digits.startswith("05"):
        digits = f"90{digits[1:]}"
    elif len(digits) == 10 and digits.startswith("5"):
        digits = f"90{digits}"
    if not (len(digits) == 12 and digits.startswith("905")):
        raise ValueError("wacli yalnızca geçerli Türkiye GSM (+90 5xx) numaralarına gönderim yapar")
    return f"+{digits}"


def wacli_configured() -> bool:
    return os.getenv("WACLI_ENABLED", "0") == "1" or os.getenv("WHATSAPP_TRANSPORT", "").lower() == "wacli"


def send_via_wacli(phone: str, message: str, ssh_host: str | None = None) -> dict[str, Any]:
    """Send a single approved WhatsApp text via wacli (local or SSH host)."""
    if not wacli_configured():
        raise RuntimeError("wacli gönderimi etkin değil (WACLI_ENABLED=1 ayarlayın)")
    target = _format_tr_e164(phone)
    clean_msg = str(message or "").strip()[:4000]
    if not clean_msg:
        raise ValueError("Mesaj içeriği boş olamaz")

    host = (ssh_host or os.getenv("WACLI_SSH_HOST", "")).strip()
    if host:
        cmd = [
            "ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", host,
            "wacli", "send", "text", "--to", target, "--message", clean_msg,
        ]
    else:
        cmd = ["wacli", "send", "text", "--to", target, "--message", clean_msg]

    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:300]
        raise RuntimeError(f"wacli gönderim hatası ({proc.returncode}): {detail}")
    return {
        "ok": True,
        "transport": "wacli",
        "to": target,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "stdout": (proc.stdout or "").strip()[:200],
    }
