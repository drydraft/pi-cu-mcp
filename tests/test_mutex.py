"""All server instances must serialize desktop input on this Windows session."""

from __future__ import annotations

from threading import Event, Thread

from windows_mcp.backend import PywinautoBackend


def test_named_mutex_excludes_another_thread() -> None:
    backend = PywinautoBackend.__new__(PywinautoBackend)
    first_entered = Event()
    release_first = Event()
    second_entered = Event()

    def first() -> None:
        with backend.exclusive():
            first_entered.set()
            assert release_first.wait(2)

    def second() -> None:
        with backend.exclusive():
            second_entered.set()

    first_thread = Thread(target=first)
    second_thread = Thread(target=second)
    first_thread.start()
    assert first_entered.wait(2)
    second_thread.start()
    assert not second_entered.wait(0.1)
    release_first.set()
    first_thread.join(2)
    second_thread.join(2)
    assert second_entered.is_set()
