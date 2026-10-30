class ITSMError(Exception):
    """Parent of every error in our system."""


class InvalidStateTransitionError(ITSMError):
    """Tried to move an incident to a stage that isn't allowed."""


class UnauthorizedActionError(ITSMError):
    """A user tried to do something their role doesn't allow."""


class InvalidIncidentError(ITSMError):
    """The incident doesn't exist or is malformed."""


class NoEligibleTechnicianError(ITSMError):
    """No technician could take this incident."""


class TechnicianUnavailableError(ITSMError):
    """The technician is on leave, inactive, or otherwise unavailable."""


class TechnicianWorkloadExceededError(ITSMError):
    """A technician already has too many incidents."""


class MissingSLAError(ITSMError):
    """No SLA is configured for this priority or service."""


class ServiceNotFoundError(ITSMError):
    """The affected IT service doesn't exist."""


class DuplicateIncidentError(ITSMError):
    """This incident looks like a duplicate."""


class ValidationError(ITSMError):
    """Some input was invalid."""