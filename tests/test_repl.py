import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from civ6_cli.game import KnownCity, PlayerStatus, Unit
from civ6_cli.repl import Terminal, _normalize_option_lines, run
from civ6_cli.rendering import Display
from test_overview import SnapshotConnection, SUMMARY


class CommandTests(unittest.TestCase):
    def test_name_resolution_and_ownership(self):
        terminal = Terminal(SnapshotConnection())
        self.assertEqual(terminal.resolve('unit', '勇士').id, 7)
        with self.assertRaisesRegex(ValueError, '未找到'):
            terminal.resolve('unit', '999')

    def test_duplicate_names_require_id(self):
        units = [Unit(i, '勇士', 'UNIT_WARRIOR', 1, 1, 2, 2, 100, 100) for i in (1, 2)]
        with patch('civ6_cli.repl.read_units', return_value=units):
            with self.assertRaisesRegex(ValueError, '多个对象'):
                Terminal(None).resolve('unit', '勇士')

    def test_map_can_resolve_revealed_foreign_city_with_owner_id(self):
        kyoto = KnownCity(1, '日本', 65536, '京都', 54, 31, False)
        with patch('civ6_cli.repl.read_visible_entities', return_value=([], [kyoto])):
            self.assertEqual(Terminal(None).resolve_map_entity('city', '1:65536'), kyoto)

    def test_actions_and_wrong_arguments_are_rejected(self):
        for words in (['move', '1', '2', '3'], ['end'], ['status', 'extra'], ['map', 'show'],
                      ['reports'], ['options', 'research'], ['unit', '7', 'move', '1', '2'],
                      ['unit', 'help'], ['quit']):
            with self.assertRaises(ValueError):
                Terminal(None).execute(words)

    def test_turn_check_prints_only_once_and_waits_for_local_turn(self):
        terminal = Terminal(None)
        status = PlayerStatus(97, 0, 'Arabia', 'Saladin', 0, 0, 0, 0, 0, 0, False)
        with patch('civ6_cli.repl.read_status', return_value=status), patch.object(terminal, 'overview') as show:
            self.assertFalse(terminal.check_turn())
            show.assert_not_called()
        active = PlayerStatus(97, 0, 'Arabia', 'Saladin', 0, 0, 0, 0, 0, 0, True)
        with patch('civ6_cli.repl.read_status', return_value=active), patch.object(terminal, 'overview') as show:
            self.assertTrue(terminal.check_turn())
            show.assert_called_once()
            terminal.last_stamp = (97,0)
            self.assertFalse(terminal.check_turn())

    def test_scripted_repl_has_initial_overview(self):
        with patch('builtins.input', side_effect=['help', 'session quit']), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(run(SnapshotConnection(), display=Display(80)), 0)
        self.assertIn('第 96 回合', output.getvalue())

    def test_help_needs_no_connection_and_has_domain_queries(self):
        with redirect_stdout(io.StringIO()) as output:
            Terminal(None).execute(['help'])
            Terminal(None).execute(['help', 'map'])
            Terminal(None).execute(['help', 'great-work'])
        self.assertIn('research', output.getvalue())
        self.assertIn('<阵营ID>:<城市ID>', output.getvalue())
        self.assertIn('great-work list', output.getvalue())
        self.assertNotIn('report show', output.getvalue())

    def test_resource_filter_is_forwarded_to_fixed_domain_query(self):
        terminal = Terminal(None)
        with patch('civ6_cli.repl.run_report', return_value=['RESOURCE_COUNT|0']) as report, redirect_stdout(io.StringIO()):
            terminal.execute(['economy', 'resources', '鱼'])
        report.assert_called_once_with(None, 'resources', '鱼')
        with self.assertRaises(ValueError):
            terminal.execute(['economy', 'show', '鱼'])

    def test_legacy_truncated_unit_ids_resolve_only_for_reads(self):
        unit = Unit(6619157, '苏迪曼', 'UNIT_GREAT_GENERAL', 66, 32, 4, 4, 100, 100)
        terminal = Terminal(None)
        with patch('civ6_cli.repl.read_units', return_value=[unit]), redirect_stdout(io.StringIO()):
            self.assertEqual(terminal.resolve('unit', '661915', allow_truncated=True), unit)
            with self.assertRaisesRegex(ValueError, '未找到'):
                terminal.resolve('unit', '661915')
            with self.assertRaises(ValueError):
                terminal.execute(['unit', 'skip', '661915'])
        another = Unit(6619158, '另一单位', 'UNIT_GREAT_GENERAL', 66, 32, 4, 4, 100, 100)
        with patch('civ6_cli.repl.read_units', return_value=[unit, another]):
            with self.assertRaisesRegex(ValueError, '多个对象'):
                terminal.resolve('unit', '661915', allow_truncated=True)
        exact = Unit(661915, '精确 ID', 'UNIT_WARRIOR', 66, 32, 4, 4, 100, 100)
        with patch('civ6_cli.repl.read_units', return_value=[unit, exact]):
            self.assertEqual(terminal.resolve('unit', '661915', allow_truncated=True), exact)

    def test_policy_no_slots_is_explained_as_noop_not_filled_layout(self):
        lines = _normalize_option_lines('政策槽位与可用政策卡', ['GOV|NONE|无政体|0'])
        self.assertIn('当前没有政策槽位', lines[-1])
        self.assertNotIn('全部槽位已填满', lines[-1])

    def test_repl_does_not_poll_between_commands(self):
        connection = SnapshotConnection()
        with patch('builtins.input', side_effect=['help', 'help', 'session quit']), redirect_stdout(io.StringIO()):
            self.assertEqual(run(connection), 0)
        self.assertEqual(connection.summary_reads, 1)

    def test_todo_adds_human_next_step(self):
        lines = _normalize_option_lines(
            "回合待办与外部响应",
            ["BLOCKING|ENDTURN_BLOCKING_PRODUCTION|选择生产项目"],
        )
        self.assertIn("next=city production <城市>", lines[0])

    def test_disloyal_city_hint_does_not_create_a_fake_record_column(self):
        lines = _normalize_option_lines(
            "回合待办与外部响应",
            ["BLOCKING|ENDTURN_BLOCKING_CONSIDER_DISLOYAL_CITY|选择城市处置"],
        )
        self.assertIn("keep 或 reject", lines[0])
        self.assertNotIn("keep|reject", lines[0])

    def test_unit_options_localize_activity_and_order_state(self):
        row = "1|1|勇士|UNIT_WARRIOR|2,3|2/2|fortify_or_alert|no|100/100|20|0|0||0|0||0||"
        normalized = _normalize_option_lines("单位与可执行动作", [row])
        self.assertIn("|驻防/警戒|否|", normalized[0])

        ready = row.replace("fortify_or_alert|no", "ready|yes")
        self.assertIn("|待命|是|", _normalize_option_lines("单位与可执行动作", [ready])[0])

        unknown = row.replace("fortify_or_alert|no", "unknown|unknown")
        self.assertIn("|未知|未知|", _normalize_option_lines("单位与可执行动作", [unknown])[0])
