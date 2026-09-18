import unittest

from civ6_cli.game import (City, KnownPlayer, PlayerStatus, Unit, read_cities,
                           read_status, read_units, read_visible_entities)
from civ6_cli.reports import bounded_int


class FakeConnection:
    def __init__(self, lines):
        self.lines = lines

    def execute_read_lines(self, _lua, **_kwargs):
        return self.lines


class DataModelTests(unittest.TestCase):
    def test_models_hold_typed_values(self):
        status = PlayerStatus(1, 0, "China", "Qin", 10.0, 2.0, 1.0, 0.0, 1, 2)
        unit = Unit(9, "Warrior", "UNIT_WARRIOR", 2, 3, 2, 2, 100, 100)
        city = City(4, "Beijing", 5, 6, 1)
        player = KnownPlayer(0, "China", "Qin", True)
        self.assertEqual((status.turn, unit.x, city.population, player.is_local), (1, 2, 1, True))

    def test_unit_parser_accepts_ten_field_wire_row(self):
        connection = FakeConnection(["UNIT|7|Warrior|UNIT_WARRIOR|12|34|2|2|100|100"])
        units = read_units(connection)
        self.assertEqual(len(units), 1)
        self.assertEqual((units[0].id, units[0].name, units[0].x), (7, "Warrior", 12))

    def test_city_parser_accepts_six_field_wire_row(self):
        connection = FakeConnection(["CITY|2|Beijing|7|8|5"])
        cities = read_cities(connection)
        self.assertEqual(len(cities), 1)
        self.assertEqual((cities[0].id, cities[0].name, cities[0].population), (2, "Beijing", 5))

    def test_status_accepts_legacy_and_active_turn_records(self):
        line = 'STATUS|96|0|Arabia|Saladin|513.6|41.5|23.2|337.4|3|6'
        self.assertTrue(read_status(FakeConnection([line])).is_turn_active)
        self.assertFalse(read_status(FakeConnection([line+'|no'])).is_turn_active)

    def test_visible_foreign_units_and_revealed_cities_are_typed(self):
        connection = FakeConnection([
            'VISIBLE_UNIT|63|野蛮人|4|散兵|UNIT_SKIRMISHER|31|21|80|100',
            'KNOWN_CITY|2|日本|65540|京都|54|31|no',
        ])
        units, cities = read_visible_entities(connection)
        self.assertEqual((units[0].owner, units[0].name, units[0].hp), ('野蛮人', '散兵', 80))
        self.assertEqual((cities[0].owner, cities[0].name, cities[0].visible), ('日本', '京都', False))

    def test_bounded_int_rejects_invalid_or_unsafe_template_values(self):
        self.assertEqual(bounded_int("4", name="radius", minimum=0, maximum=5), 4)
        with self.assertRaises(ValueError):
            bounded_int("0; os.execute('x')", name="x", minimum=-200, maximum=200)
        with self.assertRaises(ValueError):
            bounded_int("6", name="radius", minimum=0, maximum=5)
