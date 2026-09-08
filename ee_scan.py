#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Where the caller's vocabulary actually occurs, inside a procurement's documents.

WHY THIS EXISTS. The recall terms used to decide which procurements were worth fetching, and
they decided it from a title and a classification name, because that is all this register's
search row carries. That was measured and it was bad: over 1 Aug - 7 Sep 2026 it dropped 376 of
741 notices unread. So the window is fetched whole now — and the same terms, applied to the text
that actually contains the answer, become useful for the first time.

WHAT IT IS FOR. A reader with a whole window has more to open than it can read. This says which
documents are worth opening and where to look inside them, so that reading stays bounded without
anything being hidden. **The terms decide reading order, never existence**: a procurement with no
hit is still delivered, still judged and still gets a ledger record. `scope.md` decides what is
ours; this file only decides what to read first.

WHY IT MATCHES LINE BY LINE. `policy.fold` collapses punctuation and case so a short term written
with spaces around it behaves, and that is the right comparison — but it destroys offsets, so a
match in a folded blob cannot be pointed at. Folding one line at a time keeps the comparison and
keeps the original: the hit records the line as the buyer wrote it, which is what a card's quote
has to be copied from and what a check searches the source file for.

WHY THE COUNTS ARE CAPPED. A specification can say `automaatika` two hundred times. Two hundred
identical hits tell a reader nothing the first three did not, and a scan file nobody can afford to
read has reproduced the problem it was written to solve.
"""

import io
import json
import os
import re

import policy as policy_mod

# How many quoted lines are kept per document. Enough to see what kind of mention this is —
# a heading, a requirement, a line in a bill of quantities — and few enough that the whole
# scan stays small enough to read before deciding anything.
CONTEXT_PER_DOCUMENT = 8

# A line longer than this is a table row or a wall of prose; the quote is trimmed so one
# unlucky document cannot dominate the file. The original stays on disk either way.
CONTEXT_CHARS = 320


def matcher(terms):
    """One compiled alternation for the whole vocabulary, longest term first.

    Longest first matters: `automaatikakilp` and `automaatika` both match the same position,
    and the reader learns more from being told the longer one was there.
    """
    usable = sorted({t.strip() for t in terms if t and t.strip()}, key=len, reverse=True)
    if not usable:
        return None
    return re.compile("|".join(re.escape(t) for t in usable))


def scan_text(text, pattern):
    """Every line of one document that carries a term, with the line as it was written."""
    hits, counts = [], {}
    for number, line in enumerate(text.splitlines(), 1):
        folded = policy_mod.fold(line)
        if not folded:
            continue
        found = pattern.findall(folded)
        if not found:
            continue
        for term in found:
            counts[term] = counts.get(term, 0) + 1
        if len(hits) < CONTEXT_PER_DOCUMENT:
            quoted = line.strip()
            hits.append({"line": number,
                         "terms": sorted(set(found)),
                         # The buyer's own wording, untouched. A card's quote is located by
                         # searching the source file for exactly this, so tidying it here
                         # would break the one check that makes a card worth trusting.
                         "text": quoted[:CONTEXT_CHARS]})
    return hits, counts


def scan_home(home, terms):
    """Read a procurement's extracted text and say where the vocabulary occurs.

    Returns None when there is nothing to say — no terms configured, or no extracted text.
    A home with documents and no hits returns a real result with zero hits, which is a
    different statement and the one a reader needs: *this was read, and it says nothing*.
    """
    pattern = matcher(terms)
    if pattern is None:
        return None
    doc_dir = os.path.join(home, "doc")
    if not os.path.isdir(doc_dir):
        return None

    documents, total, vocabulary = [], 0, {}
    for name in sorted(os.listdir(doc_dir)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(doc_dir, name)
        try:
            with io.open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            # A document that cannot be read is not a document with nothing in it, and the
            # difference has to survive into the scan or a reader will draw the wrong
            # conclusion from a quiet file.
            documents.append({"doc": "doc/%s" % name, "unreadable": True,
                              "hits": 0, "terms": [], "context": []})
            continue
        hits, counts = scan_text(text, pattern)
        here = sum(counts.values())
        total += here
        for term, n in counts.items():
            vocabulary[term] = vocabulary.get(term, 0) + n
        documents.append({"doc": "doc/%s" % name, "hits": here,
                          "terms": sorted(counts, key=lambda t: (-counts[t], t)),
                          "context": hits})

    if not documents:
        return None
    documents.sort(key=lambda d: (-d.get("hits", 0), d["doc"]))
    return {
        "schema": "scan/1",
        "documents": documents,
        "hits": total,
        "documents_scanned": len(documents),
        "documents_with_hits": sum(1 for d in documents if d.get("hits")),
        "terms": sorted(vocabulary, key=lambda t: (-vocabulary[t], t)),
        "term_counts": vocabulary,
    }


def summary(scan):
    """The few numbers the day carries per procurement, so a reader can order its work.

    The day's own files are read before anything is downloaded, so the summary belongs there
    and the detail stays in the home. A reader that only wants to know whether a procurement
    is worth opening should not have to open it to find out.
    """
    if not scan:
        return None
    return {"hits": scan["hits"],
            "documents_with_hits": scan["documents_with_hits"],
            "documents_scanned": scan["documents_scanned"],
            "terms": scan["terms"][:12]}


def write(home, scan):
    """`scan.json` in the procurement's home, beside the text it describes.

    Written after `index.json` on purpose. The index is written last as the proof that the
    home's SOURCE is whole; this file is derived from that source and can be rebuilt from it,
    so its absence means "not scanned", never "incomplete".
    """
    if not scan:
        return None
    path = os.path.join(home, "scan.json")
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(scan, ensure_ascii=False, indent=2))
    return path
