from enum import Enum


class Status(Enum):
    NEW = "NEW"
    CLASSIFIED = "CLASSIFIED"
    ASSIGNED = "ASSIGNED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_INFO = "AWAITING_INFO"
    RESOLVED = "RESOLVED"
    VERIFIED = "VERIFIED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class Priority(Enum):
    P1 = 1  # Critical
    P2 = 2  # High
    P3 = 3  # Medium
    P4 = 4  # Low


class Impact(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3


class Urgency(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3



class Role(Enum):
    EMPLOYEE = "EMPLOYEE"
    TECHNICIAN = "TECHNICIAN"
    ADMIN = "ADMIN"