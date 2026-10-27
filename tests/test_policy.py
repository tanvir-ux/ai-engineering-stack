from aistack.auth.policy import Principal, can_use_tool, classes_for, permissions_for


def test_employee_cannot_read_hr_or_security() -> None:
    assert classes_for(["employee"]) == {"public", "internal"}


def test_roles_union() -> None:
    assert classes_for(["employee", "hr"]) == {"public", "internal", "hr"}


def test_unknown_role_grants_nothing() -> None:
    assert classes_for(["made-up"]) == frozenset()
    assert permissions_for(["made-up"]) == frozenset()


def test_contractor_is_read_only() -> None:
    p = Principal("s", "eve.contractor@meridian.example", "Eve", ("contractor",))
    assert can_use_tool(p, "search_documents")
    assert not can_use_tool(p, "create_ticket")
    assert not can_use_tool(p, "list_my_tickets")


def test_per_user_deny_override_wins() -> None:
    normal = Principal("s", "alice.nguyen@meridian.example", "A", ("employee",))
    hugo = Principal("h", "hugo.martin@meridian.example", "H", ("employee",))
    assert can_use_tool(normal, "create_ticket")
    assert not can_use_tool(hugo, "create_ticket")
    assert can_use_tool(hugo, "search_documents")


def test_unknown_tool_is_denied() -> None:
    p = Principal("a", "a@x", "A", ("admin",))
    assert not can_use_tool(p, "drop_database")


def test_stats_only_for_security_and_admin() -> None:
    assert "stats:read" not in permissions_for(["employee"])
    assert "stats:read" in permissions_for(["security"])
    assert "stats:read" in permissions_for(["admin"])
