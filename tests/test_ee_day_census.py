#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The window's census has to survive the loop that fetches the window.

This is here because of a real failure on 8 Sep 2026. The census — the list of requests the
register was asked, which is the whole proof that the window arrived whole — is built after
the per-procurement loop from a variable assigned before it. A later change introduced a
second variable inside that loop under the same name, so by the time the census was built it
held the last procurement's document scan. The run died with `KeyError: 'requests'`.

Every unit test passed. They exercise `survey` and they exercise the scan, and neither runs
`run` from end to end, so nothing noticed that the two had been wired into the same name.
That is the shape this file covers: not whether either half works, but whether what the first
half computed is still intact when the second half has finished with it.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ee_day
import ee_fetch
import ee_scan
import ee_targets


def _row(pid):
    return {"pid": pid, "ref": "RHR:%s" % pid, "kind": "tender",
            "title": "T %s" % pid, "buyer": "B", "published": "2026-08-03",
            "deadline": None, "status": "11", "procedure": "LM", "work_kind": "T",
            "cpv_name": "C", "record": {}}


SURVEY = {
    "rows": [_row("1"), _row("2")],
    "slices": [{"from": "2026-08-01", "to": "2026-08-02", "rows": 1},
               {"from": "2026-08-03", "to": "2026-08-04", "rows": 1}],
    "cap": 500, "requests": 2, "at_cap": [],
}


def _fetched(row, out_root, kind=None, **kw):
    home = os.path.join(out_root, "tenders", row["pid"])
    os.makedirs(home, exist_ok=True)
    return {"state": {"pid": row["pid"]}, "documents": 1, "withheld": [], "uncatalogued": [],
            "bytes": 10, "deadline": None, "value": None, "cpv_main": None,
            "index": {"documents": [{"changed_at": None}]}}


class TheCensusSurvivesTheFetchLoop(unittest.TestCase):

    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.out, True)
        for module, name, stub in (
            (ee_targets, "survey", lambda *a, **k: dict(SURVEY)),
            (ee_fetch, "fetch", _fetched),
            # The scan returns a dict shaped like a real one. The bug this file exists for
            # was the scan's own result overwriting the survey's, so a stub that returned
            # None would have passed even before the fix.
            (ee_scan, "scan_home", lambda home, terms: {
                "schema": "scan/1", "documents": [], "hits": 3, "documents_scanned": 1,
                "documents_with_hits": 1, "terms": ["automaatika"],
                "term_counts": {"automaatika": 3}}),
            (ee_scan, "write", lambda home, scan: None),
        ):
            original = getattr(module, name)
            setattr(module, name, stub)
            self.addCleanup(setattr, module, name, original)

    def run_day(self):
        day, changes = ee_day.run("2026-08-01", self.out, date_to="2026-08-04")
        return day, changes

    def test_the_requests_the_register_was_asked_are_still_there(self):
        day, _ = self.run_day()
        self.assertEqual(day["discovery"]["requests"], 2)
        self.assertEqual(day["discovery"]["at_cap"], [])

    def test_the_slices_are_the_survey_s_and_not_a_procurement_s(self):
        day, _ = self.run_day()
        self.assertEqual(day["discovery"]["slices"], SURVEY["slices"])

    def test_what_the_register_named_is_counted_before_any_trimming(self):
        day, _ = self.run_day()
        self.assertEqual(day["discovery"]["discovered"], 2)

    def test_the_scan_lands_on_the_procurement_and_not_on_the_window(self):
        # The two live in different places on purpose, and putting either where the other
        # belongs is the failure this file was written after.
        day, changes = self.run_day()
        self.assertNotIn("hits", day["discovery"])
        self.assertEqual(changes["tenders"][0]["scan"]["hits"], 3)
        self.assertEqual(day["tenders"][0]["scan"]["documents_with_hits"], 1)

    def test_the_day_is_still_valid_json_on_disk(self):
        self.run_day()
        with open(os.path.join(self.out, "2026-08-04", "day.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["discovery"]["requests"], 2)


if __name__ == "__main__":
    unittest.main()
