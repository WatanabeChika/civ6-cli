import unittest

from civ6_cli.actions import (
    ActionOutcomeUnknown,
    ActionPlan,
    ActionRejected,
    ActionService,
    Query,
    city_plan,
    game_symbol,
    parse_policy_assignments,
    parse_trade_items,
    parse_vote_specs,
    trade_plan,
    diplomacy_plan,
    unit_plan,
)
from civ6_cli.lua import units
from civ6_cli.transport import FireTunerError


STATUS = "STATUS|96|0|阿拉伯|萨拉丁|100.0|10.0|8.0|20.0|2|3|yes"


class RoutedConnection:
    def __init__(self, action_lines=None, *, active=True, fail_action=False):
        self.action_lines = action_lines or ["OK:DONE", "---END---"]
        self.active = active
        self.fail_action = fail_action
        self.calls = []

    def execute_read_lines(self, lua, *, context="GameCore_Tuner", timeout=None):
        self.calls.append((lua, context, timeout))
        if "local cfg = PlayerConfigurations[id]" in lua:
            return [STATUS.replace("|yes", "|yes" if self.active else "|no")]
        if lua == "VERIFY":
            return ["CONFIRMED|state", "---END---"]
        if self.fail_action:
            raise FireTunerError("wire lost")
        return list(self.action_lines)

    def execute_action_lines(self, lua, *, context="InGame", timeout=None):
        return self.execute_read_lines(lua, context=context, timeout=timeout)


class ActionValidationTests(unittest.TestCase):
    def test_unit_options_use_authoritative_ready_state(self):
        lua = units.build_units_query()
        self.assertIn("unit:IsReadyToMove()", lua)
        self.assertIn("UnitManager.GetActivityType(unit)", lua)
        self.assertIn("unit:IsAutomated()", lua)
        self.assertIn('needsOrders = ready and "yes" or "no"', lua)

    def test_batch_actions_do_not_touch_persistent_or_unknown_states(self):
        for lua in (units.build_skip_remaining_units(), units.build_fortify_remaining_units()):
            self.assertIn("unit:IsReadyToMove()", lua)
            self.assertIn("okReady and ready", lua)
            self.assertNotIn("unit:GetMovesRemaining() > 0", lua)

    def test_game_symbols_reject_lua_injection_and_wrong_prefix(self):
        self.assertEqual(game_symbol("unit_warrior", "UNIT_"), "UNIT_WARRIOR")
        for value in ('UNIT_X"] print("oops") --', "UNIT_X;DROP", "POLICY_AGOGE"):
            with self.assertRaises(ValueError):
                game_symbol(value, "UNIT_")

    def test_complex_human_parameters_are_validated(self):
        self.assertEqual(parse_policy_assignments(["0=POLICY_AGOGE,1=NONE"]),
                         {0: "POLICY_AGOGE", 1: "NONE"})
        votes = parse_vote_specs(["-123:A:4:3"])
        self.assertEqual(votes[0], {"hash": -123, "option": 1, "target": 4, "votes": 3})
        give, want = parse_trade_items([
            "give-resource=RESOURCE_IRON:20:30", "want-gpt=5", "want-open-borders"
        ])
        self.assertEqual(give[0]["amount"], 20)
        self.assertEqual(want[0]["duration"], 30)
        self.assertEqual(want[1]["subtype"], "OPEN_BORDERS")

    def test_unit_and_city_plans_use_fixed_builders(self):
        move = unit_plan(7, "move", ["4", "5"], coordinate=int)
        self.assertIn("RequestOperation", move.lua)
        self.assertIn("= 4", move.lua)
        buy = city_plan(65536, "buy", ["gold", "district", "DISTRICT_CAMPUS", "3", "4"], coordinate=int)
        self.assertIn("PARAM_X] = 3", buy.lua)
        with self.assertRaises(ValueError):
            city_plan(65536, "buy", ["gold", "district", "DISTRICT_CAMPUS"], coordinate=int)

    def test_trade_test_does_not_require_mutating_ack(self):
        plan = trade_plan(["propose", "2", "test", "give-gold=10"])
        self.assertFalse(plan.requires_ack)
        connection = RoutedConnection(["CIV|2|罗马", "AI_COUNTER", "REJECTED", "---END---"])
        result = ActionService(connection).execute(plan)
        self.assertIn("AI_COUNTER", result.lines)

    def test_trade_send_never_auto_accepts_counteroffer(self):
        plan = trade_plan(["propose", "2", "send", "give-gold=10"])
        marker = 'print("OK:PROPOSED|Trade proposal sent'
        self.assertIn(marker, plan.lua)
        self.assertNotIn("DealProposalAction.ACCEPTED", plan.lua)

    def test_war_declaration_schedules_two_phase_ui_cleanup(self):
        plan = diplomacy_plan(["action", "2", "DECLARE_FORMAL_WAR"])
        self.assertEqual([delay for delay, _ in plan.followups], [8.0, 1.0])


class ActionExecutionTests(unittest.TestCase):
    def test_execute_preflights_once_and_verifies(self):
        connection = RoutedConnection(["OK:CHANGED|value", "---END---"])
        result = ActionService(connection).execute(ActionPlan("change", "ACTION", verify=Query("VERIFY")))
        self.assertEqual(result.lines, ("OK:CHANGED|value",))
        self.assertEqual(result.verification, ("CONFIRMED|state",))
        self.assertEqual(len(connection.calls), 3)

    def test_definitive_game_rejection_is_not_unknown(self):
        connection = RoutedConnection(["ERR:NO_MOVES|done", "---END---"])
        with self.assertRaises(ActionRejected):
            ActionService(connection).execute(ActionPlan("move", "ACTION"))

    def test_transport_failure_after_preflight_is_unknown_and_not_retried(self):
        connection = RoutedConnection(fail_action=True)
        with self.assertRaises(ActionOutcomeUnknown):
            ActionService(connection).execute(ActionPlan("move", "ACTION"))
        self.assertEqual(len(connection.calls), 2)

    def test_inactive_turn_blocks_normal_action_but_allows_response(self):
        connection = RoutedConnection(active=False)
        with self.assertRaises(ActionRejected):
            ActionService(connection).execute(ActionPlan("move", "ACTION"))
        result = ActionService(connection).execute(
            ActionPlan("respond", "ACTION", allow_inactive_turn=True)
        )
        self.assertEqual(result.lines, ("OK:DONE",))

    def test_failed_readback_is_flagged_as_uncertain_not_silently_successful(self):
        for lines in (["NOT_SET|current=UNIT_SCOUT"], ["ERROR|optional API failed"]):
            connection = RoutedConnection()
            service = ActionService(connection)
            with unittest.mock.patch.object(service, "query", return_value=lines):
                result = service.execute(ActionPlan("change", "ACTION", verify=Query("VERIFY")))
            self.assertTrue(result.uncertain)


if __name__ == "__main__":
    unittest.main()
