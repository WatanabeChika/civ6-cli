"""Player-visible hex neighbourhoods, with odd rows shifted to the right."""

from __future__ import annotations

from dataclasses import dataclass

from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .records import Record, parse_records
from .rendering import (ACCENT, BORDER, DIM, ERROR, FAINT, HEADING, INFO,
                        SUCCESS, WARNING, Display, hint, inline, pad,
                        render_records, render_rich, rule, cell_width)
from .reports import _COMMON, bounded_int
from .transport import FireTunerConnection


def hex_distance(x: int, y: int, tx: int, ty: int) -> int:
    q, tq = x - (y - (y & 1)) // 2, tx - (ty - (ty & 1)) // 2
    dq, dr = tq - q, ty - y
    return max(abs(dq), abs(dr), abs(dq + dr))


def map_lua(x: int, y: int, radius: int) -> str:
    x = bounded_int(str(x), name="x", minimum=0, maximum=10000)
    y = bounded_int(str(y), name="y", minimum=0, maximum=10000)
    radius = bounded_int(str(radius), name="radius", minimum=0, maximum=5)
    return _COMMON + f"""
local cx, cy, r = {x}, {y}, {radius}
local w, h = Map.GetGridSize()
if cx >= w or cy >= h then print('ERROR|地图坐标超出范围'); return end
local wrap = safe(function() return Map.IsWrapX() end, false)
local me = Game.GetLocalPlayer()
local vis, techs = PlayersVisibility[me], Players[me]:GetTechs()
local function owner_name(id)
  if id == 63 then return clean(Locale.Lookup('LOC_CIVILIZATION_BARBARIAN_NAME')) end
  local cfg = PlayerConfigurations[id]
  return cfg and clean(Locale.Lookup(cfg:GetCivilizationShortDescription())) or ('P' .. id)
end
print('MAP_META|x=' .. cx .. '|y=' .. cy .. '|radius=' .. r .. '|width=' .. w .. '|height=' .. h .. '|player=' .. me)
for ly = cy-r, cy+r do
  for lx = cx-r, cx+r do
    local tx = wrap and (lx % w) or lx
    local plot = ly >= 0 and ly < h and tx >= 0 and tx < w and Map.GetPlot(tx, ly) or nil
    if plot and Map.GetPlotDistance(cx, cy, tx, ly) <= r then
      local prefix = '|position=' .. tx .. ',' .. ly .. '|layout_x=' .. lx .. '|layout_y=' .. ly
      local index = plot:GetIndex()
      if not vis:IsRevealed(index) then
        print('MAP_TILE' .. prefix .. '|visibility=unexplored')
      else
        local visible = vis:IsVisible(index)
        local terrain = GameInfo.Terrains[plot:GetTerrainType()]
        local info = '|visibility=' .. (visible and 'visible' or 'fog') .. '|terrain=' .. clean(terrain and terrain.TerrainType or 'UNKNOWN') .. '|terrain_name=' .. local_name(terrain) .. '|hills=' .. (plot:IsHills() and 'yes' or 'no')
        -- In fog the debug API still exposes live improvements, ownership,
        -- yields and units. Do not report those as if a player could see them.
        if visible then
          local feature = safe(function() return GameInfo.Features[plot:GetFeatureType()] end, nil)
          local resource = safe(function() return GameInfo.Resources[plot:GetResourceType()] end, nil)
          if resource and resource.PrereqTech then
            local prereq = GameInfo.Technologies[resource.PrereqTech]
            if not prereq or not techs:HasTech(prereq.Index) then resource = nil end
          end
          local imp = safe(function() return GameInfo.Improvements[plot:GetImprovementType()] end, nil)
          local district = safe(function() return GameInfo.Districts[plot:GetDistrictType()] end, nil)
          local wonder_index = safe(function() return plot:GetWonderType() end, -1)
          local wonder = wonder_index and wonder_index >= 0 and GameInfo.Buildings[wonder_index] or nil
          local site, site_name = 'none', 'none'
          if imp and imp.ImprovementType == 'IMPROVEMENT_BARBARIAN_CAMP' then
            site, site_name = 'barbarian_camp', clean(Locale.Lookup('LOC_IMPROVEMENT_BARBARIAN_CAMP_NAME'))
          elseif imp and imp.ImprovementType == 'IMPROVEMENT_GOODY_HUT' then
            site, site_name = 'tribal_village', clean(Locale.Lookup('LOC_IMPROVEMENT_GOODY_HUT_NAME'))
          end
          local owner = plot:GetOwner()
          local plot_owner_name = owner >= 0 and PlayerConfigurations[owner] and clean(Locale.Lookup(PlayerConfigurations[owner]:GetCivilizationShortDescription())) or 'unowned'
          local city = safe(function() return Cities.GetCityInPlot(tx, ly) end, nil)
          local unit_names, mine, others = {{}}, false, false
          local units = safe(function() return Units.GetUnitsInPlot(plot) end, {{}})
          for _, unit in ipairs(units) do
            local my_unit = unit:GetOwner() == me
            local unit_visible = safe(function() return vis:IsUnitVisible(unit) end, false)
            if my_unit or unit_visible then
              mine, others = mine or my_unit, others or not my_unit
              local unit_owner = unit:GetOwner()
              table.insert(unit_names, clean(Locale.Lookup(unit:GetName())) .. '#' .. unit:GetID() .. '（' .. owner_name(unit_owner) .. ' / P' .. unit_owner .. '）')
            end
          end
          local ys = {{}}
          for yi=0,5 do table.insert(ys, safe(function() return plot:GetYield(yi) end, '?')) end
          info = info .. '|feature=' .. clean(feature and feature.FeatureType or 'none') .. '|feature_name=' .. (feature and local_name(feature) or 'none') .. '|resource=' .. clean(resource and resource.ResourceType or 'none') .. '|resource_name=' .. (resource and local_name(resource) or 'none') .. '|improvement_name=' .. (imp and local_name(imp) or 'none') .. '|site=' .. site .. '|site_name=' .. site_name .. '|district_name=' .. (district and local_name(district) or 'none') .. '|wonder_name=' .. (wonder and local_name(wonder) or 'none') .. '|wonder_complete=' .. (wonder and (safe(function() return plot:IsWonderComplete() end, false) and 'yes' or 'no') or 'none') .. '|owner=' .. plot_owner_name .. '|appeal=' .. safe(function() return plot:GetAppeal() end, '?') .. '|river=' .. (plot:IsRiver() and 'yes' or 'no') .. '|road=' .. (safe(function() return plot:GetRouteType() end, -1) >= 0 and 'yes' or 'no') .. '|pillaged=' .. (safe(function() return plot:IsImprovementPillaged() end, false) and 'yes' or 'no') .. '|city_name=' .. (city and clean(Locale.Lookup(city:GetName())) or 'none') .. '|units=' .. (#unit_names > 0 and table.concat(unit_names, '; ') or 'none') .. '|own_units=' .. (mine and 'yes' or 'no') .. '|other_units=' .. (others and 'yes' or 'no') .. '|yields=' .. table.concat(ys, ',')
        end
        print('MAP_TILE' .. prefix .. info)
      end
    end
  end
end
"""


@dataclass(frozen=True)
class MapArea:
    x: int
    y: int
    radius: int
    tiles: list[Record]


def read_map(connection: FireTunerConnection, x: int, y: int, radius: int = 2) -> MapArea:
    records = parse_records(connection.execute_read_lines(map_lua(x, y, radius), context="InGame", timeout=10.0))
    errors = [" | ".join(r.values) for r in records if r.kind == "ERROR"]
    if errors:
        raise ValueError("地图读取失败：" + "; ".join(errors))
    if not any(r.kind == "MAP_META" for r in records):
        raise ValueError("未收到地图数据")
    return MapArea(x, y, radius, [r for r in records if r.kind == "MAP_TILE"])


def tile_glyph(f: dict[str, str], display: Display, center: bool) -> tuple[str, str]:
    visibility = f.get("visibility")
    if visibility == "unexplored":
        return "??", "2;37"
    terrain, feature = f.get("terrain", ""), f.get("feature", "")
    short, ansi = "??", "37"
    for suffix, zh, en, color in [("GRASS", "草地", "Gr", "32"), ("PLAINS", "平原", "Pl", "33"),
                                  ("DESERT", "沙漠", "Ds", "33"), ("TUNDRA", "冻土", "Tu", "37"),
                                  ("SNOW", "雪地", "Sn", "37"), ("COAST", "海岸", "Co", "36"), ("OCEAN", "深海", "Oc", "34")]:
        if suffix in terrain:
            short, ansi = (en if display.ascii else zh), color
            break
    if "MOUNTAIN" in terrain:
        short, ansi = ("Mt" if display.ascii else "山脉"), "37"
    elif f.get("hills") == "yes":
        short = "Hi" if display.ascii else "丘陵"
    if "FOREST" in feature:
        short = "Fo" if display.ascii else "森林"
    elif "JUNGLE" in feature:
        short = "Ju" if display.ascii else "雨林"
    elif "MARSH" in feature:
        short = "Ma" if display.ascii else "沼泽"
    if visibility == "fog":
        return short + "~" + ("@" if center else ""), "2;" + ansi
    markers = "".join(marker for marker, present in (
        ("C", f.get("city_name", "none") != "none"),
        ("U", f.get("own_units") == "yes"),
        ("!", f.get("other_units") == "yes"),
        ("R", f.get("resource", "none") != "none"),
        ("D", f.get("district_name", "none") != "none"),
        ("W", f.get("wonder_name", "none") != "none"),
        ("B", f.get("site") == "barbarian_camp"),
        ("V", f.get("site") == "tribal_village"),
        ("I", f.get("improvement_name", "none") != "none" and f.get("site", "none") == "none"),
        ("=" if display.ascii else "≈", f.get("river") == "yes"),
        ("@", center),
    ) if present)
    return short + (" " + markers if markers else ""), ansi


def _legend(display: Display) -> str:
    items = [
        ("C", "城市", ACCENT), ("U", "己方单位", SUCCESS), ("!", "其他可见单位", ERROR),
        ("R", "资源", SUCCESS), ("D", "区域", INFO), ("W", "奇观", WARNING),
        ("B", "蛮族哨站", ERROR), ("V", "部落村庄", INFO), ("I", "改良", DIM),
        ("=" if display.ascii else "≈", "河流", INFO), ("@", "中心", ACCENT),
        ("~", "迷雾", FAINT), ("??", "未探索", FAINT),
    ]
    columns = 3 if display.width < 96 else 4
    grid = Table.grid(expand=True, padding=(0, 1))
    for _ in range(columns):
        grid.add_column(ratio=1)
    for start in range(0, len(items), columns):
        cells = []
        for marker, label, style in items[start:start + columns]:
            cell = Text()
            cell.append(marker.ljust(2), style=f"bold {style}")
            cell.append(label, style=DIM)
            cells.append(cell)
        while len(cells) < columns:
            cells.append(Text())
        grid.add_row(*cells)
    return render_rich([
        Panel(
            grid,
            title=Text("地图图例", style=HEADING),
            title_align="left",
            border_style=BORDER,
            box=box.ASCII if display.ascii else box.ROUNDED,
            padding=(0, 1),
            expand=True,
        )
    ], display)


def _styled_glyph_rows(glyph: str, ansi: str, display: Display, width: int = 10) -> tuple[str, str]:
    terrain_style = {
        "32": SUCCESS, "33": WARNING, "36": INFO, "34": INFO, "37": DIM,
        "2;32": FAINT, "2;33": FAINT, "2;36": FAINT, "2;34": FAINT, "2;37": FAINT,
    }.get(ansi, DIM)
    terrain, separator, markers = glyph.partition(" ")
    terrain_row = inline(terrain, terrain_style, display) + " " * max(0, width - cell_width(terrain))
    marker_row = ""
    marker_styles = {
        "C": ACCENT, "U": SUCCESS, "!": ERROR, "R": SUCCESS, "D": INFO,
        "W": WARNING, "B": ERROR, "V": INFO, "I": DIM, "≈": INFO, "=": INFO,
        "~": FAINT, "@": ACCENT,
    }
    for marker in markers:
        marker_row += inline(marker, marker_styles.get(marker, DIM), display)
    marker_row += " " * max(0, width - cell_width(markers))
    return terrain_row, marker_row


def render_map(area: MapArea, display: Display = Display()) -> str:
    tiles = {(int(t.fields['layout_x']), int(t.fields['layout_y'])): t.fields for t in area.tiles}
    summary = Text()
    summary.append(f"中心 ({area.x},{area.y})", style="bold")
    summary.append(f"    半径 {area.radius}    {len(area.tiles)} 个地块", style=DIM)
    summary.append("\n游戏画面方向 · 奇数行右移半格 · 格内保留实际坐标", style=DIM)
    header = render_rich([
        Panel(
            summary,
            title=Text("局部六边形地图", style=HEADING),
            subtitle=Text("玩家可见信息", style=DIM),
            title_align="left",
            subtitle_align="right",
            border_style=ACCENT,
            box=box.ASCII if display.ascii else box.ROUNDED,
            padding=(0, 1),
            expand=True,
        )
    ], display)
    output = [header, _legend(display)]
    # Horizontal bands keep the requested radius intact in narrow terminals.
    # Five-row cells keep terrain and stacked markers readable while allowing
    # the default radius-2 map (five columns) to fit an 80-column terminal.
    hex_width, indent, content_width = 14, 8, 10
    columns = max(1, (display.width - indent) // hex_width)
    xs = list(range(area.x-area.radius, area.x+area.radius+1))
    for begin in range(0, len(xs), columns):
        band = xs[begin:begin+columns]
        if len(xs) > columns:
            output.append(rule(f"地图分栏 {begin // columns + 1} · 布局 X {band[0]}..{band[-1]}", display))
        for y in range(area.y+area.radius, area.y-area.radius-1, -1):
            row = [" " * (indent if y & 1 else 0) for _ in range(5)]
            for x in band:
                f = tiles.get((x, y))
                if f is None:
                    parts = [" " * hex_width] * 5
                else:
                    glyph, ansi = tile_glyph(f, display, (x, y) == (area.x, area.y))
                    terrain_row, marker_row = _styled_glyph_rows(glyph, ansi, display, content_width)
                    if display.ascii:
                        parts = [
                            inline("  __________  ", FAINT, display),
                            inline(" /", FAINT, display) + inline(pad(f['position'], content_width), DIM, display) + inline("\\ ", FAINT, display),
                            inline(" |", FAINT, display) + terrain_row + inline("| ", FAINT, display),
                            inline(" \\" , FAINT, display) + marker_row + inline("/ ", FAINT, display),
                            inline("  ----------  ", FAINT, display),
                        ]
                    else:
                        parts = [
                            inline("  ──────────  ", FAINT, display),
                            inline(" /", FAINT, display) + inline(pad(f['position'], content_width), DIM, display) + inline("\\ ", FAINT, display),
                            inline(" │", FAINT, display) + terrain_row + inline("│ ", FAINT, display),
                            inline(" \\" , FAINT, display) + marker_row + inline("/ ", FAINT, display),
                            inline("  ──────────  ", FAINT, display),
                        ]
                for i in range(5):
                    row[i] += parts[i]
            if any((x, y) in tiles for x in band):
                output.extend(line.rstrip() for line in row)
    detail = []
    for t in area.tiles:
        f = t.fields
        if f.get("visibility") == "visible" and any(f.get(k, 'none') != 'none' for k in ('resource_name', 'city_name', 'units', 'district_name', 'improvement_name', 'wonder_name', 'site_name')):
            detail.append('TILE|position=' + f['position'] + '|terrain=' + f.get('terrain_name', '?') + '|resource=' + f.get('resource_name', 'none') + '|city=' + f.get('city_name', 'none') + '|district=' + f.get('district_name', 'none') + '|wonder=' + f.get('wonder_name', 'none') + '|wonder_complete=' + f.get('wonder_complete', 'none') + '|site=' + f.get('site_name', 'none') + '|improvement=' + f.get('improvement_name', 'none') + '|river=' + f.get('river', 'no') + '|units=' + f.get('units', 'none'))
    if detail:
        output.append(render_records(detail, display, title="可见地标与单位"))
    output.append(hint("map tile <x> <y> 查看地块详情；迷雾内不显示实时单位、归属、设施或产出。", display))
    return "\n".join(output)
