"""Session access for paid research questions. Challenges in the component bridge are single-use."""
from collections import deque
import hmac
import re
import secrets
import threading
import time


_SESSION_KEY = secrets.token_bytes(32)
_failures = deque()
_lock = threading.Lock()


def _verify(state, secret, challenge, proof):
    now = time.monotonic()
    with _lock:
        while _failures and now - _failures[0] >= 60:
            _failures.popleft()
        attempts = [t for t in state.get("unlock_attempts", ()) if now - t < 60]
        if len(attempts) >= 6 or len(_failures) >= 120:
            return "尝试过于频繁，请稍等一分钟再试。"
        expected = hmac.digest(secret, ("xuheng-ai:" + challenge).encode(), "sha256").hex() if challenge else None
        if expected and isinstance(proof, str) and re.fullmatch("[0-9a-f]{64}", proof) and hmac.compare_digest(expected, proof):
            state.pop("unlock_attempts", None)
            return ""
        _failures.append(now)
        state["unlock_attempts"] = [*attempts, now]
        return "问答密码不正确或本次验证已过期，请重新输入。"


def gate(state, body, password):
    """Return a locked response, or None when the requested action may continue."""
    action = body.get("action")
    if action == "lock":
        state.pop("grant", None)
        state.pop("challenge", None)
    secret = password.encode() if isinstance(password, str) and password.strip() else b""
    tag = hmac.digest(_SESSION_KEY, secret, "sha256") if secret else b""
    if tag and hmac.compare_digest(tag, state.get("grant", b"")):
        return None
    # Also discard turns from pre-password sessions and permissions from an old password.
    state.pop("grant", None)
    state.pop("turns", None)
    locked = {"access": "locked", "ready": False, "turns": []}
    if not secret:
        state.pop("challenge", None)
        return {**locked, "access": "unconfigured"}
    if action == "unlock":
        error = _verify(state, secret, state.pop("challenge", None), body.get("proof"))
        if not error:
            state["grant"] = tag
            return None
        locked["message"] = error
    if "challenge" not in state:
        state["challenge"] = secrets.token_hex(24)
    return {**locked, "challenge": state["challenge"]}
