#!/usr/bin/env python3
"""CF-0476: a month that is over leaves `publish/` for one zip on Archive.

The user's decisions of 2026-10-01: `publish/` is cut by the calendar - when a
month is over (Moscow time), every video of it is *moved* to the external disk
Archive (the `Archive` volume; `Archive-TimeMachine` is never touched), as **one
archive per channel and month**, and its day folders leave the repository:

    publish/<channel>/<YYYY-MM-DD>/<slug>.mp4|.md                 (CF-0475)
      -> <volume>/shorts-content-factory-publish/<channel>/<YYYY-MM>.zip
             <YYYY-MM-DD>/<slug>.mp4|.md          (stored, not recompressed:
                                                   an mp4 does not shrink, and a
                                                   stored zip opens with a double
                                                   click on the Mac)
         <volume>/shorts-content-factory-publish/<channel>/<YYYY-MM>.manifest.json
             every member (path, size, sha256, day, slug, YouTube link) and the
             sha256 of the zip itself

The order is the safety:
  1. the zip is written as `<YYYY-MM>.zip.partial` on the volume, flushed,
  2. read back from the device (`F_NOCACHE`, not the page cache the write just
     filled) and every member's sha256 compared with its source - the set of
     names must be exactly the expected one,
  3. only then renamed to `<YYYY-MM>.zip`, the manifest written next to it,
  4. and only then the month leaves `publish/`: `.mp4` deleted, `.md` by
     `git rm` (its history stays in git; plain delete when the root is no git
     checkout), the emptied day folders removed;
  5. the README rows, the `publish_path` of those videos and the `note` of
     their rows in `publish/uploads.json` (CF-0594, written through
     `agents/publisher/upload_records.py`, the journal's only writer) now
     point into the zip: `Archive:shorts-content-factory-publish/example-film/2026-09.zip#
     2026-09-25/you-can-see-everything.mp4` (`publish_layout.archive_ref`) -
     `runlog publish where` answers "в архиве", `acceptance --check` lists it
     as archived, never as a problem;
  6. one commit of exactly those paths (`git rm`s, README, acceptance-log,
     uploads.json),
     made by the script itself - but only when none of those paths had changes
     of someone else's before the run, and never while a batch is open
     (`runlog batch-active`, CF-0457: a commit under a batch reads as a crash).
     Otherwise the edits stay in the tree and a question says so; a commit put
     off by an open batch is retried by every later run (`--commit-pending`
     does only that). `--no-commit` is the manual mode. The root's post-commit
     hook pushes, as for every commit.

A month already archived gets a late file the same way: the new zip carries the
old zip's members and the new ones (a member of one name and other bytes is a
conflict - nothing is touched). A month archived the old way, as folders
(`<channel>/<YYYY-MM>/<day>/...` + `MANIFEST.json`, 2026-10-01), is repacked by
`--repack-legacy` (a dry run without `--apply`): every file checked against
that MANIFEST.json, zipped and verified as above, then the folder is removed
from the volume and what is left of that month in `publish/` leaves it as in
step 4-6. The regular run leaves such a month alone and says so.

After step (a) the same run does the rest of the monthly freeing (CF-0358,
the user's decision of 2026-10-04) - `scripts/monthly_archive.py`: (b) the
footage pool (`pool_release`, published/withdrawn topics plus the 14-day rule),
(c) batches older than 30 days -> one zip per month on Archive, (d) `$TMPDIR` -
each at most once a month; `--publish-only` skips them, `--force` re-runs them.

When: launchd (`scripts/launchd/com.example-film.archive-publish-month.plist`)
on the 1st of every month at 10:00 and whenever a volume is mounted. With no
debt (no day folder of a past month in `publish/`) a run says nothing and
writes nothing. With debt and no Archive mounted (a real mount point, not an
empty `/Volumes/Archive` folder) one question in the journal of questions
(shared/needs_you.py, CF-0652) asks to plug it in - reworded, never repeated,
resolved once the debt is paid - and the next mount of Archive pays it.

    python3 scripts/archive_publish_month.py [--dry-run] [--no-commit]
        [--repack-legacy [--apply]] [--commit-pending] [--root DIR]
        [--volume /Volumes/Archive] [--log FILE] [--needs-you-dir DIR]
        [--today YYYY-MM-DD] [--min-free-gb N] [--json] [--by WHO] [--via WHERE]

The log is `scripts/archive.log`; step (a) writes lines starting with
`publish:`, steps (b)-(d) with `month:`.

CF-0720 (the command center's ask 3 of 2026-10-13): `--json` prints one JSON
document on stdout instead of the lines (they go to stderr, and into the
document's `lines`) - for `--dry-run` the plan, for a real run the same
document with what was done: `dry_run, mode (month | repack), today, volume,
mounted, by, via, debt[], legacy_skipped[], jobs[] ({channel, month, zip,
action create|extend|null, old_members, members, bytes, from_publish[{path,
kind, bytes, op git rm|delete}], day_dirs[], status planned|moved|failed}),
need_bytes, free_bytes, margin_bytes, enough_space, commit {message, by,
via} | null, monthly {lines} | null, lines[], exit_code`. `--by WHO --via
WHERE` (short one-line strings, `_who`) go into the document, a `кто:` line
of the log and the commit message (`Requested-by: <by> via <via>`).
"""
import argparse
import errno
import fcntl
import hashlib
import json
import os
import re
import shutil
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:                                             # pragma: no cover
    ZoneInfo = None

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "shared" / "runlog"))
sys.path.insert(0, str(REPO / "agents" / "publisher"))
import git_read                                                 # noqa: E402  (CF-0717)
import publish_layout as pl                                     # noqa: E402
import upload_records                                           # noqa: E402

TASK = "CF-0476"
DEFAULT_VOLUME = "/Volumes/Archive"
ARCHIVE_DIR = pl.ARCHIVE_DIR
LEGACY_MANIFEST = "MANIFEST.json"               # the folder form of 2026-10-01
ZIP = ".zip"
MANIFEST = ".manifest.json"
PARTIAL = ".partial"
# CF-0652: the reminders are questions of the journal of questions
# (shared/needs_you.py), one live per marker: key `archive:<marker>`.
NEEDS_YOU_SOURCE = "archive-publish-month"
MIN_FREE_GB = 2.0
# Every reminder carries its marker - the key of its question - so the next run
# finds it, rewords it instead of asking a second time, and resolves it once it
# is no longer true.
MARKER = "долг архива publish"
COMMIT_MARKER = "коммит архива publish"
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
YT_RE = re.compile(r"(?:https?://)?(?:www\.)?(?:youtube\.com/shorts/|youtu\.be/)"
                   r"([A-Za-z0-9_-]{6,})")
STRUCK_RE = re.compile(r"~~.*?~~")
F_NOCACHE = getattr(fcntl, "F_NOCACHE", 48 if sys.platform == "darwin" else None)
JUNK = (".DS_Store",)                           # Finder litter, never a member
ZIP_OVERHEAD = 1 << 20                          # headers and directory, generously
README_REL = "publish/README.md"
LOG_REL = "publish/acceptance-log.json"
UPLOADS_REL = "publish/uploads.json"
OWN_RELS = (README_REL, LOG_REL, UPLOADS_REL)


class ArchiveError(Exception):
    pass


# --------------------------------------------------------------------------
# small things
# --------------------------------------------------------------------------

def msk_today():
    if ZoneInfo is None:                                        # pragma: no cover
        raise SystemExit("zoneinfo is unavailable (Python < 3.9)")
    return datetime.now(ZoneInfo("Europe/Moscow")).strftime("%Y-%m-%d")


def is_mounted(volume):
    """A real mount point - not the empty folder macOS can leave behind in
    /Volumes when a disk goes away, which would happily take a copy."""
    v = Path(volume)
    return v.is_dir() and os.path.ismount(str(v))


def _nocache(fd):
    if F_NOCACHE is not None:
        try:
            fcntl.fcntl(fd, F_NOCACHE, 1)
        except OSError:
            pass


def _hash_stream(f):
    h = hashlib.sha256()
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
    return h.hexdigest()


def sha256(path, no_cache=False):
    """sha256 of a file. `no_cache` asks macOS to read it from the device, not
    from the page cache a write just filled."""
    fd = os.open(str(path), os.O_RDONLY)
    try:
        if no_cache:
            _nocache(fd)
        with os.fdopen(fd, "rb", closefd=False) as f:
            return _hash_stream(f)
    finally:
        os.close(fd)


def mb(n):
    return f"{n / (1 << 20):.1f} МБ" if n >= (1 << 20) else f"{n / 1024:.1f} КБ"


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Log:
    """`scripts/archive.log`, the same file and line shape as
    the retired archive_old_batches.sh; every line is echoed to stdout too. A dry run
    writes nothing; `say` is stdout only (a run with nothing to do stays out
    of the log - it runs on every mount)."""

    def __init__(self, path, write=True, out=None, sink=None):
        self.path = Path(path)
        self.write = write
        self.out = out              # CF-0720: --json prints the lines to stderr
        self.sink = sink            # CF-0720: and keeps them for the document

    def _line(self, msg):
        return f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} publish: {msg}"

    def _show(self, line):
        print(line, flush=True, file=self.out or sys.stdout)
        if self.sink is not None:
            self.sink.append(line)

    def say(self, msg):
        self._show(self._line(msg))

    def __call__(self, msg):
        line = self._line(msg)
        self._show(line)
        if self.write:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")


# --------------------------------------------------------------------------
# the YouTube link
# --------------------------------------------------------------------------

def _last_link(text):
    found = YT_RE.findall(STRUCK_RE.sub("", text or ""))
    return f"https://youtube.com/shorts/{found[-1]}" if found else None


def youtube_link(slug, channel, day, md, readme_lines, volume):
    """The live link of a video: its note first, then its README row (under
    its day folder, or already pointing into the archive); a link struck
    through (`~~...~~`, a deleted upload) is not it."""
    if md:
        try:
            link = _last_link(Path(md).read_text(encoding="utf-8"))
        except OSError:
            link = None
        if link:
            return link
    for at in (pl.where(channel, day), pl.archive_where(volume, channel, day)):
        for i in pl.readme_rows(readme_lines, slug, at=at):
            link = _last_link(readme_lines[i])
            if link:
                return link
    return None


# --------------------------------------------------------------------------
# members: what goes into a month's zip, from where
# --------------------------------------------------------------------------
#
# A member is a dict: name (its path inside the zip, `<day>/<file>`), day,
# slug, file, kind, size, sha256, youtube, archived_at, origin ("local" - a
# file in publish/, "zip" - a member of the month's zip already on the volume,
# "legacy" - a file of the folder form), src (the file, for local/legacy) and
# mtime.

def _member(name, size, digest, origin, src=None, mtime=None, youtube=None,
            archived_at=None, slug=None):
    day, _, file = name.partition("/")
    stem, suffix = os.path.splitext(file)
    return {"name": name, "day": day, "file": file, "slug": slug or stem,
            "kind": suffix.lstrip(".") or "file", "size": size, "sha256": digest,
            "origin": origin, "src": src, "mtime": mtime, "youtube": youtube,
            "archived_at": archived_at}


def past_days(publish, today):
    """`{(channel, month): [day folder]}` - every day folder of a month before
    `today`'s (the current and future months and `_queue/` are never read)."""
    out = {}
    for channel in pl.channels(publish):
        for d in sorted((Path(publish) / channel).iterdir()):
            if not d.is_dir() or not pl.DAY_RE.match(d.name):
                continue
            try:
                pl.release_day(d.name)
            except pl.LayoutError:
                continue
            if d.name[:7] >= today[:7] or d.name >= today:
                continue
            out.setdefault((channel, d.name[:7]), []).append(d)
    return out


def local_members(publish, channel, month, readme_lines, volume, digest=True):
    """The videos of one channel's month still in `publish/`; `digest=False`
    leaves sha256 for later (`hash_members`) - a plan should not read 200 МБ
    to say the volume is not plugged in."""
    out = []
    for e in pl.entries(publish, channel):
        if e["channel"] != channel or e["bucket"] in (pl.FLAT, *pl.WAITING) \
                or e["bucket"][:7] != month:
            continue
        link = youtube_link(e["slug"], channel, e["bucket"], e["md"], readme_lines, volume)
        for kind in ("mp4", "md"):
            src = e[kind]
            if src:
                st = src.stat()
                out.append(_member(f"{e['bucket']}/{src.name}", st.st_size,
                                   sha256(src) if digest else None,
                                   "local", src=src, mtime=st.st_mtime, youtube=link,
                                   slug=e["slug"]))
    return out


def hash_members(members):
    for m in members:
        if m["sha256"] is None:
            m["sha256"] = sha256(m["src"])
    return members


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def zip_members(zpath, manifest):
    """The members of a month's zip already on the volume, their hashes read
    from the zip itself (a manifest can be stale, the bytes cannot)."""
    rows = {r.get("path"): r for r in (manifest or {}).get("files", []) if isinstance(r, dict)}
    out = []
    with open_zip(zpath) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            with zf.open(info) as f:
                digest = _hash_stream(f)
            r = rows.get(info.filename) or {}
            out.append(_member(info.filename, info.file_size, digest, "zip",
                               mtime=time.mktime(info.date_time + (0, 0, -1)),
                               youtube=r.get("youtube"), archived_at=r.get("archived_at"),
                               slug=r.get("slug")))
    return out


def legacy_members(mdir):
    """The files of a month archived as folders, each checked against that
    folder's MANIFEST.json: same set of files, same size, same sha256 (read
    from the device). `(members, problems)`."""
    mdir = Path(mdir)
    manifest = load_json(mdir / LEGACY_MANIFEST)
    problems = []
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        return [], [f"{mdir}/{LEGACY_MANIFEST}: нет или не читается"]
    rows = {}
    for r in manifest["files"]:
        if isinstance(r, dict) and r.get("path"):
            rows[r["path"]] = r
    found = {}
    for p in sorted(mdir.rglob("*")):
        if not p.is_file() or p.name in JUNK or p.name.startswith(".") \
                or p.parent == mdir:
            continue
        found[str(p.relative_to(mdir))] = p
    for name in sorted(set(rows) - set(found)):
        problems.append(f"{name}: есть в {LEGACY_MANIFEST}, нет на томе")
    for name in sorted(set(found) - set(rows)):
        problems.append(f"{name}: на томе, но нет в {LEGACY_MANIFEST}")
    out = []
    for name in sorted(set(found) & set(rows)):
        p, r = found[name], rows[name]
        st = p.stat()
        digest = sha256(p, no_cache=True)
        if st.st_size != r.get("size") or digest != r.get("sha256"):
            problems.append(f"{name}: размер/sha256 не совпадает с {LEGACY_MANIFEST}")
            continue
        out.append(_member(name, st.st_size, digest, "legacy", src=p, mtime=st.st_mtime,
                           youtube=r.get("youtube"), archived_at=r.get("archived_at"),
                           slug=r.get("slug")))
    return out, problems


def merge(*sources):
    """One member per name; later sources win the metadata, the earliest
    `archived_at` and any known link are kept. A name with two different
    sha256 is a conflict: `ArchiveError`, nothing is touched."""
    out = {}
    for src in sources:
        for m in src:
            old = out.get(m["name"])
            if old is None:
                out[m["name"]] = dict(m)
                continue
            if old["sha256"] != m["sha256"]:
                raise ArchiveError(f"{m['name']}: в архиве ({old['origin']}) и здесь "
                                   f"({m['origin']}) разные файлы с одним именем — "
                                   f"ничего не трогаю, разберите вручную")
            new = dict(m)
            new["youtube"] = m["youtube"] or old["youtube"]
            new["archived_at"] = old["archived_at"] or m["archived_at"]
            out[m["name"]] = new
    return [out[k] for k in sorted(out)]


# --------------------------------------------------------------------------
# the zip: build, read back, verify
# --------------------------------------------------------------------------

class open_zip:
    """A zip on the volume read from the device (`F_NOCACHE`)."""

    def __init__(self, path):
        self.fd = os.open(str(path), os.O_RDONLY)
        _nocache(self.fd)
        self.f = os.fdopen(self.fd, "rb")
        self.zf = zipfile.ZipFile(self.f)

    def __enter__(self):
        return self.zf

    def __exit__(self, *exc):
        self.zf.close()
        self.f.close()


def _date_time(mtime):
    t = time.localtime(mtime or time.time())
    return max(t[:6], (1980, 1, 1, 0, 0, 0))


def build_zip(zpath, members):
    """Write every member, stored, into `<zpath>.partial`, flushed to the
    device. A member of origin `zip` is streamed out of the old `zpath`."""
    tmp = Path(str(zpath) + PARTIAL)
    old = open_zip(zpath) if any(m["origin"] == "zip" for m in members) else None
    try:
        with open(tmp, "wb") as raw:
            with zipfile.ZipFile(raw, "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
                for m in members:
                    zi = zipfile.ZipInfo(m["name"], date_time=_date_time(m["mtime"]))
                    zi.compress_type = zipfile.ZIP_STORED
                    zi.external_attr = 0o100644 << 16
                    zi.file_size = m["size"]
                    src = old.zf.open(m["name"]) if m["origin"] == "zip" else open(m["src"], "rb")
                    with src as fi, zf.open(zi, "w", force_zip64=m["size"] > 0x7FFF0000) as fo:
                        shutil.copyfileobj(fi, fo, 1 << 20)
            raw.flush()
            os.fsync(raw.fileno())
    finally:
        if old:
            old.__exit__()
    return tmp


def verify_zip(zpath, members):
    """`(problems, zip_size, zip_sha256)` - the zip read back from the device:
    exactly the expected names, each member's size and sha256 those of its
    source."""
    want = {m["name"]: m for m in members}
    problems = []
    try:
        with open_zip(zpath) as zf:
            names = [i.filename for i in zf.infolist() if not i.is_dir()]
            for n in sorted(set(names) - set(want)):
                problems.append(f"{n}: в zip лишний член")
            for n in sorted(set(want) - set(names)):
                problems.append(f"{n}: в zip нет члена")
            for info in zf.infolist():
                m = want.get(info.filename)
                if m is None:
                    continue
                try:
                    with zf.open(info) as f:
                        digest = _hash_stream(f)
                except (zipfile.BadZipFile, OSError) as e:
                    problems.append(f"{info.filename}: член не читается ({e})")
                    continue
                if info.file_size != m["size"] or digest != m["sha256"]:
                    problems.append(f"{info.filename}: размер/sha256 в zip не совпадает "
                                    f"с исходником")
    except (OSError, zipfile.BadZipFile) as e:
        problems.append(f"{zpath}: zip не читается ({e})")
        return problems, None, None
    return problems, Path(zpath).stat().st_size, sha256(zpath, no_cache=True)


def write_manifest(path, channel, month, members, zip_size, zip_sha):
    stamp = now_iso()
    data = {"channel": channel, "month": month, "task": TASK,
            "zip": f"{month}{ZIP}", "zip_size": zip_size, "zip_sha256": zip_sha,
            "updated_at": stamp,
            "files": [{"path": m["name"], "day": m["day"], "slug": m["slug"],
                       "file": m["file"], "kind": m["kind"], "size": m["size"],
                       "sha256": m["sha256"], "youtube": m["youtube"],
                       "archived_at": m["archived_at"] or stamp} for m in members]}
    tmp = Path(str(path) + PARTIAL)
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))
    return data


def pack_month(adir, channel, month, members, log):
    """Build, read back and verify `<adir>/<month>.zip`, then put it in place
    and write its manifest. Returns True only when all of that held."""
    zpath = adir / f"{month}{ZIP}"
    adir.mkdir(parents=True, exist_ok=True)
    try:
        tmp = build_zip(zpath, members)
    except (OSError, zipfile.BadZipFile) as e:
        log(f"{channel} {month}: zip не собран — {e}; ничего не удаляю")
        Path(str(zpath) + PARTIAL).unlink(missing_ok=True)
        return False
    problems, size, digest = verify_zip(tmp, members)
    if problems:
        for p in problems:
            log(f"{channel} {month}: сверка не сошлась — {p}")
        log(f"{channel} {month}: zip не принят, ничего не удаляю")
        tmp.unlink(missing_ok=True)
        return False
    os.replace(str(tmp), str(zpath))
    write_manifest(adir / f"{month}{MANIFEST}", channel, month, members, size, digest)
    # The last word before anything is deleted: the zip is in place with the
    # size it was verified at.
    if not zpath.is_file() or zpath.stat().st_size != size:
        log(f"{channel} {month}: {zpath} после переименования не подтвердился, "
            f"ничего не удаляю")
        return False
    log(f"{channel} {month}: {zpath} — членов {len(members)}, {mb(size)}, sha256 "
        f"{digest[:12]}…, сверка с исходниками сошлась; манифест {month}{MANIFEST}")
    return True


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------

def _git(root, *args, timeout=60):
    # CF-0717: reads with optional locks off, `rm`/`commit` as before
    return git_read.run(["-C", str(root), *args], capture_output=True, text=True,
                        timeout=timeout)


def git_root(root):
    """The root itself when it is the top of a git checkout - never a repo
    the root merely sits inside (a temp folder under some other checkout)."""
    top = pl._git_root(root)
    return top if top is not None and top.resolve() == Path(root).resolve() else None


def dirty(root, rels):
    """The paths among `rels` with changes in the index or the tree."""
    if not rels:
        return []
    cp = _git(root, "status", "--porcelain=v1", "--untracked-files=all", "--", *rels)
    return [ln[3:] for ln in cp.stdout.splitlines() if ln.strip()]


def tracked(root, rel):
    return _git(root, "ls-files", "--error-unmatch", "--", rel).returncode == 0


def batch_open(root):
    """CF-0457: a commit while a batch is open reads as a crash. Any doubt
    (the check itself fails) counts as open: the commit waits."""
    try:
        import runlog
        return any(fresh for _, _, fresh in runlog.open_batches(root))
    except Exception:                                           # noqa: BLE001
        return True


def commit(root, rels, message, log):
    """One commit of exactly `rels` (their tree state), other staged changes
    left staged. True when the paths are clean afterwards."""
    changed = dirty(root, rels)
    if not changed:
        return True
    cp = _git(root, "commit", "-q", "-m", message, "--only", "--", *changed, timeout=300)
    if cp.returncode != 0:
        log(f"git commit не удался: {(cp.stderr or cp.stdout).strip()}")
        return False
    sha = _git(root, "rev-parse", "--short", "HEAD").stdout.strip()
    log(f"коммит {sha}: {message.splitlines()[0]}")
    return not dirty(root, rels)


# --------------------------------------------------------------------------
# NEEDS-YOU
# --------------------------------------------------------------------------

def _journal():
    shared = str(REPO / "shared")
    if shared not in sys.path:
        sys.path.append(shared)
    import needs_you                                            # noqa: PLC0415
    return needs_you


def needs_you_dir(explicit, root):
    """--needs-you-dir, else the journal's default for this root
    ($NEEDS_YOU_DIR, else <root>/needs-you)."""
    if explicit:
        return Path(explicit).expanduser()
    mine = Path(root).resolve() == REPO.resolve()
    return _journal().journal_dir(None if mine else root)


def reminder_key(marker=MARKER):
    return f"archive:{marker}"


def remind(directory, today, text, log, marker=MARKER):
    """One question for the operator per marker, reworded in place - never a
    second one; a new one goes to Telegram once (CF-0652). True when the
    journal changed. `today` is kept for the callers - the question carries
    the time it was asked."""
    text = f"{text} ({TASK}, `scripts/archive_publish_month.py`)"
    try:
        j = _journal()
        before = next((q for q in j.live(directory=directory)
                       if q["key"] == reminder_key(marker)), None)
        q, created = j.add(NEEDS_YOU_SOURCE, reminder_key(marker), text, by=NEEDS_YOU_SOURCE,
                           directory=directory)
    except Exception as e:                                      # noqa: BLE001
        log(f"NEEDS-YOU: не записано ({e.__class__.__name__}: {e}), напоминание: {text}")
        return False
    if not created and before is not None and before["text"] == q["text"]:
        return False                        # already said
    log(f"NEEDS-YOU {q['id']}: {text}")
    return True


def clear_reminder(directory, log, marker=MARKER):
    try:
        done = _journal().resolve(key=reminder_key(marker), by=NEEDS_YOU_SOURCE,
                                  note="больше не нужно", directory=directory)
    except Exception as e:                                      # noqa: BLE001
        log(f"NEEDS-YOU: не снято ({e.__class__.__name__}: {e})")
        return False
    if not done:
        return False
    log(f"NEEDS-YOU: «{marker}» больше не нужно, вопрос {', '.join(q['id'] for q in done)} решён")
    return True


def months_text(keys):
    return ", ".join(f"{c} {m}" for c, m in sorted(keys))


# --------------------------------------------------------------------------
# the move out of publish/
# --------------------------------------------------------------------------

def remove_local(root, members, day_dirs, git_top, log):
    """Delete the local members (mp4 from disk, a tracked note by `git rm`),
    then the emptied day folders. Returns the repo-relative paths of the
    notes removed from git."""
    gone = []
    for m in members:
        if m["origin"] != "local" or not m["src"].exists():
            continue
        rel = str(m["src"].resolve().relative_to(Path(root).resolve()))
        if m["kind"] == "md" and git_top is not None and tracked(root, rel):
            cp = _git(root, "rm", "-q", "-f", "--", rel)
            if cp.returncode != 0:
                raise ArchiveError(f"git rm {rel}: {cp.stderr.strip()}")
            gone.append(rel)
        else:
            m["src"].unlink()
    for d in day_dirs:
        for junk in JUNK:
            (d / junk).unlink(missing_ok=True)
        try:
            d.rmdir()
        except FileNotFoundError:
            pass
        except OSError:
            left = ", ".join(sorted(p.name for p in d.iterdir()))
            log(f"{d}: остались посторонние файлы ({left}) — папка не удалена")
    return gone


def repoint(publish, channel, volume, pairs):
    """The README rows, the `publish_path` and the upload journal's `note` of
    these `(day, slug)` now point into the month's zip. Returns `(readme rows,
    log rows, journal rows)` changed."""
    n_readme = n_log = 0
    readme = Path(publish) / "README.md"
    if readme.is_file():
        text = readme.read_text(encoding="utf-8")
        new = text
        for day, slug in pairs:
            new, n = pl.repoint_readme(new, slug, pl.where(channel, day),
                                       pl.archive_where(volume, channel, day))
            n_readme += n
        if new != text:
            readme.write_text(new, encoding="utf-8")
    lp = Path(publish) / "acceptance-log.json"
    if lp.is_file():
        acc = pl._acceptance()
        doc = acc.read_log(lp)
        rows = acc.entries(log=doc)
        for day, slug in pairs:
            old = pl.rel(channel, day, slug)
            for r in rows:
                if r.get("slug") == slug and r.get("publish_path") == old:
                    r["publish_path"] = pl.archive_ref(volume, channel, day, slug)
                    n_log += 1
        if n_log:
            acc.write_log(rows, path=lp, note=doc.get("note"))
    # CF-0594: the note of an uploaded video, through the journal's own writer.
    n_up = upload_records.repoint_notes(
        {pl.rel(channel, day, slug, ".md"): pl.archive_ref(volume, channel, day, slug, ".md")
         for day, slug in pairs}, path=Path(publish) / "uploads.json")
    return n_readme, n_log, n_up


def pending_path(log):
    return Path(str(log.path) + ".publish.pending.json")


def _digest_of(root, rel):
    p = Path(root) / rel
    return sha256(p) if p.is_file() else None


def settle_commit(a, root, git_top, rels, foreign, message, today, log):
    """Commit the run's own edits - or say why not. `rels` are the paths the
    run changed (repo-relative), `foreign` those of them that had someone
    else's changes before it started."""
    if git_top is None or not rels:
        return 0
    _report(a)["commit"] = {"message": message.splitlines()[0], "by": getattr(a, "by", None),
                            "via": getattr(a, "via", None)}
    if a.no_commit:
        log("коммит не делаю (--no-commit); вручную: git commit -m '" + message.splitlines()[0]
            + "' -- " + " ".join(rels))
        return 0
    if foreign:
        log(f"коммит не делаю: в этих путях были чужие изменения до запуска "
            f"({', '.join(foreign)}) — правки архива в дереве, закоммитьте вручную")
        remind(a.needs_you, today, f"{COMMIT_MARKER}: правки в дереве не закоммичены — в "
               f"путях были чужие изменения ({', '.join(foreign)}); закоммитьте вручную",
               log, marker=COMMIT_MARKER)
        return 0
    if batch_open(root):
        pend = {"task": TASK, "created": now_iso(), "message": message, "paths": rels,
                "digests": {r: _digest_of(root, r) for r in rels}}
        p = pending_path(log)
        p.write_text(json.dumps(pend, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        log(f"батч открыт — коммит отложен ({p.name}); его сделает следующий запуск "
            f"или --commit-pending")
        remind(a.needs_you, today, f"{COMMIT_MARKER} отложен: батч был открыт — после батча "
               f"`python3 scripts/archive_publish_month.py --commit-pending`", log,
               marker=COMMIT_MARKER)
        return 0
    if commit(root, rels, message, log):
        clear_reminder(a.needs_you, log, marker=COMMIT_MARKER)
        return 0
    remind(a.needs_you, today, f"{COMMIT_MARKER} не удался — см. scripts/archive.log",
           log, marker=COMMIT_MARKER)
    return 1


def commit_pending(a, root, today, log):
    """The commit an open batch put off. Made only when the batch is over and
    every path still holds exactly what the archive run left there."""
    p = pending_path(log)
    pend = load_json(p) if p.is_file() else None
    if not pend:
        return 0
    if git_root(root) is None:
        p.unlink(missing_ok=True)
        return 0
    rels = pend.get("paths") or []
    if not dirty(root, rels):
        p.unlink(missing_ok=True)
        clear_reminder(a.needs_you, log, marker=COMMIT_MARKER)
        log("отложенный коммит архива уже сделан кем-то — снимаю")
        return 0
    if batch_open(root):
        log.say("отложенный коммит архива ждёт: батч открыт")
        return 0
    changed = [r for r, d in (pend.get("digests") or {}).items() if _digest_of(root, r) != d]
    if changed:
        p.unlink(missing_ok=True)
        log(f"отложенный коммит архива не делаю: после архива менялись {', '.join(changed)}")
        remind(a.needs_you, today, f"{COMMIT_MARKER}: правки в дереве не закоммичены — "
               f"после архива менялись {', '.join(changed)}; закоммитьте вручную", log,
               marker=COMMIT_MARKER)
        return 0
    if commit(root, rels, pend.get("message") or f"{TASK}: archive", log):
        p.unlink(missing_ok=True)
        clear_reminder(a.needs_you, log, marker=COMMIT_MARKER)
        return 0
    return 1


def move_out(a, root, publish, adir, channel, month, members, day_dirs, volume, log):
    """After a verified zip: the month leaves publish/ and its rows point into
    the zip. Returns the repo-relative paths changed in git."""
    git_top = git_root(root)
    gone = remove_local(root, members, day_dirs, git_top, log)
    pairs = sorted({(m["day"], m["slug"]) for m in members})
    n_readme, n_log, n_up = repoint(publish, channel, volume, pairs)
    mp4 = sum(1 for m in members if m["origin"] == "local" and m["kind"] == "mp4")
    log(f"{channel} {month}: из publish/ ушли mp4 {mp4}, заметок {len(gone)} (git rm), "
        f"папок дней {len(day_dirs)}; README строк → архив {n_readme}, "
        f"acceptance-log строк → архив {n_log}, uploads.json note → архив {n_up}")
    return gone


def message_for(done, volume, what, by=None, via=None):
    head = "; ".join(f"{c} {m} -> {volume}:{ARCHIVE_DIR}/{c}/{m}{ZIP} ({n} files)"
                     for c, m, n in done)
    who = ""
    if by is not None or via is not None:
        who = f"\n\nRequested-by: {by or '-'} via {via or '-'}"
    return (f"{TASK}: {what}: {head}\n\n"
            f"Made by scripts/archive_publish_month.py: the zip was read back from the "
            f"volume and every member's sha256 matched its source before anything was "
            f"removed. Day folders leave publish/ (notes git rm'd, mp4 deleted); README rows, "
            f"acceptance-log publish_path and uploads.json note now point into the zip.{who}")


# --------------------------------------------------------------------------
# CF-0720: the run as a document (--json)
# --------------------------------------------------------------------------

WHO_MAX = 40


def _who(value, what):
    """`by` / `via` - None (not given) or a short non-empty single-line
    string (the shape of notify._who, CF-0700); else ValueError."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what}={value!r}: a short non-empty string (e.g. by='user', "
                         f"via='center') or not given at all")
    value = value.strip()
    if len(value) > WHO_MAX or any(c in value for c in "\r\n\t"):
        raise ValueError(f"{what}={value!r}: at most {WHO_MAX} characters on one line")
    return value


def new_report(dry, mode, today, volume, by=None, via=None):
    return {"dry_run": bool(dry), "mode": mode, "today": today, "volume": str(volume),
            "mounted": None, "by": by, "via": via, "debt": [], "legacy_skipped": [],
            "jobs": [], "need_bytes": None, "free_bytes": None, "margin_bytes": None,
            "enough_space": None, "commit": None, "monthly": None, "lines": [],
            "exit_code": None}


def _report(a):
    """The run's document, or a throw-away one for a caller without it."""
    rep = getattr(a, "report", None)
    return rep if isinstance(rep, dict) else new_report(getattr(a, "dry_run", False), "month",
                                                        None, getattr(a, "volume", ""))


def _rel(root, path):
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return str(path)


def job_doc(root, channel, month, j, zpath, mounted):
    """One job of the document: what goes into the zip and what leaves publish/."""
    old = j.get("old") or []
    members = j.get("members") or []
    return {"channel": channel, "month": month, "zip": str(zpath),
            "action": (("extend" if old else "create") if mounted else None),
            "old_members": len(old), "members": len(members),
            "bytes": sum(m["size"] for m in members) if members else None,
            "from_publish": [{"path": _rel(root, m["src"]), "kind": m["kind"],
                              "bytes": m["size"], "op": "git rm" if m["kind"] == "md" else "delete"}
                             for m in j["local"]],
            "day_dirs": [_rel(root, d) for d in j["days"]],
            "status": "planned"}


# --------------------------------------------------------------------------
# the two runs
# --------------------------------------------------------------------------

def run_month(a, root, publish, archive_root, volume, today, log):
    readme = publish / "README.md"
    readme_lines = readme.read_text(encoding="utf-8").splitlines() if readme.exists() else []
    owed = {}
    for (channel, month), days in sorted(past_days(publish, today).items()):
        mine = local_members(publish, channel, month, readme_lines, volume, digest=False)
        if mine:
            owed[(channel, month)] = {"days": days, "local": mine}
        elif not a.dry_run:
            remove_local(root, [], days, None, log)    # empty day folders: nothing to keep
    report = _report(a)
    report["debt"] = [{"channel": c, "month": m, "days": [d.name for d in p["days"]],
                       "files": len(p["local"])} for (c, m), p in sorted(owed.items())]
    if not owed:
        log.say(f"долга архива нет (сегодня {today}, архивируются месяцы до {today[:7]})")
        if not a.dry_run:
            clear_reminder(a.needs_you, log)
        return 0
    mounted = (a.skip_mount_check and Path(a.volume).is_dir()) or is_mounted(a.volume)
    report["mounted"] = bool(mounted)
    if not mounted:
        report["jobs"] = [job_doc(root, c, m, p, archive_root / c / f"{m}{ZIP}", False)
                          for (c, m), p in sorted(owed.items())]
        msg = (f"{a.volume} не смонтирован (не точка монтирования) — ничего не трогаю; "
               f"долг: {months_text(owed)}")
        if a.dry_run:
            log(msg)
            print_month_plan(owed, archive_root, log, mounted=False)
        elif remind(a.needs_you, today,
                    f"подключите Archive: {MARKER} {months_text(owed)}", log):
            log(msg)
        else:
            log.say(msg)
        return 0

    legacy = sorted(k for k in owed if (archive_root / k[0] / k[1]).is_dir())
    report["legacy_skipped"] = [{"channel": c, "month": m, "folder": str(archive_root / c / m)}
                                for c, m in legacy]
    for k in legacy:
        log(f"{k[0]} {k[1]}: на томе месяц в старой форме (папка {archive_root / k[0] / k[1]}) "
            f"— сначала `--repack-legacy --apply`, этот месяц пропускаю")
        owed.pop(k)
    if legacy and not a.dry_run:
        remind(a.needs_you, today, f"{MARKER} {months_text(legacy)}: на Archive старая форма — "
               f"`python3 scripts/archive_publish_month.py --repack-legacy --apply`", log)
    if not owed:
        return 0

    jobs = {}
    try:
        for (channel, month), p in sorted(owed.items()):
            adir = archive_root / channel
            zpath = adir / f"{month}{ZIP}"
            old = zip_members(zpath, load_json(adir / f"{month}{MANIFEST}")) \
                if zpath.is_file() else []
            jobs[(channel, month)] = dict(p, adir=adir, old=old,
                                          members=merge(old, hash_members(p["local"])))
    except (ArchiveError, OSError, zipfile.BadZipFile) as e:
        log(f"план не собран: {e}")
        if not a.dry_run:
            remind(a.needs_you, today, f"{MARKER}: {e}", log)
        return 1

    need = sum(m["size"] for j in jobs.values() for m in j["members"])
    free = shutil.disk_usage(a.volume).free
    margin = int(a.min_free_gb * (1 << 30)) + ZIP_OVERHEAD
    report["jobs"] = [job_doc(root, c, m, j, j["adir"] / f"{m}{ZIP}", True)
                      for (c, m), j in sorted(jobs.items())]
    report.update(need_bytes=need, free_bytes=free, margin_bytes=margin,
                  enough_space=need + margin <= free)
    if a.dry_run:
        print_month_plan(jobs, archive_root, log, mounted=True)
        log(f"сухой прогон: zip займут {mb(need)}, свободно {mb(free)} — ничего не изменено")
        return 0
    if need + margin > free:
        log(f"мало места на {a.volume}: нужно {mb(need)} + запас {mb(margin)}, "
            f"свободно {mb(free)} — ничего не трогаю")
        remind(a.needs_you, today, f"мало места на Archive: {MARKER} {months_text(jobs)}",
               log)
        return 1

    failed, code = archive_jobs(a, root, publish, jobs, volume, today, log,
                                "past month moved to the archive")
    if failed:
        remind(a.needs_you, today, f"сверка архива не сошлась ({MARKER} "
               f"{months_text(jobs)}), см. scripts/archive.log", log)
        return 1
    if not legacy:
        clear_reminder(a.needs_you, log)
    return code


def archive_jobs(a, root, publish, jobs, volume, today, log, what):
    """Pack, verify and move out every job, then one commit. `(failed, code)`.
    A job with `mdir` (the folder form) has that folder removed from the
    volume once its zip is verified."""
    git_top = git_root(root)
    candidates = list(OWN_RELS) + [
        str(m["src"].resolve().relative_to(root)) for j in jobs.values()
        for m in j["local"] if m["kind"] == "md"]
    foreign = dirty(root, candidates) if git_top else []
    failed, done, changed = 0, [], set()
    docs = {(d["channel"], d["month"]): d for d in _report(a)["jobs"]}
    for (channel, month), j in sorted(jobs.items()):
        doc = docs.get((channel, month)) or {}
        if not pack_month(j["adir"], channel, month, j["members"], log):
            doc["status"] = "failed"
            failed += 1
            continue
        try:
            if j.get("mdir"):
                shutil.rmtree(j["mdir"])
                log(f"{channel} {month}: папка старой формы {j['mdir']} удалена с тома")
            gone = move_out(a, root, publish, j["adir"], channel, month, j["local"],
                            j["days"], volume, log)
        except (ArchiveError, OSError) as e:
            log(f"{channel} {month}: перенос прерван — {e}")
            doc["status"] = "failed"
            failed += 1
            continue
        doc["status"] = "moved"
        changed.update(gone)
        done.append((channel, month, len(j["members"])))
    if not done:
        return failed, 0
    if git_top:
        changed.update(r for r in OWN_RELS if dirty(root, [r]))
    code = settle_commit(a, root, git_top, sorted(changed), sorted(set(foreign)),
                         message_for(done, volume, what, getattr(a, "by", None),
                                     getattr(a, "via", None)), today, log)
    return failed, code


def print_month_plan(jobs, archive_root, log, mounted):
    for (channel, month), j in sorted(jobs.items()):
        local = j["local"]
        zpath = archive_root / channel / f"{month}{ZIP}"
        old = j.get("old") or []
        mp4 = [m for m in local if m["kind"] == "mp4"]
        md = [m for m in local if m["kind"] == "md"]
        where = (f"дополню {zpath} (в нём {len(old)})" if old else f"соберу {zpath}") \
            if mounted else f"{zpath} (том не подключён)"
        log(f"план {channel} {month}: {where}; из publish/ — mp4 {len(mp4)} удалить, "
            f"заметок {len(md)} git rm, папок дней {len(j['days'])} убрать")
        for m in local:
            log(f"  {m['name']} ({m['kind']}, {mb(m['size'])})")


def run_repack(a, root, publish, archive_root, volume, today, log):
    """The folder form of 2026-10-01 -> one zip per month (see the module doc).
    A dry run without `--apply`; even the dry run checks every file against
    the folder's MANIFEST.json, so it says whether `--apply` would pass."""
    mounted = (a.skip_mount_check and Path(a.volume).is_dir()) or is_mounted(a.volume)
    if not mounted:
        log(f"{a.volume} не смонтирован — перепаковывать нечего")
        return 1
    found = []
    if archive_root.is_dir():
        for cdir in sorted(archive_root.iterdir()):
            if not cdir.is_dir() or not pl.CHANNEL_RE.match(cdir.name):
                continue
            for mdir in sorted(cdir.iterdir()):
                if mdir.is_dir() and MONTH_RE.match(mdir.name):
                    found.append((cdir.name, mdir.name, mdir))
    if not found:
        log.say(f"на {archive_root} нет месяцев в старой форме (папкой) — перепаковывать нечего")
        return 0
    readme = publish / "README.md"
    readme_lines = readme.read_text(encoding="utf-8").splitlines() if readme.exists() else []
    days_all = past_days(publish, today)
    jobs, bad = {}, 0
    for channel, month, mdir in found:
        legacy, problems = legacy_members(mdir)
        if problems:
            for p in problems:
                log(f"{channel} {month}: {p}")
            log(f"{channel} {month}: папка не сходится со своим {LEGACY_MANIFEST} — не трогаю")
            bad += 1
            continue
        local = local_members(publish, channel, month, readme_lines, volume) \
            if month < today[:7] else []
        adir = archive_root / channel
        zpath = adir / f"{month}{ZIP}"
        try:
            old = zip_members(zpath, load_json(adir / f"{month}{MANIFEST}")) \
                if zpath.is_file() else []
            members = merge(old, legacy, local)
        except (ArchiveError, OSError, zipfile.BadZipFile) as e:
            log(f"{channel} {month}: {e}")
            bad += 1
            continue
        jobs[(channel, month)] = {"mdir": mdir, "adir": adir, "local": local, "old": old,
                                  "legacy_n": len(legacy),
                                  "members": members,
                                  "days": days_all.get((channel, month), [])}
    report = _report(a)
    report["mounted"] = True
    report["jobs"] = [job_doc(root, c, m, j, j["adir"] / f"{m}{ZIP}", True)
                      for (c, m), j in sorted(jobs.items())]
    for (channel, month), j in sorted(jobs.items()):
        mdir, zpath = j["mdir"], j["adir"] / f"{month}{ZIP}"
        size = sum(m["size"] for m in j["members"])
        log(f"{'сухой прогон' if not a.apply else 'перепаковка'} {channel} {month}: "
            f"{mdir} ({j['legacy_n']} файлов, "
            f"сошлись с {LEGACY_MANIFEST}) -> {zpath} ({len(j['members'])} членов, {mb(size)})"
            + (f", плюс {len(j['old'])} из прежнего zip" if j["old"] else ""))
        log(f"  на томе после сверки удалить: {mdir}/")
        for m in j["local"]:
            log(f"  из publish/: {m['src'].relative_to(root)} "
                f"({'git rm' if m['kind'] == 'md' else 'удалить'}; в архиве та же sha256)")
        empty = [d for d in j["days"] if not any(
            m["src"].parent == d for m in j["local"])]
        for d in empty:
            log(f"  из publish/: пустая папка {d.relative_to(root)}")
        pairs = sorted({(m["day"], m["slug"]) for m in j["members"]})
        log(f"  README, acceptance-log и uploads.json: строки {len(pairs)} роликов → "
            f"{pl.archive_where(volume, channel, month + '-01').rsplit('#', 1)[0]}#<день>/<slug>")
    if not a.apply:
        log.say("сухой прогон: ничего не изменено (`--apply` — сделать)")
        return 1 if bad else 0

    need = sum(m["size"] for j in jobs.values() for m in j["members"])
    free = shutil.disk_usage(a.volume).free
    if need + int(a.min_free_gb * (1 << 30)) + ZIP_OVERHEAD > free:
        log(f"мало места на {a.volume}: нужно {mb(need)}, свободно {mb(free)} — ничего не трогаю")
        return 1
    failed, code = archive_jobs(a, root, publish, jobs, volume, today, log,
                                "folder-form month repacked into one zip")
    if not failed and not bad:
        clear_reminder(a.needs_you, log)
    return 1 if failed or bad else code


# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=str(REPO), help="factory root (publish/ is under it)")
    ap.add_argument("--volume", default=DEFAULT_VOLUME)
    ap.add_argument("--log", default=None, help="default: <root>/scripts/archive.log")
    ap.add_argument("--needs-you-dir", default=None,
                    help="the journal of questions' directory (CF-0652; default "
                         "$NEEDS_YOU_DIR, else <root>/needs-you)")
    ap.add_argument("--today", default=None, help="YYYY-MM-DD, default: today in Moscow")
    ap.add_argument("--min-free-gb", type=float, default=MIN_FREE_GB)
    ap.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    ap.add_argument("--no-commit", action="store_true",
                    help="make the edits (git rm, README, acceptance-log), do not commit")
    ap.add_argument("--repack-legacy", action="store_true",
                    help="repack months archived as folders into one zip each "
                         "(a dry run without --apply)")
    ap.add_argument("--apply", action="store_true", help="--repack-legacy: do it")
    ap.add_argument("--commit-pending", action="store_true",
                    help="only make the commit an open batch put off")
    ap.add_argument("--skip-mount-check", action="store_true",
                    help="tests only: a temp folder stands in for the volume")
    ap.add_argument("--publish-only", action="store_true",
                    help="step (a) only - not the monthly pool/batches/other steps "
                         "(scripts/monthly_archive.py)")
    ap.add_argument("--json", action="store_true",
                    help="CF-0720: one JSON document on stdout (the plan with --dry-run, "
                         "what was done otherwise); the lines go to stderr")
    ap.add_argument("--by", default=None, help="CF-0720: who asked (e.g. user)")
    ap.add_argument("--via", default=None, help="CF-0720: from where (e.g. center, cli)")
    import monthly_archive as ma
    ma.add_arguments(ap)
    a = ap.parse_args(argv)
    try:
        a.by, a.via = _who(a.by, "by"), _who(a.via, "via")
    except ValueError as e:
        ap.error(str(e))

    root = Path(a.root).resolve()
    a.needs_you = needs_you_dir(a.needs_you_dir, root)
    today = pl.release_day(a.today) if a.today else msk_today()
    dry = a.dry_run or (a.repack_legacy and not a.apply)
    a.report = new_report(dry, "repack" if a.repack_legacy else "month", today, a.volume,
                          a.by, a.via)
    if not a.json:
        return _run(a, root, today, dry)
    # stdout is the document's alone: the lines and any child's output go to stderr
    sys.stdout.flush()
    saved = None
    try:
        saved = os.dup(1)
        os.dup2(2, 1)
    except OSError:
        saved = None
    try:
        code = _run(a, root, today, dry)
    finally:
        sys.stdout.flush()
        if saved is not None:
            os.dup2(saved, 1)
            os.close(saved)
    a.report["exit_code"] = code
    print(json.dumps(a.report, ensure_ascii=False, indent=2, default=str), flush=True)
    return code


def _run(a, root, today, dry):
    publish = root / "publish"
    sink = a.report["lines"] if a.json else None
    log = Log(a.log or (root / "scripts" / "archive.log"), write=not dry,
              out=sys.stderr if a.json else None, sink=sink)
    archive_root = Path(a.volume) / ARCHIVE_DIR
    volume = Path(a.volume).name

    if not dry:
        log.path.parent.mkdir(parents=True, exist_ok=True)
        lock = open(str(log.path) + ".publish.lock", "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            if e.errno in (errno.EAGAIN, errno.EACCES):
                log.say("другой запуск ещё идёт, выхожу")
                return 0
            raise
        if a.by is not None or a.via is not None:
            log(f"кто: by {a.by or '-'}, via {a.via or '-'}")
        code = commit_pending(a, root, today, log)
        if a.commit_pending:
            return code
    if a.repack_legacy:
        return run_repack(a, root, publish, archive_root, volume, today, log)
    code = run_month(a, root, publish, archive_root, volume, today, log)
    if a.publish_only:
        return code
    # CF-0358 (the user's decision of 2026-10-04): the rest of the monthly
    # freeing - pool, old batches, $TMPDIR - runs right after, in that order.
    import monthly_archive as ma
    monthly = []
    a.report["monthly"] = {"lines": monthly}
    mlog = ma.Log(log.path, write=log.write, out=log.out, sink=monthly if a.json else None)
    return max(code, ma.run_steps(ma.ctx_from_args(a, root, mlog, today)))


if __name__ == "__main__":
    sys.exit(main())
