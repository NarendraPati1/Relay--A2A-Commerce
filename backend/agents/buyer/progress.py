"""Per-request progress reporting for the buyer workflow UI."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from typing import Any


ProgressReporter = Callable[[dict[str, Any]], None]
_reporter: ContextVar[ProgressReporter | None] = ContextVar(
    "buyer_progress_reporter", default=None,
)


def set_progress_reporter(reporter: ProgressReporter):
    """Install a reporter for the current request and return its reset token."""
    return _reporter.set(reporter)


def reset_progress_reporter(token: object) -> None:
    _reporter.reset(token)


def report_progress(step: str, detail: str) -> None:
    """Report a real graph step without exposing internal state or errors."""
    print(f"-> {step}")
    reporter = _reporter.get()
    if reporter is not None:
        reporter({"type": "progress", "step": step, "detail": detail})


def report_agent_activity(
    sender: str,
    recipient: str,
    text: str,
    *,
    merchants: list[str] | None = None,
) -> None:
    """Report a customer-safe, factual message exchanged by local agents."""
    reporter = _reporter.get()
    if reporter is not None:
        payload: dict[str, Any] = {
            "type": "agent_activity",
            "from": sender,
            "to": recipient,
            "text": text,
        }
        if merchants is not None:
            payload["merchants"] = merchants
        reporter(payload)
