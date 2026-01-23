from __future__ import annotations

from app.services.ib_settings import probe_ib_connection
from app.services import ib_stream

get_stream_status = ib_stream.get_stream_status


def build_ib_health(session) -> dict[str, object]:
    state = probe_ib_connection(session)
    stream = get_stream_status()
    return {
        "connection_status": (state.status or "unknown"),
        "stream_status": stream.get("status") or "unknown",
        "stream_last_heartbeat": stream.get("last_heartbeat"),
    }
