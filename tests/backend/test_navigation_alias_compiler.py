from uuid import uuid4

from app.domains.asset_compiler.navigation_aliases import build_navigation_aliases
from app.infrastructure.db.models.crawl import MenuNode


def test_build_navigation_aliases_emits_title_leaf_and_chain_when_chain_complete():
    root_id = uuid4()
    middle_id = uuid4()
    leaf_id = uuid4()
    aliases = build_navigation_aliases(
        page_title="指标管理",
        route_path="/front/database/configManage/indicesManage",
        menu_topology=[
            MenuNode(id=root_id, label="数据库", depth=0, sort_order=1, parent_id=None),
            MenuNode(id=middle_id, label="配置管理", depth=1, sort_order=1, parent_id=root_id),
            MenuNode(id=leaf_id, label="指标管理", depth=2, sort_order=1, parent_id=middle_id),
        ],
    )

    assert {item.alias_type for item in aliases} == {"page_title", "menu_leaf", "menu_chain"}
    assert any(item.display_chain == "数据库 -> 配置管理 -> 指标管理" for item in aliases)


def test_build_navigation_aliases_downgrades_to_leaf_when_parent_chain_is_broken():
    aliases = build_navigation_aliases(
        page_title="指标管理",
        route_path="/target",
        menu_topology=[
            MenuNode(label="数据库", depth=0, sort_order=1),
            MenuNode(label="指标管理", depth=2, sort_order=11, route_path="/target"),
        ],
    )

    page_title_alias = next(item for item in aliases if item.alias_type == "page_title")
    leaf_alias = next(item for item in aliases if item.alias_type == "menu_leaf")

    assert page_title_alias.display_chain == "指标管理"
    assert page_title_alias.chain_complete is False
    assert leaf_alias.chain_complete is False
    assert not any(item.alias_type == "menu_chain" for item in aliases)


def test_build_navigation_aliases_dedupes_repeated_menu_nodes():
    root_id = uuid4()
    middle_id = uuid4()
    leaf_id = uuid4()
    aliases = build_navigation_aliases(
        page_title="指标管理",
        route_path="/front/database/configManage/indicesManage",
        menu_topology=[
            MenuNode(id=root_id, label="数据库", depth=0, sort_order=1, parent_id=None),
            MenuNode(id=middle_id, label="配置管理", depth=1, sort_order=1, parent_id=root_id),
            MenuNode(id=middle_id, label="配置管理", depth=1, sort_order=1, parent_id=root_id),
            MenuNode(id=leaf_id, label="指标管理", depth=2, sort_order=1, parent_id=middle_id),
            MenuNode(id=leaf_id, label="指标管理", depth=2, sort_order=1, parent_id=middle_id),
        ],
    )

    chain_aliases = [item for item in aliases if item.alias_type == "menu_chain"]
    assert len(chain_aliases) == 1
    assert chain_aliases[0].alias_text == "数据库 -> 配置管理 -> 指标管理"


def test_build_navigation_aliases_does_not_synthesize_cross_branch_chain():
    root_a = uuid4()
    child_a = uuid4()
    root_b = uuid4()
    leaf_b = uuid4()

    aliases = build_navigation_aliases(
        page_title="目标页面",
        route_path="/target",
        menu_topology=[
            MenuNode(id=root_a, label="根A", depth=0, sort_order=1, parent_id=None),
            MenuNode(id=child_a, label="子A", depth=1, sort_order=1, parent_id=root_a),
            MenuNode(id=root_b, label="根B", depth=0, sort_order=2, parent_id=None),
            MenuNode(id=leaf_b, label="叶B", depth=2, sort_order=1, parent_id=root_b, route_path="/target"),
        ],
    )

    leaf_alias = next(item for item in aliases if item.alias_type == "menu_leaf")
    assert leaf_alias.alias_text == "叶B"
    assert leaf_alias.chain_complete is False
    assert not any(item.alias_type == "menu_chain" for item in aliases)
    assert not any(item.alias_text == "根A -> 子A -> 叶B" for item in aliases)


def test_build_navigation_aliases_treats_single_root_node_as_complete_chain():
    aliases = build_navigation_aliases(
        page_title="系统设置",
        route_path="/settings",
        menu_topology=[MenuNode(label="系统设置", depth=0, sort_order=1, parent_id=None)],
    )

    page_title_alias = next(item for item in aliases if item.alias_type == "page_title")
    leaf_alias = next(item for item in aliases if item.alias_type == "menu_leaf")
    chain_alias = next(item for item in aliases if item.alias_type == "menu_chain")
    assert page_title_alias.chain_complete is True
    assert leaf_alias.chain_complete is True
    assert chain_alias.chain_complete is True
    assert chain_alias.alias_text == leaf_alias.leaf_text


def test_build_navigation_aliases_sets_page_title_leaf_none_when_menus_empty():
    aliases = build_navigation_aliases(
        page_title="系统设置",
        route_path="/settings",
        menu_topology=[],
    )

    page_title_alias = next(item for item in aliases if item.alias_type == "page_title")
    assert page_title_alias.leaf_text is None
    assert page_title_alias.display_chain is None


def test_build_navigation_aliases_prefers_leaf_matching_route_path():
    root_a = uuid4()
    leaf_a = uuid4()
    root_b = uuid4()
    mid_b = uuid4()
    leaf_b = uuid4()

    aliases = build_navigation_aliases(
        page_title="A页面",
        route_path="/a",
        menu_topology=[
            MenuNode(id=root_a, label="根A", depth=0, sort_order=1, parent_id=None),
            MenuNode(id=leaf_a, label="叶A", depth=1, sort_order=1, parent_id=root_a, route_path="/a"),
            MenuNode(id=root_b, label="根B", depth=0, sort_order=2, parent_id=None),
            MenuNode(id=mid_b, label="中B", depth=1, sort_order=1, parent_id=root_b),
            MenuNode(id=leaf_b, label="叶B", depth=2, sort_order=1, parent_id=mid_b, route_path="/b"),
        ],
    )

    assert any(item.alias_type == "menu_leaf" and item.alias_text == "叶A" for item in aliases)
    assert any(item.alias_type == "menu_chain" and item.alias_text == "根A -> 叶A" for item in aliases)
    assert not any(item.alias_text == "叶B" for item in aliases)
    assert not any(item.alias_text == "根B -> 中B -> 叶B" for item in aliases)


def test_build_navigation_aliases_mixed_topology_keeps_target_leaf_without_menu_chain():
    root_a = uuid4()
    leaf_a = uuid4()
    root_b = uuid4()
    child_b = uuid4()

    aliases = build_navigation_aliases(
        page_title="A页面",
        route_path="/a",
        menu_topology=[
            MenuNode(id=root_b, label="根B", depth=0, sort_order=1, parent_id=None),
            MenuNode(id=child_b, label="子B", depth=1, sort_order=1, parent_id=root_b, route_path="/b"),
            MenuNode(id=root_a, label="根A", depth=0, sort_order=2, parent_id=None, route_path="/a"),
            MenuNode(id=leaf_a, label="叶A", depth=1, sort_order=2, parent_id=uuid4(), route_path="/a"),
        ],
    )

    leaf_alias = next(item for item in aliases if item.alias_type == "menu_leaf")
    assert leaf_alias.alias_text == "叶A"
    assert leaf_alias.chain_complete is False
    assert not any(item.alias_type == "menu_chain" for item in aliases)
    assert not any(item.alias_text == "根B -> 子B" for item in aliases)


def test_build_navigation_aliases_keeps_only_page_title_when_leaf_is_ambiguous_without_route_match():
    root_a = uuid4()
    leaf_a = uuid4()
    root_b = uuid4()
    leaf_b = uuid4()

    aliases = build_navigation_aliases(
        page_title="目标页面",
        route_path="/missing",
        menu_topology=[
            MenuNode(id=root_a, label="根A", depth=0, sort_order=1, parent_id=None),
            MenuNode(id=leaf_a, label="叶A", depth=1, sort_order=1, parent_id=root_a, route_path="/a"),
            MenuNode(id=root_b, label="根B", depth=0, sort_order=2, parent_id=None),
            MenuNode(id=leaf_b, label="叶B", depth=1, sort_order=1, parent_id=root_b, route_path="/b"),
        ],
    )

    assert [item.alias_type for item in aliases] == ["page_title"]
    assert aliases[0].leaf_text is None
    assert aliases[0].display_chain is None


def test_build_navigation_aliases_duplicate_semantic_chains_do_not_trigger_ambiguity():
    root_a1 = uuid4()
    leaf_a1 = uuid4()
    root_a2 = uuid4()
    leaf_a2 = uuid4()

    aliases = build_navigation_aliases(
        page_title="A页面",
        route_path="/missing",
        menu_topology=[
            MenuNode(id=root_a1, label="根A", depth=0, sort_order=1, parent_id=None),
            MenuNode(id=leaf_a1, label="叶A", depth=1, sort_order=1, parent_id=root_a1, route_path="/a"),
            MenuNode(id=root_a2, label="根A", depth=0, sort_order=1, parent_id=None),
            MenuNode(id=leaf_a2, label="叶A", depth=1, sort_order=1, parent_id=root_a2, route_path="/a"),
        ],
    )

    assert any(item.alias_type == "menu_leaf" and item.alias_text == "叶A" for item in aliases)
    assert any(item.alias_type == "menu_chain" and item.alias_text == "根A -> 叶A" for item in aliases)


def test_build_navigation_aliases_keeps_only_page_title_when_complete_and_broken_branches_are_mixed_without_route_match():
    root_a = uuid4()
    leaf_a = uuid4()
    root_b = uuid4()
    leaf_b = uuid4()

    aliases = build_navigation_aliases(
        page_title="目标页面",
        route_path="/missing",
        menu_topology=[
            MenuNode(id=root_a, label="根A", depth=0, sort_order=1, parent_id=None),
            MenuNode(id=leaf_a, label="叶A", depth=1, sort_order=1, parent_id=root_a, route_path="/a"),
            MenuNode(id=root_b, label="根B", depth=0, sort_order=2, parent_id=None),
            MenuNode(id=leaf_b, label="叶B", depth=2, sort_order=1, parent_id=root_b, route_path="/b"),
        ],
    )

    assert [item.alias_type for item in aliases] == ["page_title"]
    assert aliases[0].leaf_text is None
    assert aliases[0].display_chain is None


def test_build_navigation_aliases_reconstructs_chain_from_full_topology_with_separate_ancestor_rows():
    root_id = uuid4()
    middle_id = uuid4()
    leaf_id = uuid4()
    other_root = uuid4()
    other_leaf = uuid4()
    page_id = uuid4()

    aliases = build_navigation_aliases(
        page_title="指标管理",
        route_path="/target",
        menu_topology=[
            MenuNode(id=root_id, label="数据库", depth=0, sort_order=1, parent_id=None, page_id=None),
            MenuNode(id=middle_id, label="配置管理", depth=1, sort_order=1, parent_id=root_id, page_id=None),
            MenuNode(
                id=leaf_id,
                label="指标管理",
                depth=2,
                sort_order=1,
                parent_id=middle_id,
                page_id=page_id,
                route_path="/target",
            ),
            MenuNode(id=other_root, label="其他根", depth=0, sort_order=2, parent_id=None),
            MenuNode(id=other_leaf, label="其他页", depth=1, sort_order=1, parent_id=other_root, route_path="/other"),
        ],
    )

    assert any(item.alias_type == "menu_leaf" and item.alias_text == "指标管理" for item in aliases)
    assert any(item.alias_type == "menu_chain" and item.alias_text == "数据库 -> 配置管理 -> 指标管理" for item in aliases)
