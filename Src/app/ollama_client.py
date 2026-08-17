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


class ModelUnavailable(Exception):
    """
    Raised when the local model cannot be reached or fails.

    Callers must treat this as "I do not know" and never fall back
    to answering from the model's own memory.
    """


def ask_model(user_message, temperature=0.2):
    """
    Send a prompt to the local Ollama model and return raw text.

    A low temperature is used by default: this agent extracts fields
    and quotes verified policy, so creative variation is a liability.
    """

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": user_message,
        "stream": False,
        "think": False,
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

        return response.json()["response"]

    except (requests.RequestException, KeyError, ValueError) as error:

        raise ModelUnavailable(str(error)) from error
