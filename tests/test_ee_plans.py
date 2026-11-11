"""The two Estonian plans, read from files built to their shape, with no network and no drive.

Under test: the person columns never reach a record, a plan keeps one key from day to day, and
the diff tells a plan that went from a source that did not answer.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ee_plans

XML = b"""<ProcurementPlanOpenData><ProcurementPlans>
<ProcurementPlan><Year>2026</Year><ProcurerCode>1</ProcurerCode><ProcurerName>Amet</ProcurerName>
<TargetProcurerName>Kool</TargetProcurerName><TargetProcurerCode>2</TargetProcurerCode>
<Status>Avaldatud</Status><ReferenceNumber>HP26000001</ReferenceNumber>
<ProcurementName>Hooneautomaatika renoveerimine</ProcurementName>
<ProcurementDescription>BMS</ProcurementDescription><JointProcurement>Ei</JointProcurement>
<CentralProcurement>Ei</CentralProcurement><ProcurementCost>65000.00</ProcurementCost>
<ExpectedContractSigningDate>2026-06-01</ExpectedContractSigningDate><EuFunds>Ei</EuFunds>
<ResponsiblePersonEmail>someone@example.invalid</ResponsiblePersonEmail></ProcurementPlan>
</ProcurementPlans></ProcurementPlanOpenData>"""


def xlsx(rows):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Hanke nimetus", "Hankemenetluse liik", "Korraldav üksus", "Vastutav isik",
               "Vastutava isiku e-post", "Pakkumuse esitamine (eeldatav)"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


RKAS = xlsx([["Tartu Vangla hooneautomaatika renoveerimine", "OT3 (Lihthange)", "Osakond",
              "Mari Maasikas", "mari@example.invalid", "01.12.2026 13:00"]])


class Reading(unittest.TestCase):
    def test_the_register_plan_is_read_without_its_person(self):
        plan = ee_plans.rhr_plans(XML)[0]
        self.assertEqual(plan["key"], "RHR-PLAN:HP26000001")
        self.assertEqual(plan["cost"], 65000.0)
        self.assertNotIn("example.invalid", json.dumps(plan))

    def test_the_rkas_row_is_read_without_its_person_and_in_tallinn_time(self):
        plan = ee_plans.rkas_plans(RKAS)[0]
        self.assertEqual(plan["expected"], "2026-12-01T13:00:00+02:00")
        self.assertEqual(plan["expected_meaning"], "bid submission")
        self.assertNotIn("Maasikas", json.dumps(plan, ensure_ascii=False))
        self.assertNotIn("example.invalid", json.dumps(plan))

    def test_an_rkas_key_survives_spacing_and_case(self):
        again = xlsx([["TARTU  Vangla hooneautomaatika renoveerimine ", "OT3 (Lihthange)", "",
                       "", "", "01.12.2026 13:00"]])
        self.assertEqual(ee_plans.rkas_plans(RKAS)[0]["key"], ee_plans.rkas_plans(again)[0]["key"])


class Snapshot(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="ee-plans-")
        self.addCleanup(shutil.rmtree, self.out, ignore_errors=True)

    def served(self, failing=()):
        def get(url):
            if any(word in url for word in failing):
                raise OSError("no answer")
            return RKAS if "rkas" in url else XML
        return get

    def test_a_failed_source_is_named_and_costs_only_its_own_plans(self):
        snap = ee_plans.collect(self.out, "2026-11-11", get=self.served(failing=("rkas",)))
        self.assertIn("error", snap["sources"]["rkas"])
        self.assertEqual({p["source"] for p in snap["plans"]}, {"RHR"})
        self.assertTrue(os.path.exists(os.path.join(self.out, "EE", "plans", "2026-11-11",
                                                    "plans.json")))

    def test_the_diff_says_new_gone_and_moved(self):
        before = ee_plans.collect(self.out, "2026-11-10", get=self.served())
        now = json.loads(json.dumps(before))
        now["date"] = "2026-11-11"
        now["plans"][0]["cost"] = 70000.0
        now["plans"] = [p for p in now["plans"] if p["source"] != "RKAS"]
        now["plans"].append(dict(now["plans"][0], key="RHR-PLAN:HP26000002", name="Uus"))
        changes = ee_plans.diff(before, now)
        self.assertEqual([p["key"] for p in changes["new"]], ["RHR-PLAN:HP26000002"])
        self.assertEqual([g["source"] for g in changes["gone"]], ["RKAS"])
        self.assertEqual(changes["changed"][0]["moved"]["cost"], [65000.0, 70000.0])

    def test_a_source_that_did_not_answer_withdraws_nothing(self):
        before = ee_plans.collect(self.out, "2026-11-10", get=self.served())
        now = ee_plans.collect(self.out, "2026-11-11", get=self.served(failing=("rkas",)))
        self.assertEqual(ee_plans.diff(before, now)["gone"], [])

    def test_the_first_snapshot_announces_nothing_as_new(self):
        now = ee_plans.collect(self.out, "2026-11-11", get=self.served())
        changes = ee_plans.diff(None, now)
        self.assertTrue(changes["first_snapshot"])
        self.assertEqual(changes["new"], [])


if __name__ == "__main__":
    unittest.main()
