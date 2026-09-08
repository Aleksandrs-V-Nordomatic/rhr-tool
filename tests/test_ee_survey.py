#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Asking for a window wider than the register will answer in one go.

The register cuts at five hundred rows and says nothing about it: the answer is a bare array
with no total and no next page, so a truncated window and a complete one are the same shape.
`_search` raises rather than handing back a short answer, which is right — but a raise ends the
run, and the caller was then left to guess a narrower window and ask again. A month of this
register was fetched as six weeks cut by hand for exactly that reason.

`survey` answers the cap instead: it splits and asks again until every piece fits, and it hands
back the requests it made so that "complete" can be checked rather than believed.

The stubs model the one behaviour that matters — the register returns at most `CAP` rows and
does not say when it stopped.
"""

import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ee_targets


def _date(text):
    return datetime.date(*(int(p) for p in text.split("-")))


def row(pid, revealed):
    return {"procurementId": pid, "procurementReferenceNr": str(pid),
            "procurementName": "T %s" % pid, "contractingAuthorityName": "B",
            "procProcessRevealDate": "%sT10:00:00.000+0300" % revealed,
            "procurementStatus": "11", "procurementProcessType": "LM",
            "procurementType": "T", "mainCpvName": "C"}


class Register(object):
    """A register publishing `per_day` notices a day, cutting every answer at the cap.

    It honours the one thing about this endpoint a caller has to get right: the range is
    exclusive at the start, so the day named as `Begin` is not in the answer.
    """

    def __init__(self, per_day):
        self.per_day = per_day
        self.asked = []

    def post_json(self, url, payload, **kw):
        criteria = payload["filter"]
        self.asked.append(criteria)
        first = _date(criteria["procurementProcessRevealDateBegin"][:10]) + datetime.timedelta(days=1)
        last = _date(criteria["procurementProcessRevealDateEnd"][:10])
        out, day = [], first
        while day <= last:
            for n in range(self.per_day):
                out.append(row("%s-%d" % (day.isoformat(), n), day.isoformat()))
            day += datetime.timedelta(days=1)
        return out[:ee_targets.CAP]          # the register cuts, and says nothing


class AWindowThatFitsIsAskedForOnce(unittest.TestCase):

    def test_one_request_and_one_slice(self):
        register = Register(per_day=10)
        found = ee_targets.survey("2026-08-01", "2026-08-07", register)
        self.assertEqual(found["requests"], 1)
        self.assertEqual(len(found["rows"]), 70)
        self.assertEqual(found["slices"], [{"from": "2026-08-01", "to": "2026-08-07",
                                            "rows": 70}])
        self.assertEqual(found["at_cap"], [])


class AWindowThatOverflowsIsSplitUntilItFits(unittest.TestCase):
    """The whole point: the caller asks for the month and does not have to know the rate."""

    def test_every_slice_comes_back_under_the_cap(self):
        register = Register(per_day=200)          # 4 days = 800 rows, well over the cap
        found = ee_targets.survey("2026-08-01", "2026-08-04", register)
        self.assertEqual(found["at_cap"], [])
        for piece in found["slices"]:
            self.assertLess(piece["rows"], ee_targets.CAP)

    def test_nothing_is_lost_and_nothing_is_counted_twice(self):
        register = Register(per_day=200)
        found = ee_targets.survey("2026-08-01", "2026-08-04", register)
        self.assertEqual(len(found["rows"]), 800)
        pids = [r["pid"] for r in found["rows"]]
        self.assertEqual(len(set(pids)), 800)

    def test_the_slices_tile_the_window_exactly(self):
        register = Register(per_day=200)
        found = ee_targets.survey("2026-08-01", "2026-08-04", register)
        covered = []
        for piece in found["slices"]:
            covered += ee_targets.days(piece["from"], piece["to"])
        self.assertEqual(covered, ee_targets.days("2026-08-01", "2026-08-04"))

    def test_a_month_asked_for_whole_still_comes_back_whole(self):
        # The shape that used to require six hand-cut weeks.
        register = Register(per_day=120)
        found = ee_targets.survey("2026-08-01", "2026-09-07", register)
        self.assertEqual(len(found["rows"]), 38 * 120)
        self.assertEqual(found["at_cap"], [])
        self.assertGreater(found["requests"], 1)


class ADayThatCannotBeSplitSaysSo(unittest.TestCase):
    """A single day at the cap is the register failing to answer, not a window to narrow.

    Returning a short day here would be the exact dishonesty this module exists to prevent:
    the rows past the cap are named nowhere, so nothing downstream could tell.
    """

    def test_it_raises_rather_than_returning_a_short_day(self):
        register = Register(per_day=ee_targets.CAP + 50)
        with self.assertRaises(ee_targets.Truncated) as caught:
            ee_targets.survey("2026-08-03", "2026-08-03", register)
        self.assertIn("2026-08-03", str(caught.exception))
        self.assertIn("cannot be asked for in pieces", str(caught.exception))

    def test_a_wide_window_holding_such_a_day_still_raises(self):
        register = Register(per_day=ee_targets.CAP + 50)
        with self.assertRaises(ee_targets.Truncated):
            ee_targets.survey("2026-08-01", "2026-08-08", register)


class WindowStillAnswersThePlainQuestion(unittest.TestCase):
    """Existing callers ask `window` and want a list; that did not change."""

    def test_it_returns_the_rows_and_splits_when_it_has_to(self):
        register = Register(per_day=200)
        rows = ee_targets.window("2026-08-01", "2026-08-04", register)
        self.assertIsInstance(rows, list)
        self.assertEqual(len(rows), 800)


if __name__ == "__main__":
    unittest.main()
