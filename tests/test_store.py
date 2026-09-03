from __future__ import annotations

import threading
from pathlib import Path

from harness.store import Store


def _store_with_run(tmp_path: Path) -> tuple[Store, str]:
    store = Store(tmp_path / "harness.db")
    store.initialize()
    user = store.create_user("ada", "scrypt$not-used$not-used")
    run = store.create_run(user.id, "repo", "objective")
    store.update_run(run.id, status="running")
    return store, run.id


def test_runtime_update_cannot_clobber_a_concurrent_stop(tmp_path: Path, monkeypatch):
    store, run_id = _store_with_run(tmp_path)
    inside_write = threading.Event()
    release_write = threading.Event()
    original_write = store._write_run

    def slow_write(run, insert=True):
        # The runtime thread has read the row and is about to write it back.
        inside_write.set()
        release_write.wait(5)
        original_write(run, insert=insert)

    monkeypatch.setattr(store, "_write_run", slow_write)

    runtime = threading.Thread(target=store.update_run, args=(run_id,), kwargs={"active_work": "Editing"})
    runtime.start()
    assert inside_write.wait(5)

    stopper = threading.Thread(target=store.request_stop, args=(run_id,))
    stopper.start()
    stopper.join(0.3)
    # The stop must wait for the in-flight read-modify-write instead of interleaving with it.
    assert stopper.is_alive()

    release_write.set()
    runtime.join(5)
    stopper.join(5)
    assert not runtime.is_alive() and not stopper.is_alive()

    final = store.get_run(run_id)
    assert final is not None
    assert final.stop_requested is True
    assert final.status == "stopping"
    assert final.active_work == "Editing"


def test_request_stop_is_ignored_for_finished_runs(tmp_path: Path):
    store, run_id = _store_with_run(tmp_path)
    store.update_run(run_id, status="completed")
    stopped = store.request_stop(run_id)
    assert stopped is not None
    assert stopped.status == "completed"
    assert stopped.stop_requested is False
