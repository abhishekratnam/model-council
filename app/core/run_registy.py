"""Tracks in-flight council rounds so the frontend can cancel them."""
import threading

_ACTIVE_RUNS: dict[str, threading.Event] = {}
_LOCK = threading.Lock()


def register_run(round_id: str) -> threading.Event:
    """Create and store a cancel flag for a running round."""
    event = threading.Event()
    with _LOCK:
        _ACTIVE_RUNS[round_id] = event
    return event


def finish_run(round_id: str) -> None:
    """Remove the round's flag once the run is over (success, error, or cancel)."""
    with _LOCK:
        _ACTIVE_RUNS.pop(round_id, None)


def cancel_run(round_id: str) -> bool:
    """Signal a running round to stop. False if the round isn't active."""
    with _LOCK:
        event = _ACTIVE_RUNS.get(round_id)
    if event is None:
        return False
    event.set()
    return True