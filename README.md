# rhr-tool

Downloads every public document of an Estonian procurement and turns it into text.
Deterministically, with no model in the main path, and with every file it could not read
named rather than quietly missing.

**Proprietary. No licence is granted — see [LICENSE](LICENSE).** Issues and pull requests
are closed and unreviewed.

Nothing here decides which procurements matter. The tool fetches what it is pointed at,
extracts it, and says what it could not read; the interest, the destination and the schedule
all arrive from outside as configuration.

## One country

This tool reads one country: Estonia, from RHR — the state register at `riigihanked.riik.ee`,
run by the State Shared Service Centre. `country.py` names it and nothing else, and
`--country` has no default: a run launched without it stops rather than publishing under a
folder the tool guessed, which is a failure that otherwise succeeds quietly.

There is one register and only one. EU-scale tenders, national ones and small purchases are
published in the same place, so there is no second platform to reconcile and no below-threshold
lane to miss.

**The register answers with data rather than with a page.** The site is a single-page
application over a public JSON service, and that service can be asked directly. Nothing is
scraped: the fields arrive named and typed, and they do not move when somebody restyles a page.
Everything after the read — the pack, the digests, the index, the change comparison, the
delivery — is deliberately the same as every other country tool in this family, so the shape a
reader sees does not depend on which register it came from.

**And it lets any address in.** Every request in this repository was made from an ordinary work
machine with no proxy and none was refused. So a day is one runner in one pass: there are no
shards, no address lottery and no `probe` step, because a check that can only answer yes teaches
a reader that the failure it names happens here, and it does not.

## What it does

```
search  ─window─→  rows (title · buyer · CPV name · state · procedure · deadline)
                          │
                     gate │  ← decided here, on what the search already returned
                          ↓
        ─3 calls─→  facts + catalogue  ─1 request─→  one archive  ─extract─→  Markdown
                                                                        │
                                                                        └── what could not be
                                                                            read, named with
                                                                            size and digest
```

The gate costs nothing. Elsewhere, deciding what is worth downloading means fetching a card per
procurement first; here the search row already carries the title, the buyer, the classification's
name, the state, the procedure and the deadline, so the whole window is decided on what discovery
returned and the first extra request of a run is made for something already worth keeping.

## Use

```bash
python3 eis_tool.py day 2026-09-04 --country EE --out work
python3 eis_tool.py day 2026-09-01 --to 2026-09-04 --country EE --out work
python3 eis_tool.py scans --date 2026-09-04 --country EE --out work
python3 eis_tool.py doors --country EE --out work
python3 eis_tool.py extract --pack out
```

In CI: **ee-day.yml**, one runner, one pass, and a delivery step behind it.

`day` takes a **window, not a date**, and both ends are inclusive. A night that did not run is a
day of procurements nobody reads and the register does not publish them again, so a missed run is
caught up by widening the window rather than by running twice. One request answers a fortnight as
easily as a day.

`doors` reads the dynamic purchasing systems standing open for entry. That is a stock, not a
stream: a system announced in March is exactly as open in September, and purchases made inside one
are never advertised again — so it is read on demand rather than as a card each morning.

The window travels with its watch list. `--targets` names the references somebody is still
deciding about; they ride with the window in one pass rather than a second run, because two runs
are two draws at one register for one date and two answers about what that date contained. The
recall gate does not apply to them — it decides what is worth fetching for the *first* time, and
these already have a card.

Requirements: Python 3.12, `pip install -r requirements.txt` (pinned exactly), plus `p7zip-full`
and LibreOffice for 7z archives, Word 97 attachments and open-format spreadsheets.

## Three ids, and they are not interchangeable

```
procurementReferenceNr   what a person quotes, and what a card is keyed on   314707
procurementId            what the search returns and the link is built from  10739244
procurementOldId         what the DOCUMENT side understands, and only it     10773064
```

Ask the document side with the search's id and it answers that there is no such procurement,
which reads like a withdrawn tender rather than like the wrong number. Resolving the third id is
what the first extra request of a fetch is for, and it is the only reason that step exists.

## Three ways this register lies quietly

All three answer 200 with a well-formed body, and each is guarded in code rather than left to a
caller to remember. Every one was measured against the live register on 4 September 2026.

**The window is exclusive at its start.** `Begin=2026-09-02, End=2026-09-03` returns the third
and not the second; `Begin=D, End=D` returns nothing at all. So the day D is asked for as
`Begin = D-1, End = D`. A caller reasoning by analogy with an inclusive range gets an empty
answer, delivers an empty day, and calls it complete — which reads exactly like a public holiday.

**A filter key it does not recognise is ignored, not refused.** `procurementReferenceNr` — the
name the *rows* use for the reference number — is not the name the *filter* uses, and asking with
it returns the register's whole answer under a 200. A run watching one card would have fetched
five hundred procurements and reported success. Every answer is therefore checked against what
was asked for, and a filter that plainly did not bite stops the run.

**Five hundred is a cap and nothing says so.** The answer is a bare array with no total and no
next page. Exactly five hundred rows means it was cut and the rest is named nowhere, so it is
raised rather than returned. A working day publishes on the order of twenty-five notices, so a
window has to be weeks wide before this can fire; the one place it genuinely does is a first
sweep of everything standing open.

Two more habits, both cheap to know and expensive to rediscover. Before anything else the caller
must GET `security/current-user`, which sets an `XSRF-TOKEN` cookie, and send that value back as
an `X-XSRF-TOKEN` header on everything after — without it the answer is 401, and nothing in the
API's shape hints at it. A body with no `orderBy` is refused the same way, with a 500 that reads
like a broken route rather than like a missing argument. And a **500 carrying
`{"actionId": …, "errorStack": "-"}` is this register's catch-all for a route it does not have**;
a resource that genuinely does not exist answers `404 PROCUREMENT_NOT_FOUND`. Read a 500 here as
"you asked the wrong question", never as a permission wall.

## What one tender looks like

```
pack/
  procurement.json    the tender's own facts — the codes the register states, each with the
                      register's own word for it beside it, never instead of it
  manifest.json       what was downloaded, with sha256 per file
  normalized/         one Markdown document per readable file, plus the audit list
  index.json          what is here and what is worth opening — carries the moment the
                      register says each document last changed
  llm/                what the decoder could not read, read anyway — local OCR by default,
                      a hosted model only if one is configured. Marked `ocr-fallback` or
                      `llm-fallback` per entry, never merged into `normalized/`, and not
                      delivered: it stays in the pack and the run's artifact.
  <pid>.zip           the archive the register built
```

The directory is named `llm/` for a lane that has not been model-first since Tesseract became its
default. Renaming it would move paths the manifest already hands out, so the name stays and this
note carries the correction.

## The download address works once

The register issues a single-use address for a procurement's archive, and a second request with
that same address is answered as though the documents were gone. It is the one failure in this
country that returns a **wrong result rather than an error**: a retry with the saved address
reports that the documents have disappeared, when they are sitting right there.

So nothing caches it. `ee_fetch.archive` asks `ee_page.package` for a fresh address immediately
before the download, and a retry is a retry of the download rather than of an address that has
already been spent.

## What gets published

A tender has one home. A day is a list of what moved. This shape is the tool's own and is what a
reader may rely on:

```
work/EE/
  tenders/<pid>/              the tender, complete, whenever each part of it arrived
    procurement.json            its facts, as above
    manifest.json               what was downloaded, sha256 per file
    doc/<digest>.md             the Markdown, one file per document, named for its source
    normalized/manifest_normalized.json
    structure.json              Word numbering, when the tender had any
    index.json                  what is here and what is worth opening — written LAST
    state.json                  the fingerprint the next run compares against
    seen.json                   when it was first and last looked at
    runs/<date>.json            what that date's run found — one file per date
    <pid>.zip                   the whole tender, one request
  <date>/
    changes.json              what moved — read this first
    day.json                  the list, and the proof the day is there to be read
  doors/{index.json,doors.jsonl}
```

**`GRAPH_DEST_ROOT` names the folder that CONTAINS the country folders, not one of them.** The
code is appended by the tool. Configuring the full path instead would put the country in two
places that can disagree, and the way that disagreement surfaces is a day of one country's
tenders sitting in another's folder — uploaded cleanly, indexed validly, with nothing anywhere
saying so. A root already ending in a country code is refused, and so is one copied across from
another country's deployment.

**The day folder holds no tender bytes and no per-tender file.** A day is a statement about what a
run did; the tenders it did it to are addressed from here. `changes.json` and `day.json` answer
everything a consumer asks of a day, and both are small — so a reader takes the two, then fetches
only the tenders they point at. `day.json` goes last of all, and a reader that lists folders
instead of reading it will read the wrong day.

**The window it covers is stated, not inferred.** `day.json` carries `window: {from, to}` beside
`date`, and the folder is named for the end of the range. A three-day catch-up therefore lands
where tomorrow's reader looks, and says what it actually covered.

**A tender delivered again uploads only the documents that were not there before.** Its name is
the digest of the file it came from, so an unchanged document has the same address every day and
there is nothing to re-send. A superseded document is not deleted — a digest cannot name two
different files, so the previous version stays readable and `runs/` says which day it stopped
being current. A tender that did not move writes only `seen.json` and `runs/<date>.json`.

**An index that exists was written after everything it names**, and `state.json` after the index.
The first is the reader's proof that a home is whole; the second is the next run's proof of what
it may skip, and a fingerprint that landed before the documents it vouches for would let tomorrow
carry over text that is not there.

The shape above is this repository's contract. Which tender matters is not: no judgement is made
here and none can be.

## What changed, and how it is known

`changes.json` names every tender the window touched and what moved about it — `new`, `changed` or
`unchanged` — with the values on both sides of each move. A day on which two deadlines shifted is
a few kilobytes; the tenders themselves are not in it.

Everything is compared over sha256 of **original** bytes, never over the Markdown. `normalize.py`
is deterministic for a given version, but two versions of it may render one unchanged PDF
differently, and a diff taken over the text would report that as the buyer replacing a document.
The extractor's own version rides in `state.json`, so *the text was extracted again* is a
different sentence from *the tender changed*.

**Nothing here is generated fresh per request, and that was measured rather than assumed.** Two
downloads of the same procurement a second apart returned byte-identical members on every file.
A register that stamps its own rendering of the notice with the moment it was made needs a split
between what is delivered and what is compared; this one does not, so every member counts and
there is no machinery guarding a failure that cannot happen here.

**The facts cannot drift with a translation, and that is a property of the source.** They arrive
as codes — the state is `"11"`, the procedure is `"LM"` — and a code does not translate. The
register's own word for each is looked up from its classifier and carried beside the code, never
instead of it, so a procedure renamed in the register changes a caption and not a fact. A tool
reading a portal that renders words has to skip half its comparison whenever the page arrives in
the other language; nothing here does.

**The facts still have their own version, for a different reason.** They are read by `ee_page`,
not by the extractor: one more field read, or a value that used to come back null, changes facts
across the whole corpus in a night. Compared blind that is an amendment reported against every
buyer in the register, from this side of the wire. So a procurement read by a different parser has
none of its facts compared, the run is spent refreshing the fingerprint so the next one compares
clean, and no document travels for it.

Where the previous state comes from is the destination itself. A run remembers nothing — the
runner is new and the previous run's artifact is exactly what a consumer cannot reach — so each
tender's `state.json` is read back off the drive with the credential the delivery already holds.
`compared_against: "drive"` in the delivered `changes.json` says so.

**What that buys, and what it costs.** A delta delivery trusts `state.json` about what is already
on the drive, so a document deleted by hand is not noticed and not replaced. The remedy is one
deletion — remove that tender's `state.json` and the next run delivers it whole.
`runs/<date>.json` is never read by the delivery and there is one per date, so `state.json` can be
rebuilt from the runs if it is ever lost.

## Properties worth knowing before changing anything

**Partial success is failure.** If any expected record or file is missing the run exits non-zero
and writes nothing to the success path. Publishing a partial tender would also record a
fingerprint saying that is what the procurement is, and every later run would agree with it.

**A procurement with nothing public is a home, not a failure.** The register serves the notice and
withholds the documents often enough to matter — a restricted procedure publishes its
specification to the qualified only. That is a fact about the tender, and `index.json` states the
catalogue count and the withheld count separately so a gap between them is visible rather than
inferred.

**Nothing is dropped on a guess about importance.** Usefulness is never judged — that would need a
model. Each file is classified only by whether a decoder recovered characters from it. Everything
readable is extracted in full; everything else is listed by name, size and digest.

**Same bytes in, same text out.** Dependencies are pinned exactly and walk orders are sorted. Two
container formats are decided by their bytes rather than by the name a buyer typed: an
open-format spreadsheet is a ZIP with none of the OOXML members, and without recognising its
stored media type it would be *unpacked* and a reader handed `content.xml` instead of a price
table. A signed container carries the same member with a different value and must keep falling
through to the archive path, so the rule matches the value and never the member's presence.

**An empty window over working days is reported as broken, not as quiet.** This register publishes
on the order of twenty-five notices a working day and none at the weekend — measured across
20 August to 4 September 2026: 312 notices, and both Saturdays and both Sundays empty. So zero
over a range containing no working day is the country resting, and zero over a range that
contains one is our own discovery breaking. `day.json` carries `discovery_failed` and refuses to
call itself complete, because the alternative is a green run, a complete day, an empty morning,
and nothing to tell it from a holiday.

**A hole in the watch is not the day arriving short.** The day is the window; a watched card is a
standing question asked of it. A watched reference the register will not serve is counted in
`coverage.watch_holes` and named in `lost`, and it leaves `complete` alone — otherwise every
night would be incomplete until somebody edited the board, and a flag that is always on is one
nobody reads on the night it starts meaning something.

**One retry policy, and it lives in `net.py`.** Every request this tool makes goes through it: the
honest exception set — `OSError` and `http.client.HTTPException`, because a reset arrives as
`RemoteDisconnected` and that is neither a `URLError` nor a `TimeoutError` — a budget that
outlasts a register hiccup, `Retry-After`, and the parse inside the retry because a service under
load answers 200 with an error page.

**The archive download retries around its address rather than inside it.** Its URL is spent by the
time a retry would happen, so the shared policy cannot simply be handed it: each attempt asks the
register for a fresh address and then downloads that. The alternative was tried and cost a tender —
one download in a four-day window died on an ordinary connection reset, with no retry, and the
procurement was reported lost.

## The recall gate

Which notices are worth fetching is not decided here. `policy.py` holds the rule and nothing else:
recall terms and CPV prefixes arrive from the environment as JSON, so this repository names no
industry, no trade and no target, and a reader learns the shape of the filter without learning
what anyone points it at.

**The gate reads two texts here, and it has nothing else.** The title, and the Estonian name of
the classification the buyer chose. The search row carries no description at all —
`shortDescription` comes back empty on every row the register serves — and no classification
*code*, only its name. So the code clauses in a policy are silent on a first sighting and bind
only where a code is already known, and the word list is doing all the work at the moment that
matters. A buyer who writes three vague words and then classifies the purchase exactly is the
common shape, and the second text is what catches it.

**Every run of punctuation is folded to one space and the whole text is padded with one.** That is
what makes a short term safe to write. A list for this language needs entries like ` ats `, ` kv `
and ` vk `, each written with spaces around it precisely so it cannot match inside a longer word.
Without the folding, `KV,` and `(VK)` never match because of the punctuation, and a term at the
very start or end of a title never matches because there is no space beyond it. Both failures are
silent and both drop tenders.

**The gate is required, not optional, in the scheduled lane.** `policy.load_policy` fails open by
design: an unreadable policy returns `None` rather than dropping everything. Inside a library that
is right; for an unattended night it would mean fetching every archive the window holds from a
state register because a secret was misspelt. `ee-day.yml` therefore checks that the policy parses
before the register is touched, and stops if it does not.

**And the policy comes from the secret or the run does not happen.** `ee_policy.example.json` is a
deliberately unrelated illustration — office printing — so that this repository discloses nothing
about what any deployment actually hunts for. It exists to be copied into `EE_POLICY` and to
document the shape, never to be run against. A scheduled night with no secret stops rather than
falling back: run against the example it would fetch almost nothing, deliver a valid day and
report success, and an empty morning reads exactly like a quiet one. A sibling country's secret
name set here stops the run for the same reason, rather than loading nothing and fetching all.

## Scans, and the account this does not need

There is no model in extraction. `assist.py` is a quarantined fallback that reads **only** the
files the deterministic extractor already listed as unreadable — scans with no text layer — and
writes **only** into `llm/`, cached by content digest so a re-run costs nothing and returns
identical bytes. Drawings are never sent. Consumers treat that text as grounds to look, never as a
located quote.

**The default reader is Tesseract with the Estonian language pack, on the runner: no account, no
API key, no billing relationship, nothing to migrate.** An automation whose credential belongs to
a private sign-up is a dependency nobody owns, and it fails at the worst possible moment. The
volume argues for it too: the deterministic extractor reads most tenders whole, which leaves this
lane an ordinarily empty queue.

A hosted model is available for the day a scan defeats OCR — `--provider gemini` with
`GEMINI_API_KEY` — and adding another is one entry in `PROVIDERS`. Each result records which
reader produced it: `ocr-fallback` or `llm-fallback`, never merged.

Nothing this lane does may fail a tender, and the guard around it catches every exception rather
than one class.

## Tests

```bash
python3 -m unittest discover -s tests -t tests
```

Everything is offline. The register's answers are fixtures, so a test never needs the network and
never goes red on a public holiday. What the tests hold is mostly the three quiet lies above:
every one of them was found by asking the live register a question and reading an answer that
looked right.
