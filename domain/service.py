from domain.exceptions import ValidationError


class ITService:
    def __init__(self, service_id, name, criticality):
        if not name or not name.strip():
            raise ValidationError("Service name is required")
        if not 1 <= criticality <= 5:
            raise ValidationError("criticality must be between 1 and 5")
        self._service_id = service_id
        self._name = name
        self._criticality = criticality
        self._active = True

    @property
    def service_id(self):
        return self._service_id

    @property
    def name(self):
        return self._name

    @property
    def criticality(self):
        return self._criticality

    @property
    def is_active(self):
        return self._active

    def deactivate(self):
        self._active = False