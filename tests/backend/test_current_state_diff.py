from __future__ import annotations

import pytest

from app.domains.asset_compiler import current_state_diff


def _build_fingerprint(
    *,
    route_path: str,
    page_title: str = "Title",
    menu_chain: list[str] | None = None,
    key_elements: list[dict[str, str]] | None = None,
) -> current_state_diff.PageSemanticFingerprint:
    return current_state_diff.PageSemanticFingerprint.from_components(
        route_path=route_path,
        page_title=page_title,
        menu_chain=menu_chain or [],
        key_elements=key_elements or [],
    )


def test_no_change_detected() -> None:
    active = _build_fingerprint(
        route_path="/home",
        page_title="Home",
        menu_chain=["Dashboard"],
        key_elements=[{"kind": "button", "role": "button", "text": "Submit"}],
    )
    draft = _build_fingerprint(
        route_path="/home",
        page_title="Home",
        menu_chain=["Dashboard"],
        key_elements=[{"kind": "button", "role": "button", "text": "Submit"}],
    )

    diff = current_state_diff.compare_semantic_states(active=[active], draft=[draft])

    assert not diff.has_changes
    assert diff.added_routes == set()
    assert diff.deleted_routes == set()
    assert diff.changed_routes == set()


def test_added_route_detected() -> None:
    draft = _build_fingerprint(route_path="/new", page_title="New")

    diff = current_state_diff.compare_semantic_states(active=[], draft=[draft])

    assert diff.has_changes
    assert diff.added_routes == {"/new"}
    assert diff.deleted_routes == set()
    assert diff.changed_routes == set()


def test_deleted_route_detected() -> None:
    active = _build_fingerprint(route_path="/old", page_title="Old")

    diff = current_state_diff.compare_semantic_states(active=[active], draft=[])

    assert diff.has_changes
    assert diff.added_routes == set()
    assert diff.deleted_routes == {"/old"}
    assert diff.changed_routes == set()


def test_changed_route_detects_key_element_update() -> None:
    active = _build_fingerprint(
        route_path="/settings",
        page_title="Settings",
        key_elements=[{"kind": "button", "role": "button", "text": "Submit"}],
    )
    draft = _build_fingerprint(
        route_path="/settings",
        page_title="Settings",
        key_elements=[{"kind": "button", "role": "button", "text": "Confirm"}],
    )

    diff = current_state_diff.compare_semantic_states(active=[active], draft=[draft])

    assert diff.has_changes
    assert diff.added_routes == set()
    assert diff.deleted_routes == set()
    assert diff.changed_routes == {"/settings"}


def test_direct_instantiation_normalizes_values() -> None:
    fingerprint = current_state_diff.PageSemanticFingerprint(
        route_path="  /about  ",
        page_title="  About Page ",
        menu_chain=(" Section ", "", "Overview"),
        key_elements=(
            {"kind": "Button", "role": "button", "text": " Submit "},
            {"kind": "button", "role": "button", "text": "Submit"},
        ),
    )

    assert fingerprint.route_path == "/about"
    assert fingerprint.page_title == "About Page"
    assert fingerprint.menu_chain == ("Section", "Overview")
    assert tuple((el.kind, el.role, el.text) for el in fingerprint.key_elements) == (
        ("Button", "button", "Submit"),
        ("button", "button", "Submit"),
    )


def test_duplicate_key_elements_deduped() -> None:
    fingerprint = _build_fingerprint(
        route_path="/dup",
        key_elements=[
            {"kind": "button", "role": "button", "text": "Submit"},
            {"kind": "button", "role": "button", "text": "Submit"},
            {"kind": "button", "role": "button", "text": "Cancel"},
        ],
    )

    assert tuple((el.kind, el.role, el.text) for el in fingerprint.key_elements) == (
        ("button", "button", "Cancel"),
        ("button", "button", "Submit"),
    )


def test_compare_semantic_states_handles_unordered_input() -> None:
    active = _build_fingerprint(route_path="/a")
    unchanged = _build_fingerprint(route_path="/b")
    draft = _build_fingerprint(route_path="/b", page_title="Updated")

    diff = current_state_diff.compare_semantic_states(
        active=[active, unchanged],
        draft=[draft, active],
    )

    assert diff.added_routes == set()
    assert diff.deleted_routes == set()
    assert diff.changed_routes == {"/b"}


def test_compare_semantic_states_rejects_blank_route() -> None:
    invalid = _build_fingerprint(route_path=" ")

    with pytest.raises(ValueError):
        current_state_diff.compare_semantic_states(active=[invalid], draft=[])


def test_compare_semantic_states_rejects_duplicate_route() -> None:
    original = _build_fingerprint(route_path="/duplicate")
    duplicate = _build_fingerprint(route_path="/duplicate")

    with pytest.raises(ValueError):
        current_state_diff.compare_semantic_states(active=[original, duplicate], draft=[])


def test_invalid_key_element_raises() -> None:
    with pytest.raises(TypeError):
        _build_fingerprint(route_path="/bad", key_elements=[object()])
