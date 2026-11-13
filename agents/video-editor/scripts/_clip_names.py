"""CF-0665: the one reading of a source id inside a clip name.

Every cut clip / held frame the Editor writes carries its source id between
an attempt prefix and the `_sNNN` shot suffix (`a00_<id>_s009.mp4`,
`nc01_<id>_s008.mp4`, `open_left_<id>_s003.mp4`,
`s01_held_a01_<id>_s011.png`). Two shapes of id exist:

* a YouTube id - exactly 11 chars of `[A-Za-z0-9_-]`, which is what keeps it
  unambiguous even when it holds underscores itself (`H6RXVb_J5J4`);
* an archive file the Footage Indexer downloads directly (FI f537616):
  `nasa-<id>` or `commons-<pageid>`, everything outside `[A-Za-z0-9_-]`
  replaced by `_` - any length (`nasa-Artemis_II_Science_-_AVATAR_Vertical_Video`,
  `commons-151359165`);
* the factory's own screen recording (CF-0567, `docs/tech-footage.md` of the
  root): `own_capture-<id>` on disk, `own_capture:<id>` as the Trend
  Hunter / Footage Indexer name it (the `:` is not allowed on disk - the
  `<source>:<shot>` keys split on it, as for `nasa:` / `commons:`). The
  recorder (`capture_tool.py`) names its files so; `<id>` is
  `<page slug>-<UTC stamp>`, `[a-z0-9-]`.

The archive shape is read first and over the whole name: an 11-char window
would otherwise take the tail of an archive id (`s-151359165` out of
`a00_commons-151359165_s053`) or a prefix glued to a short one
(`a00_nasa-ab` out of `a00_nasa-ab_s001`). A name without an archive id is
read exactly as before - the 11-char rule, nothing looser.

retired_shots.py, entity_guard.py and source_gate.py take it from here.
"""
import re

YOUTUBE_ID = r"[A-Za-z0-9_-]{11}"
# CF-0567: `own_capture-<id>` reads like an archive file id (any length,
# prefix first) - it is a file the factory itself wrote, not an upload.
OWN_CAPTURE_PREFIX = "own_capture-"
OWN_CAPTURE_NAME = "own_capture:"
# The recording's record beside its mp4 (`capture_tool.py` writes it, the
# Footage Indexer keeps it beside `<id>.mp4` in the pool).
OWN_CAPTURE_SIDECAR_SUFFIX = ".own_capture.json"
ARCHIVE_ID = r"(?:nasa|commons|own_capture)-[A-Za-z0-9_-]+"
# An id-shaped token, archive shape first (the alternation is ordered).
SOURCE_ID = rf"(?:{ARCHIVE_ID}|{YOUTUBE_ID})"

_ARCHIVE_CLIP = re.compile(rf"(?:^|_)(?P<vid>{ARCHIVE_ID})_s(?P<n>\d+)$")
_YOUTUBE_CLIP = re.compile(rf"(?:^|_)(?P<vid>{YOUTUBE_ID})_s(?P<n>\d+)$")
_SOURCE_ID_FULL = re.compile(SOURCE_ID)


def clip_shot(stem, min_digits=1):
    """`(source id, shot number as written)` out of a clip/frame stem
    (`a00_<id>_s009` -> `(<id>, "009")`), or None. `min_digits` is the
    least number of shot digits the caller accepts."""
    if not isinstance(stem, str) or not stem:
        return None
    m = _ARCHIVE_CLIP.search(stem) or _YOUTUBE_CLIP.search(stem)
    if m and len(m.group("n")) >= min_digits:
        return m.group("vid"), m.group("n")
    return None


def is_source_id(value):
    """True when `value` as a whole is id-shaped (a bare media stem)."""
    return isinstance(value, str) and bool(_SOURCE_ID_FULL.fullmatch(value))


def is_own_capture(vid):
    """CF-0567: True for a source id of the factory's own screen recording -
    `own_capture-<id>` (on disk, in clip names and shot keys) or
    `own_capture:<id>` (the Trend Hunter's / Footage Indexer's name)."""
    return isinstance(vid, str) and (vid.startswith(OWN_CAPTURE_PREFIX)
                                     or vid.startswith(OWN_CAPTURE_NAME))


OWN_CAPTURE_KIND = "own_capture"   # footage-indexer's shots.json `source_kind`


def is_own_capture_shot(shot=None, source=None):
    """CF-0567 (FI 14c4ff4): a shot of the factory's own screen recording -
    the shots.json entry says `source_kind: own_capture`, or the source it
    is read from (a `<id>:<n>` key, a media path, a clip name, a bare id)
    is `own_capture-<id>`. By kind only: never by what the frame shows."""
    if isinstance(shot, dict) and shot.get("source_kind") == OWN_CAPTURE_KIND:
        return True
    if not source:
        return False
    s = str(source).strip()
    if is_own_capture(s):
        return True
    head = s.split(":")[0] if ":" in s and "/" not in s else s
    stem = head.rsplit("/", 1)[-1]
    stem = stem.rsplit(".", 1)[0] if "." in stem else stem
    if is_own_capture(stem):
        return True
    hit = clip_shot(stem)
    return bool(hit) and is_own_capture(hit[0])


def own_capture_file_id(capture_id):
    """`own_capture:<id>` / `own_capture-<id>` / a bare `<id>` -> the on-disk
    `own_capture-<id>`, every character outside [A-Za-z0-9_-] made `_` (the
    archive files' rule, footage-indexer archive_source.file_id)."""
    s = str(capture_id or "")
    for head in (OWN_CAPTURE_NAME, OWN_CAPTURE_PREFIX):
        if s.startswith(head):
            s = s[len(head):]
            break
    return OWN_CAPTURE_PREFIX + re.sub(r"[^A-Za-z0-9_-]", "_", s)
