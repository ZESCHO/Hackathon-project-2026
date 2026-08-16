import os
import json
from app.ollama_client import ask_model


def understand_request(user_request):

    prompt = f"""
You are the AI understanding module of a Secure Agentic-AI
institutional service platform.

Analyze the user's request and return ONLY valid JSON.

Possible services:
- certificate
- maintenance
- laboratory
- grievance

Possible intents:
- certificate_request
- maintenance_report
- laboratory_booking
- grievance_submission
- unknown

User request:
{user_request}

Return exactly this structure:

{{
    "intent": "one of the possible intents",
    "category": "certificate, maintenance, laboratory, grievance, or unknown",
    "action": "request, report, book, submit, or unknown",
    "confidence": "high, medium, or low",
    "message": "A short friendly explanation of what you understood"
}}
"""

    try:

        result = ask_model(prompt)
        
        # Remove accidental markdown fences
        if result.startswith("```"):
            result = result.replace("```json", "")
            result = result.replace("```", "")
            result = result.strip()

        data = json.loads(result)

        return data

    except Exception as e:
        print("AI ERROR:", e)

        return {
            "intent": "unknown",
            "category": "unknown",
            "action": "unknown",
            "confidence": "low",
            "message": "I could not understand the request right now."
        }