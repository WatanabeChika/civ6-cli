"""Offline visual gallery for terminal screenshot regression checks.

This script never connects to FireTuner.  It feeds representative, player-
visible records through the same production renderers used by the CLI.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from civ6_cli.commands import show_help
from civ6_cli.game import PlayerStatus, Unit
from civ6_cli.map_view import MapArea, hex_distance, render_map
from civ6_cli.overview import CitySummary, Overview, ResearchProgress, render_overview
from civ6_cli.records import parse_records
from civ6_cli.rendering import Display, hint, render_records, rule, table


def status_sample(display: Display) -> str:
    snapshot = Overview(
        PlayerStatus(96, 0, "阿拉伯", "萨拉丁", 513.6, 41.5, 23.2, 337.4, 3, 6),
        [Unit(7, "马穆鲁克", "UNIT_ARABIAN_MAMLUK", 31, 24, 2, 4, 82, 100)],
        [
            CitySummary(65536, "开罗", "31,24", 8, 21.6, "大学", 3, 49, 160, 10, 3, 4, -1, 6),
            CitySummary(65537, "麦地那", "35,22", 5, 13.2, "商人", 2, 34, 80, 7, 4, 3, 1, 4),
            CitySummary(65538, "大马士革", "28,27", 3, 8.7, "古典城墙", 7, 21, 80, 5, 2, 3, -1, 11),
        ],
        [
            ResearchProgress("tech", "教育", 219, 390, 5, True),
            ResearchProgress("civic", "外交部门", 183, 410, 8, False),
        ],
        {"income": "40.2", "maintenance": "14", "net": "26.2", "faith_per_turn": "39.1", "score": "196"},
        {"name": "中世纪", "score": "48", "dark": "64", "golden": "78"},
        ["大马士革宜居度不足。"],
        [
            "NOTIFICATION|type=NOTIFICATION_CHOOSE_PRODUCTION|blocking=yes|message=开罗需要选择生产项目",
            "NOTIFICATION|type=NOTIFICATION_DIPLOMACY_SESSION|blocking=no|message=日本希望讨论一项交易",
            "NOTIFICATION_COUNT|2",
        ],
    )
    return render_overview(snapshot, display)


def trade_sample(display: Display) -> str:
    body = render_records([
        "TRADE_CIV|2|日本",
        "TRADE_ECON|513|26|48|822|31|92",
        "TRADE_RESOURCE|丝绸|RESOURCE_SILK|奢侈|2|0",
        "TRADE_RESOURCE|铁|RESOURCE_IRON|战略|34|12",
        "TRADE_RESOURCE|马|RESOURCE_HORSES|战略|8|27",
        "TRADE_OPEN_BORDERS|no",
        "TRADE_ALLIANCE|yes|none",
        "TRADE_CITY|对方|65536|京都|9|yes",
        "TRADE_CITY|我方|65537|麦地那|5|no",
    ], display, title="可交易内容")
    return body + "\n" + hint("先试算：trade propose 2 test <give-/want-条款> [...]", display)


def units_sample(display: Display) -> str:
    rows = [
        [7, "马穆鲁克", "(31,24)", "2/4", "待命", "是", "82/100"],
        [12, "建造者", "(33,23)", "0/2", "行动力耗尽", "否", "100/100"],
        [18, "侦察兵", "(41,18)", "3/3", "自动探索", "否", "100/100"],
        [24, "商人", "(31,24)", "0/2", "执行商路", "否", "100/100"],
        [29, "弩手", "(29,25)", "0/2", "驻防/警戒", "否", "67/100"],
    ]
    return table(
        ["ID", "单位", "坐标", "移动力", "活动状态", "需指令", "生命值"],
        rows,
        display,
        title="己方单位 · 5",
        caption="1 个单位需要指令 · unit options <单位> 查看合法动作",
    )


def production_sample(display: Display) -> str:
    body = render_records([
        "CURRENT|city=65536|name=大学|type=BUILDING|progress=49|cost=160|turns=3",
        "PRODUCTION_UNIT|name=建造者|type=UNIT_BUILDER|cost=80|turns=4|requirements=无额外条件|combat=0|ranged=0|moves=2|charges=3|maintenance=0|effect=可修建地块改良",
        "PRODUCTION_UNIT|name=马穆鲁克|type=UNIT_ARABIAN_MAMLUK|cost=180|turns=8|requirements=科技：马镫|combat=48|ranged=0|moves=4|charges=0|maintenance=3|effect=回合结束后自动恢复生命值",
        "PRODUCTION_BUILDING|name=市场|type=BUILDING_MARKET|is_wonder=no|cost=120|turns=6|requirements=区域：商业中心|effect=金币 +3；贸易路线容量 +1",
        "PRODUCTION_BUILDING|name=佩特拉古城|type=BUILDING_PETRA|is_wonder=yes|cost=400|turns=19|requirements=必须位于沙漠|effect=本城沙漠单元格食物 +2、金币 +2、生产力 +1",
        "PRODUCTION_DISTRICT|name=学院|type=DISTRICT_CAMPUS|cost=210|turns=10|requirements=占用人口区域容量|effect=提供科技相邻加成",
        "PRODUCTION_PROJECT|name=学院研究资助|type=PROJECT_CAMPUS_RESEARCH_GRANTS|cost=90|turns=5|requirements=区域：学院|effect=提供科技值与大科学家点数",
        "PURCHASE_GOLD|UNIT|name=建造者|cost=320|affordable=yes|details=可修建地块改良",
        "PURCHASE_GOLD|BUILDING|name=粮仓|cost=260|affordable=yes|details=住房 +2；食物 +1",
        "PURCHASE_GOLD|BUILDING|name=大学|cost=920|affordable=no|details=科技 +4；大科学家点数 +1",
        "PURCHASE_FAITH|UNIT|name=传教士|cost=150|affordable=yes|details=传播宗教 3 次",
        "PURCHASE_FAITH|UNIT|name=使徒|cost=400|affordable=no|details=传播宗教并参与神学战斗",
    ], display, title="城市生产与购买")
    return body + "\n" + hint(
        "选择内部类型后：city produce 65536 <unit|building|district|project> <TYPE> [x y]；"
        "购买使用 city buy 65536 <gold|faith> <unit|building|district> <TYPE> [x y]",
        display,
    )


def routes_sample(display: Display) -> str:
    body = table(
        ["目的城市", "文明", "目标坐标", "单程距离", "预计回合", "我方收益/回合", "对方收益/回合"],
        [
            ["京都", "日本", "(41,18)", "8", "24", "食3 产2 金4", "金2 科1"],
            ["日内瓦", "日内瓦", "(46,22)", "12", "36", "金5 科2 文1", "金3"],
            ["麦地那", "国内", "(35,22)", "5", "30", "食4 产3", "食1 产1"],
        ],
        display,
        title="合法商路",
        caption="收益为每回合；持续时间按路线往返与游戏速度估计",
    )
    extras = render_records([
        "ROUTE_EXTRA|city=京都|details=已有贸易站|pressure_out=12 伊斯兰教|pressure_in=3 神道教",
        "ROUTE_EXTRA|city=日内瓦|details=城邦、完成城邦任务|pressure_out=8 伊斯兰教|pressure_in=0 无",
    ], display)
    return body + "\n" + extras + "\n" + hint(
        "执行：unit trade-route 24 <目标x> <目标y>；迁移：unit teleport 24 <己方城市x> <己方城市y>",
        display,
    )


def todo_sample(display: Display) -> str:
    return render_records([
        "TODO|type=ENDTURN_BLOCKING_PRODUCTION|message=开罗需要选择生产项目|next=city production 开罗",
        "TODO|type=ENDTURN_BLOCKING_UNITS|message=1 个单位仍需要指令|next=unit list / unit options <单位> / unit skip <单位>",
        "DIPLO_SESSION|17|2|日本|北条时宗|希望交换奢侈资源|传入会面|positive/negative|no",
        "PENDING_DEAL|2|日本|北条时宗",
        "DEAL_ITEM|2|日本|RESOURCE|丝绸|1|30",
    ], display, title="回合待办与外部响应")


def map_sample(display: Display) -> str:
    lines = []
    center_x, center_y, radius = 10, 10, 2
    for y in range(center_y - radius, center_y + radius + 1):
        for x in range(center_x - radius, center_x + radius + 1):
            if hex_distance(center_x, center_y, x, y) > radius:
                continue
            base = f"MAP_TILE|position={x},{y}|layout_x={x}|layout_y={y}"
            if (x, y) == (8, 10):
                lines.append(base + "|visibility=unexplored")
                continue
            if (x, y) in {(9, 9), (10, 8)}:
                lines.append(base + "|visibility=fog|terrain=TERRAIN_PLAINS|terrain_name=平原|hills=no")
                continue
            fields = "|visibility=visible|terrain=TERRAIN_GRASS|terrain_name=草原|hills=no|feature=none|feature_name=none|resource=none|resource_name=none|improvement_name=none|site=none|site_name=none|district_name=none|wonder_name=none|wonder_complete=none|owner=unowned|river=no|city_name=none|units=none|own_units=no|other_units=no"
            if (x, y) == (10, 10):
                fields = fields.replace("district_name=none", "district_name=市中心").replace("city_name=none", "city_name=开罗").replace("units=none", "units=马穆鲁克#7（阿拉伯 / P0）").replace("own_units=no", "own_units=yes").replace("owner=unowned", "owner=阿拉伯")
            elif (x, y) == (11, 10):
                fields = fields.replace("resource=none", "resource=RESOURCE_IRON").replace("resource_name=none", "resource_name=铁").replace("improvement_name=none", "improvement_name=矿山")
            elif (x, y) == (9, 10):
                fields = fields.replace("site=none", "site=barbarian_camp").replace("site_name=none", "site_name=蛮族哨站").replace("improvement_name=none", "improvement_name=蛮族哨站")
            elif (x, y) == (10, 11):
                fields = fields.replace("wonder_name=none", "wonder_name=佩特拉古城").replace("wonder_complete=none", "wonder_complete=yes")
            elif (x, y) == (11, 9):
                fields = fields.replace("units=none", "units=武士#42（日本 / P2）").replace("other_units=no", "other_units=yes").replace("owner=unowned", "owner=日本")
            elif (x, y) == (10, 9):
                fields = fields.replace("river=no", "river=yes")
            lines.append(base + fields)
    return render_map(MapArea(center_x, center_y, radius, parse_records(lines)), display)


SAMPLES = {
    "status": status_sample,
    "trade-options": trade_sample,
    "unit-list": units_sample,
    "city-production": production_sample,
    "unit-routes": routes_sample,
    "map-show": map_sample,
    "turn-todo": todo_sample,
}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--width", type=int, default=100)
    parser.add_argument("--color", choices=("always", "never"), default="always")
    parser.add_argument("--ascii", action="store_true")
    parser.add_argument("--sample", choices=("all", "help-trade", *SAMPLES), default="all")
    args = parser.parse_args()
    display = Display(args.width, args.ascii, args.color == "always")

    selected = ["status", "help-trade", "trade-options", "unit-list", "city-production", "unit-routes", "map-show", "turn-todo"] if args.sample == "all" else [args.sample]
    for index, name in enumerate(selected):
        if index:
            print()
        print(rule(name, display))
        if name == "help-trade":
            show_help(["trade"], display)
        else:
            print(SAMPLES[name](display))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
