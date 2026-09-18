"""Great People domain — Lua builders and parsers."""

from __future__ import annotations

from civ6_cli.lua._helpers import SENTINEL, _bail, _bail_lua, _int, _lua_get_unit
from civ6_cli.lua.models import GPAdvisorCity, GPAdvisorResult, GreatPersonInfo


def build_great_people_query() -> str:
    """One live query for candidates, abilities, competition and sponsorship."""
    from civ6_cli.reports import available_reports
    return next(report.lua for report in available_reports() if report.name == "great-people") + f'\nprint("{SENTINEL}")\n'


def build_recruit_great_person(individual_id: int) -> str:
    """Recruit a Great Person with accumulated GP points (InGame context)."""
    return f"""
local me = Game.GetLocalPlayer()
local gp = Game.GetGreatPeople()
if not gp:CanRecruitPerson(me, {individual_id}) then
    local ind = GameInfo.GreatPersonIndividuals[{individual_id}]
    local name = ind and Locale.Lookup(ind.Name) or "unknown"
    {_bail_lua('"ERR:CANNOT_RECRUIT|Not enough GP points to recruit " .. name')}
end
local kParams = {{}}
kParams[PlayerOperations.PARAM_GREAT_PERSON_INDIVIDUAL_TYPE] = {individual_id}
UI.RequestPlayerOperation(me, PlayerOperations.RECRUIT_GREAT_PERSON, kParams)
local ind = GameInfo.GreatPersonIndividuals[{individual_id}]
local name = ind and Locale.Lookup(ind.Name) or "unknown"
print("OK:RECRUITED|" .. name)
print("{SENTINEL}")
"""


def build_patronize_great_person(
    individual_id: int, yield_type: str = "YIELD_GOLD"
) -> str:
    """Buy a Great Person with gold or faith (InGame context)."""
    yield_idx = 2 if yield_type == "YIELD_GOLD" else 5  # YieldTypes.GOLD=2, FAITH=5
    return f"""
local me = Game.GetLocalPlayer()
local gp = Game.GetGreatPeople()
if not gp:CanPatronizePerson(me, {individual_id}, {yield_idx}) then
    local ind = GameInfo.GreatPersonIndividuals[{individual_id}]
    local name = ind and Locale.Lookup(ind.Name) or "unknown"
    local cost = gp:GetPatronizeCost(me, {individual_id}, {yield_idx})
    {_bail_lua(f'"ERR:CANNOT_PATRONIZE|Cannot buy " .. name .. " (cost: " .. cost .. " {yield_type.replace("YIELD_", "").lower()})"')}
end
local kParams = {{}}
kParams[PlayerOperations.PARAM_GREAT_PERSON_INDIVIDUAL_TYPE] = {individual_id}
kParams[PlayerOperations.PARAM_YIELD_TYPE] = {yield_idx}
UI.RequestPlayerOperation(me, PlayerOperations.PATRONIZE_GREAT_PERSON, kParams)
local ind = GameInfo.GreatPersonIndividuals[{individual_id}]
local name = ind and Locale.Lookup(ind.Name) or "unknown"
local cost = gp:GetPatronizeCost(me, {individual_id}, {yield_idx})
print("OK:PATRONIZED|" .. name .. "|cost:" .. cost .. " {yield_type.replace("YIELD_", "").lower()}")
print("{SENTINEL}")
"""


def build_reject_great_person(individual_id: int) -> str:
    """Pass on a Great Person (costs faith). InGame context."""
    return f"""
local me = Game.GetLocalPlayer()
local gp = Game.GetGreatPeople()
if not gp:CanRejectPerson(me, {individual_id}) then
    local ind = GameInfo.GreatPersonIndividuals[{individual_id}]
    local name = ind and Locale.Lookup(ind.Name) or "unknown"
    {_bail_lua('"ERR:CANNOT_REJECT|Cannot reject " .. name')}
end
local cost = gp:GetRejectCost(me, {individual_id})
local kParams = {{}}
kParams[PlayerOperations.PARAM_GREAT_PERSON_INDIVIDUAL_TYPE] = {individual_id}
UI.RequestPlayerOperation(me, PlayerOperations.REJECT_GREAT_PERSON, kParams)
local ind = GameInfo.GreatPersonIndividuals[{individual_id}]
local name = ind and Locale.Lookup(ind.Name) or "unknown"
print("OK:REJECTED|" .. name .. "|faith_cost:" .. cost)
print("{SENTINEL}")
"""


def build_activate_great_person(unit_index: int) -> str:
    """Activate a Great Person on their matching district (InGame context).

    Great Prophets use UNITOPERATION_FOUND_RELIGION instead of the generic
    UNITCOMMAND_ACTIVATE_GREAT_PERSON used by all other Great People.
    """
    return f"""
{_lua_get_unit(unit_index)}
local uInfo = GameInfo.Units[unit:GetType()]
local uName = uInfo and uInfo.UnitType or "UNKNOWN"
local ux, uy = unit:GetX(), unit:GetY()

-- Great Prophets use a different activation path
if uName == "UNIT_GREAT_PROPHET" then
    local opRow = GameInfo.UnitOperations["UNITOPERATION_FOUND_RELIGION"]
    if not opRow then {_bail("ERR:CANNOT_ACTIVATE|UNITOPERATION_FOUND_RELIGION not found in GameInfo")} end
    local params = {{}}
    params[UnitOperationTypes.PARAM_X] = ux
    params[UnitOperationTypes.PARAM_Y] = uy
    local canStart = UnitManager.CanStartOperation(unit, opRow.Hash, nil, params, true)
    if not canStart then
        {_bail('ERR:CANNOT_ACTIVATE|Great Prophet must be on a completed Holy Site with moves remaining (at " .. ux .. "," .. uy .. ")')}
    end
    UnitManager.RequestOperation(unit, opRow.Hash, params)
    print("OK:GP_ACTIVATED|" .. Locale.Lookup(unit:GetName()) .. " (" .. uName .. ") founded religion at " .. ux .. "," .. uy)
    print("{SENTINEL}"); return
end

-- All other Great People: standard activation command
local cmdHash = GameInfo.UnitCommands["UNITCOMMAND_ACTIVATE_GREAT_PERSON"].Hash
local can, failTable = UnitManager.CanStartCommand(unit, cmdHash, nil, true)
if not can then
    -- Extract game's own requirement strings from the failure table.
    -- Structure: top-level strings are category names (skip); nested tables hold
    -- sequential string arrays — requirements ("Must be...") and effect descriptions.
    local requirements = {{}}
    if failTable then
        for _, v in pairs(failTable) do
            if type(v) == "table" then
                for _, s in pairs(v) do
                    if type(s) == "string" and s ~= "" then
                        -- Strip icon codes like [ICON_GreatWork_Artifact]
                        local clean = s:gsub("%[ICON_[^%]]*%]", ""):gsub("%s+", " "):match("^%s*(.-)%s*$")
                        if clean and clean ~= "" then
                            table.insert(requirements, clean)
                        end
                    end
                end
            end
        end
    end
    -- Also gather valid activation tiles as a fallback hint
    local gp = unit:GetGreatPerson()
    local charges = gp and gp:GetActionCharges() or -1
    local validTiles = {{}}
    if gp then
        local ok, plots = pcall(function() return gp:GetActivationHighlightPlots() end)
        if ok and plots then
            for i = 1, math.min(#plots, 5) do
                local vPlot = Map.GetPlotByIndex(plots[i])
                if vPlot then
                    local vdt = vPlot:GetDistrictType()
                    local vdtName = "none"
                    if vdt >= 0 then
                        local vdInfo = GameInfo.Districts[vdt]
                        if vdInfo then vdtName = vdInfo.DistrictType end
                    end
                    table.insert(validTiles, vPlot:GetX() .. "," .. vPlot:GetY() .. "=" .. vdtName)
                end
            end
        end
    end
    local reqStr = #requirements > 0 and " Requirements: " .. table.concat(requirements, "; ") or ""
    local tilesStr = #validTiles > 0 and " Valid tiles: " .. table.concat(validTiles, "; ") or " No valid activation tiles found."
    local classStr = ""
    local classHint = ""
    pcall(function()
        local gpClass = uInfo and uInfo.GreatPersonClass or nil
        if gpClass then
            classStr = " class=" .. gpClass
            if gpClass == "GREAT_PERSON_CLASS_WRITER" or gpClass == "GREAT_PERSON_CLASS_ARTIST" or gpClass == "GREAT_PERSON_CLASS_MUSICIAN" then
                classHint = " Hint: Must be on a city center with an empty Great Work slot of the matching type."
            end
        end
    end)
    {_bail_lua('"ERR:CANNOT_ACTIVATE|" .. Locale.Lookup(unit:GetName()) .. " (" .. uName .. ")" .. classStr .. " at (" .. ux .. "," .. uy .. ") charges=" .. charges .. "." .. reqStr .. tilesStr .. classHint')}
end
-- Track charges before activation to compute remaining.
-- GetActionCharges() is stale same-frame (async C++ activation), so we
-- compute remaining = chargesBefore - 1 rather than re-reading post-call.
local chargesBefore = 1
pcall(function() chargesBefore = unit:GetGreatPerson():GetActionCharges() or 1 end)
UnitManager.RequestCommand(unit, cmdHash, {{}})
local remCharges = chargesBefore - 1
local chargeStr = ""
if remCharges > 0 then chargeStr = " charges_remaining=" .. remCharges .. " — activate again to use next charge" end
print("OK:GP_ACTIVATED|" .. Locale.Lookup(unit:GetName()) .. " (" .. uName .. ") at " .. ux .. "," .. uy .. chargeStr)
print("{SENTINEL}")
"""


def parse_great_people_response(lines: list[str]) -> list[GreatPersonInfo]:
    """Parse GP| lines from build_great_people_query."""
    results: list[GreatPersonInfo] = []
    for line in lines:
        if line.startswith("GREAT_PERSON|"):
            fields = dict(part.split("=", 1) for part in line.split("|")[1:] if "=" in part)
            if "id" not in fields:
                continue
            def number(key: str) -> int:
                value = fields.get(key, "?")
                return -1 if value in {"?", "unknown", ""} else _int(value)
            results.append(GreatPersonInfo(
                class_name=fields.get("class", ""), individual_name=fields.get("name", ""),
                era_name=fields.get("era", ""), cost=number("cost"), claimant=fields.get("claimant", ""),
                player_points=number("my_points"), ability=fields.get("active", ""),
                gold_cost=number("gold_cost"), faith_cost=number("faith_cost"),
                can_recruit=None if fields.get("can_recruit") == "unknown" else fields.get("can_recruit") == "true",
                individual_id=number("id"), passive=fields.get("passive", ""),
                great_works=fields.get("great_works", ""), competition=fields.get("progress", "")))
            continue
        if line.startswith("GP|"):
            parts = line.split("|")
            if len(parts) >= 7:
                ability = parts[7] if len(parts) >= 8 else ""
                gold_cost = 0
                faith_cost = 0
                can_recruit = False
                individual_id = 0
                if len(parts) >= 10:
                    cost_str = parts[8]  # "gold:X,faith:Y,recruit:true/false"
                    for kv in cost_str.split(","):
                        k, _, v = kv.partition(":")
                        if k == "gold":
                            gold_cost = _int(v) if v else 0
                        elif k == "faith":
                            faith_cost = _int(v) if v else 0
                        elif k == "recruit":
                            can_recruit = v == "true"
                    individual_id = _int(parts[9])
                results.append(
                    GreatPersonInfo(
                        class_name=parts[1],
                        individual_name=parts[2],
                        era_name=parts[3],
                        cost=_int(parts[4]),
                        claimant=parts[5],
                        player_points=_int(parts[6]),
                        ability=ability,
                        gold_cost=gold_cost,
                        faith_cost=faith_cost,
                        can_recruit=can_recruit,
                        individual_id=individual_id,
                    )
                )
    return results


def build_gp_advisor_query(unit_index: int) -> str:
    """InGame context: list candidate cities for a Great Person activation.

    Reports each city that has the matching district, with activation
    eligibility, distance from GP, city yield, and great work slot info.
    """
    sentinel = SENTINEL
    return f"""
{_lua_get_unit(unit_index)}
local uInfo = GameInfo.Units[unit:GetType()]
if not uInfo then {_bail("ERR:UNIT_INFO_NOT_FOUND")} end
local gpClass = ""
pcall(function() gpClass = uInfo.GreatPersonClass end)
if gpClass == "" then {_bail("ERR:NOT_A_GREAT_PERSON")} end
local classToDistrict = {{
    GREAT_PERSON_CLASS_SCIENTIST = "DISTRICT_CAMPUS",
    GREAT_PERSON_CLASS_ENGINEER = "DISTRICT_INDUSTRIAL_ZONE",
    GREAT_PERSON_CLASS_MERCHANT = "DISTRICT_COMMERCIAL_HUB",
    GREAT_PERSON_CLASS_WRITER = "DISTRICT_THEATER",
    GREAT_PERSON_CLASS_ARTIST = "DISTRICT_THEATER",
    GREAT_PERSON_CLASS_MUSICIAN = "DISTRICT_THEATER",
    GREAT_PERSON_CLASS_PROPHET = "DISTRICT_HOLY_SITE",
    GREAT_PERSON_CLASS_GENERAL = "DISTRICT_ENCAMPMENT",
    GREAT_PERSON_CLASS_ADMIRAL = "DISTRICT_HARBOR",
}}
local classToYield = {{
    GREAT_PERSON_CLASS_SCIENTIST = "YIELD_SCIENCE",
    GREAT_PERSON_CLASS_ENGINEER = "YIELD_PRODUCTION",
    GREAT_PERSON_CLASS_MERCHANT = "YIELD_GOLD",
    GREAT_PERSON_CLASS_WRITER = "YIELD_CULTURE",
    GREAT_PERSON_CLASS_ARTIST = "YIELD_CULTURE",
    GREAT_PERSON_CLASS_MUSICIAN = "YIELD_CULTURE",
    GREAT_PERSON_CLASS_PROPHET = "YIELD_FAITH",
    GREAT_PERSON_CLASS_GENERAL = "YIELD_PRODUCTION",
    GREAT_PERSON_CLASS_ADMIRAL = "YIELD_GOLD",
}}
local targetDist = classToDistrict[gpClass]
if not targetDist then {_bail("ERR:UNKNOWN_GP_CLASS")} end
local charges = -1
local gp = unit:GetGreatPerson()
if gp then pcall(function() charges = gp:GetActionCharges() end) end
print("GP_INFO|" .. Locale.Lookup(unit:GetName()) .. "|" .. gpClass .. "|" .. targetDist .. "|" .. unit:GetX() .. "|" .. unit:GetY() .. "|" .. charges)
local validPlotSet = {{}}
if gp then
    pcall(function()
        local plots = gp:GetActivationHighlightPlots()
        if plots then
            for _, pIdx in ipairs(plots) do validPlotSet[pIdx] = true end
        end
    end)
end
local yieldType = classToYield[gpClass]
local yieldIdx = -1
if yieldType then pcall(function() yieldIdx = GameInfo.Yields[yieldType].Index end) end
local isCultural = gpClass == "GREAT_PERSON_CLASS_WRITER" or gpClass == "GREAT_PERSON_CLASS_ARTIST" or gpClass == "GREAT_PERSON_CLASS_MUSICIAN"
local targetDistInfo = GameInfo.Districts[targetDist]
if not targetDistInfo then {_bail("ERR:DISTRICT_NOT_FOUND")} end
for i, city in Players[me]:GetCities():Members() do
    pcall(function()
        local districts = city:GetDistricts()
        if districts:HasDistrict(targetDistInfo.Index, true) then
            local dObj = districts:GetDistrict(targetDistInfo.Index)
            if dObj then
                local dx, dy = dObj:GetX(), dObj:GetY()
                local pPlot = Map.GetPlot(dx, dy)
                local plotIdx = pPlot:GetIndex()
                local canAct = validPlotSet[plotIdx] == true
                local dist = Map.GetPlotDistance(unit:GetX(), unit:GetY(), dx, dy)
                local cityYield = 0
                if yieldIdx >= 0 then
                    pcall(function() cityYield = city:GetYield(yieldIdx) end)
                end
                local slotsFree = -1
                local slotsTotal = -1
                if isCultural then
                    pcall(function()
                        local bldgs = city:GetBuildings()
                        local free = 0
                        local total = 0
                        for bld in GameInfo.Buildings() do
                            if bldgs:HasBuilding(bld.Index) then
                                for s = 0, 5 do
                                    local ok2, gwType = pcall(function() return bldgs:GetGreatWorkSlotType(bld.Index, s) end)
                                    if ok2 and gwType and gwType >= 0 then
                                        total = total + 1
                                        local ok3, gw = pcall(function() return bldgs:GetGreatWorkInSlot(bld.Index, s) end)
                                        if not ok3 or not gw or gw < 0 then
                                            free = free + 1
                                        end
                                    end
                                end
                            end
                        end
                        slotsFree = free
                        slotsTotal = total
                    end)
                end
                local cn = (Locale.Lookup(city:GetName()):gsub("|", "/"))
                print("GP_CITY|" .. cn .. "|" .. city:GetID() .. "|" .. dx .. "|" .. dy .. "|" .. tostring(canAct) .. "|" .. dist .. "|" .. cityYield .. "|" .. slotsFree .. "|" .. slotsTotal)
            end
        end
    end)
end
print("{sentinel}")
"""


def parse_gp_advisor_response(lines: list[str]) -> GPAdvisorResult | None:
    """Parse GP_INFO and GP_CITY lines from build_gp_advisor_query."""
    gp_name = ""
    gp_class = ""
    target_district = ""
    gp_x = 0
    gp_y = 0
    charges = -1
    cities: list[GPAdvisorCity] = []

    for line in lines:
        if line.startswith("GP_INFO|"):
            parts = line.split("|")
            if len(parts) >= 7:
                gp_name = parts[1]
                gp_class = parts[2]
                target_district = parts[3]
                gp_x = int(parts[4])
                gp_y = int(parts[5])
                charges = int(parts[6])
        elif line.startswith("GP_CITY|"):
            parts = line.split("|")
            if len(parts) >= 10:
                try:
                    cities.append(
                        GPAdvisorCity(
                            city_name=parts[1],
                            city_id=int(parts[2]),
                            district_x=int(parts[3]),
                            district_y=int(parts[4]),
                            can_activate=parts[5] == "true",
                            distance=int(parts[6]),
                            city_yield=_int(parts[7]),
                            slots_free=int(parts[8]),
                            slots_total=int(parts[9]),
                        )
                    )
                except (ValueError, IndexError):
                    continue

    if not gp_name:
        return None
    return GPAdvisorResult(
        gp_name=gp_name,
        gp_class=gp_class,
        target_district=target_district,
        gp_x=gp_x,
        gp_y=gp_y,
        charges=charges,
        cities=cities,
    )


