"""The Estonian work that never reaches the register: two public lists on hange.ee.

The register carries what the law makes a buyer publish. Below the simple-procurement threshold
nothing has to be published at all, and hange.ee is the one aggregator found that collects it:

    GET https://www.hange.ee/hanketeated/            notices its staff type in from buyers'
                                                     own sites -- 86 in the last 30 days,
                                                     legal persons only
    GET https://www.hange.ee/hanked/?filter=all-active&page=N
                                                     requests buyers post themselves -- 112
                                                     active, 50 a page

ONLY THE LISTS. A notice's detail and its buyer's contacts are a paid feature; the list says what
the work is, where, in which field and until when, which is what decides whether a person opens
it. Nothing is downloaded behind the list.

A PRIVATE PERSON'S REQUEST IS LEFT WHERE IT IS. Three in four active requests are somebody's
bathroom or roof, posted by `eraisik`. None is work this radar looks for, and each is a private
person's job ad, so it is skipped at reading and never reaches a file. Companies, apartment
associations and municipalities are kept.

A snapshot a day, diffed against the previous one on the drive, as `ee_plans` does.

    python3 ee_hange.py collect --out work --date 2026-11-11
    python3 ee_hange.py deliver --out work --date 2026-11-11
"""
import argparse
import html
import json
import os
import re
import sys
import time

import net

NOTICES = "https://www.hange.ee/hanketeated/"
REQUESTS = "https://www.hange.ee/hanked/?filter=all-active&page=%d"
UA = "Mozilla/5.0 (compatible; eis-tool)"
# 112 active requests were three pages on 11 Nov 2026. Ten is room to grow and a bound on a list
# that stopped paging.
MAX_PAGES = 10
PRIVATE = "eraisik"
COMPARED = ("title", "deadline", "county", "field", "organiser")


def _text(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))).strip()


def _date(text):
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text or "")
    return "%s-%02d-%02d" % (m.group(3), int(m.group(2)), int(m.group(1))) if m else None


def _labelled(block, label):
    m = re.search(r'<span class="light">\s*%s\s*</span>(.*?)(?:<br|</p>)' % re.escape(label),
                  block, re.S)
    return _text(m.group(1)) if m else None


def notices(page):
    """The staff-entered notices: legal persons' work found nowhere else."""
    out = []
    for row in page.split("<tr>")[1:]:
        ident = re.search(r'data-notice-id="(\d+)"', row)
        title = re.search(r'class="trigger-modal register-click border-link"\s*>(.*?)</a>', row, re.S)
        if not ident or not title:
            continue
        due = re.search(r"Pakkumisi oodatakse kuni:\s*</span>(.*?)<", row, re.S)
        out.append({
            "key": "HANGE-NOTICE:%s" % ident.group(1), "source": "hange.ee notices",
            "id": ident.group(1), "title": _text(title.group(1)),
            "county": _labelled(row, "Asukoht:"), "field": _labelled(row, "Valdkond:"),
            "deadline": _date(due.group(1)) if due else None,
            "organiser": "legal person", "has_files": "icon-clip" in row,
            "link": NOTICES,
        })
    return out


def requests(page):
    """The requests buyers post themselves, without the private persons'."""
    out, skipped = [], 0
    for row in page.split('<tr class=')[1:]:
        link = re.search(r'<a class="border-link" href="(https://www\.hange\.ee/(\d+)/[^"]*)">(.*?)</a>',
                         row, re.S)
        if not link:
            continue
        organiser = _labelled(row, "Hanke korraldaja:") or ""
        if organiser.casefold() == PRIVATE:
            skipped += 1
            continue
        stage = _labelled(row, "Hanke etapp:") or ""
        added = re.search(r"</td>\s*<td>\s*(\d{1,2}\.\d{1,2}\.\d{4})\s*</td>", row)
        out.append({
            "key": "HANGE-REQUEST:%s" % link.group(2), "source": "hange.ee requests",
            "id": link.group(2), "title": _text(link.group(3)),
            "county": _labelled(row, "Asukoht:"), "field": None,
            "deadline": _date(stage), "stage": stage or None,
            "added": _date(added.group(1)) if added else None,
            "organiser": organiser or None, "link": link.group(1),
        })
    return out, skipped


def _get(url):
    data, _ = net.get(url, headers={"User-Agent": UA}, timeout=60)
    return data.decode("utf-8", "replace")


def collect(out_root, date, get=None, max_pages=MAX_PAGES):
    """Both lists into `<out>/EE/hange/<date>/hange.json`. A list that fails is named and costs
    only its own rows."""
    get = get or _get
    sources, items = {}, []
    try:
        found = notices(get(NOTICES))
        sources["notices"] = {"url": NOTICES, "items": len(found)}
        items.extend(found)
    except Exception as exc:
        sources["notices"] = {"url": NOTICES, "error": "%s: %s" % (type(exc).__name__, str(exc)[:160])}
    try:
        kept, private, pages = [], 0, 0
        for number in range(1, max_pages + 1):
            page = get(REQUESTS % number)
            pages += 1
            rows, skipped = requests(page)
            private += skipped
            fresh = [r for r in rows if r["key"] not in {k["key"] for k in kept}]
            if not rows and not skipped or (not fresh and not skipped):
                break
            kept.extend(fresh)
            if "page=%d" % (number + 1) not in page:
                break
        sources["requests"] = {"url": REQUESTS % 1, "pages": pages, "items": len(kept),
                               "private_skipped": private}
        items.extend(kept)
    except Exception as exc:
        sources["requests"] = {"url": REQUESTS % 1,
                               "error": "%s: %s" % (type(exc).__name__, str(exc)[:160])}
    snapshot = {"schema": "hange/1", "country": "EE", "date": date,
                "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "sources": sources, "items": items}
    folder = os.path.join(out_root, "EE", "hange", date)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "hange.json"), "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, indent=2)
    return snapshot


def diff(before, now):
    """New, gone and moved. A list that failed today withdraws nothing."""
    failed = {"hange.ee %s" % name for name, s in now.get("sources", {}).items() if s.get("error")}
    was = {i["key"]: i for i in (before or {}).get("items", [])}
    is_ = {i["key"]: i for i in now.get("items", [])}
    changed = []
    for key in sorted(set(was) & set(is_)):
        moved = {f: [was[key].get(f), is_[key].get(f)] for f in COMPARED
                 if was[key].get(f) != is_[key].get(f)}
        if moved:
            changed.append({"key": key, "title": is_[key].get("title"), "moved": moved})
    return {
        "schema": "hange-changes/1", "date": now.get("date"), "since": (before or {}).get("date"),
        "new": [is_[k] for k in sorted(set(is_) - set(was))] if before else [],
        "gone": [{"key": k, "title": was[k].get("title"), "source": was[k].get("source")}
                 for k in sorted(set(was) - set(is_)) if was[k].get("source") not in failed],
        "changed": changed, "first_snapshot": before is None,
    }


def deliver(out_root, date, drive, base, tok, graph):
    folder = os.path.join(out_root, "EE", "hange", date)
    with open(os.path.join(folder, "hange.json"), encoding="utf-8") as fh:
        snapshot = json.load(fh)
    changes = diff(graph.json_at(drive, "%s/hange/latest.json" % base, tok), snapshot)
    with open(os.path.join(folder, "changes.json"), "w", encoding="utf-8") as fh:
        json.dump(changes, fh, ensure_ascii=False, indent=2)
    blob = lambda o: json.dumps(o, ensure_ascii=False, indent=2).encode("utf-8")
    graph.upload(drive, "%s/hange/%s/changes.json" % (base, date), blob(changes), tok)
    graph.upload(drive, "%s/hange/%s/hange.json" % (base, date), blob(snapshot), tok)
    graph.upload(drive, "%s/hange/latest.json" % base, blob(snapshot), tok)   # last
    return changes


def line(snapshot, changes=None):
    """Counts only, for a public log."""
    parts = ["%s %s" % (n, s.get("items", "FAILED")) for n, s in snapshot["sources"].items()]
    text = "hange.ee %s: %d (%s)" % (snapshot["date"], len(snapshot["items"]), ", ".join(parts))
    if changes is not None:
        text += " -- %s" % ("first snapshot" if changes["first_snapshot"] else
                            "%d new, %d gone, %d changed" % (len(changes["new"]),
                                                             len(changes["gone"]),
                                                             len(changes["changed"])))
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(description="hange.ee's public lists, Estonia below the register.")
    ap.add_argument("command", choices=("collect", "deliver"))
    ap.add_argument("--out", default="work")
    ap.add_argument("--date", required=True)
    args = ap.parse_args(argv)
    if args.command == "collect":
        snapshot = collect(args.out, args.date)
        print(line(snapshot))
        return 0 if snapshot["items"] else 1
    import country
    import deliver_graph as graph
    drive = graph.env("GRAPH_DRIVE_ID")
    base = country.destination(graph.env("GRAPH_DEST_ROOT"), "EE")
    changes = deliver(args.out, args.date, drive, base, graph.graph_token(), graph)
    with open(os.path.join(args.out, "EE", "hange", args.date, "hange.json"), encoding="utf-8") as fh:
        print(line(json.load(fh), changes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
