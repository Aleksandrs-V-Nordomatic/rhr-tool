#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
One Estonian tender, end to end: find it, download it, read it, say what could not be read.

    python3 eis_tool.py day 2026-09-04 --country EE --out work    # the published window
    python3 eis_tool.py scans --date 2026-09-04 --country EE      # read what no decoder could
    python3 eis_tool.py doors --country EE --out work             # systems open for entry
    python3 eis_tool.py extract --pack out                        # deterministic text

WHY A SINGLE ENTRY POINT, AND WHY IT KEEPS THE FAMILY'S NAME. The steps could live as
separate scripts glued together inside a workflow file, which would put the sequence in YAML,
where it cannot be tested and cannot be run anywhere else. A VPS, a laptop and a runner now
execute the identical thing — and they execute it under the same command in every country
tool, so a person who has driven one has driven this.

WHY THERE IS NO `probe` HERE. A tool whose register refuses part of the cloud address space
has to ask for permission before it builds anything, because a failed fetch there is evidence
about the address rather than about the tender. This register refuses none: every request in
this repository was made from an ordinary machine with no proxy and none was turned away. The
same gate would be a question that always answers yes, and a check that cannot fail teaches a
reader that the failure it names does not happen here.

ONE COUNTRY, AND IT STILL HAS TO BE NAMED. `--country EE` is not decoration and there is no
default: the destination folder is derived from it, and a tool that assumes its own country
is a tool that cannot say when it was pointed at the wrong drive. See country.py.
"""

import argparse
import country
import os
import re
import sys

from console import utf8_streams


def extract(pack, with_images=False, keep_unpacked=False):
    """Deterministic text. Imported rather than shelled out, so a failure is a traceback."""
    import normalize
    argv = ["--in", pack, "--out", os.path.join(pack, "normalized")]
    if with_images:
        argv.append("--with-images")
    # The scan lane runs after this and can only read what still exists: a file that came
    # out of an archive has no downloaded original to fall back on.
    if keep_unpacked:
        argv.append("--keep-unpacked")
    return normalize.main(argv)


def read_scans(pack, model=None, limit=None, provider=None):
    """The fallback lane over files no decoder could read. Never fails the run.

    Defaults to local OCR, which needs no account and no key — so this step works out of the
    box on any machine that has Tesseract, and degrades to a printed note rather than an
    error on one that does not. A pack whose scans stay unread is exactly as complete as it
    was before this lane existed.
    """
    import assist as assist_mod
    provider = provider or os.environ.get("ASSIST_PROVIDER", assist_mod.DEFAULT_PROVIDER)
    _, needs_key, _, _ = assist_mod.PROVIDERS.get(
        provider, assist_mod.PROVIDERS[assist_mod.DEFAULT_PROVIDER])
    api_key = (os.environ.get("%s_API_KEY" % provider.upper())
               or os.environ.get("ASSIST_API_KEY"))
    if needs_key and not api_key:
        print("scan lane skipped — %s_API_KEY not set (the pack is complete without it)"
              % provider.upper())
        return 0
    # EVERY exception, not one class of them. This lane reads files the deterministic
    # extractor already listed as unreadable, and a pack whose scans stay unread is exactly
    # as complete as it was before the lane existed — so nothing it does may fail a tender.
    # Guarding only RuntimeError would make that promise depend on which class a dependency
    # happened to raise: PyMuPDF raises its own hierarchy, and rasterising one oversized page
    # threw `code=5: Overly large image` straight past such a handler.
    try:
        doc = assist_mod.run(pack, model=model, api_key=api_key, provider=provider,
                             limit=limit)
    except Exception as exc:
        print("scan lane skipped — %s" % str(exc)[:200])
        return 0
    print("%s lane · %d read · %d deferred · %d skipped"
          % (doc["provider"], doc["read"], doc["deferred"], doc["skipped"]))
    return 0


def read_targets(source):
    """References from a file or from the argument itself, in the order they were given.

    Both spellings because both callers are real: a workflow writes its multi-line input to a
    file, and a person on a terminal types two references separated by a comma. Deduplicated
    while keeping order, because a list naming the same procurement twice would fetch it
    twice and count the day wrong.
    """
    if not source:
        return []
    raw = source
    if os.path.exists(source):
        with open(source, encoding="utf-8") as fh:
            raw = fh.read()
    out, seen = [], set()
    for token in re.split(r"[\s,]+", raw.strip()):
        # `RHR:314707` is how a card spells a key; the number is what the register answers to.
        token = token.split(":")[-1].strip()
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def main(argv=None):
    utf8_streams()

    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("extract", help="turn a downloaded pack into text")
    p.add_argument("--pack", required=True)
    p.add_argument("--with-images", action="store_true")

    # ONE COMMAND, ONE WINDOW. It names a country and a window and gets the delivery shape
    # every country tool produces — the same `day.json` beside the same folders, so a reader
    # that knows one country's layout knows them all. That shape is the contract between the
    # tools, and it is the reason each country can be its own repository without the reader
    # having to learn a second one.
    p = sub.add_parser("day", help="fetch one country's published window into the delivery shape")
    p.add_argument("date", help="YYYY-MM-DD, the first day of the window")
    p.add_argument("--to", default=None,
                   help="the last day. Absent means a single day. A range exists because a "
                        "night that did not run is a day nobody reads, and the register does "
                        "not publish it again")
    p.add_argument("--out", default="work")
    p.add_argument("--limit", type=int, default=None, help="stop after this many, for a trial")
    p.add_argument("--policy", default=None,
                   help="recall policy: JSON, a path to one, or EE_POLICY from the "
                        "environment. Absent means fetch everything.")
    # THE WATCH LIST TRAVELS WITH THE WINDOW, never in a run of its own. Two runs are two
    # draws at one register for one date, and two answers about what that date contained.
    # These are references somebody is still deciding about, so the recall gate does not
    # apply: it decides what is worth fetching for the FIRST time, and these already have a
    # card.
    p.add_argument("--targets", default=None,
                   help="references to re-read whatever the gate would say — a file of them, "
                        "one per line, or the references themselves separated by commas")
    country.add_argument(p)

    # THE FALLBACK LANE, AS ITS OWN COMMAND AND NOT A STEP INSIDE THE DAY. It works only on
    # the queue the deterministic extractor already produced and named, and it must be able
    # to fail without touching the day: a pack whose scans stay unread is exactly as complete
    # as it was before this lane existed. A separate command is what makes that true of the
    # exit code as well as of the files.
    p = sub.add_parser("scans", help="read the files no decoder could, over one day's homes")
    p.add_argument("--out", default="work")
    p.add_argument("--date", required=True, help="the day whose homes to walk")
    p.add_argument("--model", default=None,
                   help="OCR language string, or a model name when --provider is a hosted one")
    p.add_argument("--provider", default=None)
    p.add_argument("--limit", type=int, default=None)
    country.add_argument(p)

    # The standing population. Not a window and not a day: a dynamic purchasing system
    # announced in March is exactly as open in September, and purchases made inside one are
    # never advertised again. Read as a stock, on demand.
    p = sub.add_parser("doors", help="the dynamic purchasing systems standing open for entry")
    p.add_argument("--out", default="work")
    p.add_argument("--policy", default=None)
    p.add_argument("--limit", type=int, default=None)
    country.add_argument(p)

    args = ap.parse_args(argv)

    try:
        code = country.resolve(args.country, os.environ) if args.command != "extract" else None
    except country.Mismatch as exc:
        # A stack trace here would be the tool blaming the caller for a question it simply
        # has to be asked.
        print("%s: %s" % (args.command, exc), file=sys.stderr)
        return 2

    if args.command == "scans":
        import json
        root = os.path.join(args.out, code)
        day_file = os.path.join(root, args.date, "day.json")
        if not os.path.exists(day_file):
            # THE DAY NAMES THE HOMES, NOT THE DIRECTORY. `tenders/` accumulates every
            # procurement ever fetched onto this disk; only what this day delivered is this
            # day's business. Without the day there is nothing to walk, and guessing at the
            # folder would silently re-read months of them.
            print("scans: no day at %s — nothing to walk" % args.date, file=sys.stderr)
            return 0
        with open(day_file, encoding="utf-8") as fh:
            day = json.load(fh)
        for row in day.get("tenders", []):
            home = os.path.join(root, "tenders", str(row["pid"]))
            if os.path.isdir(home):
                read_scans(home, model=args.model, limit=args.limit,
                           provider=args.provider)
        return 0

    if args.command == "doors":
        import ee_doors
        # The destination carries the country for the same reason the source does: one run is
        # one country, and neither half is configured where the other cannot see it.
        index = ee_doors.harvest(os.path.join(args.out, code), args.policy, limit=args.limit)
        print("doors: %d open, %d ours, %d document(s)"
              % (index["counts"]["open"], index["counts"]["ours"],
                 index["counts"]["documents"]))
        return 0

    if args.command == "day":
        import ee_day
        out = os.path.join(args.out, code)
        day, _ = ee_day.run(args.date, out, args.limit, policy=args.policy,
                            watch=read_targets(args.targets), date_to=args.to)
        print("%s %s..%s: %d/%d delivered, %d document(s) -> %s"
              % (code, day["window"]["from"], day["window"]["to"],
                 day["coverage"]["delivered"], day["coverage"]["targets"],
                 day["counts"]["documents"], out))
        # NAMED, NOT COUNTED. "5 of 41" is also what a heavily gated day looks like, so a
        # short day that only reported a number would be indistinguishable from a normal one.
        # The exit code says the day is short; these lines say which procurements and why,
        # which is the part a person can act on.
        for row in day.get("lost", []):
            print("  lost %s (%s): %s" % (row.get("ref") or row.get("pid"),
                                          row.get("kind") or "?", row.get("reason")),
                  file=sys.stderr)
        return 0 if day["complete"] else 1

    if args.command == "extract":
        return extract(os.path.abspath(args.pack), args.with_images)

    raise AssertionError("unreachable: argparse rejects any other command")


if __name__ == "__main__":
    sys.exit(main())
