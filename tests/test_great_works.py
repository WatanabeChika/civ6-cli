import unittest
from unittest.mock import Mock

from civ6_cli.actions import great_work_move_plan, great_work_options_plan
from civ6_cli.commands import COMMANDS
from civ6_cli.lua import governance, great_works
from civ6_cli.reports import available_reports


class GreatWorkTests(unittest.TestCase):
    def test_move_plan_validates_before_city_lookup_and_lua_interpolation(self):
        lookup = Mock(return_value=131073)
        plan = great_work_move_plan(['0', '马赛', 'building-amphitheater', '1'], city_id=lookup)
        lookup.assert_called_once_with('马赛')
        self.assertIn('BUILDING_AMPHITHEATER', plan.lua)
        self.assertIn('交换', plan.summary)
        self.assertIsNone(plan.verify)
        for args in (['-1', 'city', 'BUILDING_PALACE', '0'],
                     ['1', 'city', 'BUILDING_PALACE', '-1'],
                     ['1', 'city', 'BUILDING_PALACE', '256'],
                     ['1', 'city', 'BUILDING_PALACE\"] print(1)', '0'],
                     ['1', 'city', 'UNIT_WARRIOR', '0'], ['1']):
            with self.subTest(args=args), self.assertRaises(ValueError):
                great_work_move_plan(args, city_id=lookup)

    def test_work_id_is_runtime_index_and_all_native_parameters_are_present(self):
        plan = great_work_move_plan(['36', '131073', 'BUILDING_PALACE', '0'], city_id=int)
        for parameter in ('PARAM_PLAYER_ONE', 'PARAM_CITY_SRC', 'PARAM_CITY_DEST',
                          'PARAM_BUILDING_SRC', 'PARAM_BUILDING_DEST', 'PARAM_GREAT_WORK_INDEX', 'PARAM_SLOT'):
            self.assertIn('params[PlayerOperations.' + parameter + ']', plan.lua)
        self.assertIn('PlayerOperations.MOVE_GREAT_WORK', plan.lua)
        self.assertIn('local workID = 36', plan.lua)
        self.assertIn('srcCity:GetID()', plan.lua)
        self.assertIn('dstCity:GetID() ~= 131073', plan.lua)
        self.assertIn('ERR:SAME_GREAT_WORK_SLOT', plan.lua)
        self.assertIn('ERR:GREAT_WORK_MOVE_REJECTED', plan.lua)

    def test_read_and_write_share_exact_slot_legality_rules(self):
        options = great_work_options_plan('36').queries[0].lua
        move = great_works.build_move(36, 131073, 'BUILDING_PALACE', 0)
        for source in (options, move):
            self.assertIn(great_works._COMMON, source)
            self.assertIn('GREATWORK_ART_LOCK_TIME', source)
            self.assertIn('GREATWORKOBJECT_ARTIFACT', source)
            self.assertIn('GameInfo.GreatWork_ValidSubTypes', source)
            self.assertIn('fits(src, srcBuilding, srcSlot, object(dst, other))', source)
        self.assertIn('|next=', options)
        self.assertNotIn('UI.RequestPlayerOperation', options)
        for invalid in ('-1', '1.0', 'bad', '2147483648'):
            with self.assertRaises(ValueError):
                great_work_options_plan(invalid)

    def test_all_old_report_information_remains_reachable_by_domains(self):
        covered = {c.route[1] for c in COMMANDS if c.route[0] == 'query'}
        # turn todo combines blockers with current diplomatic responses.
        covered.add('blockers')
        merged = {'research options': 'research', 'government options': 'government',
                  'envoy options': 'city-states', 'era options': 'era',
                  'great-person options': 'great-people', 'congress options': 'congress'}
        registered = {command.path for command in COMMANDS}
        self.assertTrue(set(merged) <= registered)
        self.assertTrue({'policy options', 'governor options'} <= registered)
        covered.update(merged.values())
        self.assertEqual(covered, {r.name for r in available_reports()})
        self.assertFalse(any(c.path.split()[0] in ('report', 'dedication') for c in COMMANDS))

    def test_policies_read_live_anarchy_and_preserve_unlocked_card_visibility(self):
        lua = governance.build_policies_query()
        self.assertIn('IsInAnarchy()', lua)
        self.assertIn('GetAnarchyTurns()', lua)
        self.assertIn('canSlot or numSlots == 0', lua)
        self.assertIn('|description=', lua)
        self.assertIn('|can_slot=', lua)
