"""Espionage domain — Lua builders and parsers for spy operations."""

from __future__ import annotations

from civ6_cli.lua._helpers import SENTINEL, _bail, _bail_lua, _int, _lua_get_unit
from civ6_cli.lua.models import SpyInfo

# Verified base-game fallback hashes. Direct GameInfo/enum lookups are preferred;
# some tuner builds expose lookups while iteration returns zero rows.
_SPY_OP_HASHES: dict[str, int] = {
    "TRAVEL": -1295211657,
    "COUNTERSPY": -2005926703,
    "GAIN_SOURCES": -311249027,
    "SIPHON_FUNDS": 574548564,
    "STEAL_TECH_BOOST": -664243095,
    "SABOTAGE_PRODUCTION": 163704001,
    "GREAT_WORK_HEIST": 485545794,
    "RECRUIT_PARTISANS": -713713573,
    "NEUTRALIZE_GOVERNOR": -1064658215,
    "FABRICATE_SCANDAL": -1766334630,
}

_RANK_NAMES = {1: "Recruit", 2: "Agent", 3: "Special Agent", 4: "Senior Agent"}

# Direct lookups supplement iteration (some tuner builds return zero rows).
_MISSION_NAMES = tuple(k for k in _SPY_OP_HASHES if k != "TRAVEL") + (
    "LISTENING_POST", "FOMENT_UNREST", "DISRUPT_ROCKETRY", "BREACH_DAM", "ZOMBIFY",
)


def build_spy_options_query(unit_index: int, *, destinations_only: bool = False) -> str:
    """Mirror EspionageChooser/EspionageSupport, including DLC operations."""
    names = ",".join(f'"{name}"' for name in _MISSION_NAMES)
    return f"""
{_lua_get_unit(unit_index)}
local info = GameInfo.Units[unit:GetType()]
if not info or info.UnitType ~= "UNIT_SPY" then {_bail("ERR:NOT_A_SPY")} end
local function safe(fn, fallback)
    local ok, value = pcall(fn)
    if ok and value ~= nil then return value end
    return fallback
end
local function clean(value) return tostring(value or ""):gsub("|", "/"):gsub("[\\r\\n]", " ") end
local x, y = unit:GetX(), unit:GetY()
local current = safe(function() return unit:GetSpyOperation() end, -1)
local finish = safe(function() return unit:GetSpyOperationEndTurn() end, -1)
local currentRow = current >= 0 and GameInfo.UnitOperations[current] or nil
print("SPY|id=" .. unit:GetID() .. "|name=" .. clean(Locale.Lookup(unit:GetName())) .. "|position=" .. x .. "," .. y
    .. "|operation=" .. (currentRow and clean(Locale.Lookup(currentRow.Description)) or "none")
    .. "|turns=" .. (finish >= 0 and math.max(0, finish - Game.GetCurrentGameTurn()) or -1))
local operations, seen = {{}}, {{}}
local function add(row)
    if row and not seen[row.OperationType] then
        seen[row.OperationType] = true
        table.insert(operations, row)
    end
end
for row in GameInfo.UnitOperations() do
    if row.OperationType == "UNITOPERATION_SPY_COUNTERSPY" or row.CategoryInUI == "OFFENSIVESPY" then add(row) end
end
for _, name in ipairs({{{names}}}) do add(GameInfo.UnitOperations["UNITOPERATION_SPY_" .. name]) end
table.sort(operations, function(a,b) return a.OperationType < b.OperationType end)
local unitPlot = x >= 0 and Map.GetPlot(x, y) or nil
local city = nil
if not {"true" if destinations_only else "false"} and unitPlot then
    city = CityManager.GetCityAt(x, y) or safe(function() return Cities.GetPlotPurchaseCity(unitPlot) end, nil)
end
local count = 0
if city then
    local cityPlot = Map.GetPlot(city:GetX(), city:GetY())
    for _, operation in ipairs(operations) do
        local own = city:GetOwner() == me
        if (own and operation.OperationType == "UNITOPERATION_SPY_COUNTERSPY")
            or (not own and operation.OperationType ~= "UNITOPERATION_SPY_COUNTERSPY") then
            local ok, can, results = pcall(function()
                return UnitManager.CanStartOperation(unit, operation.Hash, cityPlot, false, true)
            end)
            if ok and can then
                local plots = results and results[UnitOperationResults.PLOTS] or {{cityPlot:GetIndex()}}
                if #plots == 0 then plots = {{cityPlot:GetIndex()}} end
                for _, plotID in ipairs(plots) do
                    local target = Map.GetPlotByIndex(plotID)
                    if target then
                        local turns = safe(function() return UnitManager.GetTimeToComplete(operation.Index, unit) end, -1)
                        local chance = "—"
                        if not own then
                            local probabilities = safe(function() return UnitManager.GetResultProbability(operation.Index, unit, target) end, nil)
                            chance = probabilities and tostring(math.floor(((probabilities.ESPIONAGE_SUCCESS_UNDETECTED or 0)
                                + (probabilities.ESPIONAGE_SUCCESS_MUST_ESCAPE or 0)) * 100 + 0.5)) .. "%" or "?"
                        end
                        local detail = safe(function() return UnitManager.GetOperationDetailText(operation.Index, unit, cityPlot) end, "")
                        local key = "LOC_SPYMISSIONDETAILS_" .. operation.OperationType
                        local kind = operation.OperationType:gsub("UNITOPERATION_SPY_", "")
                        if kind == "SIPHON_FUNDS" then detail = Locale.Lookup(key, Locale.Lookup(city:GetName()), detail)
                        elseif kind == "GREAT_WORK_HEIST" or kind == "FOMENT_UNREST" or kind == "FABRICATE_SCANDAL" or kind == "NEUTRALIZE_GOVERNOR" then detail = Locale.Lookup(key, detail)
                        elseif detail == "" then detail = Locale.Lookup(key) end
                        if own then detail = "保护目标区域及相邻区域，降低敌方间谍成功率" end
                        local district = GameInfo.Districts[target:GetDistrictType()]
                        print("SPY_MISSION|mission=" .. kind .. "|name=" .. clean(Locale.Lookup(operation.Description))
                            .. "|position=" .. target:GetX() .. "," .. target:GetY() .. "|district=" .. (district and clean(Locale.Lookup(district.Name)) or "none")
                            .. "|total_turns=" .. turns .. "|success=" .. chance .. "|effect=" .. clean(detail))
                        count = count + 1
                    end
                end
            end
        end
    end
end
if {"false" if destinations_only else "true"} and count == 0 then print("SPY_NOTE|message=当前没有可执行任务；旅行中或任务进行中需等待完成") end
print("SPY_NOTE|message=派遣城市与旅行回合：spy destinations {unit_index}；执行任务：spy mission {unit_index} <任务类型> <目标x> <目标y>")
if {"true" if destinations_only else "false"} then
local travel = GameInfo.UnitOperations["UNITOPERATION_SPY_TRAVEL_NEW_CITY"]
local travelHash = travel and travel.Hash or UnitOperationTypes.SPY_TRAVEL_NEW_CITY
for id = 0, 62 do
    local player = Players[id]
    if player and player:IsAlive() and (id == me or Players[me]:GetDiplomacy():HasMet(id)) then
        for _, destination in player:GetCities():Members() do
            local dx, dy = destination:GetX(), destination:GetY()
            local params = {{[UnitOperationTypes.PARAM_X]=dx, [UnitOperationTypes.PARAM_Y]=dy}}
            local can = safe(function() return UnitManager.CanStartOperation(unit, travelHash, Map.GetPlot(dx,dy), params) end, false)
            if can then
                local travelTurns = safe(function() return UnitManager.GetTravelTime(unit, destination) end, -1)
                local establish = safe(function() return UnitManager.GetEstablishInCityTime(unit, destination) end, -1)
                print("SPY_DESTINATION|name=" .. clean(Locale.Lookup(destination:GetName())) .. "|owner=" .. id .. "|position=" .. dx .. "," .. dy
                    .. "|travel_turns=" .. travelTurns .. "|establish_turns=" .. establish
                    .. "|total_turns=" .. (travelTurns >= 0 and establish >= 0 and travelTurns + establish or -1))
            end
        end
    end
end
end
print("{SENTINEL}")
"""


def build_get_spies_query() -> str:
    """InGame context: list all spy units with rank, position, city, and available ops."""
    # Build the op table literal for Lua (key=name, value=hash)
    op_entries = ", ".join(
        f"{name}={hash_val}" for name, hash_val in _SPY_OP_HASHES.items()
    )
    sentinel = SENTINEL
    return f"""
local me = Game.GetLocalPlayer()
local SPY_OPS = {{{op_entries}}}
for _, suffix in ipairs({{{', '.join(f'"{name}"' for name in _MISSION_NAMES)}}}) do
    local operation = GameInfo.UnitOperations["UNITOPERATION_SPY_" .. suffix]
    if operation then SPY_OPS[suffix] = operation.Hash end
end
for i, u in Players[me]:GetUnits():Members() do
    local entry = GameInfo.Units[u:GetType()]
    if entry and entry.UnitType == "UNIT_SPY" then
        local ok_spy, err_spy = pcall(function()
            local x, y = u:GetX(), u:GetY()
            local name = Locale.Lookup(u:GetName())
            local uid = u:GetID() + me * 65536
            local rank = 1
            local xp = 0
            local exp = u:GetExperience()
            if exp then
                local ok_r, lv = pcall(function() return exp:GetLevel() end)
                if ok_r and lv then rank = lv end
                local ok_x, ep = pcall(function() return exp:GetExperiencePoints() end)
                if ok_x and ep then xp = ep end
            end
            local moves = u:GetMovesRemaining()
            local cityName = "none"
            local cityOwner = -1
            local opStr = ""
            local currentOp = "none"
            local status = "idle"
            if x == -9999 then
                status = "in_transit"
            else
                local pCity = CityManager.GetCityAt(x, y)
                if not pCity then pcall(function() pCity = Cities.GetPlotPurchaseCity(Map.GetPlot(x,y)) end) end
                if pCity then
                    cityName = Locale.Lookup(pCity:GetName())
                    cityOwner = pCity:GetOwner()
                end
                local params = {{[UnitOperationTypes.PARAM_X]=x, [UnitOperationTypes.PARAM_Y]=y}}
                local availOps = {{}}
                for opName, opHash in pairs(SPY_OPS) do
                    local ok, can = pcall(function() return UnitManager.CanStartOperation(u, opHash, Map.GetPlot(x,y), params) end)
                    if ok and can then
                        table.insert(availOps, opName)
                    end
                end
                opStr = table.concat(availOps, ",")
                local ok_op, opIdx = pcall(function() return u:GetSpyOperation() end)
                if ok_op and opIdx and opIdx >= 0 then
                    local row = GameInfo.UnitOperations[opIdx]
                    if row then currentOp = row.OperationType:gsub("UNITOPERATION_SPY_", ""):gsub("UNITOPERATION_", "") end
                    status = "on_mission"
                end
            end
            print(uid.."|"..name.."|"..x.."|"..y.."|"..rank.."|"..xp.."|"..moves.."|"..cityName.."|"..cityOwner.."|"..opStr.."|"..currentOp.."|"..status)
        end)
        if not ok_spy then
            print("0|ERROR_SPY|0|0|1|0|0|none|-1||none|idle")
        end
    end
end
print("{sentinel}")
"""


def parse_spies_response(lines: list[str]) -> list[SpyInfo]:
    """Parse pipe-delimited spy rows into SpyInfo list."""
    spies = []
    for line in lines:
        if not line or line == SENTINEL:
            continue
        parts = line.split("|")
        if len(parts) < 10:
            continue
        try:
            uid = int(parts[0])
            name = parts[1]
            x = int(parts[2])
            y = int(parts[3])
            rank = int(parts[4])
            xp = int(parts[5])
            moves = _int(parts[6])
            city_name = parts[7]
            city_owner = int(parts[8])
            ops_str = parts[9].strip()
            available_ops = [op for op in ops_str.split(",") if op]
            current_mission = parts[10].strip() if len(parts) > 10 else "none"
            status_str = parts[11].strip() if len(parts) > 11 else "idle"
            is_escaping = status_str == "escaping"
            spies.append(
                SpyInfo(
                    unit_id=uid,
                    unit_index=uid % 65536,
                    name=name,
                    x=x,
                    y=y,
                    rank=rank,
                    xp=xp,
                    moves=moves,
                    city_name=city_name,
                    city_owner=city_owner,
                    available_ops=available_ops,
                    current_mission=current_mission,
                    is_escaping=is_escaping,
                    status=status_str,
                )
            )
        except (ValueError, IndexError):
            continue
    return spies


def build_spy_travel(unit_index: int, target_x: int, target_y: int) -> str:
    """InGame context: send spy to a target city tile.

    Target legality and travel duration are decided by the game. Travel is
    asynchronous; arrival/establishment can take several turns.
    """
    travel_hash = _SPY_OP_HASHES["TRAVEL"]
    sentinel = SENTINEL
    # Build the Lua error message expression without backslash escapes in f-strings
    err_lua = (
        '"ERR:CANNOT_TRAVEL|Cannot send spy to (" .. '
        f"{target_x} .. ',' .. {target_y} .. "
        '"). Read spy destinations for currently legal cities; a busy spy may have none."'
    )
    return " ".join(
        [
            _lua_get_unit(unit_index),
            "local entry = GameInfo.Units[unit:GetType()]",
            f'if not entry or entry.UnitType ~= "UNIT_SPY" then {_bail("ERR:NOT_A_SPY")} end',
            'local operation = GameInfo.UnitOperations["UNITOPERATION_SPY_TRAVEL_NEW_CITY"]',
            f'local opHash = operation and operation.Hash or UnitOperationTypes.SPY_TRAVEL_NEW_CITY or {travel_hash}',
            f"local params = {{[UnitOperationTypes.PARAM_X]={target_x}, [UnitOperationTypes.PARAM_Y]={target_y}}}",
            f"local ok, can = pcall(function() return UnitManager.CanStartOperation(unit, opHash, Map.GetPlot({target_x}, {target_y}), params) end)",
            f"if not ok or not can then",
            f"  {_bail_lua(err_lua)}",
            "end",
            "UnitManager.RequestOperation(unit, opHash, params)",
            f'print("OK:SPY_TRAVEL|间谍已请求派遣至 ({target_x},{target_y})；旅行/建立情报网回合见 spy destinations，抵达需等待实际回合")',
            f'print("{sentinel}")',
        ]
    )


def build_spy_mission(
    unit_index: int, mission_type: str, target_x: int, target_y: int
) -> str:
    """InGame context: launch a spy mission at a target city tile.

    Offensive missions (anything except COUNTERSPY) require the spy to be physically
    IN the target city. CanStartOperation will return false until arrival.
    """
    op_hash = _SPY_OP_HASHES.get(mission_type.upper())
    sentinel = SENTINEL
    err_lua = (
        f'"ERR:CANNOT_MISSION|{mission_type} not available at (" .. '
        f"{target_x} .. ',' .. {target_y} .. "
        '"). Spy must be in the target city first (use spy_action travel)."'
    )
    return " ".join(
        [
            _lua_get_unit(unit_index),
            "local entry = GameInfo.Units[unit:GetType()]",
            f'if not entry or entry.UnitType ~= "UNIT_SPY" then {_bail("ERR:NOT_A_SPY")} end',
            f'local operation = GameInfo.UnitOperations["UNITOPERATION_SPY_{mission_type}"]',
            f'local opHash = operation and operation.Hash or UnitOperationTypes["SPY_{mission_type}"] or {op_hash if op_hash is not None else "nil"}',
            f'if not opHash then {_bail("ERR:UNKNOWN_MISSION|Mission not available in this ruleset")} end',
            f"local params = {{[UnitOperationTypes.PARAM_X]={target_x}, [UnitOperationTypes.PARAM_Y]={target_y}}}",
            f"local ok, can = pcall(function() return UnitManager.CanStartOperation(unit, opHash, Map.GetPlot({target_x}, {target_y}), params) end)",
            f"if not ok or not can then",
            f"  {_bail_lua(err_lua)}",
            "end",
            "UnitManager.RequestOperation(unit, opHash, params)",
            f'print("OK:SPY_MISSION|{mission_type} mission launched at ({target_x},{target_y}).")',
            f'print("{sentinel}")',
        ]
    )


# ---------------------------------------------------------------------------
# Escape route resolution
# ---------------------------------------------------------------------------

# District priority for escape: fastest travel time first.
# City Center is always available (every city has one) so it's the fallback.
_ESCAPE_DISTRICTS = [
    "DISTRICT_AERODROME",
    "DISTRICT_HARBOR",
    "DISTRICT_COMMERCIAL_HUB",
    "DISTRICT_CITY_CENTER",
]


def build_spy_escape_route() -> str:
    """InGame context: auto-resolve spy escape by choosing the fastest available district.

    Uses the same API as the game's EspionageEscape.lua popup:
    - GetNextEscapingSpyID() to find the caught spy
    - HasDistrict() to check which escape routes are available
    - SET_ESCAPE_ROUTE PlayerOperation to choose the district
    """
    sentinel = SENTINEL
    # Build Lua table of districts to try in priority order
    district_checks = []
    for dist in _ESCAPE_DISTRICTS:
        if dist == "DISTRICT_CITY_CENTER":
            # City Center is always available — no HasDistrict check needed
            district_checks.append(
                f"if not chosen then "
                f'  chosen = GameInfo.Districts["{dist}"]; '
                f'  chosenName = "{dist}" '
                f"end"
            )
        else:
            district_checks.append(
                f"if not chosen and city:GetDistricts():HasDistrict("
                f'GameInfo.Districts["{dist}"].Index, true, true) then '
                f'  chosen = GameInfo.Districts["{dist}"]; '
                f'  chosenName = "{dist}" '
                f"end"
            )
    checks_lua = " ".join(district_checks)

    # WARNING: GetNextEscapingSpyID() causes native ACCESS_VIOLATION crashes
    # in some game states. Only call it here where it's essential (escape blocker
    # is active, so the game expects this call). Never call it speculatively.
    return (
        f"local me = Game.GetLocalPlayer() "
        f"local pDiplo = Players[me]:GetDiplomacy() "
        f"local ok_esc, spyID = pcall(function() return pDiplo:GetNextEscapingSpyID() end) "
        f"if not ok_esc or spyID == nil or spyID < 0 then "
        f'  print("NO_ESCAPING_SPY") print("{sentinel}") do return end '
        f"end "
        f"local spy = Players[me]:GetUnits():FindID(spyID) "
        f"if not spy then "
        f'  print("ERR:SPY_NOT_FOUND") print("{sentinel}") do return end '
        f"end "
        f"local city = Cities.GetPlotPurchaseCity(spy:GetX(), spy:GetY()) "
        f"if not city then "
        f'  print("ERR:NO_CITY") print("{sentinel}") do return end '
        f"end "
        f"local chosen = nil "
        f"local chosenName = nil "
        f"{checks_lua} "
        f"if not chosen then "
        f'  print("ERR:NO_DISTRICT") print("{sentinel}") do return end '
        f"end "
        f"local params = {{}} "
        f"params[PlayerOperations.PARAM_DISTRICT_TYPE] = chosen.Index "
        f"UI.RequestPlayerOperation(me, PlayerOperations.SET_ESCAPE_ROUTE, params) "
        f'local popup = ContextPtr:LookUpControl("/InGame/EspionageEscape") '
        f"if popup then popup:SetHide(true) end "
        f'print("OK:ESCAPE_ROUTE|" .. Locale.Lookup(spy:GetName()) .. " escaping via " .. chosenName) '
        f'print("{sentinel}")'
    )
