"""Fixed read-only reports for the player-visible Civ VI game state.

Every template is authored here, rather than accepting arbitrary Lua from the
terminal.  Dynamic values are parsed as bounded integers before interpolation.
"""

from __future__ import annotations

from dataclasses import dataclass

from .transport import FireTunerConnection
from .lua import congress, governance, tech
from .lua.governance import _GOVERNMENT_STATE


@dataclass(frozen=True)
class Report:
    name: str
    description: str
    lua: str
    context: str = "GameCore_Tuner"


_COMMON = """
local function safe(callback, fallback)
  local ok, value = pcall(callback)
  if ok and value ~= nil then return value end
  return fallback
end
local function clean(value)
  -- Civ VI's Lua pattern classes follow the active Windows locale.  Using
  -- %s on a UTF-8 byte string can classify a Chinese continuation byte as
  -- whitespace and remove it (for example the final byte of 漠/渠/炮).
  -- Restrict trimming and collapsing to literal ASCII spaces.
  return tostring(value or ""):gsub("|", "/"):gsub("%[NEWLINE%]", "；"):gsub("%[ICON_[^%]]+%]", ""):gsub("[\\r\\n]", " "):gsub("  +", " "):gsub("^ +", ""):gsub(" +$", "")
end
local function local_name(row)
  if not row then return "Unknown" end
  return clean(safe(function() return Locale.Lookup(row.Name) end, row.Name or "Unknown"))
end
local function resource_known(resource, techs)
  if not resource then return false end
  if not resource.PrereqTech then return true end
  local prereq = GameInfo.Technologies[resource.PrereqTech]
  return prereq and safe(function() return techs:HasTech(prereq.Index) end, false)
end
"""

_PRODUCTION_COMMON = """
local production_rows = {}
for kind, source in pairs({Unit=GameInfo.Units, Building=GameInfo.Buildings, District=GameInfo.Districts, Project=GameInfo.Projects}) do
  for row in source() do production_rows[row.Hash] = {kind=kind, row=row} end
end
local function production_value(queue, item, suffix)
  if not item then return '?' end
  return safe(function() return queue['Get' .. item.kind .. suffix](queue, item.row.Index) end, '?')
end
local function production_type(row)
  return row and (row.UnitType or row.BuildingType or row.DistrictType or row.ProjectType) or 'none'
end
"""

_REPORTS: dict[str, Report] = {
    "research": Report("research", "current research/civic and every currently selectable option",
        tech.build_tech_civics_query(), "InGame"),
    "economy": Report(
        "economy", "treasury, income, maintenance, and strategic stockpiles", _COMMON + """
local me = Game.GetLocalPlayer()
local player = Players[me]
local treasury = player:GetTreasury()
print("TREASURY|gold=" .. safe(function() return string.format("%.1f", treasury:GetGoldBalance()) end, "?") .. "|income=" .. safe(function() return string.format("%.1f", treasury:GetGoldYield()) end, "?") .. "|maintenance=" .. safe(function() return string.format("%.1f", treasury:GetTotalMaintenance()) end, "?") .. "|net=" .. safe(function() return string.format("%.1f", treasury:GetGoldYield()-treasury:GetTotalMaintenance()) end, "?"))
local resources = player:GetResources()
for row in GameInfo.Resources() do
  if row.ResourceClassType == "RESOURCECLASS_STRATEGIC" then
    local amount = safe(function() return resources:GetResourceAmount(row.Hash) end, safe(function() return resources:GetResourceAmount(row.ResourceType) end, 0))
    local domestic = safe(function() return resources:GetResourceAccumulationPerTurn(row.Hash) end, safe(function() return resources:GetResourceAccumulationPerTurn(row.ResourceType) end, 0))
    local imports = safe(function() return resources:GetResourceImportPerTurn(row.Hash) end, safe(function() return resources:GetResourceImportPerTurn(row.ResourceType) end, 0))
    local bonus = safe(function() return resources:GetBonusResourcePerTurn(row.Hash) end, safe(function() return resources:GetBonusResourcePerTurn(row.ResourceType) end, 0))
    local units = safe(function() return resources:GetUnitResourceDemandPerTurn(row.Hash) end, safe(function() return resources:GetUnitResourceDemandPerTurn(row.ResourceType) end, 0))
    local power = safe(function() return resources:GetPowerResourceDemandPerTurn(row.Hash) end, safe(function() return resources:GetPowerResourceDemandPerTurn(row.ResourceType) end, 0))
    local gain, consumption = domestic + imports + bonus, units + power
    if amount > 0 or gain > 0 or consumption > 0 then
      print("STOCKPILE|" .. local_name(row) .. "|amount=" .. amount .. "|domestic_gain=" .. domestic .. "|imports=" .. imports .. "|bonus_gain=" .. bonus .. "|gain=" .. gain .. "|unit_consumption=" .. units .. "|power_consumption=" .. power .. "|consumption=" .. consumption .. "|net_change=" .. (gain-consumption))
    end
  end
end
""", "InGame"),
    "diplomacy": Report(
        "diplomacy", "met civilizations, diplomatic state, military strength, and visibility", _COMMON + """
local me = Game.GetLocalPlayer()
local mine = Players[me]
local diplo = mine:GetDiplomacy()
local states = {"ALLIED","FRIEND","FRIENDLY","NEUTRAL","UNFRIENDLY","DENOUNCED","WAR"}
for id = 0, 62 do
  local player = Players[id]
  if player and player:IsAlive() and player:IsMajor() and (id == me or diplo:HasMet(id)) then
    local cfg = PlayerConfigurations[id]
    local state_index = safe(function() return player:GetDiplomaticAI():GetDiplomaticStateIndex(me) end, -1)
    local state = id == me and 'SELF' or states[state_index + 1] or tostring(state_index)
    local treasury, religion, culture, techs = player:GetTreasury(), player:GetReligion(), player:GetCulture(), player:GetTechs()
    print("CIV|id=" .. id .. "|" .. clean(Locale.Lookup(cfg:GetCivilizationShortDescription())) .. "|" .. clean(Locale.Lookup(cfg:GetLeaderName())) .. "|state=" .. state .. "|war=" .. (id ~= me and safe(function() return diplo:IsAtWarWith(id) end, false) and "yes" or "no") .. "|score=" .. safe(function() return player:GetScore() end, "?") .. "|military=" .. safe(function() return player:GetStats():GetMilitaryStrength() end, "?") .. "|science_per_turn=" .. safe(function() return string.format("%.1f", techs:GetScienceYield()) end, "?") .. "|culture_per_turn=" .. safe(function() return string.format("%.1f", culture:GetCultureYield()) end, "?") .. "|gold=" .. safe(function() return string.format("%.1f", treasury:GetGoldBalance()) end, "?") .. "|faith=" .. safe(function() return string.format("%.1f", religion:GetFaithBalance()) end, "?") .. "|favor=" .. safe(function() return player:GetFavor() end, "?") .. "|grievances=" .. (id == me and '-' or safe(function() return diplo:GetGrievancesAgainst(id) end, "?")) .. "|visibility=" .. (id == me and '-' or safe(function() return diplo:GetVisibilityOn(id) end, "?")))
  end
end
""", "InGame"),
    "government": Report("government", "government type, policy slots, governors, and diplomatic favor",
        governance.build_available_governments_query() + governance.build_policies_query() + governance.build_governors_query(), "InGame"),
    "religion": Report(
        "religion", "pantheon, founded religion, and detailed religion for every visible city", _COMMON + """
local me = Game.GetLocalPlayer()
local player = Players[me]
local religion = player:GetReligion()
local pantheon = safe(function() return religion:GetPantheon() end, -1)
local pantheon_row = pantheon >= 0 and GameInfo.Beliefs[pantheon] or nil
local founded = safe(function() return religion:GetReligionTypeCreated() end, -1)
local founded_row = founded >= 0 and GameInfo.Religions[founded] or nil
local founded_name = local_name(founded_row)
if founded_row and founded_row.ReligionType == "RELIGION_PANTHEON" then founded_name = "none" end
print("MY_RELIGION|founded=" .. founded_name .. "|pantheon=" .. local_name(pantheon_row) .. "|faith=" .. safe(function() return string.format("%.1f", religion:GetFaithBalance()) end, "?"))
local visibility = PlayersVisibility[me]
local diplomacy = player:GetDiplomacy()
for id = 0, 62 do
  local owner = Players[id]
  if owner and owner:IsAlive() and owner:IsMajor() and (id == me or diplomacy:HasMet(id)) then
    local owner_name = clean(Locale.Lookup(PlayerConfigurations[id]:GetCivilizationShortDescription()))
    for _, city in owner:GetCities():Members() do
      local x, y = city:GetX(), city:GetY()
      if id == me or visibility:IsRevealed(x, y) then
        local city_religion = city:GetReligion()
        local majority = safe(function() return city_religion:GetMajorityReligion() end, -1)
        local majority_row = majority >= 0 and GameInfo.Religions[majority] or nil
        local followers = {}
        local religions = safe(function() return city_religion:GetReligionsInCity() end, nil)
        if religions then
          for key, entry in pairs(religions) do
            local rel_id, count = nil, nil
            if type(entry) == "table" then rel_id, count = entry.Religion, entry.Followers end
            if rel_id == nil and type(key) == "number" then rel_id, count = key, entry end
            if rel_id and rel_id >= 0 then
              local rel_row = GameInfo.Religions[rel_id]
              table.insert(followers, local_name(rel_row) .. ":" .. (count or 0))
            end
          end
        end
        print("CITY_RELIGION|owner=" .. owner_name .. "|city=" .. clean(Locale.Lookup(city:GetName())) .. "|position=" .. x .. "," .. y .. "|population=" .. city:GetPopulation() .. "|majority=" .. local_name(majority_row) .. "|followers=" .. table.concat(followers, ","))
      end
    end
  end
end
""", "InGame"),
    "victory": Report(
        "victory", "player-visible victory indicators for every met major civilization", _COMMON + """
local me = Game.GetLocalPlayer()
local diplo = Players[me]:GetDiplomacy()
local religion_founders = {}
for founder_id = 0, 62 do
  local founder = Players[founder_id]
  if founder and founder:IsAlive() and founder:IsMajor() and (founder_id == me or diplo:HasMet(founder_id)) then
    local created = safe(function() return founder:GetReligion():GetReligionTypeCreated() end, -1)
    if created and created > 0 and PlayerConfigurations[founder_id] then
      religion_founders[created] = clean(Locale.Lookup(PlayerConfigurations[founder_id]:GetCivilizationShortDescription()))
    end
  end
end
for id = 0, 62 do
  local player = Players[id]
  if player and player:IsAlive() and player:IsMajor() and (id == me or diplo:HasMet(id)) then
    local cfg = PlayerConfigurations[id]
    local stats, culture = player:GetStats(), player:GetCulture()
    local majority = safe(function() return player:GetReligion():GetReligionInMajorityOfCities() end, -1)
    local majority_name, religion_founder = 'none', 'none'
    if majority and majority > 0 then
      local religion_row = GameInfo.Religions[majority]
      majority_name = clean(safe(function() return Game.GetReligion():GetName(majority) end, local_name(religion_row)))
      religion_founder = religion_founders[majority] or 'unknown'
    end
    print("VICTORY|id=" .. id .. "|" .. clean(Locale.Lookup(cfg:GetCivilizationShortDescription())) .. "|score=" .. safe(function() return player:GetScore() end, 0) .. "|science=" .. safe(function() return stats:GetScienceVictoryPoints() end, 0) .. "/" .. safe(function() return stats:GetScienceVictoryPointsTotalNeeded() end, "?") .. "|diplo=" .. safe(function() return stats:GetDiplomaticVictoryPoints() end, 0) .. "|international_tourists=" .. safe(function() return culture:GetTouristsTo() end, 0) .. "|domestic_tourists=" .. safe(function() return culture:GetStaycationers() end, 0) .. "|majority_religion=" .. majority_name .. "|religion_founder=" .. religion_founder)
  end
end
""", "InGame"),
    "great-people": Report(
        "great-people", "available Great People, abilities, points, claimants, and patronage costs", _COMMON + """
local me = Game.GetLocalPlayer()
local timeline_source = safe(function() return Game.GetGreatPeople() end, nil)
local timeline = safe(function() return timeline_source:GetTimeline() end, nil)
local my_points = safe(function() return Players[me]:GetGreatPeoplePoints() end, nil)
local function add_unique(parts, seen, value)
  value = clean(value or "")
  if value ~= "" and not seen[value] then
    seen[value] = true
    table.insert(parts, value)
  end
end
local function modifier_summaries(source, person_type)
  local parts, seen = {}, {}
  local ok = pcall(function() for relation in source() do
    if relation.GreatPersonIndividualType == person_type then
      local key = safe(function() return GameEffects.GetModifierTextKey(relation.ModifierId, "Summary") end, nil)
      local text = key and safe(function() return GameEffects.GetModifierText(relation.ModifierId, key) end, nil) or nil
      add_unique(parts, seen, text or ('unknown: ' .. tostring(relation.ModifierId)))
    end
  end end)
  if not ok then return {'unknown'} end
  return parts
end
local function great_works(person_type)
  local parts, seen = {}, {}
  local ok = pcall(function() for work in GameInfo.GreatWorks() do
    if work.GreatPersonIndividualType == person_type then add_unique(parts, seen, local_name(work)) end
  end end)
  if not ok then return {'unknown'} end
  return parts
end
if timeline then
  for _, entry in ipairs(timeline) do
    local class = entry.Class and GameInfo.GreatPersonClasses[entry.Class] or nil
    local person = entry.Individual and GameInfo.GreatPersonIndividuals[entry.Individual] or nil
    if class and person then
      local era = entry.Era and GameInfo.Eras[entry.Era] or nil
      local claimant = "unclaimed"
      if entry.Claimant and entry.Claimant >= 0 and PlayerConfigurations[entry.Claimant] then claimant = clean(Locale.Lookup(PlayerConfigurations[entry.Claimant]:GetCivilizationShortDescription())) end
      local active = {}
      local override = clean(safe(function() return Locale.Lookup(person.ActionEffectTextOverride) end, ""))
      if person.ActionEffectTextOverride and person.ActionEffectTextOverride ~= "" and override ~= clean(person.ActionEffectTextOverride) then
        table.insert(active, override)
      else
        active = modifier_summaries(GameInfo.GreatPersonIndividualActionModifiers, person.GreatPersonIndividualType)
      end
      local passive = modifier_summaries(GameInfo.GreatPersonIndividualBirthModifiers, person.GreatPersonIndividualType)
      local works = great_works(person.GreatPersonIndividualType)
      local points = safe(function() return my_points:GetPointsTotal(entry.Class) end, '?')
      local gold = safe(function() return timeline_source:GetPatronizeCost(me, entry.Individual, 2) end, '?')
      local faith = safe(function() return timeline_source:GetPatronizeCost(me, entry.Individual, 5) end, '?')
      local recruit = safe(function() return timeline_source:CanRecruitPerson(me, entry.Individual) end, 'unknown')
      local progress = {}
      for id = 0, 62 do
        local owner = Players[id]
        if owner and owner:IsAlive() and owner:IsMajor() and PlayerConfigurations[id] and (id == me or Players[me]:GetDiplomacy():HasMet(id)) then
          local owner_name = clean(Locale.Lookup(PlayerConfigurations[id]:GetCivilizationShortDescription()))
          local owner_points = safe(function() return owner:GetGreatPeoplePoints():GetPointsTotal(entry.Class) end, '?')
          table.insert(progress, owner_name .. ":" .. tostring(owner_points) .. "/" .. (entry.Cost or 0))
        end
      end
      print("GREAT_PERSON|id=" .. entry.Individual .. "|can_recruit=" .. tostring(recruit) .. "|class=" .. local_name(class) .. "|name=" .. local_name(person) .. "|era=" .. local_name(era) .. "|cost=" .. (entry.Cost or 0) .. "|claimant=" .. claimant .. "|my_points=" .. points .. "|gold_cost=" .. gold .. "|faith_cost=" .. faith .. "|active=" .. (#active > 0 and table.concat(active, "；") or "none") .. "|passive=" .. (#passive > 0 and table.concat(passive, "；") or "none") .. "|great_works=" .. (#works > 0 and table.concat(works, "、") or "none") .. "|progress=" .. table.concat(progress, ","))
    end
  end
else
  print("GREAT_PERSON|system_unavailable")
end
""", "InGame"),
    "great-works": Report(
        "great-works", "owned Great Works, their creators, locations, yields, and empty slots", _COMMON + """
local me = Game.GetLocalPlayer()
local total, occupied, empty = 0, 0, 0
for _, city in Players[me]:GetCities():Members() do
  local buildings = city:GetBuildings()
  for building in GameInfo.Buildings() do
    if safe(function() return buildings:HasBuilding(building.Index) end, false) then
      local slots = safe(function() return buildings:GetNumGreatWorkSlots(building.Index) end, 0)
      if slots and slots > 0 then
        total = total + slots
        for slot = 0, slots - 1 do
          local work_index = safe(function() return buildings:GetGreatWorkInSlot(building.Index, slot) end, -1)
          if work_index and work_index >= 0 then
            occupied = occupied + 1
            local work_type = safe(function() return buildings:GetGreatWorkTypeFromIndex(work_index) end, -1)
            local work = work_type >= 0 and GameInfo.GreatWorks[work_type] or nil
            local data = safe(function() return Game.GetGreatWorkDataFromIndex(work_index) end, nil)
            local object_name = work and clean(Locale.Lookup('LOC_' .. work.GreatWorkObjectType)) or 'Unknown'
            local yields = {}
            if work then
              for change in GameInfo.GreatWork_YieldChanges() do
                if change.GreatWorkType == work.GreatWorkType then
                  local yield = GameInfo.Yields[change.YieldType]
                  table.insert(yields, local_name(yield) .. ':' .. change.YieldChange)
                end
              end
            end
            print("GREAT_WORK|id=" .. work_index .. "|name=" .. local_name(work) .. "|type=" .. object_name .. "|creator=" .. clean(data and Locale.Lookup(data.CreatorName) or safe(function() return Locale.Lookup(buildings:GetCreatorNameFromIndex(work_index)) end, 'Unknown')) .. "|city=" .. clean(Locale.Lookup(city:GetName())) .. "|city_id=" .. city:GetID() .. "|building=" .. local_name(building) .. "|building_type=" .. building.BuildingType .. "|slot=" .. slot+1 .. "/" .. slots .. "|slot_index=" .. slot .. "|yields=" .. (#yields > 0 and table.concat(yields, '、') or 'none') .. "|tourism=" .. clean(work and work.Tourism or 0))
          else
            empty = empty + 1
            print("GREAT_WORK_SLOT|city=" .. clean(Locale.Lookup(city:GetName())) .. "|city_id=" .. city:GetID() .. "|building=" .. local_name(building) .. "|building_type=" .. building.BuildingType .. "|slot=" .. slot+1 .. "/" .. slots .. "|slot_index=" .. slot .. "|state=empty")
          end
        end
      end
    end
  end
end
print("GREAT_WORK_SUMMARY|occupied=" .. occupied .. "|empty=" .. empty .. "|total=" .. total)
""", "InGame"),
    "notifications": Report(
        "notifications", "active notifications and end-turn blockers", _COMMON + """
local me = Game.GetLocalPlayer()
local list = safe(function() return NotificationManager.GetList(me) end, nil)
local total = 0
if list then
  for _, id in ipairs(list) do
    pcall(function()
      local entry = NotificationManager.Find(me, id)
      if entry and not entry:IsDismissed() then
        total = total + 1
        local blocking = safe(function() return entry:GetEndTurnBlocking() end, 0)
        print("NOTIFICATION|type=" .. clean(safe(function() return entry:GetTypeName() end, "UNKNOWN")) .. "|blocking=" .. (blocking ~= 0 and 'yes' or 'no') .. "|blocking_code=" .. blocking .. "|message=" .. clean(safe(function() return entry:GetMessage() end, "")))
      end
    end)
  end
end
print("NOTIFICATION_COUNT|" .. total)
""", "InGame"),
    "blockers": Report(
        "blockers", "unique conditions currently preventing a safe end turn", _COMMON + """
local me = Game.GetLocalPlayer()
local list = safe(function() return NotificationManager.GetList(me) end, nil)
local seen, found = {}, 0
if list then
  for _, id in ipairs(list) do
    pcall(function()
      local entry = NotificationManager.Find(me, id)
      if entry and not entry:IsDismissed() then
        local blocking = safe(function() return entry:GetEndTurnBlocking() end, 0)
        if blocking and blocking ~= 0 then
          local kind = "UNKNOWN"
          for key, value in pairs(EndTurnBlockingTypes or {}) do if value == blocking then kind = key; break end end
          if not seen[kind] then
            seen[kind] = true
            print("BLOCKING|type=" .. clean(kind) .. "|message=" .. clean(safe(function() return entry:GetMessage() end, "")))
            found = found + 1
          end
        end
      end
    end)
  end
end
if found == 0 then print("BLOCKING|none") end
""", "InGame"),
    "trade": Report(
        "trade", "trade-route capacity, active routes, and idle traders", _COMMON + """
local me = Game.GetLocalPlayer()
local player = Players[me]
local trade = player:GetTrade()
local capacity = safe(function() return trade:GetOutgoingRouteCapacity() end, 0)
local active = 0
for _, city in player:GetCities():Members() do
  pcall(function()
    local routes = city:GetTrade():GetOutgoingRoutes()
    if routes then
      for _, route in ipairs(routes) do
        active = active + 1
        local destination = Players[route.DestinationCityPlayer]:GetCities():FindID(route.DestinationCityID)
        local destination_name = destination and clean(Locale.Lookup(destination:GetName())) or "Unknown"
        print("ROUTE|trader=" .. (route.TraderUnitID or "?") .. "|from=" .. clean(Locale.Lookup(city:GetName())) .. "|to=" .. destination_name .. "|destination_player=" .. (route.DestinationCityPlayer or "?"))
      end
    end
  end)
end
print("TRADE_CAPACITY|capacity=" .. capacity .. "|active=" .. active)
for _, unit in player:GetUnits():Members() do
  local info = safe(function() return GameInfo.Units[unit:GetType()] end, nil)
  if info and info.MakeTradeRoute then
    print("TRADER|id=" .. unit:GetID() .. "|position=" .. unit:GetX() .. "," .. unit:GetY() .. "|moves=" .. safe(function() return unit:GetMovesRemaining() end, 0))
  end
end
""", "InGame"),
    "resources": Report(
        "resources", "all revealed resource tiles, including owner and improvement", _COMMON + """
local me = Game.GetLocalPlayer()
local visibility = PlayersVisibility[me]
local count = 0
local techs = Players[me]:GetTechs()
for index = 0, Map.GetPlotCount() - 1 do
  local plot = Map.GetPlotByIndex(index)
  local x, y = plot:GetX(), plot:GetY()
  if visibility:IsRevealed(x, y) then
    local resource_index = plot:GetResourceType()
    if resource_index and resource_index >= 0 then
      local resource = GameInfo.Resources[resource_index]
      if resource_known(resource, techs) then
        local visible = visibility:IsVisible(plot:GetIndex())
        local improvement = visible and safe(function() return GameInfo.Improvements[plot:GetImprovementType()] end, nil) or nil
        print("RESOURCE|" .. local_name(resource) .. "|class=" .. clean(resource.ResourceClassType) .. "|position=" .. x .. "," .. y .. "|owner=" .. (visible and safe(function() return plot:GetOwner() end, -1) or '?') .. "|improvement=" .. (visible and (improvement and local_name(improvement) or 'none') or 'unknown'))
        count = count + 1
      end
    end
  end
end
print("RESOURCE_COUNT|" .. count)
"""),
    "city-states": Report("city-states", "met city-states, envoy count, suzerainty, and bonuses",
        governance.build_city_states_query(), "InGame"),
    "spies": Report(
        "spies", "owned spies, their location, rank, and current mission when available", _COMMON + """
local me = Game.GetLocalPlayer()
for _, unit in Players[me]:GetUnits():Members() do
  local info = safe(function() return GameInfo.Units[unit:GetType()] end, nil)
  if info and info.UnitType == "UNIT_SPY" then
    local rank = safe(function() return unit:GetExperience():GetLevel() end, 1)
    local operation_index = safe(function() return unit:GetSpyOperation() end, -1)
    local operation = operation_index and operation_index >= 0 and GameInfo.UnitOperations[operation_index] or nil
    local operation_name = operation and clean(Locale.Lookup(operation.Description or operation.Name)) or 'none'
    local end_turn = safe(function() return unit:GetSpyOperationEndTurn() end, -1)
    local remaining = end_turn and end_turn >= 0 and math.max(0, end_turn - Game.GetCurrentGameTurn()) or -1
    local total = operation_index and operation_index >= 0 and safe(function() return UnitManager.GetTimeToComplete(operation_index, unit) end, -1) or -1
    print("SPY|id=" .. unit:GetID() .. "|name=" .. clean(safe(function() return Locale.Lookup(unit:GetName()) end, "Unknown")) .. "|position=" .. safe(function() return unit:GetX() end, -9999) .. "," .. safe(function() return unit:GetY() end, -9999) .. "|rank=" .. rank .. "|moves=" .. safe(function() return unit:GetMovesRemaining() end, 0) .. "|operation=" .. operation_name .. "|turns=" .. remaining .. "|total_turns=" .. total)
  end
end
""", "InGame"),
    "congress": Report("congress", "World Congress timing, favor, vote-cost curve, and session status",
        congress.build_world_congress_query(), "InGame"),
    "era": Report("era", "current era, era score, dark/golden thresholds, and game speed",
        governance.build_dedications_query(), "InGame"),
}


def available_reports() -> list[Report]:
    return list(_REPORTS.values())


def run_report(connection: FireTunerConnection, name: str, filter_text: str | None = None) -> list[str]:
    report = _REPORTS.get(name)
    if report is None:
        choices = ", ".join(sorted(_REPORTS))
        raise ValueError(f"unknown report {name!r}; choose one of: {choices}")
    if filter_text is not None and name != "resources":
        raise ValueError(f"report {name} 不支持筛选参数")
    lines = connection.execute_read_lines(report.lua, context=report.context, timeout=10.0)
    if name != "resources" or filter_text is None:
        return lines
    needle = filter_text.strip().casefold()
    if not needle:
        raise ValueError("资源筛选词不能为空")
    matched = []
    for line in lines:
        if not line.startswith("RESOURCE|"):
            if not line.startswith("RESOURCE_COUNT|"):
                matched.append(line)
            continue
        resource_name = line.split("|", 2)[1]
        if needle in resource_name.casefold():
            matched.append(line)
    matched.append(f"RESOURCE_COUNT|{sum(line.startswith('RESOURCE|') for line in matched)}")
    return matched


def unit_detail_lua(unit_id: int) -> str:
    return _COMMON + f"""
local me = Game.GetLocalPlayer()
local routedTraders = {{}}
for _, city in Players[me]:GetCities():Members() do
  local routes = safe(function() return city:GetTrade():GetOutgoingRoutes() end, {{}})
  for _, route in ipairs(routes or {{}}) do
    if route.TraderUnitID then routedTraders[route.TraderUnitID] = true end
  end
end
local function order_state(unit, unit_type)
  local ready = safe(function() return unit:IsReadyToMove() end, nil)
  local needs = ready == nil and "unknown" or ready and "yes" or "no"
  local activity = safe(function() return UnitManager.GetActivityType(unit) end, nil)
  local key = "unknown"
  if activity ~= nil then
    key = "activity_" .. tostring(activity)
    for name, value in pairs(ActivityTypes or {{}}) do
      if value == activity then
        key = name == "NO_ACTIVITY" and "none" or string.lower(string.gsub(name, "^ACTIVITY_", ""))
        break
      end
    end
  end
  if safe(function() return unit:IsAutomated() end, false) then key = "auto_explore" end
  if routedTraders[unit:GetID()] then
    key = "trade_route"
  elseif unit_type == "UNIT_SPY" and safe(function() return unit:GetSpyOperation() end, -1) >= 0 then
    key = "spy_mission"
  end
  local fortify_turns = safe(function() return unit:GetFortifyTurns() end, 0)
  if key == "sentry" and fortify_turns > 0 then
    key = "fortify_or_alert"
  elseif fortify_turns > 0 and needs == "no" and key ~= "heal" and key ~= "sleep" and key ~= "hold" then
    key = "fortify"
  end
  if needs == "yes" then
    key = "ready"
  elseif needs == "no" and (key == "awake" or key == "none") then
    key = unit:GetMovesRemaining() <= 0 and "exhausted" or "busy"
  end
  return key, needs
end
for _, unit in Players[me]:GetUnits():Members() do
  if unit:GetID() == {unit_id} then
    local info = safe(function() return GameInfo.Units[unit:GetType()] end, nil)
    local max_damage = safe(function() return unit:GetMaxDamage() end, 100)
    local activity, needs_orders = order_state(unit, info and info.UnitType or "UNKNOWN")
    print("UNIT_DETAIL|id={unit_id}|name=" .. clean(safe(function() return Locale.Lookup(unit:GetName()) end, "Unknown")) .. "|type=" .. clean(info and info.UnitType or "UNKNOWN") .. "|position=" .. safe(function() return unit:GetX() end, -1) .. "," .. safe(function() return unit:GetY() end, -1) .. "|moves=" .. safe(function() return unit:GetMovesRemaining() end, 0) .. "/" .. safe(function() return unit:GetMaxMoves() end, 0) .. "|activity=" .. activity .. "|needs_orders=" .. needs_orders .. "|hp=" .. (max_damage - safe(function() return unit:GetDamage() end, 0)) .. "/" .. max_damage .. "|charges=" .. safe(function() return unit:GetBuildCharges() end, 0) .. "|combat=" .. clean(info and info.Combat or 0) .. "|ranged=" .. clean(info and info.RangedCombat or 0))
  end
end
"""


def city_detail_lua(city_id: int) -> str:
    return _COMMON + f"""
local me = Game.GetLocalPlayer()
local city = CityManager.GetCity(me, {city_id} % 65536)
if city then
  local growth = city:GetGrowth()
  local amenities = safe(function() return growth:GetAmenities() end, nil)
  local amenities_needed = safe(function() return growth:GetAmenitiesNeeded() end, nil)
  local amenities_surplus = amenities and amenities_needed and amenities-amenities_needed or "?"
  local buildings = city:GetBuildings()
  local power = safe(function() return city:GetPower() end, nil)
  local power_current, power_required, fully_powered = 'unavailable', 'unavailable', 'unavailable'
  if power then
    power_current = safe(function() return power:GetFreePower() + power:GetTemporaryPower() end, '?')
    power_required = safe(function() return power:GetRequiredPower() end, '?')
    fully_powered = safe(function() return power:IsFullyPowered() end, false) and 'yes' or 'no'
  end
  print("CITY_DETAIL|id={city_id}|name=" .. clean(safe(function() return Locale.Lookup(city:GetName()) end, "Unknown")) .. "|position=" .. city:GetX() .. "," .. city:GetY() .. "|population=" .. city:GetPopulation() .. "|food=" .. safe(function() return string.format("%.1f", city:GetYield(0)) end, "?") .. "|production=" .. safe(function() return string.format("%.1f", city:GetYield(1)) end, "?") .. "|gold=" .. safe(function() return string.format("%.1f", city:GetYield(2)) end, "?") .. "|science=" .. safe(function() return string.format("%.1f", city:GetYield(3)) end, "?") .. "|culture=" .. safe(function() return string.format("%.1f", city:GetYield(4)) end, "?") .. "|faith=" .. safe(function() return string.format("%.1f", city:GetYield(5)) end, "?") .. "|housing=" .. safe(function() return string.format("%.1f", growth:GetHousing()) end, "?") .. "|amenities=" .. (amenities or "?") .. "|amenities_needed=" .. (amenities_needed or "?") .. "|amenities_surplus=" .. amenities_surplus .. "|growth_turns=" .. safe(function() return growth:GetTurnsUntilGrowth() end, "?") .. "|power_current=" .. power_current .. "|power_required=" .. power_required .. "|fully_powered=" .. fully_powered)
  for _, district in city:GetDistricts():Members() do
    local row = safe(function() return GameInfo.Districts[district:GetType()] end, nil)
    local dx, dy = safe(function() return district:GetX() end, -1), safe(function() return district:GetY() end, -1)
    local plot = Map.GetPlot(dx, dy)
    local children = {{}}
    local at_location = plot and safe(function() return buildings:GetBuildingsAtLocation(plot:GetIndex()) end, {{}}) or {{}}
    for _, building_type in pairs(at_location) do
      local building = safe(function() return GameInfo.Buildings[building_type] end, nil)
      if building then
        local suffix = safe(function() return buildings:IsPillaged(building.Index) end, false) and "（遭劫掠）" or ""
        if building.IsWonder then
          print("WONDER|name=" .. local_name(building) .. "|position=" .. dx .. "," .. dy .. "|complete=" .. (safe(function() return plot:IsWonderComplete() end, false) and "yes" or "no") .. "|pillaged=" .. (safe(function() return buildings:IsPillaged(building.Index) end, false) and "yes" or "no"))
        else
          table.insert(children, local_name(building) .. suffix)
        end
      end
    end
    table.sort(children)
    print("DISTRICT|" .. local_name(row) .. "|position=" .. dx .. "," .. dy .. "|buildings=" .. (#children > 0 and table.concat(children, "、") or "none") .. "|pillaged=" .. (safe(function() return district:IsPillaged() end, false) and "yes" or "no"))
  end
else
  print("NOT_FOUND|CITY|{city_id}")
end
"""


def tile_lua(x: int, y: int, radius: int) -> str:
    return _COMMON + f"""
local me = Game.GetLocalPlayer()
local visibility = PlayersVisibility[me]
for ty = {y - radius}, {y + radius} do
  for tx = {x - radius}, {x + radius} do
    local plot = Map.GetPlot(tx, ty)
    if plot and Map.GetPlotDistance({x}, {y}, tx, ty) <= {radius} and visibility:IsRevealed(tx, ty) then
      local terrain = safe(function() return GameInfo.Terrains[plot:GetTerrainType()] end, nil)
      local feature = safe(function() return GameInfo.Features[plot:GetFeatureType()] end, nil)
      local resource = safe(function() return GameInfo.Resources[plot:GetResourceType()] end, nil)
      local owner = safe(function() return plot:GetOwner() end, -1)
      local owner_name = "unowned"
      if owner >= 0 and PlayerConfigurations[owner] then owner_name = clean(Locale.Lookup(PlayerConfigurations[owner]:GetCivilizationShortDescription())) end
      print("TILE|position=" .. tx .. "," .. ty .. "|terrain=" .. clean(terrain and terrain.TerrainType or "UNKNOWN") .. "|feature=" .. clean(feature and feature.FeatureType or "none") .. "|resource=" .. clean(resource and resource.ResourceType or "none") .. "|owner=" .. owner_name .. "|hills=" .. (plot:IsHills() and "yes" or "no") .. "|water=" .. (plot:IsWater() and "yes" or "no") .. "|appeal=" .. safe(function() return plot:GetAppeal() end, "?") .. "|yields=" .. safe(function() return plot:GetYield(0) end, 0) .. "," .. safe(function() return plot:GetYield(1) end, 0) .. "," .. safe(function() return plot:GetYield(2) end, 0) .. "," .. safe(function() return plot:GetYield(3) end, 0) .. "," .. safe(function() return plot:GetYield(4) end, 0) .. "," .. safe(function() return plot:GetYield(5) end, 0))
    end
  end
end
"""


def bounded_int(value: str, *, name: str, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= number <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return number


def city_production_lua(city_id: int) -> str:
    return _COMMON + _PRODUCTION_COMMON + f"""
local me = Game.GetLocalPlayer()
local city = CityManager.GetCity(me, {city_id} % 65536)
if not city then print("NOT_FOUND|CITY|{city_id}"); return end
local queue = city:GetBuildQueue()
local function add(parts, text)
  text = clean(text or '')
  if text ~= '' and text ~= '0' then table.insert(parts, text) end
end
local function row_description(row)
  if not row or not row.Description then return 'none' end
  local text = clean(safe(function() return Locale.Lookup(row.Description) end, ''))
  return text ~= '' and text or 'none'
end
local function requirement_text(row, include_buildings)
  local parts = {{}}
  if row.PrereqTech then add(parts, '科技：' .. local_name(GameInfo.Technologies[row.PrereqTech])) end
  if row.PrereqCivic then add(parts, '市政：' .. local_name(GameInfo.Civics[row.PrereqCivic])) end
  if row.PrereqDistrict then add(parts, '区域：' .. local_name(GameInfo.Districts[row.PrereqDistrict])) end
  if row.AdjacentDistrict then add(parts, '邻接区域：' .. local_name(GameInfo.Districts[row.AdjacentDistrict])) end
  if row.StrategicResource then add(parts, '战略资源：' .. local_name(GameInfo.Resources[row.StrategicResource])) end
  if row.PrereqPopulation and row.PrereqPopulation > 0 then add(parts, '人口至少 ' .. row.PrereqPopulation) end
  if row.RequiresPopulation then add(parts, '占用人口区域容量') end
  if row.RequiresAdjacentRiver then add(parts, '必须邻接河流') end
  if row.MustBeAdjacentLand then add(parts, '必须邻接陆地') end
  if row.Coast then add(parts, '必须位于海岸') end
  if row.Aqueduct then add(parts, '必须满足水渠选址') end
  if row.NoAdjacentCity then add(parts, '不能邻接市中心') end
  if include_buildings then
    local prereq_buildings = {{}}
    for prereq in GameInfo.BuildingPrereqs() do
      if prereq.Building == row.BuildingType then add(prereq_buildings, local_name(GameInfo.Buildings[prereq.PrereqBuilding])) end
    end
    if #prereq_buildings > 0 then add(parts, '前置建筑：' .. table.concat(prereq_buildings, ' 或 ')) end
  end
  return #parts > 0 and table.concat(parts, '；') or '无额外条件'
end
local function building_effect(row)
  local parts = {{}}
  local description = row_description(row)
  if description ~= 'none' then add(parts, description) end
  local yields = {{}}
  for change in GameInfo.Building_YieldChanges() do
    if change.BuildingType == row.BuildingType then
      add(yields, local_name(GameInfo.Yields[change.YieldType]) .. ' ' .. (change.YieldChange >= 0 and '+' or '') .. change.YieldChange)
    end
  end
  if #yields > 0 then add(parts, '产出：' .. table.concat(yields, '、')) end
  if row.Housing and row.Housing ~= 0 then add(parts, '住房 ' .. (row.Housing > 0 and '+' or '') .. row.Housing) end
  if row.Entertainment and row.Entertainment ~= 0 then add(parts, '宜居度 ' .. (row.Entertainment > 0 and '+' or '') .. row.Entertainment) end
  if row.CitizenSlots and row.CitizenSlots > 0 then add(parts, '专家槽位 +' .. row.CitizenSlots) end
  if row.OuterDefenseHitPoints and row.OuterDefenseHitPoints > 0 then add(parts, '外部防御生命值 +' .. row.OuterDefenseHitPoints) end
  if row.OuterDefenseStrength and row.OuterDefenseStrength > 0 then add(parts, '外部防御强度 +' .. row.OuterDefenseStrength) end
  if row.Maintenance and row.Maintenance > 0 then add(parts, '维护费 ' .. row.Maintenance .. ' 金币/回合') end
  return #parts > 0 and table.concat(parts, '；') or '无说明'
end
local function district_effect(row)
  local parts = {{}}
  local description = row_description(row)
  if description ~= 'none' then add(parts, description) end
  if row.Housing and row.Housing ~= 0 then add(parts, '住房 ' .. (row.Housing > 0 and '+' or '') .. row.Housing) end
  if row.Entertainment and row.Entertainment ~= 0 then add(parts, '宜居度 ' .. (row.Entertainment > 0 and '+' or '') .. row.Entertainment) end
  if row.AirSlots and row.AirSlots > 0 then add(parts, '空军槽位 +' .. row.AirSlots) end
  if row.Maintenance and row.Maintenance > 0 then add(parts, '维护费 ' .. row.Maintenance .. ' 金币/回合') end
  return #parts > 0 and table.concat(parts, '；') or '无说明'
end
local function unit_effect(row)
  local parts = {{}}
  local description = row_description(row)
  if description ~= 'none' then add(parts, description) end
  if row.ReligiousStrength and row.ReligiousStrength > 0 then add(parts, '宗教战斗力 ' .. row.ReligiousStrength) end
  if row.SpreadCharges and row.SpreadCharges > 0 then add(parts, '传播次数 ' .. row.SpreadCharges) end
  if row.FoundCity then add(parts, '可建立城市') end
  if row.MakeTradeRoute then add(parts, '可建立贸易路线') end
  return #parts > 0 and table.concat(parts, '；') or '无说明'
end
local current = safe(function() return queue:GetCurrentProductionTypeHash() end, 0)
local turns = safe(function() return queue:GetTurnsLeft() end, -1)
local item = production_rows[current]
print("CURRENT|city={city_id}|name=" .. (current == 0 and 'none' or item and local_name(item.row) or 'Unknown') .. "|type=" .. production_type(item and item.row or nil) .. "|progress=" .. production_value(queue, item, 'Progress') .. "|cost=" .. production_value(queue, item, 'Cost') .. "|turns=" .. turns)
for row in GameInfo.Units() do
  local ok = safe(function() return queue:CanProduce(row.Hash, true) end, false)
  if ok and not row.MustPurchase then
    print("PRODUCTION_UNIT|name=" .. local_name(row) .. "|type=" .. row.UnitType .. "|cost=" .. production_value(queue, production_rows[row.Hash], 'Cost') .. "|turns=" .. safe(function() return queue:GetTurnsLeft(row.Hash) end, -1) .. "|requirements=" .. requirement_text(row, false) .. "|combat=" .. clean(row.Combat or 0) .. "|ranged=" .. clean(row.RangedCombat or 0) .. "|bombard=" .. clean(row.Bombard or 0) .. "|range=" .. clean(row.Range or 0) .. "|moves=" .. clean(row.BaseMoves or 0) .. "|charges=" .. clean(row.BuildCharges or row.ParkCharges or 0) .. "|maintenance=" .. clean(row.Maintenance or 0) .. "|effect=" .. unit_effect(row))
  end
end
for row in GameInfo.Buildings() do
  local ok = safe(function() return queue:CanProduce(row.Hash, true) end, false)
  if ok then print("PRODUCTION_BUILDING|name=" .. local_name(row) .. "|type=" .. row.BuildingType .. "|is_wonder=" .. (row.IsWonder and "yes" or "no") .. "|cost=" .. production_value(queue, production_rows[row.Hash], 'Cost') .. "|turns=" .. safe(function() return queue:GetTurnsLeft(row.Hash) end, -1) .. "|requirements=" .. requirement_text(row, true) .. "|effect=" .. building_effect(row)) end
end
for row in GameInfo.Districts() do
  local ok = safe(function() return queue:CanProduce(row.Hash, true) end, false)
  if ok then print("PRODUCTION_DISTRICT|name=" .. local_name(row) .. "|type=" .. row.DistrictType .. "|cost=" .. production_value(queue, production_rows[row.Hash], 'Cost') .. "|turns=" .. safe(function() return queue:GetTurnsLeft(row.Hash) end, -1) .. "|requirements=" .. requirement_text(row, false) .. "|effect=" .. district_effect(row)) end
end
for row in GameInfo.Projects() do
  if safe(function() return queue:CanProduce(row.Hash, true) end, false) then print('PRODUCTION_PROJECT|name=' .. local_name(row) .. '|type=' .. row.ProjectType .. '|cost=' .. production_value(queue, production_rows[row.Hash], 'Cost') .. '|turns=' .. safe(function() return queue:GetTurnsLeft(row.Hash) end, -1) .. '|requirements=' .. requirement_text(row, false) .. '|effect=' .. row_description(row)) end
end
local function purchase_unit(row, yield_type, record_kind)
  local yield = GameInfo.Yields[yield_type]
  if not yield then return end
  local params = {{}}
  params[CityCommandTypes.PARAM_UNIT_TYPE] = row.Hash
  params[CityCommandTypes.PARAM_YIELD_TYPE] = yield.Index
  if safe(function() return CityManager.CanStartCommand(city, CityCommandTypes.PURCHASE, true, params, false) end, false) then
    local affordable = safe(function() return CityManager.CanStartCommand(city, CityCommandTypes.PURCHASE, false, params, true) end, false)
    local cost = safe(function() return city:GetGold():GetPurchaseCost(yield.Index, row.Hash, MilitaryFormationTypes.STANDARD_MILITARY_FORMATION) end, '?')
    print(record_kind .. '|UNIT|name=' .. local_name(row) .. '|cost=' .. cost .. '|affordable=' .. (affordable and 'yes' or 'no') .. '|details=' .. unit_effect(row))
  end
end
local function purchase_building(row, yield_type, record_kind)
  local yield = GameInfo.Yields[yield_type]
  if not yield then return end
  local params = {{}}
  params[CityCommandTypes.PARAM_BUILDING_TYPE] = row.Hash
  params[CityCommandTypes.PARAM_YIELD_TYPE] = yield.Index
  if safe(function() return CityManager.CanStartCommand(city, CityCommandTypes.PURCHASE, true, params, false) end, false) then
    local affordable = safe(function() return CityManager.CanStartCommand(city, CityCommandTypes.PURCHASE, false, params, true) end, false)
    local cost = safe(function() return city:GetGold():GetPurchaseCost(yield.Index, row.Hash) end, '?')
    print(record_kind .. '|BUILDING|name=' .. local_name(row) .. '|cost=' .. cost .. '|affordable=' .. (affordable and 'yes' or 'no') .. '|details=' .. building_effect(row))
  end
end
local function purchase_district(row, yield_type, record_kind)
  local yield = GameInfo.Yields[yield_type]
  if not yield then return end
  local params = {{}}
  params[CityCommandTypes.PARAM_DISTRICT_TYPE] = row.Hash
  params[CityCommandTypes.PARAM_YIELD_TYPE] = yield.Index
  if safe(function() return CityManager.CanStartCommand(city, CityCommandTypes.PURCHASE, true, params, false) end, false) then
    local affordable = safe(function() return CityManager.CanStartCommand(city, CityCommandTypes.PURCHASE, false, params, true) end, false)
    local cost = safe(function() return city:GetGold():GetPurchaseCost(yield.Index, row.Hash) end, '?')
    print(record_kind .. '|DISTRICT|name=' .. local_name(row) .. '|cost=' .. cost .. '|affordable=' .. (affordable and 'yes' or 'no') .. '|details=' .. district_effect(row))
  end
end
for _, purchase in ipairs({{{{'YIELD_GOLD', 'PURCHASE_GOLD'}}, {{'YIELD_FAITH', 'PURCHASE_FAITH'}}}}) do
  for row in GameInfo.Units() do
    local listed = row.PurchaseYield == purchase[1]
    if purchase[1] == 'YIELD_FAITH' and safe(function() return city:GetGold():IsUnitFaithPurchaseEnabled(row.Hash) end, false) then listed = true end
    if listed then purchase_unit(row, purchase[1], purchase[2]) end
  end
  for row in GameInfo.Buildings() do
    local listed = row.PurchaseYield == purchase[1]
    if purchase[1] == 'YIELD_FAITH' and safe(function() return city:GetGold():IsBuildingFaithPurchaseEnabled(row.Hash) end, false) then listed = true end
    if listed then purchase_building(row, purchase[1], purchase[2]) end
  end
  for row in GameInfo.Districts() do purchase_district(row, purchase[1], purchase[2]) end
end
"""


def unit_promotions_lua(unit_id: int) -> str:
    return _COMMON + f"""
local me = Game.GetLocalPlayer()
local unit = Players[me]:GetUnits():FindID({unit_id})
if not unit then print("NOT_FOUND|UNIT|{unit_id}"); return end
local info = safe(function() return GameInfo.Units[unit:GetType()] end, nil)
local exp = safe(function() return unit:GetExperience() end, nil)
print("UNIT_XP|id={unit_id}|type=" .. clean(info and info.UnitType or "UNKNOWN") .. "|class=" .. clean(info and info.PromotionClass or "") .. "|xp=" .. safe(function() return exp:GetExperiencePoints() end, 0) .. "|next=" .. safe(function() return exp:GetExperienceForNextLevel() end, 0) .. "|stored=" .. safe(function() return exp:GetStoredPromotions() end, 0))
if exp and info then
  for row in GameInfo.UnitPromotions() do
    if row.PromotionClass == info.PromotionClass and not safe(function() return exp:HasPromotion(row.Index) end, true) then
      local can = safe(function() return exp:CanPromote(row.Index) end, false)
      if can then print("PROMOTION|" .. clean(row.UnitPromotionType) .. "|name=" .. local_name(row) .. "|description=" .. clean(safe(function() return Locale.Lookup(row.Description) end, ""))) end
    end
  end
end
"""


def path_estimate_lua(unit_id: int, x: int, y: int) -> str:
    return _COMMON + f"""
local me = Game.GetLocalPlayer()
local unit = Players[me]:GetUnits():FindID({unit_id})
if not unit then print("NOT_FOUND|UNIT|{unit_id}"); return end
local ux, uy = unit:GetX(), unit:GetY()
local distance = Map.GetPlotDistance(ux, uy, {x}, {y})
local terrain = Map.GetPlot({x}, {y})
local revealed = terrain and PlayersVisibility[me]:IsRevealed(terrain:GetIndex())
print("PATH|unit={unit_id}|from=" .. ux .. "," .. uy .. "|to={x},{y}|hex_distance=" .. distance .. "|target_exists=" .. (terrain and "yes" or "no") .. "|target_water=" .. (not revealed and '?' or terrain:IsWater() and 'yes' or 'no'))
"""
