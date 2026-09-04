#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What a window means to this register, and the three ways it lies quietly.

Every assertion below was measured against the live register on 4 September 2026 and then
frozen here, because all three failures share one symptom: a 200, a well-formed answer, and
the wrong tenders. Nothing raises, nothing logs, and a morning of cards is silently wrong or
silently absent.

The stubs are deliberate. A test that asked the real register would be measuring Estonia's
publishing schedule rather than this code, and would go red on a public holiday.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ee_targets


class FakeSession(object):
    """Answers a search with whatever the test decided, and remembers what it was asked."""

    def __init__(self, rows):
        self.rows = rows
        self.sent = []

    def post_json(self, url, payload, **kw):
        self.sent.append(payload)
        return self.rows(payload) if callable(self.rows) else self.rows


def row(pid, revealed, ref=None, **extra):
    record = {"procurementId": pid, "procurementReferenceNr": ref or str(pid),
              "procurementName": "T %s" % pid, "contractingAuthorityName": "B",
              "procProcessRevealDate": "%sT10:00:00.000+0300" % revealed,
              "procurementStatus": "11", "procurementProcessType": "LM",
              "procurementType": "T", "mainCpvName": "C"}
    record.update(extra)
    return record


class TheWindowIsExclusiveAtTheStart(unittest.TestCase):
    """`Begin` is not included and `End` is.

    Measured: `Begin=2026-09-02, End=2026-09-03` returns the third and not the second, and
    `Begin=D, End=D` returns nothing at all. A caller reasoning by analogy with an inclusive
    range would ask for `Begin=D, End=D`, get an empty answer, deliver an empty day and call
    it complete — which reads exactly like a public holiday.
    """

    def test_the_day_before_is_what_gets_asked_for(self):
        session = FakeSession([row(1, "2026-09-04")])
        ee_targets.window("2026-09-04", "2026-09-04", session)
        criteria = session.sent[-1]["filter"]
        self.assertEqual(criteria["procurementProcessRevealDateBegin"],
                         "2026-09-03T00:00:00.000Z")
        self.assertEqual(criteria["procurementProcessRevealDateEnd"],
                         "2026-09-04T00:00:00.000Z")

    def test_a_range_shifts_only_its_beginning(self):
        session = FakeSession([row(1, "2026-09-02"), row(2, "2026-09-04")])
        ee_targets.window("2026-09-02", "2026-09-04", session)
        criteria = session.sent[-1]["filter"]
        self.assertEqual(criteria["procurementProcessRevealDateBegin"],
                         "2026-09-01T00:00:00.000Z")
        self.assertEqual(criteria["procurementProcessRevealDateEnd"],
                         "2026-09-04T00:00:00.000Z")

    def test_the_order_travels_because_without_it_the_register_refuses(self):
        # A body with no `orderBy` is answered with a 500, which reads like a broken route
        # rather than like a missing argument. It is not optional and never was.
        session = FakeSession([row(1, "2026-09-04")])
        ee_targets.window("2026-09-04", "2026-09-04", session)
        self.assertIn("orderBy", session.sent[-1])


class AFilterKeyItDoesNotKnowIsIgnored(unittest.TestCase):
    """The one failure this API produces that looks exactly like success.

    Measured: `procurementReferenceNr` — the name the ROWS use for the reference number — is
    not the name the FILTER uses. Asking with it does not fail; it returns the register's
    whole answer under a 200. A run watching one card would have fetched five hundred
    procurements and reported success.
    """

    def test_rows_outside_the_window_stop_the_run(self):
        session = FakeSession([row(1, "2026-09-04"), row(2, "2026-06-01")])
        with self.assertRaises(ee_targets.FilterIgnored) as raised:
            ee_targets.window("2026-09-04", "2026-09-04", session)
        self.assertIn("did not apply the window", str(raised.exception))

    def test_the_message_says_how_many_and_over_what(self):
        session = FakeSession([row(i, "2026-01-0%d" % (i % 9 + 1)) for i in range(1, 5)])
        with self.assertRaises(ee_targets.FilterIgnored) as raised:
            ee_targets.window("2026-09-04", "2026-09-04", session)
        self.assertIn("4 of 4", str(raised.exception))

    def test_a_state_filter_that_did_not_bite_stops_the_doors_read(self):
        session = FakeSession([row(1, "2026-09-04", procurementStatus="14"),
                               row(2, "2026-09-04", procurementStatus="11")])
        with self.assertRaises(ee_targets.FilterIgnored):
            ee_targets.doors(session)

    def test_an_answer_that_is_not_a_list_stops_the_run(self):
        session = FakeSession({"error": "something"})
        with self.assertRaises(ee_targets.FilterIgnored):
            ee_targets.window("2026-09-04", "2026-09-04", session)


class FiveHundredIsACapAndNothingSaysSo(unittest.TestCase):
    """The answer is a bare array with no total and no next page.

    So exactly five hundred rows means the answer was cut, and what it dropped is named
    nowhere. There is nothing honest to deliver from a truncated window, so it is raised
    rather than returned — unlike a target that failed, which the day can name in `lost`.
    """

    def test_the_cap_is_raised_not_returned(self):
        session = FakeSession([row(i, "2026-09-04") for i in range(ee_targets.CAP)])
        with self.assertRaises(ee_targets.Truncated):
            ee_targets.window("2026-09-04", "2026-09-04", session)

    def test_one_row_short_of_the_cap_is_an_ordinary_answer(self):
        session = FakeSession([row(i, "2026-09-04") for i in range(ee_targets.CAP - 1)])
        self.assertEqual(len(ee_targets.window("2026-09-04", "2026-09-04", session)),
                         ee_targets.CAP - 1)


class WhatAWindowReturns(unittest.TestCase):
    def test_a_procurement_named_twice_is_one_row(self):
        session = FakeSession([row(1, "2026-09-04"), row(1, "2026-09-04")])
        self.assertEqual(len(ee_targets.window("2026-09-04", "2026-09-04", session)), 1)

    def test_the_row_carries_what_the_gate_reads(self):
        session = FakeSession([row(1, "2026-09-04")])
        found = ee_targets.window("2026-09-04", "2026-09-04", session)[0]
        # The two texts the gate has before a byte moves, and nothing else it could use:
        # the register serves no description in a search row.
        self.assertEqual(found["title"], "T 1")
        self.assertEqual(found["cpv_name"], "C")

    def test_a_window_that_ends_before_it_begins_is_refused(self):
        with self.assertRaises(ValueError):
            ee_targets.window("2026-09-04", "2026-09-01", FakeSession([]))


class OneProcurementByTheNumberAPersonQuotes(unittest.TestCase):
    def test_the_filter_spelling_is_the_one_that_bites(self):
        session = FakeSession([row(10739244, "2026-09-04", ref="314707")])
        ee_targets.one("314707", session)
        self.assertIn("referenceNumber", session.sent[-1]["filter"])

    def test_a_board_key_is_accepted_as_it_is_written(self):
        session = FakeSession([row(10739244, "2026-09-04", ref="314707")])
        self.assertIsNotNone(ee_targets.one("RHR:314707", session))

    def test_rows_that_are_not_the_one_asked_for_are_a_miss(self):
        """The filter matches on more than equality, so a near answer is still a miss.

        A watched card reporting nothing is a hole somebody can see. A watched card reporting
        the WRONG tender is a card that quietly starts describing a different procurement.
        """
        session = FakeSession([row(1, "2026-09-04", ref="3147070")])
        self.assertIsNone(ee_targets.one("314707", session))


if __name__ == "__main__":
    unittest.main()
