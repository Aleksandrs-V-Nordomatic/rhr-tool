"""Transport for Estonia: one procurement, whole, into a home.

The register builds the archive. One request returns every public document of a procurement
as a single zip, and the caller assembles nothing — so this file is short, and it is short
for a reason worth writing down rather than for lack of care.

WHAT IS THE SOURCE OF TRUTH ABOUT WHAT A TENDER CONTAINS. The archive, and the catalogue is
joined onto it. Members are enumerated from the zip because a member the catalogue does not
list still exists, and silence about it is the failure this tool is written against; the
catalogue is then matched in by file name for what only it knows — the document's title, its
type, and when it last changed.

WHAT ESTONIA DOES NOT HAVE, MEASURED RATHER THAN ASSUMED. The archive holds no artefact the
register generates fresh per request: two downloads of the same procurement, a second apart,
gave byte-identical members on every file — 9 of 9 and 2 of 2. So there is nothing here that
has to be delivered but kept out of the comparison, and every member counts. A country whose
portal stamps its own rendering of the notice with the moment it was made needs that split;
this one does not, and adding it anyway would be machinery guarding against a failure that
cannot happen here.

THE ONE THING THAT MUST NOT BE CACHED is the download address. It works once. A second
request with the same address is answered as though the documents were gone, so a retry asks
the register for a new address rather than reusing the one it holds — which is why `archive`
calls `ee_page.package` itself instead of taking a URL.

    python3 ee_fetch.py 314707 --out work/EE
"""
import argparse
import hashlib
import io
import json
import os
import sys
import time
import urllib.request
import zipfile

import ee_page
import net

try:
    import changes as changes_mod
except Exception:                          # the fingerprint is optional for a bare fetch
    changes_mod = None


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _safe(name):
    """A member name that cannot climb out of the home it is written into."""
    name = name.replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ord(ch) >= 32).strip().lstrip(".")
    return name or "unnamed"


def archive(pid, timeout=600, tries=net.TRIES):
    """The whole procurement, one request per attempt. Returns the archive's bytes.

    THE RETRY IS AROUND THE ADDRESS, NOT INSIDE IT, and that is the whole point of this
    function existing. The register's download address works exactly once; a second request
    with the same one is answered as though the documents were gone. So the shared retry
    policy cannot simply be handed this URL: its retries would all be retries of an address
    that has already been spent, and each would report a procurement with no documents.

    MEASURED, AND IT COST A TENDER. With a single attempt and no retry at all, one download
    in a four-day window died on a `ConnectionResetError` — the ordinary failure `net.py`
    exists to absorb — and the procurement was reported lost. One attempt is not a policy;
    it is the absence of one.

    So each attempt asks for a fresh address and then downloads it, and the backoff between
    attempts is the shared one. `net.open_url` is still given `tries=1` for exactly the
    reason above: the loop that may retry is this one, because it is the only one that can
    also renew what a retry needs.
    """
    last = None
    for attempt in range(tries):
        try:
            request = urllib.request.Request(ee_page.package(pid),
                                             headers={"User-Agent": ee_page.UA})
            data, headers = net.open_url(request, timeout=timeout, tries=1,
                                         opener=ee_page.session().opener, log=ee_page.log)
            if not data.startswith(b"PK"):
                # The status line proves nothing on its own; the magic number is the check
                # that does. An HTML error page arrives with a 200 as readily as an archive.
                kind = headers.get("content-type") or headers.get("Content-Type") or "?"
                raise RuntimeError(
                    "ee_fetch: %s did not answer with an archive (%s, %d bytes)"
                    % (pid, str(kind).split(";")[0], len(data)))
            return data
        except ee_page.Refused:
            raise                       # the register says there is nothing to download
        except Exception as exc:
            if not net.retryable(exc):
                raise
            last = exc
            if attempt == tries - 1:
                break
            wait = net.delay(attempt, exc)
            ee_page.log("  %s: retrying the archive in %.0fs after %s: %s"
                        % (pid, wait, type(exc).__name__, str(exc)[:120]))
            time.sleep(wait)
    raise net.Unreachable("ee_fetch: %s did not download after %d attempt(s): %s: %s"
                          % (pid, tries, type(last).__name__, last)) from last


def unpack(data, home, catalogue):
    """Every member to `originals/`, joined to the catalogue where the catalogue knows it."""
    listed = {}
    for document in catalogue or []:
        name = (document.get("filename") or "").casefold()
        if name:
            listed.setdefault(name, document)

    originals = os.path.join(home, "originals")
    os.makedirs(originals, exist_ok=True)
    records, seen = [], set()
    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
        for member in bundle.namelist():
            if member.endswith("/"):
                continue
            payload = bundle.read(member)
            bare = member.replace("\\", "/").split("/")[-1]
            filename = _safe(bare)
            stem, dot, ext = filename.rpartition(".")
            n = 1
            while filename.casefold() in seen:
                n += 1
                filename = "%s (%d)%s%s" % (stem or filename, n, dot, ext)
            seen.add(filename.casefold())

            with open(os.path.join(originals, filename), "wb") as fh:
                fh.write(payload)
            entry = listed.get(bare.casefold())
            records.append({
                "id": (entry or {}).get("doc_id") or "member:%s" % member,
                "title": (entry or {}).get("title") or bare,
                # What the register calls this kind of document — a specification, an
                # information document, an outcome. `changes` compares it, so a document
                # reclassified in place is news rather than nothing.
                "type_code": (entry or {}).get("type_code"),
                "subtype": (entry or {}).get("subtype"),
                "section": "current",
                # The register's own note of when this document last moved. The byte digest
                # below is what actually decides; this is what lets a person be told WHICH
                # document the buyer touched, and when.
                "publish_date": (entry or {}).get("publish_date"),
                "catalogued": entry is not None,
                "member": member,
                "download": None,
                "files": [{"filename": filename,
                           # `path` is what the extractor opens, relative to the home.
                           "path": "originals/%s" % filename,
                           "original_name": bare,
                           "sha256": _sha256(payload),
                           "bytes": len(payload)}],
            })
    return records


def extract(home):
    """Turn the originals into Markdown, then give each one its permanent address.

    `normalize.py` is the same code in every country tool and knows nothing about any of
    them — it reads `manifest.json` and writes `normalized/`. What it does not do is name the
    results the way a reader addresses them, so that happens here: `doc/<digest>.md`, where
    the digest is `changes.document_key` over the ORIGINAL bytes and the document's place.
    An unchanged document therefore keeps the same address for ever and costs nothing to
    re-deliver, and a superseded one stays readable instead of being overwritten.
    """
    try:
        import normalize
    except ImportError as exc:
        return {"documents": [], "unreadable_files": [],
                "skipped": "normalize unavailable: %s" % exc}

    out = os.path.join(home, "normalized")
    stdout = sys.stdout
    try:
        sys.stdout = io.StringIO()             # the extractor narrates; a fetch does not
        normalize.main(["--in", home, "--out", out])
    finally:
        sys.stdout = stdout

    with open(os.path.join(out, "manifest_normalized.json"), encoding="utf-8") as fh:
        normalized = json.load(fh)

    doc_dir = os.path.join(home, "doc")
    os.makedirs(doc_dir, exist_ok=True)
    for entry in normalized.get("documents", []):
        if entry.get("also_listed_under") or not entry.get("markdown_path"):
            continue
        source = os.path.join(out, entry["markdown_path"])
        if not os.path.exists(source):
            continue
        key = (changes_mod.document_key(entry.get("original_sha256"), entry.get("source"))
               if changes_mod else (entry.get("original_sha256") or "")[:16])
        with open(source, encoding="utf-8") as fh:
            text = fh.read()
        with open(os.path.join(doc_dir, "%s.md" % key), "w", encoding="utf-8") as fh:
            fh.write(text)
        entry["doc"] = "doc/%s.md" % key
    return normalized


def _with_text(documents, normalized):
    """Point each index entry at the Markdown its bytes produced."""
    by_sha = {}
    for entry in normalized.get("documents", []):
        if entry.get("doc"):
            by_sha.setdefault(entry.get("original_sha256"), []).append(entry)
    out = []
    for row in documents:
        texts = by_sha.get(row["sha256"], [])
        out.append(dict(row,
                        doc=texts[0]["doc"] if texts else None,
                        chars=sum(t.get("markdown_chars", 0) for t in texts) or None))
    return out


def _write(home, name, payload):
    with open(os.path.join(home, name), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def fetch(row, out_root, kind=None, with_text=True, procurement=None):
    """One procurement into `<out_root>/tenders/<pid>/`, in the delivery shape.

    `index.json` is written LAST and `state.json` after it, exactly as every tool in this
    family promises: the index existing is a reader's proof that the home is whole, and a
    fingerprint that landed before the documents it vouches for would let the next run skip
    text that is not there.
    """
    pid = str(row.get("pid") or row.get("procurementId"))
    kind = kind or row.get("kind") or "tender"
    procurement = procurement or ee_page.collect(row.get("record") or row, kind)

    home = os.path.join(out_root, "tenders", pid)
    os.makedirs(home, exist_ok=True)

    catalogue = list(procurement.pop("documents", []))
    withheld = list(procurement.pop("withheld_documents", []))

    # A PROCUREMENT WITH NOTHING PUBLIC IS A HOME, NOT A FAILURE. The register serves the
    # notice and withholds the documents often enough to matter — a restricted procedure
    # publishes its specification to the qualified only. That is a fact about the tender and
    # the day says so; it is not the day arriving short.
    records, data = [], b""
    if catalogue:
        data = archive(pid)
        with open(os.path.join(home, "%s.zip" % pid), "wb") as fh:
            fh.write(data)
        records = unpack(data, home, catalogue)

    manifest = {"pid": pid, "procurement_id": pid,
                "reference": procurement.get("ref"),
                "archive": "%s.zip" % pid if records else None,
                "archive_sha256": _sha256(data) if data else None,
                "archive_bytes": len(data),
                "documents": records,
                # Listed rather than dropped: a record the register published without giving
                # anybody the bytes is still a record, and its arrival is news of exactly the
                # same kind as a document's. `changes` reads this key.
                "withheld_records": [dict(w, files=[]) for w in withheld]}
    _write(home, "procurement.json", procurement)
    _write(home, "manifest.json", manifest)

    index = {
        "schema": "index/1",
        "pid": pid,
        "ref": procurement.get("ref"),
        "country": "EE",
        "kind": kind,
        "source": "RHR",
        "link": procurement.get("link"),
        "documents_link": procurement.get("documents_link"),
        "title": procurement.get("title"),
        "buyer": procurement.get("buyer"),
        "deadline": procurement.get("deadline"),
        "status": procurement.get("status"),
        "status_text": procurement.get("status_text"),
        "procedure": procurement.get("procedure"),
        "procedure_text": procurement.get("procedure_text"),
        "value": procurement.get("value"),
        "cpv_main": procurement.get("cpv_main"),
        # What the catalogue said and what the archive held, kept apart on purpose: a gap
        # between them is a fact about the delivery, not a rounding error.
        "catalogued_documents": len(catalogue),
        "withheld_documents": len(withheld),
        "documents": [{
            "id": r["id"],
            "name": r["files"][0]["original_name"],
            "title": r["title"],
            "sha256": r["files"][0]["sha256"],
            "bytes": r["files"][0]["bytes"],
            "original": "originals/%s" % r["files"][0]["filename"],
            "type_code": r["type_code"],
            "changed_at": r["publish_date"],
            "catalogued": r["catalogued"],
        } for r in records],
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _write(home, "index.json", index)

    normalized = extract(home) if (with_text and records) else {"documents": [],
                                                                "unreadable_files": []}
    if normalized.get("documents"):
        index["documents"] = _with_text(index["documents"], normalized)
        index["text_documents"] = sum(1 for e in normalized["documents"]
                                      if e.get("markdown_path"))
        index["chars"] = normalized.get("chars", 0)
        _write(home, "index.json", index)          # rewritten with the text it now names

    state = None
    if changes_mod is not None:
        # STAMPED WITH THE VERSIONS THAT PRODUCED IT, AND WITH ESTONIA'S PARSER. Left
        # unstamped, a fingerprint cannot tell a buyer's amendment from our own extractor
        # being upgraded under a procurement that never moved.
        import country as country_mod
        state = changes_mod.fingerprint(
            pid, procurement, manifest, normalized,
            tool=changes_mod.pipeline_version(),
            parser=changes_mod.parser_version(files=country_mod.parser_files("EE")))
        _write(home, "state.json", state)

    return {"pid": pid, "ref": procurement.get("ref"), "kind": kind, "home": home,
            "documents": len(records), "catalogued": len(catalogue),
            "withheld": len(withheld),
            "uncatalogued": sum(1 for r in records if not r["catalogued"]),
            "bytes": len(data), "index": index, "state": state,
            "title": procurement.get("title"), "buyer": procurement.get("buyer"),
            "deadline": procurement.get("deadline"), "value": procurement.get("value"),
            "cpv_main": procurement.get("cpv_main")}


def main(argv=None):
    ap = argparse.ArgumentParser(description="One Estonian procurement into a home.")
    ap.add_argument("reference", help="the number a person quotes, e.g. 314707")
    ap.add_argument("--out", default="work/EE")
    args = ap.parse_args(argv)

    import ee_targets
    row = ee_targets.one(args.reference)
    if row is None:
        raise SystemExit("ee_fetch: the register served no row for %s" % args.reference)
    done = fetch(row, args.out)
    print("%s (%s): %d document(s), %d withheld, %.1f MB -> %s"
          % (done["ref"], done["pid"], done["documents"], done["withheld"],
             done["bytes"] / 1048576.0, done["home"]))
    return done


if __name__ == "__main__":
    main()
