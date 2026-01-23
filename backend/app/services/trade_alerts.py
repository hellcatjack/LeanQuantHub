from __future__ import annotations

import json
import urllib.request

from app.models import PreTradeSettings


def notify_trade_alert(session, message: str) -> bool:
    settings = session.query(PreTradeSettings).order_by(PreTradeSettings.id.desc()).first()
    if not settings:
        return False
    token = (settings.telegram_bot_token or "").strip()
    chat_id = (settings.telegram_chat_id or "").strip()
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as _:
            return True
    except Exception:
        return False
