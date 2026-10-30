from domain.exceptions import ValidationError


class Category:
    def __init__(self, name, description=""):
        name = (name or "").strip()
        if not name:
            raise ValidationError("Category name is required")
        self._name = name.upper()
        self._description = description
        self._active = True

    @property
    def name(self):
        return self._name

    @property
    def description(self):
        return self._description

    @property
    def is_active(self):
        return self._active

    def deactivate(self):
        self._active = False

    def activate(self):
        self._active = True


class CategoryRegistry:
    """Admins can add or retire categories without touching any other code."""

    DEFAULT_NAMES = (
        "Hardware", "Software", "Network", "Database", "Cloud",
        "Security", "Authentication", "Application", "Storage",
    )

    def __init__(self, names=()):
        self._categories = {}
        for name in names:
            self.add(name)

    @classmethod
    def default(cls):
        return cls(cls.DEFAULT_NAMES)

    def add(self, name, description=""):
        category = Category(name, description)
        if category.name in self._categories:
            raise ValidationError(f"Category '{category.name}' already exists")
        self._categories[category.name] = category
        return category

    def get(self, name):
        key = (name or "").strip().upper()
        if key not in self._categories:
            raise ValidationError(f"Unknown category '{name}'")
        return self._categories[key]

    def deactivate(self, name):
        self.get(name).deactivate()

    def active(self):
        return sorted(
            (c for c in self._categories.values() if c.is_active),
            key=lambda c: c.name,
        )