#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The reader: three ids, three populations, and the answer that must never be cached.

Everything here was measured against the live register on 4 September 2026. What is frozen
below is the part that would otherwise have to be rediscovered by somebody spending a morning
on a service that looks closed and is not.
"""

import os
import sys
import unittest
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ee_page


class FakeSession(object):
    """Answers whatever the test put at a URL, and remembers every URL it was asked for."""

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.asked = []

    def get_json(self, url, **kw):
        self.asked.append(url)
        for fragment, payload in self.answers.items():
            if fragment in url:
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise AssertionError("no fixture for %s" % url)


def use(session):
    """Point the module at a fake for one test, and put the real one back afterwards."""
    ee_page._SESSION[0] = session
    return session


class WhichPopulationARowBelongsTo(unittest.TestCase):
    """Three things arrive through one search and a reader asks a different question of each.

    So the kind is read off the row rather than stored on a card: a kind kept on a card is one
    more thing that can be wrong, and asking the register again is a request that returns what
    we already had.
    """

    def test_a_market_consultation_is_told_by_its_procedure(self):
        # `TU` is turu-uuring: the buyer publishes a DRAFT specification and asks for comments
        # before the tender exists. Answering it is a different action from bidding.
        self.assertEqual(ee_page.kind_of({"procurementProcessType": "TU",
                                          "procurementStatus": "11"}), "consultation")

    def test_a_system_open_for_entry_is_told_by_its_state(self):
        # State 14 is `liitumiseks avatud`. Purchases inside such a system are never
        # advertised again, so missing one is a channel missed rather than one tender.
        self.assertEqual(ee_page.kind_of({"procurementProcessType": "DP",
                                          "procurementStatus": "14"}), "door")

    def test_a_dps_procurement_that_is_not_open_for_entry_is_an_ordinary_tender(self):
        # `DP` alone is a purchase made INSIDE a system, which is a competition like any
        # other. Reading the procedure without the state would file it as a door.
        self.assertEqual(ee_page.kind_of({"procurementProcessType": "DP",
                                          "procurementStatus": "11"}), "tender")

    def test_everything_else_is_a_tender(self):
        for procedure in ("A", "LM", "VO", "MS", "SE", "G", "IK"):
            self.assertEqual(ee_page.kind_of({"procurementProcessType": procedure,
                                              "procurementStatus": "11"}), "tender")


class TheThirdId(unittest.TestCase):
    """One procurement has three numbers and they are not interchangeable.

    Ask the document side with the search's id and it answers that there is no such
    procurement — which reads like a withdrawn tender rather than like the wrong number.
    """

    def test_the_newest_version_is_the_one_the_documents_hang_off(self):
        use(FakeSession({"proc-versions": {"procVersionItems": [
            {"procurementOldId": 111, "startDate": "2026-08-01T10:00:00.000+0300"},
            {"procurementOldId": 222, "startDate": "2026-09-04T14:35:32.032+0300"},
        ]}}))
        self.assertEqual(ee_page.old_id("10739244")[0], 222)

    def test_a_procurement_the_register_does_not_have_is_refused_not_retried(self):
        # A real miss answers 404 PROCUREMENT_NOT_FOUND. A 500 is this register's catch-all
        # for a route it does not have, and means the question was wrong rather than the id.
        use(FakeSession({"proc-versions": urllib.error.HTTPError(
            "u", 404, "PROCUREMENT_NOT_FOUND", None, None)}))
        with self.assertRaises(ee_page.Refused):
            ee_page.old_id("1")

    def test_a_version_list_with_no_document_id_is_refused_rather_than_guessed(self):
        use(FakeSession({"proc-versions": {"procVersionItems": [{"activityCode": "X"}]}}))
        with self.assertRaises(ee_page.Refused):
            ee_page.old_id("1")


class TheCatalogue(unittest.TestCase):
    def setUp(self):
        use(FakeSession({"documents/general-info": {"procurementDocuments": [
            {"procurementDocumentOldId": 1, "name": "Tehniline kirjeldus",
             "fileName": "ts.pdf", "fileSize": 10, "documentTypeCode": "S",
             "visibilityCode": "PUBLIC", "statusCode": "PUBLISHED",
             "stampUpd": "2026-09-01T11:00:00.000+0300"},
            {"procurementDocumentOldId": 2, "name": "Sisemine",
             "fileName": "x.pdf", "fileSize": 20, "documentTypeCode": "I",
             "visibilityCode": "PRIVATE", "statusCode": "PUBLISHED"},
            {"procurementDocumentOldId": 3, "name": "Mustand",
             "fileName": "y.pdf", "visibilityCode": "PUBLIC", "statusCode": "DRAFT"},
        ]}}))

    def test_only_what_an_anonymous_caller_can_actually_get_counts_as_public(self):
        """Both halves matter, and each on its own lets a document through that is not there.

        A withheld document and an unpublished one are both listed in the catalogue and
        neither is in the archive, so counting either as public makes every such procurement
        report a gap between what was promised and what arrived — a gap that is not one.
        """
        public, withheld = ee_page.catalogue(999)
        self.assertEqual([d["title"] for d in public], ["Tehniline kirjeldus"])
        self.assertEqual(len(withheld), 2)

    def test_the_moment_a_document_last_moved_travels(self):
        # The closest this register comes to a buyer saying "I replaced this on the first".
        # Byte digests stay the floor; this is what lets an update name WHICH document moved.
        public, _ = ee_page.catalogue(999)
        self.assertEqual(public[0]["publish_date"], "2026-09-01T11:00:00.000+0300")


class TheDownloadAddressIsUsedOnceAndNeverKept(unittest.TestCase):
    """The one failure here that returns a WRONG result rather than an error.

    A second request with the same address is answered as though the documents were gone. So
    a caller must come back for a new address rather than reuse the one it holds, and nothing
    may cache it.
    """

    def test_every_call_asks_the_register_again(self):
        session = use(FakeSession({"documents-temp-url": {"value": "/filetransfer/a"}}))
        ee_page.package("1")
        ee_page.package("1")
        self.assertEqual(len(session.asked), 2)

    def test_a_relative_path_is_made_absolute_against_the_register(self):
        use(FakeSession({"documents-temp-url": {"value": "/filetransfer/client/shared/a"}}))
        self.assertEqual(ee_page.package("1"),
                         ee_page.BASE + "/filetransfer/client/shared/a")

    def test_a_procurement_with_no_package_is_refused_rather_than_downloaded_as_nothing(self):
        use(FakeSession({"documents-temp-url": {}}))
        with self.assertRaises(ee_page.Refused):
            ee_page.package("1")


class TheCodeIsTheFactAndTheWordIsTheCaption(unittest.TestCase):
    """Why this country's facts survive a comparison that another country's cannot.

    A portal that renders words moves ten display strings at once when it answers in the other
    language, and a diff over them reports ten amendments nobody made. Here the state is
    `"11"` and the procedure is `"LM"`. A code does not translate, so the comparison answers
    the question it was asked — and the words are looked up beside the code, never instead.
    """

    def setUp(self):
        ee_page._DOMAINS[("PROCUREMENT_STATE", "et")] = {"11": "alustatud"}
        ee_page._DOMAINS[("PROCEDURE_TYPE", "et")] = {"LM": "Lihthange"}
        ee_page._DOMAINS[("PROCUREMENT_TYPE", "et")] = {"E": "Ehitustööd"}
        self.addCleanup(ee_page._DOMAINS.clear)
        self.row = {"procurementId": 10739244, "procurementReferenceNr": "314707",
                    "procurementName": "Koolimaja rekonstrueerimine",
                    "contractingAuthorityName": "Kambja Vallavalitsus",
                    "procurementStatus": "11", "procurementProcessType": "LM",
                    "procurementType": "E", "mainCpvName": "Ehitustööd",
                    "procProcessSubmitDate": "2026-09-17T09:00:00.000+0300"}

    def test_both_travel_and_the_code_is_the_one_compared(self):
        out = ee_page.notice(self.row, {})
        self.assertEqual(out["status"], "11")
        self.assertEqual(out["status_text"], "alustatud")
        self.assertEqual(out["procedure"], "LM")
        self.assertEqual(out["procedure_text"], "Lihthange")
        # `changes.FACTS` compares `status` and `procedure`; it does not compare the captions,
        # so a classifier renamed in the register is not reported as an amendment.
        import changes
        self.assertIn("status", changes.FACTS)
        self.assertNotIn("status_text", changes.FACTS)

    def test_a_classifier_that_will_not_load_costs_a_caption_never_a_tender(self):
        ee_page._DOMAINS.clear()
        ee_page._DOMAINS[("PROCUREMENT_STATE", "et")] = {}
        ee_page._DOMAINS[("PROCEDURE_TYPE", "et")] = {}
        ee_page._DOMAINS[("PROCUREMENT_TYPE", "et")] = {}
        out = ee_page.notice(self.row, {})
        self.assertEqual(out["status"], "11")
        self.assertIsNone(out["status_text"])

    def test_the_classification_name_comes_from_the_row_and_the_code_from_the_detail(self):
        """The search row names the classification and never numbers it.

        So the gate reads the name — it is free — and the card quotes the code, which costs a
        request and is the only place one comes from.
        """
        out = ee_page.notice(self.row, {"cpv": ["45310000-3", "45311000-0"]})
        self.assertEqual(out["cpv_name"], "Ehitustööd")
        self.assertEqual(out["cpv_main"], "45310000-3")
        self.assertEqual(out["cpv_additional"], ["45311000-0"])

    def test_the_link_is_built_from_the_search_id_not_the_reference(self):
        # A link built from the reference number opens nothing, and one built from the
        # document id opens somebody else's tender.
        out = ee_page.notice(self.row, {})
        self.assertIn("10739244", out["link"])
        self.assertNotIn("314707", out["link"])

    def test_a_value_the_buyer_declared_confidential_is_not_a_missing_one(self):
        """Both leave the field empty and only one of them is a gap."""
        out = ee_page.notice(self.row, {"value": None, "value_classified": True})
        self.assertIsNone(out["value"])
        self.assertTrue(out["value_classified"])


if __name__ == "__main__":
    unittest.main()
