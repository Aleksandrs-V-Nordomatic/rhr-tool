"""The standing doors: dynamic purchasing systems open for entry.

A dynamic purchasing system is not a tender and not a stream. It is a pool a buyer opens for
a category and keeps open for years: applications are accepted for the whole life of the
system, so there is no deadline to miss and nothing to hurry. What there is, is a door —
qualify once, and every actual purchase inside that category afterwards arrives as an
invitation, none of which is ever advertised again.

WHY THEY NEED THEIR OWN COMMAND. A nightly window shows a system on the one day it was
created and never again, which is exactly backwards: the day it was created is the least
useful day to hear about it, and every day after is equally good. So these are enumerated as
a stock, on demand, and what a reader wants from them is a list to work through once rather
than a card each morning.

WHAT THIS REGISTER GIVES THEM THAT A WINDOW WOULD NOT. A door here is an ordinary
procurement: the same search row carries its title, buyer and classification name, and the
same three requests give its facts and its catalogue. So the qualification documents — which
are the whole point, because they say what a supplier has to prove — are fetched into the
same homes a tender lands in, and a reader who has read one has read both.

    python3 ee_doors.py --out work/EE --policy rules.json
"""
import argparse
import json
import os
import time

import ee_fetch
import ee_page
import ee_targets

try:
    import policy as policy_mod
except Exception:
    policy_mod = None


def harvest(out_root, policy=None, limit=None, with_documents=True):
    """Every system standing open for entry, gated, and the kept ones fetched into homes."""
    rules = policy_mod.load_policy(policy) if policy_mod is not None else None
    rows = ee_targets.doors()

    base = os.path.join(out_root, "doors")
    os.makedirs(base, exist_ok=True)

    kept, failed, documents = [], [], 0
    candidates = rows[:limit] if limit else rows
    for row in candidates:
        # The same gate the day runs, given the same two texts: this register's search row
        # carries the classification's name for a door exactly as it does for a tender, so
        # nothing has to be weakened here.
        if rules is not None and policy_mod.outside_scope(row, rules):
            continue
        entry = {
            "pid": row["pid"], "ref": row["ref"],
            "title": row["title"], "buyer": row["buyer"],
            "published": row.get("published"),
            "status": row.get("status"), "status_text": ee_page.label(
                "PROCUREMENT_STATE", row.get("status")),
            "procedure": row.get("procedure"),
            "procedure_text": ee_page.label("PROCEDURE_TYPE", row.get("procedure")),
            "cpv_name": row.get("cpv_name"),
            # A door has no submission deadline in the sense a tender does — applications
            # stay open for the life of the system. Whatever the register prints here is that
            # system's own end date, not a date to hurry for.
            "deadline": row.get("deadline"),
            "link": ee_page.VIEW % row["pid"],
            "home": None,
        }
        if with_documents:
            try:
                done = ee_fetch.fetch(row, out_root, "door")
            except Exception as exc:
                # One unreachable system must not lose the list: the rest is still worth
                # having, and the failure is named rather than dropped.
                failed.append({"pid": row["pid"], "ref": row["ref"],
                               "reason": str(exc)[:200]})
                kept.append(entry)
                continue
            documents += done["documents"]
            entry.update({"home": "tenders/%s" % row["pid"],
                          "documents": done["documents"],
                          "cpv_main": done.get("cpv_main"),
                          "value": done.get("value")})
        kept.append(entry)

    path = os.path.join(base, "doors.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        for row in kept:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    index = {
        "schema": "doors/1", "country": "EE", "source": "RHR",
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "counts": {"open": len(rows), "ours": len(kept), "documents": documents},
        "failed": failed,
        "doors_path": "doors/doors.jsonl",
        "_what": "Systems to apply into, not tenders to bid on. Applications stay open for "
                 "the life of each system, so this is a list to work through once rather "
                 "than a card each morning.",
    }
    with open(os.path.join(base, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=2)
    return index


def main(argv=None):
    ap = argparse.ArgumentParser(description="Estonian systems worth applying into.")
    ap.add_argument("--out", default="work/EE")
    ap.add_argument("--policy", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--list-only", action="store_true",
                    help="enumerate and gate without downloading the qualification documents")
    args = ap.parse_args(argv)
    index = harvest(args.out, args.policy, args.limit, not args.list_only)
    print("doors: %d open, %d ours, %d document(s)"
          % (index["counts"]["open"], index["counts"]["ours"], index["counts"]["documents"]))
    return index


if __name__ == "__main__":
    main()
