import os

import requests


OLLAMA_HOST = os.environ.get(
    "OLLAMA_HOST",
    "http://localhost:11434"
)

OLLAMA_MODEL = os.environ.get(
    "OLLAMA_MODEL",
    "qwen3:8b"
)

# A stalled model call must not hold a web request open forever.
OLLAMA_TIMEOUT = int(
    os.environ.get("OLLAMA_TIMEOUT", "120")
)

# Qwen3 can emit its reasoning before its answer. It roughly doubles
# response time, so it is off unless someone is debugging.
OLLAMA_THINK = os.environ.get(
    "OLLAMA_THINK", "0"
) not in ("0", "false", "")


class ModelUnavailable(Exception):
    """
    Raised when the local model cannot be reached or fails.

    Callers must treat this as "I do not know" and never fall back
    to answering from the model's own memory.
    """


def ask_model_verbose(user_message, temperature=0.2):
    """
    Send a prompt to the local model and return (answer, thinking).

    `thinking` is the model's own reasoning when thinking mode is on,
    and None otherwise. A low temperature is used by default: this
    agent extracts fields and quotes verified policy, so creative
    variation is a liability.
    """

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": user_message,
        "stream": False,
        "think": OLLAMA_THINK,
        "options": {
            "temperature": temperature
        }
    }

    try:

        response = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json=payload,
            timeout=OLLAMA_TIMEOUT
        )

        response.raise_for_status()

        body = response.json()

        return body["response"], (body.get("thinking") or None)

    except (requests.RequestException, KeyError, ValueError) as error:

        raise ModelUnavailable(str(error)) from error


def ask_model(user_message, temperature=0.2):
    """
    Send a prompt to the local model and return its answer text.
    """

    answer, _ = ask_model_verbose(user_message, temperature)

    return answer
