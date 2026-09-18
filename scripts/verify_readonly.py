"""Read-only live audit. Never submits an action or advances the current turn.

Run from the project root: python scripts/verify_readonly.py
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from civ6_cli.actions import ActionService, Query, option_plan
from civ6_cli.game import read_units
from civ6_cli.lua import cities, diplomacy, espionage, governance, great_works, religion, tech, units
from civ6_cli.map_view import map_lua
from civ6_cli.overview import read_overview, render_overview
from civ6_cli.reports import available_reports, city_production_lua, unit_detail_lua
from civ6_cli.transport import FireTunerConnection
from great_work_contracts import contract_query
from query_trade_contracts import contract_query as query_trade_contract_query


def lua_string(value: str) -> str:
    # Byte escapes preserve all quotes/newlines without accepting Lua input.
    return '"' + "".join("\\%03d" % byte for byte in value.encode("utf-8")) + '"'


_CAPTURE_SANDBOX = """
local requested = nil
local records = {}
local function city(id)
    return {GetID=function() return id end, GetName=function() return "TestCity" .. id end,
        GetPopulation=function() return 2 end, GetOwner=function() return 0 end,
        GetBuildQueue=function() return {CurrentlyBuilding=function() return "UNIT_BUILDER" end,
            GetTurnsLeft=function() error("Not Implemented") end} end}
end
local city1, city2, ordinary = city(1), city(2), city(3)
local collection = {GetNextRebelledCity=function() return nil end,
    GetNextCapturedCity=function() return city1 end,
    FindID=function(_, id) return id == 1 and city1 or id == 2 and city2 or ordinary end}
local environment = {
    Game={GetLocalPlayer=function() return 0 end},
    Players={[0]={GetCities=function() return collection end}},
    GameInfo={Units={UNIT_BUILDER={Hash=1}}, Buildings={}, Districts={}, Projects={}},
    UI={}, UnitManager={},
    Locale={Lookup=function(value) return value end},
    CityManager={GetCityAt=function(x,y) return x == 20 and y == 20 and city2 or nil end,
        CanStartCommand=function() return true end,
        RequestCommand=function(target) requested=target:GetID() end},
    CityDestroyDirectives={KEEP=1, REJECT=2, RAZE=3, LIBERATE_FOUNDER=4, LIBERATE_PREVIOUS_OWNER=5},
    CityCommandTypes={DESTROY=1}, UnitOperationTypes={PARAM_FLAGS=1},
    EndTurnBlockingTypes={ENDTURN_BLOCKING_CONSIDER_RAZE_CITY=1},
    NotificationManager={GetList=function() return {1} end, Find=function() return {
        IsDismissed=function() return false end, GetEndTurnBlocking=function() return 1 end,
        GetTypeName=function() return "NOTIFICATION_CONSIDER_RAZE_CITY" end,
        GetLocation=function() return 20,20 end} end},
    print=function(value) table.insert(records,tostring(value)) end,
}
local function run(source)
    requested, records = nil, {}
    -- Lexical shadows work in Civ VI builds without setfenv. Native game
    -- namespaces are never looked up while the fixed contract template runs.
    local prefix = [[return function(env)
local Game, Players, GameInfo, UI, UnitManager, Locale, CityManager =
    env.Game, env.Players, env.GameInfo, env.UI, env.UnitManager, env.Locale, env.CityManager
local CityDestroyDirectives, CityCommandTypes, UnitOperationTypes, EndTurnBlockingTypes, NotificationManager, print =
    env.CityDestroyDirectives, env.CityCommandTypes, env.UnitOperationTypes, env.EndTurnBlockingTypes, env.NotificationManager, env.print
]]
    local compiled, err = loadstring(prefix .. source .. "\\nend")
    if not compiled then error(err) end
    compiled()(environment)
end
"""


def main() -> int:
    failures = []
    with FireTunerConnection() as connection:
        service = ActionService(connection)

        def check(name, query):
            lines = service.query(query)
            errors = [line for line in lines if line.startswith(("ERROR|", "ERR:"))]
            print(f"{name}: {len(lines)} records" + (" FAILED: " + " / ".join(errors) if errors else " OK"))
            failures.extend(errors)
            return lines

        snapshot = read_overview(connection)
        output = render_overview(snapshot)
        assert "单位概览" not in output and "通知" in output
        print(f"status: turn={snapshot.status.turn}, notifications={len(snapshot.notifications)} OK")
        for report in available_reports():
            records = check("domain query " + report.name, Query(report.lua, report.context))
            if report.name == 'great-works':
                works = [int(row.split('|id=')[1].split('|')[0]) for row in records if row.startswith('GREAT_WORK|')]
                if works:
                    check('great-work options', Query(great_works.build_destinations_query(works[0])))
        check('policy options live state', Query(governance.build_policies_query()))
        check('government options live state', Query(governance.build_available_governments_query()))
        # Audit the public option queries as well as legacy internal data sources.
        # The old audit omitted research options and missed its nil civic API.
        for topic in ('research', 'policies', 'governors', 'envoys', 'pantheon',
                      'religion', 'dedications', 'governments', 'great-people', 'congress'):
            plan = option_plan(topic, [], unit_id=int, city_id=int)
            for query in plan.queries:
                check(plan.title, query)
        players = check('met players for options', Query(
            "local me=Game.GetLocalPlayer(); local diplo=Players[me]:GetDiplomacy(); "
            "for id=0,62 do if id~=me and Players[id] and Players[id]:IsAlive() and "
            "Players[id]:IsMajor() and diplo:HasMet(id) then print('PLAYER|' .. id) end end"))
        for row in players:
            if row.startswith('PLAYER|'):
                player = row.split('|')[1]
                for topic in ('trades', 'diplomacy'):
                    plan = option_plan(topic, [player], unit_id=int, city_id=int)
                    for query in plan.queries:
                        check(plan.title + ' ' + player, query)
        roster = read_units(connection)
        check("unit list", Query(units.build_units_query()))
        if roster:
            detail = check(f"unit show {roster[0].id}", Query(unit_detail_lua(roster[0].id), "InGame"))
            if not any("|activity=" in row and "|needs_orders=" in row for row in detail):
                failures.append("unit detail omitted activity/needs_orders")
            tile = check(f"map tile {roster[0].x} {roster[0].y}", Query(map_lua(roster[0].x, roster[0].y, 0), "InGame"))
            if not any("|appeal=" in row for row in tile):
                failures.append("visible map tile omitted appeal")
        for unit in roster:
            if unit.unit_type in {"UNIT_TRADER", "UNIT_SPY", "UNIT_BUILDER", "UNIT_MILITARY_ENGINEER",
                                  "UNIT_ARCHAEOLOGIST", "UNIT_NATURALIST", "UNIT_ROCK_BAND", "UNIT_JET_FIGHTER", "UNIT_JET_BOMBER"}:
                rows = check(f"unit options {unit.id} ({unit.unit_type})", Query(units.build_unit_operations_query(unit.id)))
                for row in rows[:2]:
                    print("  " + row)
                if unit.unit_type == "UNIT_TRADER":
                    plan = option_plan("trade-routes", [str(unit.id)], unit_id=int, city_id=int)
                    routes = check(f"unit options {unit.id}", plan.queries[0])
                    for row in routes[:2]:
                        print("  " + row)
                if unit.unit_type == "UNIT_SPY":
                    rows = check(f"unit options {unit.id}", Query(espionage.build_spy_options_query(unit.id)))
                    for row in rows[:4]:
                        print("  " + row)
        captures = check("city captures", Query(cities.build_pending_captures_query()))
        for row in captures:
            if row.startswith("CAPTURE|") and not all(field in row for field in ("|name=", "|population=", "|source=", "|choices=")):
                failures.append("capture row omitted identifying fields: " + row)
        if snapshot.cities:
            production = check(f"city production {snapshot.cities[0].id}", Query(city_production_lua(snapshot.cities[0].id), "InGame"))
            option_rows = [row for row in production if row.startswith(("PRODUCTION_UNIT|", "PRODUCTION_BUILDING|", "PRODUCTION_DISTRICT|", "PRODUCTION_PROJECT|"))]
            if option_rows and not all("|type=" in row for row in option_rows):
                failures.append("production option omitted internal type")
        # Compilation only: validate write template syntax without invoking it.
        templates = [("government keep", governance.build_keep_government()),
                     ("great-work move", great_works.build_move(36, 131073, 'BUILDING_PALACE', 0)),
                     ("policy keep", governance.build_keep_policies()),
                     ("city produce", cities.build_produce_item(1, "UNIT", "UNIT_BUILDER")),
                     ("set civic", tech.build_set_civic("CIVIC_CODE_OF_LAWS")),
                     ("apostle evangelize", religion.build_evangelize_belief(1)),
                     ("religion add belief", religion.build_add_belief("BELIEF_WAT")),
                     ("trade test", diplomacy.build_test_trade(1, [{"type": "GOLD", "amount": 1}], [])),
                     ("conditional peace", diplomacy.build_propose_peace(1, [], [{"type": "GOLD", "amount": 1}])),
                     ("capture city", cities.build_resolve_city_capture("keep", 1)),
                     ("spy travel", espionage.build_spy_travel(1, 2, 3)),
                     ("spy DLC mission", espionage.build_spy_mission(1, "BREACH_DAM", 2, 3))]
        templates += [(name, units.build_plot_task(1, "UNITOPERATION_" + name, 2, 3)) for name in units.PLOT_TASKS]
        templates += [(name, units.build_unit_control(1, name)) for name in ("WAKE", "CANCEL")]
        for name, source in templates:
            compiled = service.query(Query("local compiled, err = loadstring(" + lua_string(source) + ")\n"
                                           "if compiled then print('COMPILED') else print('ERROR|' .. tostring(err)) end"))
            if compiled != ["COMPILED"]:
                failures.append(name + ": " + " / ".join(compiled))
        print(f"write templates: {len(templates)} compiled (not executed)")
        # Runtime contract checks use isolated fake objects, never real game objects.
        simulation = _CAPTURE_SANDBOX + "\nrun(" + lua_string(cities.build_resolve_city_capture("keep", 2)) + ")\n"
        simulation += "if requested ~= 2 then error('second pending city not selected') end\n"
        simulation += "run(" + lua_string(cities.build_resolve_city_capture("keep", 3)) + ")\n"
        simulation += "if requested ~= nil then error('ordinary city incorrectly accepted') end\n"
        simulation += "print('CONTRACT_CHECK|second city selected; ordinary city refused')"
        check("isolated Lua contracts", Query(simulation))
        check("isolated Great Work contracts", Query(contract_query(lua_string)))
        check("isolated research / trade contracts", Query(query_trade_contract_query(lua_string)))
        finish = read_overview(connection)
        if finish.status.turn != snapshot.status.turn:
            failures.append("turn changed during audit (possibly player activity)")
        print(f"Finished at turn {finish.status.turn}; no action requests were sent.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
