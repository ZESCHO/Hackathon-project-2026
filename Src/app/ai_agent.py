import os
import json
from app.ollama_client import ask_model


def understand_request(user_request, history):

    history_text = "\n".join([f"{h['role']}: {h['content']}" for h in history])

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

Conversation so far:
{history_text}

User request:
{user_request}

Required fields per service (used to judge status and missing):

When judging what's missing, consider the ENTIRE conversation so far
(all previous user and bot turns), not just the latest message alone —
information given in earlier turns still counts.

If status is "needs_clarification", the clarification_question must
explicitly name the still-missing fields (e.g. "Could you tell me the
location and room number?"), never a vague question like "what details
do you need?".

- certificate: certificate_type, purpose
- maintenance: location, room, description
- laboratory: laboratory_name, booking_date, booking_time, purpose
- grievance: subject, description

If any required field for the detected category is missing from the
user's message, set "status" to "needs_clarification", list the missing
field names in "missing", and write a specific "clarification_question"
asking for exactly those fields. Only set "status" to "complete" if
every required field for that category is present.

Return exactly this structure:

{{
    "intent": "one of the possible intents",
    "category": "certificate, maintenance, laboratory, grievance, or unknown",
    "action": "request, report, book, submit, or unknown",
    "confidence": "high, medium, or low",
    "message": "A short friendly explanation of what you understood",
    "status": "complete or needs_clarification",
    "missing": "a list of missing required fields, empty list if none",
    "clarification_question": "a question to ask the user if status is needs_clarification, otherwise empty
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