
"""
Audit package.

Every important agent action should eventually
be recorded in the audit trail.

Audit information can include:

- User
- Request
- Intent
- Action
- Policy used
- Approval status
- Tool executed
- Result
- Timestamp
"""

AUDIT_EVENTS = [
    "REQUEST_CREATED",
    "INTENT_DETECTED",
    "PLAN_CREATED",
    "POLICY_CHECKED",
    "APPROVAL_REQUESTED",
    "APPROVAL_GRANTED",
    "APPROVAL_REJECTED",
    "TOOL_EXECUTED",
    "WORKFLOW_COMPLETED",
    "WORKFLOW_FAILED"
]
