#!/usr/bin/env python3
"""Fetch source footage with yt-dlp into the factory-wide cache.

The first pipeline had no yt-dlp at all, so it screen-recorded a browser; when
YouTube's streaming went flaky mid-session the whole approach collapsed to
still photos. Downloading directly removes that dependency and gets native
resolution instead of a capture of a player.

The cache is shared across channels because they overlap thematically - one
trailer earns its keep in several videos. Every entry records where it came
from and whether the uploader is the official channel, because Compliance
Checker downstream needs that distinction and cannot recover it later.

CF-0090: a failed download must leave nothing behind. yt-dlp writes its
intermediates (`<id>.f616.mp4`, `.part`, `.ytdl`) into a per-fetch temp dir
under the cache and only the merged final file is moved next to index.json;
on a non-zero exit, or a missing / empty final file, the temp dir and any
`<id>` partial in the cache are removed and nothing is registered. Every
real fetch also sweeps orphan partials first, so a leftover from an older
run (2026-09-03T2037Z left `Hk_xChyX9kc.f616.mp4`, 1.1GB) goes on the next
ingest, not by hand. "Cached" means a registered entry whose final file is
present and non-empty - never "some file with this prefix exists".

This script does one download and reports honestly; whether to try another
candidate is decided one level up, in ingest_batch.py.

Usage:
    fetch_footage.py <url> [--official] [--note "..."]
    fetch_footage.py <source_url> --archive-json '<candidate>' [--licences-json '<lists>']
                     [--max-duration S] [--max-height H] [--official]
    fetch_footage.py <page url> --own-capture-json '<candidate>' [--rights-json '<rights>']
    fetch_footage.py --list

CF-0665: an archive candidate (`nasa:<id>` / `commons:<pageid>`, TH-3) is not a
video-site page: `--archive-json` hands over its whole candidate record and the
file is downloaded from its `download_url` directly (`archive_source.py`) -
no yt-dlp. It is kept as `<file id>.mp4`
(`nasa-<id>` / `commons-<pageid>`), its licence is read again from the
archive before the download (exit LICENCE_CHANGED_EXIT with one
`LICENCE_CHANGED {json}` line when it is not the one the candidate was judged
on), the length ceiling is the candidate's `duration_seconds` before and
ffprobe's after, and WebM / Ogg become mp4 through ffmpeg.

CF-0567: an own capture (`own_capture:<id>`, ExampleTech's own screen recording,
the Video Editor's capture_tool.py) is not downloaded at all: `--own-capture-json`
hands over its candidate record with `capture_file` (the recording ingest_batch
found, `own_capture_source.locate`), and the finished mp4 and its
`.own_capture.json` sidecar are copied into the pool as `<file id>.mp4` /
`<file id>.own_capture.json`. A missing sidecar, a sidecar that is not an own
capture's or not this file's, and a length or frame size ffprobe disagrees with
are refused (exit 1, one `own_capture_refused: ...` line) with nothing copied.
No duration ceiling.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402 - CF-0267
from _fi_paths import pool_dir, venv_bin as _venv_bin  # noqa: E402 - CF-0267: unique name, see _fi_paths.py
import source_rights  # noqa: E402 - CF-0663: the rights record of a source
import archive_source  # noqa: E402 - CF-0665: NASA / Commons files, fetched directly
import own_capture_source  # noqa: E402 - CF-0567: ExampleTech's own screen recordings

CACHE = pool_dir()  # CF-0620: this checkout's factory (or FACTORY_ROOT), not the home checkout
INDEX = CACHE / "index.json"
import shutil as _shutil

_LOCAL = _venv_bin("yt-dlp")  # CF-0267: a worktree has no .venv of its own
# Prefer this agent's own copy, but fall back to whatever is on PATH so the
# fetcher stays usable before the environment is fully built.
YTDLP = _LOCAL if _LOCAL.exists() else (_shutil.which("yt-dlp") or str(_LOCAL))

# How long yt-dlp waits between two of its own HTTP requests. The gap between
# two *sources* is ingest_batch.py's (FETCH_PAUSE_SECONDS); this one is about
# the handful of requests inside one download.
SLEEP_REQUESTS_SECONDS = 1.5


# ---------------------------------------------------------------------------
# How long a video is, asked without downloading it (CF-0302)
#
# On batch 2026-09-21T0358Z `Lv_GOa6HXVA` - a 2 h 14 min news talk show with
# the word "Trailer" in its title and 46 views - was offered as a topic's
# second source, came down whole, and its index was still in the shot-splitting
# pass 41 minutes later, a tenth of the way through the file, when the stage
# operator killed it by hand. The topic lost the attempt, hit the CF-0129 cap
# and was refused with two unused candidates and a good first source in hand.
#
# Nothing in the download tells the length in time to act on it, so it is
# asked for on its own: one metadata request, `--skip-download`, no media and
# no cache entry written. The caller (ingest_batch.py's duration ceiling) asks
# before it spends a topic's attempt.
#
# The answer is a `Metadata`, never an exception: a probe that did not answer
# must not decide anything.
DURATION_ARGS = ["--print", "%(duration)s", "--skip-download",
                 "--no-playlist", "--no-warnings"]
DURATION_TIMEOUT_SECONDS = 60

Metadata = namedtuple("Metadata", "seconds error")

# CF-0333: the ceiling held on the fact, inside the download request itself.
#
# The probe above is a promise: it is asked once, and a probe that got no
# answer decides nothing - which the ceiling rightly reads as "not a refusal".
# One 8019 s video once came down whole for that reason, 2 GB of it. So the
# download carries the ceiling as well:
# yt-dlp extracts the video's metadata before it selects a format, and
# `--match-filter` is applied right there, on the number from that very
# request, before a byte of media moves. `<=?` keeps the CF-0302 rule that a
# length nobody knows (a live stream, "NA") is never a refusal.
#
# The length is printed at `pre_process`, which yt-dlp runs *before* the
# filter, so the refusal can name the number; a filtered video exits 0 with
# no file, and this script turns that into TOO_LONG_EXIT and one TOO_LONG line
# on stderr, which ingest_batch.py reads as `source_too_long`.
DURATION_MARK = "duration="
TOO_LONG_EXIT = 3
TOO_LONG_PREFIX = "TOO_LONG"
TOO_LONG_LINE = (TOO_LONG_PREFIX + " seconds={seconds} limit={limit} - {vid} is over "
                 "the {limit} s ceiling; yt-dlp's match filter refused it before any "
                 "media moved (CF-0333); nothing registered")


def max_duration_args(limit):
    """The yt-dlp arguments that hold a download to `limit` seconds."""
    return ["--match-filter", f"duration <=? {int(limit)}",
            "--print", f"pre_process:{DURATION_MARK}%(duration)s"]


def printed_duration(lines):
    """The length the `pre_process` print carried, or None."""
    for line in lines:
        if line.startswith(DURATION_MARK):
            try:
                v = float(line[len(DURATION_MARK):])
            except ValueError:
                return None
            return v if v > 0 else None
    return None


def parse_too_long(text):
    """(seconds, limit) from a TOO_LONG line in `text`, or None."""
    for line in (text or "").splitlines():
        if line.startswith(TOO_LONG_PREFIX + " "):
            fields = dict(f.split("=", 1) for f in line.split()[1:3] if "=" in f)
            try:
                return float(fields["seconds"]), float(fields["limit"])
            except (KeyError, ValueError):
                return None
    return None


def probe_duration(url, runner=None, timeout=DURATION_TIMEOUT_SECONDS):
    """The length of the video at `url` in seconds, without fetching it.

    Returns a `Metadata`: `seconds` is a float when the source answered with a
    number and None otherwise, `error` the line that explains an unanswered
    probe. Never raises - a probe is a convenience the caller may do without.

    `runner` is the subprocess seam: tests pass a stub and no request is made.
    """
    cmd = [str(YTDLP), url, *DURATION_ARGS,
           "--sleep-requests", str(SLEEP_REQUESTS_SECONDS)]
    run = runner or subprocess.run
    try:
        out = run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as e:                      # a probe never breaks a fetch
        return Metadata(None, f"{type(e).__name__}: {e}")
    err = (out.stderr or "").strip()
    if out.returncode != 0:
        return Metadata(None, err.splitlines()[-1] if err else
                        f"yt-dlp exit {out.returncode} with nothing on stderr")
    lines = [l.strip() for l in (out.stdout or "").splitlines() if l.strip()]
    text = lines[0] if lines else ""
    try:
        seconds = float(text)
    except ValueError:
        # "NA" is what yt-dlp prints for a live stream and for a video whose
        # metadata carries no duration at all.
        return Metadata(None, f"yt-dlp printed {text!r}, not a duration")
    if seconds <= 0:
        return Metadata(None, f"yt-dlp printed a duration of {seconds}")
    return Metadata(seconds, None)


# ---------------------------------------------------------------------------
# Exit codes the fetcher reports to ingest_batch.py
# CF-0663: a `--rights-json` record whose licence was judged and refused.
LICENCE_EXIT = 5
LICENCE_LINE = "LICENCE {url} not fetched: {reason} (CF-0663)"
# CF-0665: an archive file whose licence, read again from the archive before
# the download, is not the one the candidate was judged on.
LICENCE_CHANGED_EXIT = 6
LICENCE_CHANGED_CODE = archive_source.LICENCE_CHANGED_CODE
LICENCE_CHANGED_PREFIX = "LICENCE_CHANGED"
ARCHIVE_FAILED_LINE = "ARCHIVE {vid}: {what}"
def licence_changed_line(check):
    """CF-0665: the one stderr line of a `licence_changed` refusal."""
    return LICENCE_CHANGED_PREFIX + " " + json.dumps(check, ensure_ascii=False)


def parse_licence_changed(text):
    """The re-read record of a `licence_changed` refusal, out of the fetcher's
    stderr, or None."""
    for line in reversed(str(text or "").splitlines()):
        line = line.strip()
        if line.startswith(LICENCE_CHANGED_PREFIX + " "):
            try:
                rec = json.loads(line[len(LICENCE_CHANGED_PREFIX) + 1:])
            except ValueError:
                return None
            return rec if isinstance(rec, dict) else None
    return None


def load_index():
    if INDEX.exists():
        return json.load(open(INDEX))
    return {"entries": []}


def save_index(idx):
    CACHE.mkdir(parents=True, exist_ok=True)
    json.dump(idx, open(INDEX, "w"), indent=2)


# The cache is factory-wide and grows without bound otherwise. 100GB against
# the ~420GB free here; eviction is by least-recently-used, and a file's
# sidecars go with it so an index never outlives the footage it describes.
BUDGET_BYTES = 100 * 1024 ** 3


def entry_size(entry):
    total = 0
    for f in sidecars(entry["path"]):
        if f.exists():
            total += f.stat().st_size
    return total


def sidecars(path):
    p = Path(path)
    # CF-0080: the content fingerprint rides with the media too - it is only
    # a shortcut for the next batch's dedup and must not outlive the file.
    out = [p, p.with_suffix(".shots.json"), p.with_suffix(".contact.jpg"),
           p.with_suffix(".fingerprint.json")]
    if own_capture_source.is_own_capture(p.stem):
        # CF-0567: an own capture's recorder sidecar lives and dies with it.
        out.append(own_capture_source.sidecar_path(p))
    return out


def prune(idx, budget=BUDGET_BYTES, protect=()):
    """Evict least-recently-used entries until the cache fits its budget."""
    entries = [e for e in idx["entries"] if Path(e["path"]).exists()]
    total = sum(entry_size(e) for e in entries)
    if total <= budget:
        return [], total

    # Never evict what a caller is using right now, nor the underlay loops -
    # those are a standing asset, not a per-video download.
    keep = set(protect)
    candidates = [e for e in entries
                  if e["path"] not in keep and "/underlay/" not in e["path"]]
    candidates.sort(key=lambda e: e.get("last_used", e.get("fetched_at", "")))

    evicted = []
    for e in candidates:
        if total <= budget:
            break
        size = entry_size(e)
        for f in sidecars(e["path"]):
            if f.exists():
                f.unlink()
        idx["entries"] = [x for x in idx["entries"] if x["path"] != e["path"]]
        evicted.append(e["path"])
        total -= size
    return evicted, total


# ---------------------------------------------------------------------------
# CF-0090: partial files and the per-fetch temp dir.
#
# What yt-dlp leaves mid-way, by name, next to a final `<id>.mp4`:
#   <id>.f616.mp4            one stream of a bestvideo+bestaudio merge
#   <id>.f616.mp4.part       a stream still being written
#   <id>.f616.mp4.ytdl       the resume state for that stream
#   <id>.f616.mp4.part-Frag3 one fragment of a fragmented stream
#   <id>.temp.mp4            the merger's output before the move
# None of the real sidecars (.mp4 / .shots.json / .contact.jpg /
# .fingerprint.json, and index.json) match this, so a sweep can never touch
# footage that is or could be registered.
PARTIAL_RE = re.compile(
    r"^(?P<id>[^./]+)\.(?:f\d+\.[A-Za-z0-9]+|.+\.part(?:-Frag\d+)?|.+\.ytdl|temp\.[A-Za-z0-9]+)$")

# Where one fetch's intermediates live: a dir per process under the cache,
# so a crash mid-download leaves one obviously-temporary dir, not a spray
# of `<id>.f*` files that look like footage.
TEMP_PREFIX = ".fetch-tmp-"

# The log lines the RUN_LOG will carry. SWEEP is one line per orphan found
# at startup; CLEANUP is one line per failed fetch, naming everything that
# went with it.
SWEEP_LINE = "SWEEP {vid}: orphan partial removed {name} ({size})"
SWEEP_DIR_LINE = "SWEEP: stale temp dir removed {name} ({size})"
CLEANUP_LINE = "CLEANUP {vid}: yt-dlp failed, removed {what}; nothing registered"


def partial_id(name):
    """The video id a partial file name belongs to, or None if the name is
    not a yt-dlp intermediate."""
    m = PARTIAL_RE.match(name)
    return m.group("id") if m else None


def fmt_size(nbytes):
    if nbytes >= 1024 ** 3:
        return f"{nbytes / 1024 ** 3:.2f}GB"
    if nbytes >= 1024 ** 2:
        return f"{nbytes / 1024 ** 2:.1f}MB"
    return f"{nbytes}B"


def _tree_size(d):
    return sum(f.stat().st_size for f in Path(d).rglob("*") if f.is_file())


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def temp_dir_for(pid=None):
    return CACHE / f"{TEMP_PREFIX}{pid if pid is not None else os.getpid()}"


def partials_for(vid):
    """Every partial of one id lying loose in the cache (top level only)."""
    if not vid or not CACHE.exists():
        return []
    return sorted(f for f in CACHE.iterdir()
                  if f.is_file() and partial_id(f.name) == vid)


def cleanup_partials(vid, tmp=None):
    """Remove one failed fetch's leftovers: its temp dir and any `<id>`
    partial in the cache. Returns [(name, bytes)] of what was removed."""
    removed = []
    if tmp is not None and Path(tmp).is_dir():
        removed.append((Path(tmp).name + "/", _tree_size(tmp)))
        _shutil.rmtree(tmp, ignore_errors=True)
    for f in partials_for(vid):
        removed.append((f.name, f.stat().st_size))
        f.unlink()
    return removed


def sweep_partials(log=print):
    """Startup sweep: remove every orphan partial in the cache and every
    temp dir whose fetch process is gone. Registered footage and its
    sidecars are never candidates (see PARTIAL_RE). Returns [(name, bytes)]."""
    removed = []
    if not CACHE.exists():
        return removed
    for f in sorted(CACHE.iterdir()):
        if f.is_file():
            vid = partial_id(f.name)
            if vid is None:
                continue
            size = f.stat().st_size
            f.unlink()
            removed.append((f.name, size))
            log(SWEEP_LINE.format(vid=vid, name=f.name, size=fmt_size(size)))
        elif f.is_dir() and f.name.startswith(TEMP_PREFIX):
            suffix = f.name[len(TEMP_PREFIX):]
            if suffix.isdigit() and _pid_alive(int(suffix)):
                continue  # another fetch is using it right now
            size = _tree_size(f)
            _shutil.rmtree(f, ignore_errors=True)
            removed.append((f.name + "/", size))
            log(SWEEP_DIR_LINE.format(name=f.name, size=fmt_size(size)))
    return removed


def cached_entry(idx, url):
    """The registered entry for `url` whose final file is present and
    non-empty, else None. Presence of a file alone never counts."""
    for e in idx["entries"]:
        if e["url"] != url:
            continue
        p = Path(e["path"])
        if p.is_file() and p.stat().st_size > 0:
            return e
    return None


# CF-0665: the network and subprocess seams of the archive path - None is
# urllib's urlopen and subprocess.run; a test sets stand-ins here.
ARCHIVE_OPENER = None
ARCHIVE_RUNNER = None


def cached_by_id(idx, fid):
    """CF-0665: the registered entry whose id is `fid` (an archive file's
    `nasa-<id>` / `commons-<pageid>`) and whose final file is present and
    non-empty, else None. An archive item is one file whatever rendition or
    address it was offered under, so it is found by its id, not its URL."""
    for e in idx["entries"]:
        if e.get("id") != fid:
            continue
        p = Path(e["path"])
        if p.is_file() and p.stat().st_size > 0:
            return e
    return None


def _archive_fail(fid, tmp, what):
    removed = cleanup_partials(fid, tmp)
    gone = ", ".join(f"{n} ({fmt_size(b)})" for n, b in removed) or "nothing to remove"
    print(ARCHIVE_FAILED_LINE.format(vid=fid, what=what), file=sys.stderr)
    print(f"CLEANUP {fid}: archive download failed, removed {gone}; nothing registered",
          file=sys.stderr)
    sys.exit(f"archive download failed for {fid}: {what}")


def fetch_archive(args, cand, record=None, licences=None, opener=None,
                  rule="auto", runner=None):
    """CF-0665: one archive candidate (`cand`, the Trend Hunter's record) into
    the cache as `<file id>.mp4`. The same contract as the yt-dlp path:
    `cached -> <path>` / `fetched -> <path>` on stdout, TOO_LONG_EXIT,
    LICENCE_CHANGED_EXIT, and any other failure an exit with a
    message and nothing registered. `opener` / `runner` are the network and
    subprocess seams of the tests."""
    import subprocess as _sp
    runner = runner or _sp.run
    cid = str(cand.get("candidate_id") or cand.get("video_id") or "")
    fid = archive_source.file_id(cid)
    url = cand.get("download_url")
    if not archive_source.is_archive(cid) or not url:
        sys.exit(f"--archive-json: {cid or '?'} is not an archive candidate with a "
                 f"download_url (CF-0665)")
    runlog.annotate(video=fid)
    idx = load_index()

    sweep_partials(log=lambda m: print(m, file=sys.stderr))

    e = cached_by_id(idx, fid)
    if e is not None:
        e["last_used"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if record is not None:
            source_rights.merge_into_entry(e, record)
        save_index(idx)
        runlog.annotate(cached=True)
        print(f"cached -> {e['path']}")
        return

    # CF-0302 / CF-0333: the ceiling on the length the archive gave, before
    # anything moves; ffprobe's after the download for a file without one.
    limit = args.max_duration
    said = cand.get("duration_seconds")
    if (limit and isinstance(said, (int, float)) and not isinstance(said, bool)
            and said > limit):
        runlog.annotate(too_long=True, duration_s=said)
        print(TOO_LONG_LINE.format(seconds=int(round(said)), limit=int(limit), vid=fid),
              file=sys.stderr)
        sys.exit(TOO_LONG_EXIT)

    # The licence, read again from the archive.
    mod = source_rights.licence_rule() if rule == "auto" else rule
    check = archive_source.recheck(dict(cand, candidate_id=cid), licences=licences,
                                   rule=mod, opener=opener)
    check["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if check.get("changed"):
        runlog.annotate(licence_changed=True)
        print(licence_changed_line(dict(check, reason_code=LICENCE_CHANGED_CODE,
                                        video_id=fid, candidate_id=cid)),
              file=sys.stderr)
        sys.exit(LICENCE_CHANGED_EXIT)
    if not check.get("read"):
        print(f"LICENCE {fid}: not read again ({check.get('error')}) - the candidate's "
              f"own verdict stands (CF-0665)", file=sys.stderr)

    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = temp_dir_for()
    tmp.mkdir(parents=True, exist_ok=True)
    suffix = archive_source.suffix_for(cand.get("media_type"), url)
    part = tmp / f"{fid}{suffix}.part"
    try:
        got = archive_source.download(url, part, max_bytes=archive_source.MAX_BYTES,
                                      opener=opener)
    except archive_source.ArchiveError as exc:
        _archive_fail(fid, tmp, str(exc))
    want = cand.get("bytes")
    if isinstance(want, int) and want > 0 and got["bytes"] != want:
        print(f"ARCHIVE {fid}: {got['bytes']} bytes came, the candidate said {want} "
              f"(the archive's file changed since it was found)", file=sys.stderr)
    raw = tmp / f"{fid}{suffix if suffix != '.bin' else '.media'}"
    part.rename(raw)
    info = archive_source.probe(raw, runner=runner)
    if info is None:
        _archive_fail(fid, tmp, f"ffprobe finds no picture in {raw.name}")
    if limit and info.get("duration") and info["duration"] > limit:
        removed = cleanup_partials(fid, tmp)
        runlog.annotate(too_long=True, duration_s=info["duration"])
        print(TOO_LONG_LINE.format(seconds=int(round(info["duration"])), limit=int(limit),
                                   vid=fid), file=sys.stderr)
        sys.exit(TOO_LONG_EXIT)
    staged = tmp / f"{fid}.staged.mp4"
    try:
        encoded = archive_source.to_mp4(raw, staged, info, max_height=args.max_height,
                                        runner=runner)
    except archive_source.ArchiveError as exc:
        _archive_fail(fid, tmp, str(exc))
    final = CACHE / f"{fid}.mp4"
    _shutil.move(str(staged), str(final))
    _shutil.rmtree(tmp, ignore_errors=True)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    arch = cand.get("archive") if isinstance(cand.get("archive"), dict) else {}
    entry = {
        "id": fid,
        "url": args.url,
        "path": str(final),
        "title": cand.get("title") or "",
        "uploader": cand.get("channel_title") or "",
        "duration": info.get("duration") or said,
        # NASA's library is an official origin (the Trend Hunter's
        # `origin: official`); a Commons file is anyone's upload.
        "official_channel": bool(args.official),
        "note": args.note,
        "fetched_at": now,
        "last_used": now,
        "candidate_id": cid,
        "archive": {"name": arch.get("name") or archive_source.ARCHIVES.get(
                        archive_source.archive_of(cid)),
                    "id": arch.get("id"), "rendition": arch.get("rendition"),
                    "download_url": url, "media_type": cand.get("media_type"),
                    "bytes": got["bytes"], "download_seconds": got["seconds"],
                    "re_encoded": bool(encoded), "width": info.get("width"),
                    "height": info.get("height")},
        "licence_recheck": check,
    }
    if record is not None:
        source_rights.merge_into_entry(entry, dict(record, licence_recheck=check))
    idx["entries"].append(entry)
    evicted, _total = prune(idx, protect=(str(final),))
    save_index(idx)
    for gone in evicted:
        print(f"  evicted from cache (budget {BUDGET_BYTES // 1024 ** 3}GB): {gone}",
              file=sys.stderr)
    print(f"fetched -> {final}")


def _own_capture_fail(fid, tmp, refusals):
    if tmp is not None:
        cleanup_partials(fid, tmp)
    runlog.annotate(own_capture_refused=",".join(c for c, _ in refusals))
    sys.exit(own_capture_source.refused_line(fid, refusals))


def fetch_own_capture(args, cand, record=None, runner=None):
    """CF-0567: one own capture (`cand`, its candidate record with
    `capture_file`) into the cache as `<file id>.mp4` beside its
    `<file id>.own_capture.json`. The yt-dlp path's contract on stdout
    (`cached -> <path>` / `fetched -> <path>`); a refusal is an exit with one
    `own_capture_refused: ...` line and nothing registered. `runner` is the
    ffprobe seam of the tests."""
    import subprocess as _sp
    runner = runner or _sp.run
    cid = str(cand.get("candidate_id") or cand.get("video_id") or "")
    if not own_capture_source.is_own_capture(cid):
        sys.exit(f"--own-capture-json: {cid or '?'} is not an own capture (CF-0567)")
    fid = own_capture_source.file_id(cid)
    runlog.annotate(video=fid)
    idx = load_index()
    sweep_partials(log=lambda m: print(m, file=sys.stderr))

    e = cached_by_id(idx, fid)
    if e is not None and own_capture_source.sidecar_path(e["path"]).is_file():
        e["last_used"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if record is not None:
            source_rights.merge_into_entry(e, record)
        save_index(idx)
        runlog.annotate(cached=True)
        print(f"cached -> {e['path']}")
        return

    named = cand.get(own_capture_source.CAPTURE_FILE_KEY)
    # The candidate's own path (ingest_batch writes the one it found), else the
    # factory's inbox - a run by hand names the file or uses the inbox.
    src = own_capture_source.locate(fid, cand, own_capture_source.capture_dirs(
        root=CACHE.parent.parent))
    if src is None:
        _own_capture_fail(fid, None, [(own_capture_source.NO_RECORDING,
                                       f"no recording at {named or '(no capture_file on the candidate)'}")])
    sidecar = own_capture_source.read_sidecar(src)
    refusals = own_capture_source.sidecar_refusals(fid, sidecar)
    if refusals:
        _own_capture_fail(fid, None, refusals)
    info = archive_source.probe(src, runner=runner)
    refusals = own_capture_source.probe_refusals(fid, sidecar, info)
    if refusals:
        _own_capture_fail(fid, None, refusals)

    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = temp_dir_for()
    tmp.mkdir(parents=True, exist_ok=True)
    staged = tmp / f"{fid}.staged.mp4"
    try:
        _shutil.copyfile(str(src), str(staged))
    except OSError as exc:
        _own_capture_fail(fid, tmp, [(own_capture_source.NO_RECORDING,
                                      f"the recording did not copy: {exc}")])
    final = CACHE / f"{fid}.mp4"
    side_final = own_capture_source.sidecar_path(final)
    side_final.write_text(json.dumps(sidecar, ensure_ascii=False, indent=1) + "\n",
                          encoding="utf-8")
    _shutil.move(str(staged), str(final))
    _shutil.rmtree(tmp, ignore_errors=True)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entry = {
        "id": fid,
        "url": args.url or sidecar.get("url") or "",
        "path": str(final),
        "title": cand.get("title") or sidecar.get("url") or "",
        "uploader": "",
        "duration": info.get("duration"),
        # Our own footage.
        "official_channel": True,
        "note": args.note,
        "fetched_at": now,
        "last_used": now,
        "candidate_id": own_capture_source.candidate_name(fid),
        own_capture_source.OWN_CAPTURE: own_capture_source.summary(sidecar, source=src),
    }
    if record is not None:
        source_rights.merge_into_entry(entry, record)
    idx["entries"] = [x for x in idx["entries"] if x.get("id") != fid]
    idx["entries"].append(entry)
    evicted, _total = prune(idx, protect=(str(final),))
    save_index(idx)
    for gone in evicted:
        print(f"  evicted from cache (budget {BUDGET_BYTES // 1024 ** 3}GB): {gone}",
              file=sys.stderr)
    print(f"fetched -> {final}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("url", nargs="?")
    p.add_argument("--official", action="store_true",
                   help="the uploader is the official channel")
    p.add_argument("--note", default="")
    p.add_argument("--list", action="store_true")
    p.add_argument("--duration", action="store_true",
                   help="CF-0302: print the length of the video in seconds and "
                        "stop - one metadata request, nothing downloaded and "
                        "nothing registered")
    p.add_argument("--ytdlp", default=None, help="path to yt-dlp; defaults to this agent's own")
    p.add_argument("--max-height", type=int, default=1080)
    p.add_argument("--max-duration", type=float, default=None,
                   help="CF-0333: refuse, inside the download request, a video "
                        "longer than this many seconds - nothing is downloaded "
                        f"and the exit code is {TOO_LONG_EXIT}")
    # CF-0663: internal, ingest_batch.py -> here; no user-facing setting.
    p.add_argument("--rights-json", default=None,
                   help="CF-0663: the source's `rights` record (source_rights.rights_of) "
                        "as JSON, kept on the cache entry; a record whose licence was "
                        f"judged and refused is not fetched (exit {LICENCE_EXIT})")
    # CF-0665: internal, ingest_batch.py -> here; no user-facing setting.
    p.add_argument("--archive-json", default=None,
                   help="CF-0665: an archive candidate's whole record (TH-3, "
                        "`nasa:<id>` / `commons:<pageid>`) as JSON - downloaded from its "
                        "download_url directly, not through yt-dlp")
    p.add_argument("--licences-json", default=None,
                   help="CF-0665: the channel's footage-origin.json `licences` lists, "
                        "for the archive licence read again before the download")
    # CF-0567: internal, ingest_batch.py -> here; no user-facing setting.
    p.add_argument("--own-capture-json", default=None,
                   help="CF-0567: an own capture's candidate record (`own_capture:<id>`, "
                        "with `capture_file`) as JSON - the finished recording and its "
                        "sidecar are copied into the pool, nothing is downloaded")
    args = p.parse_args()

    global YTDLP
    if args.ytdlp:
        YTDLP = args.ytdlp

    record = None
    if args.rights_json:
        try:
            record = json.loads(args.rights_json)
        except ValueError as exc:
            sys.exit(f"--rights-json does not read as JSON: {exc}")
        if not isinstance(record, dict):
            sys.exit("--rights-json is not a JSON object")
        if record.get("judged") and record.get("accepted") is False:
            # CF-0663: defence in depth - nothing is asked of the source.
            print(LICENCE_LINE.format(url=args.url, reason=record.get("reason") or "?"),
                  file=sys.stderr)
            sys.exit(LICENCE_EXIT)

    if args.own_capture_json:
        try:
            cand = json.loads(args.own_capture_json)
        except ValueError as exc:
            sys.exit(f"--own-capture-json does not read as JSON: {exc}")
        if not isinstance(cand, dict):
            sys.exit("--own-capture-json is not a JSON object")
        return fetch_own_capture(args, cand, record=record, runner=ARCHIVE_RUNNER)

    if args.archive_json:
        try:
            cand = json.loads(args.archive_json)
            lists = json.loads(args.licences_json) if args.licences_json else None
        except ValueError as exc:
            sys.exit(f"--archive-json / --licences-json does not read as JSON: {exc}")
        if not isinstance(cand, dict):
            sys.exit("--archive-json is not a JSON object")
        if not args.url:
            args.url = cand.get("source_url") or cand.get("download_url")
        return fetch_archive(args, cand, record=record,
                             licences=lists if isinstance(lists, dict) else None,
                             opener=ARCHIVE_OPENER, runner=ARCHIVE_RUNNER)

    idx = load_index()

    if args.list:
        total = sum(entry_size(e) for e in idx["entries"] if Path(e["path"]).exists())
        for e in idx["entries"]:
            flag = "official" if e["official_channel"] else "THIRD-PARTY"
            indexed = "indexed" if Path(e["path"]).with_suffix(".shots.json").exists() else "-"
            print(f"{e['id']:14s} {flag:12s} {indexed:8s} {e['path']}")
        print(f"\n{len(idx['entries'])} entries, {total / 1024 ** 3:.2f}GB "
              f"of {BUDGET_BYTES // 1024 ** 3}GB budget")
        return

    if not args.url:
        sys.exit("give a url or --list")

    # CF-0302: the same question ingest_batch.py asks before it spends a
    # topic's attempt, available by hand for a candidate list checked by eye.
    if args.duration:
        meta = probe_duration(args.url)
        if meta.seconds is None:
            sys.exit(f"duration unknown for {args.url}: {meta.error}")
        print(f"{meta.seconds:.0f}")
        return

    # CF-0090: orphans from earlier failed or killed fetches go first, on
    # every real fetch, so the cache never accumulates them.
    sweep_partials(log=lambda m: print(m, file=sys.stderr))

    e = cached_entry(idx, args.url)
    if e is not None:
        e["last_used"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if record is not None:
            source_rights.merge_into_entry(e, record)       # CF-0663
        save_index(idx)
        runlog.annotate(video=e["id"], cached=True)
        print(f"cached -> {e['path']}")
        return

    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = temp_dir_for()
    tmp.mkdir(parents=True, exist_ok=True)
    # The template must stay relative: yt-dlp ignores --paths for an
    # absolute -o, and then the intermediates land in the cache again.
    cmd = [
        str(YTDLP), args.url,
        "-f", f"bestvideo[height<={args.max_height}]+bestaudio/best[height<={args.max_height}]",
        "--merge-output-format", "mp4",
        "-P", f"home:{CACHE}", "-P", f"temp:{tmp}",
        "-o", "%(id)s.%(ext)s",
        "--print", "pre_process:%(id)s",
        "--print", "after_move:filepath",
        "--no-playlist", "--no-warnings",
        # pace this download's own requests
        "--sleep-requests", str(SLEEP_REQUESTS_SECONDS),
    ]
    if args.max_duration:
        cmd += max_duration_args(args.max_duration)
    # CF-0107: the download is a `child` event (tool yt-dlp) under this
    # script's event, so the RUN_EVENTS can tell network time from CPU time.
    out = runlog.run_child(cmd, tool="yt-dlp", capture_output=True, text=True)
    lines = [l.strip() for l in out.stdout.splitlines() if l.strip()]
    length = printed_duration(lines)
    lines = [l for l in lines if not l.startswith(DURATION_MARK)]
    vid = lines[0] if lines else ""
    if vid:
        runlog.annotate(video=vid)
    if (args.max_duration and out.returncode == 0 and len(lines) < 2
            and length is not None and length > args.max_duration):
        # CF-0333: the match filter said no. Nothing came down; whatever the
        # temp dir holds is swept like any failed fetch's.
        if vid:
            cleanup_partials(vid, tmp)
        _shutil.rmtree(tmp, ignore_errors=True)
        runlog.annotate(too_long=True, duration_s=length)
        print(TOO_LONG_LINE.format(seconds=int(round(length)),
                                   limit=int(args.max_duration), vid=vid or args.url),
              file=sys.stderr)
        sys.exit(TOO_LONG_EXIT)
    final = Path(lines[-1]) if out.returncode == 0 and len(lines) >= 2 else None
    ok = final is not None and final.is_file() and final.stat().st_size > 0
    if not ok:
        removed = []
        if final is not None and final.exists():
            removed.append((final.name + " (empty)", final.stat().st_size))
            final.unlink()
        removed += cleanup_partials(vid, tmp)
        what = ", ".join(f"{n} ({fmt_size(s)})" for n, s in removed) or "nothing to remove"
        if out.stderr.strip():
            print(out.stderr.rstrip(), file=sys.stderr)
        print(CLEANUP_LINE.format(vid=vid or "?", what=what), file=sys.stderr)
        sys.exit(f"yt-dlp failed for {args.url} - removed {what}; nothing registered")
    _shutil.rmtree(tmp, ignore_errors=True)
    path = str(final)

    meta_cmd = [str(YTDLP), args.url, "--dump-single-json", "--no-warnings",
                "--no-playlist"]
    meta = runlog.run_child(meta_cmd, tool="yt-dlp", capture_output=True, text=True)
    info = json.loads(meta.stdout) if meta.returncode == 0 else {}

    entry = {
        "id": info.get("id", vid),
        "url": args.url,
        "path": path,
        "title": info.get("title", ""),
        "uploader": info.get("uploader", ""),
        "duration": info.get("duration"),
        # Recorded, never inferred: whether this came from the official
        # channel is a compliance input, and guessing it later is impossible.
        "official_channel": bool(args.official),
        "note": args.note,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "last_used": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if record is not None:
        source_rights.merge_into_entry(entry, record)       # CF-0663
    idx["entries"].append(entry)

    evicted, total = prune(idx, protect=(path,))
    save_index(idx)
    for gone in evicted:
        print(f"  evicted from cache (budget {BUDGET_BYTES // 1024 ** 3}GB): {gone}",
              file=sys.stderr)
    print(f"fetched -> {path}")
    if not args.official:
        print("  NOTE: not marked as an official channel - "
              "Compliance Checker will see this", file=sys.stderr)


@runlog.script("footage-indexer", "fetch", name="fetch_footage.py")
def cli():
    """The command-line entry (CF-0107): start/done|failed around main(), the
    video id annotated once yt-dlp (or the cache) has named it. `main()` stays
    bare for the tests that call it in-process."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
