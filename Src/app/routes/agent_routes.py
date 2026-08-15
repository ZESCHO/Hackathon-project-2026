from flask import Blueprint, request, jsonify

from app.agent.agent import SecureAgent
from app.security.authentication import login_required


agent_bp = Blueprint(
    "agent",
    __name__,
    url_prefix="/api/agent"
)


@agent_bp.route("/understand", methods=["POST"])
@login_required
def understand_request():

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "success": False,
            "error": "JSON request body is required"
        }), 400

    message = data.get("message", "").strip()

    if not message:
        return jsonify({
            "success": False,
            "error": "Message is required"
        }), 400

    if len(message) > 2000:
        return jsonify({
            "success": False,
            "error": "Message is too long"
        }), 400

    try:

        agent = SecureAgent()

        result = agent.understand_request(
            message
        )

        return jsonify({
            "success": True,
            "result": result
        })

    except Exception as error:

        print("Agent error:", error)

        return jsonify({
            "success": False,
            "error": "The AI service is currently unavailable."
        }), 503