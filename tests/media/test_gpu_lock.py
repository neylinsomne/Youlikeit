"""El lock de GPU no debe quedar trabado por un proceso que murió sin limpiar."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from utils import gpu_lock


@pytest.mark.unit
def test_pid_alive_for_self_and_dead_process():
    assert gpu_lock.pid_alive(os.getpid())
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert not gpu_lock.pid_alive(proc.pid)
    assert not gpu_lock.pid_alive(0)


@pytest.mark.integration
def test_lock_left_by_dead_process_is_reclaimed_immediately(tmp_path):
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    lock = tmp_path / "gpu.lock"
    lock.write_text(f"{proc.pid} asr 0\n")            # huérfano: su dueño ya no existe
    with gpu_lock.gpu_slot("test", lock_path=lock, timeout=1, poll=0.05):
        assert gpu_lock.lock_holder(lock) == (os.getpid(), "test")
    assert not lock.exists()


@pytest.mark.integration
def test_lock_held_by_live_process_times_out(tmp_path):
    lock = tmp_path / "gpu.lock"
    lock.write_text(f"{os.getpid()} asr 0\n")         # dueño vivo (este mismo proceso)
    with pytest.raises(TimeoutError, match="asr"):
        with gpu_lock.gpu_slot("other", lock_path=lock, timeout=0.2, poll=0.05):
            pass
    assert lock.exists()
