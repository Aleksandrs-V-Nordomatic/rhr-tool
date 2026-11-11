"""What Estonian buyers say they will buy, before the notice: two published procurement plans.

A notice is the last public moment of a procurement. The plan is the first, and for the work
this radar looks for it arrives months earlier: RKAS, the state's property company, lists its
building-automation renovations with an expected bid date long before they reach the register.

Two sources, both public and both machine-readable:

    RHR  GET https://riigihanked.riik.ee/rhr/api/public/v1/procurement-plans/
             procurement-plans/opendata/xml?year=<year>      431 plans for 2026, 6 buyers
    RKAS GET https://www.rkas.ee/et/rkas-hankeplaan-export   134 rows, XLSX, live

THE PEOPLE IN THEM STAY BEHIND. Both name a responsible person and their e-mail. A plan is read
for what is being bought, by whom and when; who answers the phone is on the buyer's page, which
the record links to. So the person columns are dropped at reading and never reach a file.

A SNAPSHOT A DAY, AND A DIFF AGAINST THE LAST ONE ON THE DRIVE. A runner has no memory, so
`deliver` reads the previous `plans/latest.json` back from the destination -- as the tender
delivery reads its state -- and writes what appeared, what went and what changed. A plan that
appears is the news; a plan that goes has usually become a notice.

    python3 ee_plans.py collect --out work --date 2026-11-11
    python3 ee_plans.py deliver --out work --date 2026-11-11
"""
import argparse
import datetime
import hashlib
import io
import json
import os
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET

import net

RHR_URL = ("https://riigihanked.riik.ee/rhr/api/public/v1/procurement-plans/procurement-plans/"
           "opendata/xml?year=%d")
RKAS_URL = "https://www.rkas.ee/et/rkas-hankeplaan-export"
UA = "Mozilla/5.0 (compatible; eis-tool)"

# The fields of a plan a reader compares from one day to the next. A plan whose cost or date
# moved is news of the same kind as a new one.
COMPARED = ("name", "description", "buyer", "for_buyer", "cost", "expected", "procedure",
            "type", "cpv")


def _fold(text):
    text = unicodedata.normalize("NFKC", text or "").casefold()
    return re.sub(r"\s+", " ", text).strip()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def rhr_plans(xml_bytes):
    """Every plan in the register's open data, without the responsible person."""
    root = ET.fromstring(xml_bytes)
    out = []
    for plan in root.iter("ProcurementPlan"):
        text = lambda tag: (plan.findtext(tag) or "").strip() or None
        cost = text("ProcurementCost")
        cpv = [c for c in re.split(r"[\s,;]+", text("CpvCodes") or "") if c]
        out.append({
            "key": "RHR-PLAN:%s" % text("ReferenceNumber"),
            "source": "RHR",
            "reference": text("ReferenceNumber"),
            "year": text("Year"),
            "buyer": text("ProcurerName"),
            "buyer_code": text("ProcurerCode"),
            "for_buyer": text("TargetProcurerName"),
            "for_buyer_code": text("TargetProcurerCode"),
            "name": text("ProcurementName"),
            "description": text("ProcurementDescription"),
            "cost": float(cost) if cost else None,
            # The register's own word for when the contract is expected to be signed.
            "expected": text("ExpectedContractSigningDate"),
            "expected_meaning": "contract signing",
            "type": text("ProcurementType"),
            "procedure": text("ProcedureType"),
            "cpv": cpv,
            "joint": text("JointProcurement"),
            "central": text("CentralProcurement"),
            "eu_funds": text("EuFunds"),
            "status": text("Status"),
        })
    return [p for p in out if p["reference"]]


def _tallinn(value):
    """`03.03.2027 11:00` (Tallinn wall clock) as ISO with its offset, or the text as given."""
    if isinstance(value, datetime.datetime):
        local = value
    else:
        m = re.match(r"\s*(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s+(\d{1,2}):(\d{2}))?", str(value or ""))
        if not m:
            return str(value).strip() if value else None
        d, mo, y, h, mi = m.groups()
        local = datetime.datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0))
    # Worked out here rather than asked of a tz database, which the toolchain image does not
    # carry: Estonia is UTC+2 and keeps EU summer time, from 03:00 on the last Sunday of March
    # to 04:00 on the last Sunday of October, local wall clock.
    def last_sunday(month):
        day = datetime.datetime(local.year, month, 31)
        return day - datetime.timedelta(days=(day.weekday() + 1) % 7)
    summer = (last_sunday(3).replace(hour=3) <= local < last_sunday(10).replace(hour=4))
    offset = datetime.timezone(datetime.timedelta(hours=3 if summer else 2))
    return local.replace(tzinfo=offset).isoformat()


def rkas_plans(xlsx_bytes):
    """RKAS's plan, without the responsible person.

    The export carries no number, so the key is built from what a row says it is: its name and
    its procedure, folded. A row renamed is therefore a plan gone and a plan new, which is what a
    reader would also have to decide by eye.
    """
    import openpyxl
    sheet = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True).active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return []
    head = [_fold(str(h or "")) for h in rows[0]]

    def col(*names):
        for name in names:
            if name in head:
                return head.index(name)
        return None
    c_name = col("hanke nimetus")
    c_proc = col("hankemenetluse liik")
    c_unit = col("korraldav üksus")
    c_bid = col("pakkumuse esitamine (eeldatav)")
    if c_name is None:
        raise ValueError("the RKAS export has no 'Hanke nimetus' column: %s" % head)
    out = []
    for row in rows[1:]:
        cell = lambda i: (row[i] if i is not None and i < len(row) else None)
        name = str(cell(c_name) or "").strip()
        if not name:
            continue
        procedure = str(cell(c_proc) or "").strip() or None
        key = _sha(("%s|%s" % (_fold(name), _fold(procedure))).encode("utf-8"))[:16]
        out.append({
            "key": "RKAS-PLAN:%s" % key, "source": "RKAS", "reference": None,
            "buyer": "Riigi Kinnisvara AS", "for_buyer": None,
            "unit": str(cell(c_unit) or "").strip() or None,
            "name": name, "description": None, "cost": None,
            "expected": _tallinn(cell(c_bid)), "expected_meaning": "bid submission",
            "type": None, "procedure": procedure, "cpv": [],
        })
    return out


def collect(out_root, date, get=None, year=None):
    """Both plans into `<out>/EE/plans/<date>/plans.json`. A source that fails is named in the
    file and costs only its own plans."""
    get = get or (lambda url: net.get(url, headers={"User-Agent": UA}, timeout=120)[0])
    year = year or int(date[:4])
    sources, plans = {}, []
    readers = [("rhr_%d" % y, RHR_URL % y, rhr_plans) for y in (year, year + 1)]
    readers.append(("rkas", RKAS_URL, rkas_plans))
    for name, url, read in readers:
        try:
            data = get(url)
            found = read(data)
            sources[name] = {"url": url, "bytes": len(data), "sha256": _sha(data),
                             "plans": len(found)}
            plans.extend(found)
        except Exception as exc:
            sources[name] = {"url": url, "error": "%s: %s" % (type(exc).__name__, str(exc)[:160])}
    seen, unique = set(), []
    for plan in plans:                         # two RKAS rows of one name stay one plan
        if plan["key"] not in seen:
            seen.add(plan["key"])
            unique.append(plan)
    snapshot = {"schema": "plans/1", "country": "EE", "date": date,
                "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "sources": sources, "plans": unique}
    folder = os.path.join(out_root, "EE", "plans", date)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "plans.json"), "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, indent=2)
    return snapshot


def diff(before, now):
    """What appeared, what went, and what moved, between two snapshots.

    A source that failed today says nothing about its plans: they are neither gone nor kept, so
    they are left out of `gone` rather than reported as withdrawn.
    """
    failed = {name.split("_")[0].upper() for name, s in now.get("sources", {}).items()
              if s.get("error")}
    was = {p["key"]: p for p in (before or {}).get("plans", [])}
    is_ = {p["key"]: p for p in now.get("plans", [])}
    changed = []
    for key in sorted(set(was) & set(is_)):
        moved = {f: [was[key].get(f), is_[key].get(f)] for f in COMPARED
                 if was[key].get(f) != is_[key].get(f)}
        if moved:
            changed.append({"key": key, "name": is_[key].get("name"), "moved": moved})
    return {
        "schema": "plans-changes/1", "date": now.get("date"),
        "since": (before or {}).get("date"),
        "new": [is_[k] for k in sorted(set(is_) - set(was))] if before else [],
        "gone": [{"key": k, "name": was[k].get("name"), "source": was[k].get("source")}
                 for k in sorted(set(was) - set(is_)) if was[k].get("source") not in failed],
        "changed": changed,
        "first_snapshot": before is None,
    }


def deliver(out_root, date, drive, base, tok, graph):
    folder = os.path.join(out_root, "EE", "plans", date)
    with open(os.path.join(folder, "plans.json"), encoding="utf-8") as fh:
        snapshot = json.load(fh)
    previous = graph.json_at(drive, "%s/plans/latest.json" % base, tok)
    changes = diff(previous, snapshot)
    with open(os.path.join(folder, "changes.json"), "w", encoding="utf-8") as fh:
        json.dump(changes, fh, ensure_ascii=False, indent=2)
    blob = lambda o: json.dumps(o, ensure_ascii=False, indent=2).encode("utf-8")
    # Changes and the dated snapshot first, `latest` last: tomorrow compares against `latest`,
    # and a `latest` that landed before today's files would make today's news vanish.
    graph.upload(drive, "%s/plans/%s/changes.json" % (base, date), blob(changes), tok)
    graph.upload(drive, "%s/plans/%s/plans.json" % (base, date), blob(snapshot), tok)
    graph.upload(drive, "%s/plans/latest.json" % base, blob(snapshot), tok)
    return changes


def line(snapshot, changes=None):
    """Counts only, for a public log."""
    parts = ["%s %s" % (name, s.get("plans", "FAILED")) for name, s in snapshot["sources"].items()]
    text = "plans %s: %d (%s)" % (snapshot["date"], len(snapshot["plans"]), ", ".join(parts))
    if changes is not None:
        text += " -- %s" % ("first snapshot" if changes["first_snapshot"] else
                            "%d new, %d gone, %d changed" % (len(changes["new"]),
                                                             len(changes["gone"]),
                                                             len(changes["changed"])))
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(description="Estonian procurement plans, RHR and RKAS.")
    ap.add_argument("command", choices=("collect", "deliver"))
    ap.add_argument("--out", default="work")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD, the day the snapshot is for")
    args = ap.parse_args(argv)
    if args.command == "collect":
        snapshot = collect(args.out, args.date)
        print(line(snapshot))
        return 0 if snapshot["plans"] else 1
    import country
    import deliver_graph as graph
    drive = graph.env("GRAPH_DRIVE_ID")
    base = country.destination(graph.env("GRAPH_DEST_ROOT"), "EE")
    changes = deliver(args.out, args.date, drive, base, graph.graph_token(), graph)
    with open(os.path.join(args.out, "EE", "plans", args.date, "plans.json"), encoding="utf-8") as fh:
        print(line(json.load(fh), changes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
