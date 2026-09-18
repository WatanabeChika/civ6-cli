import unittest

from civ6_cli.game import PlayerStatus
from civ6_cli.overview import progress_text, read_overview, render_overview
from civ6_cli.rendering import Display
from civ6_cli.rendering import cell_width


STATUS = 'STATUS|96|0|阿拉伯|萨拉丁|513.6|41.5|23.2|337.4|1|1|yes'
SUMMARY = [
    'FINANCE|income=40.2|maintenance=14|net=26.2|faith_per_turn=39.1|score=196',
    'RESEARCH|kind=tech|name=建造|progress=79.4|cost=160|turns=2|boosted=no',
    'RESEARCH|kind=civic|name=封建主义|progress=129.9|cost=300|turns=8|boosted=yes',
    'CITY_SUMMARY|id=65536|name=开罗|position=31,24|population=8|production=21.6|producing=水磨|progress=49|cost=80|turns=1|housing=10|amenities=3|amenities_needed=4|amenities_surplus=-1|growth_turns=6',
    'SNAPSHOT_ERA|name=中世纪|score=48|dark=64|golden=78',
    'STAMP|turn=96|player=0',
]


class SnapshotConnection:
    def __init__(self, summaries=None):
        self.summaries = summaries or [SUMMARY]
        self.summary_reads = 0

    def execute_read_lines(self, lua, **kwargs):
        if "'STATUS'" in lua:
            return [STATUS]
        if "'UNIT'" in lua:
            return ['UNIT|7|勇士|UNIT_WARRIOR|31|24|2|2|100|100']
        if 'NOTIFICATION_COUNT|' in lua:
            return ['NOTIFICATION|type=NOTIFICATION_CHOOSE_TECH|blocking=yes|message=选择研究', 'NOTIFICATION_COUNT|1']
        if "'STAMP|turn='" in lua:
            self.summary_reads += 1
            return self.summaries[min(self.summary_reads - 1, len(self.summaries) - 1)]
        raise AssertionError('unexpected query')


class OverviewTests(unittest.TestCase):
    def test_snapshot_keeps_balances_and_yields_separate(self):
        snap = read_overview(SnapshotConnection())
        self.assertEqual(snap.status.gold, 513.6)
        self.assertEqual(snap.finance['net'], '26.2')
        self.assertEqual(snap.status.faith, 337.4)
        self.assertEqual(snap.finance['faith_per_turn'], '39.1')

    def test_research_and_city_progress_are_typed(self):
        snap = read_overview(SnapshotConnection())
        self.assertEqual((snap.research[1].cost, snap.research[1].turns), (300, 8))
        self.assertEqual((snap.cities[0].progress, snap.cities[0].cost), (49, 80))
        self.assertEqual((snap.cities[0].amenities_needed, snap.cities[0].amenities_surplus), (4, -1))
        self.assertTrue(snap.research[1].boosted)

    def test_snapshot_retries_when_turn_changes(self):
        changed = SUMMARY[:-1] + ['STAMP|turn=97|player=0']
        connection = SnapshotConnection([changed, SUMMARY])
        self.assertEqual(read_overview(connection).status.turn, 96)
        self.assertEqual(connection.summary_reads, 2)

    def test_snapshot_rejects_repeated_turn_change(self):
        changed = SUMMARY[:-1] + ['STAMP|turn=97|player=0']
        with self.assertRaisesRegex(ValueError, '发生变化'):
            read_overview(SnapshotConnection([changed]))

    def test_snapshot_rejects_player_change(self):
        changed = SUMMARY[:-1] + ['STAMP|turn=96|player=1']
        with self.assertRaises(ValueError):
            read_overview(SnapshotConnection([changed]))

    def test_missing_stamp_preserves_interface_error(self):
        with self.assertRaisesRegex(ValueError, 'missing API'):
            read_overview(SnapshotConnection([['ERROR|missing API']]))

    def test_unknown_optional_fields_are_not_zero(self):
        changed = [s.replace('faith_per_turn=39.1', 'faith_per_turn=?').replace('progress=49', 'progress=?') for s in SUMMARY]
        snap = read_overview(SnapshotConnection([changed]))
        self.assertIsNone(snap.cities[0].progress)
        self.assertIn('未知', render_overview(snap))

    def test_empty_production_adds_warning(self):
        changed = [s.replace('producing=水磨', 'producing=none') for s in SUMMARY]
        self.assertIn('开罗', ' '.join(read_overview(SnapshotConnection([changed])).warnings))

    def test_negative_gold_adds_warning(self):
        changed = [s.replace('net=26.2', 'net=-4.0') for s in SUMMARY]
        self.assertIn('金币净收入为负', ' '.join(read_overview(SnapshotConnection([changed])).warnings))

    def test_roster_mismatch_adds_warning(self):
        changed = [s for s in SUMMARY if not s.startswith('CITY_SUMMARY')]
        self.assertIn('不一致', ' '.join(read_overview(SnapshotConnection([changed])).warnings))

    def test_render_has_requested_sections(self):
        output = render_overview(read_overview(SnapshotConnection()), Display(80))
        self.assertNotIn('单位概览', output)
        for section in ('帝国产出', '研究进度', '城市生产', '城市发展', '通知', '选择研究', '+26.2', '513.6', '+39.1', '337.4', '封建主义', '-1.0'):
            self.assertIn(section, output)

    def test_progress_clamps_and_unknown_is_explicit(self):
        self.assertIn('100%', progress_text(200, 100, Display()))
        self.assertEqual(progress_text(None, None, Display()), '未知')
        self.assertIn('#', progress_text(50, 100, Display(ascii=True)))

    def test_status_respects_eighty_column_layout(self):
        output = render_overview(read_overview(SnapshotConnection()), Display(80))
        self.assertTrue(all(cell_width(line) <= 80 for line in output.splitlines()))
