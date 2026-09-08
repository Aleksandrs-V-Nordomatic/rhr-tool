#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reading the vocabulary out of the documents rather than out of a title.

The terms decided what to fetch until 8 Sep 2026, from a title and a classification name,
because that is all this register's search row carries. Now the window arrives whole and the
same terms are applied to the text — where they can finally be right.

Two properties carry the weight here and both have a failure that looks like success.

The quote has to survive **exactly as the buyer wrote it**, because a card's evidence is
checked by searching the source file for that string byte for byte. A scan that stored the
folded, lower-cased comparison text would produce cards whose quotes are nowhere in any
document, and every one of them would look complete on screen.

And a document read with no hits has to be distinguishable from a document nobody read. The
first says "this says nothing"; the second says "we do not know". Collapsing them is how a
reader concludes a procurement is empty when the scan simply never ran.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ee_scan

TERMS = ("automaatika", "automaatikakilp", "hooneautomaatika", "nork vool", "bms")


class Home(object):
    """A procurement home with whatever documents the test decided."""

    def __init__(self, docs=None):
        self.path = tempfile.mkdtemp()
        if docs is not None:
            doc_dir = os.path.join(self.path, "doc")
            os.makedirs(doc_dir)
            for name, text in docs.items():
                with io.open(os.path.join(doc_dir, name), "w", encoding="utf-8") as fh:
                    fh.write(text)

    def close(self):
        shutil.rmtree(self.path, ignore_errors=True)


class TheQuoteIsTheBuyersOwnWording(unittest.TestCase):
    """The one property a card's evidence depends on."""

    def setUp(self):
        self.home = Home({"a.md": "Hoone kirjeldus\n"
                                  "3.2. Hooneautomaatika süsteem, KNX-põhine.\n"
                                  "Muu tekst\n"})
        self.addCleanup(self.home.close)

    def test_the_line_is_stored_unfolded_and_uncased(self):
        scan = ee_scan.scan_home(self.home.path, TERMS)
        quote = scan["documents"][0]["context"][0]["text"]
        self.assertEqual(quote, "3.2. Hooneautomaatika süsteem, KNX-põhine.")

    def test_the_quote_can_be_found_in_the_source(self):
        # The check a card actually undergoes: search the file for the string.
        scan = ee_scan.scan_home(self.home.path, TERMS)
        quote = scan["documents"][0]["context"][0]["text"]
        with io.open(os.path.join(self.home.path, "doc", "a.md"), encoding="utf-8") as fh:
            self.assertIn(quote, fh.read())

    def test_the_line_number_points_at_it(self):
        scan = ee_scan.scan_home(self.home.path, TERMS)
        self.assertEqual(scan["documents"][0]["context"][0]["line"], 2)


class TheLongestTermWins(unittest.TestCase):
    """`hooneautomaatika` and `automaatika` match the same position; one says more."""

    def test_the_longer_term_is_the_one_reported(self):
        home = Home({"a.md": "Hooneautomaatika süsteem\n"})
        self.addCleanup(home.close)
        scan = ee_scan.scan_home(home.path, TERMS)
        self.assertEqual(scan["documents"][0]["terms"], ["hooneautomaatika"])


class ReadAndSilentIsNotTheSameAsUnread(unittest.TestCase):

    def test_documents_with_no_hits_still_produce_a_result(self):
        home = Home({"a.md": "Teede rekonstrueerimine ja asfalteerimine\n"})
        self.addCleanup(home.close)
        scan = ee_scan.scan_home(home.path, TERMS)
        self.assertIsNotNone(scan)
        self.assertEqual(scan["hits"], 0)
        self.assertEqual(scan["documents_scanned"], 1)
        self.assertEqual(scan["documents_with_hits"], 0)

    def test_a_home_with_no_text_at_all_says_nothing_rather_than_zero(self):
        home = Home()                      # no doc/ directory: nothing was extracted
        self.addCleanup(home.close)
        self.assertIsNone(ee_scan.scan_home(home.path, TERMS))

    def test_no_vocabulary_configured_says_nothing(self):
        home = Home({"a.md": "Hooneautomaatika\n"})
        self.addCleanup(home.close)
        self.assertIsNone(ee_scan.scan_home(home.path, ()))


class TheFileStaysSmallEnoughToRead(unittest.TestCase):
    """A scan nobody can afford to open has reproduced the problem it was written to solve."""

    def setUp(self):
        self.home = Home({"a.md": "Automaatika rida\n" * 200})
        self.addCleanup(self.home.close)

    def test_the_quotes_are_capped(self):
        scan = ee_scan.scan_home(self.home.path, TERMS)
        self.assertEqual(len(scan["documents"][0]["context"]), ee_scan.CONTEXT_PER_DOCUMENT)

    def test_the_count_is_not_capped(self):
        # Capping the quotes must not cap the arithmetic: how often a term occurs is the
        # signal that orders the reading, and a truncated count would order it wrongly.
        scan = ee_scan.scan_home(self.home.path, TERMS)
        self.assertEqual(scan["hits"], 200)
        self.assertEqual(scan["term_counts"]["automaatika"], 200)

    def test_a_long_line_is_trimmed(self):
        home = Home({"a.md": "automaatika " + ("x" * 900) + "\n"})
        self.addCleanup(home.close)
        scan = ee_scan.scan_home(home.path, TERMS)
        self.assertLessEqual(len(scan["documents"][0]["context"][0]["text"]),
                             ee_scan.CONTEXT_CHARS)


class TheStrongestDocumentComesFirst(unittest.TestCase):
    """Ordering is the whole point: a reader opens the top of this list and stops."""

    def test_documents_are_sorted_by_hits(self):
        home = Home({"quiet.md": "Automaatika\n",
                     "loud.md": "Automaatika\n" * 5,
                     "silent.md": "Teede ehitus\n"})
        self.addCleanup(home.close)
        scan = ee_scan.scan_home(home.path, TERMS)
        self.assertEqual([d["doc"] for d in scan["documents"]],
                         ["doc/loud.md", "doc/quiet.md", "doc/silent.md"])


class WhatTheDayCarries(unittest.TestCase):
    """The summary rides in the day's files, which are read before anything is downloaded."""

    def test_the_summary_is_small_and_says_the_useful_part(self):
        home = Home({"a.md": "Hooneautomaatika ja BMS\n"})
        self.addCleanup(home.close)
        summary = ee_scan.summary(ee_scan.scan_home(home.path, TERMS))
        self.assertEqual(summary["documents_with_hits"], 1)
        self.assertEqual(summary["documents_scanned"], 1)
        self.assertIn("hooneautomaatika", summary["terms"])
        self.assertNotIn("context", summary)

    def test_no_scan_is_no_summary(self):
        self.assertIsNone(ee_scan.summary(None))


class ItLandsBesideTheTextItDescribes(unittest.TestCase):

    def test_scan_json_is_written_into_the_home(self):
        home = Home({"a.md": "Automaatikakilp\n"})
        self.addCleanup(home.close)
        scan = ee_scan.scan_home(home.path, TERMS)
        path = ee_scan.write(home.path, scan)
        self.assertTrue(os.path.isfile(path))
        with io.open(path, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["schema"], "scan/1")

    def test_nothing_to_say_writes_no_file(self):
        home = Home()
        self.addCleanup(home.close)
        self.assertIsNone(ee_scan.write(home.path, None))
        self.assertFalse(os.path.exists(os.path.join(home.path, "scan.json")))


if __name__ == "__main__":
    unittest.main()
