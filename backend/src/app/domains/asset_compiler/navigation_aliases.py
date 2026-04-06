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
    normalized_chain, chain_complete = _derive_menu_chain(menus, route_path=route_path)

    drafts: list[NavigationAliasDraft] = []
    if page_title:
        drafts.append(
            NavigationAliasDraft(
                alias_type="page_title",
                alias_text=page_title,
                leaf_text=normalized_chain[-1] if normalized_chain else None,
                display_chain=_format_chain(normalized_chain),
                chain_complete=chain_complete,
            )
        )

    if normalized_chain:
        drafts.append(
            NavigationAliasDraft(
                alias_type="menu_leaf",
                alias_text=normalized_chain[-1],
                leaf_text=normalized_chain[-1],
                display_chain=_format_chain(normalized_chain),
                chain_complete=chain_complete,
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


def _derive_menu_chain(menus: list[MenuNode], *, route_path: str) -> tuple[list[str], bool]:
    labeled_nodes = [node for node in menus if (node.label or "").strip()]
    if not labeled_nodes:
        return [], False

    node_by_id = {node.id: node for node in labeled_nodes}

    child_count_by_parent_id: dict[object, int] = {}
    for node in labeled_nodes:
        if node.parent_id is None:
            continue
        child_count_by_parent_id[node.parent_id] = child_count_by_parent_id.get(node.parent_id, 0) + 1

    leaf_candidates = [node for node in labeled_nodes if child_count_by_parent_id.get(node.id, 0) == 0]
    if not leaf_candidates:
        leaf_candidates = list(labeled_nodes)

    ordered_candidates = sorted(
        leaf_candidates,
        key=lambda node: (
            0 if _route_matches(node.route_path, route_path) else 1,
            -node.depth,
            node.sort_order,
            node.label.strip(),
            str(node.id),
        ),
    )

    for candidate in ordered_candidates:
        chain, chain_complete = _derive_chain_for_candidate(
            candidate,
            node_by_id=node_by_id,
            nodes=labeled_nodes,
            route_path=route_path,
        )
        if chain:
            return chain, chain_complete

    return [], False


def _derive_chain_for_candidate(
    candidate: MenuNode,
    *,
    node_by_id: dict[object, MenuNode],
    nodes: list[MenuNode],
    route_path: str,
) -> tuple[list[str], bool]:
    lineage: list[MenuNode] = [candidate]
    visited = {candidate.id}
    current = candidate
    while current.parent_id is not None:
        parent = node_by_id.get(current.parent_id)
        if parent is None or parent.id in visited:
            return _derive_chain_from_depth_fallback(
                nodes,
                preferred_leaf=candidate,
                route_path=route_path,
            )
        lineage.insert(0, parent)
        visited.add(parent.id)
        current = parent

    depth_continuous = all(child.depth == parent.depth + 1 for parent, child in zip(lineage, lineage[1:]))
    starts_from_root = lineage[0].depth == 0
    if not starts_from_root or not depth_continuous:
        if candidate.parent_id is None:
            return _derive_chain_from_depth_fallback(
                nodes,
                preferred_leaf=candidate,
                route_path=route_path,
            )
        return [candidate.label.strip()], False
    return [node.label.strip() for node in lineage], True


def _derive_chain_from_depth_fallback(
    nodes: list[MenuNode],
    *,
    preferred_leaf: MenuNode,
    route_path: str,
) -> tuple[list[str], bool]:
    route_nodes = [node for node in nodes if _route_matches(node.route_path, route_path)]
    neutral_nodes = [node for node in nodes if node.route_path is None]
    candidate_pool = route_nodes + neutral_nodes
    if not candidate_pool:
        candidate_pool = list(nodes)

    first_node_by_depth: dict[int, MenuNode] = {}
    for node in sorted(
        candidate_pool,
        key=lambda item: (
            0 if _route_matches(item.route_path, route_path) else 1,
            item.sort_order,
            item.label.strip(),
            str(item.id),
        ),
    ):
        if node.depth not in first_node_by_depth:
            first_node_by_depth[node.depth] = node

    if preferred_leaf.depth not in first_node_by_depth:
        first_node_by_depth[preferred_leaf.depth] = preferred_leaf
    else:
        first_node_by_depth[preferred_leaf.depth] = min(
            [first_node_by_depth[preferred_leaf.depth], preferred_leaf],
            key=lambda item: (
                0 if _route_matches(item.route_path, route_path) else 1,
                item.sort_order,
                item.label.strip(),
                str(item.id),
            ),
        )

    ordered_depths = sorted(first_node_by_depth)
    labels = [first_node_by_depth[depth].label.strip() for depth in ordered_depths]
    has_gap = any(curr != prev + 1 for prev, curr in zip(ordered_depths, ordered_depths[1:]))
    starts_from_root = ordered_depths[0] == 0
    if not starts_from_root or has_gap:
        return [labels[-1]], False
    return labels, True


def _route_matches(node_route_path: str | None, target_route_path: str) -> bool:
    return bool(node_route_path) and node_route_path == target_route_path


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
