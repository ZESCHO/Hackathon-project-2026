import requests

def ask_model(user_message):
    payload = {
        "model": "qwen3:8b",
        "prompt": user_message,
        "stream": False
    }
    response = requests.post("http://localhost:11434/api/generate", json=payload)
    return response.json()["response"]