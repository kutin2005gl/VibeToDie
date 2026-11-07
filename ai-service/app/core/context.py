"""Who a run works for. Every tool runs with this user's permissions, never its own (mandates
`<permissions>`): the Go API gateway authenticates the user and forwards the identity."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RequestContext:
    user_id: str
    departments: tuple[str, ...]

    def in_any(self, departments: tuple[str, ...]) -> bool:
        return any(department in self.departments for department in departments)
