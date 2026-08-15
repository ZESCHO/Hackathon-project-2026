
"""
Human approval package.

Consequential actions must receive appropriate
human approval before execution.
"""

CONSEQUENTIAL_ACTIONS = [
    "create_certificate_request",
    "create_lab_booking",
    "escalate_grievance"
]


def requires_approval(action):
    """
    Determine whether an action requires approval.
    """

    return action in CONSEQUENTIAL_ACTIONS
