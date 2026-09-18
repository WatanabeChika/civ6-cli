"""Tech domain — Lua builders and parsers."""

from __future__ import annotations

from civ6_cli.lua._helpers import SENTINEL, _LUA_SAFE_READ, _bail
from civ6_cli.lua.models import (
    CivicOption,
    LockedCivic,
    LockedTech,
    TechCivicStatus,
    TechOption,
)


def build_tech_civics_query() -> str:
    return _LUA_SAFE_READ + """
local id = Game.GetLocalPlayer()
local te = Players[id]:GetTechs()
local cu = Players[id]:GetCulture()
local techIdx = safe(function() return te:GetResearchingTech() end,-1)
local civicIdx = safe(function() return cu:GetProgressingCivic() end,-1)
local techName = "None"
local techTurns = -1
if techIdx >= 0 then
    techName = safe(function() return Locale.Lookup(GameInfo.Technologies[techIdx].Name) end,'unknown')
    techTurns = safe(function() return te:GetTurnsToResearch(techIdx) end, -1)
end
local civicName = "None"
local civicTurns = -1
if civicIdx >= 0 then
    civicName = safe(function() return Locale.Lookup(GameInfo.Civics[civicIdx].Name) end,'unknown')
    civicTurns = safe(function() return cu:GetTurnsLeft() end, nil)
    if civicTurns == nil then civicTurns = safe(function() return cu:GetTurnsLeftOnCurrentCivic() end, -1) end
end
local currentTech = techIdx >= 0 and GameInfo.Technologies[techIdx] or nil
local currentCivic = civicIdx >= 0 and GameInfo.Civics[civicIdx] or nil
print("CURRENT|" .. techName .. "|" .. techTurns .. "|" .. civicName .. "|" .. civicTurns
    .. "|tech_type=" .. (currentTech and currentTech.TechnologyType or 'NONE')
    .. "|tech_progress=" .. (techIdx >= 0 and safe(function() return te:GetResearchProgress(techIdx) end, '?') or '?')
    .. "|tech_cost=" .. (techIdx >= 0 and safe(function() return te:GetResearchCost(techIdx) end, '?') or '?')
    .. "|civic_type=" .. (currentCivic and currentCivic.CivicType or 'NONE')
    .. "|civic_progress=" .. (civicIdx >= 0 and safe(function() return cu:GetCulturalProgress(civicIdx) end, '?') or '?')
    .. "|civic_cost=" .. (civicIdx >= 0 and safe(function() return cu:GetCultureCost(civicIdx) end, '?') or '?'))
-- Build boost lookup
local boostsByTech = {}
local boostsByCivic = {}
for b in GameInfo.Boosts() do
    if b.TechnologyType then boostsByTech[b.TechnologyType] = b end
    if b.CivicType then boostsByCivic[b.CivicType] = b end
end
-- Build tech prereqs lookup
local techPrereqs = {}
pcall(function()
    for row in GameInfo.TechnologyPrereqs() do
        if not techPrereqs[row.Technology] then techPrereqs[row.Technology] = {} end
        table.insert(techPrereqs[row.Technology], row.PrereqTech)
    end
end)
for tech in GameInfo.Technologies() do
    if te:CanResearch(tech.Index) and not te:HasTech(tech.Index) then
        local cost = safe(function() return te:GetResearchCost(tech.Index) end, -1)
        local progress = safe(function() return te:GetResearchProgress(tech.Index) end, -1)
        local turns = safe(function() return te:GetTurnsToResearch(tech.Index) end, -1)
        local pct = cost > 0 and progress >= 0 and math.floor(progress * 100 / cost) or -1
        local boosted = safe(function() return te:HasBoostBeenTriggered(tech.Index) end, nil)
        local boostDesc = ""
        local b = boostsByTech[tech.TechnologyType]
        if b and b.TriggerDescription then
            boostDesc = Locale.Lookup(b.TriggerDescription):gsub("|", "/")
        end
        local unlocks = {}
        for u in GameInfo.Units() do if u.PrereqTech == tech.TechnologyType then table.insert(unlocks, Locale.Lookup(u.Name)) end end
        for bld in GameInfo.Buildings() do if bld.PrereqTech == tech.TechnologyType then table.insert(unlocks, Locale.Lookup(bld.Name)) end end
        for d in GameInfo.Districts() do if d.PrereqTech == tech.TechnologyType then table.insert(unlocks, Locale.Lookup(d.Name)) end end
        for imp in GameInfo.Improvements() do if imp.PrereqTech == tech.TechnologyType then table.insert(unlocks, Locale.Lookup(imp.Name)) end end
        for r in GameInfo.Resources() do
            if r.PrereqTech == tech.TechnologyType then table.insert(unlocks, "Reveals " .. Locale.Lookup(r.Name)) end
        end
        pcall(function()
            for proj in GameInfo.Projects() do
                if proj.PrereqTech == tech.TechnologyType then table.insert(unlocks, "Project: " .. Locale.Lookup(proj.Name)) end
            end
        end)
        local unlockStr = table.concat(unlocks, ", "):gsub("|", "/")
        local boostTag = boosted == nil and "unknown" or boosted and "BOOSTED" or "UNBOOSTED"
        local prereqStr = ""
        if techPrereqs[tech.TechnologyType] then
            prereqStr = table.concat(techPrereqs[tech.TechnologyType], ",")
        end
        print("TECH|" .. Locale.Lookup(tech.Name) .. "|" .. tech.TechnologyType .. "|" .. cost .. "|" .. pct .. "|" .. turns .. "|" .. boostTag .. "|" .. boostDesc .. "|" .. unlockStr .. "|" .. prereqStr .. "|" .. (tech.EraType or ""))
    end
end
local completedTechs = 0
for tech in GameInfo.Technologies() do
    if te:HasTech(tech.Index) then completedTechs = completedTechs + 1 end
end
local completedCivics = 0
for civic in GameInfo.Civics() do
    if cu:HasCivic(civic.Index) then completedCivics = completedCivics + 1 end
end
print("COMPLETED|" .. completedTechs .. "|" .. completedCivics)
local curEra = safe(function() return Game.GetEras():GetCurrentEra() end,0)
local prereqs = {}
for row in GameInfo.CivicPrereqs() do
    if not prereqs[row.Civic] then prereqs[row.Civic] = {} end
    table.insert(prereqs[row.Civic], row.PrereqCivic)
end
local eraLookup = {}
for e in GameInfo.Eras() do eraLookup[e.EraType] = e.Index end
for civic in GameInfo.Civics() do
    if not cu:HasCivic(civic.Index) then
        local civicEra = eraLookup[civic.EraType] or 99
        if civicEra <= curEra + 2 then
            local canProgress = true
            if prereqs[civic.CivicType] then
                for _, pType in ipairs(prereqs[civic.CivicType]) do
                    local pEntry = GameInfo.Civics[pType]
                    if pEntry and not cu:HasCivic(pEntry.Index) then canProgress = false; break end
                end
            end
            if canProgress then
                local selectable = safe(function() return cu:CanProgress(civic.Index) end, nil)
                if selectable ~= false then
                local cost = safe(function() return cu:GetCultureCost(civic.Index) end, -1)
                local currentProg = safe(function() return cu:GetCulturalProgress(civic.Index) end, -1)
                local pct2 = cost > 0 and currentProg >= 0 and math.floor(currentProg * 100 / cost) or -1
                local cultureYield = safe(function() return cu:GetCultureYield() end, 0)
                local turns2 = civic.Index == civicIdx and civicTurns or (cost >= 0 and currentProg >= 0 and cultureYield > 0 and math.ceil(math.max(0,cost-currentProg) / cultureYield) or -1)
                local boosted2 = safe(function() return cu:HasBoostBeenTriggered(civic.Index) end, nil)
                local boostDesc2 = ""
                local b2 = boostsByCivic[civic.CivicType]
                if b2 and b2.TriggerDescription then
                    boostDesc2 = Locale.Lookup(b2.TriggerDescription):gsub("|", "/")
                end
                local boostTag2 = boosted2 == nil and "unknown" or boosted2 and "BOOSTED" or "UNBOOSTED"
                local unlocks = {}
                for _, source in ipairs({GameInfo.Units,GameInfo.Buildings,GameInfo.Districts,GameInfo.Improvements,GameInfo.Policies,GameInfo.Governments,GameInfo.Projects}) do
                    pcall(function()
                        for row in source() do if row.PrereqCivic == civic.CivicType then table.insert(unlocks,Locale.Lookup(row.Name)) end end
                    end)
                end
                local unlockStr = table.concat(unlocks, ', '):gsub('|','/')
                local civicPrereqStr = ""
                if prereqs[civic.CivicType] then
                    civicPrereqStr = table.concat(prereqs[civic.CivicType], ",")
                end
                print("CIVIC|" .. Locale.Lookup(civic.Name) .. "|" .. civic.CivicType .. "|" .. cost .. "|" .. pct2 .. "|" .. turns2 .. "|" .. boostTag2 .. "|" .. boostDesc2 .. "|" .. unlockStr .. "|" .. civicPrereqStr .. "|" .. (civic.EraType or ""))
                end
            end
        end
    end
end
-- Locked civics: within curEra + 2 only (skip far-future clutter)
for civic in GameInfo.Civics() do
    local civicEra = eraLookup[civic.EraType] or 99
    if not cu:HasCivic(civic.Index) and civicEra <= curEra + 2 then
        local missing = {}
        if prereqs[civic.CivicType] then
            for _, pType in ipairs(prereqs[civic.CivicType]) do
                local pEntry = GameInfo.Civics[pType]
                if pEntry and not cu:HasCivic(pEntry.Index) then
                    table.insert(missing, (Locale.Lookup(pEntry.Name):gsub("|", "/")))
                end
            end
        end
        if #missing > 0 then
            local boostDesc = ""
            local b = boostsByCivic[civic.CivicType]
            if b and b.TriggerDescription then boostDesc = Locale.Lookup(b.TriggerDescription):gsub("|", "/") end
            local boost = safe(function() return cu:HasBoostBeenTriggered(civic.Index) end, nil)
            local boostTag = boost == nil and "unknown" or boost and "BOOSTED" or "UNBOOSTED"
            print("LOCKED_CIVIC|" .. Locale.Lookup(civic.Name):gsub("|", "/") .. "|" .. civic.CivicType .. "|" .. table.concat(missing, ",") .. "|" .. (civic.EraType or "") .. "|" .. boostTag .. "|" .. boostDesc)
        end
    end
end
-- Locked techs: within curEra + 2 only (skip far-future clutter)
for tech in GameInfo.Technologies() do
    local techEra = eraLookup[tech.EraType] or 99
    if not te:HasTech(tech.Index) and not te:CanResearch(tech.Index) and techEra <= curEra + 2 then
        local missing = {}
        if techPrereqs[tech.TechnologyType] then
            for _, pType in ipairs(techPrereqs[tech.TechnologyType]) do
                local pEntry = GameInfo.Technologies[pType]
                if pEntry and not te:HasTech(pEntry.Index) then
                    table.insert(missing, (Locale.Lookup(pEntry.Name):gsub("|", "/")))
                end
            end
        end
        if #missing > 0 then
            local boostDesc = ""
            local b = boostsByTech[tech.TechnologyType]
            if b and b.TriggerDescription then boostDesc = Locale.Lookup(b.TriggerDescription):gsub("|", "/") end
            local boost = safe(function() return te:HasBoostBeenTriggered(tech.Index) end, nil)
            local boostTag = boost == nil and "unknown" or boost and "BOOSTED" or "UNBOOSTED"
            print("LOCKED_TECH|" .. Locale.Lookup(tech.Name):gsub("|", "/") .. "|" .. tech.TechnologyType .. "|" .. table.concat(missing, ",") .. "|" .. (tech.EraType or "") .. "|" .. boostTag .. "|" .. boostDesc)
        end
    end
end
print("{SENTINEL}")
""".replace("{SENTINEL}", SENTINEL)


def _build_set_ingame(
    name: str,
    gi_table: str,
    type_field: str,
    param: str,
    operation: str,
    ok_prefix: str,
) -> str:
    """Shared builder for set_research / set_civic via InGame UI."""
    err_label = "TECH" if "Tech" in gi_table else "CIVIC"
    has_method = "HasTech" if "Tech" in gi_table else "HasCivic"
    can_method = "CanResearch" if "Tech" in gi_table else "CanProgress"
    player_method = "GetTechs" if "Tech" in gi_table else "GetCulture"
    return f"""
local id = Game.GetLocalPlayer()
local idx = nil
for row in GameInfo.{gi_table}() do
    if row.{type_field} == "{name}" then idx = row.Index; break end
end
if idx == nil then {_bail(f"ERR:{err_label}_NOT_FOUND|{name}")} end
if Players[id]:{player_method}():{has_method}(idx) then
    {_bail(f"ERR:ALREADY_COMPLETED|{name} is already researched")}
end
if not Players[id]:{player_method}():{can_method}(idx) then
    {_bail(f"ERR:CANNOT_SELECT_{err_label}|{name} is not currently available; use research options")}
end
local params = {{}}
params[PlayerOperations.{param}] = idx
UI.RequestPlayerOperation(id, PlayerOperations.{operation}, params)
-- Do not perform any fallible readback or notification cleanup after the
-- accepted request.  Some game builds expose those UI methods as nil even
-- though the research/civic change has already succeeded.
print("{ok_prefix}|{name}")
print("{SENTINEL}")
"""


def build_set_research(tech_name: str) -> str:
    return _build_set_ingame(
        tech_name,
        "Technologies",
        "TechnologyType",
        "PARAM_TECH_TYPE",
        "RESEARCH",
        "OK:RESEARCHING",
    )


def build_set_civic(civic_name: str) -> str:
    return _build_set_ingame(
        civic_name,
        "Civics",
        "CivicType",
        "PARAM_CIVIC_TYPE",
        "PROGRESS_CIVIC",
        "OK:PROGRESSING",
    )


def _build_set_gamecore(
    name: str,
    gi_table: str,
    type_field: str,
    player_method: str,
    setter: str,
    getter: str | None,
    ok_prefix: str,
) -> str:
    """Shared builder for set_research / set_civic via GameCore fallback."""
    err_label = "TECH" if "Tech" in gi_table else "CIVIC"
    verify = ""
    if getter:
        verify = f"""
local now = Players[id]:{player_method}():{getter}()
if now == idx then
    print("{ok_prefix}|{name}")
else
    {_bail(f"ERR:RESEARCH_FAILED|GameCore also failed to set {name}")}
end"""
    else:
        verify = f'\nprint("{ok_prefix}|{name}")'
    has_method = "HasTech" if "Tech" in gi_table else "HasCivic"
    completed_method = "GetTechs" if "Tech" in gi_table else "GetCulture"
    return f"""
local id = Game.GetLocalPlayer()
local idx = nil
for row in GameInfo.{gi_table}() do
    if row.{type_field} == "{name}" then idx = row.Index; break end
end
if idx == nil then {_bail(f"ERR:{err_label}_NOT_FOUND|{name}")} end
if Players[id]:{completed_method}():{has_method}(idx) then
    {_bail(f"ERR:ALREADY_COMPLETED|{name} is already researched")}
end
Players[id]:{player_method}():{setter}(idx){verify}
print("{SENTINEL}")
"""


def build_set_research_gamecore(tech_name: str) -> str:
    """Set tech via GameCore — fallback when InGame RequestPlayerOperation silently fails."""
    return _build_set_gamecore(
        tech_name,
        "Technologies",
        "TechnologyType",
        "GetTechs",
        "SetResearchingTech",
        "GetResearchingTech",
        "OK:RESEARCHING_GAMECORE",
    )


def build_set_civic_gamecore(civic_name: str) -> str:
    """Set civic via GameCore — fallback when InGame RequestPlayerOperation silently fails."""
    return _build_set_gamecore(
        civic_name,
        "Civics",
        "CivicType",
        "GetCulture",
        "SetProgressingCivic",
        None,
        "OK:PROGRESSING_GC",
    )


def parse_tech_civics_response(lines: list[str]) -> TechCivicStatus:
    current_research = "None"
    current_research_turns = -1
    current_civic = "None"
    current_civic_turns = -1
    available_techs: list[TechOption] = []
    available_civics: list[CivicOption] = []
    completed_tech_count = 0
    completed_civic_count = 0
    current_fields: dict[str, str] = {}

    locked_civics: list[LockedCivic] = []
    locked_techs: list[LockedTech] = []

    for line in lines:
        if line.startswith("COMPLETED|"):
            parts = line.split("|")
            completed_tech_count = int(parts[1]) if len(parts) > 1 else 0
            completed_civic_count = int(parts[2]) if len(parts) > 2 else 0
        elif line.startswith("CURRENT|"):
            parts = line.split("|")
            current_research = parts[1]
            current_research_turns = int(parts[2])
            current_civic = parts[3]
            current_civic_turns = int(parts[4])
            current_fields = dict(part.split("=", 1) for part in parts[5:] if "=" in part)
        elif line.startswith("TECH|"):
            parts = line.split("|")
            if len(parts) >= 9:
                available_techs.append(
                    TechOption(
                        name=parts[1],
                        tech_type=parts[2],
                        cost=int(parts[3]),
                        progress_pct=int(parts[4]),
                        turns=int(parts[5]),
                        boosted=None if parts[6] == "unknown" else parts[6] == "BOOSTED",
                        boost_desc=parts[7],
                        unlocks=parts[8],
                        prereqs=parts[9] if len(parts) > 9 else "",
                        era=parts[10] if len(parts) > 10 else "",
                    )
                )
            elif len(parts) >= 3:
                available_techs.append(
                    TechOption(
                        name=parts[1],
                        tech_type=parts[2],
                        cost=0,
                        progress_pct=0,
                        turns=0,
                        boosted=False,
                        boost_desc="",
                        unlocks="",
                    )
                )
        elif line.startswith("CIVIC|"):
            parts = line.split("|")
            if len(parts) >= 8:
                available_civics.append(
                    CivicOption(
                        name=parts[1],
                        civic_type=parts[2],
                        cost=int(parts[3]),
                        progress_pct=int(parts[4]),
                        turns=int(parts[5]),
                        boosted=None if parts[6] == "unknown" else parts[6] == "BOOSTED",
                        boost_desc=parts[7],
                        prereqs=parts[9] if len(parts) > 10 else (parts[8] if len(parts) > 8 else ""),
                        era=parts[10] if len(parts) > 10 else (parts[9] if len(parts) > 9 else ""),
                        unlocks=parts[8] if len(parts) > 10 else "",
                    )
                )
            elif len(parts) >= 3:
                available_civics.append(
                    CivicOption(
                        name=parts[1],
                        civic_type=parts[2],
                        cost=0,
                        progress_pct=0,
                        turns=0,
                        boosted=False,
                        boost_desc="",
                    )
                )
        elif line.startswith("LOCKED_CIVIC|"):
            parts = line.split("|")
            if len(parts) >= 4:
                locked_civics.append(
                    LockedCivic(
                        name=parts[1],
                        civic_type=parts[2],
                        missing_prereqs=parts[3].split(","),
                        era=parts[4] if len(parts) > 4 else "",
                        boosted=parts[5] == "BOOSTED" if len(parts) > 5 else False,
                        boost_desc=parts[6] if len(parts) > 6 else "",
                    )
                )
        elif line.startswith("LOCKED_TECH|"):
            parts = line.split("|")
            if len(parts) >= 4:
                locked_techs.append(
                    LockedTech(
                        name=parts[1],
                        tech_type=parts[2],
                        missing_prereqs=parts[3].split(","),
                        era=parts[4] if len(parts) > 4 else "",
                        boosted=parts[5] == "BOOSTED" if len(parts) > 5 else False,
                        boost_desc=parts[6] if len(parts) > 6 else "",
                    )
                )

    return TechCivicStatus(
        current_research=current_research,
        current_research_turns=current_research_turns,
        current_civic=current_civic,
        current_civic_turns=current_civic_turns,
        available_techs=available_techs,
        available_civics=available_civics,
        completed_tech_count=completed_tech_count,
        completed_civic_count=completed_civic_count,
        locked_civics=locked_civics or None,
        locked_techs=locked_techs or None,
        current_research_type=current_fields.get("tech_type", ""),
        current_civic_type=current_fields.get("civic_type", ""),
        current_research_progress=_optional_number(current_fields.get("tech_progress")),
        current_research_cost=_optional_number(current_fields.get("tech_cost")),
        current_civic_progress=_optional_number(current_fields.get("civic_progress")),
        current_civic_cost=_optional_number(current_fields.get("civic_cost")),
    )


def _optional_number(value: str | None) -> float | None:
    return None if value in {None, "?", "unknown", ""} else float(value)
