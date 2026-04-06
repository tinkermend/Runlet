from __future__ import annotations

from dataclasses import dataclass

from app.infrastructure.db.models.crawl import MenuNode


@dataclass(frozen=True)
class NavigationAliasDraft:
    alias_type: str
    alias_text: str
    leaf_text: str | None
    display_chain: str | None
    chain_complete: bool


def build_navigation_aliases(
    *, page_title: str | None, route_path: str, menus: list[MenuNode]
) -> list[NavigationAliasDraft]:
    del route_path  # Kept for caller contract consistency.
    normalized_chain = _derive_menu_chain(menus)

    drafts: list[NavigationAliasDraft] = []
    if page_title:
        drafts.append(
            NavigationAliasDraft(
                alias_type="page_title",
                alias_text=page_title,
                leaf_text=normalized_chain[-1] if normalized_chain else page_title,
                display_chain=_format_chain(normalized_chain),
                chain_complete=bool(normalized_chain),
            )
        )

    if normalized_chain:
        drafts.append(
            NavigationAliasDraft(
                alias_type="menu_leaf",
                alias_text=normalized_chain[-1],
                leaf_text=normalized_chain[-1],
                display_chain=_format_chain(normalized_chain),
                chain_complete=len(normalized_chain) > 1,
            )
        )

    if len(normalized_chain) > 1:
        chain_text = _format_chain(normalized_chain)
        drafts.append(
            NavigationAliasDraft(
                alias_type="menu_chain",
                alias_text=chain_text or "",
                leaf_text=normalized_chain[-1],
                display_chain=chain_text,
                chain_complete=True,
            )
        )

    return _dedupe_drafts(drafts)


def _derive_menu_chain(menus: list[MenuNode]) -> list[str]:
    if not menus:
        return []

    first_node_by_depth: dict[int, MenuNode] = {}
    for node in sorted(menus, key=lambda item: (item.depth, item.sort_order, item.label)):
        label = (node.label or "").strip()
        if not label:
            continue
        if node.depth not in first_node_by_depth:
            first_node_by_depth[node.depth] = node

    if not first_node_by_depth:
        return []

    ordered_depths = sorted(first_node_by_depth)
    labels = [first_node_by_depth[depth].label.strip() for depth in ordered_depths]

    # Chain is complete only when it starts from depth=0 and has no depth gaps.
    has_gap = any(curr != prev + 1 for prev, curr in zip(ordered_depths, ordered_depths[1:]))
    starts_from_root = ordered_depths[0] == 0
    if has_gap or not starts_from_root:
        return [labels[-1]]

    return labels


def _format_chain(chain: list[str]) -> str | None:
    if not chain:
        return None
    return " -> ".join(chain)


def _dedupe_drafts(drafts: list[NavigationAliasDraft]) -> list[NavigationAliasDraft]:
    deduped: list[NavigationAliasDraft] = []
    seen: set[tuple[str, str, str | None, str | None, bool]] = set()
    for draft in drafts:
        key = (
            draft.alias_type,
            draft.alias_text,
            draft.leaf_text,
            draft.display_chain,
            draft.chain_complete,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(draft)
    return deduped
