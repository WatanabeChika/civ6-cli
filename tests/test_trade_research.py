import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from civ6_cli.actions import option_plan, parse_trade_items, trade_plan
from civ6_cli.commands import show_help
from civ6_cli.game import Unit
from civ6_cli.lua import diplomacy, great_people, tech
from civ6_cli.rendering import Display, render_records
from civ6_cli.repl import Terminal


class TradeResearchTests(unittest.TestCase):
    def test_native_instance_terms_are_nonnegative_ids_in_both_directions(self):
        for kind, expected in (('great-work', 'GREAT_WORK'), ('captive', 'CAPTIVE'), ('city', 'CITY')):
            offer, request = parse_trade_items([f'give-{kind}=0', f'want-{kind}=36'])
            self.assertEqual(offer[0]['type'], expected)
            self.assertEqual(request[0]['type'], expected)
            for bad in ('-1', '1.5', '2147483648', '1;print(1)'):
                with self.assertRaises(ValueError):
                    parse_trade_items([f'give-{kind}={bad}'])

    def test_agreements_keep_secondary_selections_and_signed_war_hash(self):
        offer, request = parse_trade_items([
            'give-alliance=research', 'give-research-agreement=TECH_WRITING',
            'give-joint-war=3:-566258', 'want-third-party-war=4:1941490022'])
        self.assertEqual(offer[0]['alliance_type'], 'ALLIANCE_RESEARCH')
        self.assertEqual(offer[1]['technology'], 'TECH_WRITING')
        self.assertEqual(offer[2]['war_type'], -566258)
        self.assertEqual(request[0]['value_id'], 4)
        for bad in ('give-alliance=unknown', 'give-research-agreement=0',
                    'give-joint-war=3:1:2', 'give-joint-war=64',
                    'give-joint-war=3:-2147483649', 'give-joint-war=3:1;print(1)'):
            with self.assertRaises(ValueError):
                parse_trade_items([bad])

    def test_duplicate_terms_cannot_silently_overwrite_requested_amounts(self):
        for tokens in (['give-gold=10', 'give-gold=20'], ['give-favor=1', 'give-favor=2'],
                       ['give-great-work=36', 'give-great-work=36'],
                       ['want-resource=RESOURCE_IRON:10', 'want-resource=RESOURCE_IRON:20'],
                       ['give-alliance=research', 'give-alliance=military']):
            with self.assertRaisesRegex(ValueError, '重复'):
                parse_trade_items(tokens)
        offer, _ = parse_trade_items(['give-gold=10', 'give-gpt=20',
                                     'give-great-work=36', 'give-great-work=37'])
        self.assertEqual(len(offer), 4)

    def test_new_terms_work_for_test_send_and_conditional_peace(self):
        for command in ('propose', 'peace'):
            for mode in ('test', 'send'):
                plan = trade_plan([command, '5', mode, 'give-great-work=36', 'want-captive=1'])
                self.assertIn('di:SetSubType(selected.ForTypeDescriptionID)', plan.lua)
                self.assertIn('DealItemTypes.CAPTIVE', plan.lua)
                self.assertIn('deal:IsValid()', plan.lua)
                self.assertLess(plan.lua.index('ERR:INVALID_DEAL'), plan.lua.index('DealManager.SendWorkingDeal'))
        with self.assertRaises(ValueError):
            diplomacy._lua_deal_item('me', {'type': 'UNKNOWN'})

    def test_option_reads_do_not_mutate_sessions_or_deal_drafts(self):
        source = diplomacy.build_deal_options_query(5)
        for mutation in ('ClearWorkingDeal', 'SendWorkingDeal', 'RequestSession', ':AddItemOfType'):
            self.assertNotIn(mutation, source)
        self.assertIn('TRADE_GREAT_WORK', source)
        self.assertIn('TRADE_CAPTIVE', source)
        self.assertIn('TRADE_AGREEMENT', source)
        self.assertIn('ValidationResult', source)
        self.assertNotIn('GetVisibilityOn(target) >= 2', source)

    def test_native_options_parser_preserves_ids_legality_and_terms(self):
        result = diplomacy.parse_deal_options_response([
            'CIV|5|日本',
            'TRADE_GREAT_WORK|side=OURS|id=36|name=圣母|available=true|reason=VALID|term=give-great-work=36',
            'TRADE_CAPTIVE|side=THEIRS|id=1|name=俘虏|available=false|reason=MISSING_DEPENDENCY|term=want-captive=1',
            'TRADE_AGREEMENT|side=OURS|name=研究同盟|turns=30|available=true|term=give-alliance=research',
            'CITY|OURS|65536|开罗|8|0|available=false|reason=INVALID|term=give-city=65536'])
        self.assertEqual(result.native_options[0].instance_id, 36)
        self.assertFalse(result.native_options[1].available)
        self.assertEqual(result.native_options[2].term, 'give-alliance=research')
        self.assertEqual(result.native_options[2].turns, 30)
        self.assertFalse(result.our_cities[0].available)

    def test_research_new_and_legacy_civic_wire_formats(self):
        source = ['CURRENT|科技|3|市政|4|tech_type=TECH_TEST|tech_progress=40.5|tech_cost=100|civic_type=CIVIC_TEST|civic_progress=?|civic_cost=100',
                  'CIVIC|市政|CIVIC_TEST|100|60|4|unknown|条件|解锁政策|CIVIC_FIRST|ERA_ANCIENT']
        result = tech.parse_tech_civics_response(source)
        self.assertEqual(result.current_research_progress, 40.5)
        self.assertIsNone(result.current_civic_progress)
        self.assertEqual(result.available_civics[0].unlocks, '解锁政策')
        self.assertEqual(result.available_civics[0].prereqs, 'CIVIC_FIRST')
        self.assertIsNone(result.available_civics[0].boosted)
        legacy = tech.parse_tech_civics_response(['CIVIC|市政|CIVIC_TEST|100|60|4|BOOSTED|条件|CIVIC_FIRST|ERA_ANCIENT'])
        self.assertEqual(legacy.available_civics[0].prereqs, 'CIVIC_FIRST')
        self.assertEqual(legacy.available_civics[0].unlocks, '')

    def test_research_percentage_is_not_rendered_as_progress_points(self):
        lines = ['TECH|科技|TECH_TEST|100|40|3|BOOSTED|条件|解锁|前置|ERA_ANCIENT']
        rendered = render_records(lines, Display(width=150))
        self.assertIn('40%', rendered)
        self.assertNotIn('40/100', rendered)

    def test_great_people_combined_options_preserve_every_detail(self):
        result = great_people.parse_great_people_response([
            'GREAT_PERSON|id=1|can_recruit=unknown|class=艺术家|name=姓名|era=时代|cost=100|claimant=unclaimed|my_points=20|gold_cost=?|faith_cost=200|active=主动能力|passive=被动能力|great_works=巨作名|progress=日本:30/100'])
        self.assertEqual(result[0].passive, '被动能力')
        self.assertEqual(result[0].great_works, '巨作名')
        self.assertEqual(result[0].competition, '日本:30/100')
        self.assertEqual(result[0].gold_cost, -1)
        self.assertIsNone(result[0].can_recruit)

    def test_diplomacy_options_no_longer_duplicates_trade_options(self):
        plan = option_plan('diplomacy', ['5'], unit_id=int, city_id=int)
        self.assertEqual(len(plan.queries), 1)
        self.assertNotIn('TRADE_GREAT_WORK', plan.queries[0].lua)
        self.assertIn('DIPLO_NOTE', plan.queries[0].lua)

    def test_unit_show_does_not_append_task_options_for_special_units(self):
        for kind in ('UNIT_TRADER', 'UNIT_SPY'):
            unit = Unit(7, '测试单位', kind, 1, 2, 1, 1, 100, 100)
            terminal = Terminal(None)
            with patch.object(terminal, 'resolve', return_value=unit), patch.object(terminal, 'lines'), \
                 patch.object(terminal, 'show_unit_options') as options, patch('builtins.print'):
                terminal.execute(['unit', 'show', '7'])
            options.assert_not_called()

    def test_removed_duplicates_never_appear_in_help_or_manual(self):
        removed = ('research show', 'government show', 'envoy show', 'era show',
                   'great-person show', 'congress show', 'unit routes', 'spy options')
        with patch('sys.stdout', new_callable=io.StringIO) as output:
            show_help(['tree'], Display(width=160))
        manual = (Path(__file__).resolve().parents[1] / 'COMMAND_MANUAL.md').read_text(encoding='utf-8')
        for old in removed:
            self.assertNotIn(old, output.getvalue())
            self.assertNotIn(old, manual)

    def test_isolated_lua51_runtime_contracts(self):
        try:
            from lupa.lua51 import LuaRuntime
        except ImportError:
            self.skipTest('Optional Lua 5.1 runtime; also covered by verify_readonly.py')
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
        from query_trade_contracts import contract_query
        from verify_readonly import lua_string
        runtime = LuaRuntime()
        records = []
        runtime.globals().print = records.append
        runtime.execute(contract_query(lua_string))
        self.assertEqual(len(records), 30)
        self.assertTrue(all(record.startswith('CONTRACT_CHECK|') for record in records))

    def test_all_new_read_and_write_templates_compile_in_lua51(self):
        try:
            from lupa.lua51 import LuaRuntime
        except ImportError:
            self.skipTest('Optional Lua 5.1 runtime')
        runtime = LuaRuntime(unpack_returned_tuples=True)
        compile_source = runtime.eval('function(source) local f,e=loadstring(source); return f~=nil,e end')
        tokens = ['give-gold=10', 'give-gpt=2', 'give-favor=1',
                  'give-resource=RESOURCE_IRON:20:30', 'give-city=65536',
                  'give-great-work=36', 'give-captive=1', 'give-alliance=research',
                  'give-research-agreement=TECH_WRITING', 'give-joint-war=3:-566258',
                  'give-third-party-war=4:1941490022']
        sources = [diplomacy.build_deal_options_query(5),
                   diplomacy.build_pending_deals_query(), diplomacy.build_diplomacy_session_query(),
                   tech.build_tech_civics_query(), great_people.build_great_people_query()]
        for token in tokens:
            for command in ('propose', 'peace'):
                for mode in ('test', 'send'):
                    sources.append(trade_plan([command, '5', mode, token]).lua)
        for source in sources:
            ok, error = compile_source(source)
            self.assertTrue(ok, error)
