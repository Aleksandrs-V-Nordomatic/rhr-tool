"""Discovery for Estonia: which procurements a window contains.

One POST answers a whole window, and the rows come back already carrying the title, the
buyer, the classification's name, the state, the procedure and the deadline. There is no
pager to walk and no register to resolve against: the search IS the register.

That leaves three ways to get a wrong answer quietly, and all three are guarded here rather
than left to a caller to remember.

FIRST: THE WINDOW IS EXCLUSIVE AT THE START. Measured against the live register on
4 Sep 2026 — `Begin=2026-09-02, End=2026-09-03` returns the third and not the second;
`Begin=D, End=D` returns nothing at all. So the day D is asked for as `Begin = D-1,
End = D`, and a caller that reasoned by analogy with an inclusive range would deliver an
empty day, call it complete, and look exactly like a public holiday.

SECOND: AN UNKNOWN FILTER KEY IS IGNORED, NOT REFUSED. `procurementReferenceNr` — the name
the ROWS use for the reference number — is not the name the FILTER uses, and asking with it
does not fail: it returns the register's whole answer, truncated to five hundred rows, with
a 200. A run watching one card would have fetched five hundred procurements and reported
success. So every answer is checked against what was asked for, and a filter that plainly
did not bite stops the run.

THIRD: FIVE HUNDRED IS A CAP AND NOTHING SAYS SO. The answer is a bare array with no total
and no next page. Exactly five hundred rows means the answer was cut, and the rows beyond it
are not named anywhere — so it is raised rather than returned. A working day publishes on
the order of twenty-five notices, so a window has to be weeks wide before this can fire; the
one place it genuinely does is a first sweep of everything standing open.

    python3 ee_targets.py 2026-09-04                # one published day
    python3 ee_targets.py 2026-08-20 2026-09-04     # a range, inclusive of both ends
    python3 ee_targets.py --doors                   # the systems standing open for entry
"""
import argparse
import datetime
import json
import sys

import ee_page

# The register sorts by publication and the caller does not get to omit this: a body without
# `orderBy` is answered with a 500, which reads like a broken route rather than like a
# missing argument.
ORDER = {"procurementProcessRevealDate": "desc"}

# What the register returns at most, with nothing in the answer saying it stopped.
CAP = 500

# The state a dynamic purchasing system stands in while suppliers may still apply.
OPEN_FOR_ENTRY = "14"


class Truncated(RuntimeError):
    """The register cut the answer, and the rows it dropped are named nowhere.

    Raised rather than returned. A window that came back short cannot say what it missed —
    unlike a target that failed, which the day names in `lost` — so there is nothing honest
    to deliver and no way for a reader to know the day is incomplete.
    """


class FilterIgnored(RuntimeError):
    """The register answered, and the answer is not the question that was asked.

    The one failure this API produces that looks exactly like success. See the module
    docstring: a misspelt filter key returns the unfiltered register under a 200.
    """


def _iso(day):
    """The register takes an instant; a date is what a caller means."""
    return "%sT00:00:00.000Z" % day


def _search(criteria, session=None):
    rows = (session or ee_page.session()).post_json(
        ee_page.SEARCH, {"orderBy": ORDER, "filter": criteria})
    if not isinstance(rows, list):
        raise FilterIgnored("the register answered with %s rather than a list of rows"
                            % type(rows).__name__)
    if len(rows) >= CAP:
        raise Truncated(
            "the register returned %d rows, which is its cap — the answer was cut and what "
            "it dropped is named nowhere. Ask for a narrower window." % len(rows))
    return rows


def days(date_from, date_to):
    """Every calendar day the caller asked about, inclusive of both ends.

    Public because the day driver asks the same question of a window — whether any working day is
    in it, which is what makes an empty answer a broken crawl rather than a quiet country. Two
    modules deriving that list separately is two places for the arithmetic to differ.
    """
    start = datetime.date(*(int(p) for p in date_from.split("-")))
    end = datetime.date(*(int(p) for p in date_to.split("-")))
    if end < start:
        raise ValueError("the window ends before it begins: %s .. %s" % (date_from, date_to))
    out, day = [], start
    while day <= end:
        out.append(day.isoformat())
        day = day + datetime.timedelta(days=1)
    return out


def _row(record):
    """One search row, in the small shape the day works with."""
    return {
        "pid": str(record.get("procurementId")),
        "ref": record.get("procurementReferenceNr"),
        "kind": ee_page.kind_of(record),
        "title": record.get("procurementName"),
        "buyer": record.get("contractingAuthorityName"),
        "published": record.get("procProcessRevealDate"),
        "deadline": record.get("procProcessSubmitDate"),
        "status": str(record.get("procurementStatus") or "") or None,
        "procedure": record.get("procurementProcessType"),
        "work_kind": record.get("procurementType"),
        # The classification's Estonian name. The gate reads it as its second surface,
        # because the search row does not carry the code and the code costs a request.
        "cpv_name": record.get("mainCpvName"),
        "record": record,
    }


def window(date_from, date_to=None, session=None):
    """Every procurement the register published in the window, both ends inclusive.

    The register's own range is exclusive at the start, so a day earlier is asked for and the
    answer is then checked against the days the CALLER meant. That check is not belt and
    braces: it is the only thing standing between a filter this API silently ignores and a
    day that contains the whole register.
    """
    date_to = date_to or date_from
    wanted = set(days(date_from, date_to))
    begin = (datetime.date(*(int(p) for p in date_from.split("-")))
             - datetime.timedelta(days=1)).isoformat()
    rows = _search({"procurementProcessRevealDateBegin": _iso(begin),
                    "procurementProcessRevealDateEnd": _iso(date_to)}, session)

    outside = [r for r in rows if (r.get("procProcessRevealDate") or "")[:10] not in wanted]
    if outside:
        raise FilterIgnored(
            "%d of %d rows were published outside %s .. %s — the register did not apply the "
            "window. A filter key it does not recognise is ignored rather than refused, and "
            "the answer is then the whole register."
            % (len(outside), len(rows), date_from, date_to))
    out, seen = [], set()
    for record in rows:
        pid = str(record.get("procurementId"))
        if pid and pid not in seen:
            seen.add(pid)
            out.append(_row(record))
    return out


def day(date, session=None):
    """One published day."""
    return window(date, date, session)


def one(reference, session=None):
    """The row for a single procurement, found by the number a person quotes.

    `referenceNumber` is the filter's spelling and `procurementReferenceNr` is the row's, and
    they are not interchangeable: the second is silently ignored. Both are written down here
    because the next reader will have the row in front of them and will reach for its name.
    """
    token = str(reference).strip().split(":")[-1].strip()
    if not token:
        return None
    rows = _search({"referenceNumber": token}, session)
    exact = [r for r in rows if str(r.get("procurementReferenceNr") or "") == token]
    if not exact:
        # The filter matches on more than equality, so a token that brought back rows but not
        # ITS row is a miss rather than a match — and saying so is the difference between a
        # watched card reporting nothing and a watched card reporting the wrong tender.
        return None
    return _row(exact[0])


def doors(session=None):
    """The dynamic purchasing systems standing open for entry, as a stock rather than a day.

    Not a window and not a day. A system announced in March is exactly as open in September,
    and purchases made inside one are never advertised again — so this population is read on
    demand, when somebody asks what there is to apply to, and not every night.
    """
    rows = _search({"procurementStatusCode": OPEN_FOR_ENTRY}, session)
    wrong = [r for r in rows if str(r.get("procurementStatus") or "") != OPEN_FOR_ENTRY]
    if wrong:
        raise FilterIgnored(
            "%d of %d rows are not open for entry — the register ignored the state filter"
            % (len(wrong), len(rows)))
    return [_row(r) for r in rows]


def main(argv=None):
    ap = argparse.ArgumentParser(description="What RHR published in a window.")
    ap.add_argument("date_from", nargs="?", help="YYYY-MM-DD")
    ap.add_argument("date_to", nargs="?")
    ap.add_argument("--doors", action="store_true",
                    help="the systems standing open for entry, instead of a window")
    ap.add_argument("--ref", default=None, help="one procurement, by reference number")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.ref:
        rows = [r for r in [one(args.ref)] if r]
    elif args.doors:
        rows = doors()
    elif args.date_from:
        rows = window(args.date_from, args.date_to or args.date_from)
    else:
        ap.error("name a date, or --doors, or --ref")

    if args.json:
        json.dump([{k: v for k, v in r.items() if k != "record"} for r in rows],
                  sys.stdout, ensure_ascii=False, indent=2)
        print()
        return rows
    by_kind = {}
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    print("%d record(s) %s" % (len(rows), by_kind))
    for r in rows[:20]:
        print("  %-9s %-8s %-13s %s" % (r["pid"], r["ref"], r["kind"],
                                        (r["title"] or "")[:58]))
    return rows


if __name__ == "__main__":
    main()
