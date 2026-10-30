from domain.enums import Role
from domain.exceptions import (
    ValidationError,
    TechnicianUnavailableError,
    TechnicianWorkloadExceededError,
)


class User:
    def __init__(self, user_id, name, roles):
        if not name or not name.strip():
            raise ValidationError("Name is required")
        self._user_id = user_id
        self._name = name
        self._roles = set(roles)
        self._active = True

    @property
    def user_id(self):
        return self._user_id

    @property
    def name(self):
        return self._name

    @property
    def is_active(self):
        return self._active

    def has_role(self, role):
        return role in self._roles

    def deactivate(self):
        self._active = False


class Employee(User):
    def __init__(self, user_id, name):
        super().__init__(user_id, name, {Role.EMPLOYEE})


class Administrator(User):
    def __init__(self, user_id, name):
        super().__init__(user_id, name, {Role.ADMIN})


class Technician(User):
    def __init__(self, user_id, name, skills, experience_years=0, max_workload=5):
        super().__init__(user_id, name, {Role.EMPLOYEE, Role.TECHNICIAN})
        if max_workload < 1:
            raise ValidationError("max_workload must be at least 1")
        if experience_years < 0:
            raise ValidationError("experience_years cannot be negative")
        self._skills = {s.lower() for s in skills}
        self._experience_years = experience_years
        self._max_workload = max_workload
        self._active_count = 0
        self._available = True

    @property
    def skills(self):
        return set(self._skills)

    @property
    def experience_years(self):
        return self._experience_years

    @property
    def max_workload(self):
        return self._max_workload

    @property
    def active_count(self):
        return self._active_count

    @property
    def is_available(self):
        return self._active and self._available

    def has_skill(self, skill):
        return skill.lower() in self._skills

    def set_available(self, available):
        self._available = available

    def can_take_more(self):
        return self.is_available and self._active_count < self._max_workload

    def take_incident(self):
        if not self.is_available:
            raise TechnicianUnavailableError(f"{self._name} is not available")
        if self._active_count >= self._max_workload:
            raise TechnicianWorkloadExceededError(f"{self._name} is at full capacity")
        self._active_count += 1

    def release_incident(self):
        if self._active_count > 0:
            self._active_count -= 1