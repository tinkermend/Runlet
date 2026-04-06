from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True, order=True)
class KeyElementDescriptor:
    kind: str
    role: str
    text: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _normalize_text(self.kind))
        object.__setattr__(self, "role", _normalize_text(self.role))
        object.__setattr__(self, "text", _normalize_text(self.text))


KeyElementInput = Mapping[str, object] | KeyElementDescriptor


@dataclass(frozen=True, init=False)
class PageSemanticFingerprint:
    route_path: str
    page_title: str
    menu_chain: tuple[str, ...]
    key_elements: tuple[KeyElementDescriptor, ...]

    def __init__(
        self,
        *,
        route_path: object,
        page_title: object = "",
        menu_chain: Iterable[object] = (),
        key_elements: Iterable[KeyElementInput] = (),
    ) -> None:
        normalized_route = _normalize_text(route_path)
        normalized_title = _normalize_text(page_title)
        normalized_chain = tuple(
            label
            for label in (_normalize_text(label) for label in menu_chain)
            if label
        )
        normalized_elements = _normalize_key_elements(key_elements)

        object.__setattr__(self, "route_path", normalized_route)
        object.__setattr__(self, "page_title", normalized_title)
        object.__setattr__(self, "menu_chain", normalized_chain)
        object.__setattr__(self, "key_elements", normalized_elements)

    @classmethod
    def from_components(
        cls,
        *,
        route_path: str,
        page_title: str,
        menu_chain: Iterable[str],
        key_elements: Iterable[Mapping[str, object]],
    ) -> "PageSemanticFingerprint":
        return cls(
            route_path=route_path,
            page_title=page_title,
            menu_chain=tuple(menu_chain),
            key_elements=tuple(key_elements),
        )


@dataclass(frozen=True)
class SemanticStateDiff:
    added_routes: frozenset[str]
    deleted_routes: frozenset[str]
    changed_routes: frozenset[str]

    @property
    def has_changes(self) -> bool:
        return bool(self.added_routes or self.deleted_routes or self.changed_routes)


def compare_semantic_states(
    *,
    active: Iterable[PageSemanticFingerprint],
    draft: Iterable[PageSemanticFingerprint],
) -> SemanticStateDiff:
    active_by_route = _index_by_route(active)
    draft_by_route = _index_by_route(draft)
    added_routes = frozenset(route for route in draft_by_route if route not in active_by_route)
    deleted_routes = frozenset(route for route in active_by_route if route not in draft_by_route)
    changed_routes = frozenset(
        route
        for route in active_by_route.keys() & draft_by_route.keys()
        if active_by_route[route] != draft_by_route[route]
    )
    return SemanticStateDiff(
        added_routes=added_routes,
        deleted_routes=deleted_routes,
        changed_routes=changed_routes,
    )


def _index_by_route(
    fingerprints: Iterable[PageSemanticFingerprint],
) -> dict[str, PageSemanticFingerprint]:
    index: dict[str, PageSemanticFingerprint] = {}
    for fingerprint in fingerprints:
        route_path = fingerprint.route_path
        if not route_path:
            raise ValueError("route_path must be non-empty for all fingerprints")
        if route_path in index:
            raise ValueError(f"duplicate fingerprint for route_path {route_path}")
        index[route_path] = fingerprint
    return index


def _normalize_key_elements(
    elements: Iterable[KeyElementInput],
) -> tuple[KeyElementDescriptor, ...]:
    seen: set[KeyElementDescriptor] = set()
    for element in elements:
        descriptor = _build_key_element_descriptor(element)
        if descriptor is None:
            continue
        seen.add(descriptor)
    return tuple(sorted(seen))


def _build_key_element_descriptor(
    element: KeyElementInput,
) -> KeyElementDescriptor | None:
    if isinstance(element, KeyElementDescriptor):
        descriptor = element
    elif isinstance(element, Mapping):
        descriptor = KeyElementDescriptor(
            kind=element.get("kind", ""),
            role=element.get("role", ""),
            text=element.get("text", ""),
        )
    else:
        raise TypeError("key elements must be mappings or KeyElementDescriptor instances")

    if not (descriptor.kind or descriptor.role or descriptor.text):
        return None
    return descriptor


def _normalize_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
