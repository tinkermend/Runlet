import pytest
from pydantic import ValidationError

from app.domains.crawler_service.navigation_targets import (
    NavigationTarget,
    NavigationTargetRegistry,
)
from app.domains.crawler_service.schemas import NavigationTargetResult


def test_navigation_target_registry_dedups_by_kind_route_state_and_parent():
    registry = NavigationTargetRegistry(max_targets_per_route=4)

    first = NavigationTarget(
        target_kind="tab_switch",
        route_hint="/users",
        state_context={"active_tab": "enabled"},
        parent_target_key="page:/users",
    )
    second = NavigationTarget(
        target_kind="tab_switch",
        route_hint="/users",
        state_context={"active_tab": "enabled"},
        parent_target_key="page:/users",
    )

    first_decision = registry.add(first)
    second_decision = registry.add(second)

    assert first_decision.accepted is True
    assert first.materialization_status == "queued"
    assert second_decision.accepted is False
    assert second_decision.reason == "duplicate_target"
    assert second.materialization_status == "duplicate"
    assert len(registry.targets) == 1


def test_navigation_target_registry_rejects_when_route_budget_is_exhausted():
    registry = NavigationTargetRegistry(
        max_total_targets=8,
        max_targets_per_route=1,
        max_targets_per_kind=8,
        max_children_per_parent=8,
    )

    first = NavigationTarget(
        target_kind="tab_switch",
        route_hint="/users",
        state_context={"active_tab": "enabled"},
        parent_target_key="page:/users",
    )
    second = NavigationTarget(
        target_kind="open_modal",
        route_hint="/users",
        state_context={"modal_title": "create"},
        parent_target_key="page:/users",
    )

    assert registry.add(first).accepted is True
    decision = registry.add(second)

    assert decision.accepted is False
    assert decision.reason == "route_budget_exhausted"
    assert second.materialization_status == "blocked"
    assert second.rejection_reason == "route_budget_exhausted"


def test_navigation_target_registry_rejects_when_kind_budget_is_exhausted():
    registry = NavigationTargetRegistry(
        max_total_targets=8,
        max_targets_per_route=8,
        max_targets_per_kind=1,
        max_children_per_parent=8,
    )

    assert (
        registry.add(
            NavigationTarget(
                target_kind="tab_switch",
                route_hint="/users",
                state_context={"active_tab": "enabled"},
                parent_target_key="page:/users",
            )
        ).accepted
        is True
    )
    decision = registry.add(
        NavigationTarget(
            target_kind="tab_switch",
            route_hint="/roles",
            state_context={"active_tab": "disabled"},
            parent_target_key="page:/roles",
        )
    )

    assert decision.accepted is False
    assert decision.reason == "kind_budget_exhausted"


def test_navigation_target_registry_rejects_when_parent_budget_is_exhausted():
    registry = NavigationTargetRegistry(
        max_total_targets=8,
        max_targets_per_route=8,
        max_targets_per_kind=8,
        max_children_per_parent=1,
    )

    assert (
        registry.add(
            NavigationTarget(
                target_kind="menu_expand",
                route_hint="/settings",
                state_context={"section": "account"},
                parent_target_key="page:/settings",
            )
        ).accepted
        is True
    )
    decision = registry.add(
        NavigationTarget(
            target_kind="menu_expand",
            route_hint="/settings",
            state_context={"section": "security"},
            parent_target_key="page:/settings",
        )
    )

    assert decision.accepted is False
    assert decision.reason == "parent_budget_exhausted"


def test_navigation_target_registry_rejects_when_total_budget_is_exhausted():
    registry = NavigationTargetRegistry(
        max_total_targets=1,
        max_targets_per_route=8,
        max_targets_per_kind=8,
        max_children_per_parent=8,
    )

    assert registry.add(NavigationTarget(target_kind="page_route", route_hint="/users")).accepted is True
    decision = registry.add(NavigationTarget(target_kind="page_route", route_hint="/roles"))

    assert decision.accepted is False
    assert decision.reason == "total_budget_exhausted"


def test_navigation_target_registry_prefers_higher_priority_discovery_source_on_duplicate_merge():
    registry = NavigationTargetRegistry(max_targets_per_route=4)

    first = NavigationTarget(
        target_kind="tab_switch",
        route_hint="/users",
        state_context={"active_tab": "enabled"},
        parent_target_key="page:/users",
        discovery_source="network_request",
    )
    second = NavigationTarget(
        target_kind="tab_switch",
        route_hint="/users",
        state_context={"active_tab": "enabled"},
        parent_target_key="page:/users",
        discovery_source="runtime_route_hints",
    )

    assert registry.add(first).accepted is True

    decision = registry.add(second)

    assert decision.accepted is False
    assert decision.reason == "duplicate_target"
    assert len(registry.targets) == 1
    assert registry.targets[0].discovery_source == "runtime_route_hints"


def test_navigation_target_result_rejects_unknown_contract_values():
    with pytest.raises(ValidationError):
        NavigationTargetResult.model_validate(
            {
                "target_key": "x",
                "target_kind": "typo_kind",
                "route_hint": "/users",
                "materialization_status": "queued",
            }
        )

    with pytest.raises(ValidationError):
        NavigationTargetResult.model_validate(
            {
                "target_key": "x",
                "target_kind": "tab_switch",
                "route_hint": "/users",
                "materialization_status": "typo_status",
            }
        )

    with pytest.raises(ValidationError):
        NavigationTargetResult.model_validate(
            {
                "target_key": "x",
                "target_kind": "tab_switch",
                "route_hint": "/users",
                "materialization_status": "blocked",
                "rejection_reason": "typo_reason",
            }
        )


def test_navigation_target_result_rejects_impossible_status_and_extra_fields():
    with pytest.raises(ValidationError):
        NavigationTargetResult.model_validate(
            {
                "target_key": "x",
                "target_kind": "tab_switch",
                "route_hint": "/users",
                "materialization_status": "blocked",
                "rejection_reason": None,
            }
        )

    with pytest.raises(ValidationError):
        NavigationTargetResult.model_validate(
            {
                "target_key": "x",
                "target_kind": "tab_switch",
                "route_hint": "/users",
                "materialization_status": "queued",
                "unexpected_field": "boom",
            }
        )


def test_navigation_target_result_rejects_semantically_invalid_reason_detail_pairs():
    with pytest.raises(ValidationError):
        NavigationTargetResult.model_validate(
            {
                "target_key": "x",
                "target_kind": "tab_switch",
                "route_hint": "/users",
                "materialization_status": "duplicate",
                "rejection_reason": "route_budget_exhausted",
            }
        )

    with pytest.raises(ValidationError):
        NavigationTargetResult.model_validate(
            {
                "target_key": "x",
                "target_kind": "tab_switch",
                "route_hint": "/users",
                "materialization_status": "queued",
                "rejection_detail": "should-not-exist",
            }
        )

    with pytest.raises(ValidationError):
        NavigationTargetResult.model_validate(
            {
                "target_key": "x",
                "target_kind": "tab_switch",
                "route_hint": "/users",
                "materialization_status": "applied",
                "rejection_detail": "should-not-exist",
            }
        )
