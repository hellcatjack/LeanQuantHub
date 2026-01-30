import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import lean_executor_pool


def test_pool_selects_single_leader():
    pool = lean_executor_pool.LeanExecutorPoolManager(mode="paper", size=3)
    roles = [inst.role for inst in pool.instances]
    assert roles.count("leader") == 1


def test_pool_marks_dead_pid_stale():
    inst = lean_executor_pool.ExecutorInstance(pid=999999, role="worker")
    assert inst.is_alive() is False
