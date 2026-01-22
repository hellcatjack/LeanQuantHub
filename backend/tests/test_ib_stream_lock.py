import pytest

from app.services.ib_stream import acquire_stream_lock
from app.services.job_lock import JobLock


def test_stream_lock_busy(tmp_path):
    lock = JobLock("ib_stream", tmp_path)
    assert lock.acquire()
    with pytest.raises(RuntimeError):
        acquire_stream_lock(tmp_path)
    lock.release()
