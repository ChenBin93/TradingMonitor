from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class HealthStatus:
    healthy: bool
    timestamp: datetime
    components: dict[str, Any]
    errors: list[str]


class HealthChecker:
    def __init__(self):
        self._components: dict[str, callable] = {}
        self._last_status: HealthStatus | None = None

    def register(self, name: str, check_fn: callable):
        self._components[name] = check_fn

    def check(self) -> HealthStatus:
        components = {}
        errors = []
        for name, check_fn in self._components.items():
            try:
                result = check_fn()
                components[name] = {"healthy": result, "checked_at": datetime.now()}
                if not result:
                    errors.append(f"{name}: unhealthy")
            except Exception as e:
                components[name] = {"healthy": False, "error": str(e), "checked_at": datetime.now()}
                errors.append(f"{name}: {e}")
        status = HealthStatus(
            healthy=len(errors) == 0,
            timestamp=datetime.now(),
            components=components,
            errors=errors,
        )
        self._last_status = status
        return status

    def get_last_status(self) -> HealthStatus | None:
        return self._last_status
