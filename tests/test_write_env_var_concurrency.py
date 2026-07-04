"""Test for agents/shared/modes.py::_write_env_var concurrency safety.

Covers the Review Finding: an unguarded read-then-write of .env let two
concurrent mode-toggle requests (e.g. an unauthenticated POST
/api/control/mode fired twice back-to-back) both read the same
pre-update file and each write their own version — whichever call
finished writing LAST silently discarded the other's update.
"""

import os
import pathlib
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_write_env_var_serializes_concurrent_writers(tmp_path, monkeypatch):
    import agents.shared.modes as modes_mod

    # _write_env_var computes env_path as Path(__file__).parent.parent.parent
    # / ".env" — redirect it to our temp file by making Path(anything)
    # return a fixed stand-in three levels below tmp_path.
    fake_deep_path = tmp_path / "a" / "b" / "c"
    monkeypatch.setattr(modes_mod, "Path", lambda _: fake_deep_path)

    env_file = tmp_path / ".env"
    env_file.write_text("")

    original_read_text = pathlib.Path.read_text
    thread_a_read_done = threading.Event()
    let_thread_a_write = threading.Event()

    def _paused_read_text(self, *a, **k):
        result = original_read_text(self, *a, **k)
        if self == env_file:
            thread_a_read_done.set()
            let_thread_a_write.wait(timeout=2.0)
        return result

    monkeypatch.setattr(pathlib.Path, "read_text", _paused_read_text)

    thread_a = threading.Thread(target=lambda: modes_mod._write_env_var("SIMULATION_MODE", "true"))
    thread_a.start()
    assert thread_a_read_done.wait(timeout=2.0), "thread A never reached its read"

    # Thread A is now paused between its read and its write, still holding
    # _env_write_lock. A second writer must block on the lock instead of
    # reading the same stale (pre-A-write) content and clobbering it later.
    thread_b = threading.Thread(target=lambda: modes_mod._write_env_var("PAPER_MODE", "false"))
    thread_b.start()

    # Give thread B every chance to race ahead if the lock isn't working —
    # it must NOT have written anything yet, because it should still be
    # blocked waiting for thread A's lock.
    thread_b.join(timeout=0.3)
    assert thread_b.is_alive(), "a second writer must block on the lock, not race ahead"
    assert "PAPER_MODE" not in env_file.read_text()

    let_thread_a_write.set()
    thread_a.join(timeout=5.0)
    thread_b.join(timeout=5.0)

    content = env_file.read_text()
    assert content.count("SIMULATION_MODE=") == 1
    assert content.count("PAPER_MODE=") == 1
    assert "SIMULATION_MODE=true" in content
    assert "PAPER_MODE=false" in content
