#!/usr/bin/env python3
"""The meme desk: the user's tool for the meme library (CF-0391).

The library is `shared/inserts/memes/` with its `index.json`. A person decides
what is in it (inserts/POLICY.md); this script is how that decision is made
cheap - the command center's «Мемы» (`/memes`, api/memes.py over the
functions below) where the user looks at every meme, keeps or drops it, ticks
whether it may be cut out, and accepts what was just added; the marks are
saved to shared/inserts/memes/_desk/decisions.json - plus the machine half
around it: adding a still, cutting a GIF from a video, finding the moment in a
clip, and writing the user's marks back. CC-0035 (the center 1.0) retired the
desk's own page (`serve`, port 8765); every command below stays.

    python3 scripts/meme_desk.py status
        what the desk holds: new entries awaiting review, marks, notes
    python3 scripts/meme_desk.py apply [--drop] [--dry-run]
        write the marks into index.json: cutout ticks, accepted new entries;
        rejected new entries are removed with their file. Dropping an
        accepted entry needs --drop, and is refused for a meme an intent in
        inserts/meme.json defaults to (rewrite the vocabulary first).
    python3 scripts/meme_desk.py add-image --id ID --url FILE_URL --source-url PAGE
                                  --description TEXT --tags "a,b,c" [--notes TEXT]
        download a still (Imgflip template file, Wikimedia...), check the stretch
        ceiling, add it as `review: pending` with no rights-holder entry, embed it
    python3 scripts/meme_desk.py add-gif --id ID --video URL_OR_FILE --start S --end E
                                  --description TEXT --tags "a,b,c" [--notes TEXT]
        cut a silent GIF from a video (720p video track via yt-dlp for a URL),
        warn if the span crosses a cut, record the span in `clip`, embed it
    python3 scripts/meme_desk.py cutout [--id ID] [--force] [--dry-run]
        cut the foreground of every `cutout: true` still into <id>.cutout.png
        beside it (macOS Vision, local) and record `cutout_asset` on the entry;
        a cut that fails the machine check is recorded as refused, no file -
        the meme stays whole. Unchanged sources are skipped (sha256).
    python3 scripts/meme_desk.py trim-blank [--id ID] [--dry-run]
        cut the blank caption panel (a white or black band across the full
        width at the top or bottom, asset_floor.blank_band in inserts/meme.json)
        off every still that has one, keeping the original in _desk/originals/,
        re-embedding it and re-checking the stretch ceiling (CF-0534); --dry-run
        only reports what it would cut
    python3 scripts/meme_desk.py sheet --video URL_OR_FILE [--from S] [--to S] [--every S]
        a timestamped contact sheet and the scene cuts of a video, to find the
        moment a GIF is cut from
    python3 scripts/meme_desk.py candidates --channel example-tech
        the bank's candidates.json - the templates waiting on the user's yes,
        with the stretch ceiling recomputed and the total download size
    python3 scripts/meme_desk.py job-run <bank>/_desk/jobs/<job_id>.json
        one background job of the command center, started by start_job() in
        a session of its own (CF-0755) - not for the terminal

Every subcommand takes `--channel ID` or `--bank memes-<channel>` (CF-0393):
the desk then works on that channel's own bank, shared/inserts/memes-<channel>/
(insert_layers.meme.bank in channels/<id>.json), instead of the default
shared/inserts/memes/. A bank that is named but not on disk is refused - the
desk never falls back to the default folder. A channel that names no bank is
the default folder.

Rules the desk enforces rather than trusts (inserts/POLICY.md, inserts/meme.json):
  - a meme carries no rights-holder entry; `source_url` is where the file came from
  - fitted `contain` into the insert box (asset_floor.fit_box_px, 1080x1219),
    a still or a GIF is stretched at most asset_floor.max_upscale_factor (2.25)
    times - the rule the editor's meme gate applies (CF-0392)
  - a blank caption panel of an Imgflip template (a uniform white/black band
    across the full width, at least asset_floor.blank_band.min_share of the
    height on one side) is not content: add-image cuts it off and says so in
    `notes`; the meme itself is never edited (CF-0534)
  - a GIF is inserted whole: never `cutout: true`
  - Giphy and Tenor are not sources; a GIF the library needs is cut here

For the command center (CF-0693) the desk is also functions, each taking its
bank as a parameter (channel=None, bank=None, root=..., repo=...), printing
nothing and refusing with MemeDeskError(code, text): desk_state() - what
`status` prints, as data, with no disk writes; save_marks() - the page's draft,
validated, `by`/`via` stamping the changed marks; plan_apply() / apply_marks()
- `apply` split into the plan and the write, same guards; thumb() - a card's
picture, made explicitly. `status` and `apply` are thin wrappers over them.
The long jobs are functions too (CF-0694), for the center's background
tasks: cutout_available() (the macOS Vision layer, CF-0654),
cutout_entries(), trim_blank_entries(), add_image_entry(), add_gif_entry()
and make_sheet() (written under <bank>/_desk/sheets/ only); the `cutout`,
`trim-blank`, `add-image`, `add-gif` and `sheet` subcommands wrap them.
Accepting the bank's candidates from the center (CF-0725):
candidates_state() - candidates.json with what the disk says and a
fingerprint; plan_accept() - what would be taken in and why not, and the
answer the user types; accept_candidates() - only a candidate whose file is
already in the bank, as `review: pending` with add-image's keys, refused
whole when the list moved since the plan (fingerprint) or the answer is not
the user's «да». Nothing is downloaded or copied there, `cutout` never set.
The center's delta (CF-0760): plan_add_image(), plan_add_gif() and
plan_sheet() take the job's own arguments, refuse with its codes and say what
it would do - {bank, id, file, will_fetch (url | yt-dlp | local), url, video,
source_url, span, tags (normalised), steps, max_seconds} - with no network,
no child and no write; `max_seconds` is the job's worst-case wall time, the
sum of the ceilings of the children it would run (fetch, ffmpeg, probes,
embedding). URLs are http(s) only (bad_url); a local video only with
`local=True` and inside the bank; a URL's video is cached in
<bank>/_desk/clips/<sha1(url)>.mp4; a still's body is at most 25 MB, a sheet
at most 300 frames (too_many_frames). cutout_entries(),
trim_blank_entries(), add_image_entry() and add_gif_entry() take
`by`/`via` (bad_who): a "<kind> <date> (by X, via Y)" stamp in the entry's
notes and a row {at, by, via, kind, ids} in <bank>/_desk/jobs.jsonl
(kind cutout | trim_blank | add_image | add_gif). They and make_sheet() take
`progress(step, i, of, text)` (bad_progress; a callback that raises never
stops the job). The cutout and the trim re-read index.json before their
write and apply their results by id (an entry gone meanwhile:
index_changed); a file that crashes in the middle is refused / left and the
index is written all the same.
Background jobs (CF-0755, center 0.4.1): start_job(kind, params, *,
channel, bank, by, via, root, repo, environ) - kind cutout | trim_blank |
add_image | add_gif | sheet | embed, params the function's own arguments -
refuses what the job's plan refuses (cutout_available + a dry run, the
plan_* functions, the bank for embed) before anything starts, then writes
<bank>/_desk/jobs/<job_id>.json (state running) and starts `job-run
<state_file>` detached (start_new_session, output in <job_id>.log). job-run
puts the homebrew folders on PATH, calls the function with `progress`
writing into the state file (atomic) and records the result, or the error
{code, text, en} (job_crashed with the log's tail for anything unexpected,
embed_failed for an embedding job that did not embed). job_status(job_id) /
list_jobs() read the state files; a job is alive while its process holds
<job_id>.lock (flock handed over by start_job), so a file saying running
over a free lock is `interrupted`. One job per machine: the slot is
<main checkout>/schedule/meme-desk/ ($MEME_DESK_JOBS_DIR) - a second start
is job_running (`.job_id`). No cancel; the last 50 records per bank are
kept.

Embedding and the contact sheet need the footage-indexer venv (torch, Pillow);
the script finds it beside the checkout and calls it, it does not import it.
"""
import argparse
import contextlib
import datetime
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "shared" / "inserts"))
import inserts_lib as lib  # noqa: E402
if str(REPO / "shared" / "runlog") not in sys.path:
    sys.path.append(str(REPO / "shared" / "runlog"))
import git_read  # noqa: E402  (CF-0717: git reads with optional locks off)

KIND = "meme"
LIBRARY = lib.INSERTS_ROOT         # shared/inserts; tests point it at a fixture
BANK = None                        # CF-0393: memes-<channel>, None = the default memes/
CANDIDATES = "candidates.json"     # CF-0393: a bank's list waiting on the user's yes
DESK = "_desk"                     # inside the memes folder, untracked like the media
VENV_PY = REPO / "agents" / "footage-indexer" / ".venv" / "bin" / "python"
VENV_YTDLP = REPO / "agents" / "footage-indexer" / ".venv" / "bin" / "yt-dlp"
USER_AGENT = "shorts-content-factory meme desk (example-user)"
GIF_WIDTH, GIF_FPS = 960, 15
THUMB_WIDTH = 420


class MemeDeskError(Exception):
    """CF-0693: what a desk function refuses, for a caller that is not a
    terminal (the command center's API). `code` is stable and machine-read,
    `text` is the user's language (Russian); `en` is the line the CLI printed
    before CF-0693, so the terminal says what it always said."""

    def __init__(self, code, text, en=None):
        super().__init__(text)
        self.code, self.text, self.en = code, text, en or text


def resolve_bank(channel=None, bank=None, root=None, repo=REPO):
    """CF-0393/CF-0693: (bank name or None, folder) of the bank a desk call
    works on - `channel` reads insert_layers.meme.bank from
    <repo>/channels/<id>.json (no bank there = the default folder), `bank`
    names the folder outright, neither is the default folder. `root` is the
    inserts library (shared/inserts). Reads and returns, sets nothing; a bank
    that is malformed or not on disk is MemeDeskError, never the default."""
    root = Path(root) if root is not None else lib.INSERTS_ROOT
    if channel and bank:
        raise MemeDeskError("bank_conflict", "указаны и канал, и банк — нужно что-то одно",
                            "--channel and --bank both name a bank - give one")
    cfg = None
    if channel:
        path = Path(repo) / "channels" / f"{channel}.json"
        try:
            cfg = json.loads(path.read_text())
        except (OSError, ValueError) as e:
            raise MemeDeskError("no_channel", f"нет настроек канала {channel}",
                                f"no channel config {path} ({e})")
    try:
        return lib.meme_bank_folder(cfg, root, bank=bank)
    except lib.MemeBankError as e:
        raise MemeDeskError("bad_bank", "банк мемов недоступен — его нет на диске или он "
                                         "назван не по правилам", str(e))


# CF-0697: an entry's `file` / `cutout_asset.file` is a name inside its bank.
# Every place the desk opens, thumbnails, cuts or deletes an entry's media goes
# through bank_media: `../x`, an absolute path or a link that leads out of the
# bank is MemeDeskError('outside_bank' - the command center's code for the same
# refusal, contract 0.24.0) and nothing is read, written or deleted.
# The bank is compared resolved (a bank folder linked into the library is the
# folder it names, CF-0393); a version worktree's media are the links
# `scripts/agents sync` made (agents.lock.json links.root) to the same file of
# the working copy, and those are the bank's own.

_WORKING_COPY = {}


def _glob_full(parts, pat):
    """`parts` matches the glob `pat` segment by segment (`**` any number)."""
    import fnmatch  # noqa: PLC0415
    if not pat:
        return not parts
    if pat[0] == "**":
        return any(_glob_full(parts[i:], pat[1:]) for i in range(len(parts) + 1))
    return bool(parts) and fnmatch.fnmatchcase(parts[0], pat[0]) and _glob_full(parts[1:], pat[1:])


def _synced_link(path, real, repo):
    """Is lexical `path` (resolving to `real`) under a link `scripts/agents
    sync` made in `repo`: the first symlink on its way from the repo matches a
    links.root pattern of the repo's lock, points at the same path of the
    working copy, and `real` stays under that target."""
    repo = Path(repo)
    try:
        rel = Path(os.path.abspath(path)).relative_to(os.path.abspath(repo))
    except ValueError:
        return False
    sys.path.insert(0, str(REPO / "shared"))
    try:
        import agents_lock as al  # noqa: PLC0415
    finally:
        sys.path.pop(0)
    try:
        lock = al.load(repo, required=False)
    except al.LockError:
        return False
    pats = [Path(x).parts for x in al.root_links(lock or {})]
    key = os.path.abspath(repo)
    if key not in _WORKING_COPY:
        try:
            _WORKING_COPY[key] = Path(al.working_copy(repo)).resolve()
        except (OSError, RuntimeError):
            _WORKING_COPY[key] = None
    wc = _WORKING_COPY[key]
    if not pats or wc is None or wc == repo.resolve():
        return False
    cur = repo
    for i, part in enumerate(rel.parts):
        cur = cur / part
        if cur.is_symlink():
            sub = rel.parts[:i + 1]
            if not any(_glob_full(sub, pat) for pat in pats):
                return False
            try:
                target = cur.resolve()
                return target == wc.joinpath(*sub).resolve() and real.is_relative_to(target)
            except (OSError, RuntimeError):
                return False
    return False


def bank_media(base, rel, repo=REPO, links=True):
    """CF-0697: `<base>/<rel>` (as written, links not followed) for an entry's
    media name `rel`, when it lies in the bank folder `base`; MemeDeskError
    ('outside_bank') otherwise - an absolute path, a `..`, a link out of the
    bank. `links=False` checks the name only (the terminal's trim-blank and
    cutout, which follow a link into the media it names - CF-0393)."""
    base = Path(base)
    shown = Path(rel).name if isinstance(rel, str) and "\0" not in rel else rel
    bad = MemeDeskError("outside_bank", f"файл {shown!r} лежит вне банка {base.name} — "
                                    f"его не открываю и не удаляю",
                        f"{rel!r} lies outside the bank {base} - not opened, not deleted")
    if not isinstance(rel, str) or not rel or "\0" in rel:
        raise bad
    parts = Path(rel).parts
    if Path(rel).is_absolute() or ".." in parts:
        raise bad
    path = base / rel
    if not links:
        return path
    try:
        home, real = base.resolve(), path.resolve()
    except (OSError, RuntimeError):
        raise bad
    if real.is_relative_to(home) and real != home:
        return path
    if _synced_link(path, real, repo):
        return path
    raise bad


# The CLI's own default: `select_bank` sets BANK for the subcommands of one
# terminal run. The functions for the center (desk_state, save_marks,
# plan_apply, apply_marks, thumb) never read or set it - their bank is a
# parameter (CF-0693).

def folder(root=None):
    return lib.folder_for(KIND, root or LIBRARY, BANK)


def load_index():
    return lib.load_index(KIND, LIBRARY, BANK)


def save_index(idx):
    lib.save_index(idx, KIND, LIBRARY, BANK)


def select_bank(channel=None, bank=None, repo=REPO):
    """CF-0393: point the CLI at a channel's own bank (resolve_bank). Sets and
    returns BANK; a bank that is malformed or not on disk ends the run
    (SystemExit)."""
    global BANK
    try:
        BANK, _ = resolve_bank(channel, bank, LIBRARY, repo)
    except MemeDeskError as e:
        raise SystemExit(e.en)
    return BANK


def desk_dir(root=None):
    d = folder(root) / DESK
    (d / "thumbs").mkdir(parents=True, exist_ok=True)
    return d


def _asset_floor(root=REPO):
    spec = json.loads((Path(root) / "inserts" / "meme.json").read_text())
    return spec["asset_floor"]


def fit_box(root=REPO):
    """(w, h) of the box a meme is drawn `contain` into - inserts/meme.json
    asset_floor.fit_box_px, the editor's meme_box() at 1080x1920 (CF-0392)."""
    bw, bh = _asset_floor(root)["fit_box_px"]
    return int(bw), int(bh)


def max_upscale(root=REPO):
    """inserts/meme.json asset_floor.max_upscale_factor - the one key of the
    block the editor reads, so the desk reads the same one."""
    return float(_asset_floor(root)["max_upscale_factor"])


def upscale_factor(size, box):
    """How far a (w, h) picture is stretched fitted `contain` into box (w, h):
    min(bw / w, bh / h) - the editor's meme_layer.upscale_factor."""
    (w, h), (bw, bh) = size, box
    return min(bw / w, bh / h)


# CF-0534: the blank caption panel. surprised-pikachu (Imgflip 2kbn1e) carried
# 760 white rows of 1892 above the picture; fitted `contain`, they were a white
# strip over the video (WNL 0701Z, 05.10). The defaults are the block
# inserts/meme.json asset_floor.blank_band states; that block wins.
BLANK_BAND_DEFAULTS = {"min_share": 0.12, "white_min": 240, "black_max": 16,
                       "noise_share": 0.005}


def blank_band_spec(root=REPO):
    spec = dict(BLANK_BAND_DEFAULTS)
    try:
        spec.update(_asset_floor(root).get("blank_band") or {})
    except (OSError, ValueError, KeyError):
        pass
    return spec


def _band_rows(data, stride, rows, drop, noise):
    """How many rows from the start of `rows` are of one tone: at most `noise`
    of a row's bytes fall outside the tone (the bytes in `drop` are the tone's,
    deleted by translate - the count left over is the off-tone bytes)."""
    n = 0
    for y in rows:
        r = data[y * stride:(y + 1) * stride]
        if len(r.translate(None, drop)) > noise * len(r):
            break
        n += 1
    return n


def measure_blank_bands(path, spec=None):
    """The blank bands of a picture (a GIF by its first frame): `{size, top,
    bottom, over, crop, trimmed_size, blank}`. `top`/`bottom` are `{rows,
    tone, share}`; a side is `over` when its band is at least `min_share` of
    the height, and `crop` is `[top_rows, bottom_rows]` to cut - the sides
    over the threshold only. A picture that is one tone all over is `blank`,
    with nothing to crop."""
    from PIL import Image                                   # noqa: PLC0415
    spec = spec or blank_band_spec()
    with Image.open(path) as im:
        im.seek(0)
        rgb = im.convert("RGB")
    w, h = rgb.size
    data, stride = rgb.tobytes(), w * 3
    tones = {"white": bytes(range(int(spec["white_min"]), 256)),
             "black": bytes(range(0, int(spec["black_max"]) + 1))}
    out = {"size": [w, h], "blank": False}
    for side, rows in (("top", range(h)), ("bottom", range(h - 1, -1, -1))):
        best = {"rows": 0, "tone": None, "share": 0.0}
        for tone, drop in tones.items():
            n = _band_rows(data, stride, rows, drop, float(spec["noise_share"]))
            if n > best["rows"]:
                best = {"rows": n, "tone": tone, "share": round(n / h, 4)}
        out[side] = best
    if out["top"]["rows"] >= h:
        out.update(blank=True, over=True, crop=None, trimmed_size=None)
        return out
    cut = [out[s]["rows"] if out[s]["share"] >= float(spec["min_share"]) else 0
           for s in ("top", "bottom")]
    out["over"] = any(cut)
    out["crop"] = cut if out["over"] else None
    out["trimmed_size"] = [w, h - sum(cut)] if out["over"] else [w, h]
    return out


def band_phrase(m):
    if m.get("blank"):
        return "one tone all over"
    parts = [f"{side} {m[side]['rows']} {m[side]['tone']} rows ({m[side]['share']:.0%})"
             for side in ("top", "bottom") if m[side]["rows"]]
    return ", ".join(parts) or "no band"


TONE_RU = {"white": "белых", "black": "чёрных"}
SIDE_RU = {"top": "сверху", "bottom": "снизу"}


def _band_ru(side, m, share=".0%"):
    b = m[side]
    return (f"{SIDE_RU[side]} {b['rows']} {TONE_RU.get(b['tone'], b['tone'])} строк "
            f"({b['share']:{share}})")


def band_phrase_ru(m):
    """CF-0762: band_phrase in the user's words."""
    if m.get("blank"):
        return "один тон целиком"
    parts = [_band_ru(side, m) for side in ("top", "bottom") if m[side]["rows"]]
    return ", ".join(parts) or "полос нет"


def trim_blank_file(src, dst, m):
    """Write `src` without the bands `m["crop"]` names into `dst`, in the
    format of `src` (a .part file keeps its format). Stills only."""
    from PIL import Image                                   # noqa: PLC0415
    top, bottom = m["crop"]
    with Image.open(src) as im:
        fmt = im.format
        w, h = im.size
        box = im.crop((0, top, w, h - bottom))
        box.load()
    kw = {"quality": 95} if fmt in ("JPEG", "WEBP") else {}
    if fmt == "JPEG" and box.mode not in ("RGB", "L"):
        box = box.convert("RGB")
    box.save(dst, format=fmt, **kw)
    return box.size


def trim_note(m):
    """The note of a cut: the sides cut, and - so the note never claims a cut
    that did not happen - a side with a band under min_share that was left."""
    sides = list(zip(("top", "bottom"), m.get("crop") or (0, 0)))
    cut = [f"{s} {m[s]['rows']} {m[s]['tone']} rows ({m[s]['share']:.0%})"
           for s, n in sides if n]
    left = [f"{s} {m[s]['rows']} {m[s]['tone']} rows ({m[s]['share']:.1%}, under min_share)"
            for s, n in sides if not n and m[s]["rows"]]
    return (f"CF-0534 ({datetime.date.today().isoformat()}): blank caption panel cut off - "
            f"{', '.join(cut)} of {m['size'][0]}x{m['size'][1]}"
            + (f", left: {', '.join(left)}" if left else "")
            + "; the picture itself is not edited")


def trim_note_ru(m):
    """CF-0762: trim_note in the user's words - for the answer only; the
    entry's notes keep the English line."""
    sides = list(zip(("top", "bottom"), m.get("crop") or (0, 0)))
    cut = [_band_ru(s, m) for s, n in sides if n]
    left = [_band_ru(s, m, ".1%") + " — меньше порога" for s, n in sides if not n and m[s]["rows"]]
    return (f"срезана пустая полоса под подпись: {', '.join(cut)} из "
            f"{m['size'][0]}x{m['size'][1]}"
            + (f"; оставлено: {', '.join(left)}" if left else "")
            + "; сама картинка не тронута")


def leaders_of(bank, repo=REPO):
    """meme id -> the intent of <repo>/inserts/meme.json that defaults to it.
    The vocabulary was measured on the default folder, so a channel's own
    bank (CF-0393, `bank` not None) has no defaults to protect."""
    if bank is not None:
        return {}
    spec = json.loads((Path(repo) / "inserts" / "meme.json").read_text())
    vocab = spec["selection"]["intent_vocabulary"]
    return {v["expected_leader"]: k for k, v in vocab.items() if v.get("expected_leader")}


def intent_leaders(root=REPO):
    """leaders_of() the CLI's bank."""
    return leaders_of(BANK, root)


def read_draft(base):
    """The desk's draft of marks in bank folder `base`, {} when there is none.
    Reads only - no folder is made."""
    p = Path(base) / DESK / "decisions.json"
    return json.loads(p.read_text()) if p.exists() else {}


def write_draft(base, decisions):
    d = Path(base) / DESK
    d.mkdir(parents=True, exist_ok=True)
    p = d / "decisions.json"
    tmp = p.with_suffix(".part")
    tmp.write_text(json.dumps(decisions, ensure_ascii=False, indent=1, sort_keys=True))
    tmp.replace(p)


def load_decisions(root=None):
    return read_draft(folder(root))


def save_decisions(decisions, root=None):
    write_draft(folder(root), decisions)


# CF-0229: every child this desk starts carries a ceiling (tests/test_timeouts.py).
# A probe or a git question answers in well under a second; a media pass
# (yt-dlp fetch of one clip, an ffmpeg cut or a contact sheet) is minutes at
# most; the embedding pass walks the whole library.
PROBE_TIMEOUT_SECONDS = 60
MEDIA_TIMEOUT_SECONDS = 900
EMBED_TIMEOUT_SECONDS = 1800


def run(cmd, *, timeout=MEDIA_TIMEOUT_SECONDS):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise SystemExit(f"{cmd[0]} hung: no answer within the {timeout:g} s ceiling")
    if r.returncode != 0:
        raise SystemExit(f"{cmd[0]} failed: {(r.stderr or r.stdout).strip()[-600:]}")
    return r.stdout


def media_size(path):
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
               "stream=width,height", "-of", "csv=p=0", str(path)],
              timeout=PROBE_TIMEOUT_SECONDS)
    w, h = out.strip().splitlines()[0].split(",")[:2]
    return int(w), int(h)


# --------------------------------------------------------------------------
# reading and applying the marks
# --------------------------------------------------------------------------

def _short(ids, n=12):
    ids = list(ids)
    return ", ".join(ids[:n]) + (f" ... (+{len(ids) - n})" if len(ids) > n else "") if ids else "-"


# --------------------------------------------------------------------------
# CF-0693: the desk as functions - what the command center's API calls.
# Every one takes its bank as a parameter (channel=None, bank=None, root=the
# inserts library, repo=the checkout whose channels/ and inserts/meme.json are
# read), prints nothing and refuses with MemeDeskError(code, text). `status`
# and `apply` below are the terminal's thin wrappers over them.
# --------------------------------------------------------------------------

MARK_KEYS = ("v", "cut", "note")
MARK_META = ("marked_by", "marked_at", "via")


def _bank_index(channel, bank, root, repo):
    name, base = resolve_bank(channel, bank, root, repo)
    lib_root = Path(root) if root is not None else lib.INSERTS_ROOT
    try:
        idx = lib.load_index(KIND, lib_root, name)
    except (OSError, ValueError) as e:
        raise MemeDeskError("bad_index", f"список мемов банка {name or lib.KIND_FOLDERS[KIND]} "
                                         f"не читается",
                            f"index.json of the bank {name or lib.KIND_FOLDERS[KIND]} "
                            f"unreadable ({e})")
    return name, base, lib_root, idx


def _draft_of(base):
    try:
        dec = read_draft(base)
    except (OSError, ValueError) as e:
        raise MemeDeskError("bad_draft", f"черновик отметок банка {Path(base).name} не читается",
                            f"{Path(base) / DESK / 'decisions.json'} unreadable ({e})")
    if not isinstance(dec, dict):
        raise MemeDeskError("bad_draft", "черновик отметок испорчен — в нём не отметки мемов",
                            "decisions.json is not an object {id: mark}")
    return dec


def _leaders(name, repo):
    try:
        return leaders_of(name, repo)
    except (OSError, ValueError, KeyError) as e:
        raise MemeDeskError("bad_spec", "настройки мемов фабрики не читаются",
                            f"inserts/meme.json in {repo} unreadable ({e})")


def desk_state(channel=None, bank=None, *, root=None, repo=REPO):
    """What `status` prints, as data. Reads only: no folder is made, no
    thumbnail, no draft. `bank` is the folder name (`memes` = the default),
    `entries` the index in its order, `decisions` the draft as saved, `status`
    the summary `status` prints. Without Pillow the blank-band check is
    skipped and `blank_bands_checked` is false with a note why."""
    name, base, _, idx = _bank_index(channel, bank, root, repo)
    dec = _draft_of(base)
    entries = []
    for e in idx["entries"]:
        a = e.get("cutout_asset")
        cut_file = cut_refused = cut_refused_en = None
        if e.get("cutout") and isinstance(a, dict):        # the cut file or why it was refused
            try:
                cp = bank_media(base, a["file"], repo) if a.get("file") else None
            except MemeDeskError as ex:                     # CF-0697
                cp, cut_refused, cut_refused_en = None, ex.text, ex.en
            if cp is not None and cp.exists():
                cut_file = a["file"]
            elif cut_refused is None:
                cut_refused = cutout_refused_ru(a)
                cut_refused_en = a.get("refused") or CUT_FILE_MISSING
        entries.append({"id": e["id"], "file": e["file"],
                        "gif": e["file"].lower().endswith(".gif"),
                        "description": e.get("description"), "tags": e.get("tags") or [],
                        "source_url": e.get("source_url"), "notes": e.get("notes"),
                        "review": e.get("review"), "cutout": bool(e.get("cutout")),
                        "cutout_asset": a, "cut_file": cut_file, "cut_refused": cut_refused,
                        "cut_refused_en": cut_refused_en,
                        "clip": e.get("clip")})
    by_id = {e["id"]: e for e in idx["entries"]}
    marks = {i: d for i, d in dec.items() if isinstance(d, dict)}
    cut_marks = {i: bool(d["cut"]) for i, d in marks.items() if "cut" in d and i in by_id}
    st = {"pending": [e["id"] for e in idx["entries"] if e.get("review") == "pending"],
          "keep": sorted(i for i, d in marks.items() if d.get("v") == "keep" and i in by_id),
          "drop": sorted(i for i, d in marks.items() if d.get("v") == "drop" and i in by_id),
          "cut_diff": sorted(i for i, c in cut_marks.items()
                             if c != bool(by_id[i].get("cutout"))),
          "notes": {i: d["note"] for i, d in sorted(marks.items())
                    if (d.get("note") or "").strip() and i in by_id},
          "stale": sorted(set(dec) - set(by_id)),
          "blank_bands": [], "blank_band_errors": [],
          "blank_band_min_share": blank_band_spec(repo)["min_share"]}
    try:
        import PIL  # noqa: F401, PLC0415
    except ImportError:
        st["blank_bands_checked"] = False
        st["blank_bands_note"] = ("пустые полосы под подпись не проверены: на этой машине "
                                  "нет библиотеки для работы с картинками")
        st["blank_bands_note_en"] = ("Pillow is unavailable - blank bands (CF-0534) not "
                                     "checked; run meme_desk.py status where it is")
    else:
        st["blank_bands_checked"] = True
        spec = blank_band_spec(repo)
        for e in idx["entries"]:
            try:
                p = bank_media(base, e["file"], repo)
            except MemeDeskError as ex:                     # CF-0697: never opened
                st["blank_band_errors"].append({"id": e["id"], "error": ex.text, "en": ex.en})
                continue
            if not p.is_file():
                continue
            try:
                m = measure_blank_bands(p, spec)
            except Exception as ex:                         # noqa: BLE001
                st["blank_band_errors"].append({"id": e["id"], "error": "файл не читается",
                                                "en": str(ex)})
                continue
            if m["over"]:
                st["blank_bands"].append({"id": e["id"], "phrase": band_phrase(m),
                                          "phrase_ru": band_phrase_ru(m)})
    return {"bank": name or lib.KIND_FOLDERS[KIND], "default_bank": name is None,
            "channel": channel, "folder": str(base), "entries": entries,
            "decisions": dec, "status": st}


def _check_marks(decisions, ids):
    if not isinstance(decisions, dict):
        raise MemeDeskError("bad_decisions", "отметки — объект {id мема: отметка}")
    for i, d in decisions.items():
        if i not in ids:
            raise MemeDeskError("unknown_id", f"мема {i!r} нет в банке")
        if not isinstance(d, dict):
            raise MemeDeskError("bad_decisions", f"{i}: отметка — объект {{v, cut, note}}")
        extra = sorted(set(d) - set(MARK_KEYS) - set(MARK_META))
        if extra:
            raise MemeDeskError("bad_decisions", f"{i}: лишние поля {', '.join(extra)} "
                                                 f"(можно v, cut, note)")
        if "v" in d and d["v"] not in ("keep", "drop"):
            raise MemeDeskError("bad_decisions", f"{i}: v — keep или drop, а не {d['v']!r}")
        if "cut" in d and not isinstance(d["cut"], bool):
            raise MemeDeskError("bad_decisions", f"{i}: cut — да или нет")
        if "note" in d and not isinstance(d["note"], str):
            raise MemeDeskError("bad_decisions", f"{i}: note — строка")
        for k in MARK_META:
            if k in d and not isinstance(d[k], str):
                raise MemeDeskError("bad_decisions", f"{i}: {k} — строка")


def save_marks(decisions, channel=None, bank=None, *, by=None, via=None, root=None, repo=REPO):
    """Save the desk's draft of marks, `{id: {v: keep|drop, cut: bool, note:
    str}}`, whole - as the center's «Мемы» does on every click. Unknown ids and bad
    values are MemeDeskError. Without `by`/`via` the draft is byte-identical
    to the retired desk page's; with them every mark that differs from the saved draft is
    stamped `marked_by`, `marked_at` (UTC, ISO) and `via`, an unchanged mark
    keeps the stamp it had. Writes only the draft - index.json is `apply`'s."""
    name, base, _, idx = _bank_index(channel, bank, root, repo)
    _check_marks(decisions, {e["id"] for e in idx["entries"]})
    out = decisions
    if by is not None or via is not None:
        old = _draft_of(base)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        stamp = {k: v for k, v in (("marked_by", by), ("marked_at", now), ("via", via))
                 if v is not None}
        out = {}
        for i, d in decisions.items():
            core = {k: d[k] for k in MARK_KEYS if k in d}
            prev = old.get(i) if isinstance(old.get(i), dict) else {}
            if core == {k: prev[k] for k in MARK_KEYS if k in prev}:
                out[i] = {**core, **{k: prev[k] for k in MARK_META if k in prev}}
            else:
                out[i] = {**core, **stamp}
    write_draft(base, out)
    return {"saved": len(out), "bank": name or lib.KIND_FOLDERS[KIND]}


def _plan(channel, bank, drop, root, repo):
    """The one computation of `apply`: (result, new index, draft, removed
    entries). Writes nothing."""
    name, base, lib_root, idx = _bank_index(channel, bank, root, repo)
    dec = _draft_of(base)
    leaders = _leaders(name, repo)
    kept, removed, refused, changed, uncut = [], [], [], [], []
    out = []
    for e in idx["entries"]:
        d = dec.get(e["id"], {})
        d = d if isinstance(d, dict) else {}
        pending = e.get("review") == "pending"
        if d.get("v") == "drop" and (pending or drop):
            if e["id"] in leaders:
                refused.append({"id": e["id"], "intent": leaders[e["id"]]})
                out.append(e)
                continue
            removed.append(e)
            continue
        if pending and d.get("v") == "keep":
            e.pop("review")
            kept.append(e["id"])
        if "cut" in d:
            want = bool(d["cut"]) and not e["file"].lower().endswith(".gif")
            if bool(e.get("cutout")) != want or "cutout" not in e:
                e["cutout"] = want
                changed.append(e["id"])
            if not want and "cutout_asset" in e:
                # CF-0403: the cut belongs to a `cutout: true` meme only
                a = e.pop("cutout_asset")
                if isinstance(a, dict) and a.get("file"):
                    uncut.append(a["file"])
        out.append(e)
    idx["entries"] = out
    held = sorted(i for i, d in dec.items() if isinstance(d, dict) and d.get("v") == "drop"
                  and any(e["id"] == i and e.get("review") != "pending" for e in out)
                  and not drop and i not in leaders)
    files = []
    for e in removed:
        a = e.get("cutout_asset")
        files += [e["file"]] + ([a["file"]] if isinstance(a, dict) and a.get("file") else [])
    files += uncut
    deletable, outside = [], []
    for f in files:
        try:
            if bank_media(base, f, repo).exists():
                deletable.append(f)
        except MemeDeskError as ex:                         # CF-0697: never deleted
            outside.append(ex.text)
    result = {"bank": name or lib.KIND_FOLDERS[KIND], "default_bank": name is None,
              "drop": bool(drop), "accept": kept, "cutout_changed": changed,
              "remove": [e["id"] for e in removed], "refused": refused, "held": held,
              "errors": lib.validate_index(idx, KIND) + outside,
              "files_to_delete": deletable}
    return result, (name, base, lib_root, idx), dec, removed


def plan_apply(channel=None, drop=False, *, bank=None, root=None, repo=REPO):
    """What `apply` would do, written nowhere: `accept` (new entries kept),
    `cutout_changed`, `remove`, `refused` [{id, intent}] (an intent's default
    in the default bank is never removed), `held` (accepted entries marked
    drop that stay without `drop`), `errors` (the index it would write is
    invalid - apply_marks refuses), `files_to_delete` (media that would go)."""
    return _plan(channel, bank, drop, root, repo)[0]


def apply_marks(channel=None, drop=False, *, bank=None, root=None, repo=REPO):
    """`apply` without --dry-run: exactly what plan_apply returns, done -
    index.json written, the files of `files_to_delete` deleted, the removed
    ids' marks taken out of the draft. Accepted entries leave only with
    `drop`; `cutout` changes only where a mark says so. An invalid index is
    MemeDeskError('invalid_index') and nothing is written. Adds `written`."""
    result, (name, base, lib_root, idx), dec, removed = _plan(channel, bank, drop, root, repo)
    if result["errors"]:
        raise MemeDeskError("invalid_index",
                            f"список мемов не записан — он вышел бы неверным "
                            f"(ошибок: {len(result['errors'])})",
                            "refusing to write an invalid index:\n  "
                            + "\n  ".join(result["errors"]))
    lib.save_index(idx, KIND, lib_root, name)
    for f in result["files_to_delete"]:
        p = bank_media(base, f, repo)
        if p.exists():
            p.unlink()
    for e in removed:
        dec.pop(e["id"], None)
    write_draft(base, dec)
    return {**result, "written": True}


def _make_thumb(src, out):
    """A small JPEG of still `src` at `out`, made when missing or older than
    the source; False when ffmpeg failed or hung."""
    if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
        return True
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf",
                        f"scale='min({THUMB_WIDTH},iw)':-2", "-frames:v", "1", str(out)],
                       capture_output=True, timeout=PROBE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return False
    return out.exists() and out.stat().st_mtime >= src.stat().st_mtime


def thumb(channel=None, meme_id=None, *, bank=None, root=None, repo=REPO):
    """The picture a card shows for `meme_id`, made on this call (desk_state
    never makes one): a still's JPEG thumbnail in <bank>/_desk/thumbs/ (made
    or refreshed), a GIF's own file so it plays. Returns the absolute Path."""
    name, base, _, idx = _bank_index(channel, bank, root, repo)
    e = next((x for x in idx["entries"] if x["id"] == meme_id), None)
    if e is None:
        raise MemeDeskError("unknown_id", f"мема {meme_id!r} нет в банке")
    if e["file"].lower().endswith(".gif"):
        # nothing opened, nothing made: the path as written, for the caller
        # that serves it to guard (api/memes.py thumb_path: factory.contained,
        # 404 outside_bank - CC-0078)
        src = base / e["file"]
        if not src.is_file():
            raise MemeDeskError("no_file", f"файла {e['file']} нет в банке "
                                           f"{name or lib.KIND_FOLDERS[KIND]}")
        return src
    src = bank_media(base, e["file"], repo)          # CF-0697: outside_bank, nothing made
    if not src.is_file():
        raise MemeDeskError("no_file", f"файла {e['file']} нет в банке "
                                       f"{name or lib.KIND_FOLDERS[KIND]}")
    out = base / DESK / "thumbs" / (Path(e["file"]).stem + ".jpg")
    out.parent.mkdir(parents=True, exist_ok=True)
    if not _make_thumb(src, out):
        raise MemeDeskError("thumb_failed", f"миниатюра {e['id']} не сделана (ffmpeg)")
    return out


# the terminal

def status(args):
    try:
        s = desk_state(bank=BANK, root=LIBRARY)
    except MemeDeskError as e:
        raise SystemExit(e.en)
    st = s["status"]
    n = len(s["entries"])
    print(f"library{f' {BANK}' if BANK else ''}: {n} memes, {len(st['pending'])} awaiting "
          f"review: {', '.join(st['pending']) or '-'}")
    print(f"marked keep {len(st['keep'])}, drop {len(st['drop'])}: {_short(st['drop'])}")
    print(f"cutout ticks differing from index.json: {', '.join(st['cut_diff']) or '-'}")
    for i, note in st["notes"].items():
        print(f"note {i}: {note}")
    if st["blank_bands_checked"]:
        for b in st["blank_band_errors"]:
            print(f"blank band of {b['id']}: unreadable ({b['error']})")
        banded = [f"{b['id']} ({b['phrase']})" for b in st["blank_bands"]]
        print(f"blank caption panels over {st['blank_band_min_share']:.0%} (CF-0534, "
              f"trim-blank): {'; '.join(banded) or '-'}")
    else:
        print("blank caption panels (CF-0534): not checked - Pillow is not installed here")
    if st["stale"]:
        print(f"marks for ids no longer in the library (ignored): {', '.join(st['stale'])}")


def apply(args):
    try:
        plan = plan_apply(drop=args.drop, bank=BANK, root=LIBRARY)
    except MemeDeskError as e:
        raise SystemExit(e.en)
    if plan["errors"]:
        raise SystemExit("refusing to write an invalid index:\n  " + "\n  ".join(plan["errors"]))
    if BANK:
        print(f"bank {BANK}")
    print(f"accept {len(plan['accept'])}: {', '.join(plan['accept']) or '-'}")
    print(f"cutout written {len(plan['cutout_changed'])}: "
          f"{', '.join(plan['cutout_changed']) or '-'}")
    print(f"remove {len(plan['remove'])}: {', '.join(plan['remove']) or '-'}")
    if plan["refused"]:
        print("refused to remove (rewrite inserts/meme.json intent_vocabulary first): "
              + ", ".join(f"{r['id']} (default of intent '{r['intent']}')"
                          for r in plan["refused"]))
    if plan["held"]:
        print(f"marked drop but kept - accepted entries leave only with --drop: "
              f"{len(plan['held'])}")
    if args.dry_run:
        print("dry run - nothing written")
        return
    try:
        apply_marks(drop=args.drop, bank=BANK, root=LIBRARY)
    except MemeDeskError as e:
        raise SystemExit(e.en)
    print("index.json written; run the insert tests before committing")


# --------------------------------------------------------------------------
# adding
# --------------------------------------------------------------------------

def _tags_of(tags):
    if isinstance(tags, str):
        tags = tags.split(",")
    if not isinstance(tags, (list, tuple)) or not all(isinstance(t, str) for t in tags):
        raise MemeDeskError("bad_entry", "теги — список строк или строка через запятую")
    return [t.strip() for t in tags if t.strip()]


def _check_new(idx, meme_id, description):
    """An id the bank can take: the index's id pattern, not taken yet."""
    if not isinstance(meme_id, str) or not lib.ID_RE.match(meme_id):
        raise MemeDeskError("bad_entry", f"id {meme_id!r}: только строчные латинские буквы, "
                                         f"цифры, дефис и подчёркивание",
                            f"id must match {lib.ID_RE.pattern}")
    if any(e["id"] == meme_id for e in idx["entries"]):
        raise MemeDeskError("duplicate_id", f"{meme_id} уже есть в банке",
                            f"{meme_id} is already in the library")
    if not isinstance(description, str) or not description.strip():
        raise MemeDeskError("bad_entry", "нужно описание мема", "a meme needs a description")


def _append_entry(name, base, lib_root, meme_id, file, source_url, description, tags,
                  notes, extra):
    """Add the entry for `file` (already in the bank) to the bank's index as
    `review: pending`, no rights-holder entry. The index is read afresh - a long
    download may have run in between. MemeDeskError when it does not fit."""
    idx = lib.load_index(KIND, lib_root, name)
    _check_new(idx, meme_id, description)
    entry = {"id": meme_id, "file": file, "kind": KIND, "description": description,
             "tags": _tags_of(tags), "source_url": source_url, "licence": None,
             "medium": None, "added": datetime.date.today().isoformat(), "review": "pending",
             "notes": (notes or "").strip() or None}
    entry.update(extra)
    if entry["notes"] is None:
        entry.pop("notes")
    errs = lib.validate_entry(entry, KIND, base)
    if errs:
        raise MemeDeskError("invalid_entry", f"запись не принята — она не проходит проверку банка (ошибок: {len(errs)})",
                            "\n".join(errs))
    idx["entries"].append(entry)
    lib.save_index(idx, KIND, lib_root, name)
    return entry


def _new_entry(args, file, source_url, extra):
    """The terminal's add: _append_entry on the CLI's bank."""
    return _append_entry(BANK, folder(), LIBRARY, args.id, file, source_url, args.description,
                         args.tags, args.notes, extra)


EMBED_STEP_RU = "признаки для поиска похожих мемов"       # CF-0762: the embeddings, in words
EMBED_NOT_DONE_RU = "признаки для поиска похожих мемов не пересчитаны"


def _embed_run(name, lib_root):
    """CF-0694: recompute the bank's embeddings (scripts/index_inserts.py
    under the footage-indexer venv). Prints nothing, raises nothing: the entry
    is in either way, so the outcome is data - `{done, line, error, en}`;
    `done` False with `error` when there is no venv, the child hung or failed.
    Tests replace this."""
    py = indexer_python()
    if not py.exists():
        return {"done": False, "line": None,
                "error": f"{EMBED_NOT_DONE_RU}: на этой машине нет среды для пересчёта; "
                         f"мем в банке, пересчёт можно запустить позже",
                "en": f"no {py}: the entry is in without an embedding; "
                      "run scripts/index_inserts.py --kind meme from the footage-indexer venv",
                "fatal": False}
    try:
        r = subprocess.run([str(py), str(REPO / "scripts" / "index_inserts.py"),
                            "--kind", KIND, "--strict", "--root", str(lib_root),
                            *(["--bank", name] if name else [])],
                           capture_output=True, text=True, timeout=EMBED_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return {"done": False, "line": None,
                "error": f"{EMBED_NOT_DONE_RU}: пересчёт не ответил за "
                         f"{EMBED_TIMEOUT_SECONDS} с; мем в банке",
                "en": f"index_inserts.py hung: no answer within the "
                      f"{EMBED_TIMEOUT_SECONDS} s ceiling; the entry is in without an embedding",
                "fatal": True}
    lines = (r.stdout or r.stderr).strip().splitlines()
    line = lines[-1] if lines else ""
    if r.returncode != 0:
        return {"done": False, "line": line, "error": f"{EMBED_NOT_DONE_RU}: пересчёт завершился с ошибкой",
                "en": r.stderr[-600:], "fatal": True}
    return {"done": True, "line": line, "error": None, "en": None, "fatal": False}


def _embed():
    """The terminal's embedding: what _embed_run did, printed; a hang or a
    failure ends the run as before."""
    r = _embed_run(BANK, LIBRARY)
    if r["line"] is not None:
        print(r["line"])
    elif not r["fatal"]:
        print(r["en"])
    if r["fatal"]:
        raise SystemExit(r["en"])


def _floor_error(path, size, box, ceiling):
    """The terminal's line refusing a file stretched past the ceiling, or None."""
    w, h = size
    factor = upscale_factor((w, h), box)
    if factor > ceiling + 1e-9:
        return (f"{Path(path).name} is {w}x{h}: stretched {factor:.2f}x into the "
                f"{box[0]}x{box[1]} insert box, over the {ceiling} ceiling "
                f"(inserts/meme.json asset_floor.max_upscale_factor) - find a "
                f"larger file, or for a GIF cut it from the video with add-gif")
    return None


def _check_floor(path, box=None, repo=REPO):
    """(w, h) of a file the editor would place, SystemExit otherwise. The rule
    is the editor's (CF-0392): refused only when the stretch into `box` - the
    insert box by default; a CF-0380 cutout passes its own - exceeds
    max_upscale_factor. The short side alone decides nothing."""
    w, h = media_size(path)
    err = _floor_error(path, (w, h), tuple(box or fit_box(repo)), max_upscale(repo))
    if err:
        raise SystemExit(err)
    return w, h


@contextlib.contextmanager
def _as_error(code, what):
    """The terminal helpers (run, media_size, _video_file, scene_cuts) end a
    run with SystemExit; inside a function that is MemeDeskError(code)."""
    try:
        yield
    except SystemExit as e:
        raise MemeDeskError(code, what, str(e)) from None


def _floor(path, repo):
    """_check_floor for the functions: MemeDeskError('over_ceiling')."""
    with _as_error("media_failed", "размер файла не прочитан"):
        w, h = media_size(path)
    box, ceiling = fit_box(repo), max_upscale(repo)
    err = _floor_error(path, (w, h), box, ceiling)
    if err:
        raise MemeDeskError("over_ceiling",
                            f"{Path(path).name} {w}x{h}: в окне {box[0]}x{box[1]} растянулась бы "
                            f"в {upscale_factor((w, h), box):.2f} раза — допустимо до {ceiling}; "
                            f"нужен файл крупнее, а GIF — вырезать из видео", err)
    return w, h


FETCH_TIMEOUT_SECONDS = 30
MAX_IMAGE_BYTES = 25 * 1024 * 1024  # CF-0760: a still's body; more is download_failed
MAX_SHEET_FRAMES = 300              # CF-0760: frames of one contact sheet; more is too_many_frames
CLIPS = "clips"                     # CF-0760: <bank>/_desk/clips/<sha1(url)>.mp4, the video cache


def check_url(url, what="url"):
    """CF-0760: `url` when it is an http(s) address with a host, else
    MemeDeskError('bad_url') - file://, a bare path, ftp: and the rest are
    never handed to urlopen or yt-dlp."""
    from urllib.parse import urlsplit  # noqa: PLC0415
    ok = isinstance(url, str) and bool(url) and not any(c in url for c in " \t\r\n\0")
    if ok:
        try:
            u = urlsplit(url)
            ok = u.scheme in ("http", "https") and bool(u.hostname)
        except ValueError:
            ok = False
    if not ok:
        said = {"url": "адрес картинки", "video": "адрес видео"}.get(what, what)
        raise MemeDeskError("bad_url", f"{said}: нужен адрес в интернете (http или https) — "
                                       f"локальный путь, file: и другие схемы не принимаются",
                            f"{what} must be an http(s) URL, not {url!r}")
    return url


def _fetch(url):
    """The bytes of a still at `url` - the add's one download. Called only
    by add_image_entry, i.e. on the user's word; tests replace it. http(s)
    only (bad_url); a body over MAX_IMAGE_BYTES is download_failed."""
    check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    mb = MAX_IMAGE_BYTES // (1024 * 1024)
    big = MemeDeskError("download_failed", f"{url} не скачан: файл больше {mb} МБ — "
                                           f"это не картинка-мем",
                        f"{url} not fetched: over the {mb} MB ceiling")
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as r:
            size = r.headers.get("Content-Length") if getattr(r, "headers", None) else None
            if size and size.isdigit() and int(size) > MAX_IMAGE_BYTES:
                raise big
            body = r.read(MAX_IMAGE_BYTES + 1)
    except (OSError, ValueError) as e:
        raise MemeDeskError("download_failed", f"{url} не скачан",
                            f"{url} not fetched ({e})")
    if len(body) > MAX_IMAGE_BYTES:
        raise big
    return body


STILL_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _image_check(name, base, lib_root, meme_id, url, source_url, description, tags, repo):
    """add-image's refusals known before the download - shared by the add
    and plan_add_image (CF-0760), so the plan refuses exactly what the add
    would: (target path in the bank, normalised tags)."""
    check_url(url)
    suffix = Path(str(url).split("?")[0]).suffix.lower()
    if suffix not in STILL_SUFFIXES:
        raise MemeDeskError("bad_suffix", f"картинка — .png, .jpg, .jpeg или .webp, а не {suffix!r}; "
                                          f"GIF добавляется из видео",
                            f"a still is .png/.jpg/.jpeg/.webp, not {suffix!r}; "
                            f"a GIF goes through add-gif")
    if not isinstance(source_url, str) or not source_url.startswith(("http://", "https://")):
        raise MemeDeskError("no_source_url", "нужна ссылка на страницу, где файл найден",
                            "--source-url: the page the file was found on (http/https)")
    _check_new(lib.load_index(KIND, lib_root, name), meme_id, description)
    tags = _tags_of(tags)
    target = bank_media(base, f"{meme_id}{suffix}", repo)
    if target.exists() or target.is_symlink():
        raise MemeDeskError("file_exists", f"{target.name} уже лежит в банке",
                            f"{target} already exists")
    return target, tags


def _add_image(name, base, lib_root, meme_id, url, source_url, description, tags, notes, repo,
               by=None, via=None, progress=None, of=4):
    """add-image's work on bank folder `base`: {entry, file, size, trim_note}.
    CF-0760: `by`/`via` stamp the entry's notes ("add_image <date> (by …)");
    progress ("download", 1, of, url) → ("check", 2, …) → ("index", 3, …)."""
    target, tags = _image_check(name, base, lib_root, meme_id, url, source_url, description,
                                tags, repo)
    _tick(progress, "download", 1, of, url)
    body = _fetch(url)
    _tick(progress, "check", 2, of, target.name)
    tmp = target.with_name(target.name + ".part")
    tmp.write_bytes(body)
    note = note_ru = None
    try:
        try:
            m = measure_blank_bands(tmp, blank_band_spec(repo))
        except Exception as e:                              # noqa: BLE001
            raise MemeDeskError("bad_image", f"{url} — не картинка",
                                f"{url} is not a picture ({e})")
        if m["blank"]:
            raise MemeDeskError("blank_image", f"{url} — один тон целиком, это не мем",
                                f"{url} is one tone all over - not a meme")
        if m["over"]:
            trim_blank_file(tmp, tmp, m)
            note, note_ru = trim_note(m), trim_note_ru(m)
        w, h = _floor(tmp, repo)
    except BaseException:
        tmp.unlink()
        raise
    tmp.replace(target)
    notes = "; ".join(x for x in ((notes or "").strip(), note or "") if x) or None
    notes = _stamp(notes, "add_image", by, via)
    _tick(progress, "index", 3, of, meme_id)
    try:
        entry = _append_entry(name, base, lib_root, meme_id, target.name, source_url,
                              description, tags, notes, {"download_url": url})
    except MemeDeskError:
        target.unlink()             # the file came in with this call; the bank stays as it was
        raise
    return {"entry": entry, "file": target.name, "size": [w, h], "trim_note": note,
            "trim_note_ru": note_ru}


def add_image_entry(meme_id, url, source_url, description, tags, notes=None, channel=None,
                    bank=None, *, root=None, repo=REPO, embed=True, by=None, via=None,
                    progress=None):
    """CF-0694: `add-image` as a function - downloads the still at `url`
    (an Imgflip template file, Wikimedia...; only on the user's word), cuts a
    blank caption panel off (said in `notes`, CF-0534), checks the stretch
    ceiling (CF-0392) and adds it to the bank as `review: pending` with
    `source_url` and no rights-holder entry, then embeds the bank. `tags` - a list
    or "a,b,c". Returns {bank, entry, file, size, trim_note, embedding}
    (embedding: _embed_run's outcome, None with embed=False). Nothing is left
    in the bank when it is refused (MemeDeskError: bad_entry, duplicate_id,
    bad_suffix, no_source_url, file_exists, download_failed, bad_image,
    blank_image, over_ceiling, media_failed, invalid_entry, outside_bank,
    bad_url, bad_who, bad_progress).
    CF-0760: `by`/`via` stamp the entry's notes ("add_image <date> (by X,
    via Y)") and add the row {at, by, via, kind: "add_image", ids: [id]} to
    <bank>/_desk/jobs.jsonl; `progress(step, i, of, text)` - ("download", 1,
    4, url) → ("check", 2, 4, file) → ("index", 3, 4, id) → ("embedding", 4,
    4, …) (of = 3, no embedding step, with embed=False). plan_add_image() says
    beforehand, with no network and no write, what this call would do."""
    by, via, progress = _who(by, "by"), _who(via, "via"), check_progress(progress)
    name, base, lib_root, _ = _bank_index(channel, bank, root, repo)
    r = _add_image(name, base, lib_root, meme_id, url, source_url, description, tags,
                   notes, repo, by, via, progress, 4 if embed else 3)
    _journal(base, "add_image", [meme_id], by, via)
    r["bank"] = name or lib.KIND_FOLDERS[KIND]
    r["embedding"] = _embed_step(name, lib_root, embed, progress, 4)
    return r


def _embed_step(name, lib_root, embed, progress, i):
    """The adds' last step (CF-0760): ("embedding", i, i, …), then
    _embed_run; None with embed=False."""
    if not embed:
        return None
    _tick(progress, "embedding", i, i, EMBED_STEP_RU)
    return _embed_run(name, lib_root)


def add_image(args):
    r = _add_image(BANK, folder(), LIBRARY, args.id, args.url, args.source_url,
                   args.description, args.tags, args.notes, REPO)
    if r["trim_note"]:
        print(f"{args.id}: {r['trim_note']}")
    w, h = r["size"]
    print(f"added {args.id}: {r['file']} {w}x{h}, review pending")
    _embed()


JOBS_JOURNAL = "jobs.jsonl"        # CF-0760: <bank>/_desk/jobs.jsonl, who ran which job


def check_progress(progress):
    """CF-0760: `progress` - None or a callable (step, i, of, text); else
    MemeDeskError('bad_progress')."""
    if progress is not None and not callable(progress):
        raise MemeDeskError("bad_progress", "progress — функция (step, i, of, text) или None")
    return progress


def _tick(progress, step, i, of, text=""):
    """Tell `progress` where a job is: (step, i, of, text). A callback that
    raises never stops the work (CF-0760) - its error is dropped here."""
    if progress is None:
        return
    with contextlib.suppress(Exception):
        progress(step, i, of, text)


def _stamp(notes, kind, by, via, today=None):
    """`notes` with the stamp of a job run by `by` via `via` (CF-0760) -
    "<kind> <date> (by X, via Y)"; an earlier stamp of the same kind is
    replaced, so a re-run does not grow the notes. Unchanged with neither."""
    if by is None and via is None:
        return notes
    who = ", ".join(x for x in (f"by {by}" if by else "", f"via {via}" if via else "") if x)
    old = re.compile(rf"^{re.escape(kind)} \d{{4}}-\d{{2}}-\d{{2}} \(")
    keep = [x for x in (notes or "").split("; ") if x.strip() and not old.match(x)]
    return "; ".join(keep + [f"{kind} {today or datetime.date.today().isoformat()} ({who})"])


def _journal(base, kind, ids, by, via):
    """One row of <bank>/_desk/jobs.jsonl: {at, by, via, kind, ids} (CF-0760)."""
    d = Path(base) / DESK
    d.mkdir(parents=True, exist_ok=True)
    row = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "by": by, "via": via, "kind": kind, "ids": list(ids)}
    with (d / JOBS_JOURNAL).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_by_id(name, lib_root, changes, validate=True):
    """CF-0760: a pass's results written into index.json as it is on disk
    NOW - read afresh right before the write, each change applied to its
    entry by id - so marks applied or candidates accepted while the pass ran
    are kept. `changes` {id: fn(entry)}. Returns (written, gone): the ids no
    longer in the index are not written (the caller says index_changed)."""
    fresh = lib.load_index(KIND, lib_root, name)
    by_id = {e["id"]: e for e in fresh["entries"]}
    gone = [i for i in changes if i not in by_id]
    if len(gone) == len(changes):
        return False, gone
    for i, fn in changes.items():
        if i in by_id:
            fn(by_id[i])
    errs = lib.validate_index(fresh, KIND) if validate else []
    if errs:
        raise MemeDeskError("invalid_index",
                            f"список мемов не записан — он вышел бы неверным "
                            f"(ошибок: {len(errs)})",
                            "refusing to write an invalid index:\n  " + "\n  ".join(errs))
    lib.save_index(fresh, KIND, lib_root, name)
    return True, gone


def _index_changed(gone, what):
    return MemeDeskError("index_changed",
                         f"пока шёл проход, из банка убрали {', '.join(gone)} (применение "
                         f"отметок или приём кандидатов) — {what} для них не записан(а); "
                         f"остальное записано",
                         f"{', '.join(gone)} left index.json during the pass - {what} not "
                         f"recorded for them; the rest is written")


def _trim(name, base, lib_root, idx, only, dry_run, repo, links, by=None, via=None,
          progress=None, journal=False):
    """CF-0534/CF-0694: the one pass over bank folder `base` - every still
    with a blank band over the threshold is cut (the original kept in
    _desk/originals/), its embedding dropped for recomputing, and the stretch
    ceiling of CF-0392 checked on the cut size. A still the cut would push
    under the ceiling is left whole and reported (`under`): whether to drop
    or replace it is the user's call. A GIF is reported, never cut (its bands
    may move from frame to frame). CF-0760: a file that fails in the middle
    is `left` with the reason and the pass goes on; what was cut is written
    into index.json read afresh (_write_by_id) even when the pass breaks off,
    and an entry gone meanwhile is MemeDeskError('index_changed')."""
    spec = blank_band_spec(repo)
    box, ceiling = fit_box(repo), max_upscale(repo)
    trim, left, under, changed = [], [], [], []
    changes = {}
    todo = [e for e in idx["entries"] if not only or e["id"] == only]
    _tick(progress, "trim", 0, len(todo), "")
    broke = None
    try:
        for i, e in enumerate(todo, 1):
            _trim_one(e, base, repo, links, spec, box, ceiling, dry_run, by, via,
                      trim, left, under, changes)
            _tick(progress, "trim", i, len(todo), e["id"])
    except BaseException as ex:                             # noqa: BLE001
        broke = ex
    gone = []
    if changes:
        # the trim wrote its index unchecked before CF-0760 too: a bank whose
        # index already carries a bad entry still gets its cuts recorded
        written, gone = _write_by_id(name, lib_root, changes, validate=False)
        changed = [i for i in changes if i not in gone]
        if written and journal:
            _journal(base, "trim_blank", changed, by, via)
    if broke is not None:
        raise broke
    if gone:
        raise _index_changed(gone, "срез полей")
    return {"bank": name or lib.KIND_FOLDERS[KIND], "dry_run": bool(dry_run),
            "trim": trim, "left": left, "under": under, "changed": changed,
            "originals": str(Path(base) / DESK / "originals") if changed else None}


def _trim_one(e, base, repo, links, spec, box, ceiling, dry_run, by, via, trim, left, under,
              changes):
    """_trim's work on one entry; its rows go to trim/left/under, the index
    change to `changes`."""
    try:
        p = bank_media(base, e["file"], repo, links=links)
    except MemeDeskError as ex:                             # CF-0697: never cut
        left.append({"id": e["id"], "reason": ex.text, "en": ex.en})
        return
    if not p.is_file():
        return
    try:
        m = measure_blank_bands(p, spec)
    except Exception as ex:                                 # noqa: BLE001
        left.append({"id": e["id"], "reason": "файл не читается",
                     "en": f"unreadable ({ex})"})
        return
    if not m["over"]:
        return
    if m["blank"] or p.suffix.lower() == ".gif":
        why = "a GIF is not cut here" if not m["blank"] else "nothing to keep"
        left.append({"id": e["id"],
                     "reason": f"{band_phrase_ru(m)} — " + ("GIF здесь не режется"
                               if not m["blank"] else "оставлять нечего")
                               + "; решает пользователь",
                     "en": f"{band_phrase(m)} - {why}; the user decides"})
        return
    row = {"id": e["id"], "file": e["file"], "size": m["size"],
           "trimmed_size": m["trimmed_size"], "crop": m["crop"], "phrase": band_phrase(m),
           "phrase_ru": band_phrase_ru(m),
           "stretch": upscale_factor(m["trimmed_size"], box), "ceiling": ceiling}
    if row["stretch"] > ceiling + 1e-9:
        under.append(row)
        return
    row["recut"] = bool(e.get("cutout_asset"))
    if dry_run:
        trim.append(row)
        return
    # a version worktree borrows the media from the working copy by symlink
    # (agents.lock.json `links`): the cut goes into the file the link names,
    # the link stays a link
    real = p.resolve()
    part = real.with_name(real.name + ".part")
    try:
        keep = Path(base) / DESK / "originals"
        keep.mkdir(parents=True, exist_ok=True)
        if not (keep / p.name).exists():
            shutil.copy2(p, keep / p.name)
        trim_blank_file(real, part, m)
        part.replace(real)
    except Exception as ex:                                 # noqa: BLE001  CF-0760
        with contextlib.suppress(OSError):
            part.unlink()
        left.append({"id": e["id"], "reason": "срез не удался; файл не тронут",
                     "en": f"the cut failed ({ex}); the file is untouched"})
        return
    trim.append(row)
    note = trim_note(m)

    def write(entry, note=note):
        entry["notes"] = _stamp("; ".join(x for x in ((entry.get("notes") or "").strip(), note)
                                          if x), "trim_blank", by, via)
        entry.pop("embedding", None)
    changes[e["id"]] = write


def trim_blank_entries(channel=None, id=None, dry_run=False, *, bank=None, root=None,  # noqa: A002
                       repo=REPO, embed=True, by=None, via=None, progress=None):
    """CF-0694: `trim-blank` as a function, on the bank of `channel`/`bank`
    (or only meme `id`). Returns `trim` [{id, file, size, trimmed_size, crop,
    phrase, stretch, ceiling, recut}] - cut (with dry_run: would be cut;
    `recut` - its cutout is to be redone), `left` [{id, reason}] - a GIF, a
    picture of one tone, an unreadable file, one outside the bank or one whose
    cut failed (CF-0760), never cut, `under` [... as trim] - the cut would
    push it over the stretch ceiling, left whole, `changed` [id] - cut on this
    call, `originals` - where the originals are kept, and `embedding`
    (_embed_run's outcome, None when nothing changed or `embed` is False).
    dry_run writes nothing. CF-0760: `by`/`via` (bad_who) stamp the cut
    entries' notes and the run's row in <bank>/_desk/jobs.jsonl
    {at, by, via, kind: "trim_blank", ids}; `progress(step, i, of, text)` -
    ("trim", i, N, id) per entry, then ("embedding", 1, 1, ...); an entry
    removed from index.json during the pass is MemeDeskError('index_changed')
    (the rest is written)."""
    by, via, progress = _who(by, "by"), _who(via, "via"), check_progress(progress)
    name, base, lib_root, idx = _bank_index(channel, bank, root, repo)
    if id is not None and not any(e["id"] == id for e in idx["entries"]):
        raise MemeDeskError("unknown_id", f"мема {id!r} нет в банке")
    r = _trim(name, base, lib_root, idx, id, dry_run, repo, True, by, via, progress, True)
    r["embedding"] = None
    if r["changed"] and embed:
        _tick(progress, "embedding", 1, 1, EMBED_STEP_RU)
        r["embedding"] = _embed_run(name, lib_root)
    return r


def trim_blank(args):
    idx = load_index()
    r = _trim(BANK, folder(), LIBRARY, idx, args.id, args.dry_run, REPO, False)
    ceiling = max_upscale()
    rows = ([("left", x) for x in r["left"]] + [("trim", x) for x in r["trim"]]
            + [("under", x) for x in r["under"]])
    out = []
    for kind, x in _by_index(rows, idx):
        if kind == "left":
            out.append(f"left  {x['id']}: {x['en']}")
            continue
        line = (f"{x['id']}: {x['file']} {x['size'][0]}x{x['size'][1]} -> "
                f"{x['trimmed_size'][0]}x{x['trimmed_size'][1]} ({x['phrase']}), "
                f"stretch {x['stretch']:.2f}x of {ceiling}")
        if kind == "under":
            out.append(f"under {line} - over the CF-0392 ceiling once cut: left whole, the "
                       f"user decides whether it stays")
        else:
            out.append(f"trim  {line}" + ("; cutout to redo: meme_desk.py cutout --id "
                                          f"{x['id']}" if x["recut"] else ""))
    print("\n".join(out) or "no still carries a blank band over the threshold")
    if args.dry_run:
        print("(dry run: nothing cut)")
        return
    if r["changed"]:
        print(f"cut {len(r['changed'])}: {', '.join(r['changed'])}; originals in "
              f"{r['originals']}")
        _embed()


def video_source(video, base, local=False, repo=REPO):
    """CF-0760: where the video of an add-gif or a sheet comes from, checked,
    nothing fetched - {will_fetch, video, path, url, cache, cached}.
    A URL (http(s) only, else 'bad_url') is fetched by yt-dlp into the bank's
    cache <bank>/_desk/clips/<sha1(url)>.mp4 (`cached`: already there, no
    download). A local file only with `local=True` and only inside the bank:
    `video` is a name in the bank folder (or an absolute path under it), read
    through bank_media ('outside_bank'); a file that is not there is
    'video_failed'."""
    base = Path(base)
    if local:
        rel = video
        if isinstance(video, (str, os.PathLike)) and Path(video).is_absolute():
            rel = None
            for home in (base, base.resolve()):
                with contextlib.suppress(ValueError):
                    rel = str(Path(os.path.abspath(video)).relative_to(home))
                    break
            if rel is None:
                raise MemeDeskError("outside_bank", f"видео {Path(video).name!r} лежит вне "
                                                    f"банка {base.name} — его не открываю",
                                    f"{video!r} lies outside the bank {base}")
        path = bank_media(base, rel, repo)
        if not path.is_file():
            raise MemeDeskError("video_failed", f"видео {rel} нет в банке {base.name}",
                                f"no video {rel} in the bank {base}")
        return {"will_fetch": "local", "video": str(path), "path": path, "url": None,
                "cache": None, "cached": False}
    check_url(video, "video")
    cache = base / DESK / CLIPS / (hashlib.sha1(video.encode("utf-8")).hexdigest() + ".mp4")
    return {"will_fetch": "yt-dlp", "video": video, "path": None, "url": video,
            "cache": cache, "cached": cache.is_file() and cache.stat().st_size > 0}


def _cli_video(video):
    """The terminal's video: a file the user named, wherever it lies (their
    own terminal), else a URL cached in the CLI's bank (video_source)."""
    if Path(video).is_file():
        return {"will_fetch": "local", "video": str(video), "path": Path(video), "url": None,
                "cache": None, "cached": False}
    return video_source(video, folder(), False)


def _video_file(src):
    """The file of video_source `src`: a local file as is; a URL from the
    bank's cache, fetched into it first (its video track only, 720p at most)
    when it is not there. SystemExit on a failed child (the terminal's way)."""
    if src["path"] is not None:
        return Path(src["path"])
    cache = Path(src["cache"])
    if cache.is_file() and cache.stat().st_size > 0:
        return cache
    ytdlp = str(indexer_ytdlp()) if indexer_ytdlp().exists() else shutil.which("yt-dlp")
    if not ytdlp:
        raise SystemExit("no yt-dlp (expected in the footage-indexer venv)")
    cache.parent.mkdir(parents=True, exist_ok=True)
    part = cache.with_name(cache.stem + ".part.mp4")
    try:
        run([ytdlp, "-q", "--no-warnings", "--no-playlist", "-f",
             "136/232/bv[height<=720][ext=mp4]/bv[height<=720]", "-o", str(part), src["url"]])
        if not part.is_file():
            raise SystemExit(f"yt-dlp wrote no file for {src['url']}")
        part.replace(cache)
    finally:
        if part.exists():
            part.unlink()
    return cache


def scene_cuts(path, start=0.0, end=None):
    cmd = ["ffmpeg", "-v", "error", "-ss", str(start)]
    if end is not None:
        cmd += ["-to", str(end)]
    cmd += ["-i", str(path), "-an", "-vf", "select='gt(scene,0.3)',metadata=print:file=-",
            "-f", "null", "-"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=MEDIA_TIMEOUT_SECONDS).stdout
    except subprocess.TimeoutExpired:
        raise SystemExit(f"ffmpeg scene detection hung: no answer within the "
                         f"{MEDIA_TIMEOUT_SECONDS} s ceiling")
    return [round(start + float(line.split("pts_time:")[1]), 2)
            for line in out.splitlines() if "pts_time:" in line]


def _gif_check(name, base, lib_root, meme_id, video, start, end, description, tags,
               source_url, repo):
    """add-gif's refusals known before anything runs - shared by the add and
    plan_add_gif (CF-0760), `video` a video_source: (start, end, source_url,
    target path in the bank, normalised tags)."""
    try:
        start, end = float(start), float(end)
    except (TypeError, ValueError):
        raise MemeDeskError("bad_span", "start и end — секунды", "--start/--end are seconds")
    if start < 0 or end <= start:
        raise MemeDeskError("bad_span", "end должен быть позже start (и start >= 0)",
                            "--end must be after --start")
    local = video["will_fetch"] == "local"
    source = (source_url or "") if local else video["url"]
    if not isinstance(source, str) or not source.startswith(("http://", "https://")):
        raise MemeDeskError("no_source_url", "для локального видео нужна ссылка — "
                                             "откуда это видео",
                            "a local --video needs --source-url: where the video came from")
    _check_new(lib.load_index(KIND, lib_root, name), meme_id, description)
    tags = _tags_of(tags)
    target = bank_media(base, f"{meme_id}.gif", repo)
    if target.exists() or target.is_symlink():
        raise MemeDeskError("file_exists", f"{target.name} уже лежит в банке",
                            f"{target} already exists")
    return start, end, source, target, tags


def _add_gif(name, base, lib_root, meme_id, video, start, end, description, tags,
             source_url, notes, width, fps, repo, by=None, via=None, progress=None, of=6):
    """add-gif's work on bank folder `base`, `video` a video_source:
    {entry, file, size, duration_s, cuts_inside}. CF-0760: `by`/`via` stamp
    the entry's notes ("add_gif <date> (by …)"); progress ("download", 1,
    of) → ("scenes", 2) → ("cut", 3) → ("check", 4) → ("index", 5)."""
    start, end, source, target, tags = _gif_check(name, base, lib_root, meme_id, video, start,
                                                  end, description, tags, source_url, repo)
    with tempfile.TemporaryDirectory() as tmp:
        _tick(progress, "download", 1, of, _video_says(video))
        with _as_error("video_failed", "видео не получено"):
            src = _video_file(video)
        _tick(progress, "scenes", 2, of, "смены сцен")
        with _as_error("media_failed", "смены сцен не найдены"):
            cuts = scene_cuts(src, start, end)
        inside = [c for c in cuts if start + 0.1 < c < end - 0.1]
        part = Path(tmp) / "out.gif"
        _tick(progress, "cut", 3, of, f"{start:g}-{end:g} с")
        with _as_error("media_failed", "GIF не вырезан"):
            run(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t",
                 str(round(end - start, 3)), "-i", str(src), "-an", "-vf",
                 f"fps={int(fps)},scale={int(width)}:-2:flags=lanczos,split[a][b];"
                 "[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
                 str(part)])
        _tick(progress, "check", 4, of, target.name)
        w, h = _floor(part, repo)
        shutil.move(str(part), target)
    _tick(progress, "index", 5, of, meme_id)
    try:
        entry = _append_entry(name, base, lib_root, meme_id, target.name, source, description,
                              tags, _stamp(notes, "add_gif", by, via),
                              {"clip": {"start_s": round(start, 2), "end_s": round(end, 2)},
                               "cutout": False})
    except MemeDeskError:
        target.unlink()             # the GIF came in with this call; the bank stays as it was
        raise
    return {"entry": entry, "file": target.name, "size": [w, h],
            "duration_s": round(end - start, 2), "cuts_inside": inside}


def _video_says(video):
    """The download step's text: what is fetched, or why nothing is."""
    if video["will_fetch"] == "local":
        return "локальный файл банка"
    return "из кэша банка" if video["cached"] else video["url"]


def add_gif_entry(meme_id, video, start, end, description, tags, source_url=None, notes=None,
                  width=GIF_WIDTH, fps=GIF_FPS, channel=None, bank=None, *, local=False,
                  root=None, repo=REPO, embed=True, by=None, via=None, progress=None):
    """CF-0694: `add-gif` as a function - cuts a silent GIF [start, end] s
    out of `video` (a URL is fetched as its 720p video track by yt-dlp - only
    on the user's word; a local file needs `source_url`, where it came from),
    checks the stretch ceiling, adds it as `review: pending` with its span in
    `clip` and `cutout: false` (a GIF is inserted whole), then embeds the
    bank. Returns {bank, entry, file, size, duration_s, cuts_inside,
    embedding}; `cuts_inside` - scene cuts inside the span (the loop will
    jump; narrow it with make_sheet unless the cut is wanted). Nothing is left
    in the bank when it is refused (MemeDeskError: bad_span, no_source_url,
    bad_entry, duplicate_id, file_exists, video_failed, media_failed,
    over_ceiling, invalid_entry, outside_bank, bad_url, bad_who,
    bad_progress).
    CF-0760: `video` is an http(s) URL (cached in <bank>/_desk/clips/) or,
    with `local=True`, a file inside the bank; `by`/`via` stamp the entry's
    notes ("add_gif <date> (by X, via Y)") and add the row {at, by, via,
    kind: "add_gif", ids: [id]} to <bank>/_desk/jobs.jsonl;
    `progress(step, i, of, text)` - ("download", 1, 6, url | "из кэша банка"
    | "локальный файл банка") → ("scenes", 2, 6) → ("cut", 3, 6) → ("check",
    4, 6) → ("index", 5, 6, id) → ("embedding", 6, 6) (of = 5, no embedding
    step, with embed=False). plan_add_gif() says beforehand, with no network
    and no write, what this call would do."""
    by, via, progress = _who(by, "by"), _who(via, "via"), check_progress(progress)
    name, base, lib_root, _ = _bank_index(channel, bank, root, repo)
    r = _add_gif(name, base, lib_root, meme_id, video_source(video, base, local, repo), start,
                 end, description, tags, source_url, notes, width, fps, repo, by, via, progress,
                 6 if embed else 5)
    _journal(base, "add_gif", [meme_id], by, via)
    r["bank"] = name or lib.KIND_FOLDERS[KIND]
    r["embedding"] = _embed_step(name, lib_root, embed, progress, 6)
    return r


def add_gif(args):
    r = _add_gif(BANK, folder(), LIBRARY, args.id, _cli_video(args.video), args.start, args.end,
                 args.description, args.tags, args.source_url, args.notes, args.width,
                 args.fps, REPO)
    if r["cuts_inside"]:
        print(f"warning: the span crosses a cut at {r['cuts_inside']} s - the loop will jump; "
              f"narrow it with `sheet` unless the cut is wanted")
    w, h = r["size"]
    print(f"added {args.id}: {r['file']} {w}x{h}, {args.end - args.start:.2f} s, review pending")
    _embed()


SHEET_SCRIPT = (
    "import sys,os\nfrom PIL import Image, ImageDraw\n"
    "d,out,t0,step=sys.argv[1],sys.argv[2],float(sys.argv[3]),float(sys.argv[4])\n"
    "fs=sorted(os.listdir(d));im0=Image.open(os.path.join(d,fs[0]));W,H=im0.size;cols=10\n"
    "rows=(len(fs)+cols-1)//cols\n"
    "s=Image.new('RGB',(W*cols,(H+14)*rows),'black');g=ImageDraw.Draw(s)\n"
    "for i,f in enumerate(fs):\n"
    "  x,y=(i%cols)*W,(i//cols)*(H+14);s.paste(Image.open(os.path.join(d,f)),(x,y+14))\n"
    "  g.text((x+3,y+1),f'{t0+i*step:.1f}s',fill='yellow')\n"
    "s.save(out)\n")


def sheet_frames(start, end, every):
    """How many frames a sheet of [start, end] every `every` s holds - None
    while `end` is not known (the video's end; counted after extraction)."""
    if end is None:
        return None
    return max(1, math.ceil((float(end) - float(start or 0)) / float(every) - 1e-9))


def _too_many(n, every):
    more = f"больше {MAX_SHEET_FRAMES}" if n is None else str(n)
    return MemeDeskError("too_many_frames",
                         f"лист кадров вышел бы на {more} кадров (не больше "
                         f"{MAX_SHEET_FRAMES} кадров): сузьте отрезок или увеличьте шаг "
                         f"между кадрами (сейчас {every:g} с)",
                         f"the sheet would hold {more} frames, over the {MAX_SHEET_FRAMES} "
                         f"ceiling: narrow --to or raise --every")


def _sheet(video, start, end, every, out, progress=None):
    """The contact sheet of video_source `video` at file `out` (SystemExit
    on a failed child, the terminal's way; MemeDeskError('too_many_frames')
    past MAX_SHEET_FRAMES): {sheet, scene_cuts}. CF-0760: progress
    ("download", 1, 3) → ("frames", 2, 3) → ("sheet", 3, 3)."""
    n = sheet_frames(start, end, every)
    if n is not None and n > MAX_SHEET_FRAMES:
        raise _too_many(n, every)
    with tempfile.TemporaryDirectory() as tmp:
        _tick(progress, "download", 1, 3, _video_says(video))
        src = _video_file(video)
        _tick(progress, "frames", 2, 3, "кадры" if n is None else f"{n} кадров")
        frames = Path(tmp) / "f"
        frames.mkdir()
        cmd = ["ffmpeg", "-v", "error", "-y"]
        if start:
            cmd += ["-ss", str(start)]
        if end:
            cmd += ["-to", str(end)]
        # a known span was counted above (the cap only drops fps's rounding
        # frame); an open one is cut at one frame past the ceiling and refused
        cap = MAX_SHEET_FRAMES if n is not None else MAX_SHEET_FRAMES + 1
        cmd += ["-i", str(src), "-vf", f"fps=1/{every},scale=240:-2",
                "-frames:v", str(cap), str(frames / "%04d.jpg")]
        run(cmd)
        if len(list(frames.iterdir())) > MAX_SHEET_FRAMES:
            raise _too_many(None, every)
        _tick(progress, "sheet", 3, 3, "склейка листа и смены сцен")
        out = Path(out).resolve()
        py = str(indexer_python()) if indexer_python().exists() else sys.executable
        run([py, "-c", SHEET_SCRIPT, str(frames), str(out), str(start or 0), str(every)])
        return {"sheet": str(out), "scene_cuts": scene_cuts(src, start or 0, end)}


SHEETS = "sheets"                  # <bank>/_desk/sheets/: where make_sheet writes


def _sheet_check(base, video, start, end, every, out, local, repo):
    """make_sheet's refusals known before anything runs - shared with
    plan_sheet (CF-0760): (start, end, every, frames | None, target,
    video_source)."""
    try:
        start = float(start or 0)
        end = None if end is None else float(end)
        every = float(every)
    except (TypeError, ValueError):
        raise MemeDeskError("bad_span", "start, end и every — секунды")
    if start < 0 or every <= 0 or (end is not None and end <= start):
        raise MemeDeskError("bad_span", "нужны start >= 0, every > 0 и end позже start")
    folder_ = Path(base) / DESK / SHEETS
    target = bank_media(folder_, out or "sheet.jpg", repo)
    if Path(target).suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        raise MemeDeskError("bad_suffix", "лист кадров — .jpg или .png")
    n = sheet_frames(start, end, every)
    if n is not None and n > MAX_SHEET_FRAMES:
        raise _too_many(n, every)
    return start, end, every, n, target, video_source(video, base, local, repo)


def make_sheet(video, start=0.0, end=None, every=2.0, out=None, *, channel=None, bank=None,
               local=False, root=None, repo=REPO, progress=None):
    """CF-0694: `sheet` as a function - a timestamped contact sheet of
    `video` (a URL is fetched by yt-dlp - only on the user's word) one frame
    every `every` s over [start, end], and the scene cuts in that span, to
    find the moment a GIF is cut from. Written inside the bank only:
    `out` is a file name under <bank>/_desk/sheets/ (default sheet.jpg); an
    absolute path or `..` is MemeDeskError('outside_bank'). Returns {sheet
    (absolute path), scene_cuts [s]}. Other refusals: bad_span, bad_suffix,
    video_failed (no yt-dlp, the fetch or a child failed or hung), bad_url,
    too_many_frames, bad_progress.
    CF-0760: `video` is an http(s) URL (cached in <bank>/_desk/clips/, one
    URL fetched once for the sheet and the GIF) or, with `local=True`, a file
    inside the bank; more than MAX_SHEET_FRAMES (300) frames is
    too_many_frames - before the fetch when `end` is given, after the frames
    are taken when it is not; `progress(step, i, of, text)` - ("download",
    1, 3) → ("frames", 2, 3) → ("sheet", 3, 3). plan_sheet() says
    beforehand, with no network and no write, what this call would do."""
    progress = check_progress(progress)
    _, base, _, _ = _bank_index(channel, bank, root, repo)
    start, end, every, _, target, src = _sheet_check(base, video, start, end, every, out, local,
                                                     repo)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _as_error("video_failed", "лист кадров не сделан"):
        return _sheet(src, start, end, every, target, progress)


# --------------------------------------------------------------------------
# the plans of the adds and the sheet (CF-0760): what a job would do, said
# before it runs - no network, no child, no write
# --------------------------------------------------------------------------
#
# `max_seconds` is the job's worst-case wall time: the sum of the ceilings of
# every child the job would run (tests/test_timeouts.py, CF-0229) - the
# fetch (FETCH_TIMEOUT_SECONDS for a still, MEDIA_TIMEOUT_SECONDS for
# yt-dlp; nothing for a local file or a cached video), each media child
# (ffmpeg: MEDIA_TIMEOUT_SECONDS), each probe (ffprobe, and the git lookup of
# a venv from a worktree: PROBE_TIMEOUT_SECONDS) and the embedding
# (EMBED_TIMEOUT_SECONDS). The pure-Python work between the children (the
# band measure, the index write) is not counted - it takes seconds. A job
# that has not ended after max_seconds is hung, not slow.


def _plan_seconds(*parts):
    return int(sum(parts))


def _fetch_video_seconds(src):
    """The download step of a video: the yt-dlp lookup and fetch, or 0."""
    if src["will_fetch"] == "local" or src["cached"]:
        return 0
    return PROBE_TIMEOUT_SECONDS + MEDIA_TIMEOUT_SECONDS


def _embed_seconds(embed):
    return PROBE_TIMEOUT_SECONDS + EMBED_TIMEOUT_SECONDS if embed else 0


def plan_add_image(meme_id, url, source_url, description, tags, notes=None, channel=None,
                   bank=None, *, root=None, repo=REPO, embed=True, by=None, via=None,
                   progress=None):
    """CF-0760: what add_image_entry() with the same arguments would do - its
    refusals (same codes, raised here), nothing downloaded, nothing written.
    Returns {bank, id, file, will_fetch: "url", url, video: None,
    source_url, span: None, tags (normalised), steps, max_seconds}; `steps`
    are the progress steps the add will report, `max_seconds` its worst-case
    wall time (the fetch, ffprobe, the embedding - see above)."""
    _who(by, "by"), _who(via, "via"), check_progress(progress)
    name, base, lib_root, _ = _bank_index(channel, bank, root, repo)
    target, tags = _image_check(name, base, lib_root, meme_id, url, source_url, description,
                                tags, repo)
    return {"bank": name or lib.KIND_FOLDERS[KIND], "id": meme_id, "file": target.name,
            "will_fetch": "url", "url": url, "video": None, "source_url": source_url,
            "span": None, "tags": tags,
            "steps": ["download", "check", "index"] + (["embedding"] if embed else []),
            "max_seconds": _plan_seconds(FETCH_TIMEOUT_SECONDS, PROBE_TIMEOUT_SECONDS,
                                         _embed_seconds(embed))}


def plan_add_gif(meme_id, video, start, end, description, tags, source_url=None, notes=None,
                 width=GIF_WIDTH, fps=GIF_FPS, channel=None, bank=None, *, local=False,
                 root=None, repo=REPO, embed=True, by=None, via=None, progress=None):
    """CF-0760: what add_gif_entry() with the same arguments would do - its
    refusals (same codes, raised here), nothing fetched, no child, nothing
    written. Returns {bank, id, file, will_fetch: "yt-dlp" | "local", url
    (the URL or None), video (the URL or the bank file's path), cached (a
    URL already in <bank>/_desk/clips/ - no download), source_url, span
    {start_s, end_s}, tags (normalised), steps, max_seconds}; `max_seconds`
    - the fetch (0 local or cached), scene detection, the cut, ffprobe, the
    embedding."""
    _who(by, "by"), _who(via, "via"), check_progress(progress)
    name, base, lib_root, _ = _bank_index(channel, bank, root, repo)
    src = video_source(video, base, local, repo)
    start, end, source, target, tags = _gif_check(name, base, lib_root, meme_id, src, start,
                                                  end, description, tags, source_url, repo)
    return {"bank": name or lib.KIND_FOLDERS[KIND], "id": meme_id, "file": target.name,
            "will_fetch": src["will_fetch"], "url": src["url"], "video": src["video"],
            "cached": src["cached"], "source_url": source,
            "span": {"start_s": round(start, 2), "end_s": round(end, 2)}, "tags": tags,
            "steps": ["download", "scenes", "cut", "check", "index"]
            + (["embedding"] if embed else []),
            "max_seconds": _plan_seconds(_fetch_video_seconds(src), MEDIA_TIMEOUT_SECONDS,
                                         MEDIA_TIMEOUT_SECONDS, PROBE_TIMEOUT_SECONDS,
                                         _embed_seconds(embed))}


def plan_sheet(video, start=0.0, end=None, every=2.0, out=None, *, channel=None, bank=None,
               local=False, root=None, repo=REPO, progress=None):
    """CF-0760: what make_sheet() with the same arguments would do - its
    refusals known beforehand (same codes: bad_span, bad_suffix,
    outside_bank, bad_url, video_failed for a local file not there,
    too_many_frames when `end` is given), nothing fetched, nothing written
    (not even _desk/sheets/). Returns {bank, id: None, file (bank-relative,
    _desk/sheets/<out>), sheet (its absolute path), will_fetch, url, video,
    cached, source_url (the URL or None), span {start_s, end_s | None,
    every_s, frames | None}, tags: None, steps, max_seconds}; `frames` None
    while the end is the video's (counted after extraction); `max_seconds` -
    the fetch, the frames, the sheet script (with its venv lookup), scene
    detection."""
    check_progress(progress)
    name, base, _, _ = _bank_index(channel, bank, root, repo)
    start, end, every, n, target, src = _sheet_check(base, video, start, end, every, out,
                                                     local, repo)
    return {"bank": name or lib.KIND_FOLDERS[KIND], "id": None,
            "file": str(Path(target).relative_to(Path(base))),
            "sheet": str(Path(target).resolve()), "will_fetch": src["will_fetch"],
            "url": src["url"], "video": src["video"], "cached": src["cached"],
            "source_url": src["url"],
            "span": {"start_s": start, "end_s": end, "every_s": every, "frames": n},
            "tags": None, "steps": ["download", "frames", "sheet"],
            "max_seconds": _plan_seconds(_fetch_video_seconds(src), MEDIA_TIMEOUT_SECONDS,
                                         PROBE_TIMEOUT_SECONDS, MEDIA_TIMEOUT_SECONDS,
                                         MEDIA_TIMEOUT_SECONDS)}


def sheet(args):
    r = _sheet(_cli_video(args.video), args.start, args.end, args.every, args.out)
    print(f"sheet: {r['sheet']}")
    print(f"scene cuts (s): {r['scene_cuts']}")


# --------------------------------------------------------------------------
# the cutout (CF-0403)
# --------------------------------------------------------------------------
#
# A meme the user ticked «можно вырезать» (`cutout: true`) gets its foreground
# cut out once, here, as library preparation - `<id>.cutout.png` beside the
# source, RGBA, cropped to the silhouette - and the result recorded on the
# entry as `cutout_asset` (schema in shared/inserts/inserts_lib.py). Where the
# cut is placed in a frame is the editor's business (CF-0404), not the desk's.
#
# The cut is macOS Vision's foreground instance mask, computed by
# scripts/meme_cutout_vision.py under Video Editor's venv (the factory's one
# interpreter with pyobjc Vision). Local, no network. The judgement of the
# cut is here, in plain Python on the downsampled mask the helper returns, so
# it is testable without Vision. A refused cut is recorded with its reason
# and no file: the meme stays whole, the block is never lost.

CUTOUT_METHOD = "vision-foreground-instance-mask/1"
# The thresholds were set on the 8 `cutout: true` memes and 3 others of the
# library on 2026-09-27 (Vision on macOS 26): every real cut had coverage
# 0.24-0.56, at most 2 blobs, majority-filter noise 0.01-0.074 and soft edge
# 0.02-0.13; the same masks with a quarter of their edge cells flipped scored
# noise 0.22-0.31.
CUT_MIN_COVERAGE = 0.02      # below: Vision found no subject - "empty mask"
CUT_MAX_COVERAGE = 0.90      # above: nothing was cut away - the whole frame
CUT_MAX_PARTS = 4            # blobs of >= CUT_PART_SHARE of the silhouette
CUT_PART_SHARE = 0.01
CUT_MAX_NOISE = 0.15         # cells the 3x3 majority filter flips, per edge cell
CUT_MAX_SOFT = 0.35          # silhouette pixels Vision was unsure of (0.1<a<0.9)


def cutout_file(entry):
    return f"{entry['id']}.cutout.png"


def sha256_file(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _blobs(grid):
    """Sizes of the 4-connected foreground blobs of a '0'/'1' grid, largest first."""
    h, w = len(grid), len(grid[0]) if grid else 0
    seen = [[False] * w for _ in range(h)]
    sizes = []
    for y in range(h):
        for x in range(w):
            if grid[y][x] != "1" or seen[y][x]:
                continue
            seen[y][x] = True
            stack, n = [(y, x)], 0
            while stack:
                cy, cx = stack.pop()
                n += 1
                for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                    if 0 <= ny < h and 0 <= nx < w and not seen[ny][nx] and grid[ny][nx] == "1":
                        seen[ny][nx] = True
                        stack.append((ny, nx))
            sizes.append(n)
    return sorted(sizes, reverse=True)


def _edge_noise(grid):
    """How ragged the contour is: cells a 3x3 majority filter would flip, per
    foreground/background edge inside the grid. The frame border is not an
    edge - a person cut off by the picture's bottom is not torn. A smooth
    contour flips a few cells at its corners; a torn one flips a quarter."""
    h, w = len(grid), len(grid[0]) if grid else 0
    edges = flips = 0
    for y in range(h):
        for x in range(w):
            on = grid[y][x] == "1"
            n = t = 0
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    yy, xx = y + dy, x + dx
                    if 0 <= yy < h and 0 <= xx < w:
                        n += 1
                        t += grid[yy][xx] == "1"
                        if on and abs(dy) + abs(dx) == 1 and grid[yy][xx] != "1":
                            edges += 1
            if (t * 2 > n) != on:
                flips += 1
    return flips / edges if edges else 0.0


def judge_cutout(rec):
    """(None, measures) for a cut the factory may use, (reason, measures) for
    one it refuses. `rec` is scripts/meme_cutout_vision.py's JSON."""
    grid = rec.get("grid") or []
    parts = _blobs(grid) if grid else []
    total = sum(parts)
    big = [p for p in parts if total and p >= CUT_PART_SHARE * total]
    m = {"coverage": rec.get("coverage", 0.0), "parts": len(big),
         "edge_noise": round(_edge_noise(grid), 4) if total else 0.0,
         "soft": rec.get("soft", 0.0)}
    if not rec.get("bbox") or m["coverage"] < CUT_MIN_COVERAGE:
        return (f"empty mask: Vision found no subject (silhouette covers "
                f"{m['coverage']:.1%} of the frame, floor {CUT_MIN_COVERAGE:.0%})"), m
    if m["coverage"] > CUT_MAX_COVERAGE:
        return (f"nothing was cut: the silhouette covers {m['coverage']:.1%} of the "
                f"frame (ceiling {CUT_MAX_COVERAGE:.0%})"), m
    if m["parts"] > CUT_MAX_PARTS:
        return (f"fragmented: {m['parts']} separate pieces of >= {CUT_PART_SHARE:.0%} "
                f"of the silhouette (at most {CUT_MAX_PARTS})"), m
    if m["edge_noise"] > CUT_MAX_NOISE:
        return (f"ragged edge: majority-filter noise {m['edge_noise']:.3f} per edge "
                f"cell (ceiling {CUT_MAX_NOISE})"), m
    if m["soft"] > CUT_MAX_SOFT:
        return (f"unsure mask: {m['soft']:.0%} of the silhouette is half-transparent "
                f"(ceiling {CUT_MAX_SOFT:.0%})"), m
    return None, m


CUT_FILE_MISSING = "file missing - run meme_desk.py cutout"


def _pct(x, fmt=".1%"):
    return format(x, fmt) if isinstance(x, (int, float)) else "?"


def cutout_refused_ru(rec):
    """CF-0762: why a cut was refused, in the user's words - from the
    `cutout_asset` record (its English `refused` plus the measures
    judge_cutout put beside it). The record keeps the English line."""
    r = (rec or {}).get("refused") or ""
    rec = rec or {}
    if not r:
        return "файла вырезки нет — вырезку нужно запустить заново"
    if r.startswith("empty mask"):
        return (f"пустая маска: распознавание не нашло фигуру (силуэт занимает "
                f"{_pct(rec.get('coverage'))} кадра, нужно не меньше {CUT_MIN_COVERAGE:.0%})")
    if r.startswith("nothing was cut"):
        return (f"вырезать нечего: силуэт занимает {_pct(rec.get('coverage'))} кадра "
                f"(допустимо до {CUT_MAX_COVERAGE:.0%})")
    if r.startswith("fragmented"):
        return (f"фигура распалась на {rec.get('parts', '?')} крупных кусков "
                f"(допустимо не больше {CUT_MAX_PARTS})")
    if r.startswith("ragged edge"):
        noise = rec.get("edge_noise")
        noise = f"{noise:.3f}" if isinstance(noise, (int, float)) else "?"
        return f"рваный край силуэта (шум {noise}, допустимо до {CUT_MAX_NOISE})"
    if r.startswith("unsure mask"):
        return (f"нечёткая маска: {_pct(rec.get('soft'), '.0%')} силуэта полупрозрачны "
                f"(допустимо до {CUT_MAX_SOFT:.0%})")
    if r.startswith("Vision failed"):
        return "распознавание фигуры не сработало на этом файле"
    return r            # not a refusal judge_cutout words: shown as recorded


def venv_path(rel, repo=None):
    """`<checkout>/<rel>` of a venv file (CF-0760): the checkout's own when it
    is there, else the main checkout's - a worktree (.worktrees/*) has no
    venv of its own (CF-0125), and `git rev-parse --git-common-dir` names the
    main checkout's .git. The checkout's own path when git cannot say."""
    repo = Path(repo) if repo is not None else REPO
    own = repo / rel
    if own.exists():
        return own
    try:
        r = git_read.run(["rev-parse", "--path-format=absolute", "--git-common-dir"],
                         cwd=repo, capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS)
    except (subprocess.TimeoutExpired, OSError):
        return own
    main = Path(r.stdout.strip()).parent if r.returncode == 0 and r.stdout.strip() else repo
    return main / rel


def _venv_of(path):
    path = Path(path)
    if path.exists():
        return path
    try:
        return venv_path(path.relative_to(REPO))
    except ValueError:              # a test's own path: as it is
        return path


def indexer_python():
    """The footage-indexer venv's python (torch, Pillow) - embedding and the
    contact sheet; venv_path, so a worktree finds the main checkout's."""
    return _venv_of(VENV_PY)


def indexer_ytdlp():
    """The footage-indexer venv's yt-dlp, looked up as indexer_python()."""
    return _venv_of(VENV_YTDLP)


def vision_python():
    """Video Editor's venv python - the one with pyobjc Vision. A worktree
    has no venv of its own (CF-0125), so the main checkout's is looked up
    too (venv_path); MEME_VISION_PY overrides both."""
    env = os.environ.get("MEME_VISION_PY")
    if env:
        return Path(env)
    return venv_path(Path("agents") / "video-editor" / ".venv" / "bin" / "python")


def _platform():
    """(sys.platform, macOS version or "") of this machine - the one place the
    cutout asks which OS it is on (CF-0654 layer); tests replace it."""
    import platform  # noqa: PLC0415
    return sys.platform, (platform.mac_ver()[0] if sys.platform == "darwin" else "")


VISION_HELPER = REPO / "scripts" / "meme_cutout_vision.py"
CUT_ONLY_MAC_RU = "вырезка мемов работает только на macOS 14+ (распознавание фигур macOS Vision)"


def _cutout_check():
    """(ok, text, en) of cutout_available: the reason in Russian and the
    terminal's English line."""
    plat, ver = _platform()
    if plat != "darwin":
        return (False, f"{CUT_ONLY_MAC_RU}, а здесь {plat}",
                f"the cutout is macOS Vision (macOS 14+); this is {plat} "
                f"(CF-0654, the replacement is rembg)")
    try:
        major = int((ver or "0").split(".")[0])
    except ValueError:
        major = 0
    if major < 14:
        return (False, f"{CUT_ONLY_MAC_RU}, а здесь macOS {ver or '?'}",
                f"the cutout needs macOS 14+ (VNGenerateForegroundInstanceMaskRequest); "
                f"this is macOS {ver or '?'}")
    py = vision_python()
    if not py.exists():
        return (False, "не найдена среда видеомонтажа с распознаванием фигур — установите "
                       "окружение видеоредактора фабрики",
                f"no {py}: the cutout needs Video Editor's venv (pyobjc Vision)")
    if not VISION_HELPER.exists():
        return (False, "в этой копии фабрики нет программы вырезки фона — обновите фабрику",
                f"no {VISION_HELPER}")
    return True, f"macOS {ver}, распознавание фигур готово", f"macOS {ver}, {py}"


def cutout_available():
    """CF-0694: (True, what it runs on) when this machine can cut a meme out -
    macOS 14+ with Video Editor's venv (pyobjc Vision) and
    scripts/meme_cutout_vision.py - else (False, why, in Russian). The
    cutout's macOS dependency sits behind this one check (CF-0654): on
    another OS the center shows the reason instead of a broken button."""
    ok, text, _ = _cutout_check()
    return ok, text


def run_vision(src, out_png):
    """scripts/meme_cutout_vision.py's JSON for one file. Tests replace this.
    A machine that cannot cut (cutout_available) is MemeDeskError
    ('cutout_unavailable') before anything is started."""
    ok, text, en = _cutout_check()
    if not ok:
        raise MemeDeskError("cutout_unavailable", text, en)
    py = vision_python()
    r = subprocess.run([str(py), str(VISION_HELPER), str(src), str(out_png)],
                       capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[-400:] or f"exit {r.returncode}")
    return json.loads(r.stdout)


def cutout_is_current(entry, digest, base):
    """True when the recorded cut is of this very source by this very method
    and, if it was accepted, its file is still there - nothing to redo."""
    a = entry.get("cutout_asset")
    if not isinstance(a, dict) or a.get("source_sha256") != digest or a.get("method") != CUTOUT_METHOD:
        return False
    return a.get("file") is None or (base / a["file"]).exists()


def cut_one(entry, base, today=None):
    """The `cutout_asset` record for one entry, writing `<id>.cutout.png` into
    `base` when the cut is accepted and removing a stale one when refused.
    CF-0760: whatever Vision's run throws (a hang past its 180 s ceiling,
    JSON that does not parse, a record without its keys) is a refused cut,
    not an end of the pass; only 'cutout_unavailable' goes up."""
    src = base / entry["file"]
    digest = sha256_file(src)
    target = base / cutout_file(entry)
    tmp = target.with_name(target.name + ".part.png")
    rec = {"file": None, "source_sha256": digest, "method": CUTOUT_METHOD,
           "made": today or datetime.date.today().isoformat()}
    try:
        try:
            v = run_vision(src, tmp)
            reason, m = judge_cutout(v)
            size = list(v["size"])
            bbox = list(v["bbox"]) if reason is None else None
        except MemeDeskError:
            raise
        except Exception as e:                              # noqa: BLE001
            what = str(e) if isinstance(e, RuntimeError) else f"{type(e).__name__}: {e}"
            rec.update({"refused": f"Vision failed: {what}"[:400], "coverage": 0.0})
            reason = rec["refused"]
        else:
            rec["source_size_px"] = size
            rec.update(m)
            if reason is None:
                rec["file"] = target.name
                rec["bbox_px"] = bbox
                tmp.replace(target)
            else:
                rec["refused"] = reason
        if reason is not None and target.exists():
            target.unlink()
    finally:
        if tmp.exists():
            tmp.unlink()
    return rec


def _ids_of(ids):
    if ids is None:
        return None
    if isinstance(ids, str):
        return [ids]
    if not isinstance(ids, (list, tuple, set)) or not all(isinstance(i, str) for i in ids):
        raise MemeDeskError("bad_ids", "ids — список id мемов")
    return list(ids)


def _cutout(name, base, lib_root, idx, ids, force, dry_run, repo, links, by=None, via=None,
            progress=None, journal=False):
    """The one pass of the cutout over bank folder `base` (index `idx`):
    cutout_entries' result, index.json written unless dry_run or nothing was
    cut or refused. Only `cutout: true` stills - the flag is the user's
    (the desk's «можно вырезать»), never set here; a GIF is never cut.
    CF-0760: a file that fails in the middle is refused and the pass goes on;
    the records are written into index.json read afresh (_write_by_id) even
    when the pass breaks off; an entry gone meanwhile loses its new cut file
    and is MemeDeskError('index_changed')."""
    todo = [e for e in idx["entries"] if e.get("cutout") is True
            and not e["file"].lower().endswith(".gif")]
    if ids is not None:
        known = {e["id"]: e for e in idx["entries"]}
        for i in ids:
            if i not in known:
                raise MemeDeskError("unknown_id", f"мема {i!r} нет в банке",
                                    f"{i}: no such entry with cutout: true")
            e = known[i]
            if e["file"].lower().endswith(".gif"):
                raise MemeDeskError("not_cutout", f"{i} — GIF, GIF не вырезается (вставляется целым)",
                                    f"{i}: no such entry with cutout: true")
            if e.get("cutout") is not True:
                raise MemeDeskError("not_cutout", f"у {i} нет отметки «можно вырезать» "
                                                  f"— её ставит только пользователь",
                                    f"{i}: no such entry with cutout: true")
        todo = [e for e in todo if e["id"] in ids]
    made, refused, same, missing, outside = [], [], [], [], []
    changes, files = {}, {}
    _tick(progress, "cutout", 0, len(todo), "")
    broke = None
    try:
        for i, e in enumerate(todo, 1):
            try:
                rec = _cut_entry(e, base, repo, links, force, dry_run, made, same, missing,
                                 outside)
            except MemeDeskError:
                raise
            except Exception as ex:                         # noqa: BLE001  CF-0760
                refused.append({"id": e["id"], "reason": "сбой на файле — мем не вырезан",
                                "en": f"{type(ex).__name__}: {ex}"[:400]})
                rec = None
            if rec is not None:
                if rec["file"]:
                    made.append({"id": e["id"], "file": rec["file"], "bbox_px": rec["bbox_px"],
                                 "coverage": rec["coverage"]})
                    files[e["id"]] = Path(base) / rec["file"]
                else:
                    refused.append({"id": e["id"], "reason": cutout_refused_ru(rec),
                                    "en": rec["refused"]})

                def write(entry, rec=rec):
                    entry["cutout_asset"] = rec
                    entry["notes"] = _stamp(entry.get("notes"), "cutout", by, via)
                    if not entry["notes"]:
                        entry.pop("notes")
                changes[e["id"]] = write
            _tick(progress, "cutout", i, len(todo), e["id"])
    except BaseException as ex:                             # noqa: BLE001
        broke = ex
    written, gone = False, []
    if changes:
        written, gone = _write_by_id(name, lib_root, changes)
        for i in gone:                                      # its cut belongs to no entry now
            if i in files and files[i].exists():
                files[i].unlink()
        if written and journal:
            _journal(base, "cutout", [i for i in changes if i not in gone], by, via)
    if broke is not None:
        raise broke
    if gone:
        raise _index_changed(gone, "вырезка")
    return {"bank": name or lib.KIND_FOLDERS[KIND], "dry_run": bool(dry_run),
            "made": made, "refused": refused, "unchanged": same, "missing": missing,
            "outside_bank": outside, "written": written}


def _cut_entry(e, base, repo, links, force, dry_run, made, same, missing, outside):
    """_cutout's work on one entry: its cutout_asset record, or None when
    there is nothing to record (outside the bank, missing, unchanged, dry run
    - those rows are added here)."""
    try:
        src = bank_media(base, e["file"], repo, links=links)
        bank_media(base, cutout_file(e), repo, links=links)
    except MemeDeskError as ex:                             # CF-0697: never cut
        outside.append({"id": e["id"], "reason": ex.text, "en": ex.en})
        missing.append(e["id"])
        return None
    if not src.exists():
        missing.append(e["id"])
        return None
    if not force and cutout_is_current(e, sha256_file(src), base):
        same.append(e["id"])
        return None
    if dry_run:
        made.append({"id": e["id"], "file": cutout_file(e), "bbox_px": None, "coverage": None})
        return None
    return cut_one(e, base)


def cutout_entries(channel=None, ids=None, force=False, dry_run=False, *, bank=None,
                   root=None, repo=REPO, by=None, via=None, progress=None):
    """CF-0694: `cutout` as a function. Cuts the foreground of every
    `cutout: true` still of the bank (or of `ids`, each of which must be one)
    into <id>.cutout.png beside it and records `cutout_asset`; unchanged
    sources are skipped unless `force`. Never sets `cutout` and never cuts a
    GIF: an id without the user's tick or a GIF is MemeDeskError('not_cutout').
    Returns `made` [{id, file, bbox_px, coverage}] (with dry_run: what would
    be cut, bbox_px/coverage None), `refused` [{id, reason}] (recorded, no
    file - the meme stays whole; CF-0760: a file whose run crashed too),
    `unchanged` [id], `missing` [id] (no source file, or one outside the bank
    - `outside_bank` [{id, reason}]), `written`.
    A machine that cannot cut is MemeDeskError('cutout_unavailable') -
    cutout_available() says so beforehand. Media only through bank_media.
    CF-0760: `by`/`via` (bad_who) stamp the entries' notes and the run's row
    in <bank>/_desk/jobs.jsonl {at, by, via, kind: "cutout", ids};
    `progress(step, i, of, text)` - ("cutout", i, N, id) per still; an entry
    removed from index.json during the pass is MemeDeskError('index_changed')
    (the rest is written)."""
    by, via, progress = _who(by, "by"), _who(via, "via"), check_progress(progress)
    name, base, lib_root, idx = _bank_index(channel, bank, root, repo)
    return _cutout(name, base, lib_root, idx, _ids_of(ids), force, dry_run, repo, True, by,
                   via, progress, True)


def _by_index(items, idx):
    pos = {e["id"]: n for n, e in enumerate(idx["entries"])}
    return sorted(items, key=lambda kv: pos.get(kv[1]["id"], len(pos)))


def cutout(args):
    idx = load_index()
    r = _cutout(BANK, folder(), LIBRARY, idx, [args.id] if args.id else None,
                args.force, args.dry_run, REPO, False)
    rows = ([("outside", x) for x in r["outside_bank"]]
            + ([] if args.dry_run else [("made", x) for x in r["made"]])
            + [("refused", x) for x in r["refused"]])
    for kind, x in _by_index(rows, idx):
        if kind == "outside":
            print(f"{x['id']}: {x['en']}")
        elif kind == "made":
            print(f"{x['id']}: {x['file']} {x['bbox_px'][2]}x{x['bbox_px'][3]} px, "
                  f"silhouette {x['coverage']:.1%} of the frame")
        else:
            print(f"{x['id']}: refused - {x['reason']}; the meme stays whole")
    made = [x["id"] for x in r["made"]]
    refused = [x["id"] for x in r["refused"]]
    verb = "would cut" if args.dry_run else "cut"
    print(f"{verb} {len(made)}: {', '.join(made) or '-'}")
    print(f"refused {len(refused)}: {', '.join(refused) or '-'}")
    print(f"unchanged {len(r['unchanged'])}: {_short(r['unchanged'])}")
    if r["missing"]:
        print(f"source file missing (fetch it first) {len(r['missing'])}: "
              f"{', '.join(r['missing'])}")
    if not r["written"]:
        print("nothing written")
        return
    print("index.json written; run the insert tests before committing")


# --------------------------------------------------------------------------
# CF-0393: the bank's candidate list
# --------------------------------------------------------------------------

CANDIDATE_KEYS = ("id", "name", "imgflip_id", "url", "width", "height",
                  "passes_ceiling", "blank_band", "intents", "use")


def load_candidates():
    path = folder() / CANDIDATES
    if not path.exists():
        raise SystemExit(f"no {path} - this bank has no candidate list")
    return json.loads(path.read_text())


def candidate_problems(data, box=None, ceiling=None, vocabulary=None):
    """What is wrong with a candidates.json: its shape, and any
    `passes_ceiling` that disagrees with the stretch the editor would apply
    (inserts/meme.json asset_floor) - the list is checked, not trusted."""
    box = tuple(box or fit_box())
    ceiling = ceiling if ceiling is not None else max_upscale()
    if vocabulary is None:
        spec = json.loads((REPO / "inserts" / "meme.json").read_text())
        vocabulary = set(spec["selection"]["intent_vocabulary"])
    probs = []
    if not isinstance(data, dict) or not isinstance(data.get("candidates"), list):
        return ["candidates.json must be an object with a `candidates` list"]
    seen = set()
    for i, c in enumerate(data["candidates"]):
        ctx = f"candidates[{i}]"
        if not isinstance(c, dict):
            probs.append(f"{ctx}: not an object")
            continue
        ctx = f"{ctx} {c.get('id', '?')}"
        missing = [k for k in CANDIDATE_KEYS if k not in c]
        if missing:
            probs.append(f"{ctx}: missing {missing}")
            continue
        if not isinstance(c["id"], str) or not lib.ID_RE.match(c["id"]) or c["id"] in seen:
            probs.append(f"{ctx}: id must be a unique [a-z0-9_-] slug")
        seen.add(c["id"])
        w, h = c["width"], c["height"]
        if w is None or h is None:
            if c["passes_ceiling"] is not None:
                probs.append(f"{ctx}: no size known, so passes_ceiling must be null")
        else:
            ok = upscale_factor((w, h), box) <= ceiling + 1e-9
            if c["passes_ceiling"] is not ok:
                probs.append(f"{ctx}: passes_ceiling is {c['passes_ceiling']}, but {w}x{h} "
                             f"is stretched {upscale_factor((w, h), box):.2f}x (ceiling {ceiling})")
        if c["url"] is not None and not str(c["url"]).startswith("https://i.imgflip.com/"):
            probs.append(f"{ctx}: url must be an Imgflip template file (i.imgflip.com) or null")
        bad = [x for x in c["intents"] or [] if x not in vocabulary]
        if bad:
            probs.append(f"{ctx}: intents {bad} are not in inserts/meme.json intent_vocabulary")
        if not str(c["use"]).strip():
            probs.append(f"{ctx}: `use` - when a video uses it - is empty")
    return probs


def candidates(args):
    """The bank's list for the user's yes: one line per template, the ones
    that fail the stretch ceiling apart, and the total download size."""
    data = load_candidates()
    probs = candidate_problems(data)
    box, ceiling = fit_box(), max_upscale()
    rows = data["candidates"]
    passing = [c for c in rows if c.get("passes_ceiling") is True]
    failing = [c for c in rows if c.get("passes_ceiling") is False]
    unknown = [c for c in rows if c.get("passes_ceiling") is None]
    print(f"bank {BANK or lib.KIND_FOLDERS[KIND]}: {len(rows)} candidates - "
          f"{len(passing)} pass the {ceiling}x ceiling into {box[0]}x{box[1]}, "
          f"{len(failing)} fail it, {len(unknown)} without template data")
    for title, group in (("pass", passing), ("fail - a GIF or a clip instead", failing),
                         ("no template data", unknown)):
        if not group:
            continue
        print(f"-- {title}")
        for c in group:
            size = (f"{c['width']}x{c['height']} "
                    f"{upscale_factor((c['width'], c['height']), box):.2f}x"
                    if c.get("width") else "size ?")
            kb = f"{c['bytes'] / 1024:.0f} KB" if c.get("bytes") else "? KB"
            print(f"  {c['id']:<34} {size:<18} {kb:>8}  {', '.join(c['intents'])}")
    fetch = [c for c in passing if not c.get("in_reel_bank")]
    copy = [c for c in passing if c.get("in_reel_bank")]
    mb = lambda group: sum(c.get("bytes") or 0 for c in group) / 1024 / 1024  # noqa: E731
    print(f"download for the passing ones: {len(fetch)} files, {mb(fetch):.2f} MB; "
          f"already in the default bank (copied on disk, no download): {len(copy)} files, "
          f"{mb(copy):.2f} MB")
    tail = (data.get("reel_tail") or {}).get("candidates") or []
    if tail:
        print(f"for the default bank (CF-0381 tail): {', '.join(c['id'] for c in tail)}")
    for p in probs:
        print("problem: " + p)
    if probs:
        raise SystemExit(1)


# --------------------------------------------------------------------------
# CF-0725: accepting the bank's candidates from the command center. Only a
# candidate whose file already lies in the bank (downloaded on an earlier yes,
# or copied from the default bank on the disk) is taken in; nothing is ever
# downloaded here - a download is add_image_entry's, on its own yes. The user
# types the answer; the plan's fingerprint ties it to the list they saw.
# --------------------------------------------------------------------------

ACCEPT_JOURNAL = "candidates_accepted.jsonl"    # in <bank>/_desk/, untracked like the draft
WHO_MAX = 40                                    # `by` / `via`: the shape of CF-0720's
ACCEPT_WORDS = ("да", "yes")
REFUSE_WORDS = ("нет", "no")


def _who(value, what):
    """`by` / `via` - None or a short one-line string (CF-0720's rule)."""
    if value is None:
        return None
    if (not isinstance(value, str) or not value.strip() or len(value.strip()) > WHO_MAX
            or any(c in value for c in "\r\n\t")):
        raise MemeDeskError("bad_who", f"{what}={value!r}: короткая строка в одну линию "
                                       f"(до {WHO_MAX} знаков, напр. by='user', via='center') "
                                       f"или не указывать вовсе")
    return value.strip()


def _read_candidates(base):
    path = Path(base) / CANDIDATES
    if not path.is_file():
        raise MemeDeskError("no_candidates", f"у банка {Path(base).name} нет списка "
                                             f"кандидатов", f"no {path}")
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise MemeDeskError("bad_candidates", f"список кандидатов банка {Path(base).name} "
                                              f"не читается", f"{path} unreadable ({e})")
    if not isinstance(data, dict) or not isinstance(data.get("candidates"), list) \
            or not all(isinstance(c, dict) and isinstance(c.get("id"), str)
                       for c in data["candidates"]):
        raise MemeDeskError("bad_candidates", "список кандидатов испорчен — в нём нет "
                                              "записей с id",
                            f"{CANDIDATES}: an object with a `candidates` list of "
                            f"records with `id` is needed")
    return data


def _candidate_file(base, c, repo):
    """(file name, path, error code) of a candidate's file in the bank:
    `<id><suffix>`, the suffix of its `url` first, then any a meme may have.
    (None, None, None) when it is not on the disk."""
    url = c.get("url")
    first = Path(str(url).split("?")[0]).suffix.lower() if url else ""
    order = ([first] if first in lib.IMAGE_SUFFIXES else []) + sorted(lib.IMAGE_SUFFIXES - {first})
    for s in order:
        name = f"{c['id']}{s}"
        raw = Path(base) / name
        if not (raw.exists() or raw.is_symlink()):
            continue
        try:
            path = bank_media(base, name, repo)
        except MemeDeskError:
            return name, None, "outside_bank"
        if not path.is_file():
            return name, None, "not_downloaded"
        return name, path, None
    return None, None, None


def _state(channel, bank, root, repo):
    """The one reading of the candidates: (state, bank name, base, lib root,
    index, raw candidate rows by id). Writes nothing."""
    name, base, lib_root, idx = _bank_index(channel, bank, root, repo)
    data = _read_candidates(base)
    in_index = {e["id"]: e for e in idx["entries"]}
    rows, by_id = [], {}
    for c in data["candidates"]:
        by_id[c["id"]] = c
        file, path, err = _candidate_file(base, c, repo)
        e = in_index.get(c["id"])
        if e is not None:
            status = "in_bank"
        elif err:
            status = err
        elif path is None:
            status = "not_downloaded"
        else:
            status = "ready"
        on_disk = path.stat().st_size if path is not None else None
        file = e["file"] if e is not None else file
        rows.append({
            "id": c["id"], "name": c.get("name"), "status": status,
            "in_bank": e is not None, "review": e.get("review") if e is not None else None,
            "downloaded": path is not None, "file": file,
            "kind": "gif" if str(file or c.get("url") or "").lower().endswith(".gif") else "still",
            "bytes": on_disk if on_disk is not None else c.get("bytes"),
            "width": c.get("width"), "height": c.get("height"), "stretch": c.get("stretch"),
            "passes_ceiling": c.get("passes_ceiling"), "blank_band": c.get("blank_band"),
            "imgflip_id": c.get("imgflip_id"), "url": c.get("url"),
            "source_url": c.get("url"), "licence": None,
            "intents": c.get("intents"), "use": c.get("use"),
            "in_reel_bank": c.get("in_reel_bank"), "note": c.get("note")})
    tail = [c["id"] for c in (data.get("reel_tail") or {}).get("candidates") or []
            if isinstance(c, dict) and isinstance(c.get("id"), str)]
    try:
        spec = json.loads((Path(repo) / "inserts" / "meme.json").read_text())
        vocabulary = set(spec["selection"]["intent_vocabulary"])
        problems = candidate_problems(data, fit_box(repo), max_upscale(repo), vocabulary)
    except (OSError, ValueError, KeyError) as e:
        raise MemeDeskError("bad_spec", "настройки мемов фабрики не читаются",
                            f"inserts/meme.json in {repo} unreadable ({e})")
    body = {"candidates": data["candidates"],
            "disk": [[r["id"], r["status"], r["file"], r["bytes"] if r["downloaded"] else None]
                     for r in rows]}
    fp = "sha256:" + hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False)
                                    .encode()).hexdigest()[:16]
    count = lambda s: sum(1 for r in rows if r["status"] == s)  # noqa: E731
    state = {"bank": name or lib.KIND_FOLDERS[KIND], "candidates": rows,
             "counts": {"total": len(rows), "ready": count("ready"), "in_bank": count("in_bank"),
                        "not_downloaded": count("not_downloaded"),
                        "outside_bank": count("outside_bank")},
             "other_bank": tail, "problems": problems, "fingerprint": fp}
    return state, name, base, lib_root, idx, by_id


def candidates_state(channel=None, bank=None, *, root=None, repo=REPO):
    """CF-0725: the bank's candidates.json as data, with what the disk says.
    One row per candidate: `status` - `ready` (its file lies in the bank, not
    in index.json yet: the only kind accept_candidates takes), `in_bank`
    (already an entry), `not_downloaded` (no file - a download is its own yes,
    add_image_entry), `outside_bank` (the name leads out of the bank, CF-0697);
    `file`, `kind` (still/gif), `bytes` (on the disk, else the recorded one),
    the recorded `width`/`height`/`stretch`/`passes_ceiling`/`blank_band`,
    `imgflip_id`, `url`, `source_url`, `licence` (a meme has none), `intents`,
    `use`. `other_bank` - the reel_tail ids, for the default bank, not this
    one; `problems` - candidate_problems; `fingerprint` - a hash of the list
    and of the disk state above, which plan_accept and accept_candidates
    compare. Reads only. No candidates.json is MemeDeskError('no_candidates')."""
    return _state(channel, bank, root, repo)[0]


def check_accept_answer(answer):
    """CF-0725: the user's typed answer to an accept plan - `{ok, why}`: it
    must say «да» (or "yes") as a word and must not say «нет» (or "no")."""
    words = ("".join(ch if ch.isalnum() else " " for ch in answer.lower()).split()
             if isinstance(answer, str) else [])
    if not any(w in ACCEPT_WORDS for w in words):
        return {"ok": False, "why": "в ответе нет «да» — кандидаты принимаются только "
                                    "по «да», набранному пользователем"}
    if any(w in REFUSE_WORDS for w in words):
        return {"ok": False, "why": "в ответе есть «нет» — это не согласие"}
    return {"ok": True, "why": None}


def _plan_accept(channel, ids, bank, details, root, repo, floor=True):
    state, name, base, lib_root, idx, by_id = _state(channel, bank, root, repo)
    if ids is None:
        ids = [r["id"] for r in state["candidates"] if r["status"] == "ready"]
    if not isinstance(ids, (list, tuple)) or not all(isinstance(i, str) for i in ids) \
            or len(set(ids)) != len(ids):
        raise MemeDeskError("bad_ids", "ids — список разных id кандидатов")
    if details is not None and (not isinstance(details, dict)
                                or not all(isinstance(v, dict) for v in details.values())):
        raise MemeDeskError("bad_details", "details — объект {id: {description, tags, notes}}")
    rows = {r["id"]: r for r in state["candidates"]}
    unknown = [i for i in ids if i not in rows and i not in state["other_bank"]]
    if unknown:
        raise MemeDeskError("unknown_id", f"нет таких кандидатов в списке: "
                                          f"{', '.join(unknown)}")
    stray = sorted(set(details or {}) - set(ids))
    if stray:
        raise MemeDeskError("bad_details", f"details для id вне списка: {', '.join(stray)}")
    reasons = {
        "in_bank": "уже в банке",
        "not_downloaded": "файла нет в банке — его скачивают отдельно, по своему «да»; "
                          "здесь ничего не скачивается",
        "outside_bank": "файл ведёт за пределы банка — не открываю",
        "other_bank": "кандидат для банка по умолчанию, не для этого",
        "no_source_url": "у кандидата нет ссылки — откуда файл, неизвестно",
    }
    accept, refused, entries = [], [], []
    for i in ids:
        r = rows.get(i)
        reason = "other_bank" if r is None else (r["status"] if r["status"] != "ready" else None)
        if reason is None and not (isinstance(r["url"], str)
                                   and r["url"].startswith(("http://", "https://"))):
            reason = "no_source_url"
        if reason:
            text = reasons[reason]
            if reason == "not_downloaded" and r.get("in_reel_bank"):
                text += (f"; тот же файл есть в банке по умолчанию ({r['in_reel_bank']}) — "
                         f"копирование тоже не здесь")
            refused.append({"id": i, "reason": reason, "text": text})
            continue
        if floor:
            try:
                _floor(bank_media(base, r["file"], repo), repo)
            except MemeDeskError as e:
                refused.append({"id": i, "reason": e.code, "text": e.text})
                continue
        accept.append(i)
        entries.append((r, by_id[i], (details or {}).get(i) or {}))
    n = len(accept)
    plan = {"bank": state["bank"], "ids": list(ids), "accept": accept, "refused": refused,
            "fingerprint": state["fingerprint"],
            "answer": {"must_contain": "да", "must_not_contain": ["нет"],
                       "prompt": (f"Принять в банк {state['bank']} {n} мем(а/ов): "
                                  f"{', '.join(accept)}? Наберите «да».") if n else None},
            "review": "pending", "downloads": 0}
    return plan, (name, base, lib_root, idx, entries)


def plan_accept(channel=None, ids=None, *, bank=None, details=None, by=None, via=None,
                root=None, repo=REPO):
    """CF-0725: what accept_candidates would do, written nowhere. `ids` - the
    candidates the user picked (None = every `ready` one); an id that is
    neither a candidate nor a reel_tail one is MemeDeskError('unknown_id').
    Returns {bank, ids, accept, refused [{id, reason, text}] (reason:
    in_bank, not_downloaded, outside_bank, other_bank, no_source_url,
    over_ceiling, media_failed), fingerprint (pass it back to
    accept_candidates), answer {must_contain: «да», must_not_contain, prompt}
    - the user types the answer themself, review: 'pending' (the entries wait
    on the desk), downloads: 0, by, via, dry_run: true}. `details` - optional
    {id: {description, tags, notes}}."""
    by, via = _who(by, "by"), _who(via, "via")
    plan = _plan_accept(channel, ids, bank, details, root, repo)[0]
    plan.update({"by": by, "via": via, "dry_run": True})
    return plan


def _accepted_entry(r, c, d, today, by, via, answer):
    """The index entry for a ready candidate - the keys add-image writes
    (_append_entry), `review: pending`, no rights-holder entry, never `cutout`."""
    own = bool(d.get("description"))
    description = d["description"] if own else f"Imgflip template «{c.get('name') or r['id']}»."
    tags = _tags_of(d["tags"]) if d.get("tags") else \
        list(dict.fromkeys([str(c.get("name") or r["id"]).lower()]
                           + [t for t in c.get("intents") or [] if isinstance(t, str)]))
    who = ", ".join(x for x in (f"by {by}" if by else "", f"via {via}" if via else "") if x)
    parts = [f"CF-0725 ({today}): accepted from {CANDIDATES}"
             + (f" ({who})" if who else "") + f" on the answer {answer.strip()!r}",
             f"Imgflip template {c.get('imgflip_id')} «{c.get('name')}»"
             if c.get("imgflip_id") else "",
             f"use: {c['use']}" if c.get("use") else "",
             "" if own and d.get("tags") else
             "description and tags are the candidate record's, not written from the picture - "
             "rewrite them on the desk before apply",
             str(d.get("notes") or "").strip()]
    return {"id": r["id"], "file": r["file"], "kind": KIND, "description": description,
            "tags": tags, "source_url": r["url"], "licence": None, "medium": None,
            "added": today, "review": "pending",
            "notes": "; ".join(p for p in parts if p), "download_url": r["url"]}


def accept_candidates(channel=None, ids=None, answer=None, by=None, via=None, *,
                      fingerprint=None, dry_run=False, bank=None, details=None, embed=True,
                      root=None, repo=REPO, today=None):
    """CF-0725: take the user's picked candidates into the bank. Refused
    whole (MemeDeskError, nothing written) when `fingerprint` is missing
    ('no_fingerprint') or no longer the list's ('list_changed' - the list or
    the disk moved since the plan), when the typed `answer` is not a «да»
    ('bad_answer', check_accept_answer), for an id that is no candidate
    ('unknown_id'), bad `ids`/`details`/`by`/`via`. Otherwise each `ready`
    candidate is added to index.json as add-image adds a file (_append_entry's
    keys: `review: pending`, no rights-holder entry, `source_url`/`download_url` -
    its Imgflip file), with `by`/`via` and the answer in `notes`; the rest are
    `refused` with plan_accept's reasons. Nothing is downloaded and `cutout`
    is never set. A real run appends one row to <bank>/_desk/
    candidates_accepted.jsonl and embeds the bank (embed=True). Returns
    {bank, accepted [ids], refused [{id, reason, text}], unchanged (index.json
    not written), entries, fingerprint, by, via, dry_run, embedding}."""
    by, via = _who(by, "by"), _who(via, "via")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise MemeDeskError("no_fingerprint", "нужен отпечаток списка из plan_accept")
    got = check_accept_answer(answer)
    if not got["ok"]:
        raise MemeDeskError("bad_answer", got["why"])
    plan, (name, base, lib_root, idx, entries) = _plan_accept(channel, ids, bank, details,
                                                             root, repo)
    if plan["fingerprint"] != fingerprint:
        raise MemeDeskError("list_changed", "список кандидатов изменился после плана — "
                                            "покажите пользователю новый план",
                            f"the candidates changed since the plan ({fingerprint} -> "
                            f"{plan['fingerprint']}) - show the user the new plan")
    today = today or datetime.date.today().isoformat()
    new = []
    for r, c, d in entries:
        _check_new(idx, r["id"], "-")
        e = _accepted_entry(r, c, d, today, by, via, answer)
        errs = lib.validate_entry(e, KIND, base)
        if errs:
            raise MemeDeskError("invalid_entry", f"запись не принята — она не проходит проверку банка (ошибок: {len(errs)})",
                                "\n".join(errs))
        new.append(e)
    idx["entries"] = idx["entries"] + new
    errs = lib.validate_index(idx, KIND)
    if errs:
        raise MemeDeskError("invalid_index", f"список мемов не записан — он вышел бы неверным "
                                             f"(ошибок: {len(errs)})",
                            "refusing to write an invalid index:\n  " + "\n  ".join(errs))
    result = {"bank": plan["bank"], "accepted": [e["id"] for e in new],
              "refused": plan["refused"], "unchanged": dry_run or not new, "entries": new,
              "fingerprint": fingerprint, "by": by, "via": via, "dry_run": bool(dry_run),
              "embedding": None}
    if dry_run or not new:
        return result
    lib.save_index(idx, KIND, lib_root, name)
    d = Path(base) / DESK
    d.mkdir(parents=True, exist_ok=True)
    row = {"event": "candidates_accepted",
           "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "accepted": result["accepted"], "refused": [x["id"] for x in plan["refused"]],
           "answer": answer, "fingerprint": fingerprint, "task": "CF-0725"}
    if by is not None:
        row["by"] = by
    if via is not None:
        row["via"] = via
    with (d / ACCEPT_JOURNAL).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    if embed:
        result["embedding"] = _embed_run(name, lib_root)
    return result


# --------------------------------------------------------------------------
# background jobs for the command center (CF-0755, center 0.4.1, CC-0075/76)
# --------------------------------------------------------------------------
#
# The center does not run a long job in its own process: start_job() checks
# it with the job's own plan (the same refusals), writes its state file and
# starts `python3 scripts/meme_desk.py job-run <state_file>` as a process of
# its own (a new session, output in the job's log) - the shape of the Studio
# reading (agents/analyst/studio_center.py). The center then only reads:
# job_status(), list_jobs(), active_job() (the machine's slot, CF-0761).
# There is no cancel.
#
#   <bank>/_desk/jobs/<job_id>.json   the state file (running | done | failed)
#   <bank>/_desk/jobs/<job_id>.log    the job's stdout + stderr
#   <bank>/_desk/jobs/<job_id>.lock   held (flock) by the job-run process for
#                                     its whole life - the liveness signal
#
# Liveness is the lock, not the pid: start_job takes the job's flock before
# the state file says `running` and hands the locked descriptor to the child
# (pass_fds); the kernel lets go of it when the child ends, however it ends.
# A state file that says `running` over a lock nobody holds is `interrupted`
# - a recycled pid cannot keep a dead job alive, and a center restart loses
# nothing (everything is on disk).
#
# One job per machine: <main checkout>/schedule/meme-desk/ (MEME_DESK_JOBS_DIR
# overrides) holds `.lock` (start_job's critical section) and `active.json`
# {job_id, kind, bank, state_file, pid, started_at} - the last job started.
# A second start while that job's lock is held is MemeDeskError('job_running',
# .job_id). The main checkout, not the calling one: a version worktree
# (.worktrees/release-*) works on the same banks (their files are links to
# the working copy's, agents.lock.json) and the same CPU, so the release
# center and the production center share the one slot. schedule/ is the
# factory's untracked machine state already (the batch switch, the Studio
# reading's runs) and survives a restart of anything; ~/Library would hide it
# from the factory's own tooling and from the tests' temp repos.

JOBS = "jobs"                       # <bank>/_desk/jobs/
JOB_KINDS = ("cutout", "trim_blank", "add_image", "add_gif", "sheet", "embed")
JOBS_KEEP = 50                      # records kept per bank; start_job prunes the rest
JOBS_DIR_ENV = "MEME_DESK_JOBS_DIR"
JOBS_MACHINE_DIR = Path("schedule") / "meme-desk"
JOBS_ACTIVE = "active.json"
JOB_ID_RE = re.compile(r"[0-9]{8}T[0-9]{6}Z-[a-z_]+-[0-9a-f]{6}")
JOB_STATES = ("running", "done", "failed", "interrupted")
HOMEBREW_BIN = ("/opt/homebrew/bin", "/usr/local/bin")
JOB_LOG_TAIL = 20                   # lines of the log an error carries
JOB_ARGV = None                     # tests: the child's argv before <state_file>
# CF-0847: start_job(commit=True) - the job commits what it changed in the
# repo when it ends done; Cc-Action is the center's action of the kind
# (api/meme_jobs.py), so the center's history names it as its own writes.
JOB_ACTIONS = {"cutout": "meme_cutout", "trim_blank": "meme_trim",
               "add_image": "meme_add_image", "add_gif": "meme_add_gif",
               "sheet": "meme_sheet", "embed": "meme_embed"}
COMMIT_PREFIX = "cc-commit:"        # every line of the job's commit in its log
COMMIT_STATES = ("committed", "refused", "nothing")

# kind -> (required params, allowed params); channel/bank/root/repo/by/via/
# progress/dry_run come from start_job, never from params
JOB_PARAMS = {
    "cutout": (set(), {"ids", "force"}),
    "trim_blank": (set(), {"id", "embed"}),
    "add_image": ({"meme_id", "url", "source_url", "description", "tags"},
                  {"meme_id", "url", "source_url", "description", "tags", "notes", "embed"}),
    "add_gif": ({"meme_id", "video", "start", "end", "description", "tags"},
                {"meme_id", "video", "start", "end", "description", "tags", "source_url",
                 "notes", "width", "fps", "local", "embed"}),
    "sheet": ({"video"}, {"video", "start", "end", "every", "out", "local"}),
    "embed": (set(), set()),
}


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _job_read(path):
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _job_write(path, doc):
    """Atomic: a reader sees the old file or the new one, never half."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _json_safe(value):
    """A function's result as plain JSON (paths and tuples as strings/lists)."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _main_checkout(repo):
    """The main checkout of `repo`: itself, or - for a worktree, whose .git is
    a file `gitdir: <main>/.git/worktrees/<name>` - the folder of the common
    .git. Read from the files, no git child; `repo` itself when unsure."""
    repo = Path(repo)
    dotgit = repo / ".git"
    if not dotgit.is_file():
        return repo
    try:
        m = re.match(r"gitdir:\s*(.+)", dotgit.read_text(encoding="utf-8").strip())
        if not m:
            return repo
        gitdir = Path(m.group(1).strip())
        gitdir = gitdir if gitdir.is_absolute() else (repo / gitdir)
        common = gitdir / "commondir"
        rel = common.read_text(encoding="utf-8").strip() if common.is_file() else "../.."
        common_dir = (gitdir / rel).resolve()
    except OSError:
        return repo
    return common_dir.parent if common_dir.name == ".git" else repo


def jobs_machine_dir(repo, environ=None):
    """Where the one-job-per-machine slot lives (see above):
    $MEME_DESK_JOBS_DIR, else <main checkout>/schedule/meme-desk/."""
    env = os.environ if environ is None else environ
    if env.get(JOBS_DIR_ENV):
        return Path(env[JOBS_DIR_ENV]).expanduser()
    return _main_checkout(repo) / JOBS_MACHINE_DIR


@contextlib.contextmanager
def _flocked(path):
    import fcntl  # noqa: PLC0415  (POSIX; the desk runs on the Mac)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _lock_held(path):
    """True while some process holds the job's lock (its job-run is alive)."""
    import fcntl  # noqa: PLC0415
    try:
        fd = os.open(str(path), os.O_RDWR)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    except OSError:
        return False
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def _jobs_dir(base):
    return Path(base) / DESK / JOBS


def _log_tail(log, n=JOB_LOG_TAIL):
    try:
        text = Path(log).read_text(encoding="utf-8", errors="replace")
    except (OSError, TypeError):
        return ""
    return "\n".join(text.rstrip().splitlines()[-n:])[-4000:]


def _check_params(kind, params):
    if kind not in JOB_KINDS:
        raise MemeDeskError("bad_kind", f"нет такой задачи {kind!r}: {', '.join(JOB_KINDS)}",
                            f"no such job kind {kind!r}: {', '.join(JOB_KINDS)}")
    params = {} if params is None else params
    if not isinstance(params, dict):
        raise MemeDeskError("bad_params", "params — словарь аргументов задачи",
                            "params is a dict of the job's arguments")
    need, allowed = JOB_PARAMS[kind]
    extra, missing = sorted(set(params) - allowed), sorted(need - set(params))
    if extra or missing:
        raise MemeDeskError(
            "bad_params",
            f"{kind}: " + "; ".join(x for x in (
                f"лишние аргументы {', '.join(extra)}" if extra else "",
                f"не хватает {', '.join(missing)}" if missing else "") if x)
            + f" (можно: {', '.join(sorted(allowed)) or 'ничего'})",
            f"{kind}: unknown {extra}, missing {missing}")
    try:
        json.dumps(params)
    except (TypeError, ValueError) as e:
        raise MemeDeskError("bad_params", f"{kind}: аргументы не JSON ({e})",
                            f"{kind}: params are not JSON ({e})")
    return dict(params)


def _job_plan(kind, params, name, lib_root, repo, by, via):
    """The job's plan - the same call start_job refuses by (a plan function
    or a dry run); writes nothing."""
    common = {"bank": name, "root": lib_root, "repo": repo}
    if kind == "cutout":
        ok, text, en = _cutout_check()
        if not ok:
            raise MemeDeskError("cutout_unavailable", text, en)
        return cutout_entries(**params, dry_run=True, by=by, via=via, **common)
    if kind == "trim_blank":
        return trim_blank_entries(**params, dry_run=True, by=by, via=via, **common)
    if kind == "add_image":
        return plan_add_image(**params, by=by, via=via, **common)
    if kind == "add_gif":
        return plan_add_gif(**params, by=by, via=via, **common)
    if kind == "sheet":
        return plan_sheet(**params, **common)
    _bank_index(None, name, lib_root, repo)             # embed: the bank is there
    return {"bank": name or lib.KIND_FOLDERS[KIND], "steps": ["embedding"],
            "max_seconds": _embed_seconds(True)}


def _job_work(kind, params, name, lib_root, repo, by, via, progress):
    """The job itself, in the job-run process."""
    common = {"bank": name, "root": lib_root, "repo": repo, "progress": progress}
    if kind == "cutout":
        return cutout_entries(**params, by=by, via=via, **common)
    if kind == "trim_blank":
        return trim_blank_entries(**params, by=by, via=via, **common)
    if kind == "add_image":
        return add_image_entry(**params, by=by, via=via, **common)
    if kind == "add_gif":
        return add_gif_entry(**params, by=by, via=via, **common)
    if kind == "sheet":
        return make_sheet(**params, **common)
    _, base, _, _ = _bank_index(None, name, lib_root, repo)
    _tick(progress, "embedding", 1, 1, EMBED_STEP_RU)
    r = {"bank": name or lib.KIND_FOLDERS[KIND], "embedding": _embed_run(name, lib_root)}
    _journal(base, "embed", [], by, via)
    return r


def _job_argv(state_file):
    head = JOB_ARGV or [sys.executable, str(Path(__file__).resolve()), "job-run"]
    return [*head, str(state_file)]


def _active_job(mdir):
    """The machine's running job {job_id, kind, bank, state_file, pid,
    started_at}, or None - a job whose lock nobody holds is not running."""
    a = _job_read(Path(mdir) / JOBS_ACTIVE)
    if not a or not a.get("state_file") or not JOB_ID_RE.fullmatch(str(a.get("job_id", ""))):
        return None
    sf = Path(a["state_file"])
    s = _job_read(sf)
    if not s or s.get("state") != "running" or not _lock_held(sf.with_suffix(".lock")):
        return None
    return a


def _prune_jobs(d, keep):
    """Keep the newest `keep` job records of a bank folder; a running one is
    never removed."""
    ids = sorted(p.stem for p in Path(d).glob("*.json") if JOB_ID_RE.fullmatch(p.stem))
    for job_id in ids[:max(0, len(ids) - keep)]:
        if _lock_held(Path(d) / f"{job_id}.lock"):
            continue
        for suffix in (".json", ".log", ".lock"):
            with contextlib.suppress(OSError):
                (Path(d) / f"{job_id}{suffix}").unlink()


def start_job(kind, params, *, channel=None, bank=None, by, via, root, repo, environ=None,
              commit=False):
    """CF-0755: start a long desk job in the background for the center.

    `kind` - cutout | trim_blank | add_image | add_gif | sheet | embed;
    `params` - the job function's own arguments (JOB_PARAMS; channel, bank,
    root, repo, by, via, progress and dry_run are not params). Checked first
    by the job's plan - cutout: cutout_available + cutout_entries(dry_run=True);
    trim_blank: trim_blank_entries(dry_run=True); add_image: plan_add_image;
    add_gif: plan_add_gif; sheet: plan_sheet; embed: the bank is there - so
    start_job refuses exactly what the plan refuses (its MemeDeskError) and
    nothing starts. `by` and `via` are required (bad_who).

    Then, under the machine's slot (jobs_machine_dir): another job running
    is MemeDeskError('job_running') with `.job_id`; else the bank's older
    records past JOBS_KEEP are removed, <bank>/_desk/jobs/<job_id>.json is
    written (state running) and `python3 scripts/meme_desk.py job-run
    <state_file>` starts in a session of its own (stdin /dev/null, output in
    <job_id>.log, cwd `repo`, environment `environ` or this process's) -
    spawn_failed when it cannot. Returns {job_id, bank, kind, pid, log,
    state_file}. Never waits on the job, never signals it.

    CF-0847: `commit` True - when the job ends done, job_run commits the
    paths of the bank folder the job changed in git's eyes (`_job_commit`),
    with `Cc-Channel` / `Cc-Action` trailers; the switch is the state file's
    `commit_on_done`, the outcome its `commit`. False (the default): no
    commit, as before. Not a bool: bad_params."""
    if not isinstance(commit, bool):
        raise MemeDeskError("bad_params", "commit — да или нет (true/false)",
                            f"commit is a bool, not {commit!r:.40}")
    by, via = _who(by, "by"), _who(via, "via")
    if by is None or via is None:
        raise MemeDeskError("bad_who", "у задачи есть автор: нужны и by, и via",
                            "a job is somebody's: both by and via are required")
    params = _check_params(kind, params)
    name, base, lib_root, _ = _bank_index(channel, bank, root, repo)
    lib_root, repo = Path(lib_root).resolve(), Path(repo).resolve()
    plan = _json_safe(_job_plan(kind, params, name, lib_root, repo, by, via))
    mdir = jobs_machine_dir(repo, environ)
    bank_word = name or lib.KIND_FOLDERS[KIND]
    with _flocked(mdir / ".lock"):
        going = _active_job(mdir)
        if going:
            e = MemeDeskError(
                "job_running",
                f"уже идёт задача {going['job_id']} ({going.get('kind')}, банк "
                f"{going.get('bank')}) — одна на машину, отмены нет; дождитесь её конца",
                f"job {going['job_id']} is running - one job per machine")
            e.job_id = going["job_id"]
            raise e
        d = _jobs_dir(base)
        d.mkdir(parents=True, exist_ok=True)
        _prune_jobs(d, JOBS_KEEP - 1)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        job_id = f"{stamp}-{kind}-{os.urandom(3).hex()}"
        state_file, log, lock = d / f"{job_id}.json", d / f"{job_id}.log", d / f"{job_id}.lock"
        import fcntl  # noqa: PLC0415
        fd = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)    # before the file says running
            state = {"job_id": job_id, "kind": kind, "bank": bank_word, "bank_name": name,
                     "root": str(lib_root), "repo": str(repo), "params": params,
                     "plan": plan, "by": by, "via": via, "state": "running",
                     "started_at": _utc_now(), "attached_at": None, "ended_at": None,
                     "pid": None, "progress": None, "result": None, "error": None,
                     "log": str(log), "machine_dir": str(mdir), "task": "CF-0755",
                     "channel": channel, "commit_on_done": commit, "commit": None}
            _job_write(state_file, state)
            env = dict(os.environ if environ is None else environ)
            try:
                with open(log, "ab") as fh:
                    proc = subprocess.Popen(_job_argv(state_file), stdin=subprocess.DEVNULL,
                                            stdout=fh, stderr=subprocess.STDOUT,
                                            cwd=str(repo), env=env, start_new_session=True,
                                            close_fds=True, pass_fds=(fd,))
            except OSError as err:
                state.update(state="failed", ended_at=_utc_now(), error={
                    "code": "spawn_failed", "text": "задача не стартовала",
                    "en": f"the job did not start ({err})"})
                _job_write(state_file, state)
                raise MemeDeskError("spawn_failed", "задача не стартовала",
                                    f"the job did not start ({err})")
        finally:
            os.close(fd)        # the child keeps its copy - the lock lives as long as it
        _job_write(mdir / JOBS_ACTIVE, {"job_id": job_id, "kind": kind, "bank": bank_word,
                                        "state_file": str(state_file), "pid": proc.pid,
                                        "started_at": state["started_at"]})
    return {"job_id": job_id, "bank": bank_word, "kind": kind, "pid": proc.pid,
            "log": str(log), "state_file": str(state_file)}


def _job_view(s, d):
    """job_status' answer for one state file `s` of jobs folder `d`."""
    job_id = s.get("job_id")
    state = s.get("state") if s.get("state") in JOB_STATES else "failed"
    alive = state == "running" and _lock_held(Path(d) / f"{job_id}.lock")
    error = s.get("error")
    if state == "running" and not alive:
        state = "interrupted"
        error = {"code": "job_interrupted",
                 "text": "задача оборвалась: её процесс не жив, а итога в файле нет "
                         "(перезагрузка, остановка или падение до записи итога)",
                 "en": "the job broke off: its process is gone and left no outcome",
                 "log_tail": _log_tail(s.get("log"))}
    plan = s.get("plan") if isinstance(s.get("plan"), dict) else {}
    return {"job_id": job_id, "kind": s.get("kind"), "bank": s.get("bank"), "state": state,
            "done": state != "running", "started_at": s.get("started_at"),
            "ended_at": s.get("ended_at"), "pid": s.get("pid"), "alive": alive,
            "progress": s.get("progress"), "result": s.get("result"), "error": error,
            "log": s.get("log"), "by": s.get("by"), "via": s.get("via"),
            "params": s.get("params"), "max_seconds": plan.get("max_seconds"),
            "commit_on_done": bool(s.get("commit_on_done")), "commit": s.get("commit")}


def job_status(job_id, *, channel=None, bank=None, root=None, repo=REPO):
    """CF-0755: one job of the bank - {job_id, kind, bank, state: running |
    done | failed | interrupted, done, started_at, ended_at, pid, alive,
    progress {step, i, of, text} | None, result (the function's return, as
    JSON) | None, error {code, text, en[, log_tail]} | None, log, by, via,
    params, max_seconds (the plan's worst-case wall time, None for the
    cutout, the trim and the embedding), commit_on_done, commit (CF-0847:
    {status: committed | refused | nothing, sha?, committed?, detail?} or
    None - see _job_commit)}. `interrupted` - the file says
    running and the job's lock is free (its process is gone). Reads only.
    Unknown or malformed id: MemeDeskError('unknown_job')."""
    if not isinstance(job_id, str) or not JOB_ID_RE.fullmatch(job_id):
        raise MemeDeskError("unknown_job", f"нет такой задачи {job_id!r}",
                            f"no such job {job_id!r}")
    _, base = resolve_bank(channel, bank, root, repo)
    d = _jobs_dir(base)
    s = _job_read(d / f"{job_id}.json")
    if not s or s.get("job_id") != job_id:
        raise MemeDeskError("unknown_job", f"в банке нет задачи {job_id}",
                            f"no job {job_id} in this bank")
    return _job_view(s, d)


def list_jobs(*, channel=None, bank=None, limit=20, root=None, repo=REPO):
    """CF-0755: the bank's jobs, newest first, at most `limit` (1..JOBS_KEEP,
    bad_limit otherwise) - each as job_status() says it. Reads only."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= JOBS_KEEP:
        raise MemeDeskError("bad_limit", f"limit — целое от 1 до {JOBS_KEEP}",
                            f"limit is an int 1..{JOBS_KEEP}")
    _, base = resolve_bank(channel, bank, root, repo)
    d = _jobs_dir(base)
    out = []
    for p in sorted(d.glob("*.json"), key=lambda p: p.stem, reverse=True):
        if not JOB_ID_RE.fullmatch(p.stem):
            continue
        s = _job_read(p)
        if s and s.get("job_id") == p.stem:
            out.append(_job_view(s, d))
        if len(out) >= limit:
            break
    return out


def _bank_channel(bank_word, repo):
    """The channel whose bank `bank_word` is (insert_layers.meme.bank of
    <repo>/channels/<id>.json; no bank there = the default `memes`) - the one
    channel that names it, None when none or several do (the default bank is
    shared). Reads the configs only; a malformed one is skipped."""
    if not isinstance(bank_word, str) or not bank_word:
        return None
    found = []
    for path in sorted((Path(repo) / "channels").glob("*.json")):
        try:
            name = lib.channel_meme_bank(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, lib.MemeBankError):
            continue
        if (name or lib.KIND_FOLDERS[KIND]) == bank_word:
            found.append(path.stem)
    return found[0] if len(found) == 1 else None


def active_job(*, root=None, repo=REPO, environ=None):
    """CF-0761: the machine's job slot as the center's plan reads it -
    {job_id, kind, bank, channel, started_at, alive} of the last job
    start_job put into jobs_machine_dir(repo, environ)/active.json, or None
    when there is no slot file (or it does not name a job). `alive` is the
    same signal as job_status: the state file says running and the job's
    <job_id>.lock is held (a non-blocking probe); a job whose process is gone
    is alive False, not None - the center decides what to say. `channel` -
    the one channel whose bank it is (channels/<id>.json), None when it is
    the shared default bank or no channel names it. Side-effect free: writes,
    cleans and creates nothing, never takes the slot's .lock (a starting job
    is never kept waiting). `root` is accepted for the desk's uniform call
    shape; the slot is per machine, not per library."""
    del root
    a = _job_read(jobs_machine_dir(repo, environ) / JOBS_ACTIVE)
    if not a or not JOB_ID_RE.fullmatch(str(a.get("job_id", ""))):
        return None
    alive = False
    if a.get("state_file"):
        sf = Path(a["state_file"])
        s = _job_read(sf)
        alive = bool(s and s.get("job_id") == a["job_id"] and s.get("state") == "running"
                     and _lock_held(sf.with_suffix(".lock")))
    return {"job_id": a["job_id"], "kind": a.get("kind"), "bank": a.get("bank"),
            "channel": _bank_channel(a.get("bank"), repo),
            "started_at": a.get("started_at"), "alive": alive}


def job_path(environ):
    """PATH with the homebrew folders (ffmpeg, ffprobe, yt-dlp) in front when
    they are missing - a process the center starts may carry launchd's bare
    PATH."""
    parts = [p for p in (environ.get("PATH") or "").split(os.pathsep) if p]
    return os.pathsep.join([b for b in HOMEBREW_BIN if b not in parts] + parts)


def _git_commit():
    import git_commit  # noqa: PLC0415  (shared/runlog, on the path beside git_read)
    return git_commit


def _channel_ids():
    if str(REPO / "shared") not in sys.path:
        sys.path.append(str(REPO / "shared"))
    import channel_ids  # noqa: PLC0415
    return channel_ids


def _job_scope(s, path):
    """(repo, [the bank folder from the repo]) of the job whose state file is
    `path` (<bank>/_desk/jobs/<job_id>.json) - the paths a job of the desk
    writes (index.json, candidates.json, the media - git ignores the media,
    _desk/ too). The folder outside the repo: no scope."""
    repo = Path(s.get("repo") or REPO)
    try:
        return repo, [_git_commit().rel(repo, path.parents[2])]
    except Exception:  # noqa: BLE001 - outside the repo: nothing of its git
        return repo, []


def _job_snap(repo, scope):
    """{path: (XY, sha256 | None)} of what git calls changed under `scope`;
    None when there is nothing to commit to (no scope, not a git work tree,
    git failed)."""
    gc = _git_commit()
    if not scope or not gc.is_repo(repo):
        return None
    try:
        st = gc.status(repo, scope)
    except (gc.CommitError, OSError, subprocess.SubprocessError):
        return None
    out = {}
    for rel, xy in st.items():
        f = Path(repo) / rel
        out[rel] = (xy, hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else None)
    return out


def _job_commit(s, path, before):
    """CF-0847: the commit of a job that ended done with commit_on_done - the
    paths under the job's scope that changed in git's eyes since `before`
    (a file already dirty counts only when its bytes moved; a stray file
    elsewhere is never touched), one `git commit --only` of exactly those
    (git_commit.commit_paths, never `add -A`), the message the center's
    (CC-0156: subject, a body naming the job, `Cc-Channel: <channel>` - left
    out for a bank no single channel names - and `Cc-Action: meme_<kind>`).
    Returns the state file's `commit`: {status: committed, sha, committed} |
    {status: nothing[, detail]} | {status: refused, detail} - git's refusal
    leaves the files in the tree, nothing staged; the job stays done. One
    `cc-commit: ...` line in the job's log."""
    gc = _git_commit()
    repo, scope = _job_scope(s, path)
    if before is None:
        out = {"status": "nothing", "detail": "not a git work tree or the bank is outside it"}
        print(f"{COMMIT_PREFIX} nothing to commit - {out['detail']}", flush=True)
        return out
    after = _job_snap(repo, scope) or {}
    touched = sorted(p for p, v in after.items() if before.get(p) != v)
    if not touched:
        print(f"{COMMIT_PREFIX} nothing to commit", flush=True)
        return {"status": "nothing"}
    cid = _channel_ids().resolve_channel(s.get("channel"), root=repo) \
        or _bank_channel(s.get("bank"), repo)
    who = f"{s.get('by')}, {s.get('via')}"
    head = f"Мемы {cid}" if cid else f"Мемы банка {s.get('bank')}"
    trailers = ([f"Cc-Channel: {cid}"] if cid else []) + \
        [f"Cc-Action: {JOB_ACTIONS.get(s.get('kind'), 'meme_job')}"]
    message = (f"{head}: задача {s.get('kind')} готова ({who})\n\n"
               f"Фоновая задача стола мемов (meme_desk.start_job, commit).\n"
               f"Задача: {s.get('job_id')}\nБанк: {s.get('bank')}\n\n"
               + "\n".join(trailers) + "\n")
    try:
        sha, committed = gc.commit_paths(repo, touched, message)
    except (gc.CommitError, OSError, subprocess.SubprocessError) as e:
        detail = " | ".join(str(x) for x in [e, *getattr(e, "details", [])] if str(x).strip())
        detail = f"{detail} | touched: {', '.join(touched)}"[:2000]
        print(f"{COMMIT_PREFIX} refused - {detail}", flush=True)
        return {"status": "refused", "detail": detail}
    if not sha:
        print(f"{COMMIT_PREFIX} nothing to commit", flush=True)
        return {"status": "nothing"}
    print(f"{COMMIT_PREFIX} committed {sha[:12]}: {', '.join(committed)}", flush=True)
    return {"status": "committed", "sha": sha, "committed": committed}


def job_run(state_file):
    """CF-0755: the job process - `meme_desk.py job-run <state_file>`.
    Runs the job the state file names with `progress` writing into it
    (atomic), then writes the outcome: state done + result, or failed + error
    {code, text, en} (a MemeDeskError's), {code: job_crashed, ..., log_tail}
    for anything unexpected (the traceback is in the log), {code:
    embed_failed} for an embed job whose embedding did not happen. CF-0847:
    a done job with commit_on_done commits what it changed (_job_commit)
    before the file says done - still under the job's lock, so no other job
    and no center write sees the bank between the work and its commit; the
    outcome is the file's `commit`, a refusal leaves the job done. Frees the
    machine's slot. Returns the exit code: 0 done, 1 failed, 2 no state file."""
    path = Path(state_file).resolve()
    s = _job_read(path)
    if not s or not JOB_ID_RE.fullmatch(str(s.get("job_id", ""))) or path.stem != s["job_id"] \
            or s.get("kind") not in JOB_KINDS or s.get("state") != "running":
        print(f"job-run: {path} is not a running job's state file", file=sys.stderr)
        return 2
    os.environ["PATH"] = job_path(os.environ)
    s.update(pid=os.getpid(), attached_at=_utc_now())
    _job_write(path, s)
    print(f"job {s['job_id']}: {s['kind']} on {s['bank']} (by {s['by']}, via {s['via']}), "
          f"pid {os.getpid()}", flush=True)
    before = _job_snap(*_job_scope(s, path)) if s.get("commit_on_done") is True else None

    def progress(step, i, of, text=""):
        s["progress"] = {"step": str(step), "i": i, "of": of, "text": str(text or "")}
        s["updated_at"] = _utc_now()
        _job_write(path, s)

    try:
        result = _json_safe(_job_work(s["kind"], s.get("params") or {}, s.get("bank_name"),
                                      s["root"], s["repo"], s.get("by"), s.get("via"),
                                      progress))
        s.update(state="done", result=result, error=None)
        emb = result.get("embedding") if isinstance(result, dict) else None
        if s["kind"] == "embed" and not (emb or {}).get("done"):
            s.update(state="failed", error={
                "code": "embed_failed",
                "text": (emb or {}).get("error") or EMBED_NOT_DONE_RU,
                "en": f"the bank's embeddings were not recomputed: {(emb or {}).get('en')}"})
    except MemeDeskError as e:
        s.update(state="failed", error={"code": e.code, "text": e.text, "en": e.en})
    except (Exception, SystemExit) as e:  # noqa: BLE001 - whatever it was, it is the outcome
        import traceback  # noqa: PLC0415
        traceback.print_exc()
        sys.stderr.flush()
        sys.stdout.flush()
        what = f"{type(e).__name__}: {e}"
        s.update(state="failed", error={"code": "job_crashed",
                                        "text": "задача упала — подробности в её журнале",
                                        "en": f"the job crashed: {what}",
                                        "log_tail": _log_tail(s.get("log"))})
    if s["state"] == "done" and s.get("commit_on_done") is True:
        try:        # CF-0847: before the file says done - under the job's lock
            s["commit"] = _job_commit(s, path, before)
        except Exception as e:  # noqa: BLE001 - the job is done whatever the commit did
            s["commit"] = {"status": "refused", "detail": f"{type(e).__name__}: {e}"[:2000]}
            print(f"{COMMIT_PREFIX} refused - {s['commit']['detail']}", flush=True)
    s["ended_at"] = _utc_now()
    _job_write(path, s)
    print(f"job {s['job_id']}: {s['state']}"
          + (f" ({s['error']['code']})" if s.get("error") else ""), flush=True)
    # CF-0858: the outcome first, the slot's file after - on purpose. The slot
    # is busy only while its job's state file says running AND its lock is
    # held (_active_job, active_job): the moment the file above says
    # done/failed the slot is free for every reader, and active.json is just a
    # stale pointer until the unlink below (a start in between takes the slot
    # and writes its own active.json, which the unlink then leaves alone). The
    # other order would open the bad window: no active.json while the file
    # still says running and the lock is held - start_job would let a second
    # job run beside this one.
    mdir = s.get("machine_dir")
    if mdir:
        with _flocked(Path(mdir) / ".lock"):
            a = _job_read(Path(mdir) / JOBS_ACTIVE)
            if a and a.get("job_id") == s["job_id"]:
                with contextlib.suppress(OSError):
                    (Path(mdir) / JOBS_ACTIVE).unlink()
    return 0 if s["state"] == "done" else 1


def job_run_cli(args):
    raise SystemExit(job_run(args.state_file))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(fn=status)
    p = sub.add_parser("apply")
    p.add_argument("--drop", action="store_true", help="also remove accepted entries marked drop")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=apply)
    for name, fn in (("add-image", add_image), ("add-gif", add_gif)):
        p = sub.add_parser(name)
        p.add_argument("--id", required=True)
        p.add_argument("--description", required=True)
        p.add_argument("--tags", required=True, help="comma-separated, English, ~20")
        p.add_argument("--notes")
        if name == "add-image":
            p.add_argument("--url", required=True, help="the file itself")
            p.add_argument("--source-url", required=True, help="the page it was found on")
        else:
            p.add_argument("--video", required=True, help="video URL, or a local file with --source-url")
            p.add_argument("--source-url")
            p.add_argument("--start", type=float, required=True)
            p.add_argument("--end", type=float, required=True)
            p.add_argument("--width", type=int, default=GIF_WIDTH)
            p.add_argument("--fps", type=int, default=GIF_FPS)
        p.set_defaults(fn=fn)
    p = sub.add_parser("cutout", help="cut out the foreground of every cutout: true meme (CF-0403)")
    p.add_argument("--id", help="only this entry")
    p.add_argument("--force", action="store_true", help="redo even when the source is unchanged")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cutout)
    p = sub.add_parser("trim-blank",
                       help="cut the blank caption panel off every still that has one (CF-0534)")
    p.add_argument("--id", help="only this entry")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=trim_blank)
    p = sub.add_parser("sheet")
    p.add_argument("--video", required=True)
    p.add_argument("--from", dest="start", type=float, default=0.0)
    p.add_argument("--to", dest="end", type=float)
    p.add_argument("--every", type=float, default=2.0)
    p.add_argument("--out", default="meme_sheet.jpg")
    p.set_defaults(fn=sheet)
    sub.add_parser("candidates", help="the bank's candidate list (CF-0393)").set_defaults(
        fn=candidates)
    p = sub.add_parser("job-run", help="run one background job of the center (CF-0755)")
    p.add_argument("state_file", help="<bank>/_desk/jobs/<job_id>.json written by start_job")
    p.set_defaults(fn=job_run_cli)
    for p in sub.choices.values():  # CF-0393: every subcommand works on one bank
        p.add_argument("--channel", help="work on this channel's own bank "
                                         "(insert_layers.meme.bank in channels/<id>.json)")
        p.add_argument("--bank", help="work on this bank: memes-<channel> or "
                                      "shared/inserts/memes-<channel>/")
    args = ap.parse_args(argv)
    select_bank(args.channel, args.bank)
    try:
        args.fn(args)
    except MemeDeskError as e:      # CF-0694: the functions' refusals, as the terminal said them
        raise SystemExit(e.en)


if __name__ == "__main__":
    main()
