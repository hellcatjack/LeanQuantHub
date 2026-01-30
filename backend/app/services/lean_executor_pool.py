from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass
class ExecutorInstance:
    pid: int | None = None
    role: str = "worker"
    last_heartbeat: datetime | None = None

    def is_alive(self) -> bool:
        if self.pid is None:
            return False
        return _pid_alive(self.pid)


class LeanExecutorPoolManager:
    def __init__(self, *, mode: str, size: int) -> None:
        self.mode = mode
        self.size = max(1, int(size))
        self.instances: list[ExecutorInstance] = []
        self._init_instances()

    def _init_instances(self) -> None:
        for idx in range(self.size):
            role = "leader" if idx == 0 else "worker"
            self.instances.append(ExecutorInstance(role=role))
