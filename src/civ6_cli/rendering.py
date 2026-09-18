"""One visual language for the linear Civilization VI terminal interface.

Rich owns layout and styling while the helpers in this module keep the command
handlers independent from terminal details.  All game text is inserted as
literal ``Text`` objects: FireTuner output can never become Rich markup or an
ANSI control sequence.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from io import StringIO
import os
import re
import shutil
import sys
import unicodedata
from typing import Iterable, Sequence

from rich import box
from rich.columns import Columns
from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from .records import parse_records


# A deliberately small 256-colour palette.  Gold is the Civ console voice;
# green/red/amber/blue are reserved for outcomes and game semantics.  Labels
# and chrome stay grey so a full screen does not become a colour chart.
ACCENT = "color(208)"
SUCCESS = "color(71)"
ERROR = "color(167)"
WARNING = "color(179)"
INFO = "color(110)"
DIM = "color(245)"
FAINT = "color(240)"
BORDER = "color(240)"
HEADING = f"bold {ACCENT}"


@dataclass(frozen=True)
class Display:
    width: int = 100
    ascii: bool = False
    color: bool = False

    @classmethod
    def terminal(cls, *, ascii: bool = False, color: str = "auto", width: int | None = None) -> Display:
        try:
            tty = bool(sys.stdout.isatty())
        except (AttributeError, ValueError):
            tty = False
        # An explicit CLI setting wins. In auto mode honour the standard
        # environment escape hatches without conflating them with --ascii.
        if color == "always":
            enabled = True
        elif color == "never" or os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
            enabled = False
        else:
            force = os.environ.get("FORCE_COLOR")
            enabled = force.casefold() not in {"0", "false"} if force is not None else tty
        return cls(width or shutil.get_terminal_size((100, 30)).columns, ascii, enabled)


def plain(value: object) -> str:
    # Game text must not inject terminal escape sequences or line breaks.
    text = re.sub(r"\[ICON_[^\]]+\]", "", str(value))
    return "".join(c if c.isprintable() else " " for c in text)


def cell_width(text: str) -> int:
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in {"W", "F"} else 1 for c in text)


def wrap_cells(text: str, width: int) -> list[str]:
    result, line, used = [], "", 0
    for char in plain(text):
        size = cell_width(char)
        if used + size > width and line:
            result.append(line)
            line, used = "", 0
        line += char
        used += size
    return result + [line]


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - cell_width(text))


def _console(display: Display, file) -> Console:
    # Rich treats a forced-colour stream with TERM=dumb as an 80-column dumb
    # terminal before consulting its explicit width. ``--color always`` and
    # ``--width`` are both deliberate overrides, so keep the former from
    # silently cancelling the latter. Auto colour still disables itself for
    # TERM=dumb in Display.terminal().
    environ = dict(os.environ)
    if display.color and environ.get("TERM") == "dumb":
        environ.pop("TERM")
    return Console(
        file=file,
        width=max(20, display.width),
        force_terminal=display.color,
        color_system="256" if display.color else None,
        no_color=not display.color,
        highlight=False,
        legacy_windows=False,
        safe_box=True,
        _environ=environ,
    )


def render_rich(renderables: Iterable[RenderableType], display: Display = Display()) -> str:
    """Render Rich objects to a printable string at the requested width."""
    stream = StringIO()
    console = _console(display, stream)
    for renderable in renderables:
        console.print(renderable)
    return stream.getvalue().rstrip("\n")


def inline(text: object, style: str, display: Display = Display()) -> str:
    """Render a styled fragment without a trailing newline (used by the map)."""
    if not display.color:
        return plain(text)
    stream = StringIO()
    _console(display, stream).print(Text(plain(text), style=style), end="")
    return stream.getvalue()


def rule(title: str, display: Display = Display(), *, style: str = HEADING) -> str:
    if display.ascii:
        label = f"-- {plain(title)} "
        return label + "-" * max(0, min(display.width, 80) - cell_width(label))
    return render_rich([Rule(Text(plain(title), style=style), align="left", style=BORDER)], display)


def panel(
    title: str,
    body: RenderableType | str,
    display: Display = Display(),
    *,
    subtitle: str | None = None,
    border_style: str = BORDER,
) -> str:
    content: RenderableType = Text(plain(body)) if isinstance(body, str) else body
    return render_rich([
        Panel(
            content,
            title=Text(plain(title), style=HEADING),
            subtitle=Text(plain(subtitle), style=DIM) if subtitle else None,
            title_align="left",
            subtitle_align="right",
            border_style=border_style,
            box=box.ASCII if display.ascii else box.ROUNDED,
            padding=(0, 1),
            expand=True,
        )
    ], display)


def status_line(role: str, message: str, display: Display = Display(), detail: str = "") -> str:
    roles = {
        "success": ("[OK]" if display.ascii else "✓", SUCCESS),
        "warning": ("[WARN]" if display.ascii else "!", WARNING),
        "error": ("[FAIL]" if display.ascii else "×", ERROR),
        "info": ("[INFO]" if display.ascii else "·", INFO),
        "step": (">", ACCENT),
    }
    glyph, style = roles.get(role, roles["info"])
    line = Text()
    line.append(glyph + " ", style=f"bold {style}")
    line.append(plain(message))
    if detail:
        line.append("  " + plain(detail), style=DIM)
    return render_rich([line], display)


def hint(text: str, display: Display = Display()) -> str:
    """A quiet, final next-step line with command-like fragments accented."""
    line = Text()
    cursor = 0
    for match in re.finditer(r"(?:status|help|turn|unit|city|research|government|policy|governor|envoy|dedication|religion|great-person|diplomacy|trade|spy|congress|map|report|session)(?: [\w<>|:/.-]+)*", plain(text)):
        line.append(plain(text)[cursor:match.start()], style=DIM)
        line.append(match.group(0), style=ACCENT)
        cursor = match.end()
    line.append(plain(text)[cursor:], style=DIM)
    return render_rich([line], display)


def _semantic_style(header: str, value: str, column: int) -> str:
    normalized = value.casefold()
    if header in {"完整命令", "下一步", "内部类型", "类型代码"} or normalized.startswith(("unit ", "city ", "trade ", "research ", "diplomacy ", "report ", "turn ")):
        return ACCENT
    if header in {"用途", "内容", "说明", "效果/详情", "详情", "建造条件", "消息"}:
        return DIM
    if header in {"需指令", "回合阻塞"}:
        return WARNING if value in {"是", "yes"} else DIM
    if header in {"交战", "敌军", "其他可见单位"}:
        return ERROR if value not in {"否", "no", "无", "none", "—"} else DIM
    if header in {"资源", "资源名称"} and value not in {"无", "none", "—", ""}:
        return SUCCESS
    if header in {"状态", "结论", "当前可购买", "可用"}:
        if any(token in normalized for token in ("失败", "拒绝", "不可", "战争", "敌")):
            return ERROR
        if any(token in normalized for token in ("警告", "待复查", "请求", "未知")):
            return WARNING
        if any(token in normalized for token in ("成功", "接受", "可用", "是")):
            return SUCCESS
    if header in {"关系", "文明", "领袖", "提供方", "外交支持", "可见性"}:
        return ERROR if any(token in value for token in ("战争", "敌对", "谴责")) else INFO
    if header in {"单位", "城市", "名称", "目的城市", "当前研究", "正在生产"}:
        return "bold"
    if header in {"ID", "玩家ID", "单位ID", "城市ID", "坐标", "目标坐标"}:
        return DIM
    if column == 0 and value in {"写", "读"}:
        return WARNING if value == "写" else INFO
    return ""


_NO_WRAP_HEADERS = {
    "读/写", "ID", "索引", "玩家ID", "单位ID", "城市ID", "商人ID", "坐标", "目标坐标",
    "生命值", "移动力", "回合", "剩余回合", "预计回合", "预计持续回合", "单程距离",
    "费用", "费用 / 时间", "当前可购买", "需指令", "回合阻塞", "已加速",
}

_PROSE_HEADERS = {
    "用途", "内容", "说明", "效果/详情", "详情", "建造条件", "消息", "条件 / 解锁",
    "普通/黑暗时代效果", "黄金/英雄时代效果", "黑暗时代效果", "能力", "奖励",
}

_WIDE_VALUE_HEADERS = {
    "完整命令", "下一步", "内部类型", "类型代码", "我方收益/回合", "对方收益/回合",
    "属性", "可见内容", "活动状态",
}


def _natural_widths(headers: Sequence[str], data: Sequence[Sequence[str]]) -> list[int]:
    """Measure content without turning that measurement into a hard column cap."""
    return [max(4, cell_width(header), *(cell_width(row[i]) for row in data)) for i, header in enumerate(headers)]


def _minimum_width(header: str, natural: int) -> int:
    """Return the useful minimum used to decide whether columns need bands."""
    header_width = max(4, cell_width(header))
    if header in _NO_WRAP_HEADERS:
        return natural
    if header in _PROSE_HEADERS:
        return max(header_width, 12)
    if header in _WIDE_VALUE_HEADERS:
        return max(header_width, 10)
    if header in {"名称", "单位", "城市", "目的城市", "文明", "领袖", "类型", "类别"}:
        return max(header_width, 6)
    return header_width


def _column_bands(headers: Sequence[str], widths: list[int], display: Display) -> list[list[int]]:
    if not widths:
        return []
    minimums = [_minimum_width(header, width) for header, width in zip(headers, widths)]
    border = 3 if display.ascii else 2
    bands: list[list[int]] = []
    band = [0]
    for index in range(1, len(widths)):
        proposed = band + [index]
        if sum(minimums[i] + 2 for i in proposed) + border > display.width and len(band) > 1:
            bands.append(band)
            band = [0, index]
        else:
            band = proposed
    bands.append(band)
    return bands


def rich_table(
    headers: list[str],
    rows: list[list[object]],
    display: Display = Display(),
    *,
    title: str | None = None,
    caption: str | None = None,
) -> RenderableType:
    """Build compact, width-aware listing tables with one semantic voice."""
    if not rows:
        return Text("（暂无可显示的信息）", style=DIM)
    data = [[plain(v) for v in row] for row in rows]
    if any(len(row) != len(headers) for row in data):
        raise ValueError("table row does not match header count")
    widths = _natural_widths(headers, data)
    rendered: list[RenderableType] = []
    bands = _column_bands(headers, widths, display)
    for band_number, indices in enumerate(bands, 1):
        listing = Table(
            title=Text(plain(title), style=HEADING) if title and len(bands) == 1 else None,
            caption=Text(plain(caption), style=DIM) if caption and band_number == len(bands) else None,
            caption_justify="left",
            box=box.ASCII if display.ascii else box.SIMPLE_HEAD,
            border_style=BORDER,
            header_style=f"bold {DIM}",
            padding=(0, 1),
            collapse_padding=True,
            show_edge=display.ascii,
            expand=True,
        )
        for index in indices:
            header = headers[index]
            no_wrap = header in _NO_WRAP_HEADERS
            minimum = _minimum_width(header, widths[index])
            if header in _PROSE_HEADERS:
                ratio = 4
            elif header in _WIDE_VALUE_HEADERS:
                ratio = 2
            else:
                ratio = None
            listing.add_column(
                plain(header),
                # Rich measures collapsed padding as one cell even on the
                # first column, whose left + right padding still uses two.
                # Reserve that missing cell without changing the UI padding.
                width=(widths[index] + (1 if index == indices[0] else 0)) if no_wrap else (minimum if ratio is not None else None),
                min_width=minimum if no_wrap else (None if ratio is not None else minimum),
                ratio=ratio,
                overflow="fold",
                no_wrap=no_wrap,
            )
        for row_values in data:
            listing.add_row(*[
                Text(row_values[index], style=_semantic_style(headers[index], row_values[index], index))
                for index in indices
            ])
        if len(bands) > 1:
            rendered.append(Text(f"字段 {band_number}/{len(bands)}", style=FAINT))
        rendered.append(listing)
    return Group(*rendered)


def table(headers: list[str], rows: list[list[object]], display: Display = Display(), **kwargs) -> str:
    return render_rich([rich_table(headers, rows, display, **kwargs)], display)


LABELS = {
    "tech_type": "当前科技代号", "tech_progress": "科技累计进度", "tech_cost": "科技费用",
    "civic_type": "当前市政代号", "civic_progress": "市政累计进度", "civic_cost": "市政费用",
    "era_name": "时代名称", "can_recruit": "可招募", "side": "提供方", "term": "交易条款", "reason": "限制原因",
    "city_id": "城市ID", "building_type": "建筑代号", "slot_index": "操作槽位", "can_slot": "可装入",
    "needs_orders": "需指令",
    "pressure_out": "向外宗教压力", "pressure_in": "向内宗教压力",
    "mission": "任务类型", "success": "成功率", "travel_turns": "旅行回合", "establish_turns": "建立情报网回合",
    "targets": "合法目标坐标", "source": "来源", "choices": "合法处置", "mode": "操作方式",
    "id": "ID", "name": "名称", "type": "类型", "position": "坐标", "moves": "移动力", "hp": "生命值",
    "charges": "次数", "combat": "近战强度", "ranged": "远程强度", "population": "人口",
    "food": "食物/回合", "production": "生产力/回合", "gold": "金币", "science": "科技", "culture": "文化", "faith": "信仰",
    "housing": "住房", "amenities": "现有宜居度", "amenities_needed": "所需宜居度", "amenities_surplus": "宜居度盈余", "growth_turns": "增长回合", "pillaged": "遭劫掠",
    "terrain": "地形", "feature": "地貌", "resource": "资源", "owner": "归属", "hills": "丘陵", "water": "水域", "appeal": "魅力值",
    "yields": "食/产/金/科/文/信", "turns": "剩余回合", "boosted": "已触发加速", "income": "毛收入/回合",
    "maintenance": "维护费/回合", "net": "净收入/回合", "amount": "库存", "per_turn": "每回合", "state": "状态",
    "domestic_gain": "国内获取/回合", "imports": "进口/回合", "bonus_gain": "奖励获取/回合", "gain": "总获取/回合",
    "unit_consumption": "单位消耗/回合", "power_consumption": "发电消耗/回合", "consumption": "总消耗/回合", "net_change": "库存净变化/回合",
    "war": "交战", "score": "分数", "military": "军力", "science_per_turn": "科技/回合", "culture_per_turn": "文化/回合",
    "favor": "外交支持", "grievances": "不满", "visibility": "可见性", "diplomatic_favor": "外交支持",
    "slot": "槽位", "slot_type": "槽位类型", "description": "说明", "available": "可用", "spent": "已花费",
    "city": "城市", "established": "已就任", "founded": "创立宗教", "pantheon": "万神殿", "majority": "主流宗教",
    "followers": "信徒", "diplo": "外交胜利点", "tourism": "旅游业绩", "international_tourists": "国际游客", "domestic_tourists": "国内游客",
    "majority_religion": "主流宗教", "religion_founder": "宗教创立文明",
    "class": "类别", "era": "时代", "cost": "费用/阈值", "claimant": "招募者", "gold_cost": "金币费用", "faith_cost": "信仰费用",
    "ability": "能力", "active": "主动能力", "passive": "被动能力", "great_works": "创作伟作", "my_points": "我方伟人点数", "progress": "进度", "blocking": "回合阻塞", "message": "消息", "trader": "商人ID",
    "from": "起点", "to": "终点", "destination_player": "目标玩家", "capacity": "容量", "active": "使用中",
    "improvement": "改良设施", "envoys": "已派使者", "suzerain": "宗主国ID", "rank": "等级", "operation": "任务", "total_turns": "任务总回合",
    "in_session": "会议中", "turns_until_next": "下次会议回合", "vote_costs": "投票费用", "dark_threshold": "黑暗阈值",
    "golden_threshold": "黄金阈值", "age": "时代状态", "cost_multiplier": "费用倍率", "priority": "优先级",
    "kind": "任务", "nearest_builder": "最近建造者", "distance": "距离", "hash": "类型Hash", "xp": "经验",
    "next": "下级经验", "stored": "待用升级", "unit": "单位ID", "hex_distance": "六边形距离",
    "target_exists": "目标存在", "target_water": "目标水域", "visible": "当前可见", "river": "沿河", "road": "道路",
    "district": "区域", "units": "单位", "city_name": "城市", "terrain_name": "地形名称", "resource_name": "资源名称",
    "feature_name": "地貌名称", "improvement_name": "改良名称", "district_name": "区域名称", "buildings": "子区域/建筑", "local_player": "本地玩家",
    "faith_per_turn": "信仰/回合", "own_units": "己方单位", "other_units": "其他单位",
    "wonder": "奇观", "wonder_name": "奇观", "wonder_complete": "奇观已完成", "is_wonder": "是否奇观", "complete": "已完成", "site": "特殊地点", "site_name": "特殊地点名称",
    "power_current": "当前电力", "power_required": "所需电力", "fully_powered": "电力充足", "activity": "当前状态",
    "requirements": "建造条件", "effect": "效果/详情", "details": "详情", "bombard": "轰炸强度", "range": "射程", "affordable": "当前可购买", "next": "下一步",
    "creator": "创作者", "building": "存放建筑", "occupied": "已占槽位", "empty": "空槽位", "total": "总槽位",
}

KINDS = {
    "TRADE_GREAT_WORK": "巨作交易选项", "TRADE_CAPTIVE": "俘虏间谍交易选项", "TRADE_AGREEMENT": "协议交易选项",
    "TRADE_NOTE": "交易说明", "DIPLO_NOTE": "会面说明", "CONGRESS_NOTE": "议会说明", "ERA_NOTE": "时代说明",
    "GOVERNMENT_FAVOR": "外交支持", "POLICY_NOTE": "政策说明",
    "GOVERNMENT_STATE": "政体状态", "GREAT_WORK_SOURCE": "待移动巨作", "GREAT_WORK_DEST": "巨作目标槽位",
    "KEEP_OPTION": "保留 / 跳过",
    "UNIT_STATE": "单位复查状态", "POS": "单位实际位置", "CONFIRMED": "已确认", "NOT_SET": "未设置为预期项目",
    "UNIT_MODE": "单位操作方式", "UNIT_OPERATION": "可选动作", "SPY_MISSION": "可执行间谍任务",
    "SPY_DESTINATION": "合法派遣目的地", "SPY_NOTE": "间谍提示", "CAPTURE_OPTION": "待处置城市",
    "ROUTE_EXTRA": "商路补充信息",
    "CURRENT_TECH": "当前科技", "CURRENT_CIVIC": "当前市政", "TECH": "可研究科技", "CIVIC": "可研究市政",
    "TREASURY": "国库", "STOCKPILE": "战略资源库存", "CIV": "文明关系", "MY_MILITARY": "我方军力",
    "GOVERNMENT": "政府", "POLICY_SLOTS": "政策槽位", "POLICY": "政策卡", "GOVERNOR_POINTS": "总督点数", "GOVERNOR": "总督",
    "MY_RELIGION": "宗教", "CITY_RELIGION": "城市宗教", "VICTORY": "胜利进展", "GREAT_PERSON": "伟人",
    "GREAT_WORK": "巨作", "GREAT_WORK_SLOT": "巨作空槽位", "GREAT_WORK_SUMMARY": "巨作汇总",
    "NOTIFICATION": "通知", "NOTIFICATION_COUNT": "通知数量", "BLOCKING": "回合待办", "ROUTE": "贸易路线",
    "TRADE_CAPACITY": "贸易容量", "TRADER": "商人", "RESOURCE": "已知资源", "RESOURCE_COUNT": "资源地块数量",
    "ENVOY_STATUS": "可用使者", "CITY_STATE": "城邦", "SPY": "间谍", "WORLD_CONGRESS": "世界议会", "ERA": "时代", "GAME_SPEED": "游戏速度",
    "BUILDER": "建造者", "TASK": "建造任务", "UNIT_DETAIL": "单位详情", "CITY_DETAIL": "城市详情",
    "DISTRICT": "城市区域", "WONDER": "城市奇观", "TILE": "地块", "CURRENT": "当前生产",
    "PRODUCTION_UNIT": "可生产单位", "PRODUCTION_BUILDING": "可生产建筑", "PRODUCTION_DISTRICT": "可生产区域", "PRODUCTION_PROJECT": "可生产项目",
    "PURCHASE_GOLD": "可用金币购买", "PURCHASE_FAITH": "可用信仰购买",
    "UNIT_XP": "单位经验", "PROMOTION": "可选升级", "PATH": "路线预检（不是实际寻路）",
    "NOT_FOUND": "未找到", "ERROR": "读取错误",
    "ACTION_UNIT": "单位可用动作信息", "ACTION_SPY": "间谍可用任务",
    "BUILD_UNIT": "可生产单位", "BUILD_BUILDING": "可生产建筑", "BUILD_DISTRICT": "可生产区域",
    "BUILD_PROJECT": "可生产项目", "RESEARCH_CURRENT": "当前研究",
    "LOCKED_TECH": "尚缺前置的科技", "LOCKED_CIVIC": "尚缺前置的市政", "COMPLETED": "已完成研究数量",
    "POLICY_GOV": "当前政体", "POLICY_SLOT": "政策槽位", "POLICY_AVAILABLE": "可用政策卡",
    "GOVERNOR_STATUS": "总督点数", "APPOINTED": "已任命总督", "AVAILABLE": "可任命总督", "GOV_PROMO": "总督升级",
    "PROMOTION_UNIT": "待晋升单位", "PROMOTION_XP": "单位经验", "PROMOTION_OPTION": "可选晋升",
    "ENVOY_TOKENS": "可派使者", "ENVOY_CITY_STATE": "可派遣城邦",
    "PANTHEON_STATUS": "万神殿状态", "PANTHEON_BELIEF": "可选万神殿",
    "RELIGION_STATUS": "创教状态", "RELIGION": "可选宗教", "RELIGION_BELIEF": "可选宗教信条",
    "DEDICATION_STATUS": "时代着力点状态", "DEDICATION_ACTIVE": "当前着力点", "DEDICATION_CHOICE": "可选着力点",
    "GOVERNMENT_OPTION": "可用政体", "GREAT_PERSON_OPTION": "可招募伟人", "TRADE_DESTINATION": "可选贸易目的地",
    "PENDING_DEAL": "待响应交易", "DEAL_ITEM": "交易条款", "TRADE_CIV": "交易对象", "TRADE_ECON": "双方经济",
    "TRADE_RESOURCE": "可交易资源", "TRADE_OPEN_BORDERS": "开放边界", "TRADE_ALLIANCE": "同盟资格", "TRADE_CITY": "可交易城市",
    "DIPLO_SESSION": "外交会面", "DIPLO_CHOICE": "外交响应选项",
    "CONGRESS_STATUS": "世界议会状态", "CONGRESS_RESOLUTION": "世界议会决议", "CONGRESS_PROPOSAL": "世界议会提案",
    "PURCHASABLE_TILE": "可购买地块", "CITY_FOCUS": "城市产出侧重", "DISTRICT_PLOT": "区域候选地块", "WONDER_PLOT": "奇观候选地块",
    "TODO": "回合待办",
    "TRADE_TEST_ITEM": "交易试算条款", "TRADE_TEST_STAGE": "交易试算阶段", "TRADE_TEST_RESULT": "交易试算结论",
}

POSITIONAL = {
    "POS": ["X", "Y"], "CONFIRMED": ["项目", "详情"], "NOT_SET": ["详情"],
    "CURRENT_TECH": ["名称", "剩余回合"], "CURRENT_CIVIC": ["名称", "剩余回合"], "TECH": ["名称", "类型"],
    "CIVIC": ["名称", "类型"], "STOCKPILE": ["资源"], "CIV": ["文明", "领袖"], "MY_MILITARY": ["军力"],
    "GOVERNMENT": ["政府"], "POLICY_SLOTS": ["槽位数"], "POLICY": ["政策"], "GOVERNOR": ["总督"],
    "VICTORY": ["文明"], "RESOURCE": ["资源"], "RESOURCE_COUNT": ["数量"], "NOTIFICATION_COUNT": ["数量"],
    "CITY_STATE": ["城邦"], "ERA": ["时代"], "DISTRICT": ["区域"], "PURCHASE_GOLD": ["种类"], "PURCHASE_FAITH": ["种类"],
    "PROMOTION": ["类型"], "NOT_FOUND": ["种类", "ID"], "ERROR": ["说明"],
    "ACTION_UNIT": ["单位ID", "本地ID", "名称", "内部类型", "坐标", "移动力", "活动状态", "需指令", "生命值", "近战", "远程", "次数", "可攻击目标", "待晋升", "可升级", "升级为", "升级费用", "当前可执行改良", "宗教"],
    "ACTION_SPY": ["单位ID", "名称", "X", "Y", "等级", "经验", "移动力", "所在城市", "城市阵营", "可用任务", "当前任务", "状态"],
    "BUILD_UNIT": ["内部类型", "生产费用", "回合", "金币费用"],
    "BUILD_BUILDING": ["内部类型", "生产费用", "回合", "金币费用", "状态"],
    "BUILD_DISTRICT": ["内部类型", "生产费用", "回合", "金币费用", "状态", "坐标"],
    "BUILD_PROJECT": ["内部类型", "生产费用", "回合", "金币费用"],
    "RESEARCH_CURRENT": ["当前科技", "科技剩余回合", "当前市政", "市政剩余回合"],
    "TECH": ["名称", "内部类型", "费用", "完成度", "回合", "尤里卡", "尤里卡条件", "解锁内容", "前置", "时代"],
    "CIVIC": ["名称", "内部类型", "费用", "完成度", "回合", "鼓舞", "鼓舞条件", "解锁内容", "前置", "时代"],
    "LOCKED_TECH": ["名称", "内部类型", "缺少前置", "时代", "尤里卡", "尤里卡条件"],
    "LOCKED_CIVIC": ["名称", "内部类型", "缺少前置", "时代", "鼓舞", "鼓舞条件"],
    "COMPLETED": ["科技", "市政"],
    "POLICY_GOV": ["内部类型", "名称", "槽位数"], "POLICY_SLOT": ["槽位", "槽位类型", "当前政策", "名称"],
    "POLICY_AVAILABLE": ["内部类型", "名称", "说明", "卡牌类型"],
    "GOVERNOR_STATUS": ["可用点数", "已花费", "可任命"],
    "APPOINTED": ["内部类型", "姓名", "头衔", "城市ID", "城市", "已就任", "剩余回合"],
    "AVAILABLE": ["内部类型", "姓名", "头衔", "说明"],
    "GOV_PROMO": ["总督类型", "升级类型", "名称", "说明", "等级", "列"],
    "PROMOTION_UNIT": ["单位ID", "本地ID", "单位类型"], "PROMOTION_XP": ["经验", "下一级", "已有晋升数"],
    "PROMOTION_OPTION": ["内部类型", "名称", "说明"],
    "ENVOY_TOKENS": ["数量"], "ENVOY_CITY_STATE": ["玩家ID", "城邦", "类型", "已派使者", "宗主国ID", "宗主国", "可派遣"],
    "PANTHEON_STATUS": ["已有万神殿", "内部类型", "名称", "信仰"], "PANTHEON_BELIEF": ["内部类型", "名称", "说明"],
    "RELIGION_STATUS": ["信息"], "RELIGION": ["内部类型", "名称"], "RELIGION_BELIEF": ["类别", "内部类型", "名称", "说明"],
    "DEDICATION_STATUS": ["时代状态", "时代", "时代分", "黑暗阈值", "黄金阈值", "可选数量"],
    "DEDICATION_ACTIVE": ["内部类型"], "DEDICATION_CHOICE": ["索引", "内部类型", "普通/黑暗时代效果", "黄金/英雄时代效果", "黑暗时代效果"],
    "GOVERNMENT_OPTION": ["内部类型", "索引", "状态", "名称", "槽位", "奖励"],
    "GREAT_PERSON_OPTION": ["类别", "姓名", "时代", "阈值", "当前招募者", "我方点数", "能力", "赞助费用", "伟人ID"],
    "TRADE_DESTINATION": ["城市", "文明", "坐标", "国内", "城邦", "商路任务", "贸易站", "向外宗教压力", "起点宗教", "向内宗教压力", "终点宗教", "我方收益/回合", "对方收益/回合", "单程距离", "预计持续回合"],
    "PENDING_DEAL": ["玩家ID", "文明", "领袖"], "DEAL_ITEM": ["玩家ID", "提供方", "类型", "内容", "数量", "持续回合"],
    "TRADE_CIV": ["玩家ID", "文明"], "TRADE_ECON": ["我方金币", "我方GPT", "我方支持", "对方金币", "对方GPT", "对方支持"],
    "TRADE_RESOURCE": ["资源", "内部类型", "类别", "我方数量", "对方数量"], "TRADE_OPEN_BORDERS": ["已开放"],
    "TRADE_ALLIANCE": ["可结盟", "当前同盟"], "TRADE_CITY": ["归属", "城市ID", "城市", "人口", "首都"],
    "DIPLO_SESSION": ["会话ID", "玩家ID", "文明", "领袖", "对话", "原因", "按钮", "交战"],
    "DIPLO_CHOICE": ["类型", "键", "文本"],
    "CONGRESS_STATUS": ["会议中", "剩余回合", "外交支持", "最大票数", "累计票价"],
    "CONGRESS_RESOLUTION": ["Hash", "内部类型", "名称", "目标类型", "选项A", "选项B", "已通过", "胜方", "已选目标", "可选目标"],
    "CONGRESS_PROPOSAL": ["发起者ID", "发起者", "目标ID", "目标", "类型", "说明"],
    "PURCHASABLE_TILE": ["坐标", "费用", "地形", "资源", "资源类别"], "CITY_FOCUS": ["产出", "状态"],
    "DISTRICT_PLOT": ["坐标", "总邻接", "生产", "金币", "信仰", "文化", "总分", "地形"],
    "WONDER_PLOT": ["坐标", "地形", "地貌", "河流", "海岸", "资源", "改良", "代价分"],
    "TRADE_TEST_ITEM": ["提供方", "类型", "数量", "持续回合", "对象", "子类型"],
    "TRADE_TEST_STAGE": ["阶段"], "TRADE_TEST_RESULT": ["结论", "说明"],
}


def friendly(value: str) -> str:
    if re.fullmatch(r"[+-]?\d+\.\d+", value):
        return f"{float(value):.1f}"
    if re.fullmatch(r"-?\d+,-?\d+", value):
        return f"({value})"
    return {"yes": "是", "no": "否", "true": "是", "false": "否", "none": "无", "?": "未知", "unknown": "未知", "Unknown": "未知", "unavailable": "不可用",
            "US": "我方", "THEM": "对方", "OURS": "我方", "THEIRS": "对方",
            "VALID": "合法", "MISSING_DEPENDENCY": "缺少配对条件（可通过组合满足）",
            "target_required": "需选择目标（以专项选项表为准）", "GONE": "单位已不在己方列表",
            "unexplored": "未探索", "visible": "当前可见", "fog": "已探索迷雾", "UNIT": "单位", "BUILDING": "建筑", "DISTRICT": "区域", "PROJECT": "项目",
            "unowned": "未归属", "unassigned": "未指派", "unclaimed": "未招募", "normal": "普通", "golden": "黄金",
            "captured": "征服占领", "rebelled": "忠诚度叛变", "pending": "待处置",
            "ready": "待命", "hold": "已跳过", "sleep": "休眠", "heal": "休整", "sentry": "警戒",
            "fortify": "驻防", "fortify_or_alert": "驻防/警戒", "intercept": "拦截", "operation": "执行持续任务",
            "auto_explore": "自动探索", "trade_route": "执行商路", "spy_mission": "执行间谍任务",
            "exhausted": "行动力耗尽", "busy": "执行持续任务", "awake": "待命",
            "dark": "黑暗", "heroic": "英雄", "urgent": "紧急", "high": "高", "FRIENDLY": "友好", "NEUTRAL": "中立",
            "SELF": "我方", "WAR": "战争", "FRIEND": "友谊", "ALLIED": "盟友", "DENOUNCED": "谴责", "UNFRIENDLY": "不友好"}.get(value, value)


def field_value(key: str, value: str) -> str:
    if key in {"turns", "growth_turns", "turns_until_next", "total_turns"} and re.fullmatch(r"-?\d+", value):
        if int(value) < 0 or int(value) >= 9999:
            return "未知"
    return friendly(value)


def _join_details(*parts: str) -> str:
    return "；".join(part for part in parts if part and part not in {"none", "无", "无说明", "无额外条件", "0"}) or "—"


def _record_matrix(kind: str, records: list) -> tuple[list[str], list[list[str]]]:
    """Convert wire records into human decision rows rather than field dumps."""
    if kind == "TILE" and all(record.fields for record in records):
        rows = []
        for record in records:
            f = record.fields
            features = []
            for key, label in (("resource", "资源"), ("city", "城市"), ("district", "区域"),
                               ("wonder", "奇观"), ("site", "地点"), ("improvement", "改良")):
                value = friendly(f.get(key, "none"))
                if value not in {"无", "none", "—", ""}:
                    features.append(f"{label}：{value}")
            if f.get("river") == "yes":
                features.append("沿河")
            rows.append([
                friendly(f.get("position", "?")), friendly(f.get("terrain", "?")),
                " · ".join(features) or "—", friendly(f.get("units", "none")),
            ])
        return ["坐标", "地形", "可见内容", "单位"], rows
    if kind in {"PRODUCTION_UNIT", "BUILD_UNIT"} and all(record.fields for record in records):
        rows = []
        for record in records:
            f = record.fields
            stats = []
            for key, label in (("combat", "近战"), ("ranged", "远程"), ("bombard", "轰炸"),
                               ("range", "射程"), ("moves", "移动"), ("charges", "次数")):
                if f.get(key) not in {None, "", "0", "?"}:
                    stats.append(f"{label} {friendly(f[key])}")
            price = friendly(f.get("cost", "?"))
            if f.get("turns") is not None:
                price += f" · {field_value('turns', f['turns'])} 回合"
            rows.append([
                friendly(f.get("name", "未知")), friendly(f.get("type", "未知")), price,
                " · ".join(stats) or "—",
                _join_details(f.get("requirements", ""), f.get("effect", f.get("details", ""))),
            ])
        return ["名称", "内部类型", "费用 / 时间", "属性", "详情"], rows
    if kind in {"PRODUCTION_BUILDING", "BUILD_BUILDING", "PRODUCTION_DISTRICT", "BUILD_DISTRICT", "PRODUCTION_PROJECT", "BUILD_PROJECT"} and all(record.fields for record in records):
        rows = []
        for record in records:
            f = record.fields
            price = friendly(f.get("cost", "?"))
            if f.get("turns") is not None:
                price += f" · {field_value('turns', f['turns'])} 回合"
            note = "奇观 · " if f.get("is_wonder") == "yes" else ""
            note += _join_details(f.get("requirements", ""), f.get("effect", f.get("details", "")))
            rows.append([friendly(f.get("name", "未知")), friendly(f.get("type", "未知")), price, note])
        return ["名称", "内部类型", "费用 / 时间", "详情"], rows
    if kind in {"PURCHASE_GOLD", "PURCHASE_FAITH"} and all(record.fields for record in records):
        return ["类别", "名称", "费用", "当前可购买", "详情"], [
            [friendly(record.values[0]) if record.values else "—", friendly(record.fields.get("name", "未知")),
             friendly(record.fields.get("cost", "?")), friendly(record.fields.get("affordable", "?")),
             friendly(record.fields.get("details", "—"))]
            for record in records
        ]
    if kind == "ACTION_UNIT" and all(len(record.values) >= 12 for record in records):
        picks = (0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11)
        headers = ["ID", "单位", "内部类型", "坐标", "移动力", "活动状态", "需指令", "生命值", "近战", "远程", "次数"]
        return headers, [[friendly(record.values[index]) for index in picks] for record in records]
    if kind in {"TECH", "CIVIC"} and all(len(record.values) >= 10 for record in records):
        rows = []
        for record in records:
            v = record.values
            pct = "未知" if v[3] == "-1" else friendly(v[3]) + "%"
            cost = "未知" if v[2] == "-1" else friendly(v[2])
            progress = f"{pct} · 费用 {cost} · {field_value('turns', v[4])} 回合"
            detail = _join_details(
                "时代：" + friendly(v[9]),
                "前置：" + friendly(v[8]) if v[8] not in {"none", "无", ""} else "",
                "加速条件：" + friendly(v[6]) if v[6] not in {"none", "无", ""} else "",
                "解锁：" + friendly(v[7]) if v[7] not in {"none", "无", ""} else "",
            )
            rows.append([friendly(v[0]), friendly(v[1]), progress, friendly(v[5]), detail])
        return ["名称", "内部类型", "进度 / 回合", "已加速", "条件 / 解锁"], rows

    positional_count = max(len(record.values) for record in records)
    names = POSITIONAL.get(kind, [])
    headers = [names[index] if index < len(names) else f"信息{index + 1}" for index in range(positional_count)]
    fields = list(dict.fromkeys(key for record in records for key in record.fields))
    headers += [LABELS.get(key, key) for key in fields]
    if kind == "GREAT_PERSON":
        headers = ["主动能力" if header == LABELS["active"] else header for header in headers]
    rows = [
        [friendly(record.values[index]) if index < len(record.values) else "—" for index in range(positional_count)]
        + [field_value(key, record.fields.get(key, "—")) for key in fields]
        for record in records
    ]
    if not headers:
        return ["信息"], [["无"]]
    return headers, rows


def _detail_grid(headers: list[str], values: list[str], display: Display) -> RenderableType:
    def one_grid(items: Sequence[tuple[str, str]]) -> Table:
        grid = Table.grid(expand=True, padding=(0, 1))
        grid.add_column(style=DIM, no_wrap=True)
        grid.add_column(ratio=1, overflow="fold")
        for header, value in items:
            grid.add_row(Text(plain(header) + "  ", style=DIM), Text(plain(value), style=_semantic_style(header, value, 1)))
        return grid

    pairs = list(zip(headers, values))
    if display.width >= 96 and len(pairs) >= 6:
        middle = (len(pairs) + 1) // 2
        return Columns([one_grid(pairs[:middle]), one_grid(pairs[middle:])], equal=True, expand=True, padding=(0, 2))
    return one_grid(pairs)


_DETAILED_OPTION_KINDS = {
    "PRODUCTION_UNIT", "PRODUCTION_BUILDING", "PRODUCTION_DISTRICT", "PRODUCTION_PROJECT",
    "BUILD_UNIT", "BUILD_BUILDING", "BUILD_DISTRICT", "BUILD_PROJECT",
    "PURCHASE_GOLD", "PURCHASE_FAITH", "TECH", "CIVIC",
}


def _split_option_details(
    headers: list[str], rows: list[list[str]],
) -> tuple[list[str], list[list[str]], list[tuple[str, str, str]]]:
    """Give long decision prose its own full-width reading area.

    The comparison table keeps the fields users scan and copy. Conditions and
    effects remain directly below it, keyed by the same name/type, rather than
    competing with every other column for horizontal space.
    """
    detail_index = next(
        (headers.index(header) for header in ("详情", "条件 / 解锁", "效果/详情") if header in headers),
        None,
    )
    if detail_index is None:
        return headers, rows, []
    name_index = headers.index("名称") if "名称" in headers else 0
    type_index = headers.index("内部类型") if "内部类型" in headers else (
        headers.index("类别") if "类别" in headers else None
    )
    details = [
        (
            row[name_index],
            row[type_index] if type_index is not None and type_index != name_index else "",
            row[detail_index],
        )
        for row in rows
        if row[detail_index] not in {"", "—", "无", "无说明", "无额外条件"}
    ]
    keep = [index for index in range(len(headers)) if index != detail_index]
    return [headers[index] for index in keep], [[row[index] for index in keep] for row in rows], details


def _option_details_panel(details: list[tuple[str, str, str]], display: Display) -> Panel:
    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(width=1, no_wrap=True)
    grid.add_column(ratio=1, overflow="fold")
    for name, type_name, detail in details:
        item = Text()
        item.append(plain(name), style="bold")
        if type_name and type_name != "—":
            item.append("  " + plain(type_name), style=ACCENT)
        item.append("\n")
        item.append(plain(detail), style=DIM)
        grid.add_row(Text("·", style=ACCENT), item)
    return Panel(
        grid,
        title=Text("效果与条件", style=HEADING),
        subtitle=Text(f"{len(details)} 项", style=FAINT),
        title_align="left",
        subtitle_align="right",
        border_style=BORDER,
        box=box.ASCII if display.ascii else box.ROUNDED,
        padding=(0, 1),
        expand=True,
    )


def _todo_panel(records: list, display: Display) -> Panel:
    body = Text()
    for index, record in enumerate(records):
        if index:
            body.append("\n")
        message = friendly(record.fields.get("message", "需要处理回合事项"))
        body.append(("! " if not display.ascii else "[!] "), style=f"bold {WARNING}")
        body.append(message, style="bold")
        blocker = friendly(record.fields.get("type", ""))
        if blocker:
            body.append("  " + blocker, style=FAINT)
        next_step = record.fields.get("next")
        if next_step:
            body.append("\n  > ", style=ACCENT)
            body.append(plain(next_step), style=ACCENT)
    return Panel(
        body,
        title=Text(f"回合待办 · {len(records)}", style=f"bold {WARNING}"),
        title_align="left",
        border_style=WARNING,
        box=box.ASCII if display.ascii else box.ROUNDED,
        padding=(0, 1),
        expand=True,
    )


def _notification_panel(records: list, display: Display) -> Panel:
    body = Text()
    blocking = 0
    for index, record in enumerate(records):
        if index:
            body.append("\n")
        is_blocking = record.fields.get("blocking") == "yes"
        blocking += int(is_blocking)
        body.append(("! " if is_blocking else "· "), style=WARNING if is_blocking else INFO)
        body.append(friendly(record.fields.get("message", "通知")), style="bold" if is_blocking else "")
        kind = record.fields.get("type")
        if kind:
            body.append("  " + plain(kind), style=FAINT)
    subtitle = f"{blocking} 项阻塞" if blocking else "无阻塞"
    return Panel(
        body or Text("当前没有通知", style=DIM),
        title=Text(f"通知 · {len(records)}", style=HEADING),
        subtitle=Text(subtitle, style=WARNING if blocking else DIM),
        title_align="left",
        subtitle_align="right",
        border_style=WARNING if blocking else BORDER,
        box=box.ASCII if display.ascii else box.ROUNDED,
        padding=(0, 1),
        expand=True,
    )


def render_records(lines: list[str], display: Display = Display(), *, title: str | None = None) -> str:
    if not lines:
        renderables: list[RenderableType] = []
        if title:
            renderables.append(Rule(Text(plain(title), style=HEADING), align="left", style=BORDER))
        renderables.append(Text("✓ 暂无玩家可见的信息" if not display.ascii else "[OK] 暂无玩家可见的信息", style=SUCCESS))
        return render_rich(renderables, display)
    groups: OrderedDict[str, list] = OrderedDict()
    for record in parse_records(lines):
        groups.setdefault(record.kind, []).append(record)
    renderables = []
    if title:
        if display.ascii:
            renderables.append(Text(rule(title, display), style=HEADING))
        else:
            renderables.append(Rule(Text(plain(title), style=HEADING), align="left", style=BORDER))
    for kind, records in groups.items():
        if kind in {"NOTIFICATION_COUNT", "RESOURCE_COUNT"}:
            continue
        if kind == "TODO":
            renderables.append(_todo_panel(records, display))
            continue
        if kind == "NOTIFICATION":
            renderables.append(_notification_panel(records, display))
            continue
        section_title = KINDS.get(kind, kind)
        headers, rows = _record_matrix(kind, records)
        option_details: list[tuple[str, str, str]] = []
        if kind in _DETAILED_OPTION_KINDS and len(rows) > 1:
            headers, rows, option_details = _split_option_details(headers, rows)
        if kind == "ERROR":
            message = " · ".join(" / ".join(row) for row in rows)
            renderables.append(Panel(
                Text(message, style=ERROR),
                title=Text(section_title, style=f"bold {ERROR}"),
                title_align="left",
                border_style=ERROR,
                box=box.ASCII if display.ascii else box.ROUNDED,
                padding=(0, 1),
            ))
        elif len(rows) == 1 and len(headers) > 1:
            renderables.append(Panel(
                _detail_grid(headers, rows[0], display),
                title=Text(section_title, style=HEADING),
                subtitle=Text("项目 / 信息", style=FAINT),
                title_align="left",
                subtitle_align="right",
                border_style=BORDER,
                box=box.ASCII if display.ascii else box.ROUNDED,
                padding=(0, 1),
                expand=True,
            ))
        elif len(rows) == 1:
            line = Text(section_title + "  ", style=f"bold {DIM}")
            line.append(headers[0] + "  ", style=DIM)
            line.append(rows[0][0])
            renderables.append(line)
        else:
            if display.ascii:
                renderables.append(Text(rule(section_title, display), style=HEADING))
            else:
                renderables.append(Rule(Text(section_title, style=HEADING), align="left", style=BORDER))
            renderables.append(rich_table(headers, rows, display))
        if option_details:
            renderables.append(_option_details_panel(option_details, display))
    return render_rich(renderables, display)
