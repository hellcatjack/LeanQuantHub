from __future__ import annotations

import threading
import time


def test_ib_request_lock_waits_for_release(tmp_path, monkeypatch):
    from app.services import ib_market
    from app.services.job_lock import JobLock

    monkeypatch.setattr(ib_market, "_resolve_data_root", lambda: tmp_path)
    lock = JobLock("ib_request", tmp_path)
    assert lock.acquire()

    def _release() -> None:
        time.sleep(0.1)
        lock.release()

    thread = threading.Thread(target=_release)
    thread.start()
    with ib_market.ib_request_lock(wait_seconds=1.0, retry_interval=0.05):
        pass
    thread.join(timeout=1)
