#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Two things the kit promised and the code did not do, found by review on 8 Sep 2026.

**Parking was documented as still being dropped, and was not.** `outside_scope` answers True
both for a notice excluded by name and for one whose title merely carries none of the recall
words. While the terms decided what to fetch, one boolean was enough — both meant *do not
download*. Once the window began to be fetched whole, `ee_day` had only that one verdict and
therefore dropped nothing, so every parking notice was downloaded, delivered, and landed in a
ledger that has no code for it.

**The document scan was written and thrown away.** `ee_scan` writes `scan.json` into the
procurement's home on the runner; the delivery uploads a fixed list of files and that list did
not name it. The runner is destroyed when the job ends, so the only reader it exists for never
saw it. Nothing failed: the summary still rode in the day's files, so the step looked alive.

Both are the same shape of defect — a claim about behaviour that nobody executed — which is why
each test below is written to fail if its fix is reverted.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deliver_ee
import policy


def rules():
    return policy.load_policy(json.dumps({
        "recall_title_terms": ["automaatika", "hooneautomaatika"],
        "hard_exclude_title_terms": ["parkla", "parking"],
        "hard_exclude_prefixes": ["9134"],
        "override_prefixes": ["45310"],
    }))


def notice(title, cpv=None):
    return {"title": title, "cpv_name": None, "cpv_main": cpv}


class ExcludedIsNotTheSameAsUnmatched(unittest.TestCase):
    """The distinction the two answers had collapsed into one."""

    def setUp(self):
        self.policy = rules()

    def test_a_notice_excluded_by_name_says_so(self):
        self.assertTrue(policy.excluded(notice("Parkla ehitus Tartus"), self.policy))

    def test_a_notice_the_words_merely_missed_is_not_excluded(self):
        # The whole point. This one is outside the recall terms and must still be fetched,
        # because a title is not enough to know whether a procurement is worth reading.
        row = notice("Toitlustusteenus koolis")
        self.assertFalse(policy.excluded(row, self.policy))
        self.assertTrue(policy.outside_scope(row, self.policy))

    def test_a_matching_notice_is_neither(self):
        row = notice("Hooneautomaatika hooldus")
        self.assertFalse(policy.excluded(row, self.policy))
        self.assertFalse(policy.outside_scope(row, self.policy))

    def test_an_excluded_code_set_counts_as_excluded(self):
        self.assertTrue(policy.excluded(notice("Midagi muud", cpv="91341000-1"),
                                        self.policy))

    def test_an_override_code_rescues_it(self):
        # An override is read wherever its division sits; that behaviour must survive the
        # split, or the exclusions start eating work the caller asked to keep.
        self.assertFalse(policy.excluded(notice("Midagi muud", cpv="45310000-3"),
                                         self.policy))

    def test_no_policy_excludes_nothing(self):
        self.assertFalse(policy.excluded(notice("Parkla ehitus"), None))

    def test_outside_scope_still_answers_its_own_question(self):
        # The cheap sweep keeps exactly what it had: both shapes are outside scope.
        for title in ("Parkla ehitus Tartus", "Toitlustusteenus koolis"):
            self.assertTrue(policy.outside_scope(notice(title), self.policy), title)


class TheScanTravelsWithTheHome(unittest.TestCase):
    """A file left on the runner is a file nobody will ever read."""

    def test_scan_json_is_in_the_published_list(self):
        self.assertIn("scan.json", deliver_ee.FLAT)

    def test_it_is_published_when_the_home_has_one(self):
        import shutil
        import tempfile
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        with open(os.path.join(home, "procurement.json"), "w", encoding="utf-8") as fh:
            fh.write("{}")
        with open(os.path.join(home, "scan.json"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"schema": "scan/1", "hits": 3}))
        names = [name for name, _ in
                 deliver_ee.members(home, "1", "2026-09-08", "r", index={"schema": "index/1"})]
        self.assertIn("scan.json", names)

    def test_a_home_without_one_publishes_without_it(self):
        import shutil
        import tempfile
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        with open(os.path.join(home, "procurement.json"), "w", encoding="utf-8") as fh:
            fh.write("{}")
        names = [name for name, _ in
                 deliver_ee.members(home, "1", "2026-09-08", "r", index={"schema": "index/1"})]
        self.assertNotIn("scan.json", names)
        self.assertIn("procurement.json", names)


class TheDayDropsOnlyWhatWasRuledOutByName(unittest.TestCase):
    """The behaviour the review actually caught: parking reaching the ledger.

    Everything below runs `ee_day.run` with the fetch and the register stubbed, because that
    is the only level at which the defect was visible. `policy.excluded` being right does not
    help if the day never asks it, and for one release it did not.
    """

    def setUp(self):
        import shutil, tempfile
        import ee_fetch, ee_scan, ee_targets
        self.out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.out, True)

        rows = [
            {"pid": "1", "ref": "R1", "kind": "tender", "title": "Parkla ehitus Tartus",
             "buyer": "B", "published": "2026-09-07", "deadline": None, "status": "11",
             "procedure": "LM", "work_kind": "T", "cpv_name": "C", "record": {}},
            {"pid": "2", "ref": "R2", "kind": "tender", "title": "Toitlustusteenus koolis",
             "buyer": "B", "published": "2026-09-07", "deadline": None, "status": "11",
             "procedure": "LM", "work_kind": "T", "cpv_name": "C", "record": {}},
            {"pid": "3", "ref": "R3", "kind": "tender", "title": "Hooneautomaatika hooldus",
             "buyer": "B", "published": "2026-09-07", "deadline": None, "status": "11",
             "procedure": "LM", "work_kind": "T", "cpv_name": "C", "record": {}},
        ]

        def fetched(row, out_root, kind=None, **kw):
            home = os.path.join(out_root, "tenders", row["pid"])
            os.makedirs(home, exist_ok=True)
            return {"state": {"pid": row["pid"]}, "documents": 1, "withheld": [],
                    "uncatalogued": [], "bytes": 10, "deadline": None, "value": None,
                    "cpv_main": None, "index": {"documents": [{"changed_at": None}]}}

        for module, name, stub in (
            (ee_targets, "survey", lambda *a, **k: {"rows": [dict(r) for r in rows],
                                                    "slices": [], "cap": 500,
                                                    "requests": 1, "at_cap": []}),
            (ee_fetch, "fetch", fetched),
            (ee_scan, "scan_home", lambda home, terms: None),
            (ee_scan, "write", lambda home, scan: None),
        ):
            original = getattr(module, name)
            setattr(module, name, stub)
            self.addCleanup(setattr, module, name, original)

    def run_day(self, gate="label"):
        import ee_day
        return ee_day.run("2026-09-07", self.out, policy=json.dumps({
            "recall_title_terms": ["automaatika", "hooneautomaatika"],
            "hard_exclude_title_terms": ["parkla"],
        }), gate=gate)

    def test_parking_is_dropped_even_though_nothing_else_is(self):
        day, changes = self.run_day()
        dropped = [g["ref"] for g in changes["gated"]]
        self.assertEqual(dropped, ["R1"])

    def test_a_merely_unmatched_notice_is_still_fetched_and_labelled(self):
        day, changes = self.run_day()
        rows = {t["ref"]: t for t in changes["tenders"]}
        self.assertIn("R2", rows)
        self.assertEqual(rows["R2"]["recall"], "unmatched")

    def test_the_matching_one_arrives_matched(self):
        day, changes = self.run_day()
        rows = {t["ref"]: t for t in changes["tenders"]}
        self.assertEqual(rows["R3"]["recall"], "matched")

    def test_the_cheap_sweep_still_drops_both(self):
        day, changes = self.run_day(gate="drop")
        self.assertEqual(sorted(g["ref"] for g in changes["gated"]), ["R1", "R2"])


if __name__ == "__main__":
    unittest.main()
