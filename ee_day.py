"""One Estonian window, delivered: `day.json`, `changes.json`, and a home per procurement.

WHAT A DAY IS. The two files a reader already knows from every country tool in this family:
`changes.json` says what moved, `day.json` says what the window contains and is written LAST,
so a reader that lists folders instead of reading it reads the wrong day. Neither holds
tender bytes; both point at `tenders/<pid>/`, which is permanent and shared across days.

A WINDOW, NOT A DATE, AND THAT IS DELIBERATE. A missed night is a day of procurements nobody
reads, and a register does not re-publish them. So the run takes a range and the caller
decides what it covers — usually yesterday, and after an outage the days that were lost. One
request answers a fortnight as easily as a day, and the day folder is named for the end of
the range so the delivery keeps its shape.

THE GATE COSTS NOTHING HERE, AND THAT IS WORTH SAYING. In a country whose search returns only
ids, deciding what is worth downloading means fetching a card per procurement first. This
register returns the title, the buyer, the classification's name, the state, the procedure and
the deadline in the search itself — so the whole day is gated on what discovery already
returned, and the first extra request of the run is made for a procurement we have already
decided to keep.

WHAT MOVED IS ASKED TWICE, ON PURPOSE. `changes.fingerprint` compares the bytes of every
document, which is the floor and is what makes *the extractor rendered it differently* a
different sentence from *the buyer replaced it*. On top of that, the register stamps each
catalogue entry with when it last changed, so a record can name WHICH document moved rather
than only that something did.

    python3 ee_day.py 2026-09-04 --out work/EE --limit 5
"""
import argparse
import datetime
import json
import os
import time

import ee_fetch
import ee_page
import ee_targets

try:
    import changes as changes_mod
except Exception:
    changes_mod = None

try:
    import policy as policy_mod
except Exception:
    policy_mod = None


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def _working_day(date):
    return datetime.date(*(int(p) for p in date.split("-"))).weekday() < 5


def run(date, out_root, limit=None, keep=None, run_id=None, policy=None, watch=None,
        date_to=None):
    """Fetch the window's procurements into homes and write the day's two files.

    `watch` is the references somebody is still deciding about — the cards whose decision has
    not been settled. They ride in the SAME pass as the window, deduplicated against it: two
    passes are two draws at one state register for one date, and two answers about what that
    date contained.

    THE GATE DOES NOT APPLY TO THEM. The gate decides what is worth fetching for the first
    time; a watched procurement was already judged worth a card by a person, and dropping it
    here would silently stop answering the question the card is open for.
    """
    run_id = run_id or time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    date_from = date
    date_to = date_to or date
    # The folder is named for the end of the range, so a reader who knows where yesterday
    # landed knows where a three-day catch-up landed too.
    folder = date_to

    targets = ee_targets.window(date_from, date_to)

    # AN EMPTY WINDOW OVER WORKING DAYS IS A BROKEN CRAWL, AND NOTHING ELSE WOULD SAY SO.
    # This register publishes on the order of twenty-five notices a working day and none at
    # the weekend — measured across 20 Aug to 4 Sep 2026: 312 notices, and both Saturdays and
    # both Sundays empty. So zero over a range that contains no working day is the country
    # resting, and zero over a range that does is our own discovery breaking. Every way it
    # can break returns an empty list rather than an error: a renamed filter key is ignored
    # rather than refused, and the answer is then simply nothing that matches. Left unsaid it
    # becomes a green run, a complete day, an empty morning, and nothing to tell it from a
    # holiday.
    span = ee_targets.days(date_from, date_to)
    discovery_failed = any(_working_day(d) for d in span) and not targets

    if keep:
        targets = [t for t in targets if t["kind"] in keep]
    if limit:
        targets = targets[:limit]

    # THE GATE FIRES BEFORE A BYTE MOVES, and here it fires before a REQUEST moves: the
    # search row carries everything it reads. It is `policy.outside_scope` unchanged — a CPV
    # code means the same thing everywhere and the terms are a file, so the gate never needed
    # a country of its own.
    rules = policy_mod.load_policy(policy) if policy_mod is not None else None

    moves, delivered, failed, gated = [], [], [], []

    known = {t["pid"] for t in targets}
    for reference in (watch or []):
        try:
            row = ee_targets.one(reference)
        except Exception as exc:
            failed.append({"ref": str(reference), "pid": None, "kind": None, "watched": True,
                           "reason": "the register did not answer: %s" % str(exc)[:150]})
            continue
        if row is None:
            # A watched card the register will not serve is a hole in the watch, and the
            # report has to be able to name it.
            failed.append({"ref": str(reference), "pid": None, "kind": None, "watched": True,
                           "reason": "no procurement with this reference — withdrawn, or "
                                     "the reference is wrong"})
            continue
        if row["pid"] in known:
            # It fell inside the window as well. Mark the one already in the list rather than
            # adding a second, so the day counts it once and still says it was watched.
            for target in targets:
                if target["pid"] == row["pid"]:
                    target["watched"] = True
            continue
        row["watched"] = True
        targets.append(row)
        known.add(row["pid"])

    for target in targets:
        pid = target["pid"]
        home = os.path.join(out_root, "tenders", pid)
        previous = _read(os.path.join(home, "state.json"))

        if rules is not None and not target.get("watched"):
            if policy_mod.outside_scope(target, rules):
                # Named, never merely dropped. A tender nobody fetched and nobody mentioned
                # reads exactly like a tender that does not exist — and the list of what was
                # cut is the fastest way to see a badly tuned word list.
                gated.append({"pid": pid, "ref": target["ref"], "kind": target["kind"],
                              "title": target["title"], "buyer": target["buyer"],
                              "cpv_name": target["cpv_name"],
                              "link": ee_page.VIEW % pid})
                continue

        try:
            done = ee_fetch.fetch(target, out_root, target["kind"])
        except Exception as exc:                      # one tender must not lose the day
            failed.append({"pid": pid, "ref": target["ref"], "kind": target["kind"],
                           "watched": bool(target.get("watched")),
                           "reason": str(exc)[:200]})
            continue

        record = None
        if changes_mod is not None and done.get("state") is not None:
            record = changes_mod.diff(previous, done["state"], date=folder, run_id=run_id)
        status = (record or {}).get("status") or ("new" if previous is None else "changed")
        # The register stamps every catalogue entry with when it last moved, so a record can
        # say which document the buyer touched rather than only that one of them changed.
        touched = sorted({d.get("changed_at") for d in done["index"]["documents"]
                          if d.get("changed_at")}, reverse=True)
        moves.append({
            "pid": pid, "ref": target["ref"], "kind": target["kind"], "status": status,
            # Which population this came from. A reader answers two different questions of
            # the two — "is this worth a card" and "has what I am waiting on moved" — and a
            # day that did not say which was which would make them guess from the date.
            "watched": bool(target.get("watched")),
            "title": target["title"], "buyer": target["buyer"],
            "published": target["published"], "deadline": done.get("deadline"),
            "value": done.get("value"), "cpv_main": done.get("cpv_main"),
            "documents_changed_at": touched[:1],
            "documents": done["documents"],
            "withheld": done["withheld"],
            "uncatalogued": done["uncatalogued"],
            "moved": (record or {}).get("moves") or [],
        })
        delivered.append({
            "pid": pid, "ref": target["ref"], "kind": target["kind"], "status": status,
            "watched": bool(target.get("watched")),
            "home": "tenders/%s" % pid,
            "documents": done["documents"], "bytes": done["bytes"],
            "title": target["title"],
        })

    by_status = {}
    for row in moves:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
    watched_count = sum(1 for row in moves if row["watched"])

    # WHOSE FAILURE MAKES A DAY SHORT. The day is the window; a watched card is a standing
    # question somebody asked of it. A watched reference the register will not serve is a
    # hole in the watch and is reported as one — but it is not the window arriving short, and
    # letting it say so would mark every night incomplete until a person edited the board,
    # which teaches a reader to ignore the flag exactly when it starts meaning something.
    lost_window = [f for f in failed if not f.get("watched")]
    lost_watch = [f for f in failed if f.get("watched")]
    complete = not lost_window and not discovery_failed

    common = {"date": folder, "window": {"from": date_from, "to": date_to},
              "country": "EE", "run_id": run_id,
              "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "complete": complete, "discovery_failed": discovery_failed}

    changes = dict(common, **{
        "schema": "day-changes/1",
        "counts": dict(by_status, tenders=len(moves), gated=len(gated),
                       watched=watched_count),
        "gated": gated,
        "tenders": moves,
    })
    _write(os.path.join(out_root, folder, "changes.json"), changes)

    day = dict(common, **{
        "schema": "day/1", "source": "RHR",
        "changes_path": "%s/changes.json" % folder,
        "tenders_path": "tenders",
        "coverage": {"targets": len(targets), "delivered": len(delivered),
                     "gated": len(gated), "failed": len(lost_window),
                     "watch_holes": len(lost_watch)},
        "counts": dict(by_status, tenders=len(delivered), gated=len(gated),
                       watched=watched_count,
                       documents=sum(t["documents"] for t in delivered),
                       bytes=sum(t["bytes"] for t in delivered)),
        "lost": failed,
        "tenders": delivered,
    })
    _write(os.path.join(out_root, folder, "day.json"), day)   # last, as the contract says
    return day, changes


def main(argv=None):
    ap = argparse.ArgumentParser(description="One Estonian window into the delivery shape.")
    ap.add_argument("date", help="YYYY-MM-DD; the first day of the window")
    ap.add_argument("--to", default=None, help="the last day, if the window is wider than one")
    ap.add_argument("--out", default="work/EE")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only", choices=("tender", "consultation", "door"), default=None)
    ap.add_argument("--policy", default=None,
                    help="recall policy: JSON, a path to one, or EE_POLICY from the "
                         "environment. Absent means fetch everything.")
    args = ap.parse_args(argv)
    day, changes = run(args.date, args.out, args.limit,
                       keep=(args.only,) if args.only else None, policy=args.policy,
                       date_to=args.to)
    print("%s..%s: %d/%d delivered, %d gated, %d document(s), %.1f MB — %s"
          % (day["window"]["from"], day["window"]["to"],
             day["coverage"]["delivered"], day["coverage"]["targets"],
             day["coverage"]["gated"], day["counts"]["documents"],
             day["counts"]["bytes"] / 1048576.0,
             "complete" if day["complete"] else "SHORT"))
    for row in changes["tenders"]:
        print("  %-9s %-6s %-12s %s" % (row["ref"], row["status"], row["kind"],
                                        (row["title"] or "")[:52]))
    return day


if __name__ == "__main__":
    main()
