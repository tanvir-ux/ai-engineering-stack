"""Authorisation policy: roles -> document classes and tool permissions, plus per-user overrides.

Kept as plain data and pure functions so it is trivial to test and to audit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Which document classifications each role may read.
ROLE_CLASSES: dict[str, frozenset[str]] = {
    "contractor": frozenset({"public"}),
    "employee": frozenset({"public", "internal"}),
    "hr": frozenset({"public", "internal", "hr"}),
    "finance": frozenset({"public", "internal", "finance"}),
    "security": frozenset({"public", "internal", "security"}),
    "admin": frozenset({"public", "internal", "hr", "finance", "security"}),
}

# Which permissions each role holds. Tools declare the permission they need (TOOL_PERMISSION).
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "contractor": frozenset({"docs:read"}),
    "employee": frozenset({"docs:read", "tickets:read", "tickets:write"}),
    "hr": frozenset({"docs:read", "tickets:read", "tickets:write"}),
    "finance": frozenset({"docs:read", "tickets:read", "tickets:write"}),
    "security": frozenset({"docs:read", "tickets:read", "tickets:write", "stats:read"}),
    "admin": frozenset({"docs:read", "tickets:read", "tickets:write", "stats:read"}),
}

TOOL_PERMISSION: dict[str, str] = {
    "search_documents": "docs:read",
    "get_document": "docs:read",
    "list_my_tickets": "tickets:read",
    "ticket_stats": "stats:read",
    "create_ticket": "tickets:write",
}

# Tools that change state: the orchestration layer pauses for human approval before running them.
WRITE_TOOLS: frozenset[str] = frozenset({"create_ticket"})

# Per-user overrides, keyed by e-mail. `deny` always wins over what roles grant.
USER_OVERRIDES: dict[str, dict[str, frozenset[str]]] = {
    "hugo.martin@meridian.example": {"deny": frozenset({"tickets:write"})},
}


@dataclass(frozen=True)
class Principal:
    sub: str
    email: str
    name: str
    roles: tuple[str, ...]
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def classes(self) -> frozenset[str]:
        return classes_for(self.roles)

    @property
    def permissions(self) -> frozenset[str]:
        return permissions_for(self.roles, self.email)

    def can_use(self, tool: str) -> bool:
        return can_use_tool(self, tool)


def classes_for(roles: tuple[str, ...] | list[str]) -> frozenset[str]:
    out: set[str] = set()
    for r in roles:
        out |= ROLE_CLASSES.get(r, frozenset())
    return frozenset(out)


def permissions_for(roles: tuple[str, ...] | list[str], email: str = "") -> frozenset[str]:
    out: set[str] = set()
    for r in roles:
        out |= ROLE_PERMISSIONS.get(r, frozenset())
    ov = USER_OVERRIDES.get(email.lower(), {})
    out |= ov.get("allow", frozenset())
    out -= ov.get("deny", frozenset())
    return frozenset(out)


def can_use_tool(principal: Principal, tool: str) -> bool:
    needed = TOOL_PERMISSION.get(tool)
    return needed is not None and needed in principal.permissions
