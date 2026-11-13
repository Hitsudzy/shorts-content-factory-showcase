#!/usr/bin/env python3
"""CF-0618: the API Data the factory keeps - how long, how it is refreshed,
how it is deleted. YouTube API Services Developer Policies, last updated
2026-09-14 (`docs/api-audit/README.md` has the clauses and their reading).

What is API Data here, and what is not
--------------------------------------
API Data (received from YouTube API Services with the owner's OAuth token):

    analytics/<channel>/daily.jsonl   YouTube Analytics metrics (metrics.py collect)
    analytics/<channel>/windows.jsonl YouTube Analytics totals of a window (CF-0624)
    analytics/<channel>/runs.jsonl    the run log of that collection (ids, API errors)
    analytics/<channel>/summary/      the daily summary - built from windows.jsonl
    publish/uploads.json, rows with `source: api` - the fields of the
        `videos.insert` answer and what goes with them: `API_ROW_FIELDS`
        (video_id, url, publish_at, publish_tz, privacy_status, ...)
    the same video id written into the video's note and publish/README.md
        (`upload_records.append_note` / `update_readme`)

Not API Data (kept): rows with `source: studio` / `backfill` - the user reads
the id and the slot in YouTube Studio and the factory writes them down;
`analytics/<channel>/studio.jsonl`, `studio_visits.jsonl`, `rights.jsonl`
(read from the Studio pages, CF-0588), `footage-wanted.*`; the OAuth token
itself (III.E.4.a, kept while it is used; the user deletes it, or `revoke --yes`).

The three rules
---------------
1. **Revocation - III.D.2.b.** A token Google will not refresh
   (`invalid_grant`: the owner revoked the access, or the Testing app's week
   ran out) is marked in the token's state by `publisher_auth` - the date of
   the *first* refusal since the last consent. `PURGE_AFTER_DAYS` (25) later
   the auto-run deletes all API Data of every channel; the policy's limit is
   `RETENTION_DAYS` (30) - five days of margin for a machine that was off. A new
   consent (`upload.py --authorize`) writes a fresh state: the mark is gone and
   nothing is deleted.
2. **Other Authorized Data - III.E.4.c**, at most 30 days without a refresh.
   The `videos.insert` fields of an API row are refreshed by `videos.list`
   (`refresh_journal`, called by `agents/analyst/metrics.py collect`) once
   they are `REFRESH_DAYS` (7) old: `privacy_status` and `api_refreshed_at`
   are rewritten; a video YouTube no longer returns gets `removed_at`. A row
   that went `STALE_DAYS` (28) without a refresh is deleted by the auto-run
   (its API fields, see "deleting a row"). Analytics metrics are III.E.4.b
   (kept long-term while the authorization is checked at least every 30 days -
   the daily collection checks it; a refused token is rule 1).
3. **On request - III.E.4.g**, within 7 days: `purge --all` or
   `purge --channel C`, run by the owner (or by the operator at the owner's
   request) - the same deletion, at once.
4. **Revocation from the client - III.D.2.b (CF-0619).** `revoke --yes`:
   the token is revoked at Google (`REVOKE_URL`, POST `token=<refresh token,
   else access token>`, `REVOKE_TIMEOUT_S`), the local token file is deleted,
   all API Data is deleted at once (the same `plan`/`apply` as `purge --all`,
   reason `revoked from the client`) and the token's state gets the mark
   (`revoked_from_client_at`, what Google answered) and `api_data_deleted`.
   Google's 400 (`invalid_token` - the token is already dead) does not stop
   the local part: it is said in the output. No answer at all (network,
   timeout, 5xx) stops before anything local changes: the token is kept for a
   retry, and the owner can still revoke on Google's own page. No token file:
   said so, the API Data is deleted all the same. Without `--yes` it is a dry
   run that says what it would do. The token value never reaches the output,
   the log or an exception text.

Deleting a row of the journal: the row leaves `uploads` (whose readers all
expect a video id) and its own, non-API part - channel, entry_id, batch, slug,
publish_day, note, title, uploaded_at, ... - goes to the journal's
`api_data_deleted` list with `api_data_deleted_at` and the reason, so the
upload gate still knows the acceptance row was uploaded once
(`upload_gate.check_not_uploaded`) and nothing is uploaded twice. The video id
in the note and in publish/README.md is replaced by `SCRUBBED`. To bring the
video back into the journal, the user reads its id in Studio:
`upload_records.py studio ...` (not API Data).

Every run that deletes appends a line to `publish/api-data-deletions.jsonl`
(when, why, which files, which entry ids - no API Data); a deletion after a
revocation is also written into the token's state (`api_data_deleted`).

Who deleted (CF-0701): `by` / `via` of the caller (the center: "user" /
"center"; the auto-run: by "auto") go into that line, into each deleted row
(`api_data_deleted_by` / `_via`) and into the token's state; not given - not
written. Rows written before CF-0701 carry the task number "CF-0618" in
`api_data_deleted_by`: `who_deleted` reads them as by None. `revoke_result` is
rule 4 as data (Google's answer, the token, the deletion record); `revoke`
prints from it.

Nothing is deleted without `--delete` (CLI) or `delete=True` (the auto-run of
the tick and of `metrics.py collect`, which deletes only what rules 1-2 make
due).

    python3 agents/publisher/api_data.py status [--env E]
    python3 agents/publisher/api_data.py purge --all | --channel C [--channel C2] [--delete]
    python3 agents/publisher/api_data.py auto [--delete] [--env E]
    python3 agents/publisher/api_data.py revoke [--yes] [--env E]
"""
import argparse
import json
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

AGENT = Path(__file__).resolve().parent
ROOT = AGENT.parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

import upload_records                                           # noqa: E402

TASK = "CF-0618"
RETENTION_DAYS = 30        # III.D.2.b / III.E.4.c: the policy's limit
PURGE_AFTER_DAYS = 25      # the auto-run deletes this long after the revocation mark
REFRESH_DAYS = 7           # an API row's fields are refreshed by videos.list this often
STALE_DAYS = 28            # an API row not refreshed this long is deleted by the auto-run
MSK = timezone(timedelta(hours=3), "МСК")

API_FILES = ("daily.jsonl", "windows.jsonl", "runs.jsonl")  # metrics_store.DAILY, WINDOWS, RUNS
API_DIRS = ("summary",)                         # summary.py's output, built from windows.jsonl
KEPT_FILES = ("studio.jsonl", "studio_visits.jsonl", "rights.jsonl", "footage-wanted.md",
              "footage-wanted.json")
# the fields of an API row that came from (or go with) the videos.insert answer
API_ROW_FIELDS = ("video_id", "url", "publish_at", "publish_tz", "privacy_status",
                  "superseded_video_ids", "replaced_by", "removed_at", "removed_reason",
                  "api_refreshed_at")
DELETED_KEY = "api_data_deleted"
LOG = "api-data-deletions.jsonl"
SCRUBBED = "[id удалён по политике YouTube API, CF-0618]"
EXIT_OK, EXIT_ERROR = 0, 2
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
REVOKE_TIMEOUT_S = 20
REVOKED_REASON = "revoked from the client"
GOOGLE_PAGE = "https://myaccount.google.com/permissions"
WHO_MAX = 40               # CF-0701: `by` / `via` of a deletion (CF-0692's rule)
AUTO_BY = "auto"           # CF-0701: who deleted, for the auto-run (rules 1-2)
LEGACY_BY = re.compile(r"CF-\d{4}")  # before CF-0701 `api_data_deleted_by` was the task number


def _now(now=None):
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, str):
        now = datetime.fromisoformat(now.replace("Z", "+00:00"))
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(ts):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _day(dt):
    return dt.astimezone(MSK).strftime("%Y-%m-%d")


def _paths(root, journal=None, analytics=None):
    """(root, journal, analytics dir, README); `journal`/`analytics` override
    the root's (metrics.py's --journal/--store)."""
    root = Path(root or ROOT)
    return (root, Path(journal) if journal else root / "publish" / "uploads.json",
            Path(analytics) if analytics else root / "analytics", root / "publish" / "README.md")


def is_api_row(row):
    return row.get("source") == "api"


def last_refresh(row):
    """When the row's API fields were last fetched from YouTube: the refresh,
    else the upload itself. None for a row with no time at all (not a row
    `check_row` lets in) - judged neither due nor stale."""
    return _parse(row.get("api_refreshed_at")) or _parse(row.get("uploaded_at")) \
        or _parse(row.get("recorded_at"))


# --------------------------------------------------------------------------
# rule 2: refresh through videos.list
# --------------------------------------------------------------------------

def due_for_refresh(rows, now=None, days=REFRESH_DAYS):
    now = _now(now)
    out = []
    for r in rows:
        if not is_api_row(r) or r.get("removed_at"):
            continue
        last = last_refresh(r)
        if last is not None and now - last >= timedelta(days=days):
            out.append(r)
    return out


def refresh_journal(client, root=None, journal=None, now=None):
    """Refresh the API rows due (`due_for_refresh`) with `client.video_statuses`
    (`youtube_client.YouTubeClient`). Returns {"asked", "refreshed", "missing"}.
    Writes the journal only when something was asked."""
    now = _now(now)
    _, jpath, _, _ = _paths(root, journal)
    doc = upload_records.read_journal(jpath)
    due = due_for_refresh(doc["uploads"], now)
    result = {"asked": [r["video_id"] for r in due], "refreshed": [], "missing": []}
    if not due:
        return result
    found = client.video_statuses(result["asked"])
    stamp = _iso(now)
    for r in due:
        st = found.get(r["video_id"])
        r["api_refreshed_at"] = stamp
        if st is None:
            r["removed_at"] = stamp
            r["removed_reason"] = f"videos.list does not return it any more ({TASK})"
            result["missing"].append(r["video_id"])
            continue
        if st.get("privacyStatus"):
            r["privacy_status"] = st["privacyStatus"]
        result["refreshed"].append(r["video_id"])
    upload_records._write(doc, jpath)                           # noqa: SLF001 - its one writer
    return result


# --------------------------------------------------------------------------
# the plan of a deletion, and doing it
# --------------------------------------------------------------------------

def analytics_channels(root=None, analytics=None):
    _, _, analytics, _ = _paths(root, analytics=analytics)
    return sorted(p.name for p in analytics.iterdir() if p.is_dir()) if analytics.is_dir() else []


def plan(root=None, channels=None, rows=None, reason="request", journal=None, analytics=None):
    """What a deletion would remove. `channels` - None: every channel (the
    analytics directories and every API row); a list: those. `rows` - an
    explicit list of journal rows to delete instead of "every API row of the
    channels" (the stale rule); with `rows`, no analytics file is touched."""
    root, jpath, analytics, readme = _paths(root, journal, analytics)
    doc = upload_records.read_journal(jpath)
    files, dirs = [], []
    if rows is None:
        chans = analytics_channels(root, analytics) if channels is None else list(channels)
        for ch in chans:
            base = analytics / ch
            files += [base / f for f in API_FILES if (base / f).is_file()]
            dirs += [base / d for d in API_DIRS if (base / d).is_dir()]
        rows = [r for r in doc["uploads"]
                if is_api_row(r) and (channels is None or r.get("channel") in channels)]
    scrub = []
    for r in rows:
        ids = [v for v in upload_records.ids_of(r) if v]
        targets = [readme]
        if r.get("note"):
            targets.append(root / r["note"])
        for t in targets:
            if t.is_file():
                text = t.read_text(encoding="utf-8")
                scrub += [(t, v) for v in ids if v in text]
    return {"reason": reason, "root": root, "journal": jpath, "files": files, "dirs": dirs,
            "rows": rows, "scrub": scrub,
            "channels": sorted({r.get("channel") for r in rows}
                               | {p.parent.name for p in files + dirs})}


def is_empty(p):
    return not (p["files"] or p["dirs"] or p["rows"] or p["scrub"])


def _rel(p, root):
    try:
        return str(Path(p).relative_to(root))
    except ValueError:
        return str(p)


def describe(p):
    """Lines a person reads: what is (or would be) deleted."""
    root = p["root"]
    out = [f"  file  {_rel(f, root)}" for f in p["files"]]
    out += [f"  dir   {_rel(d, root)}/ ({sum(1 for _ in d.rglob('*') if _.is_file())} file(s))"
            for d in p["dirs"]]
    out += [f"  row   {_rel(p['journal'], root)}: {r.get('channel')} {r.get('slug')} "
            f"{r.get('video_id')} (source api) -> API fields deleted, the rest kept in "
            f"`{DELETED_KEY}`" for r in p["rows"]]
    out += [f"  text  {_rel(t, root)}: {v} -> {SCRUBBED}" for t, v in p["scrub"]]
    return out


def _who(value, what):
    """CF-0701 (the shape of CF-0692's `studio_read._who`, CF-0700's
    `notify._who`): `by` / `via` of a deletion
    - None (not given) or a short non-empty single-line string; anything else
    is a ValueError and nothing is deleted or written."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what}={value!r}: a short non-empty string (e.g. by='user', "
                         f"via='center') or not given at all")
    value = value.strip()
    if len(value) > WHO_MAX or any(c in value for c in "\r\n\t"):
        raise ValueError(f"{what}={value!r}: at most {WHO_MAX} characters on one line")
    return value


def _who_extra(by=None, via=None):
    """{"by", "via"} of the given ones (checked), for `apply(extra=...)` and the
    token state's records; {} when neither is given."""
    by, via = _who(by, "by"), _who(via, "via")
    return {k: v for k, v in (("by", by), ("via", via)) if v is not None}


def who_deleted(row):
    """CF-0701: who deleted a row of the journal's `api_data_deleted` list -
    {"by", "via", "task"}. `api_data_deleted_by` is the one who deleted (the
    caller's `by`; "auto" for the auto-run); a row written before CF-0701 has
    the task number "CF-0618" there instead of a person - read as by=None,
    task="CF-0618". Never raises on an old or odd row."""
    by = row.get("api_data_deleted_by") if isinstance(row, dict) else None
    via = row.get("api_data_deleted_via") if isinstance(row, dict) else None
    if isinstance(by, str) and LEGACY_BY.fullmatch(by):
        return {"by": None, "via": None, "task": by}
    return {"by": by if isinstance(by, str) else None,
            "via": via if isinstance(via, str) else None, "task": None}


def _kept(row, now, reason, by=None, via=None):
    """The non-API part of a deleted row. CF-0701: `api_data_deleted_by` /
    `_via` name who deleted it (the caller's by/via) - not written when not
    given; before CF-0701 it held the task number (TASK), see `who_deleted`."""
    keep = {k: v for k, v in row.items() if k not in API_ROW_FIELDS}
    keep.update(api_data_deleted_at=_iso(now), api_data_deleted_reason=reason)
    if by is not None:
        keep["api_data_deleted_by"] = by
    if via is not None:
        keep["api_data_deleted_via"] = via
    return keep


def apply(p, now=None, log=True, extra=None):
    """Delete what the plan names. Returns the log record (`extra` merged in).
    CF-0701: `by` / `via` of `extra` (the center passes {"by": "user",
    "via": "center"}) are checked (`_who`) before anything is deleted and also
    name who deleted each journal row (`api_data_deleted_by` / `_via`)."""
    now = _now(now)
    extra = dict(extra or {})
    for k in ("by", "via"):
        if k in extra:
            extra[k] = _who(extra[k], k)
            if extra[k] is None:
                del extra[k]
    by, via = extra.get("by"), extra.get("via")
    root = p["root"]
    for f in p["files"]:
        f.unlink(missing_ok=True)
    for d in p["dirs"]:
        shutil.rmtree(d, ignore_errors=True)
    if p["rows"]:
        doc = upload_records.read_journal(p["journal"])
        ids = {r.get("video_id") for r in p["rows"]}
        keep, moved = [], []
        for r in doc["uploads"]:
            if r.get("video_id") in ids and is_api_row(r):
                moved.append(_kept(r, now, p["reason"], by, via))
            else:
                keep.append(r)
        doc["uploads"] = keep
        doc[DELETED_KEY] = list(doc.get(DELETED_KEY) or []) + moved
        upload_records._write(doc, p["journal"])                # noqa: SLF001 - its one writer
    by_file = {}
    for t, v in p["scrub"]:
        by_file.setdefault(t, set()).add(v)
    for t, vids in by_file.items():
        text = t.read_text(encoding="utf-8")
        for v in vids:
            text = text.replace(v, SCRUBBED)
        tmp = t.with_name(t.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(t)
    record = {"at": _iso(now), "reason": p["reason"], "channels": p["channels"],
              "files": [_rel(f, root) for f in p["files"]],
              "dirs": [_rel(d, root) for d in p["dirs"]],
              "entries": [r.get("entry_id") for r in p["rows"]],
              "texts": sorted({_rel(t, root) for t, _ in p["scrub"]}), "task": TASK}
    record.update(extra)
    if log:
        lp = root / "publish" / LOG
        lp.parent.mkdir(parents=True, exist_ok=True)
        with open(lp, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


# --------------------------------------------------------------------------
# the auto-run (the tick, metrics.py collect) and the status line
# --------------------------------------------------------------------------

def _auth():
    import publisher_auth                                       # noqa: PLC0415
    return publisher_auth


def revocation(cfg, now=None):
    """{"revoked_at", "due_at", "deadline", "deleted"} or None (no mark)."""
    pa = _auth()
    state = pa.read_state(cfg) or {}
    at = pa.revoked_at(state)
    if at is None:
        return None
    return {"revoked_at": at, "due_at": at + timedelta(days=PURGE_AFTER_DAYS),
            "deadline": at + timedelta(days=RETENTION_DAYS),
            "deleted": state.get("api_data_deleted")}


def stale_rows(root=None, now=None, journal=None):
    now = _now(now)
    _, jpath, _, _ = _paths(root, journal)
    rows = upload_records.uploads(jpath)
    return [r for r in rows if is_api_row(r) and last_refresh(r) is not None
            and now - last_refresh(r) >= timedelta(days=STALE_DAYS)]


def auto(cfg, root=None, now=None, delete=False, journal=None, analytics=None,
         by=AUTO_BY, via=None):
    """What is due under rules 1-2, done when `delete`. Returns a list of
    (plan, record-or-None). Deletes nothing that is not due: no mark, or a
    mark younger than PURGE_AFTER_DAYS, and no stale row -> nothing.

    CF-0701: `by` / `via` - who deleted: the auto-run of the tick and of
    `metrics.py collect` is `by="auto"` (the default); the center passes
    by="user", via="center". Checked (`_who`) before anything is deleted;
    they go into the log record, the journal rows and the token state's
    `api_data_deleted`."""
    now = _now(now)
    who = _who_extra(by, via)
    done = []
    rev = revocation(cfg, now) if cfg is not None else None
    if rev and now >= rev["due_at"]:
        p = plan(root, reason=f"revoked {_iso(rev['revoked_at'])}", journal=journal,
                 analytics=analytics)
        if not is_empty(p):
            rec = apply(p, now, extra=who) if delete else None
            if rec is not None:
                _auth().record_api_data_deleted(cfg, {"reason": p["reason"],
                                                      "channels": p["channels"], **who}, now)
            done.append((p, rec))
    stale = stale_rows(root, now, journal)
    if stale:
        p = plan(root, rows=stale, reason=f"not refreshed for {STALE_DAYS}+ days",
                 journal=journal)
        done.append((p, apply(p, now, extra=who) if delete else None))
    return done


# --------------------------------------------------------------------------
# rule 4: revocation from the client (CF-0619)
# --------------------------------------------------------------------------

def token_value(cfg):
    """(value, kind) of the token file - the refresh token, else the access
    token; (None, why) when there is no file or no value in it. The value is
    handed to Google and to nothing else."""
    path = Path(cfg.token_file)
    if not path.is_file():
        return None, "no token file"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None, "the token file does not parse"
    if not isinstance(data, dict):
        return None, "the token file does not parse"
    for key, kind in (("refresh_token", "refresh token"), ("token", "access token")):
        if isinstance(data.get(key), str) and data[key]:
            return data[key], kind
    return None, "no token value in the file"


def _safe(text, secret):
    text = str(text)
    return text.replace(secret, "***") if secret else text


def revoke_at_google(token, timeout=REVOKE_TIMEOUT_S):
    """POST the token to Google's revoke endpoint. Returns {"answer": revoked |
    invalid_token | unreachable, "detail"} - `invalid_token` for any 400 (the
    token is already revoked or expired), `unreachable` for no answer, a
    timeout or another HTTP status. The token is in the body only, never in
    the result."""
    data = urllib.parse.urlencode({"token": token}).encode()
    req = urllib.request.Request(REVOKE_URL, data=data, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:     # noqa: S310 - fixed https URL
            code = getattr(r, "status", 200)
    except urllib.error.HTTPError as e:
        err = ""
        try:
            body = json.loads(e.read().decode("utf-8", "replace") or "{}")
            err = body.get("error", "") if isinstance(body, dict) else ""
        except (ValueError, OSError):
            err = ""
        err = err if re.fullmatch(r"[a-z_]{1,40}", str(err)) else ""
        if e.code == 400:
            return {"answer": "invalid_token", "detail": f"HTTP 400 {err or 'invalid_token'}"}
        return {"answer": "unreachable", "detail": f"HTTP {e.code} {err}".strip()}
    except (urllib.error.URLError, OSError, ValueError) as e:
        reason = getattr(e, "reason", e)
        return {"answer": "unreachable",
                "detail": _safe(f"{type(e).__name__}: {reason}", token)[:200]}
    if 200 <= code < 300:
        return {"answer": "revoked", "detail": f"HTTP {code}"}
    return {"answer": "unreachable", "detail": f"HTTP {code}"}


def revoke_result(cfg, root=None, now=None, yes=False, by=None, via=None):
    """Rule 4, as data (CF-0701): what was (or, without `yes`, would be) done.
    Prints nothing; `revoke` prints from it. `by` / `via` (optional, e.g.
    by="user", via="center") are checked (`_who`) before Google is asked and
    go into the log record, the journal rows and the token state.

    {"dry_run", "ok", "exit" (EXIT_OK | EXIT_ERROR), "by", "via",
     "google": {"answer": revoked | invalid_token | unreachable | "no token" |
                None (dry run), "detail", "url"},
     "token": {"file", "kind" (refresh token | access token | None),
               "missing" (why there is no value, or None), "existed", "deleted"},
     "state_file", "log" (relative to the root), "reason",
     "items" (`describe` lines - deleted, or that would be), "channels",
     "deletion" (the log record `apply` wrote, or None)}
    Never the token value."""
    now = _now(now)
    who = _who_extra(by, via)
    pa = _auth()
    token_path = Path(cfg.token_file)
    value, kind = token_value(cfg)
    p = plan(root, reason=REVOKED_REASON)
    res = {"dry_run": not yes, "ok": True, "exit": EXIT_OK,
           "by": who.get("by"), "via": who.get("via"),
           "google": {"answer": None, "detail": None, "url": REVOKE_URL},
           "token": {"file": str(token_path), "kind": kind if value is not None else None,
                     "missing": None if value is not None else kind,
                     "existed": token_path.exists(), "deleted": False},
           "state_file": str(pa.state_file(cfg)),
           "log": _rel(p["root"] / "publish" / LOG, p["root"]),
           "reason": REVOKED_REASON, "channels": p["channels"], "items": [], "deletion": None}
    if not yes:
        res["items"] = describe(p)
        return res
    if value is not None:
        google = revoke_at_google(value)
        res["google"].update(answer=google["answer"], detail=google["detail"])
        if google["answer"] == "unreachable":
            res.update(ok=False, exit=EXIT_ERROR)
            return res
    else:
        res["google"]["answer"] = "no token"
    answer = res["google"]["answer"]
    if token_path.exists():
        token_path.unlink()
        res["token"]["deleted"] = True
    res["deletion"] = apply(p, now, extra={"google": answer, **who})
    pa.record_client_revocation(cfg, answer, now, **who)
    pa.record_api_data_deleted(cfg, {"reason": REVOKED_REASON, "channels": p["channels"], **who},
                               now)
    res["items"] = describe(p)
    return res


def revoke(cfg, root=None, now=None, yes=False, out=None, by=None, via=None):
    """Rule 4. Prints what it does (or would do); returns the exit code
    (the CLI's; `revoke_result` is the same as data)."""
    out = out or sys.stdout
    res = revoke_result(cfg, root, now, yes=yes, by=by, via=via)
    _print_revoke(res, out)
    return res["exit"]


def _print_revoke(res, out):
    tok, google = res["token"], res["google"]
    if res["dry_run"]:
        print("revoke - dry run (add --yes):", file=out)
        if tok["kind"] is not None:
            print(f"  google  POST {REVOKE_URL} ({tok['kind']} of {tok['file']})", file=out)
        else:
            print(f"  google  nothing to revoke: {tok['missing']} ({tok['file']}) - the API Data "
                  f"is deleted all the same", file=out)
        if tok["existed"]:
            print(f"  token   {tok['file']} -> deleted", file=out)
        print(f"  state   {res['state_file']}: the revocation mark "
              f"(revoked_from_client_at), api_data_deleted", file=out)
        print(f"  log     {res['log']}: reason `{REVOKED_REASON}`", file=out)
        _print_items(res["reason"], res["items"], False, out, flag="--yes")
        return
    if google["answer"] == "unreachable":
        print(f"Google did not answer the revocation ({google['detail']}): nothing changed, "
              f"the token is kept for a retry; or revoke on {GOOGLE_PAGE}", file=out)
        return
    if google["answer"] == "revoked":
        print(f"google  revoked ({google['detail']})", file=out)
    elif google["answer"] == "no token":
        print(f"google  nothing to revoke: {tok['missing']} ({tok['file']}) - the API Data is "
              f"deleted all the same", file=out)
    else:
        print(f"google  refused: the token is already invalid ({google['detail']}) - "
              f"the local deletion goes on", file=out)
    if tok["deleted"]:
        print(f"token   {tok['file']} deleted", file=out)
    print(f"state   {res['state_file']}: revocation mark {res['deletion']['at']}", file=out)
    _print_items(res["reason"], res["items"], True, out)
    print(f"log     {res['log']}", file=out)


def status(cfg, root=None, now=None, journal=None):
    """The console's line: {"kind": ok|warn|bad, "line"}."""
    now = _now(now)
    rev = revocation(cfg, now) if cfg is not None else None
    _, jpath, _, _ = _paths(root, journal)
    try:
        rows = upload_records.uploads(jpath)
    except (upload_records.JournalError, ValueError) as e:
        return {"kind": "bad", "line": f"API Data: журнал не читается ({e})"}
    api = [r for r in rows if is_api_row(r)]
    if rev:
        if rev["deleted"]:
            return {"kind": "warn", "line": (
                f"API Data удалены {str(rev['deleted'].get('at', ''))[:10]} после отзыва доступа "
                f"{_day(rev['revoked_at'])} (III.D.2.b); сбор метрик стоит до переразрешения")}
        return {"kind": "bad", "line": (
            f"API Data: Google отказал токену {_day(rev['revoked_at'])} (invalid_grant: отозван или "
            f"истёк) - метрики Analytics и API-поля журнала будут удалены {_day(rev['due_at'])} "
            f"(предел политики {_day(rev['deadline'])}); переразрешение снимает отметку")}
    stale = due_for_refresh(api, now)
    tail = (f"; {len(stale)} не обновлялись {REFRESH_DAYS}+ дн. (videos.list в metrics.py collect, "
            f"удаление на {STALE_DAYS}-й день)" if stale else "")
    return {"kind": "warn" if stale else "ok", "line": (
        f"API Data: отзыва доступа нет; журнал - {len(api)} строк(и) API-пути{tail}")}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _cfg(env):
    import publisher_config                                     # noqa: PLC0415
    return publisher_config.load(env)


def _print_plan(p, delete, out, flag="--delete"):
    _print_items(p["reason"], describe(p), delete, out, flag)


def _print_items(reason, lines, delete, out, flag="--delete"):
    verb = "deleted" if delete else f"would be deleted (dry run - add {flag})"
    print(f"{reason}: {len(lines)} item(s) {verb}" if lines else
          f"{reason}: nothing to delete", file=out)
    for line in lines:
        print(line, file=out)


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status", help="the revocation mark, the journal's API rows")
    s.add_argument("--env")
    p = sub.add_parser("purge", help="delete API Data on request (III.E.4.g)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true", help="every channel")
    g.add_argument("--channel", action="append", help="one channel id (repeatable)")
    p.add_argument("--delete", action="store_true", help="really delete (default: dry run)")
    a = sub.add_parser("auto", help="what rules 1-2 make due (revocation, stale rows)")
    a.add_argument("--delete", action="store_true", help="really delete (default: dry run)")
    a.add_argument("--env")
    r = sub.add_parser("revoke", help="revoke the token at Google, delete it and all API Data")
    r.add_argument("--yes", action="store_true", help="really do it (default: dry run)")
    r.add_argument("--env")
    for x in (s, p, a, r):
        x.add_argument("--root", help=argparse.SUPPRESS)
        x.add_argument("--now", help=argparse.SUPPRESS)
    return ap


def main(argv=None, out=None, cfg=None):
    out = out or sys.stdout
    args = build_parser().parse_args(argv)
    now = _now(args.now)
    try:
        if args.cmd == "purge":
            p = plan(args.root, channels=None if args.all else args.channel,
                     reason="owner's request (III.E.4.g)")
            _print_plan(p, args.delete, out)
            if args.delete and not is_empty(p):
                apply(p, now)
            return EXIT_OK
        if cfg is None:
            cfg = _cfg(args.env)
        if args.cmd == "status":
            print(status(cfg, args.root, now)["line"], file=out)
            return EXIT_OK
        if args.cmd == "revoke":
            return revoke(cfg, args.root, now, yes=args.yes, out=out)
        done = auto(cfg, args.root, now, delete=args.delete)
        if not done:
            print("nothing due: no revocation past its term, no stale API row", file=out)
        for p, _ in done:
            _print_plan(p, args.delete, out)
        return EXIT_OK
    except (upload_records.JournalError, ValueError, OSError) as e:
        print(f"error: {e}", file=out)
        return EXIT_ERROR
    except Exception as e:                                      # noqa: BLE001
        if type(e).__name__ == "ConfigError":
            print(f"error: {e}", file=out)
            if args.cmd == "revoke":
                print(f"the API Data can still be deleted: `api_data.py purge --all --delete`; "
                      f"the access is revoked on {GOOGLE_PAGE}", file=out)
            return EXIT_ERROR
        raise


if __name__ == "__main__":
    sys.exit(main())
