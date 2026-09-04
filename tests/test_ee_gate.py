#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The gate, given the two texts this register actually hands it.

Everywhere else in this family the gate reads a title. Here it reads a title and the Estonian
name of the classification the buyer chose, and it has nothing else: the search row's
description field comes back empty on every row the register serves, and the classification
CODE is not in the row at all.

That puts the whole weight on the word list, which is why the folding below is not a detail.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import policy


def rules(**fields):
    fields.setdefault("recall_title_terms", ["automaatika"])
    return policy.load_policy(json.dumps(fields))


class TheGateReadsTwoTexts(unittest.TestCase):
    def test_the_classification_recalls_a_tender_whose_title_says_nothing(self):
        """The common shape: three words of title, and then a precise classification.

        A buyer writes "Aamse ja Nihka küla, KIRI" and classifies the purchase exactly. Read
        the title alone and the tender is gone before a byte moves.
        """
        kept = not policy.outside_scope(
            {"title": "Aamse ja Nihka küla, KIRI", "cpv_name": "Hooneautomaatika paigaldus"},
            rules())
        self.assertTrue(kept)

    def test_an_excluded_word_in_either_text_still_excludes(self):
        pol = rules(hard_exclude_title_terms=["asfalt"])
        self.assertTrue(policy.outside_scope(
            {"title": "Tee asfalteerimine", "cpv_name": "Hooneautomaatika"}, pol))
        self.assertTrue(policy.outside_scope(
            {"title": "Hooneautomaatika", "cpv_name": "Asfaltkatte tööd"}, pol))

    def test_a_procurement_with_no_text_at_all_is_fetched(self):
        """Missing signal fails toward fetching, and that direction is the whole point.

        A needless download costs minutes. A tender dropped in silence costs a deal, and
        nothing anywhere reports it.
        """
        self.assertFalse(policy.outside_scope({"title": None, "cpv_name": None}, rules()))


class ShortTermsAreOnlySafeBecauseTheTextIsFolded(unittest.TestCase):
    """A recall list for this language needs entries like ` ats `, ` kv ` and ` vk `.

    Each is written with spaces around it precisely so it cannot match inside a longer word —
    ` kv ` must not fire on `kvaliteet`. That only works if the text is spaced the same way.
    Both failures below are silent and both drop tenders.
    """

    def test_punctuation_does_not_hide_an_abbreviation(self):
        pol = rules(recall_title_terms=[" ats "])
        for title in ("ATS, hooldus", "Hoone (ATS) vahetus", "ATS-i väljavahetamine"):
            with self.subTest(title=title):
                self.assertFalse(policy.outside_scope({"title": title}, pol))

    def test_a_term_at_the_very_start_or_end_still_matches(self):
        pol = rules(recall_title_terms=[" ats "])
        self.assertFalse(policy.outside_scope({"title": "ATS"}, pol))

    def test_a_short_term_still_refuses_to_match_inside_a_word(self):
        pol = rules(recall_title_terms=[" kv "])
        self.assertTrue(policy.outside_scope({"title": "Kvaliteedijuhtimine"}, pol))

    def test_estonian_letters_survive_the_folding(self):
        # A hand-written character class is where somebody forgets a letter, and the letter
        # they forget splits a word in half and stops its term matching.
        self.assertEqual(policy.fold("Küte, ventilatsioon ja jahutus"),
                         " küte ventilatsioon ja jahutus ")

    def test_empty_stays_empty_so_the_caller_can_tell(self):
        # Padding a blank string would make it two spaces and therefore truthy, and the gate
        # would answer "your terms are not in this text" for a text that does not exist.
        self.assertEqual(policy.fold(None), "")
        self.assertEqual(policy.fold("   "), "")


class WhatTheGateCannotDoHere(unittest.TestCase):
    """Said out loud, because the shape of the policy invites the opposite assumption.

    Code rules need codes, and the search row carries none. They are honoured wherever a code
    is already known — a watched procurement, a door already fetched — and are simply silent
    on a first sighting. A reader tuning the policy has to know that the words are doing all
    the work at this point in the run.
    """

    def test_a_code_exclusion_cannot_fire_on_a_search_row(self):
        pol = rules(hard_exclude_prefixes=["45"])
        row = {"title": "Automaatikatööd", "cpv_name": "Ehitustööd"}
        self.assertFalse(policy.outside_scope(row, pol))

    def test_the_same_exclusion_fires_once_a_code_is_known(self):
        pol = rules(hard_exclude_prefixes=["45"])
        self.assertTrue(policy.outside_scope(
            {"title": "Midagi muud", "cpv": ["45233000-9"]}, pol))


if __name__ == "__main__":
    unittest.main()
