#!/usr/bin/env python3
"""CF-0440: what kind of video a published video is - on its publication record.

Grill of 2026-09-29 ("формат канала", Q3 and Q9). There is no view analyst yet
(`agents/analyst/` is empty, CF-0020 is milestone 2.1.1), and when there is one
it will need, for every video that went out: the kind of the fact it was warmed
with, where that fact came from, the pattern it was cut to, the formula its hook
opened on and the score it reached. The same label answers a second question
today: how uniform the feed is, should YouTube ask whether the channel is mass
produced (the reused / repetitive content policy).

**Where it lives.** One field, `profile`, on the video's row of
`publish/acceptance-log.json` (CF-0328) - the record that already outlives the
batch (a batch leaves this disk after 31 days, CF-0056) and already carries
`code_shas` read from the same batch (CF-0399). `acceptance.record()` writes it
when the verdict is filed; `fill()` writes it on rows filed before this task.
The human half is one line under `## Профиль ролика` in the video's note
`publish/<channel>/<YYYY-MM-DD>/<slug>.md` (or `publish/<channel>/_queue/<slug>.md`,
CF-0475),
written by `stamp_md()` from the same dict - neither is typed by hand. A note
is stamped only by the row of the batch it names on its `Батч \`pipeline/...\``
line (or, naming none, by the row whose `publish_path` is its video), and the
stamp replaces only the profile's own lines (CF-0463).

**What it reads, and nothing else.** The batch's own artifacts:

    03-content-researcher.json scripts[]   the fact (`fact`, CF-0438 - `kind`,
                                           `source`, `url`; or the older
                                           `production_fact.source_url`), the
                                           pattern and rhythm (`pattern`), the
                                           hook opener (`hook_opener_id`,
                                           CF-0424)
    05 / 06 via scores.collect()           tier, points and the score line of
                                           the last stage that scored it
                                           (CF-0434)

The script is found by the video's name: the Editor's `videos[].output_path`
stem, then the row's `topic_id`, then the script whose `title_ref.name`
slugifies to the name - never by position.

**Nothing is invented.** A field the batch does not carry is `None` with a
sentence saying why beside it (`*_note`). One field is *derived* rather than
copied, and says so: a script written before CF-0438 carries no `kind`, only the
URL of its fact, and when that URL is a Wikipedia section the kind is the one
the section's heading names - the researcher's own heading map (CF-0439,
`HEADING_KINDS` of `production_facts.py`, repeated below) - with
`fact_kind_from` saying it was derived. Any other URL leaves the kind `None`.

**The diversity summary** (`diversity()`, `runlog diversity --last N`): the feed
is the videos the user accepted and still stands behind (the latest standing
acceptance per video name, a pulled video left out), in the order he accepted
them; for the last N, the share of each fact kind, pattern, rhythm and hook
opener. A video whose row has no profile yet is read from its batch on the
spot (and named so); one whose batch is gone counts under `unknown` - the gap
is shown, not hidden. No agent, no network, no decision: it prints numbers.
`--channel <id>` (CF-0719) counts one channel's feed: the rows whose channel
(`publish_layout.channel_of_row` - a former id resolved, a `rebuilds` row
belonging to the one channel on file) is that channel, before the last N are
taken; the answer then carries `channel`. Without it nothing changes.

**A missing file is not a broken one** (CF-0719). `_load` returns None for a
file that is not there - an empty log, a batch without 05 - as it always did;
a file that is there and does not read (not JSON, not a JSON object, unreadable
bytes) raises `PublishProfileError(path, reason)`, which names the file. Where
it goes from there:

    find_script / profile_of   the batch's 03 or 05 broken: `(None, "unreadable
                               <file>: ...")` - the profile's `problem`, so a
                               refresh keeps the profile on file (CF-0487) and a
                               verdict is never refused over it (acceptance)
    fill / the CLI             the acceptance log broken: the error is raised;
                               `runlog profile|diversity` prints it on stderr and
                               exits 2 - an empty feed is never printed for it
    api/analytics.diversity    the center: the answer as before (empty feed,
                               `log_read` false) plus `log_error` naming the file

**The outlets cache** (`_SOURCES`, CF-0719): kept per root and channel, and
re-read when `channels/<id>/fact-sources.json` changes (mtime or size) - a
long-lived process (the center) sees the list as edited, not as first read.

CLI:
    runlog profile [--fill [--refresh] [--dry-run]] [--root DIR] [--json]
    runlog diversity [--last N] [--channel ID] [--root DIR] [--json]
"""
import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

RESEARCHER_FILE = "03-content-researcher.json"
VIDEO_EDITOR_FILE = "05-video-editor.json"
TASK = "CF-0440"
MD_HEADING = "## Профиль ролика"
UNKNOWN = "unknown"
DEFAULT_LAST = 10

FROM_03 = "03 fact.kind"
FROM_SECTION = "derived from the Wikipedia section of the fact's URL (CF-0439 heading map)"

# The researcher's heading -> kind map (CF-0439, `production_facts.py`
# HEADING_KINDS, itself the hunter's `fact_search.HEADING_KINDS`): first match
# wins. Used only for a script written before CF-0438 put `kind` into 03.
HEADING_KINDS = (
    ("box_office", re.compile(r"box office|gross|commercial performance|ratings|"
                              r"viewership", re.I)),
    ("casting", re.compile(r"casting", re.I)),
    ("production", re.compile(r"production|filming|photography|shooting|development|"
                              r"design|writing|pre-production|post-production|effects|"
                              r"cinematograph|music|score|costume|make-?up|stunt|"
                              r"conception|origin|animation|editing|prosthetic", re.I)),
    ("release", re.compile(r"release|marketing|distribution|broadcast|premiere|"
                           r"home media|streaming|promotion", re.I)),
    ("reception", re.compile(r"reception|critical|accolades|awards|response|legacy|"
                             r"audience|reviews|impact", re.I)),
    ("scandal", re.compile(r"controvers|lawsuit|legal|allegation|dispute|criticism",
                           re.I)),
    ("people_news", re.compile(r"personal life", re.I)),
)


def _load_module(name, path):
    mod = sys.modules.get(name)
    if mod is not None:
        return mod
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return mod


def _acceptance():
    return _load_module("acceptance", HERE / "acceptance.py")


def _scores():
    return _load_module("scores", HERE / "scores.py")


def _fact_rule():
    return _load_module("fact_rule", ROOT / "shared" / "factrule" / "fact_rule.py")


def _channel_data():
    return _load_module("channel_data", ROOT / "shared" / "channel_data.py")


class PublishProfileError(ValueError):
    """CF-0719: a file this module reads is there but does not read - not
    JSON, not a JSON object, or the bytes cannot be read. `path` is the file,
    `reason` why; the message names both. A missing file is not this error:
    `_load` returns None for it."""

    def __init__(self, path, reason):
        self.path, self.reason = Path(path), str(reason)
        super().__init__(f"{self.path}: {self.reason}")


# {(root, channel): the channel's fact outlets}. CF-0561: the outlets are the
# channel's (`channels/<id>/fact-sources.json`, docs/channel-data.md), read for
# the channel the batch belongs to. A channel without the list - or a batch
# whose channel is not known - names no outlet (`id`/`tier` None) and says so
# in `fact_source.note` (CF-0631: an empty "no outlet" without the reason read
# like "the host is not a listed outlet"); it never borrows another channel's
# list. CF-0719: an entry is kept with the stamp (path, mtime_ns, size) of the
# list it was read from and re-read when the file is no longer that - edited,
# removed or put back; a process that lives long (the center) no longer keeps
# the first read for ever. {(root, channel): (stamp, (outlets, None) | ({}, why))}.
_SOURCES = {}


def _sources_stamp(channel, root):
    """`(path, mtime_ns, size)` of the channel's fact-sources list, `(path,
    None, None)` when it is not there, None when no path can be named (no or an
    unknown channel)."""
    try:
        path = _channel_data().channel_list_path(channel, "fact-sources", root)
    except Exception:                                       # noqa: BLE001
        return None
    try:
        st = path.stat()
    except OSError:
        return (str(path), None, None)
    return (str(path), st.st_mtime_ns, st.st_size)


def _sources(channel, root=None):
    """-> (the channel's fact outlets, None) or ({}, why they were not read)."""
    root = root or ROOT
    key = (str(root), channel)
    stamp = _sources_stamp(channel, root)
    hit = _SOURCES.get(key)
    if hit is not None and stamp is not None and hit[0] == stamp:
        return hit[1]
    try:
        got = (_channel_data().fact_sources(channel, root), None)
    except Exception as e:                                  # noqa: BLE001
        got = ({}, f"the channel's fact outlets were not read: {e}")
    _SOURCES[key] = (stamp, got)
    return got


def _load(p):
    """The JSON object in `p`; None when there is no such file. CF-0719: a
    file that is there and does not read - not JSON, not an object, bytes that
    cannot be read - raises `PublishProfileError` naming it (it used to be
    None, and a broken acceptance log read as an empty feed)."""
    p = Path(p)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise PublishProfileError(p, f"does not read: {e.__class__.__name__}: {e}") from e
    try:
        d = json.loads(text)
    except ValueError as e:
        raise PublishProfileError(p, f"is not JSON: {e}") from e
    if not isinstance(d, dict):
        raise PublishProfileError(p, f"is not a JSON object (a {type(d).__name__})")
    return d


def slugify(text):
    text = re.sub(r"['’]", "", str(text or "").lower())
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _rel(p, root):
    try:
        return str(Path(p).relative_to(root))
    except ValueError:
        return str(p)


# --------------------------------------------------------------------------
# reading one video's batch
# --------------------------------------------------------------------------

def find_script(batch_dir, slug, topic_id=None):
    """`(script, how)` - the video's script in 03, found by name: the Editor's
    output_path stem, the row's topic_id, the slug of `title_ref.name`. `(None,
    why)` when none of them lands on exactly one script, and when 03 or 05 is
    there but broken (CF-0719: `unreadable <file>: ...`, the file named - a
    broken 05 no longer reads as a batch without one)."""
    bd = Path(batch_dir)
    try:
        cr = _load(bd / RESEARCHER_FILE)
        ve = _load(bd / VIDEO_EDITOR_FILE)
    except PublishProfileError as e:
        return None, f"unreadable {e.path.name}: {e}"
    if cr is None:
        return None, f"no readable {RESEARCHER_FILE}"
    scripts = [s for s in (cr.get("scripts") or []) if isinstance(s, dict)]
    by_id = {s.get("script_id"): s for s in scripts if s.get("script_id")}
    for v in (ve or {}).get("videos") or []:
        if isinstance(v, dict) and Path(v.get("output_path") or "").stem == slug:
            s = by_id.get(v.get("script_id"))
            if s is not None:
                return s, "05 videos[].output_path"
    if topic_id:
        hits = [s for s in scripts if s.get("topic_id") == topic_id]
        if len(hits) == 1:
            return hits[0], "topic_id"
    hits = [s for s in scripts
            if slugify((s.get("title_ref") or {}).get("name")) == slug]
    if len(hits) == 1:
        return hits[0], "title_ref.name"
    return None, f"no script of {RESEARCHER_FILE} is named {slug}"


def kind_of_url(url):
    """The fact kind a Wikipedia section anchor names, or None."""
    parts = urlsplit(str(url or ""))
    if not parts.netloc.endswith("wikipedia.org") or not parts.fragment:
        return None
    heading = unquote(parts.fragment).replace("_", " ")
    for kind, pattern in HEADING_KINDS:
        if pattern.search(heading):
            return kind
    return "other"


def fact_of(script, channel=None, root=None):
    """`{fact_kind, fact_kind_from, fact_kind_note, fact_source, fact_text}`.
    `channel` is the batch's channel, whose fact outlets name the source
    (CF-0561); None names none."""
    rec = script.get("fact") if isinstance(script.get("fact"), dict) else None
    old = script.get("production_fact")
    if isinstance(old, list):
        old = old[0] if old else None
    old = old if isinstance(old, dict) else None
    out = {"fact_kind": None, "fact_kind_from": None, "fact_kind_note": None,
           "fact_source": None, "fact_text": None}
    url = (rec or {}).get("url") or (old or {}).get("source_url")
    if rec and rec.get("kind"):
        out["fact_kind"], out["fact_kind_from"] = rec["kind"], FROM_03
    else:
        derived = kind_of_url(url)
        if derived:
            out["fact_kind"], out["fact_kind_from"] = derived, FROM_SECTION
        elif rec is None and old is None:
            out["fact_kind_note"] = "the script carries no fact"
        else:
            out["fact_kind_note"] = ("03 carries no fact.kind (written before CF-0438) "
                                     "and the fact's URL is not a Wikipedia section")
    if url or (rec or {}).get("source"):
        sources, unread = _sources(channel, root) if url else ({}, None)
        where = _fact_rule().source_of(url, sources) if url else {}
        name = (rec or {}).get("source") or where.get("id") or where.get("host")
        if name == "wikipedia":
            name = "Wikipedia"
        out["fact_source"] = {"name": name, "url": url, "id": where.get("id"),
                              "tier": (rec or {}).get("tier") or where.get("tier")}
        if unread:
            out["fact_source"]["note"] = unread
    out["fact_text"] = (rec or {}).get("text") or (old or {}).get("text")
    return out


def score_of(batch_dir, slug):
    """`{tier, score, score_line, score_from}` from scores.collect()."""
    out = {"tier": None, "score": None, "score_line": None, "score_from": None}
    try:
        rows = _scores().collect(batch_dir)
    except Exception:                                       # noqa: BLE001
        return out
    for r in rows:
        if slug in (r.get("slug"), r.get("script_id")):
            line = r.get("score_line")
            if line == getattr(_scores(), "NO_LINE", None):
                line = None
            out.update(tier=r.get("tier"), score=r.get("score"), score_line=line,
                       score_from=r.get("source") if (line or r.get("score") is not None)
                       else None)
            break
    return out


def batch_dir_of(row, root=None):
    """The batch a row's video was built in: `batch_artifact`, else
    `pipeline/<channel>/<batch>` (and under the name it was given, CF-0197;
    `$RUNLOG_POOL` when no root is named - acceptance.batch_pool)."""
    root_given = root
    root = Path(root or ROOT)
    for cand in (row.get("batch_artifact"),):
        if cand:
            p = Path(cand)
            p = p if p.is_absolute() else root / p
            if p.is_dir():
                return p
    # the row's `channel` is a frozen record (CF-0197): resolved at the door,
    # and the name as written is still tried - a batch built before a rename
    # lives under the name it was given
    pool = _acceptance().batch_pool(None if root_given is None else root)
    for ch in dict.fromkeys((_acceptance().resolve_channel(row.get("channel"), root),
                             row.get("channel"), row.get("channel_as_given"))):
        if ch:
            p = pool / ch / str(row.get("batch_id") or "")
            if p.is_dir():
                return p
    return None


def _channel_of_batch(bd, root):
    """The channel a batch belongs to: its own `channel` field (01, then 03),
    else the directory it lives in (`pipeline/<channel>/<batch>`); a former
    id is resolved by the contract. None when neither says."""
    ids = _channel_data()._IDS
    for name in ("01-trend-hunter.json", RESEARCHER_FILE):
        try:
            doc = json.loads((bd / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        ch = ids.resolve_channel(doc.get("channel"), root or ROOT) if isinstance(doc, dict) else None
        if isinstance(ch, str) and ch:
            return ch
    parent = bd.parent.name
    return ids.resolve_channel(parent, root or ROOT) if bd.parent.parent.name == "pipeline" else None


def profile_of(batch_dir, slug, topic_id=None, root=None):
    """The profile of one video, read from its batch. Never raises: a batch or
    a script that is not there is a profile of `None`s with `problem` saying
    which."""
    root = Path(root or ROOT)
    prof = {"task": TASK, "read_from": None, "script_id": None, "script_found_by": None,
            "fact_kind": None, "fact_kind_from": None, "fact_kind_note": None,
            "fact_source": None, "fact_text": None,
            "pattern": None, "rhythm": None,
            "hook_opener": None, "hook_opener_note": None,
            "tier": None, "score": None, "score_line": None, "score_from": None,
            "problem": None}
    if batch_dir is None or not Path(batch_dir).is_dir():
        prof["problem"] = "the batch is not on this disk"
        return prof
    bd = Path(batch_dir)
    prof["read_from"] = _rel(bd, root)
    try:
        script, how = find_script(bd, slug, topic_id)
        if script is None:
            prof["problem"] = how
        else:
            prof["script_id"], prof["script_found_by"] = script.get("script_id"), how
            prof.update(fact_of(script, _channel_of_batch(bd, root), root))
            pat = script.get("pattern") if isinstance(script.get("pattern"), dict) else {}
            prof["pattern"], prof["rhythm"] = pat.get("pattern_id"), pat.get("rhythm_id")
            if "hook_opener_id" not in script:
                prof["hook_opener_note"] = ("03 carries no hook_opener_id (script written "
                                            "before CF-0424)")
            elif not script.get("hook_opener_id"):
                prof["hook_opener_note"] = "the writer used no opener from the library"
            else:
                prof["hook_opener"] = script["hook_opener_id"]
        prof.update(score_of(bd, slug))
    except Exception as e:                                  # noqa: BLE001
        prof["problem"] = f"unreadable: {e.__class__.__name__}: {e}"
    return prof


def profile_of_row(row, root=None):
    return profile_of(batch_dir_of(row, root), row.get("slug"), row.get("topic_id"), root)


# --------------------------------------------------------------------------
# the human line in publish/<day>/<slug>.md
# --------------------------------------------------------------------------

def md_line(prof):
    """One line a human reads: kind, source, pattern, opener, score."""
    def v(x, note=None):
        return f"`{x}`" if x else ("нет" + (f" ({note})" if note else ""))
    kind = v(prof.get("fact_kind"), prof.get("fact_kind_note"))
    if prof.get("fact_kind_from") == FROM_SECTION:
        kind += " (выведен из раздела Википедии)"
    src = prof.get("fact_source") or {}
    source = f"{src.get('name')} — {src.get('url')}" if src.get("url") else v(src.get("name"))
    if src.get("note"):
        source += f" (выход не назван: {src['note']})"
    pattern = (f"`{prof['pattern']}` / `{prof.get('rhythm')}`" if prof.get("pattern")
               else "нет")
    opener = v(prof.get("hook_opener"), prof.get("hook_opener_note"))
    score = prof.get("score_line") or "нет (в 05/06 нет строки очков, CF-0434)"
    line = (f"Вид факта {kind} · источник {source} · паттерн {pattern} · зачин хука "
            f"{opener} · очки {score}")
    if prof.get("problem"):
        line += f" · не восстановлено: {prof['problem']}"
    return line


def _layout():
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import publish_layout                                   # noqa: PLC0415
    return publish_layout


def stamp_md(path, prof, write=True):
    """Put (or replace) the `## Профиль ролика` section in a publish note.
    Returns the new text, or None when there is no note."""
    p = Path(path)
    if not p.is_file():
        return None
    text = p.read_text(encoding="utf-8")
    block = (f"{MD_HEADING}\n{md_line(prof)} (`{TASK}`, машинная запись — "
             f"`profile` в `publish/acceptance-log.json`)\n")
    # CF-0463: exactly the heading and its own lines up to the first blank
    # line - whatever a human wrote after the profile (day-drinker: «Загружен
    # и запланирован …») stays, whether or not a `## ` heading precedes it.
    pat = re.compile(rf"^{re.escape(MD_HEADING)}[ \t]*\n(?:[^\n]*\S[^\n]*(?:\n|\Z))*",
                     re.M)
    m = pat.search(text)
    if m:
        rest = text[m.end():]
        new = text[:m.start()] + block + ("\n" + rest.lstrip("\n") if rest.strip() else "")
        new = new.rstrip("\n") + "\n"
    else:
        new = text.rstrip("\n") + "\n\n" + block
    if write and new != text:
        p.write_text(new, encoding="utf-8")
    return new


# --------------------------------------------------------------------------
# filling the rows filed before this task
# --------------------------------------------------------------------------

def fill(root=None, refresh=False, dry_run=False):
    """Profile every accepted row of `<root>/publish/acceptance-log.json` that
    has none (`refresh`: every accepted row), and stamp its publish note.
    Returns `[{entry_id, slug, profile, md, action}]`. `dry_run` writes
    nothing. A log that is there but broken raises `PublishProfileError`
    (CF-0719) - nothing is filled over it; a missing one is an empty list."""
    root = Path(root or ROOT)
    acc = _acceptance()
    log_path = root / "publish" / "acceptance-log.json"
    doc = _load(log_path) or {}
    rows = [r for r in doc.get("acceptances") or [] if isinstance(r, dict)]
    out, changed = [], False
    for row in rows:
        if row.get("verdict") != acc.ACCEPTED:
            continue
        # CF-0475: the notes of the name are wherever the layout keeps them
        # (the row's channel, a day or `_queue/`, or the flat root before
        # migration). CF-0463: a note is stamped only by the row of the version
        # it describes (`_owns`) - never by the latest acceptance of the name.
        lay = _layout()
        mds = [e["md"] for e in lay.locate(row.get("slug"), publish=root / "publish",
                                           channel=lay.channel_of_row(row, root=root))
               if e.get("md")]
        reason = None
        if row.get("profile") and not refresh:
            prof, action = row["profile"], "kept"
        else:
            prof = profile_of_row(row, root)
            action = "filled"
            # CF-0487: a refresh replaces a profile only with one read from a
            # batch. The sources go once the video is out (CF-0358) - a profile
            # taken from the live batch is not swapped for an empty stub.
            reason = _unreadable(prof) if row.get("profile") else None
            if reason:
                prof, action = row["profile"], "kept"
            elif not dry_run:
                row["profile"] = prof
                changed = True
        md_state = "no note"
        mine = [md for md in mds if _owns(row, md, rows, root)]
        if mine:
            md_state = "stamped"
            if not dry_run:
                for md in mine:
                    stamp_md(md, prof)
        elif mds:
            md_state = _not_mine(mds)
        res = {"entry_id": row.get("entry_id"), "slug": row.get("slug"),
               "profile": prof, "md": md_state, "action": action}
        if reason:
            res["reason"] = f"refresh kept the profile on file: {reason}"
        out.append(res)
    if changed:
        acc.write_log(rows, path=log_path, note=doc.get("note"))
    return out


def _unreadable(prof):
    """Why a freshly read profile is nothing to replace one on file with
    (CF-0487), or None: the batch is not on this disk, or it could not be
    read at all."""
    problem = prof.get("problem") or ""
    if prof.get("read_from") is None or problem.startswith("unreadable"):
        return problem or "nothing was read"
    return None


def _owns(row, md, rows, root):
    """Does this note describe this row's version? CF-0463: by the batch the
    note names itself (`Батч \`pipeline/<канал>/<батч>\``); a note that names
    none, by the row whose `publish_path` is this note's video. Neither - the
    note is left alone (01.10: the 2210Z rebuilds of four videos that had gone
    out as 1722Z/1757Z/1248Z stamped their notes, being the latest acceptance)."""
    lay = _layout()
    batch = lay.card_batch(md)
    if batch is not None:
        return any(r is row for r in lay.row_of_batch(rows, row.get("slug"), batch))
    where = lay.bucket_of(md, publish=Path(root) / "publish")
    if where is None or not row.get("publish_path"):
        return False
    path = lay.rel(where[0], where[1], row.get("slug"))
    pointing = [r for r in rows if r.get("slug") == row.get("slug")
                and r.get("verdict") == _acceptance().ACCEPTED
                and r.get("publish_path") == path]
    # two versions claiming one file (the verdict used to write the path,
    # CF-0475 class) say nothing about which one lies there
    return len(pointing) == 1 and pointing[0] is row


def _not_mine(mds):
    lay = _layout()
    named = [lay.card_batch(md) for md in mds]
    if any(named):
        return ("note describes another version (" +
                ", ".join(f"{b[0]}/{b[1]}" for b in named if b) + ")")
    return "note names no batch and no publish_path points at it - left alone"


# --------------------------------------------------------------------------
# the feed and its diversity
# --------------------------------------------------------------------------

def _order(row):
    return (str(row.get("answered_at") or ""), str(row.get("recorded_at") or ""))


def feed(rows_all, dedupe_only=False):
    """The accepted videos, latest standing acceptance per name, in the order
    the user accepted them. `dedupe_only` returns the {slug: row} map."""
    acc = _acceptance()
    latest = {}
    for r in sorted(rows_all, key=_order):
        if r.get("verdict") == acc.ACCEPTED and r.get("slug"):
            latest[r["slug"]] = r
    # A video the user pulled is its row amended to a rejection (everyday-sorcery-2:
    # one row, the acceptance in its history), so it is simply not here; a
    # rejected rebuild of a video (widows-bay 0725Z) does not pull the version
    # that went out.
    if dedupe_only:
        return latest
    return sorted(latest.values(), key=_order)


AXES = (("fact_kind", "вид факта"), ("pattern", "паттерн"), ("rhythm", "ритм"),
        ("hook_opener", "зачин хука"))


def channel_rows(rows_all, channel, root=None):
    """CF-0719: `(today's id of channel, the rows of rows_all on it)` - a row's
    channel as the publish layout reads it (`channel_of_row`: a former id
    resolved, a `rebuilds` row the one channel on file's)."""
    want = _acceptance().resolve_channel(channel, root)
    lay = _layout()
    return want, [r for r in rows_all if lay.channel_of_row(r, root=root) == want]


def diversity(rows_all, last=DEFAULT_LAST, root=None, live=True, channel=None):
    """`{videos: [slug...], n, read_live: [slug...], axes: {axis: [(value,
    count, share)...]}}` for the last `last` videos of the feed. A row with no
    `profile` yet is read from its batch on the spot when `live` (nothing is
    written) and named under `read_live`; a batch that is gone counts under
    `unknown`. `channel` (CF-0719): only that channel's rows (`channel_rows`),
    before the last N are taken, and the answer carries `channel` - today's
    id; None - every channel, the answer as before."""
    want = None
    if channel:
        want, rows_all = channel_rows(rows_all, channel, root)
    videos = feed(rows_all)
    if last and last > 0:
        videos = videos[-last:]
    n = len(videos)
    profiles, read_live = [], []
    for r in videos:
        prof = r.get("profile")
        if not prof and live:
            prof = profile_of_row(r, root)
            read_live.append(r.get("slug"))
        profiles.append(prof or {})
    axes = {}
    for key, _label in AXES:
        counts = {}
        for prof in profiles:
            val = prof.get(key) or UNKNOWN
            counts[val] = counts.get(val, 0) + 1
        axes[key] = [(v, c, round(c / n, 3) if n else 0.0)
                     for v, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    out = {"videos": [r.get("slug") for r in videos], "n": n, "read_live": read_live,
           "axes": axes}
    if want is not None:
        out["channel"] = want
    return out


def render_diversity(d):
    where = f" канала {d['channel']}" if d.get("channel") else ""
    lines = [f"Разнообразие ленты{where}: последние {d['n']} роликов "
             f"({', '.join(d['videos']) or 'нет'})"]
    if d.get("read_live"):
        lines.append(f"  профиль не записан, прочитан из батча сейчас: "
                     f"{', '.join(d['read_live'])} (записать - runlog profile --fill)")
    for key, label in AXES:
        parts = [f"{v} {c} ({round(s * 100)}%)" for v, c, s in d["axes"][key]]
        lines.append(f"  {label}: {', '.join(parts) or '-'}")
    return lines


def render_fill(results, dry_run):
    head = "СУХОЙ ПРОГОН, ничего не записано" if dry_run else "записано"
    lines = [f"profile --fill ({head}): {len(results)} принятых строк"]
    for r in results:
        p = r["profile"]
        lines.append(f"- {r['entry_id']} [{r['action']}, .md: {r['md']}]"
                     + (f" - {r['reason']}" if r.get("reason") else ""))
        lines.append(f"    {md_line(p)}")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(prog="runlog profile|diversity")
    ap.add_argument("cmd", choices=("profile", "diversity"))
    ap.add_argument("--root", help="the data root (publish/ and pipeline/); default: this repo")
    ap.add_argument("--fill", action="store_true", help="profile accepted rows that have none")
    ap.add_argument("--refresh", action="store_true", help="with --fill: re-read every row (a profile whose batch is gone stays, CF-0487)")
    ap.add_argument("--dry-run", action="store_true", help="with --fill: write nothing")
    ap.add_argument("--last", type=int, default=DEFAULT_LAST)
    ap.add_argument("--channel", help="diversity: one channel's feed (a former id resolves)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve() if a.root else ROOT
    try:
        return _main(a, root)
    except PublishProfileError as e:
        # CF-0719: a broken log is said, never printed as an empty feed
        print(f"runlog {a.cmd}: {e}", file=sys.stderr)
        return 2


def _main(a, root):
    if a.cmd == "diversity":
        doc = _load(root / "publish" / "acceptance-log.json") or {}
        d = diversity([r for r in doc.get("acceptances") or [] if isinstance(r, dict)],
                      last=a.last, root=root, channel=a.channel)
        print(json.dumps(d, ensure_ascii=False, indent=2) if a.json
              else "\n".join(render_diversity(d)))
        return 0
    if a.fill:
        res = fill(root, refresh=a.refresh, dry_run=a.dry_run)
        print(json.dumps(res, ensure_ascii=False, indent=2) if a.json
              else "\n".join(render_fill(res, a.dry_run)))
        return 0
    doc = _load(root / "publish" / "acceptance-log.json") or {}
    rows = feed([r for r in doc.get("acceptances") or [] if isinstance(r, dict)])
    if a.json:
        print(json.dumps({r["slug"]: r.get("profile") for r in rows}, ensure_ascii=False,
                         indent=2))
    else:
        for r in rows:
            p = r.get("profile")
            print(f"- {r.get('entry_id')}: " + (md_line(p) if p else
                  "нет профиля (runlog profile --fill)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
