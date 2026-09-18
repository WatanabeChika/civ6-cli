"""Fixed, read-only Civ VI state queries and their parsers."""

from __future__ import annotations

from dataclasses import dataclass

from .transport import FireTunerConnection


@dataclass(frozen=True)
class PlayerStatus:
    turn: int
    player_id: int
    civilization: str
    leader: str
    gold: float
    science: float
    culture: float
    faith: float
    cities: int
    units: int
    is_turn_active: bool = True


@dataclass(frozen=True)
class Unit:
    id: int
    name: str
    unit_type: str
    x: int
    y: int
    moves: int
    max_moves: int
    hp: int
    max_hp: int


@dataclass(frozen=True)
class City:
    id: int
    name: str
    x: int
    y: int
    population: int


@dataclass(frozen=True)
class KnownPlayer:
    id: int
    civilization: str
    leader: str
    is_local: bool


@dataclass(frozen=True)
class VisibleUnit:
    owner_id: int
    owner: str
    id: int
    name: str
    unit_type: str
    x: int
    y: int
    hp: int
    max_hp: int


@dataclass(frozen=True)
class KnownCity:
    owner_id: int
    owner: str
    id: int
    name: str
    x: int
    y: int
    visible: bool


_STATUS_QUERY = """
local id = Game.GetLocalPlayer()
local p = Players[id]
local cfg = PlayerConfigurations[id]
local treasury = p:GetTreasury()
local cities, units = 0, 0
for _, _ in p:GetCities():Members() do cities = cities + 1 end
for _, _ in p:GetUnits():Members() do units = units + 1 end
print(table.concat({
  'STATUS', Game.GetCurrentGameTurn(), id,
  Locale.Lookup(cfg:GetCivilizationShortDescription()):gsub('|', '/'),
  Locale.Lookup(cfg:GetLeaderName()):gsub('|', '/'),
  string.format('%.1f', treasury:GetGoldBalance()),
  string.format('%.1f', p:GetTechs():GetScienceYield()),
  string.format('%.1f', p:GetCulture():GetCultureYield()),
  string.format('%.1f', p:GetReligion():GetFaithBalance()),
  cities, units, p:IsTurnActive() and 'yes' or 'no'
}, '|'))
"""

_UNITS_QUERY = """
local id = Game.GetLocalPlayer()
local function safe(callback, fallback)
  local ok, value = pcall(callback)
  if ok and value ~= nil then return value end
  return fallback
end
for _, u in Players[id]:GetUnits():Members() do
  local x, y = safe(function() return u:GetX() end, -9999), safe(function() return u:GetY() end, -9999)
  do -- Include off-map travelling spies so they remain addressable by ID.
    local entry = safe(function() return GameInfo.Units[u:GetType()] end, nil)
    local typ = entry and entry.UnitType or 'UNKNOWN'
    local name = typ
    pcall(function() name = Locale.Lookup(u:GetName()):gsub('|', '/') end)
    local maxDamage = safe(function() return u:GetMaxDamage() end, 100)
    local damage = safe(function() return u:GetDamage() end, 0)
    print(table.concat({
      'UNIT', safe(function() return u:GetID() end, -1), name, typ, x, y,
      safe(function() return u:GetMovesRemaining() end, 0), safe(function() return u:GetMaxMoves() end, 0),
      maxDamage - damage, maxDamage
    }, '|'))
  end
end
"""

_CITIES_QUERY = """
local id = Game.GetLocalPlayer()
local function safe(callback, fallback)
  local ok, value = pcall(callback)
  if ok and value ~= nil then return value end
  return fallback
end
for _, c in Players[id]:GetCities():Members() do
  local name = 'UNKNOWN'
  pcall(function() name = Locale.Lookup(c:GetName()):gsub('|', '/') end)
  print(table.concat({
    'CITY', safe(function() return c:GetID() end, -1), name,
    safe(function() return c:GetX() end, -1), safe(function() return c:GetY() end, -1), safe(function() return c:GetPopulation() end, 0)
  }, '|'))
end
"""

_KNOWN_PLAYERS_QUERY = """
local me = Game.GetLocalPlayer()
local diplomacy = Players[me]:GetDiplomacy()
for id = 0, 62 do
  local p = Players[id]
  if p and p:IsAlive() and p:IsMajor() and (id == me or diplomacy:HasMet(id)) then
    local cfg = PlayerConfigurations[id]
    print(table.concat({
      'PLAYER', id,
      Locale.Lookup(cfg:GetCivilizationShortDescription()):gsub('|', '/'),
      Locale.Lookup(cfg:GetLeaderName()):gsub('|', '/'),
      id == me and 'local' or 'met'
    }, '|'))
  end
end
"""

_VISIBLE_ENTITIES_QUERY = """
local me = Game.GetLocalPlayer()
local visibility = PlayersVisibility[me]
local function safe(callback, fallback)
  local ok, value = pcall(callback)
  if ok and value ~= nil then return value end
  return fallback
end
local function clean(value)
  return tostring(value or ''):gsub('|', '/'):gsub('[\\r\\n]', ' ')
end
local function owner_name(id)
  if id == 63 then return clean(Locale.Lookup('LOC_CIVILIZATION_BARBARIAN_NAME')) end
  local cfg = PlayerConfigurations[id]
  return cfg and clean(Locale.Lookup(cfg:GetCivilizationShortDescription())) or ('P' .. id)
end
for id = 0, 63 do
  local player = Players[id]
  if player and player:IsAlive() then
    if id ~= me then
      local units = player:GetUnits()
      if units then for _, unit in units:Members() do
        local x, y = unit:GetX(), unit:GetY()
        if visibility:IsVisible(x, y) and safe(function() return visibility:IsUnitVisible(unit) end, false) then
          local row = safe(function() return GameInfo.Units[unit:GetType()] end, nil)
          local maximum = safe(function() return unit:GetMaxDamage() end, 100)
          print(table.concat({'VISIBLE_UNIT', id, owner_name(id), unit:GetID(), clean(Locale.Lookup(unit:GetName())), row and row.UnitType or 'UNKNOWN', x, y, maximum-unit:GetDamage(), maximum}, '|'))
        end
      end end
    end
    local cities = player:GetCities()
    if cities then for _, city in cities:Members() do
      local plot = Map.GetPlot(city:GetX(), city:GetY())
      if plot and (id == me or visibility:IsRevealed(plot:GetIndex())) then
        print(table.concat({'KNOWN_CITY', id, owner_name(id), city:GetID(), clean(Locale.Lookup(city:GetName())), city:GetX(), city:GetY(), visibility:IsVisible(plot:GetIndex()) and 'yes' or 'no'}, '|'))
      end
    end end
  end
end
"""


def read_status(connection: FireTunerConnection) -> PlayerStatus:
    lines = connection.execute_read_lines(_STATUS_QUERY)
    line = next((item for item in lines if item.startswith("STATUS|")), None)
    if line is None:
        raise ValueError(f"no STATUS line in response: {lines!r}")
    parts = line.split("|")
    if len(parts) not in {11, 12}:
        raise ValueError(f"malformed STATUS line: {line!r}")
    return PlayerStatus(
        turn=int(parts[1]), player_id=int(parts[2]), civilization=parts[3],
        leader=parts[4], gold=float(parts[5]), science=float(parts[6]),
        culture=float(parts[7]), faith=float(parts[8]), cities=int(parts[9]), units=int(parts[10]),
        is_turn_active=len(parts) == 11 or parts[11] == 'yes',
    )


def read_units(connection: FireTunerConnection) -> list[Unit]:
    units: list[Unit] = []
    # GameCore is available even when the InGame UI context is partially
    # suspended by an animation/modal. Optional fields are pcall-wrapped in
    # Lua, so one version-specific method cannot erase the full list.
    for line in connection.execute_read_lines(_UNITS_QUERY):
        parts = line.split("|")
        if parts[0] != "UNIT" or len(parts) != 10:
            continue
        units.append(Unit(int(parts[1]), parts[2], parts[3], int(parts[4]), int(parts[5]), int(parts[6]), int(parts[7]), int(parts[8]), int(parts[9])))
    return sorted(units, key=lambda unit: unit.id)


def read_cities(connection: FireTunerConnection) -> list[City]:
    cities: list[City] = []
    for line in connection.execute_read_lines(_CITIES_QUERY):
        parts = line.split("|")
        if parts[0] != "CITY" or len(parts) != 6:
            continue
        cities.append(City(int(parts[1]), parts[2], int(parts[3]), int(parts[4]), int(parts[5])))
    return sorted(cities, key=lambda city: city.id)


def read_known_players(connection: FireTunerConnection) -> list[KnownPlayer]:
    players: list[KnownPlayer] = []
    for line in connection.execute_read_lines(_KNOWN_PLAYERS_QUERY):
        parts = line.split("|")
        if parts[0] != "PLAYER" or len(parts) != 5:
            continue
        players.append(KnownPlayer(int(parts[1]), parts[2], parts[3], parts[4] == "local"))
    return sorted(players, key=lambda player: (not player.is_local, player.id))


def read_visible_entities(connection: FireTunerConnection) -> tuple[list[VisibleUnit], list[KnownCity]]:
    units, cities = [], []
    for line in connection.execute_read_lines(_VISIBLE_ENTITIES_QUERY, context="InGame", timeout=10.0):
        parts = line.split("|")
        if parts[0] == "VISIBLE_UNIT" and len(parts) == 10:
            units.append(VisibleUnit(int(parts[1]), parts[2], int(parts[3]), parts[4], parts[5], int(parts[6]), int(parts[7]), int(parts[8]), int(parts[9])))
        elif parts[0] == "KNOWN_CITY" and len(parts) == 8:
            cities.append(KnownCity(int(parts[1]), parts[2], int(parts[3]), parts[4], int(parts[5]), int(parts[6]), parts[7] == "yes"))
    return (sorted(units, key=lambda u: (u.owner_id, u.id)),
            sorted(cities, key=lambda c: (c.owner_id, c.id)))
