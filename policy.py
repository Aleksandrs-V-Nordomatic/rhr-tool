#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""The recall gate: which notices are worth fetching, before a single byte moves.

WHY IT IS ITS OWN FILE. This is the one piece of judgement that is not about a country. A
CPV code means the same thing wherever it is filed, and the terms a caller recalls on are
their business rather than a portal's — so every country tool in this family runs the
identical rule, from a copy of this file, and none of them has to import another's driver
to get it.

WHAT THIS KNOWS ABOUT THE CALLER'S INTEREST: NOTHING — the same rule deliver_graph.py keeps
about its destination. The terms arrive in the environment, so this file names no industry,
no trade and no target, and a reader of this repository learns the shape of the filter
without learning what anyone points it at.
"""

import json
import os
import re


# THE ONE FILTER ALLOWED BEFORE A DOCUMENT EXISTS.
#
# A title is kept when it contains one of the caller's recall roots. Roots are matched as
# substrings rather than as whole words because the language this runs against inflects
# heavily; precision belongs to the later document-reading step, not to a title.
#
# One guard, and it fails toward fetching: no text at all means no evidence, so the notice is
# fetched.
#
# EXCLUSIONS WIN OVER RECALL, INCLUDING OVER A MATCHING TITLE, AND THAT IS DELIBERATE. This
# paragraph used to claim the opposite in the line above it -- that a classification code never
# vetoes a matching title -- while the code below did what it does now: `hard_exclude_prefixes`
# is tested BEFORE the recall terms and returns. The two sentences stood side by side for
# months. The code was right and the sentence was wrong, and it was settled by measurement
# rather than by preference.
#
# WHAT THE MEASUREMENT SAID. Both orders were run over 5 925 real Latvian notices spanning
# 9 June to 6 September 2026, against the live recall policy: they kept 2 147 each and
# disagreed about none of them. Only four notices in three months reached the contested branch
# at all -- and all four were car-park management systems, CPV 98351000 and 34926000, whose
# titles say `vadības sistēma`, control system, and match the recall terms perfectly. Dropping
# them is the entire reason those prefixes were written.
#
# So the rule that reads well is also the rule that is useless: a code exclusion that could not
# override a matching title could never drop anything, because a notice whose title does not
# match is dropped by the recall test anyway. `hard_exclude_prefixes` exists for exactly the
# notice that matches and is still not ours.
#
# WHICH PUTS THE WHOLE WEIGHT ON HOW NARROWLY A PREFIX IS WRITTEN, and that is the warning this
# paragraph is really for. An exclusion is absolute for a notice carrying no other code. Both
# live policies write theirs four to six digits long -- specific purchases, not divisions -- and
# that is why the branch fires four times a quarter instead of gutting the day. Measured on the
# same corpus, adding one two-digit division would silently drop, out of 2 147 kept notices:
#
#     45  construction works                    591
#     71  architecture and engineering          420
#     50  repair and maintenance services       204
#
# Those are the divisions our own work is filed under. Write a prefix that names a purchase,
# never one that names a division, and reach for `override_prefixes` before widening one.
#
# WHAT THIS KNOWS ABOUT THE CALLER'S INTEREST: NOTHING — the same rule deliver_graph.py
# keeps about its destination. The terms arrive in the environment, so this file names no
# industry, no trade and no target, and a reader of this repository learns the shape of the
# filter without learning what anyone points it at. An absent or unreadable policy means
# fetch everything, which is the only safe direction for a filter that failed to load:
# fetching too much costs time, and dropping silently costs a tender.
POLICY_ENV = "EE_POLICY"

# THE NAMES THIS TOOL DOES NOT READ, CHECKED RATHER THAN IGNORED. Every country tool in
# this family names its policy after its own country, and a deployment is set up by copying
# the last one that worked. An environment carrying only a sibling's name would load no
# policy at all here, and no policy means fetch everything -- a whole day drawn from a state
# register, reported as success. The one failure shape nobody catches is an empty morning
# that reads exactly like a quiet one, so a foreign name stops the run instead.
FOREIGN_POLICY_ENVS = ("EIS_POLICY", "LT_POLICY")


def load_policy(source=None):
    """The caller's recall policy, or None. None means no filter — fetch everything.

    `source` is JSON text, a path to a JSON file, or None to read `EE_POLICY` from the
    environment. Tests pass a fixture through it; production passes nothing and the
    environment answers, so no deployment's terms are ever committed here.
    """
    raw = source if source is not None else os.environ.get(POLICY_ENV)
    if source is None and not raw:
        stray = [name for name in FOREIGN_POLICY_ENVS if os.environ.get(name)]
        if stray:
            raise EnvironmentError(
                "%s is set but this tool reads %s. Rename it: honouring neither would fetch "
                "the whole day ungated and report success."
                % (", ".join(stray), POLICY_ENV))
    if not raw or not raw.strip():
        return None
    text = raw
    if not raw.lstrip().startswith("{"):              # not JSON, so treat it as a path
        try:
            with open(raw, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            return None
    try:
        policy = json.loads(text)
    except ValueError:
        return None                       # an unreadable policy must fail open, never drop all
    recall = tuple(t.casefold() for t in (policy.get("recall_title_terms") or ()))
    if not recall:
        return None                       # incomplete policy must fail open, never drop all
    return (recall,
            tuple(policy.get("hard_exclude_prefixes") or ()),
            tuple(t.casefold() for t in (policy.get("hard_exclude_title_terms") or ())),
            # CODES THAT SURVIVE THEIR OWN DIVISION. A purchase can carry a main code
            # inside an excluded division and nothing else — a buyer files it under the
            # service it is bought as rather than the thing it is — and 62% of live
            # procurements carry one code only. Without an override such a notice is
            # dropped before a byte moves, which is the one failure the exclusions are
            # least allowed to cause.
            tuple(policy.get("override_prefixes") or ()),
            # CODES THAT RECALL ON THEIR OWN, because a title is not always the better
            # signal. Recall was title-only, and a code could exclude or rescue from an
            # exclusion but never bring anything in — so a procurement whose title is vague
            # and whose code is exact was dropped before a byte moved. That shape is common:
            # a buyer writes three words and then classifies the purchase precisely, and the
            # gate could hear only the three words. Absent, this changes nothing.
            tuple(policy.get("recall_cpv_prefixes") or ()))

# THE TEXTS THE GATE READS, AND WHY THERE ARE TWO OF THEM HERE.
#
# A title is the obvious surface and in most countries it is the only one. This register
# publishes a second for free: `mainCpvName` — the Estonian name of the classification the
# buyer chose — and it is worth reading, because a buyer will often write a short and
# meaningless title and then classify the purchase precisely. The title says "Aamse ja Nihka
# küla, KIRI" and the classification says what is actually being bought.
#
# It matters more here than it would elsewhere: the search row carries no description at all
# (`shortDescription` is empty on every row the register serves) and no classification CODE,
# only its name. So these two texts are everything the gate has, and dropping one of them
# would put the whole weight on a title that buyers do not write for us.
TEXT_SURFACES = ("title", "name", "cpv_name")


# EVERY RUN OF PUNCTUATION BECOMES ONE SPACE, AND THE WHOLE STRING IS PADDED WITH ONE.
#
# This is what makes a SHORT term safe to write. A recall list for a language full of
# abbreviations needs entries like ` ats `, ` kv ` and ` vk `, and each of them is written
# with spaces around it precisely so it cannot match inside a longer word. That only works if
# the text is spaced the same way: without this, `KV,` and `(VK)` never match because of the
# punctuation, and a term at the very start or end of a title never matches because there is
# no space beyond it. Both failures are silent and both drop tenders.
#
# `[\W_]+` under Unicode keeps every letter and digit, Estonian ones included, and collapses
# everything else. It is deliberately not a named character class: a hand-written one has to
# list the language's letters, and the letter somebody forgets is the one that splits a word
# in half and stops a term matching it.
_SEPARATORS = re.compile(r"[\W_]+", re.UNICODE)


def fold(text):
    """One spelling of a text, so that a term written with spaces around it behaves.

    EMPTY STAYS EMPTY. Padding a blank string would make it two spaces and therefore truthy,
    and the caller reads emptiness as "no evidence, so fetch it". A gate that answered "this
    text contains none of your terms" for a notice with no text would fail CLOSED — the one
    direction this file is not allowed to fail in.
    """
    folded = _SEPARATORS.sub(" ", str(text or "")).casefold().strip()
    return " %s " % folded if folded else ""


def haystack(notice):
    """Everything the gate is allowed to read before a byte moves, folded for comparison."""
    parts = [str(notice.get(field) or "") for field in TEXT_SURFACES]
    return fold(" ".join(p for p in parts if p))


def cpv_codes(notice):
    """Every CPV code a notice carries, however the source spelled them."""
    codes = []
    raw = notice.get("cpv")
    if isinstance(raw, (list, tuple)):
        codes = [str(c.get("code", "")) if isinstance(c, dict) else str(c) for c in raw]
    elif raw:
        codes = [str(raw)]
    if notice.get("cpv_main"):
        codes.append(str(notice["cpv_main"]))
    return [c.strip() for c in codes if c and c.strip()]


def excluded(notice, policy):
    """Is this notice ruled out by name, rather than merely unmatched by the terms?

    TWO QUESTIONS THAT USED TO SHARE ONE ANSWER, AND THE COST OF THAT. `outside_scope`
    returns True both for a notice the caller excluded deliberately — parking, which is
    another brand's line of business — and for one whose title simply carries none of the
    recall words. Those are opposite statements: the first is "we know this is not ours",
    the second is "we have not looked". While the terms decided what to fetch, one boolean
    was enough, because both meant *do not download*.

    They stopped meaning the same thing on 8 Sep 2026, when the window began to be fetched
    whole and the terms became a label. A caller that wants to keep dropping the deliberate
    exclusions and stop dropping the unmatched needs to tell them apart, and could not: the
    Estonian kit said parking was still excluded, and in production nothing was, because
    `ee_day` had only the one verdict to act on.

    This answers the first question alone. `outside_scope` is unchanged and still answers
    the old one, so a caller that wants the cheap sweep keeps exactly what it had.
    """
    if not policy:
        return False
    exclude_prefixes, exclude_title_terms = policy[1], policy[2]
    override_prefixes = policy[3] if len(policy) > 3 else ()

    title = haystack(notice)
    if title and any(term in title for term in exclude_title_terms):
        return True

    codes = cpv_codes(notice)
    overridden = bool(override_prefixes) and any(c.startswith(override_prefixes)
                                                 for c in codes)
    return bool(codes and exclude_prefixes and not overridden
                and all(c.startswith(exclude_prefixes) for c in codes))


def outside_scope(notice, policy):
    """Should this notice be excluded before any documents are fetched?"""
    if not policy:
        return False
    # Older policies carry three fields; the override list is the fourth and optional.
    recall_terms, exclude_prefixes, exclude_title_terms = policy[:3]
    override_prefixes = policy[3] if len(policy) > 3 else ()
    recall_prefixes = policy[4] if len(policy) > 4 else ()

    if excluded(notice, policy):
        return True

    title = haystack(notice)
    codes = cpv_codes(notice)

    # A CODE CAN RECALL, AND IT IS ASKED BEFORE THE TITLE. The exclusions above still
    # bind — an excluded title term or an all-excluded code set has already returned — so
    # this widens what is fetched and can never drop anything the old gate kept.
    if recall_prefixes and any(c.startswith(recall_prefixes) for c in codes):
        return False

    if not title:
        return False                      # missing signal fails open
    return not any(term in title for term in recall_terms)
