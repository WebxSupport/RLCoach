"""Request ID counter for PsyNet API requests."""
import threading


class RequestIDCounter:
    def __init__(self):
        self._value = 0
        self._lock = threading.Lock()

    def get_id(self) -> str:
        with self._lock:
            current_id = self._value
            self._value += 1
            return f"PsyNetMessage_X_{current_id}"
