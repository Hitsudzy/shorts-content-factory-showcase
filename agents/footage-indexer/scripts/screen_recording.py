#!/usr/bin/env python3
"""A shot filmed off a screen - the cinema "экранка" - named, not yet priced
(CF-0451, 2026-10-01).

The user rejected `vanguards-endgame-encore` of batch `example-film/2026-09-30T1248Z`
(acceptance log, `cam_rip_footage`): "взяты кадры съёмки на телефон в
кинозале, это плохой формат". Neither the sieve, nor QC, nor the frame judge
said a word. The source is `L2NAh3CIdig`, "Vanguards Endgame: Encore | Official
Trailer" - Zenith's own upload, so no title or channel check could have seen
it. Four of its 38 shots (2-5, 19.2-32.6 s) are its "AUDIENCE REACTION /
OPENING NIGHT 4.26.19" segment: the big screen filmed from the stalls, the
audience's heads in silhouette across the bottom. The Editor cut shots 2 and 3
into the hook (2.3-11.1 s of the video) - a phrase-picture match of 0.307,
because the describer had written exactly what was there: "Movie-theater shot:
silhouettes of audience heads in the foreground watching a big screen that
shows Captain America...". Nothing read that sentence as a defect.

**Where the answer comes from, in this order.**

  flag         `screen_recording` on the shot - the describer's boolean (see
               `shot_schema.SCREEN_RECORDING`, SKILL.md "Descriptions").
               `false` is an answer too and wins over the text below.
  description  the describer's own sentence, read by `DESCRIPTION_RE` - the
               way `shows_entity` falls back to a name in the description
               (CF-0344). This is what reaches the pool as it stands: no shot
               indexed before this task carries the flag, and the pool is not
               re-described or re-measured (CF-0410). `L2NAh3CIdig` is caught
               here, 4 of 4 shots, 0 others.

A pixel detector (screen trapezoid, dark auditorium band, heads, moiré) was
considered and not built: every signal it would read is shared by ordinary
footage - a letterboxed trailer has the dark band, a night scene the low
contrast, a found-footage film the shake - and it would mean pulling frames
off every shot of the pool, which the pool's transience rules out. The
describer is already looking at every tile, and on the one real case it had
already said "audience silhouettes watching a screen" four times.

The source level (`title_hit`) reads the candidate's title the way Trend
Hunter recorded it (`evidence.footage_candidates[].title`) for the words a
cam copy or a filmed-in-the-cinema reaction is uploaded under. It does not
fire on `L2NAh3CIdig` (an official trailer) and is there for the whole-source
case, the camrip or "IMAX audience reaction" upload.

**Price: none until the user signs one (CF-0320).** `mode()` reads
`shared/gate-prices.json`: a *signed* row `score.hard.screen_recording` makes
the shot hard (out, like `burned_text`), a signed `score.screen_recording`
makes it a soft rule at the row's price; with neither, the shot carries a
warning in `usability.warn[]`, stays in the pool at its old score, and the
sieve writes one `screen_recording` warning per source into `warnings[]`. The
code never writes that row.

**CF-0567: an own capture is exempt by its kind.** ExampleTech's own screen
recording (`own_capture-<id>`, the Video Editor's capture_tool.py) *is* a
screen - the describer will call a screen a screen, and that is the footage,
not a cam-rip. The exemption is decided by the source's kind and nothing else
(`exempt()`): the shot's `source_kind` (`own_capture`, written on every shot
of such a source by `index_footage.py` and `mark_kind()`, so a reader holding
a bare shot - the Video Editor's `shot_score` through `shot_usability.of` -
sees it), an index whose `source` file is `own_capture-<id>.*` or whose
`source_rights` name the licence or origin `own_capture`, or a caller that
passes such a video id or rights record. `DESCRIPTION_RE`, `TITLE_RE`, the
describer's flag and the signed price are untouched: a third party's clip
filmed off a screen is caught exactly as before.
"""
import json
import re
from pathlib import Path

TASK = "CF-0451"
RULE = "screen_recording"
FLAG = "screen_recording"            # the describer's boolean on a shot
PRICE_KEY = f"score.{RULE}"          # a signed penalty row
HARD_PRICE_KEY = f"score.hard.{RULE}"  # a signed hard row

MODE_HARD = "hard"
MODE_PENALTY = "penalty"
MODE_WARN = "warn"                   # no signed row: flag and warning only

BY_FLAG = "flag"
BY_DESCRIPTION = "description"

def _fi_paths():
    """CF-0620: this directory's `_fi_paths.py`, loaded by path - video-editor's
    `shot_score` loads this module by path with the indexer's scripts/ not on
    sys.path, so a plain `import _fi_paths` would fail there."""
    import importlib.util
    path = Path(__file__).resolve().with_name("_fi_paths.py")
    spec = importlib.util.spec_from_file_location("_fi_paths", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# CF-0620: the price table of the factory this checkout belongs to (a version
# worktree's own, or FACTORY_ROOT's), not the home checkout's.
PRICES_FILE = _fi_paths().prices_file()

# The describer's sentence about a shot filmed off a screen from the room.
# Tight on purpose: a scene *set* in a cinema ("stands in a movie theater
# lobby"), a talk-show or awards audience ("seated audience applauding"), a
# concert with a video wall behind the band, an "ONLY IN THEATERS" end card -
# none of them is a filmed screen, and each of them is in the pool (the scan
# of 2026-10-01 over 173 indexes, 5917 shots).
_GAP = r"[^.;]{0,60}?"
DESCRIPTION_RE = re.compile(
    r"(\baudience reaction\b"
    r"|\b(audience|crowd|viewers|moviegoers|heads|silhouettes)\b" + _GAP +
    r"\b(watch\w*|facing)\b" + _GAP + r"\b(big |giant |cinema |movie |"
    r"theat(?:er|re) |imax )?screen\b"
    r"|\b(filmed|shot|recorded|captured)\s+(off|from|of)\s+(a|the)\s+"
    r"(big |cinema |movie |theat(?:er|re) |tv |television |imax )?screen\b"
    r"|\b(phone|handheld|camcorder|smartphone)\b" + _GAP +
    r"\b(recording|footage|filming|pointed at)\b" + _GAP +
    r"\b(cinema|theat(?:er|re)|(big|movie|cinema|tv|imax) screen)\b"
    r"|\b(cam[- ]?rip|camcorder copy|bootleg recording|telesync)\b"
    r"|\bscreen\b" + _GAP + r"\b(keystone\w*|trapezoid\w*|moir[e\u00e9])\b"
    r"|\b(keystone\w*|trapezoid\w*|moir[e\u00e9])\b" + _GAP + r"\bscreen\b)",
    re.I)

# A candidate's title (or description) the way a cam copy or a
# filmed-in-the-cinema reaction is uploaded. "cam" alone is not a word here: a
# presenter called Cam and a "cameo" are.
TITLE_RE = re.compile(
    r"(\bcam[- ]?rip\b|\bhd[- ]?cam\b|\bcam (version|copy|quality|footage)\b"
    r"|\btelesync\b|\bhdts\b"
    r"|\b(audience|crowd|fan|fans|imax|theat(?:er|re)|cinema)[- ]reactions?\b"
    r"|\breactions? (in|at|from) (the |a )?(cinema|theat(?:er|re)|imax)\b"
    r"|\b(filmed|recorded|live|shot) (in|at) (the |a )?(cinema|movie theat(?:er|re))\b"
    r"|\bopening night reactions?\b)",
    re.I)


# CF-0567: the kind that is a screen by design, never a cam-rip.
OWN_CAPTURE = "own_capture"
OWN_CAPTURE_HEAD = "own_capture-"
OWN_CAPTURE_NAME = "own_capture:"
KIND_FIELD = "source_kind"           # on a shot of an own capture


def _own_capture_id(vid):
    s = Path(str(vid or "")).name
    return ((s.startswith(OWN_CAPTURE_HEAD) and len(s) > len(OWN_CAPTURE_HEAD))
            or (s.startswith(OWN_CAPTURE_NAME) and len(s) > len(OWN_CAPTURE_NAME)))


def source_kind(video_id=None, rights=None, index=None):
    """CF-0567: `own_capture` when the source is the factory's own recording -
    by its id (`own_capture-<id>` / `own_capture:<id>`, or a media path named
    so), its rights record (licence or origin `own_capture`), or a loaded
    index's `source` / `source_rights` - else None."""
    if _own_capture_id(video_id):
        return OWN_CAPTURE
    r = rights if isinstance(rights, dict) else {}
    if OWN_CAPTURE in (r.get("licence"), r.get("footage_origin")):
        return OWN_CAPTURE
    if isinstance(index, dict):
        src = index.get("source")
        if isinstance(src, str) and _own_capture_id(src):
            return OWN_CAPTURE
        return source_kind(rights=index.get("source_rights"))
    return None


def exempt(shot=None, video_id=None, rights=None, index=None):
    """CF-0567: True when the cam-rip rule does not apply - the source is an
    own capture. Decided by the kind only, never by what the shot shows."""
    if isinstance(shot, dict) and shot.get(KIND_FIELD) == OWN_CAPTURE:
        return True
    return source_kind(video_id, rights, index) == OWN_CAPTURE


def mark_kind(index, video_id=None, rights=None):
    """CF-0567: write `source_kind: own_capture` on every shot of a loaded
    index when its source is an own capture; returns how many changed. A
    shot of any other source is left as it is."""
    if not isinstance(index, dict):
        return 0
    if source_kind(video_id, rights, index) != OWN_CAPTURE:
        return 0
    n = 0
    for s in index.get("shots") or []:
        if isinstance(s, dict) and s.get(KIND_FIELD) != OWN_CAPTURE:
            s[KIND_FIELD] = OWN_CAPTURE
            n += 1
    return n


def _text(shot):
    return " ".join(str((shot or {}).get("description") or "").split())


def shot_verdict(shot):
    """`None` when the shot is not a filmed screen, else
    `{"by": "flag"|"description", "match": <the words that fired>|None}`.

    The describer's boolean wins both ways: `screen_recording: false` is an
    answer and the description is not read over it."""
    if not isinstance(shot, dict):
        return None
    if exempt(shot):
        return None                 # CF-0567: an own capture, by its kind
    v = shot.get(FLAG)
    if isinstance(v, bool):
        return {"by": BY_FLAG, "match": None} if v else None
    m = DESCRIPTION_RE.search(_text(shot))
    if m:
        return {"by": BY_DESCRIPTION, "match": m.group(0)}
    return None


def is_screen_recording(shot):
    return shot_verdict(shot) is not None


def title_hit(*texts):
    """The words of a title/description that name a cam copy or a
    filmed-in-the-cinema reaction; None for none."""
    for t in texts:
        m = TITLE_RE.search(" ".join(str(t or "").split()))
        if m:
            return m.group(0)
    return None


def _signed(row):
    sig = (row or {}).get("signature")
    return isinstance(sig, dict) and bool(sig.get("user")) and bool(sig.get("date"))


_MODES = {}


def mode(path=None, refresh=False):
    """`{"mode": hard|penalty|warn, "price": n|None, "price_key": ...}` - what
    the signed price table says about this rule. Only a row with the user's
    `signature` counts (CF-0320): an unsigned row, a missing row or an
    unreadable file is `warn` - the flag and the warning, nothing taken out,
    nothing charged."""
    key = str(path or PRICES_FILE)
    if key in _MODES and not refresh:
        return _MODES[key]
    try:
        rules = (json.loads(Path(key).read_text()) or {}).get("rules") or {}
    except (OSError, ValueError):
        rules = {}
    out = {"mode": MODE_WARN, "price": None, "price_key": PRICE_KEY,
           "signed": False}
    hard = rules.get(HARD_PRICE_KEY)
    soft = rules.get(PRICE_KEY)
    if _signed(hard):
        out = {"mode": MODE_HARD, "price": None, "price_key": HARD_PRICE_KEY,
               "signed": True}
    elif _signed(soft):
        price = ((soft.get("penalty") or {}).get("price"))
        if isinstance(price, (int, float)) and not isinstance(price, bool):
            out = {"mode": MODE_PENALTY, "price": price,
                   "price_key": PRICE_KEY, "signed": True}
    _MODES[key] = out
    return out


def source_summary(index, title=None):
    """What one loaded index holds of filmed-screen shots:
    `{"shots", "flagged": [indices], "share", "by": {flag, description},
    "title_hit", "examples": ["2: <description>", ...]}`."""
    shots = index.get("shots") if isinstance(index, dict) else index
    shots = [s for s in shots or [] if isinstance(s, dict)]
    flagged, by, examples = [], {BY_FLAG: 0, BY_DESCRIPTION: 0}, []
    if isinstance(index, dict) and exempt(index=index):
        # CF-0567: an own capture is a screen by design - nothing flagged,
        # and its title (a page's name) is not read for cam words either.
        return {"shots": len(shots), "flagged": [], "share": 0.0, "by": by,
                "title_hit": None, "examples": [], "exempt": OWN_CAPTURE}
    for s in shots:
        v = shot_verdict(s)
        if not v:
            continue
        flagged.append(s.get("index"))
        by[v["by"]] += 1
        if len(examples) < 3:
            t = _text(s)
            examples.append(f"{s.get('index')}: "
                            + (t[:157] + "..." if len(t) > 160 else t))
    n = len(shots)
    return {"shots": n, "flagged": flagged,
            "share": round(len(flagged) / n, 3) if n else 0.0,
            "by": by, "title_hit": title_hit(title) if title else None,
            "examples": examples}


WARNING_CODE = "screen_recording"
WARN_GATE = "screen_recording"
WARN_DECISION = ("CF-0451 / CF-0320: no signed price for `score.screen_recording`"
                 " / `score.hard.screen_recording` yet - a warning, the shots "
                 "stay in the pool")


def warning(topic_id, video_id, summary, stage, rule_mode=None):
    """The `warnings[]` entry for one source, or None when it holds nothing
    filmed off a screen and its title says nothing either."""
    if not summary or not (summary["flagged"] or summary["title_hit"]):
        return None
    rule_mode = rule_mode or mode()
    parts = []
    if summary["flagged"]:
        parts.append(f"{len(summary['flagged'])} of {summary['shots']} shot(s) "
                     f"filmed off a screen (the cinema cam, CF-0451): "
                     + " | ".join(summary["examples"]))
    if summary["title_hit"]:
        parts.append(f"the title names it: '{summary['title_hit']}'")
    return {"topic_id": topic_id, "video_id": video_id,
            "warning_code": WARNING_CODE, "gate": WARN_GATE, "stage": stage,
            "severity": "warn" if rule_mode["mode"] == MODE_WARN else rule_mode["mode"],
            "mode": rule_mode["mode"], "price_key": rule_mode["price_key"],
            "decision": (WARN_DECISION if rule_mode["mode"] == MODE_WARN else
                         f"CF-0451: signed `{rule_mode['price_key']}` "
                         f"({rule_mode['mode']})"),
            "detail": "; ".join(parts),
            "numbers": {"shots": summary["shots"],
                        "flagged": len(summary["flagged"]),
                        "share": summary["share"], "by": summary["by"]},
            "flagged_shots": list(summary["flagged"]),
            "title_hit": summary["title_hit"]}
