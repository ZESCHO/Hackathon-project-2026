import json

from openai import OpenAI
from flask import current_app


class SecureAgent:
    """
    Main AI agent.

    Responsibilities:
    - Understand the user's request
    - Identify the intended service
    - Estimate confidence
    - Detect uncertainty
    - Detect possible policy conflicts
    - Create a safe action plan

    IMPORTANT:
    The agent does not directly execute consequential actions.
    """

    def __init__(self):
        api_key = current_app.config.get("AI_API_KEY")

        if not api_key:
            raise ValueError(
                "AI_API_KEY is missing from the .env file."
            )

        self.client = OpenAI(api_key=api_key)

        self.model = current_app.config.get(
            "AI_MODEL",
            "gpt-5.6-luna"
        )

    def understand_request(self, user_message):
        """
        Understand a service request and return
        a structured result.
        """

        system_prompt = """
You are the Secure Institutional AI Agent.

Your job is to understand institutional service requests.

Supported services:

1. certificate
2. maintenance
3. laboratory
4. grievance
5. information
6. unknown

You must NOT invent institutional policies.

You must NOT claim that an action has been completed.

You must NOT execute any real-world action.

If the request is ambiguous or lacks important information,
set uncertainty to true.

If the request might violate institutional policy,
set policy_conflict to true.

Return ONLY valid JSON using this structure:

{
    "intent": "certificate|maintenance|laboratory|grievance|information|unknown",
    "summary": "short summary",
    "confidence": 0.0,
    "uncertainty": false,
    "missing_information": [],
    "policy_conflict": false,
    "reason": "",
    "suggested_steps": []
}

Confidence must be between 0 and 1.
"""

        response = self.client.responses.create(
            model=self.model,
            instructions=system_prompt,
            input=user_message,
            reasoning={
                "effort": "low"
            }
        )

        text = response.output_text.strip()

        try:
            result = json.loads(text)

        except json.JSONDecodeError:
            return {
                "intent": "unknown",
                "summary": "The request could not be safely interpreted.",
                "confidence": 0.0,
                "uncertainty": True,
                "missing_information": [],
                "policy_conflict": False,
                "reason": "AI returned an invalid structured response.",
                "suggested_steps": []
            }

        return self._validate_result(result)

    def _validate_result(self, result):
        """
        Validate and normalize the AI response.
        """

        allowed_intents = {
            "certificate",
            "maintenance",
            "laboratory",
            "grievance",
            "information",
            "unknown"
        }

        intent = result.get("intent", "unknown")

        if intent not in allowed_intents:
            intent = "unknown"

        try:
            confidence = float(
                result.get("confidence", 0)
            )
        except (TypeError, ValueError):
            confidence = 0.0

        confidence = max(
            0.0,
            min(1.0, confidence)
        )

        uncertainty = bool(
            result.get("uncertainty", False)
        )

        # Low confidence automatically triggers uncertainty.
        if confidence < 0.70:
            uncertainty = True

        return {
            "intent": intent,

            "summary": str(
                result.get(
                    "summary",
                    ""
                )
            ),

            "confidence": confidence,

            "uncertainty": uncertainty,

            "missing_information": result.get(
                "missing_information",
                []
            ),

            "policy_conflict": bool(
                result.get(
                    "policy_conflict",
                    False
                )
            ),

            "reason": str(
                result.get(
                    "reason",
                    ""
                )
            ),

            "suggested_steps": result.get(
                "suggested_steps",
                []
            )
        }