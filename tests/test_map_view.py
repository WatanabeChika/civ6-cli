import unittest

from civ6_cli.map_view import MapArea, hex_distance, map_lua, read_map, render_map, tile_glyph
from civ6_cli.records import parse_records
from civ6_cli.rendering import Display, cell_width


def fixture(x=10, y=10, radius=2):
    lines = []
    for ty in range(y-radius, y+radius+1):
        for tx in range(x-radius, x+radius+1):
            if hex_distance(x, y, tx, ty) <= radius:
                lines.append(f'MAP_TILE|position={tx},{ty}|layout_x={tx}|layout_y={ty}|visibility=visible|terrain=TERRAIN_GRASS|hills=no|resource=none|city_name=none')
    return MapArea(x, y, radius, parse_records(lines))


class MapTests(unittest.TestCase):
    def test_hex_ring_tile_counts(self):
        for radius in range(6):
            self.assertEqual(len(fixture(radius=radius).tiles), 1+3*radius*(radius+1))

    def test_even_row_neighbours(self):
        neighbours = [(10,11), (11,10), (10,9), (9,9), (9,10), (9,11)]
        self.assertTrue(all(hex_distance(10,10,x,y) == 1 for x,y in neighbours))
        self.assertEqual(hex_distance(10,10,11,11), 2)

    def test_odd_row_neighbours(self):
        self.assertEqual(hex_distance(10,11,11,10), 1)
        self.assertEqual(hex_distance(10,11,9,10), 2)

    def test_map_coordinates_center_and_parity(self):
        output = render_map(fixture(radius=1), Display(100))
        self.assertIn('10,10', output)
        self.assertIn('@', output)
        row = next(line for line in output.splitlines() if '/9,11' in line)
        self.assertTrue(row.startswith('         /'))
        self.assertLess(output.index('/9,11'), output.index('/9,9'))

    def test_glyph_does_not_disclose_unexplored_data(self):
        glyph, _ = tile_glyph({'visibility':'unexplored', 'city_name':'Secret', 'resource':'IRON'}, Display(), True)
        self.assertEqual(glyph, '??')

    def test_fog_glyph_has_no_live_entities(self):
        glyph, _ = tile_glyph({'visibility':'fog', 'terrain':'TERRAIN_GRASS', 'city_name':'Secret', 'resource':'IRON', 'other_units':'yes'}, Display(), False)
        self.assertIn('~', glyph)
        self.assertNotIn('!', glyph)
        self.assertNotIn('C', glyph)
        self.assertNotIn('R', glyph)
        centered, _ = tile_glyph({'visibility':'fog', 'terrain':'TERRAIN_GRASS'}, Display(), True)
        self.assertIn('@', centered)

    def test_glyph_width_fits_hex(self):
        fields = {'visibility':'visible', 'terrain':'TERRAIN_GRASS', 'city_name':'开罗', 'resource':'IRON',
                  'own_units':'yes', 'district_name':'市中心', 'improvement_name':'矿山', 'river':'yes'}
        glyph, _ = tile_glyph(fields, Display(), True)
        for marker in ('C', 'U', 'R', 'D', 'I', '≈', '@'):
            self.assertIn(marker, glyph)
        self.assertLessEqual(cell_width(glyph), 12)

    def test_wonders_camps_and_villages_have_distinct_markers(self):
        wonder, _ = tile_glyph({'visibility':'visible', 'terrain':'TERRAIN_GRASS', 'wonder_name':'金字塔'}, Display(), False)
        camp, _ = tile_glyph({'visibility':'visible', 'terrain':'TERRAIN_GRASS', 'site':'barbarian_camp', 'improvement_name':'蛮族哨站'}, Display(), False)
        village, _ = tile_glyph({'visibility':'visible', 'terrain':'TERRAIN_GRASS', 'site':'tribal_village', 'improvement_name':'部落村庄'}, Display(), False)
        self.assertIn('W', wonder)
        self.assertIn('B', camp)
        self.assertIn('V', village)
        self.assertNotIn('I', camp + village)

    def test_narrow_map_keeps_all_coordinates(self):
        area = fixture(radius=3)
        output = render_map(area, Display(40))
        self.assertIn('地图分栏', output)
        for tile in area.tiles:
            self.assertIn(tile.fields['position'], output)
        for line in output.splitlines():
            if line.lstrip().startswith(('/', '\\', '_', '-')):
                self.assertLessEqual(cell_width(line), 40)

    def test_default_radius_fits_eighty_columns_without_a_tail_band(self):
        output = render_map(fixture(radius=2), Display(80))
        self.assertNotIn('地图分栏', output)
        for line in output.splitlines():
            self.assertLessEqual(cell_width(line), 80)

    def test_color_is_opt_in(self):
        self.assertNotIn('\x1b[', render_map(fixture(radius=0)))
        self.assertIn('\x1b[', render_map(fixture(radius=0), Display(color=True)))

    def test_query_rejects_lua_injection_and_bad_radius(self):
        for args in [('0; print(1)', 0, 2), (0, 0, 6), (-1, 0, 2)]:
            with self.assertRaises(ValueError):
                map_lua(*args)

    def test_query_has_wrap_visibility_and_prerequisite_guards(self):
        lua = map_lua(0, 10, 2)
        for term in ('Map.IsWrapX', 'lx % w', 'vis:IsRevealed(index)', 'vis:IsVisible(index)', 'resource.PrereqTech', 'techs:HasTech', 'if visible then',
                     'GetWonderType', 'IsWonderComplete', 'GetAppeal', 'IMPROVEMENT_BARBARIAN_CAMP', 'IMPROVEMENT_GOODY_HUT'):
            self.assertIn(term, lua)
        for action in ('RequestOperation', 'RemoveAt', 'SetProduction', 'SetResearch'):
            self.assertNotIn(action, lua)
        self.assertIn("owner_name(unit_owner)", lua)

    def test_read_map_exposes_errors(self):
        class Connection:
            def execute_read_lines(self, *args, **kwargs):
                return ['ERROR|bad map coordinates']
        with self.assertRaisesRegex(ValueError, 'bad map coordinates'):
            read_map(Connection(), 100, 100)
