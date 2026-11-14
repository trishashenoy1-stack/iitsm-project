"""Notification rules for events the backend adds on top of P1's (P2).

P3's notification module takes its rules as data, so escalation is covered by adding
rules here, without changing the module (open/closed).
"""

from __future__ import annotations

from app.persistence.events import EscalationExhausted, IncidentEscalated
from notifications.channels import EMAIL, IN_APP
from notifications.rules import DEFAULT_RULES, Audience, Delivery, NotificationRule

LEVEL_NAME = {1: "team lead", 2: "system admin", 3: "IT manager"}

ESCALATION_RULES = (
    NotificationRule(
        lambda e: isinstance(e, IncidentEscalated),
        lambda e: f"{e.incident_id} was escalated to you",
        lambda e: (f"{e.incident_id} has not been acknowledged in time and was escalated "
                   f"to you as {LEVEL_NAME.get(e.level, f'level {e.level}')}."),
        (Delivery(Audience.TARGET_USER, (IN_APP, EMAIL)),),
    ),
    NotificationRule(
        lambda e: isinstance(e, IncidentEscalated),
        lambda e: f"{e.incident_id} was escalated",
        lambda e: f"{e.incident_id} was escalated to level {e.level} because nobody "
                  "acknowledged it in time.",
        (Delivery(Audience.TECHNICIAN, (IN_APP,)),),
    ),
    NotificationRule(
        lambda e: isinstance(e, EscalationExhausted),
        lambda e: f"Escalation chain exhausted for {e.incident_id}",
        lambda e: f"{e.incident_id} is still unacknowledged and nobody is left to escalate to.",
        (Delivery(Audience.ADMINISTRATORS, (IN_APP, EMAIL)),),
    ),
)

BACKEND_RULES = DEFAULT_RULES + ESCALATION_RULES
