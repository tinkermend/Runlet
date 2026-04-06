from app.domains.asset_compiler.navigation_aliases import build_navigation_aliases
from app.infrastructure.db.models.crawl import MenuNode


def test_build_navigation_aliases_emits_title_leaf_and_chain_when_chain_complete():
    aliases = build_navigation_aliases(
        page_title="指标管理",
        route_path="/front/database/configManage/indicesManage",
        menus=[
            MenuNode(label="数据库", depth=0, sort_order=1),
            MenuNode(label="配置管理", depth=1, sort_order=1),
            MenuNode(label="指标管理", depth=2, sort_order=1),
        ],
    )

    assert {item.alias_type for item in aliases} == {"page_title", "menu_leaf", "menu_chain"}
    assert any(item.display_chain == "数据库 -> 配置管理 -> 指标管理" for item in aliases)


def test_build_navigation_aliases_keeps_leaf_when_parent_chain_missing():
    aliases = build_navigation_aliases(
        page_title="指标管理",
        route_path="/front/database/configManage/indicesManage",
        menus=[MenuNode(label="指标管理", depth=0, sort_order=11)],
    )

    assert any(item.alias_type == "menu_leaf" and item.chain_complete is False for item in aliases)
    assert not any(item.alias_type == "menu_chain" for item in aliases)


def test_build_navigation_aliases_dedupes_repeated_menu_nodes():
    aliases = build_navigation_aliases(
        page_title="指标管理",
        route_path="/front/database/configManage/indicesManage",
        menus=[
            MenuNode(label="数据库", depth=0, sort_order=1),
            MenuNode(label="配置管理", depth=1, sort_order=1),
            MenuNode(label="配置管理", depth=1, sort_order=1),
            MenuNode(label="指标管理", depth=2, sort_order=1),
            MenuNode(label="指标管理", depth=2, sort_order=1),
        ],
    )

    chain_aliases = [item for item in aliases if item.alias_type == "menu_chain"]
    assert len(chain_aliases) == 1
    assert chain_aliases[0].alias_text == "数据库 -> 配置管理 -> 指标管理"
