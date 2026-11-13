"""CF-0567 (FI step of the root's docs/tech-footage.md): ExampleTech's own
screen recording - `own_capture` - taken into the pool as a source.

The recorder is the Video Editor's (`agents/video-editor/scripts/capture_tool.py`,
CF-0567 step 2). It writes, into whatever `<out_dir>` it is given:

    own_capture-<id>.mp4               1080x1920 H.264, 30 fps
    own_capture-<id>.own_capture.json  the sidecar, `schema: "own-capture/1"`:
                                       id, file_id, file, origin, licence,
                                       found_by, url, final_url, host,
                                       capture_host, host_entry,
                                       capture_allowed, robots, space, steps,
                                       duration_s, width, height, fps, ...

What this module does with it, for `fetch_footage.py --own-capture-json`:

  * **ids** - `own_capture:<id>` is the Trend Hunter's (and this stage's
    candidate) name; on disk, in the cache index, in every report of this
    stage and in the Video Editor's clip names and shot keys the source is its
    *file id* `own_capture-<id>` (`file_id()`, the same rule as
    `archive_source.file_id` and VE's `_clip_names.own_capture_file_id`: every
    character outside [A-Za-z0-9_-] made `_`). `ingest_batch.walk_state()`
    translates once, at the walk's entrance; the candidate id rides along as
    `candidate_id`.
  * **where a recording is found** (`locate()`), first hit wins:
      1. the candidate's own `capture_file` - the path the recorder printed
         (`CaptureResult.file`), when whoever ran it wrote it on the candidate;
      2. `<batch dir>/captures/<file id>.mp4` - a recording made for this
         batch (`capture_tool.py <url> <batch dir>/captures ...`);
      3. `<factory root>/shared/own-captures/<file id>.mp4` - the factory's
         inbox, for a recording made outside a batch.
    The sidecar is always the one beside the mp4 (`<file id>.own_capture.json`).
  * **"download"** - nothing is downloaded: the finished recording and its
    sidecar are *copied* into the pool as `<pool>/<file id>.mp4` and
    `<pool>/<file id>.own_capture.json` (the Video Editor reads the sidecar
    there, `footage_credits.read_own_capture`). The recorder's copy is left
    where it is; the pool's is transient like any source's (CF-0358).
  * **the refusals** (`refusals()`), each a code and a sentence, before
    anything is copied: no recording at any of the places above
    (`no_recording`), no sidecar beside it (`no_sidecar`), a sidecar whose
    `origin` or `licence` is not `own_capture` or whose schema is not
    `own-capture/*` (`not_own_capture`), a sidecar `file_id` that is not this
    source's (`file_id_mismatch`), a file ffprobe finds no picture in
    (`no_picture`), and a length or frame size ffprobe disagrees with
    (`duration_mismatch`, `size_mismatch`).

No yt-dlp, no pacing, no stop rule (the owner is
the factory), no duration ceiling (`sources.youtube.max_source_duration_seconds`
is YouTube's) and no source sieve (the page is the footage - `source_sieve`
keeps it by its kind). The cam-rip rule (`screen_recording.py`) exempts it by
its kind too.
"""
import json
import re
from pathlib import Path

OWN_CAPTURE = "own_capture"            # the licence, the origin, the kind
CANDIDATE_HEAD = "own_capture:"        # the Trend Hunter's id: own_capture:<id>
FILE_HEAD = "own_capture-"             # on disk, clip names, shot keys
SIDECAR_SUFFIX = ".own_capture.json"   # VE _clip_names.OWN_CAPTURE_SIDECAR_SUFFIX
SCHEMA_PREFIX = "own-capture/"         # capture_tool.SCHEMA is "own-capture/1"
MEASURE = "own_capture"                # ingest_batch's `measured_from` for one

CAPTURE_FILE_KEY = "capture_file"      # the candidate's path to the recording
BATCH_SUBDIR = "captures"              # <batch dir>/captures/
INBOX_REL = Path("shared") / "own-captures"

UNSAFE = re.compile(r"[^A-Za-z0-9_-]")

# How far ffprobe's length may stand from the recorder's `duration_s`: the
# recorder measures the screencast's clock, ffmpeg lays the frames out at a
# constant 30 fps (capture_tool.frame_sequence), so the two differ by a frame
# or two - never by a second, nor by a tenth of a long take.
DURATION_TOLERANCE_S = 1.0
DURATION_TOLERANCE_SHARE = 0.10

NO_RECORDING = "no_recording"
NO_SIDECAR = "no_sidecar"
NOT_OWN_CAPTURE = "not_own_capture"
FILE_ID_MISMATCH = "file_id_mismatch"
NO_PICTURE = "no_picture"
DURATION_MISMATCH = "duration_mismatch"
SIZE_MISMATCH = "size_mismatch"
REFUSED_CODE = "own_capture_refused"   # the line's word, `OWN_CAPTURE_REFUSED`


# ---------------------------------------------------------------------------
# ids
# ---------------------------------------------------------------------------

def is_own_capture(vid):
    """True for `own_capture:<id>` (the candidate's name) and
    `own_capture-<id>` (the file id)."""
    s = str(vid or "")
    return ((s.startswith(CANDIDATE_HEAD) and len(s) > len(CANDIDATE_HEAD))
            or (s.startswith(FILE_HEAD) and len(s) > len(FILE_HEAD)))


def file_id(vid):
    """`own_capture:<id>` -> `own_capture-<id>` (every character outside
    [A-Za-z0-9_-] made `_`); a file id, or anything that is not an own
    capture, is returned as it is."""
    s = str(vid or "")
    if s.startswith(CANDIDATE_HEAD) and len(s) > len(CANDIDATE_HEAD):
        return FILE_HEAD + UNSAFE.sub("_", s[len(CANDIDATE_HEAD):])
    return s


def candidate_name(vid):
    """`own_capture-<id>` -> `own_capture:<id>` (the name the sidecar's `id`
    and the Trend Hunter use); a candidate name is returned as it is."""
    s = str(vid or "")
    if s.startswith(FILE_HEAD):
        return CANDIDATE_HEAD + s[len(FILE_HEAD):]
    return s


def sidecar_path(mp4):
    """`<dir>/own_capture-<id>.mp4` -> `<dir>/own_capture-<id>.own_capture.json`."""
    p = Path(mp4)
    return p.with_name(p.stem + SIDECAR_SUFFIX)


def read_sidecar(path):
    """The sidecar at `path` (or beside the mp4 `path`) as a dict, else None."""
    p = Path(path)
    if not p.name.endswith(SIDECAR_SUFFIX):
        p = sidecar_path(p)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# where a recording is
# ---------------------------------------------------------------------------

def inbox_dir(root=None):
    """`<factory root>/shared/own-captures` (FACTORY_ROOT, else this checkout's
    root - `_fi_paths.checkout_root()`)."""
    if root is None:
        from _fi_paths import checkout_root
        root = checkout_root()
    return Path(root) / INBOX_REL


def capture_dirs(batch_dir=None, root=None):
    """The directories a recording is looked for in, in order: the batch's
    `captures/` (when the batch is known), then the factory's inbox."""
    dirs = []
    if batch_dir:
        dirs.append(Path(batch_dir) / BATCH_SUBDIR)
    dirs.append(inbox_dir(root))
    return dirs


def locate(vid, record=None, dirs=()):
    """The recording of source `vid` (an mp4 path), or None. The candidate's
    `capture_file` first, then `<dir>/<file id>.mp4` for each of `dirs`."""
    fid = file_id(vid)
    rec = record if isinstance(record, dict) else {}
    named = rec.get(CAPTURE_FILE_KEY)
    if isinstance(named, str) and named.strip():
        p = Path(named).expanduser()
        if p.is_file() and p.stat().st_size > 0:
            return p
    for d in dirs or ():
        p = Path(d) / f"{fid}.mp4"
        if p.is_file() and p.stat().st_size > 0:
            return p
    return None


# ---------------------------------------------------------------------------
# the refusals
# ---------------------------------------------------------------------------

def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def sidecar_refusals(vid, sidecar):
    """[(code, sentence)] of what is wrong with `sidecar` for source `vid`
    before the file itself is probed; [] when it may be taken."""
    fid = file_id(vid)
    if not isinstance(sidecar, dict):
        return [(NO_SIDECAR, f"no readable {fid}{SIDECAR_SUFFIX} beside the recording - "
                             "the recorder writes one with every take, and a "
                             "recording without it has no page, host or robots read "
                             "on record")]
    out = []
    origin, licence = sidecar.get("origin"), sidecar.get("licence")
    schema = str(sidecar.get("schema") or "")
    if origin != OWN_CAPTURE or licence != OWN_CAPTURE or not schema.startswith(SCHEMA_PREFIX):
        out.append((NOT_OWN_CAPTURE,
                    f"the sidecar of {fid} says origin {origin!r}, licence {licence!r}, "
                    f"schema {schema or None!r} - an own capture is origin and licence "
                    f"'own_capture' under schema '{SCHEMA_PREFIX}*'"))
    side_fid = sidecar.get("file_id")
    if side_fid != fid:
        out.append((FILE_ID_MISMATCH,
                    f"the sidecar names file_id {side_fid!r}, the source is {fid!r} - "
                    "it describes another recording"))
    return out


def probe_refusals(vid, sidecar, info):
    """[(code, sentence)] where ffprobe's `info` ({duration, width, height})
    disagrees with the sidecar; [] when they agree."""
    fid = file_id(vid)
    if not info:
        return [(NO_PICTURE, f"ffprobe finds no picture in the recording of {fid}")]
    out = []
    said, got = (sidecar or {}).get("duration_s"), info.get("duration")
    if _num(said) and said > 0:
        tol = max(DURATION_TOLERANCE_S, DURATION_TOLERANCE_SHARE * float(said))
        if not _num(got) or abs(float(got) - float(said)) > tol:
            out.append((DURATION_MISMATCH,
                        f"the sidecar says {said} s, ffprobe reads {got} s in the file "
                        f"(more than {round(tol, 2)} s apart) - the mp4 is not the take "
                        "the sidecar describes"))
    else:
        out.append((DURATION_MISMATCH, f"the sidecar of {fid} carries no duration_s "
                                       "to hold the file against"))
    sw, sh = (sidecar or {}).get("width"), (sidecar or {}).get("height")
    if (sw, sh) != (info.get("width"), info.get("height")):
        out.append((SIZE_MISMATCH,
                    f"the sidecar says {sw}x{sh}, ffprobe reads "
                    f"{info.get('width')}x{info.get('height')}"))
    return out


def refused_line(vid, refusals):
    """One stderr line naming every refusal (the last line the caller reads)."""
    codes = ",".join(c for c, _ in refusals)
    why = "; ".join(s for _, s in refusals)
    return (f"{REFUSED_CODE}: {file_id(vid)} not taken ({codes}): {why} (CF-0567, "
            "nothing copied into the pool)")


# ---------------------------------------------------------------------------
# the cache entry's block
# ---------------------------------------------------------------------------

SIDECAR_SUMMARY_KEYS = ("id", "file_id", "url", "final_url", "host", "capture_host",
                        "captured_at", "duration_s", "width", "height", "fps",
                        "capped", "channel", "recorder")


def summary(sidecar, source=None):
    """The `own_capture` block of a cache entry: what the sidecar says that a
    reader of the index needs without opening it, and where it came from."""
    side = sidecar if isinstance(sidecar, dict) else {}
    out = {k: side.get(k) for k in SIDECAR_SUMMARY_KEYS}
    out["space_licence"] = ((side.get("space") or {}).get("licence")
                            if isinstance(side.get("space"), dict) else None)
    if source is not None:
        out["copied_from"] = str(source)
    return out
