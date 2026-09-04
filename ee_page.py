"""The Estonian source: one procurement in RHR, read through the register's own API.

RHR does not have to be parsed, and that is the fact this whole file rests on. The site is a
single-page application over a public JSON service, and that service can be asked directly:
the fields arrive named and typed, and they do not move when somebody restyles a page. There
is no label table here, no line-pair reader and no login-form detection, because there is no
page to read.

WHAT THAT BUYS, AND IT IS MORE THAN TIDINESS. The facts a page-scraping country compares
between runs are display strings, and a portal that serves the same procurement in two
languages moves ten of them at once for no reason anybody made. Here `procurementStatus` is
`"11"` and `procurementProcessType` is `"LM"` — codes, not words. A code does not translate,
so a comparison over these fields answers the question it was asked. The words are looked up
once from the register's own classifier and kept BESIDE the code, never instead of it.

THE ONE HABIT THAT CANNOT BE WORKED OUT BY LOOKING AT A REQUEST. Before anything else the
caller must GET `security/current-user`, which sets an `XSRF-TOKEN` cookie, and send that
value back as an `X-XSRF-TOKEN` header on everything after. Without it the answer is 401.
Nothing in the API's shape hints at it; it is written down here because the next reader will
otherwise spend a morning on a service that looks closed and is not.

THREE IDS FOR ONE PROCUREMENT, AND THEY ARE NOT INTERCHANGEABLE:

    procurementReferenceNr   what a person quotes and what a card is keyed on — 314707
    procurementId            what the search returns and the page address is built from — 10739244
    procurementOldId         what the DOCUMENT side understands, and only it — 10773064

Ask the document side with `procurementId` and it answers that there is no such procurement,
which reads like a withdrawn tender rather than like the wrong number.

AND THE ERROR THAT IS NOT AN ERROR. A 500 carrying `{"actionId": …, "errorStack": "-"}` is
this register's catch-all for a route it does not have. A resource that genuinely does not
exist answers `404 PROCUREMENT_NOT_FOUND`. Read a 500 here as "you asked the wrong question",
never as a permission wall.

    python3 ee_page.py 314707        # the procurement and its documents, as JSON
"""
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request

import net

BASE = "https://riigihanked.riik.ee"
API = BASE + "/rhr/api/public/v1"
# Where the register hands out its session and the token that goes with it.
CURRENT_USER = API + "/security/current-user"
SEARCH = API + "/search/procurements"
VERSIONS = API + "/procurement/%s/proc-versions"
GENERAL_INFO = API + "/proc-vers/%s/general-info"
CATALOGUE = API + "/proc-vers/%s/documents/general-info"
# The package address, and the one answer that must never be saved: see `package`.
PACKAGE = API + "/procurement/%s/documents-temp-url"
DOMAIN = API + "/domains/%s/%s/values"

# What a person clicks. The application addresses a procurement by `procurementId`, so this is
# the one place the second id is the right one — a link built from the reference number opens
# nothing, and one built from the document id opens somebody else's tender.
VIEW = BASE + "/rhr-web/#/procurement/%s/general-info"
DOCUMENTS_VIEW = BASE + "/rhr-web/#/procurement/%s/documents"

# The tool family's name, not this country's portal, and deliberately the same string every
# country fork sends: it identifies the client to an operator who asks and discloses nothing
# about who is running it.
UA = "Mozilla/5.0 (compatible; eis-tool)"


# WHICH POPULATION A ROW BELONGS TO, DERIVED FROM THE ROW AND NOTHING ELSE.
#
# Three things are published through one search and a reader asks a different question of
# each, so the day has to say which is which rather than let the date decide.
#
#   tender        a competition somebody can bid for.
#   consultation  `TU`, turu-uuring. The buyer publishes a DRAFT technical specification and
#                 asks for comments before the tender exists. Answering it is how a
#                 specification comes to describe something anybody can actually deliver.
#   door          a dynamic purchasing system standing open for entry — state 14. Suppliers
#                 apply at any time and purchases made inside it are never advertised again,
#                 so a door missed is a channel missed rather than one tender.
#
# Read off the row because the row already says it. Storing the kind on a card would be one
# more thing that can be wrong, and asking the register again would be a request that returns
# what we already had.
CONSULTATION_PROCEDURES = ("TU",)
DOOR_STATES = ("14", "15")
QUALIFICATION_PROCEDURES = ("QS",)


def kind_of(row):
    """`tender`, `consultation` or `door` for one search row."""
    if (row.get("procurementProcessType") or "") in CONSULTATION_PROCEDURES:
        return "consultation"
    if (str(row.get("procurementStatus") or "") in DOOR_STATES
            or (row.get("procurementProcessType") or "") in QUALIFICATION_PROCEDURES):
        return "door"
    return "tender"


class Refused(RuntimeError):
    """The register answered, and the answer was that this procurement is not there."""


class Session(object):
    """One cookie jar and one XSRF token, reused by every request in a run.

    An object rather than a function per request, because the token is only valid inside the
    session that issued it: a fresh jar per call would mean two requests for every one, and a
    token arriving with a different `JSESSIONID` than the request it rides on is answered with
    a 401 rather than with data.
    """

    def __init__(self, timeout=60):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))
        self.opener.addheaders = [("User-Agent", UA)]
        # The shared retry policy is handed the opener rather than replacing it: the jar is
        # this object's whole reason to exist, and a retry must not start a new session.
        net.open_url(CURRENT_USER, timeout=timeout, opener=self.opener, log=log)
        self.token = next((c.value for c in self.jar if c.name == "XSRF-TOKEN"), None)
        if not self.token:
            raise RuntimeError(
                "ee_page: RHR issued no XSRF-TOKEN. Everything after this answers 401 "
                "without it, so the run stops here rather than reporting a closed register.")

    def _headers(self, extra=None):
        headers = {"User-Agent": UA, "Accept": "application/json, text/plain, */*",
                   "X-XSRF-TOKEN": self.token}
        headers.update(extra or {})
        return headers

    def get(self, url, timeout=90, tries=net.TRIES):
        """GET, returning the raw bytes and the headers that came with them."""
        return net.open_url(urllib.request.Request(url, headers=self._headers()),
                            timeout=timeout, tries=tries, opener=self.opener, log=log)

    def get_json(self, url, timeout=90, tries=net.TRIES):
        """GET and parse inside one retry, so an HTML error page is another attempt."""
        body, _ = net.open_url(
            urllib.request.Request(url, headers=self._headers()),
            timeout=timeout, tries=tries, opener=self.opener, log=log,
            parse=lambda raw: json.loads(raw.decode("utf-8")))
        return body

    def post_json(self, url, payload, timeout=120, tries=net.TRIES):
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers=self._headers({"Content-Type": "application/json"}))
        body, _ = net.open_url(request, timeout=timeout, tries=tries, opener=self.opener,
                               log=log, parse=lambda raw: json.loads(raw.decode("utf-8")))
        return body


def log(line):
    print(line, file=sys.stderr)


_SESSION = [None]


def session():
    """The run's session, built on first use. One per process is the whole requirement."""
    if _SESSION[0] is None:
        _SESSION[0] = Session()
    return _SESSION[0]


# ---------------------------------------------------------------- the classifier

# The register's own words for the codes it returns, fetched once per run and cached. The
# alternative is a table in this file that goes stale in silence: a procedure renamed in the
# register would keep its old name on our cards for as long as nobody happened to look.
_DOMAINS = {}


def domain(code, lang="et"):
    """`{code: text}` for one of the register's classifiers, cached for the run."""
    key = (code, lang)
    if key not in _DOMAINS:
        try:
            rows = session().get_json(DOMAIN % (code, lang))
        except Exception:
            # A classifier that will not load costs a caption, never a tender: the code
            # itself is already on the card and is what everything downstream compares.
            rows = []
        _DOMAINS[key] = {str(r.get("code")): r.get("text") for r in rows if r.get("code")}
    return _DOMAINS[key]


def label(domain_code, value, lang="et"):
    return domain(domain_code, lang).get(str(value)) if value else None


# ---------------------------------------------------------------- the second id

def old_id(pid):
    """The document side's number for a procurement, taken from its version list.

    This request exists for exactly one reason, worth saying plainly: without it every later
    call answers that there is no such procurement. The version list is also the register's
    record of the publication itself, so the newest entry is taken — an amended procurement
    grows a version, and the documents hang off the latest one.
    """
    try:
        payload = session().get_json(VERSIONS % pid)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise Refused("%s: the register has no such procurement" % pid)
        raise
    items = [i for i in (payload or {}).get("procVersionItems") or []
             if i.get("procurementOldId")]
    if not items:
        raise Refused("%s: the register served no version carrying a document id" % pid)
    items.sort(key=lambda i: (i.get("startDate") or "", i.get("procurementOldId")))
    return items[-1]["procurementOldId"], items


# ---------------------------------------------------------------- the facts

def general_info(old):
    """Everything the register knows about a procurement that the search row does not.

    THREE OF THESE EXIST NOWHERE ELSE, and a run without them would be judging tenders on a
    title. The search row carries no estimated value, no CPV code — only the classification's
    Estonian name — and no description at all: `shortDescription` comes back empty on every
    row the register serves in a search. All three are here, as JSON, in one request.

    The register also renders a notice as a ready-made HTML page, and the same facts can be
    read out of it. This is the better road and the reason is not taste: the notice is a
    document laid out for a person — labels in whichever language it was filed in, values as
    printed strings, the whole block repeated once per lot — so reading it means matching
    labels and hoping. And a market consultation has no notice at all, while it does have
    this. One road that answers for all three populations beats two roads that disagree.
    """
    payload = session().get_json(GENERAL_INFO % old) or {}
    body = payload.get("procurement") or {}
    codes = []
    for row in payload.get("procurementCpvDtos") or []:
        code = (row.get("code") or "").strip()
        if code:
            codes.append({"code": code, "name": row.get("name"),
                          "order": row.get("orderNr")})
    codes.sort(key=lambda c: str(c.get("order") or ""))
    return {
        "description": payload.get("shortDescription"),
        # `isCostClassified` is the buyer declaring the estimate confidential, which is a
        # different fact from not having stated one. Both leave `value` empty; only one of
        # them is a gap, so the flag travels rather than being flattened into a null.
        "value": payload.get("cost"),
        "value_classified": bool(payload.get("isCostClassified")),
        "deadline": payload.get("submissionDate"),
        "opening": payload.get("submissionDateOpening"),
        "contract_duration": payload.get("durationInMonths"),
        "duration_unit": payload.get("tenderDurationType"),
        "lots": bool(payload.get("isDividedIntoParts")),
        "note": payload.get("notDividedIntoPartsComment"),
        "procedure": body.get("procedureTypeCode"),
        "work_kind": body.get("procurementTypeCode"),
        "sector": body.get("procurementSectorCode"),
        "start_basis": body.get("procurementStartBasis"),
        "multi_stage": payload.get("multiStage"),
        # THE REAL CLASSIFICATION, CHECK DIGIT AND ALL — `71320000-7`, not `71320000`. The
        # search row names the classification and never numbers it, so this is the only place
        # a code comes from, and a card that quotes one is quoting this.
        "cpv": [c["code"] for c in codes],
        "cpv_names": {c["code"]: c["name"] for c in codes},
        # The register's own statement of which procedures never produce a notice. Carried so
        # a reader does not have to infer "there is no notice" from a missing one.
        "procedures_without_notice": payload.get("procedureTypeCodesWithoutNotice") or [],
    }


# ---------------------------------------------------------------- the documents

# A document the register will not hand to an anonymous caller, and one uploaded but never
# published. Both are listed in the catalogue and neither is in the package, so a run that
# counted the catalogue and then counted the archive would report a gap that is not one.
PUBLIC = "PUBLIC"
PUBLISHED = "PUBLISHED"


def catalogue(old):
    """Every document the register lists for a procurement, the public and the rest apart.

    `stampUpd` is the closest this register comes to a buyer saying "I replaced this on the
    fourth". Byte digests stay the floor — a buyer can upload the same file twice — but the
    field is what lets an update name WHICH document moved rather than only that one did.
    """
    payload = session().get_json(CATALOGUE % old)
    public, withheld = [], []
    for row in (payload or {}).get("procurementDocuments") or []:
        entry = {
            "doc_id": str(row.get("procurementDocumentOldId")
                          or row.get("procurementDocumentId")),
            "document_id": row.get("procurementDocumentId"),
            "fileserv_id": row.get("failservId"),
            "title": row.get("name"),
            "filename": row.get("fileName"),
            "bytes": row.get("fileSize"),
            "note": row.get("description") or None,
            "type_code": row.get("documentTypeCode"),
            "subtype": row.get("documentSubtypeCode") or row.get("docSubtypeCode"),
            "version": row.get("lastVersion"),
            "publish_date": row.get("stampUpd") or row.get("dateCreated"),
            "section": "current",
        }
        if row.get("visibilityCode") == PUBLIC and row.get("statusCode") == PUBLISHED:
            public.append(entry)
        else:
            withheld.append(entry)
    return public, withheld


def package(pid):
    """A one-use address for the whole procurement, as an archive the register builds itself.

    THE ANSWER MUST NOT BE SAVED. The address works exactly once; asking with it a second time
    is answered as though the documents were gone. That is the one failure in this country
    that returns a WRONG result rather than an error, so a retry has to come back here for a
    fresh address instead of reusing the one it holds. Callers get a URL, never a cached one.
    """
    payload = session().get_json(PACKAGE % pid)
    value = (payload or {}).get("value")
    if not value:
        raise Refused("%s: the register offered no document package" % pid)
    return value if value.startswith("http") else BASE + value


# ---------------------------------------------------------------- the shape everything reads

def notice(row, detail=None, kind=None):
    """One procurement's facts, in the shape every country tool in this family produces.

    `row` is the search row and is the source of everything the register states as a code.
    `detail` is `general_info`, and is absent only when a caller deliberately asked for the
    facts a search alone can give. Codes are kept beside their words on purpose: the word is
    for a person, and the code is what the next run compares against.
    """
    detail = detail or {}
    pid = str(row.get("procurementId"))
    kind = kind or kind_of(row)
    status = str(row.get("procurementStatus") or "") or None
    procedure = row.get("procurementProcessType") or detail.get("procedure") or None
    work_kind = row.get("procurementType") or detail.get("work_kind")
    cpv = detail.get("cpv") or []
    return {
        "eis_id": pid,              # the contract's name for it, kept so readers do not fork
        "ref": row.get("procurementReferenceNr"),
        "source": "RHR",
        "country": "EE",
        "kind": kind,
        "link": VIEW % pid,
        "documents_link": DOCUMENTS_VIEW % pid,
        "title": row.get("procurementName"),
        "description": detail.get("description"),
        "buyer": row.get("contractingAuthorityName"),
        "buyer_reg": None,          # the search row does not carry it and the card does not need it
        "value": detail.get("value"),
        "value_classified": detail.get("value_classified"),
        "currency": "EUR",
        # The search row's deadline is the one the register sorts and filters on; the detail
        # carries the same instant with its time. The row wins so that a procurement fetched
        # by window and the same one fetched by reference agree.
        "deadline": row.get("procProcessSubmitDate") or detail.get("deadline"),
        "opening": detail.get("opening"),
        "docs_until": None,
        "published": row.get("procProcessRevealDate"),
        # THE CODE IS THE FACT, THE WORD IS THE CAPTION. `status` is what a later run
        # compares and cannot drift with a rename or a translation; `status_text` is what a
        # person reads and is allowed to change underneath it.
        "status": status,
        "status_text": label("PROCUREMENT_STATE", status),
        "procedure": procedure,
        "procedure_text": label("PROCEDURE_TYPE", procedure),
        "work_kind": work_kind,
        "work_kind_text": label("PROCUREMENT_TYPE", work_kind),
        "sector": row.get("procurementSectorCode") or detail.get("sector"),
        "legal_basis": None,
        "place": None,
        "profile": None,
        "framework": None,
        "iub_uuid": None,
        "award_criteria": None,
        "lots": bool(row.get("procurementHasParts")) or bool(detail.get("lots")),
        "contract_duration": detail.get("contract_duration"),
        "duration_unit": detail.get("duration_unit"),
        "multi_stage": bool(row.get("isProcurementMultiStage")),
        "suspended": bool(row.get("isSuspended")),
        "green": bool(row.get("isGreenProcurement")),
        # The classification's Estonian name, which the search row gives free and which the
        # recall gate reads as its second surface — the code itself costs a request.
        "cpv_name": row.get("mainCpvName"),
        "cpv_main": cpv[0] if cpv else None,
        "cpv_additional": cpv[1:],
        # `policy.cpv_codes` reads the whole set from here, so the gate that already works for
        # the other tools in this family works unchanged rather than growing a country branch.
        "cpv": cpv,
        "cpv_names": detail.get("cpv_names") or {},
        "fields": {},
    }


def collect(row, kind=None):
    """The facts and the catalogue, in the three requests that carry them.

    Three, not eight: the version list for the document id, the facts, and the catalogue.
    A market consultation costs the same three, which is the point of reading the service
    rather than the notice.
    """
    pid = str(row.get("procurementId"))
    old, versions = old_id(pid)
    detail = general_info(old)
    public, withheld = catalogue(old)
    out = notice(row, detail, kind)
    out.update({"procurement_old_id": old, "versions": len(versions),
                "documents": public, "withheld_documents": withheld})
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv:
        raise SystemExit("ee_page: name a reference number — python3 ee_page.py 314707")
    import ee_targets
    row = ee_targets.one(argv[0])
    if row is None:
        raise SystemExit("ee_page: the register served no row for %s" % argv[0])
    json.dump(collect(row), sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
