"""
Agent trace log.

Records what the model was asked, what it came back with, what was
parsed out of that, and what the platform decided to do. Written for a
human to read: the point is to be able to answer "why did it do that?"
without reproducing the conversation.

Enabled by default in development. Set AGENT_TRACE=0 to turn it off.

This is a debugging aid, not the audit trail. The audit trail lives in
the database and records institutional actions; this records the
model's reasoning.
"""

import os
import json
import threading
from datetime import datetime


TRACE_ENABLED = os.environ.get("AGENT_TRACE", "1") not in ("0", "false", "")

LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "logs"
)

LOG_PATH = os.path.join(LOG_DIR, "agent_trace.log")

# Keep the file from growing without bound during a long demo session.
MAX_BYTES = 5 * 1024 * 1024

_LOCK = threading.Lock()

WIDTH = 74


def _write(text):

    if not TRACE_ENABLED:
        return

    with _LOCK:

        try:
            os.makedirs(LOG_DIR, exist_ok=True)

            if (
                os.path.exists(LOG_PATH)
                and os.path.getsize(LOG_PATH) > MAX_BYTES
            ):
                os.replace(LOG_PATH, LOG_PATH + ".1")

            with open(LOG_PATH, "a", encoding="utf-8") as handle:
                handle.write(text)

        except OSError as error:
            # Never let logging break a request.
            print("TRACE WRITE FAILED:", error)


def _block(text, indent="    "):
    """
    Indent a multi-line value so it stays visually inside its section.
    """

    if text is None:
        return indent + "(none)"

    text = str(text).strip()

    if not text:
        return indent + "(empty)"

    return "\n".join(indent + line for line in text.splitlines())


def start_turn(user_message, user=None):
    """
    Open a new block for one user message.
    """

    _write(
        "\n"
        + "=" * WIDTH + "\n"
        + f"{datetime.now():%Y-%m-%d %H:%M:%S}"
        + (f"   user: {user}" if user else "")
        + "\n"
        + "=" * WIDTH + "\n"
        + "USER SAID\n"
        + _block(user_message) + "\n"
    )


def model_call(purpose, thinking, raw_response, seconds=None):
    """
    Record one call to the model.

    `thinking` is the model's own reasoning when thinking mode is on,
    and None otherwise.
    """

    timing = f"  ({seconds:.1f}s)" if seconds is not None else ""

    parts = ["\n" + "-" * WIDTH + "\n" + f"MODEL CALL: {purpose}{timing}\n"]

    if thinking:
        parts.append("  QWEN'S THINKING\n" + _block(thinking, "    ") + "\n")

    parts.append("  QWEN'S RAW REPLY\n" + _block(raw_response, "    ") + "\n")

    _write("".join(parts))


def note(label, value):
    """
    Record a parsed value or an intermediate decision.
    """

    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, indent=2)

    _write(f"\n{label}\n" + _block(value) + "\n")


def rejected(field, value, reason):
    """
    Record a value the platform refused to accept from the model.

    These are the interesting lines: they are the moments the platform
    declined to act on something the model made up.
    """

    _write(
        f"\n  REJECTED FIELD  {field} = {value!r}\n"
        f"                  reason: {reason}\n"
    )


def decision(summary):
    """
    Record what the platform actually did.
    """

    _write("\n" + "-" * WIDTH + "\n" + f"DECISION: {summary}\n")


def reply(text):
    """
    Record what the user was shown.
    """

    _write("\nREPLIED TO USER\n" + _block(text) + "\n")


def decision_note(summary):
    """
    Record a decision the understanding layer made on its own, before
    the route sees the result.
    """

    _write(f"\n  {summary}\n")
