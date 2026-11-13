#!/usr/bin/env python3
"""CF-0114: the factory insert library `shared/inserts/` - schema, rotation,
blacklist check, provenance. Stdlib only, importable from any agent repo via
`sys.path.insert(0, "<root>/shared/inserts")`.

This file *is* the schema of `index.json`, in the same sense that
`inserts/validate_inserts.py` is the schema of the insert-layer vocabulary:
there is no prose copy. The rule the schema serves is prose, and lives in
`inserts/POLICY.md`.

--------------------------------------------------------------------------
Layout
--------------------------------------------------------------------------

    shared/inserts/
      loops/index.json     kind "loop"   - silent underlay footage (CF-0014)
      memes/index.json     kind "meme"   - meme templates (CF-0067)
      sounds/index.json    kind "sound"  - <= 1.5 s recognisable sounds (CF-0068)

Media files sit next to their index and are **never tracked** (`.gitignore`:
`shared/inserts/*/*` minus `index.json`) - the same approach as
`shared/footage/`. The index is the record; the folder is the library.
Removing a file after a claim is deleting it from the folder and its entry
from the index - there is no separate "removed" list.

--------------------------------------------------------------------------
index.json
--------------------------------------------------------------------------

    {
      "schema_note": str            free text for the reader
      "kind": "loop"|"meme"|"sound" the folder's kind; every entry repeats it
      "embedding_model": str|null   set by scripts/index_inserts.py
      "entries": [ <entry>, ... ]
    }

An entry - required:

    id             str, unique in the index; [a-z0-9][a-z0-9_-]*
    file           str, filename relative to the index's folder (no dirs)
    kind           str, equal to the index's kind
    description    non-empty str, in words, written by a person - what the
                   material shows / sounds like. This is what a text query
                   is matched against, so it is prose, not a slug.
    tags           list of non-empty str (may be empty)
    source_url     str, http(s) URL of where the file was taken from
    rights_holder  non-empty str - who holds the rights, as best known.
                   The one field the blacklist check reads. Loops and sounds
                   only: a meme carries no rights-holder entry
                   (POLICY.md, 2026-09-24) - on a meme the field may be
                   absent or null, and a value written earlier is kept as
                   information.
    added          "YYYY-MM-DD"

Optional:

    licence        str|null - recorded where one exists, not required
                   (POLICY.md). "Public domain", "CC BY-SA 4.0", ...
    medium         str|null - blacklist medium the material belongs to
                   (`games_ip`, `film_tv`, `sports`, `music`, ...); lets the
                   check tell a music division from a film one. Null means
                   "match on the name alone", which is the cautious side.
    download_url   str|null - direct media URL for scripts/fetch_inserts.py
                   when `source_url` is a page rather than a file
    embedding      list of EMBEDDING_DIM floats, L2-normalised, 5 decimals -
                   written by scripts/index_inserts.py with the same CLIP
                   model, normalisation and rounding as
                   agents/footage-indexer, so that a text query embedded
                   there ranks these entries by plain dot product.
                   Images, GIFs (first frame) and loop videos (one frame).
    duration_s     float - sounds only, measured by index_inserts.py, must
                   be <= MAX_SOUND_SECONDS. Required for kind "sound".
    clip           {"start_s": float, "end_s": float} - memes only: the GIF
                   was cut by the factory from the video at `source_url`
                   over this span (silent). Such a file cannot be fetched as
                   a file; scripts/fetch_inserts.py names the span to recut.
    review         "pending" - memes only: added by scripts/meme_desk.py and
                   not yet accepted by the user on the desk page; `apply`
                   removes it on accept and the entry with its file on
                   reject. The meme layer does not read it.
    cutout         bool - memes only: the picture may be cut out along its
                   subject's contour and laid over the frame (CF-0380).
                   Absent or false means whole picture only. Set by a
                   person; a GIF is never a cutout.
    cutout_asset   object - memes with `cutout: true` only (CF-0403): the
                   foreground cut written by `scripts/meme_desk.py cutout`.
                     file            "<id>.cutout.png" beside the source (RGBA,
                                     cropped to the silhouette), or null when
                                     the cut was refused - the meme stays whole
                     refused         why (only, and always, when file is null)
                     source_sha256   the source file the cut was made from; a
                                     changed source is cut again
                     method          CUTOUT_METHOD of meme_desk.py
                     made            YYYY-MM-DD
                     coverage        fraction of the frame under the silhouette
                     bbox_px         [x, y, w, h] of the silhouette in source
                                     pixels - the cutout file is w x h (with file)
                     source_size_px  [w, h] of the source; parts, edge_noise,
                                     soft - the machine check's measures
    notes          free text

--------------------------------------------------------------------------
What the consumers call
--------------------------------------------------------------------------

    load_index(kind)                         the folder's index.json
    meme_bank_folder(channel_cfg)            (bank, folder) of a channel's
                                             memes: its own bank (CF-0393)
                                             or the default memes/
    blacklist_check(rights_holder, medium, blacklist)
                                             one file against a channel's list
    check_for(entry)                         the check, or blacklist_not_applied()
                                             for a meme (CF-0389)
    eligible(entries, blacklist)             -> (kept, skipped provenance);
                                             never skips a meme
    pick_loop(video_id, entries)             deterministic, uniform rotation
    choose_loop(video_id)                    load + eligible + pick_loop
    rank_by_embedding(entries, query_vec)    match_anchors-style ranking
    provenance_record(entry, check)          the record for 05-*.json

Provenance (item 7 of CF-0114): one shape for any insert, whatever its kind,
written by the consumer into `05-video-editor.json` under
`videos[].<PROVENANCE_FIELD>` - one record per insert *considered*, skipped
ones included, because a skipped file is exactly what the Analyst (CF-0022)
needs to see when a claim comes in for the file that was used instead:

    {
      "kind": "meme", "id": "...", "file": "...",
      "source_url": "...", "rights_holder": "..."|null, "licence": "..."|null,
      "blacklist_check": {
        "applied": bool,        # false on a meme: not applied (CF-0389),
                                # with "not_applied": <why>, skip false
        "matched": bool, "matched_entry": str|null, "matched_medium": str|null,
        "risk_level": "high"|"medium"|null, "skip": bool,
        "medium": str|null, "blacklist_updated": "YYYY-MM-DD"|null
      },
      "skipped": bool,          # true when blacklist_check.skip
      "block": int|null         # set by the consumer: which block it sat in
    }
"""
import hashlib
import json
import re
import subprocess
import wave
from datetime import date
from pathlib import Path

INSERTS_ROOT = Path(__file__).resolve().parent
REPO = INSERTS_ROOT.parent.parent
# CF-0561/CF-0631: the rights holders are a channel's list
# (`channels/<id>/rights-holder-blacklist.json`, read through
# `shared/channel_data.py`). This module keeps the common *format* and the
# check; it has no default list and no common path - every caller hands in
# the list of the channel it works for (underlay.py, the Video Editor's sound
# and proof layers), and a check asked for without one is refused
# (`_the_list`), never run against somebody else's channel.
NO_LIST = ("no rights-holder list handed in: the list is a channel's "
           "(channels/<id>/rights-holder-blacklist.json, CF-0561) and there is no "
           "common default (CF-0631) - pass the channel's list")

# kind -> folder. Closed on purpose: a fourth layer is a decision (CF-0012's
# argument), not a directory somebody creates.
KIND_FOLDERS = {"loop": "loops", "meme": "memes", "sound": "sounds"}
FOLDER_KINDS = {v: k for k, v in KIND_FOLDERS.items()}

MAX_SOUND_SECONDS = 1.5          # CF-0068: the user's accepted mitigation
EMBEDDING_DIM = 512              # openai/clip-vit-base-patch32
EMBEDDING_MODEL = "openai/clip-vit-base-patch32"
EMBEDDING_DECIMALS = 5           # same rounding as index_footage.py

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
SOUND_SUFFIXES = {".wav", ".mp3", ".ogg", ".m4a", ".flac", ".aac", ".opus"}

REQUIRED_ENTRY_KEYS = ("id", "file", "kind", "description", "tags",
                       "source_url", "rights_holder", "added")
OPTIONAL_ENTRY_KEYS = ("licence", "medium", "download_url", "embedding",
                       "duration_s", "clip", "cutout", "cutout_asset", "review", "notes")
CUTOUT_ASSET_KEYS = {"file", "refused", "source_sha256", "method", "made", "coverage",
                     "bbox_px", "source_size_px", "parts", "edge_noise", "soft"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
# A meme carries no rights-holder entry (POLICY.md, 2026-09-24): the one required key
# a meme entry may leave out.
MEME_OPTIONAL_KEYS = ("rights_holder",)

PROVENANCE_FIELD = "inserts"     # videos[].inserts[] in 05-video-editor.json

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------

def folder_for(kind, root=INSERTS_ROOT, bank=None):
    """The folder of `kind` under `root`. `bank` (CF-0393) names a channel's
    own meme bank - a folder `memes-<channel>` beside the default one; only a
    meme has banks, and a malformed name is refused, never guessed at."""
    if kind not in KIND_FOLDERS:
        raise ValueError(f"unknown insert kind {kind!r}; one of {sorted(KIND_FOLDERS)}")
    if bank is None or bank == KIND_FOLDERS[kind]:
        return Path(root) / KIND_FOLDERS[kind]
    if kind != "meme":
        raise MemeBankError(f"only the meme layer has per-channel banks, not {kind!r}")
    return Path(root) / bank_name(bank)


def index_path(kind, root=INSERTS_ROOT, bank=None):
    return folder_for(kind, root, bank) / "index.json"


# --------------------------------------------------------------------------
# CF-0393: a channel's own meme bank
# --------------------------------------------------------------------------
#
# The meme layer reads one folder per channel. A channel that says nothing
# reads the factory's default folder `shared/inserts/memes/` - ExampleFilm's
# cinema bank, unchanged. A channel that names a bank in
# `insert_layers.meme.bank` (grill 2026-10-06 Q18: ExampleTech's memes come
# from its own bank, in a tech audience's register) reads that folder and
# nothing else: a named bank that is not on disk is an error the caller
# reports, never a quiet fallback to the cinema bank - a cinema meme in a
# tech video is exactly what the bank exists to prevent.
#
# A bank is a sibling of the default folder, `shared/inserts/memes-<slug>/`,
# with its own tracked `index.json` and untracked media (.gitignore
# `shared/inserts/*/*`, agents.lock.json `links`) - the same layout, so every
# tool that works on the default folder works on a bank given its name.

MEME_BANK_KEY = "bank"                       # insert_layers.meme.bank
MEME_BANK_PREFIX = "shared/inserts/"         # how a channel config names it
BANK_NAME_RE = re.compile(r"^memes-[a-z0-9][a-z0-9-]*$")


class MemeBankError(ValueError):
    """A named meme bank that is malformed or not on disk."""


def bank_name(bank):
    """`memes-<slug>` from a bank as a config or a command line names it:
    `shared/inserts/memes-example-tech/` or `memes-example-tech`. The default
    folder answers `memes`. Anything else - another directory, a path that
    climbs out, a bare channel id - is refused."""
    if not isinstance(bank, str) or not bank.strip():
        raise MemeBankError(f"meme bank must be a folder name, got {bank!r}")
    name = bank.strip().rstrip("/")
    if name.startswith(MEME_BANK_PREFIX):
        name = name[len(MEME_BANK_PREFIX):]
    if name == KIND_FOLDERS["meme"] or BANK_NAME_RE.match(name):
        return name
    raise MemeBankError(
        f"meme bank {bank!r} is not a folder {MEME_BANK_PREFIX}memes-<channel>/ "
        f"(insert_layers.meme.{MEME_BANK_KEY}, CF-0393)")


def channel_meme_bank(channel_cfg):
    """The bank a channel config names in insert_layers.meme.bank, as a
    folder name; None when it names none (the default folder). Malformed
    names raise MemeBankError."""
    layers = (channel_cfg or {}).get("insert_layers") if isinstance(channel_cfg, dict) else None
    layer = layers.get("meme") if isinstance(layers, dict) else None
    bank = layer.get(MEME_BANK_KEY) if isinstance(layer, dict) else None
    if bank is None:
        return None
    name = bank_name(bank)
    return None if name == KIND_FOLDERS["meme"] else name


def meme_bank_folder(channel_cfg=None, root=INSERTS_ROOT, bank=None):
    """(bank name or None, folder) the meme layer reads for this channel -
    or for `bank` when one is named outright (the desk's --bank). A named
    bank must have its index.json on disk: MemeBankError otherwise, with no
    fallback to the default folder."""
    name = bank_name(bank) if bank is not None else channel_meme_bank(channel_cfg)
    if name == KIND_FOLDERS["meme"]:
        name = None
    folder = folder_for("meme", root, name)
    if name is not None and not (folder / "index.json").exists():
        raise MemeBankError(
            f"meme bank {name!r} has no index.json at {folder} - the channel's "
            f"memes come from its own bank only, never from the default "
            f"{MEME_BANK_PREFIX}{KIND_FOLDERS['meme']}/ (CF-0393)")
    return name, folder


def meme_banks(root=INSERTS_ROOT):
    """Names of the per-channel meme banks on disk (folders with an index)."""
    return sorted(p.parent.name for p in Path(root).glob("memes-*/index.json")
                  if BANK_NAME_RE.match(p.parent.name))


def empty_index(kind):
    return {
        "schema_note": "CF-0114 insert library index; schema is "
                       "shared/inserts/inserts_lib.py, rule is inserts/POLICY.md. "
                       "Media files live beside this file and are not tracked.",
        "kind": kind,
        "embedding_model": None,
        "entries": [],
    }


def load_index(kind, root=INSERTS_ROOT, bank=None):
    """The folder's index.json, or an empty index when there is none yet.
    A named meme bank without an index is not "empty" but missing - callers
    that must not fall back resolve it with meme_bank_folder() first."""
    path = index_path(kind, root, bank)
    if not path.exists():
        return empty_index(kind)
    return json.loads(path.read_text())


def save_index(index, kind, root=INSERTS_ROOT, bank=None):
    """Write the index with a stable layout, so that a re-run with nothing
    to change produces no diff (idempotence is checked by the tests)."""
    path = index_path(kind, root, bank)
    path.parent.mkdir(parents=True, exist_ok=True)
    index["entries"] = sorted(index["entries"], key=lambda e: e["id"])
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n")
    return path


def entry_path(entry, kind, root=INSERTS_ROOT, bank=None):
    return folder_for(kind, root, bank) / entry["file"]


# --------------------------------------------------------------------------
# schema
# --------------------------------------------------------------------------

def _str(errs, obj, key, ctx, nonempty=True, nullable=False):
    v = obj.get(key)
    if v is None and nullable:
        return
    if not isinstance(v, str) or (nonempty and not v.strip()):
        errs.append(f"{ctx}: {key} must be a non-empty string")


def validate_entry(entry, kind, folder=None):
    """Errors for one entry. `folder` is optional: when given, a missing
    file is reported too (the index is tracked, the media is not, so the
    check is a choice of the caller, not of the schema)."""
    errs = []
    ctx = f"{kind}:{entry.get('id', '?')}"
    if not isinstance(entry, dict):
        return [f"{ctx}: entry is not an object"]
    for key in REQUIRED_ENTRY_KEYS:
        if key not in entry and not (kind == "meme" and key in MEME_OPTIONAL_KEYS):
            errs.append(f"{ctx}: missing required field {key!r}")
    unknown = set(entry) - set(REQUIRED_ENTRY_KEYS) - set(OPTIONAL_ENTRY_KEYS)
    for key in sorted(unknown):
        errs.append(f"{ctx}: unknown field {key!r}")
    if errs:
        return errs

    if not isinstance(entry["id"], str) or not ID_RE.match(entry["id"]):
        errs.append(f"{ctx}: id must match {ID_RE.pattern}")
    if entry["kind"] != kind:
        errs.append(f"{ctx}: kind {entry['kind']!r} != index kind {kind!r}")
    f = entry["file"]
    if not isinstance(f, str) or not f or "/" in f or f.startswith("."):
        errs.append(f"{ctx}: file must be a bare filename inside the folder")
    else:
        suffix = Path(f).suffix.lower()
        allowed = SOUND_SUFFIXES if kind == "sound" else IMAGE_SUFFIXES | VIDEO_SUFFIXES
        if kind == "meme":
            allowed = IMAGE_SUFFIXES
        if suffix not in allowed:
            errs.append(f"{ctx}: {f!r} has suffix {suffix!r}, not one a {kind} may have")
        if folder is not None and not (Path(folder) / f).exists():
            errs.append(f"{ctx}: file {f!r} is not in {folder}")
    _str(errs, entry, "description", ctx)
    _str(errs, entry, "source_url", ctx)
    if isinstance(entry.get("source_url"), str) and not entry["source_url"].startswith(("http://", "https://")):
        errs.append(f"{ctx}: source_url must be an http(s) URL")
    _str(errs, entry, "rights_holder", ctx, nullable=(kind == "meme"))
    if not isinstance(entry.get("added"), str) or not DATE_RE.match(entry["added"]):
        errs.append(f"{ctx}: added must be YYYY-MM-DD")
    tags = entry.get("tags")
    if not isinstance(tags, list) or any(not isinstance(t, str) or not t.strip() for t in tags):
        errs.append(f"{ctx}: tags must be a list of non-empty strings")
    _str(errs, entry, "licence", ctx, nullable=True)
    _str(errs, entry, "medium", ctx, nullable=True)
    _str(errs, entry, "download_url", ctx, nullable=True)
    _str(errs, entry, "notes", ctx, nullable=True, nonempty=False)
    if "clip" in entry:
        c = entry["clip"]
        if kind != "meme":
            errs.append(f"{ctx}: clip is a meme field")
        elif not (isinstance(f, str) and f.lower().endswith(".gif")):
            errs.append(f"{ctx}: clip describes a GIF cut from a video; {f!r} is not a GIF")
        elif (not isinstance(c, dict) or set(c) != {"start_s", "end_s"}
              or not all(isinstance(c[k], (int, float)) and not isinstance(c[k], bool) for k in c)
              or not 0 <= c["start_s"] < c["end_s"]):
            errs.append(f"{ctx}: clip must be {{start_s, end_s}} with 0 <= start_s < end_s")
    if "review" in entry:
        if kind != "meme":
            errs.append(f"{ctx}: review is a meme field")
        elif entry["review"] != "pending":
            errs.append(f"{ctx}: review may only be 'pending' (absent once accepted)")
    if "cutout" in entry:
        if kind != "meme":
            errs.append(f"{ctx}: cutout is a meme field")
        elif not isinstance(entry["cutout"], bool):
            errs.append(f"{ctx}: cutout must be true or false")
        elif entry["cutout"] and isinstance(f, str) and f.lower().endswith(".gif"):
            errs.append(f"{ctx}: a GIF is inserted whole, never as a cutout")
    if "cutout_asset" in entry:
        if kind != "meme" or entry.get("cutout") is not True:
            errs.append(f"{ctx}: cutout_asset belongs to a meme with cutout: true only")
        else:
            errs.extend(_cutout_asset_errors(entry, ctx, folder))

    emb = entry.get("embedding")
    if emb is not None:
        if (not isinstance(emb, list) or len(emb) != EMBEDDING_DIM
                or any(not isinstance(x, (int, float)) for x in emb)):
            errs.append(f"{ctx}: embedding must be a list of {EMBEDDING_DIM} floats")
        elif kind == "sound":
            errs.append(f"{ctx}: a sound has no image embedding")

    dur = entry.get("duration_s")
    if kind == "sound":
        if dur is None:
            errs.append(f"{ctx}: duration_s missing - run scripts/index_inserts.py to measure it")
        elif not isinstance(dur, (int, float)) or dur <= 0:
            errs.append(f"{ctx}: duration_s must be a positive number")
        elif dur > MAX_SOUND_SECONDS:
            errs.append(f"{ctx}: duration_s {dur} exceeds the {MAX_SOUND_SECONDS} s ceiling (CF-0068)")
    elif dur is not None and (not isinstance(dur, (int, float)) or dur <= 0):
        errs.append(f"{ctx}: duration_s must be a positive number")
    return errs


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _ints(x, n, positive_from=0):
    return (isinstance(x, list) and len(x) == n
            and all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in x)
            and all(v > 0 for v in x[positive_from:]))


def _cutout_asset_errors(entry, ctx, folder=None):
    """CF-0403: the cutout_asset record of a `cutout: true` meme."""
    a = entry["cutout_asset"]
    c = f"{ctx}: cutout_asset"
    if not isinstance(a, dict):
        return [f"{c} must be an object"]
    errs = [f"{c}: unknown field {k!r}" for k in sorted(set(a) - CUTOUT_ASSET_KEYS)]
    for k in ("file", "source_sha256", "method", "made", "coverage"):
        if k not in a:
            errs.append(f"{c}: missing {k!r}")
    if errs:
        return errs
    if not isinstance(a["source_sha256"], str) or not SHA256_RE.match(a["source_sha256"]):
        errs.append(f"{c}: source_sha256 must be 64 lowercase hex digits")
    if not isinstance(a["method"], str) or not a["method"]:
        errs.append(f"{c}: method must be a non-empty string")
    if not isinstance(a["made"], str) or not DATE_RE.match(a["made"]):
        errs.append(f"{c}: made must be YYYY-MM-DD")
    if not _num(a["coverage"]) or not 0 <= a["coverage"] <= 1:
        errs.append(f"{c}: coverage must be a fraction in [0, 1]")
    if "source_size_px" in a and not _ints(a["source_size_px"], 2):
        errs.append(f"{c}: source_size_px must be [w, h], positive integers")
    if "parts" in a and not (isinstance(a["parts"], int) and not isinstance(a["parts"], bool)
                             and a["parts"] >= 0):
        errs.append(f"{c}: parts must be a non-negative integer")
    for k in ("edge_noise", "soft"):
        if k in a and (not _num(a[k]) or a[k] < 0):
            errs.append(f"{c}: {k} must be a non-negative number")
    f = a["file"]
    if f is None:
        if not isinstance(a.get("refused"), str) or not a["refused"].strip():
            errs.append(f"{c}: a refused cut (file null) must say why in 'refused'")
        if "bbox_px" in a:
            errs.append(f"{c}: a refused cut has no bbox_px")
        return errs
    if f != f"{entry['id']}.cutout.png":
        errs.append(f"{c}: file must be {entry['id']}.cutout.png (or null when refused)")
    if "refused" in a:
        errs.append(f"{c}: an accepted cut (file set) has no 'refused'")
    if not _ints(a.get("bbox_px"), 4, positive_from=2):
        errs.append(f"{c}: bbox_px must be [x, y, w, h] in source pixels, w and h > 0")
    elif "source_size_px" in a and _ints(a["source_size_px"], 2):
        x, y, w, h = a["bbox_px"]
        sw, sh = a["source_size_px"]
        if x + w > sw or y + h > sh:
            errs.append(f"{c}: bbox_px runs outside the {sw}x{sh} source")
    if folder is not None and isinstance(f, str) and not (Path(folder) / f).exists():
        errs.append(f"{c}: file {f!r} is not in {folder}")
    return errs


def validate_index(index, kind, folder=None):
    errs = []
    if not isinstance(index, dict):
        return ["index is not an object"]
    if index.get("kind") != kind:
        errs.append(f"index kind {index.get('kind')!r} != {kind!r}")
    if not isinstance(index.get("schema_note"), str):
        errs.append("schema_note must be a string")
    if "embedding_model" in index and index["embedding_model"] not in (None, EMBEDDING_MODEL):
        errs.append(f"embedding_model {index['embedding_model']!r} is not {EMBEDDING_MODEL!r}; "
                    "vectors would not be comparable with the footage index")
    entries = index.get("entries")
    if not isinstance(entries, list):
        return errs + ["entries must be a list"]
    seen_ids, seen_files = {}, {}
    for entry in entries:
        errs += validate_entry(entry, kind, folder)
        if isinstance(entry, dict):
            eid, f = entry.get("id"), entry.get("file")
            if eid in seen_ids:
                errs.append(f"{kind}:{eid}: duplicate id")
            if f in seen_files:
                errs.append(f"{kind}:{eid}: file {f!r} already indexed as {seen_files[f]}")
            seen_ids[eid] = True
            seen_files[f] = eid
    return errs


# --------------------------------------------------------------------------
# sounds
# --------------------------------------------------------------------------

def measure_duration(path):
    """Seconds, from the WAV header when it is a WAV, else from ffprobe.
    Raises when neither can read the file."""
    path = Path(path)
    if path.suffix.lower() == ".wav":
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, timeout=60)
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"ffprobe could not read {path}: {out.stderr.strip()}")
    return float(out.stdout.strip())


# --------------------------------------------------------------------------
# blacklist
# --------------------------------------------------------------------------

def load_blacklist(path):
    """A rights-holder list in the common format, from its file - a channel's
    `channels/<id>/rights-holder-blacklist.json`. There is no default path."""
    return json.loads(Path(path).read_text())


def _the_list(blacklist):
    if blacklist is None:
        raise ValueError(NO_LIST)
    return blacklist


_PAREN_RE = re.compile(r"\([^)]*\)")
_SPACE_RE = re.compile(r"\s+")


def _norm(s):
    return _SPACE_RE.sub(" ", _PAREN_RE.sub("", s or "").lower()).strip()


def _holder_tokens(name):
    """'Nintendo / The Pokemon Company' -> ['nintendo', 'the pokemon company'];
    'Crunchyroll / Example Pictures (anime)' -> ['crunchyroll', 'example pictures']."""
    return [t for t in (_norm(p) for p in re.split(r"\s*[/,]\s*", name or "")) if t]


def blacklist_check(rights_holder, medium=None, blacklist=None):
    """One file's rights holder against a rights-holder list (the channel's,
    `channels/<id>/rights-holder-blacklist.json`, CF-0561 - the format is
    common).

    Case-insensitive; a slash- or comma-separated multi-name entry matches on
    any of its names, as a substring of the holder or with the holder as a
    substring of it. `medium` disambiguates the corporate families the
    blacklist's own schema_note warns about: when both sides name a medium
    and they differ, it is not a match. A holder with no medium matches on
    the name alone - the cautious side.

    Returns the record that goes into provenance; `skip` is the decision
    (only `risk_level: high` skips - a medium-risk match is recorded and
    passes, which is what "raise scrutiny" means).
    """
    bl = _the_list(blacklist)
    holder = _norm(rights_holder)
    medium_norm = _norm(medium) if medium else None
    result = {
        "applied": True,
        "matched": False, "matched_entry": None, "matched_medium": None,
        "risk_level": None, "skip": False, "medium": medium,
        "blacklist_updated": bl.get("last_updated"),
    }
    if not holder:
        return result
    best = None
    for entry in bl.get("entries", []):
        entry_medium = _norm(entry.get("medium"))
        if medium_norm and entry_medium and entry_medium != medium_norm:
            continue
        for token in _holder_tokens(entry.get("rights_holder")):
            if token in holder or (len(holder) >= 3 and holder in token):
                rank = 0 if entry.get("risk_level") == "high" else 1
                if best is None or rank < best[0]:
                    best = (rank, entry)
                break
    if best is not None:
        entry = best[1]
        result.update(matched=True, matched_entry=entry.get("rights_holder"),
                      matched_medium=entry.get("medium"),
                      risk_level=entry.get("risk_level"),
                      skip=entry.get("risk_level") == "high")
    return result


# --------------------------------------------------------------------------
# provenance
# --------------------------------------------------------------------------

# CF-0389 / inserts/POLICY.md amendment 2026-09-24: a meme has no rights
# holder for the factory's purposes, so the blacklist check is not applied to
# it. The record keeps blacklist_check()'s shape - the 05-video-editor.json
# contract and the Analyst read the same keys on every insert - and says in
# `applied: false` and `not_applied` that nothing was checked, which is a
# different fact from "checked and passed" and from a skip.
BLACKLIST_NOT_APPLIED_KINDS = ("meme",)
BLACKLIST_NOT_APPLIED_NOTE = ("not applied to memes: a meme carries no rights-holder entry "
                              "(inserts/POLICY.md, amendment 2026-09-24, CF-0389)")


def blacklist_not_applied(medium=None):
    """The blacklist_check()-shaped record of a check that was not run."""
    return {
        "applied": False, "not_applied": BLACKLIST_NOT_APPLIED_NOTE,
        "matched": False, "matched_entry": None, "matched_medium": None,
        "risk_level": None, "skip": False, "medium": medium,
        "blacklist_updated": None,
    }


def check_for(entry, blacklist=None):
    """The blacklist decision an entry's provenance carries: the check itself
    for a loop or a sound, blacklist_not_applied() for a meme."""
    if entry.get("kind") in BLACKLIST_NOT_APPLIED_KINDS:
        return blacklist_not_applied(entry.get("medium"))
    return blacklist_check(entry.get("rights_holder"), entry.get("medium"), blacklist)


def provenance_record(entry, check=None, block=None, blacklist=None):
    """The one record any insert writes into 05-video-editor.json (see the
    module docstring). `check` is a blacklist_check() result; when omitted
    it is computed here from the entry's rights_holder and medium."""
    if check is None:
        check = check_for(entry, blacklist)
    return {
        "kind": entry.get("kind"),
        "id": entry.get("id"),
        "file": entry.get("file"),
        "source_url": entry.get("source_url"),
        "rights_holder": entry.get("rights_holder"),
        "licence": entry.get("licence"),
        "blacklist_check": check,
        "skipped": bool(check.get("skip")),
        "block": block,
    }


def eligible(entries, blacklist=None):
    """Split entries into (kept, skipped) where skipped is a list of
    provenance records for the files the blacklist check refused. The
    consumer writes those records too: a claim on the file used instead is
    only explainable next to the file that was not.

    A meme is never skipped here (inserts/POLICY.md, amendment 2026-09-24,
    CF-0389): the check is not applied to it, so every meme is kept."""
    bl = None
    kept, skipped = [], []
    for entry in entries:
        if entry.get("kind") in BLACKLIST_NOT_APPLIED_KINDS:
            kept.append(entry)
            continue
        if bl is None:
            bl = _the_list(blacklist)
        check = blacklist_check(entry.get("rights_holder"), entry.get("medium"), bl)
        if check["skip"]:
            skipped.append(provenance_record(entry, check))
        else:
            kept.append(entry)
    return kept, skipped


# --------------------------------------------------------------------------
# matching
# --------------------------------------------------------------------------

def rank_by_embedding(entries, query_vec, top=None):
    """(score, entry) pairs, best first, by plain dot product of the entry's
    embedding with an L2-normalised query vector - the arithmetic of
    match_anchors.py, so a text embedded there ranks this library the same
    way it ranks footage. Entries without an embedding are left out."""
    scored = []
    for entry in entries:
        emb = entry.get("embedding")
        if not emb:
            continue
        score = sum(a * b for a, b in zip(emb, query_vec))
        scored.append((round(score, 4), entry))
    scored.sort(key=lambda p: (-p[0], p[1]["id"]))
    return scored[:top] if top else scored


# --------------------------------------------------------------------------
# rotation (loops)
# --------------------------------------------------------------------------

def rotation_position(video_id, n):
    """Stable slot in [0, n) for a video id: sha256 of the id modulo n.
    Uniform over the folder in expectation, the same slot every time for
    the same id, and independent of the process - no state, no ledger."""
    if n <= 0:
        raise ValueError("rotation over an empty folder")
    digest = hashlib.sha256(str(video_id).encode("utf-8")).hexdigest()
    return int(digest, 16) % n


def pick_loop(video_id, entries):
    """The loop for a video: deterministic in the id, uniform over the
    entries given, insensitive to their order. Returns the entry, or None
    when the folder is empty. Deleting a file from the folder is the whole
    removal mechanism - the mapping simply moves."""
    ordered = sorted(entries, key=lambda e: e["id"])
    if not ordered:
        return None
    return ordered[rotation_position(video_id, len(ordered))]


def choose_loop(video_id, root=INSERTS_ROOT, blacklist=None):
    """load_index('loop') -> eligible -> pick_loop.
    Returns (entry | None, skipped provenance records)."""
    kept, skipped = eligible(load_index("loop", root)["entries"], blacklist)
    return pick_loop(video_id, kept), skipped


# --------------------------------------------------------------------------
# CLI: validate the library on disk
# --------------------------------------------------------------------------

def validate_library(root=INSERTS_ROOT, check_files=False):
    """kind -> errors for every folder that has an index; a per-channel
    meme bank (CF-0393) is reported under its folder name, `memes-<slug>`."""
    report = {}
    for kind in KIND_FOLDERS:
        path = index_path(kind, root)
        if not path.exists():
            continue
        folder = path.parent if check_files else None
        report[kind] = validate_index(json.loads(path.read_text()), kind, folder)
    for name in meme_banks(root):
        path = index_path("meme", root, name)
        folder = path.parent if check_files else None
        report[name] = validate_index(json.loads(path.read_text()), "meme", folder)
    return report


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="validate shared/inserts/*/index.json")
    ap.add_argument("--root", default=str(INSERTS_ROOT))
    ap.add_argument("--check-files", action="store_true",
                    help="also require every indexed file to be present")
    args = ap.parse_args(argv)
    report = validate_library(Path(args.root), args.check_files)
    bad = 0
    for kind, errs in sorted(report.items()):
        bank = kind if kind not in KIND_FOLDERS else None
        n = len(load_index("meme" if bank else kind, Path(args.root), bank)["entries"])
        print(f"{kind}: {n} entries, {len(errs)} errors")
        for e in errs:
            print("  " + e)
        bad += len(errs)
    print(f"today {date.today().isoformat()}: {'OK' if not bad else f'{bad} errors'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
