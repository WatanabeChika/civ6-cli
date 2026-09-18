"""Coherent, typed turn snapshots using only fixed read-only templates."""

from __future__ import annotations

from dataclasses import dataclass

from rich import box
from rich.columns import Columns
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from .game import PlayerStatus, Unit, read_status, read_units
from .records import number, parse_records
from .rendering import (ACCENT, BORDER, DIM, FAINT, HEADING, INFO, SUCCESS,
                        WARNING, Display, friendly, hint, render_records,
                        render_rich, rich_table, table)
from .reports import _COMMON, _PRODUCTION_COMMON, run_report
from .transport import FireTunerConnection


_SUMMARY_QUERY = _COMMON + _PRODUCTION_COMMON + """
local me = Game.GetLocalPlayer()
local p = Players[me]
local tr, re = p:GetTreasury(), p:GetReligion()
local income = safe(function() return tr:GetGoldYield() end, nil)
local maintenance = safe(function() return tr:GetTotalMaintenance() end, nil)
print('FINANCE|income=' .. tostring(income or '?') .. '|maintenance=' .. tostring(maintenance or '?') .. '|net=' .. tostring(income and maintenance and income-maintenance or '?') .. '|faith_per_turn=' .. safe(function() return re:GetFaithYield() end, '?') .. '|score=' .. safe(function() return p:GetScore() end, '?'))
local te, cu = p:GetTechs(), p:GetCulture()
local ti = safe(function() return te:GetResearchingTech() end, -1)
local ci = safe(function() return cu:GetProgressingCivic() end, -1)
local tech = ti >= 0 and GameInfo.Technologies[ti] or nil
local civic = ci >= 0 and GameInfo.Civics[ci] or nil
print('RESEARCH|kind=tech|name=' .. (tech and local_name(tech) or 'none') .. '|progress=' .. (tech and safe(function() return te:GetResearchProgress(ti) end, '?') or '?') .. '|cost=' .. (tech and safe(function() return te:GetResearchCost(ti) end, '?') or '?') .. '|turns=' .. (tech and safe(function() return te:GetTurnsToResearch(ti) end, -1) or -1) .. '|boosted=' .. (tech and safe(function() return te:HasBoostBeenTriggered(ti) end, false) and 'yes' or 'no'))
print('RESEARCH|kind=civic|name=' .. (civic and local_name(civic) or 'none') .. '|progress=' .. (civic and safe(function() return cu:GetCulturalProgress(ci) end, '?') or '?') .. '|cost=' .. (civic and safe(function() return cu:GetCultureCost(ci) end, '?') or '?') .. '|turns=' .. (civic and safe(function() return cu:GetTurnsLeft() end, safe(function() return cu:GetTurnsLeftOnCurrentCivic() end, -1)) or -1) .. '|boosted=' .. (civic and safe(function() return cu:HasBoostBeenTriggered(ci) end, false) and 'yes' or 'no'))
for _, city in p:GetCities():Members() do
  local q = city:GetBuildQueue()
  local hash = safe(function() return q:GetCurrentProductionTypeHash() end, nil)
  local item = production_rows[hash]
  local growth = city:GetGrowth()
  local amenities = safe(function() return growth:GetAmenities() end, nil)
  local amenities_needed = safe(function() return growth:GetAmenitiesNeeded() end, nil)
  local amenities_surplus = amenities and amenities_needed and amenities-amenities_needed or '?'
  print('CITY_SUMMARY|id=' .. city:GetID() .. '|name=' .. clean(Locale.Lookup(city:GetName())) .. '|position=' .. city:GetX() .. ',' .. city:GetY() .. '|population=' .. city:GetPopulation() .. '|production=' .. safe(function() return city:GetYield(1) end, '?') .. '|producing=' .. (hash == 0 and 'none' or item and local_name(item.row) or 'Unknown') .. '|turns=' .. safe(function() return q:GetTurnsLeft() end, -1) .. '|progress=' .. production_value(q, item, 'Progress') .. '|cost=' .. production_value(q, item, 'Cost') .. '|housing=' .. safe(function() return growth:GetHousing() end, '?') .. '|amenities=' .. (amenities or '?') .. '|amenities_needed=' .. (amenities_needed or '?') .. '|amenities_surplus=' .. amenities_surplus .. '|growth_turns=' .. safe(function() return growth:GetTurnsUntilGrowth() end, -1))
end
local eras = safe(function() return Game.GetEras() end, nil)
local ei = safe(function() return eras:GetCurrentEra() end, -1)
print('SNAPSHOT_ERA|name=' .. local_name(ei >= 0 and GameInfo.Eras[ei] or nil) .. '|score=' .. safe(function() return eras:GetPlayerCurrentScore(me) end, '?') .. '|dark=' .. safe(function() return eras:GetPlayerDarkAgeThreshold(me) end, '?') .. '|golden=' .. safe(function() return eras:GetPlayerGoldenAgeThreshold(me) end, '?'))
print('STAMP|turn=' .. Game.GetCurrentGameTurn() .. '|player=' .. Game.GetLocalPlayer())
"""


@dataclass(frozen=True)
class ResearchProgress:
    kind: str
    name: str
    progress: float | None
    cost: float | None
    turns: float | None
    boosted: bool


@dataclass(frozen=True)
class CitySummary:
    id: int
    name: str
    position: str
    population: int
    production: float | None
    producing: str
    turns: float | None
    progress: float | None
    cost: float | None
    housing: float | None
    amenities: float | None
    amenities_needed: float | None
    amenities_surplus: float | None
    growth_turns: float | None


@dataclass(frozen=True)
class Overview:
    status: PlayerStatus
    units: list[Unit]
    cities: list[CitySummary]
    research: list[ResearchProgress]
    finance: dict[str, str]
    era: dict[str, str]
    warnings: list[str]
    notifications: list[str]


def read_overview(connection: FireTunerConnection) -> Overview:
    for attempt in range(2):
        status = read_status(connection)
        units = read_units(connection)
        notifications = run_report(connection, "notifications")
        lines = connection.execute_read_lines(_SUMMARY_QUERY, context="InGame", timeout=10.0)
        records = parse_records(lines)
        stamp = next((r.fields for r in records if r.kind == "STAMP"), None)
        if stamp is None:
            errors = [" | ".join(r.values) for r in records if r.kind == "ERROR"]
            raise ValueError("总览读取未完成：" + ("; ".join(errors) or "没有回合校验记录"))
        if int(stamp["turn"]) != status.turn or int(stamp["player"]) != status.player_id:
            if attempt == 0:
                continue
            raise ValueError("读取期间回合或玩家发生变化，请在回合开始后 refresh")
        cities, research, finance, era, warnings = [], [], {}, {}, []
        for r in records:
            f = r.fields
            if r.kind == "FINANCE":
                finance = f
            elif r.kind == "SNAPSHOT_ERA":
                era = f
            elif r.kind == "RESEARCH":
                research.append(ResearchProgress(f["kind"], f["name"], number(f.get("progress")), number(f.get("cost")), number(f.get("turns")), f.get("boosted") == "yes"))
            elif r.kind == "CITY_SUMMARY":
                cities.append(CitySummary(int(f["id"]), f["name"], f["position"], int(f["population"]), number(f.get("production")), f["producing"], number(f.get("turns")), number(f.get("progress")), number(f.get("cost")), number(f.get("housing")), number(f.get("amenities")), number(f.get("amenities_needed")), number(f.get("amenities_surplus")), number(f.get("growth_turns"))))
            elif r.kind == "ERROR":
                warnings.append("读取错误：" + " | ".join(r.values))
        if len(cities) != status.cities or len(units) != status.units:
            warnings.append("城市/单位列表与游戏计数不一致，请刷新后重试。")
        net = number(finance.get("net"))
        if net is not None and net < 0:
            warnings.append("金币净收入为负。")
        idle = [c.name for c in cities if c.producing == "none"]
        if idle:
            warnings.append("城市未安排生产：" + "、".join(idle))
        return Overview(status, units, sorted(cities, key=lambda c: c.id), research, finance, era, warnings, notifications)
    raise AssertionError("unreachable")


def fmt(value: float | None, *, signed: bool = False) -> str:
    return "未知" if value is None else format(value, "+.1f" if signed else ".1f")


def turns(value: float | None) -> str:
    return "未知" if value is None or value < 0 or value >= 9999 else f"{int(value)}"


def progress_text(progress: float | None, cost: float | None, display: Display) -> str:
    if progress is None or cost is None or cost <= 0:
        return "未知" if cost is None else "—"
    fraction = max(0, min(1, progress / cost))
    fill = int(fraction * 10)
    full, empty = ("#", ".") if display.ascii else ("━", "·")
    return f"{full * fill}{empty * (10-fill)} {fraction:.0%} ({progress:.1f}/{cost:.1f})"


def render_cities(cities: list[CitySummary], display: Display) -> str:
    return table(
        ["ID", "城市", "坐标", "人口", "产能/回合", "正在生产", "生产进度", "回合"],
        [[c.id, c.name, f"({c.position})", c.population, fmt(c.production), friendly(c.producing),
          f"{fmt(c.progress)}/{fmt(c.cost)}", turns(c.turns)] for c in cities],
        display,
        title=f"己方城市 · {len(cities)}",
        caption="city show <城市> 查看详情 · city production <城市> 查看可执行选项",
    )


def render_units(units: list[Unit], display: Display) -> str:
    return table(
        ["ID", "单位", "坐标", "移动力", "生命值"],
        [[u.id, u.name, f"({u.x},{u.y})", f"{u.moves}/{u.max_moves}", f"{u.hp}/{u.max_hp}"] for u in units],
        display,
        title=f"己方单位 · {len(units)}",
        caption="unit show <单位> 查看详情 · unit options <单位> 查看合法动作",
    )


def _metric_grid(snapshot: Overview) -> Table:
    s, f = snapshot.status, snapshot.finance
    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(style=DIM, no_wrap=True)
    grid.add_column(justify="right")
    grid.add_column(style=DIM, no_wrap=True)
    grid.add_column(justify="right")
    metrics = [
        ("科技/回合", fmt(s.science, signed=True), INFO),
        ("文化/回合", fmt(s.culture, signed=True), ACCENT),
        ("金币", fmt(s.gold), WARNING),
        ("净收入/回合", fmt(number(f.get("net")), signed=True), SUCCESS if (number(f.get("net")) or 0) >= 0 else WARNING),
        ("信仰", fmt(s.faith), INFO),
        ("信仰/回合", fmt(number(f.get("faith_per_turn")), signed=True), INFO),
    ]
    for left, right in zip(metrics[::2], metrics[1::2]):
        grid.add_row(
            Text(left[0], style=DIM), Text(left[1], style=f"bold {left[2]}"),
            Text(right[0], style=DIM), Text(right[1], style=f"bold {right[2]}"),
        )
    income = fmt(number(f.get("income")))
    maintenance = fmt(number(f.get("maintenance")))
    grid.add_row(Text("毛收入 / 维护", style=DIM), Text(f"{income} / {maintenance}", style=DIM), "", "")
    return grid


def _progress_bar(progress: float | None, cost: float | None, display: Display) -> Text:
    if progress is None or cost is None or cost <= 0:
        return Text("未知", style=DIM)
    fraction = max(0.0, min(1.0, progress / cost))
    fill = int(fraction * 12)
    full, empty = ("#", ".") if display.ascii else ("━", "─")
    bar = Text(full * fill, style=INFO)
    bar.append(empty * (12 - fill), style=FAINT)
    bar.append(f"  {fraction:.0%}  {progress:.1f}/{cost:.1f}", style=DIM)
    return bar


def _research_grid(research: list[ResearchProgress], display: Display) -> Table:
    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(width=5, style=DIM, no_wrap=True)
    grid.add_column(ratio=1)
    grid.add_column(justify="right", style=DIM, no_wrap=True)
    for item in research:
        kind = "科技" if item.kind == "tech" else "市政"
        name = Text(friendly(item.name), style="bold")
        if item.boosted:
            name.append("  已加速", style=SUCCESS)
        grid.add_row(kind, name, f"{turns(item.turns)} 回合")
        grid.add_row("", _progress_bar(item.progress, item.cost, display), "")
    return grid


def _card(title: str, body: RenderableType, display: Display, *, border_style: str = BORDER) -> Panel:
    return Panel(
        body,
        title=Text(title, style=HEADING),
        title_align="left",
        border_style=border_style,
        box=box.ASCII if display.ascii else box.ROUNDED,
        padding=(0, 1),
        expand=True,
    )


def render_overview(snapshot: Overview, display: Display = Display()) -> str:
    s, f, e = snapshot.status, snapshot.finance, snapshot.era
    identity = Text()
    identity.append(s.civilization, style="bold")
    identity.append(" / " + s.leader, style=DIM)
    identity.append(f"    城市 {s.cities}  单位 {s.units}", style=DIM)
    meta = f"{friendly(e.get('name', '未知'))} · 分数 {f.get('score', '未知')}"
    if e.get("score") not in {None, "?"}:
        meta += f" · 时代分 {e['score']}（黑暗 {e.get('dark', '?')} / 黄金 {e.get('golden', '?')}）"
    header = Panel(
        identity,
        title=Text(f"文明 VI · 第 {s.turn} 回合", style=HEADING),
        subtitle=Text(meta, style=DIM),
        title_align="left",
        subtitle_align="right",
        border_style=ACCENT,
        box=box.ASCII if display.ascii else box.ROUNDED,
        padding=(0, 1),
        expand=True,
    )
    cards = [
        _card("帝国产出", _metric_grid(snapshot), display),
        _card("研究进度", _research_grid(snapshot.research, display), display),
    ]
    yield_and_research: RenderableType = (
        Columns(cards, equal=True, expand=True, padding=(0, 1)) if display.width >= 96
        else Group(*cards)
    )
    city_rows = [[
        c.name,
        f"{c.population} / {fmt(c.housing)}",
        friendly(c.producing) + (f"  {fmt(c.progress)}/{fmt(c.cost)}" if c.cost is not None else ""),
        f"{turns(c.turns)} 回合",
        f"{turns(c.growth_turns)} 回合",
        fmt(c.amenities_surplus, signed=True),
    ] for c in snapshot.cities]
    city_table = rich_table(
        ["城市", "人口 / 住房", "当前生产", "完成", "增长", "宜居度"],
        city_rows,
        display,
        caption="生产与增长只做总览；详细决策使用 city production <城市>",
    )
    main = render_rich([
        header,
        yield_and_research,
        Rule(Text("城市生产 · 城市发展", style=HEADING), align="left", style=BORDER)
        if not display.ascii else Text("-- 城市生产 · 城市发展 " + "-" * max(0, min(display.width, 80) - 25), style=HEADING),
        city_table,
    ], display)

    extras: list[str] = [main]
    notifications = render_records(snapshot.notifications, display)
    extras.append(notifications or render_rich([Text("✓ 当前没有通知", style=SUCCESS)], display))
    if snapshot.warnings:
        warnings = Text()
        for index, warning in enumerate(snapshot.warnings):
            if index:
                warnings.append("\n")
            warnings.append("! ", style=f"bold {WARNING}")
            warnings.append(warning)
        extras.append(render_rich([_card("战略提醒", warnings, display, border_style=WARNING)], display))
    extras.append(hint("status 刷新 · turn todo 查看待办 · unit list 查看单位状态 · help 查看领域命令", display))
    return "\n".join(part for part in extras if part)
