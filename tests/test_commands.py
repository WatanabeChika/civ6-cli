import io
from contextlib import redirect_stdout
from pathlib import Path
import unittest
from unittest.mock import patch

from civ6_cli.commands import COMMANDS, manual_command_tables, offline_command, route_command, show_help
from civ6_cli.game import City, Unit
from civ6_cli.lua import cities, diplomacy, economy, espionage, governance, notifications, religion, units
from civ6_cli.actions import city_plan, standalone_plan, spy_plan, unit_plan
from civ6_cli.repl import Terminal
from civ6_cli.rendering import Display
from test_overview import SnapshotConnection


class CommandTreeTests(unittest.TestCase):
    def test_paths_are_unique_and_not_ambiguous_prefixes(self):
        paths = [c.path for c in COMMANDS]
        self.assertEqual(len(paths), len(set(paths)))
        for path in paths:
            self.assertFalse(any(other.startswith(path + " ") for other in paths))

    def test_argument_order_is_consistent_and_old_entries_are_rejected(self):
        examples = {
            "unit move 7 4 5": ["unit", "7", "move", "4", "5"],
            "city produce 开罗 unit UNIT_BUILDER": ["city", "开罗", "produce", "unit", "UNIT_BUILDER"],
            "research set tech TECH_STEEL": ["research", "tech", "TECH_STEEL"],
            "policy set 0=POLICY_AGOGE": ["policies", "set", "0=POLICY_AGOGE"],
            "city capture 开罗 keep": ["capture", "开罗", "keep"],
            "map show 4 5 2": ["map", "4", "5", "2"],
            "turn end": ["endturn"],
            "great-work list": ["query", "great-works"],
            "era options": ["options", "dedications"],
        }
        for words, result in examples.items():
            self.assertEqual(route_command(words.split()), result)
        for words in ("unit 7 move 4 5", "options research", "reports", "endturn",
                      "actions", "capture 开罗 keep", "government skip", "policies skip",
                      "repl", "quit", "probe", "overview", "refresh", "report list",
                      "report show diplomacy", "dedication options", "dedication choose 0",
                      "research show", "government show", "envoy show", "era show",
                      "great-person show", "congress show", "unit routes 7", "spy options 8"):
            with self.assertRaisesRegex(ValueError, "未知命令"):
                route_command(words.split())

    def test_invalid_arity_is_rejected_before_connection(self):
        for words in ("unit move 7 4", "city capture keep", "unit task 7 UNITOPERATION_EXCAVATE 1",
                      "city produce 1 unit UNIT_BUILDER 4", "policy keep extra", "government keep extra"):
            with self.assertRaisesRegex(ValueError, "用法"):
                route_command(words.split())

    def test_help_uses_every_registered_leaf_without_connection(self):
        for command in COMMANDS:
            with redirect_stdout(io.StringIO()) as output:
                Terminal(None).execute(["help", *command.path.split()])
            self.assertIn(command.path, output.getvalue())
            self.assertTrue(offline_command(["help", *command.path.split()]))
        self.assertTrue(offline_command(["session", "quit"]))
        with self.assertRaises(ValueError):
            offline_command(["unit", "help"])
        self.assertFalse(offline_command(["unit", "list"]))

    def test_every_leaf_routes_to_a_valid_read_or_action(self):
        unit = Unit(7, "勇士", "UNIT_WARRIOR", 1, 2, 2, 2, 100, 100)
        spy = Unit(8, "间谍", "UNIT_SPY", 1, 2, 2, 2, 100, 100)
        city = City(65536, "开罗", 1, 2, 8)
        samples = {
            "unit task": ["7", "UNITOPERATION_EXCAVATE"],
            "unit improve": ["7", "IMPROVEMENT_FARM"], "unit promote": ["7", "PROMOTION_BATTLECRY"],
            "city district-sites": ["65536", "DISTRICT_CAMPUS"], "city wonder-sites": ["65536", "BUILDING_PYRAMIDS"],
            "city capture": ["65536", "keep"], "city produce": ["65536", "unit", "UNIT_BUILDER"],
            "city buy": ["65536", "gold", "unit", "UNIT_BUILDER"], "city focus": ["65536", "food"],
            "research set": ["tech", "TECH_STEEL"], "government change": ["GOVERNMENT_MONARCHY"],
            "policy set": ["0=POLICY_AGOGE"], "governor appoint": ["GOVERNOR_THE_EDUCATOR"],
            "governor assign": ["GOVERNOR_THE_EDUCATOR", "65536"],
            "governor promote": ["GOVERNOR_THE_EDUCATOR", "GOVERNOR_PROMOTION_LIBRARIAN"],
            "envoy send": ["2"], "era choose": ["0"], "religion pantheon": ["BELIEF_GOD_OF_WAR"],
            "religion found": ["RELIGION_ISLAM", "BELIEF_FEED_THE_WORLD", "BELIEF_TITHE"],
            "religion evangelize": ["7"], "religion add-belief": ["BELIEF_WAT"],
            "great-person recruit": ["1"], "great-person pass": ["1"], "great-person patronize": ["gold", "1"],
            "diplomacy options": ["2"], "diplomacy respond": ["2", "positive"],
            "diplomacy action": ["2", "DIPLOMATIC_DELEGATION"], "diplomacy alliance": ["2", "research"],
            "trade options": ["2"], "trade respond": ["2", "reject"],
            "trade propose": ["2", "test", "give-gold=10"], "spy options": ["8"], "spy destinations": ["8"],
            "trade peace": ["2", "test"],
            "spy travel": ["8", "4", "5"], "spy mission": ["8", "GAIN_SOURCES", "4", "5"],
            "congress queue": ["-123:A:2:1"], "congress vote": ["-123:A:2:1"],
            "map show": ["4", "5"], "map tile": ["4", "5"], "map unit": ["7"], "map city": ["65536"],
            "great-work options": ["36"],
            "great-work move": ["36", "65536", "BUILDING_PALACE", "0"],
        }
        terminal = Terminal(SnapshotConnection())
        query_plans, action_plans = [], []
        def options(plan):
            query_plans.append(plan)
            return [[] for _ in plan.queries]
        with patch('civ6_cli.repl.read_units', return_value=[unit, spy]), \
             patch('civ6_cli.repl.read_cities', return_value=[city]), \
             patch('civ6_cli.repl.read_known_players', return_value=[]), \
             patch('civ6_cli.repl.read_visible_entities', return_value=([], [])), \
             patch('civ6_cli.repl.read_map'), patch('civ6_cli.repl.render_map', return_value="map"), \
             patch('civ6_cli.repl.run_report', return_value=[]), \
             patch.object(terminal, 'resolve_map_entity', return_value=unit), \
             patch.object(terminal, 'lines'), patch.object(terminal, 'overview'), \
             patch.object(terminal, 'wait_for_turn'), \
             patch.object(terminal.connection, 'connect', create=True), \
             patch.object(terminal.connection, 'probe', return_value='266', create=True), \
             patch.object(terminal.connection, 'app_identity', 'Civ6', create=True), \
             patch.object(terminal, 'perform', side_effect=lambda plan, **kwargs: action_plans.append(plan)), \
             patch('civ6_cli.actions.ActionService.options', side_effect=options), redirect_stdout(io.StringIO()):
            for command in COMMANDS:
                args = samples.get(command.path)
                if args is None:
                    args = [] if not command.minimum else ["65536" if command.path.startswith("city ") else "7"] + ["4", "5"][:command.minimum - 1]
                with self.subTest(command=command.path):
                    terminal.execute(command.path.split() + args)
        self.assertEqual(len(action_plans), len([c for c in COMMANDS if c.mode == "写"]))
        self.assertTrue(all(p.lua and p.summary for p in action_plans))
        self.assertTrue(all(p.queries for p in query_plans))

    def test_manual_reference_is_generated_from_same_registry(self):
        manual = (Path(__file__).resolve().parents[1] / "COMMAND_MANUAL.md").read_text(encoding="utf-8")
        self.assertIn(manual_command_tables(), manual)


class RegressionTests(unittest.TestCase):
    def test_successful_production_has_no_fallible_post_query(self):
        lua = cities.build_produce_item(65536, "UNIT", "UNIT_BUILDER")
        after_request = lua.split("CityManager.RequestOperation", 1)[1]
        self.assertNotIn("GetTurnsLeft", after_request)
        self.assertNotIn("CurrentlyBuilding", after_request)
        self.assertIsNone(city_plan(65536, "produce", ["unit", "UNIT_BUILDER"], coordinate=int).verify)

    def test_skip_government_and_policy_keep_layout_without_paid_unlock(self):
        for command in ("government", "policies"):
            plan = standalone_plan(command, ["keep"], city_id=int)
            self.assertNotIn("UNLOCK_POLICIES", plan.lua)
            self.assertIsNone(plan.verify)
        self.assertIn("SetGovernmentChangeConsidered(true)", governance.build_keep_government())
        self.assertIn("ERR:EMPTY_POLICY_SLOT", governance.build_keep_policies())
        self.assertIn("OK:POLICIES_NOT_APPLICABLE", governance.build_keep_policies())
        self.assertIn("RequestPolicyChanges(clearList, addList)", governance.build_keep_policies())

    def test_research_success_has_no_fallible_post_query(self):
        for category, item in (("tech", "TECH_STEEL"), ("civic", "CIVIC_SUFFRAGE")):
            plan = standalone_plan("research", [category, item], city_id=int)
            self.assertIsNone(plan.verify)
            self.assertIn("UI.RequestPlayerOperation", plan.lua)
            self.assertIn("CanResearch" if category == "tech" else "CanProgress", plan.lua)
            after_request = plan.lua.split("UI.RequestPlayerOperation", 1)[1]
            self.assertNotIn("NotificationManager", after_request)

    def test_trade_test_reports_accept_counteroffer_or_rejection(self):
        lua = diplomacy.build_test_trade(2, [{"type": "GOLD", "amount": 10}], [])
        for outcome in ("RESULT|ACCEPTED", "RESULT|COUNTEROFFER", "RESULT|REJECTED"):
            self.assertIn(outcome, lua)
        self.assertIn("AreWorkingDealsEqual", lua)
        self.assertIn("ERR:PENDING_DEAL", lua)

    def test_conditional_peace_uses_locked_native_treaty(self):
        items = [{"type": "CITY", "city_id": 65536}]
        for lua in (diplomacy.build_test_peace(2, [], items), diplomacy.build_propose_peace(2, [], items)):
            self.assertIn("DealAgreementTypes.MAKE_PEACE", lua)
            self.assertIn("SetLocked(true)", lua)
            self.assertIn('RequestSession(me, target, "MAKE_DEAL")', lua)
            self.assertIn("DealItemTypes.CITIES", lua)
        self.assertIn("trade pending", diplomacy.build_propose_peace(2, [], items))

    def test_apostle_belief_is_a_complete_two_stage_cli_action(self):
        evangelize = religion.build_evangelize_belief(7)
        add = religion.build_add_belief("BELIEF_WAT")
        self.assertIn("UNITOPERATION_EVANGELIZE_BELIEF", evangelize)
        self.assertIn("UnitManager.RequestOperation", evangelize)
        self.assertIn("PlayerOperations.ADD_BELIEF", add)
        self.assertIn("PARAM_BELIEF_TYPE", add)
        self.assertIn("VALUE_EXCLUSIVE", add)

    def test_city_blocker_query_emits_identified_city(self):
        lua = notifications.build_end_turn_blocking_query()
        for field in ("BLOCKING_CITY|id=", "|name=", "|population=", "|source=", "|choices="):
            self.assertIn(field, lua)

    def test_capture_selects_only_pending_targets_and_checks_city(self):
        plan = standalone_plan("capture", ["65536", "keep"], city_id=int)
        self.assertIn("selectedID = 65536", plan.lua)
        self.assertIn("GetNextCapturedCity()", plan.lua)
        self.assertIn("entry:GetLocation()", plan.lua)
        self.assertNotIn("for _, candidate in player:GetCities():Members()", plan.lua)
        self.assertIn("ERR:CITY_REQUIRED", cities.build_resolve_city_capture("keep"))
        self.assertIn("ERR:INVALID_REBELLED_DECISION", cities.build_resolve_city_capture("raze", 65536))

    def test_routes_are_legal_and_have_duration_and_yields(self):
        lua = economy.build_trade_destinations_query(7)
        self.assertIn("GetTradeRoutePath", lua)
        self.assertIn("TRADE_ROUTE_TURN_DURATION_BASE", lua)
        self.assertIn("CostMultiplier", lua)
        self.assertNotIn("enrichDest(i, city, cx, cy, i == me)", lua.split("if found == 0 then")[1])
        parsed = economy.parse_trade_destinations_response(["TDEST|马赛|Domestic|64,26|1|0|0|0|1|拜火教|0||F4P3|0|5|30"])
        self.assertEqual((parsed[0].one_way_distance, parsed[0].estimated_turns), (5, 30))
        legacy = economy.parse_trade_destinations_response(["TDEST|马赛|Domestic|64,26|1"])
        self.assertIsNone(legacy[0].estimated_turns)

    def test_policy_and_purchase_errors_render_expected_lua_messages(self):
        purchase_lua = cities.build_purchase_item(65536, "UNIT", "UNIT_BUILDER")
        self.assertIn("action='move'", purchase_lua)
        policy_lua = governance.build_set_policies({0: "POLICY_AGOGE"})
        self.assertIn("ERR:CANNOT_SLOT|POLICY_AGOGE", policy_lua)
        self.assertIn("ERR:SLOT_MISMATCH|POLICY_AGOGE", policy_lua)

    def test_option_menus_include_keep_choices_and_precise_todo_hints(self):
        from civ6_cli.repl import _normalize_option_lines, _todo_hint
        gov = _normalize_option_lines("可用政体", ["GOV|GOVERNMENT_CHIEFDOM|0|CURRENT|酋邦||"])
        self.assertIn("next=government keep", gov[-1])
        full = _normalize_option_lines("政策槽位与可用政策卡", ["SLOT|0|SLOT_ECONOMIC|POLICY_URBAN_PLANNING|城市规划"])
        self.assertIn("available=yes", full[-1])
        empty = _normalize_option_lines("政策槽位与可用政策卡", ["SLOT|0|SLOT_ECONOMIC|NONE|Empty"])
        self.assertIn("available=no", empty[-1])
        for name, expected in (("FILL_CIVIC_SLOT", "policy"), ("GIVE_INFLUENCE_TOKEN", "envoy"),
                               ("CONSIDER_DISLOYAL_CITY", "city capture"), ("COMMEMORATION_AVAILABLE", "era"),
                               ("SPY_CHOOSE_ESCAPE_ROUTE", "spy escape")):
            self.assertIn(expected, _todo_hint("ENDTURN_BLOCKING_" + name))

    def test_spy_details_use_native_duration_probability_and_reward(self):
        lua = espionage.build_spy_options_query(8)
        for token in ("GetTimeToComplete", "GetResultProbability", "GetOperationDetailText", "ESPIONAGE_SUCCESS_MUST_ESCAPE",
                      "OFFENSIVESPY", "SPY_MISSION|", "BREACH_DAM", "GetTravelTime", "GetEstablishInCityTime"):
            self.assertIn(token, lua)
        self.assertIn("Cities.GetPlotPurchaseCity(unitPlot)", lua)
        self.assertIn("Map.GetPlot(city:GetX(), city:GetY())", lua)
        plan = spy_plan(["8", "BREACH_DAM", "4", "5"], coordinate=int)
        self.assertIn("UNITOPERATION_SPY_BREACH_DAM", plan.lua)
        self.assertIn("PARAM_X]=4", plan.lua)
        self.assertNotIn("PARAM_X0", plan.lua)
        with self.assertRaises(ValueError):
            spy_plan(["8", 'X\"] print("bad")', "4", "5"], coordinate=int)

    def test_special_units_use_safe_task_contracts(self):
        self.assertIn("TASK_MOVEMENT", units.build_move_unit(7, 4, 5))
        for operation in ("EXCAVATE", "DESIGNATE_PARK", "TOURISM_BOMB", "REBASE", "DEPLOY", "REMOVE_HERESY", "RELIGIOUS_HEAL"):
            self.assertIn(operation, units.build_unit_operations_query(7))
            self.assertIn("CanStartOperation", unit_plan(7, "task", ["UNITOPERATION_" + operation], coordinate=int).lua)
        for operation in ("UNITOPERATION_EXECUTE_SCRIPT", "UNITOPERATION_EVANGELIZE_BELIEF", "UNITOPERATION_WMD_STRIKE"):
            with self.assertRaises(ValueError):
                unit_plan(7, "task", [operation], coordinate=int)
        self.assertIn("religion evangelize", units.build_unit_operations_query(7))


if __name__ == "__main__":
    unittest.main()
