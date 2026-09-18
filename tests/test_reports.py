import unittest

from civ6_cli.reports import (available_reports, city_detail_lua,
                              city_production_lua, run_report, unit_detail_lua)


class ReportCatalogueTests(unittest.TestCase):
    def test_common_clean_never_uses_locale_whitespace_on_utf8(self):
        from civ6_cli.reports import _COMMON
        self.assertNotIn('gsub("^%s+"', _COMMON)
        self.assertNotIn('gsub("%s+$"', _COMMON)

    def test_extended_read_only_reports_are_registered(self):
        names = {report.name for report in available_reports()}
        self.assertNotIn("builder-tasks", names)
        self.assertIn("blockers", names)
        self.assertIn("era", names)
        self.assertIn("great-works", names)

    def test_great_people_uses_game_effect_text_and_great_works(self):
        report = next(report for report in available_reports() if report.name == "great-people")
        for term in ("GetModifierTextKey", "GetModifierText", "GreatPersonIndividualActionModifiers",
                     "GreatPersonIndividualBirthModifiers", "GameInfo.GreatWorks", "great_works="):
            self.assertIn(term, report.lua)
        self.assertNotIn('"LOC_GREATPERSON_"', report.lua)

    def test_city_detail_reports_amenity_surplus_and_buildings_by_district(self):
        lua = city_detail_lua(65536)
        for term in ("GetAmenitiesNeeded", "amenities_surplus=", "GetBuildingsAtLocation", "buildings=",
                     "GetFreePower", "GetRequiredPower", "WONDER|", "IsWonderComplete"):
            self.assertIn(term, lua)

    def test_economy_victory_envoys_and_spies_use_detailed_apis(self):
        reports = {report.name: report.lua for report in available_reports()}
        for term in ("GetResourceImportPerTurn", "GetUnitResourceDemandPerTurn",
                     "GetPowerResourceDemandPerTurn", "net_change="):
            self.assertIn(term, reports["economy"])
        self.assertIn("GetTouristsTo", reports["victory"])
        self.assertNotIn("GetTourism()", reports["victory"])
        for term in ("GetReligionInMajorityOfCities", "GetReligionTypeCreated",
                     "Game.GetReligion():GetName", "majority_religion=", "religion_founder="):
            self.assertIn(term, reports["victory"])
        self.assertIn("GetTokensToGive", reports["city-states"])
        for term in ("GameInfo.UnitOperations", "GetSpyOperationEndTurn", "GetTimeToComplete"):
            self.assertIn(term, reports["spies"])

    def test_great_works_and_production_have_requested_details(self):
        great_works = next(report.lua for report in available_reports() if report.name == "great-works")
        for term in ("GetNumGreatWorkSlots", "GetGreatWorkInSlot", "GetGreatWorkDataFromIndex",
                     "GREAT_WORK_SLOT|", "GREAT_WORK_SUMMARY|"):
            self.assertIn(term, great_works)
        production = city_production_lua(65536)
        for term in ("PRODUCTION_UNIT|", "PRODUCTION_BUILDING|", "PRODUCTION_DISTRICT|",
                     "PRODUCTION_PROJECT|", "Building_YieldChanges", "BuildingPrereqs",
                     "PURCHASE_GOLD", "PURCHASE_FAITH", "CanStartCommand", "GetPurchaseCost",
                     "|type=", "|is_wonder="):
            self.assertIn(term, production)

    def test_unit_detail_reports_persistent_activity(self):
        lua = unit_detail_lua(7)
        for term in ("UnitManager.GetActivityType", "unit:IsReadyToMove", "|activity=", "|needs_orders="):
            self.assertIn(term, lua)

    def test_resource_report_filter_is_applied_after_fixed_query(self):
        class Connection:
            def execute_read_lines(self, *_args, **_kwargs):
                return ["RESOURCE|鱼|position=1,2", "RESOURCE|鲸鱼|position=3,4",
                        "RESOURCE|铁|position=5,6", "RESOURCE_COUNT|3"]

        self.assertEqual(run_report(Connection(), "resources", "鱼"),
                         ["RESOURCE|鱼|position=1,2", "RESOURCE|鲸鱼|position=3,4", "RESOURCE_COUNT|2"])
        with self.assertRaisesRegex(ValueError, "不支持筛选"):
            run_report(Connection(), "economy", "鱼")

    def test_era_query_handles_hashed_game_speed(self):
        era = next(report for report in available_reports() if report.name == "era")
        self.assertIn("GameConfiguration.MakeHash", era.lua)
        self.assertIn("GAME_SPEED|", era.lua)


if __name__ == "__main__":
    unittest.main()
