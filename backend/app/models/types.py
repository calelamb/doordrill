import enum


class UserRole(str, enum.Enum):
    REP = "rep"
    MANAGER = "manager"
    ADMIN = "admin"


class AssignmentStatus(str, enum.Enum):
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    OVERDUE = "overdue"


class SessionStatus(str, enum.Enum):
    ACTIVE = "active"
    PROCESSING = "processing"
    GRADED = "graded"
    FAILED = "failed"


class EventDirection(str, enum.Enum):
    CLIENT = "client"
    SERVER = "server"
    SYSTEM = "system"


class TurnSpeaker(str, enum.Enum):
    REP = "rep"
    AI = "ai"


class ReviewReason(str, enum.Enum):
    LENIENT_AI = "lenient_ai"
    HARSH_AI = "harsh_ai"
    POLICY_OVERRIDE = "policy_override"
    MANAGER_COACHING = "manager_coaching"
