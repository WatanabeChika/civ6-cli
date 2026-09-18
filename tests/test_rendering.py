import unittest
import io
import re
from contextlib import redirect_stdout
from unittest.mock import patch

from civ6_cli.repl import _show_lines
from civ6_cli.records import parse_records
from civ6_cli.rendering import Display, cell_width, plain, render_records, table


class RenderingTests(unittest.TestCase):
    def test_coordinate_output_is_parenthesized(self):
        output = io.StringIO()
        with redirect_stdout(output):
            _show_lines(['UNIT_DETAIL|name=勇士|position=31,24'])
        self.assertIn('(31,24)', output.getvalue())

    def test_cjk_and_combining_width(self):
        self.assertEqual(cell_width('开罗ABC'), 7)
        self.assertEqual(cell_width('e\u0301'), 1)

    def test_table_borders_align_with_chinese(self):
        result = table(['城市', '生产'], [['开罗', '建造者'], ['Washington', '侦察兵']])
        self.assertEqual(len({cell_width(line) for line in result.splitlines()}), 1)

    def test_narrow_tables_preserve_all_columns(self):
        result = table(['ID', '金币', '信仰', '科技', '文化'], [['65536', '10.1', '20.2', '30.3', '40.4']], Display(30))
        for value in ['金币', '信仰', '科技', '文化', '10.1', '20.2', '30.3', '40.4']:
            self.assertIn(value, result)
        self.assertTrue(all(cell_width(line) <= 30 for line in result.splitlines()))

    def test_copyable_ids_survive_collapsed_padding_and_ratio_columns(self):
        headers = ['ID', '单位', '坐标', '移动力', '活动状态', '需指令', '生命值']
        rows = [['6619157', '苏迪曼', '66,32', '4/4', '待命', '是', '100/100'],
                ['7077910', '特里斯坦', '23,27', '1/1', '待命', '是', '100/100']]
        for width in (40, 80, 100, 140):
            for ascii_mode in (False, True):
                with self.subTest(width=width, ascii=ascii_mode):
                    result = table(headers, rows, Display(width, ascii=ascii_mode))
                    self.assertIn('6619157', result)
                    self.assertIn('7077910', result)
                    self.assertTrue(all(cell_width(line) <= width for line in result.splitlines()))

    def test_long_values_wrap_without_loss(self):
        result = table(['能力'], [['明' * 80]], Display(40))
        self.assertEqual(result.count('明'), 80)
        self.assertTrue(all(cell_width(line) <= 40 for line in result.splitlines()))

    def test_tables_expand_to_the_requested_terminal_width(self):
        result = table(
            ['名称', '内部类型', '费用', '详情'],
            [['市场', 'BUILDING_MARKET', '120', '金币 +3；贸易路线容量 +1']],
            Display(100),
        )
        self.assertTrue(result.splitlines())
        self.assertTrue(all(cell_width(line) == 100 for line in result.splitlines()))

    def test_wider_tables_give_prose_more_room(self):
        rows = [['市场', '区域：商业中心；金币 +3；贸易路线容量 +1；大商人点数 +1']]
        narrow = table(['名称', '详情'], rows, Display(40))
        wide = table(['名称', '详情'], rows, Display(100))
        self.assertLess(len(wide.splitlines()), len(narrow.splitlines()))
        self.assertTrue(all(cell_width(line) <= 40 for line in narrow.splitlines()))
        self.assertTrue(all(cell_width(line) <= 100 for line in wide.splitlines()))

    def test_ascii_borders(self):
        result = table(['City'], [['Cairo']], Display(ascii=True))
        self.assertTrue(result.startswith('+'))
        self.assertNotIn('┌', result)

    def test_terminal_control_characters_are_neutralized(self):
        self.assertNotIn('\x1b', plain('\x1b[2J开罗\n'))
        self.assertNotIn('\n', plain('开罗\n'))

    def test_records_preserve_equals_in_values(self):
        record = parse_records(['POLICY|name=卡|description=收益=10|other'])[0]
        self.assertEqual(record.fields['description'], '收益=10')
        self.assertEqual(record.values, ('other',))

    def test_single_details_are_key_value_tables(self):
        output = render_records(['UNIT_DETAIL|id=1|name=勇士|position=2,3|hp=100|moves=2'])
        self.assertIn('项目', output)
        self.assertIn('信息', output)
        self.assertIn('生命值', output)

    def test_empty_and_read_error_states(self):
        self.assertIn('暂无', render_records([]))
        self.assertIn('读取错误', render_records(['ERROR|missing method']))

    def test_unknown_fields_are_preserved(self):
        self.assertIn('new_field', render_records(['NEW|new_field=value']))

    def test_forced_color_and_plain_fallback(self):
        colored = table(['状态'], [['成功']], Display(80, color=True))
        plain_output = table(['状态'], [['成功']], Display(80, color=False))
        self.assertIn('\x1b[', colored)
        self.assertNotIn('\x1b[', plain_output)

    def test_forced_color_keeps_explicit_width_under_dumb_term(self):
        with patch.dict('os.environ', {'TERM': 'dumb'}, clear=True):
            output = table(['名称', '详情'], [['市场', '贸易路线容量 +1']], Display(120, color=True))
        plain_lines = [re.sub(r'\x1b\[[0-9;]*m', '', line) for line in output.splitlines()]
        self.assertTrue(all(cell_width(line) == 120 for line in plain_lines))

    def test_no_color_empty_value_does_not_disable_auto_color(self):
        tty = type('TTY', (), {'isatty': lambda self: True})()
        with patch('civ6_cli.rendering.sys.stdout', tty), patch.dict('os.environ', {'NO_COLOR': ''}, clear=True):
            self.assertTrue(Display.terminal(color='auto').color)
        with patch('civ6_cli.rendering.sys.stdout', tty), patch.dict('os.environ', {'NO_COLOR': '1'}, clear=True):
            self.assertFalse(Display.terminal(color='auto').color)

    def test_force_color_honors_zero_and_pipe_override(self):
        pipe = type('Pipe', (), {'isatty': lambda self: False})()
        with patch('civ6_cli.rendering.sys.stdout', pipe), patch.dict('os.environ', {'FORCE_COLOR': '1'}, clear=True):
            self.assertTrue(Display.terminal(color='auto').color)
        with patch('civ6_cli.rendering.sys.stdout', pipe), patch.dict('os.environ', {'FORCE_COLOR': '0'}, clear=True):
            self.assertFalse(Display.terminal(color='auto').color)

    def test_decision_records_keep_copyable_types_without_raw_field_wall(self):
        output = render_records([
            'PRODUCTION_UNIT|name=建造者|type=UNIT_BUILDER|cost=80|turns=4|requirements=无额外条件|moves=2|charges=3|effect=修建改良',
            'PRODUCTION_UNIT|name=勇士|type=UNIT_WARRIOR|cost=40|turns=2|requirements=无额外条件|combat=20|effect=近战单位',
        ], Display(80), title='城市生产与购买')
        self.assertIn('UNIT_BUILDER', output)
        self.assertIn('修建改良', output)
        self.assertNotIn('requirements', output)

    def test_multi_option_details_get_a_full_width_reading_block(self):
        output = render_records([
            'PURCHASE_GOLD|UNIT|name=建造者|cost=320|affordable=yes|details=可修建地块改良',
            'PURCHASE_GOLD|BUILDING|name=市场|cost=480|affordable=no|details=金币 +3；贸易路线容量 +1',
        ], Display(80))
        comparison, details = output.split('效果与条件', 1)
        self.assertNotIn('详情', comparison)
        self.assertIn('可修建地块改良', details)
        self.assertIn('贸易路线容量 +1', details)
        self.assertTrue(all(cell_width(line) <= 80 for line in output.splitlines()))

    def test_trade_route_columns_use_spare_width_without_wrapping_rows(self):
        output = table(
            ['目的城市', '文明', '目标坐标', '单程距离', '预计回合', '我方收益/回合', '对方收益/回合'],
            [
                ['京都', '日本', '(41,18)', '8', '24', '食3 产2 金4', '金2 科1'],
                ['日内瓦', '日内瓦', '(46,22)', '12', '36', '金5 科2 文1', '金3'],
            ],
            Display(100),
        )
        self.assertEqual(len(output.splitlines()), 4)
        self.assertTrue(all(cell_width(line) == 100 for line in output.splitlines()))


if __name__ == "__main__":
    unittest.main()
