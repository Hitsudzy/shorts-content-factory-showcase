"""CF-0107: the one place in this repo that finds the factory's run-accounting
library (`<root>/shared/runlog/runlog.py`) and hands it to the scripts:

    from _runlog import runlog, video_script, video_attempt

    @video_script("video-editor", "render", name="render_video.py")
    def cli(): ...

    runlog.annotate(**video_attempt(args.plan))   # slug + the ledger's attempt

Root lookup, same convention as shared/inserts/underlay.py: `FACTORY_ROOT`
wins, otherwise walk this file's ancestors for `shared/runlog/runlog.py`.
That walk works from the normal checkout (`agents/video-editor/scripts/`) and
from a worktree (`agents/video-editor/.claude/worktrees/<x>/scripts/`) alike,
because both live under the root.

If the root cannot be found at all (this repo copied somewhere on its own),
`runlog` is a silent stand-in with the same surface - accounting must never
break a render - and one line on stderr says so. Batch-dir resolution is the
library's own business: with no batch to write to it warns and does nothing,
so tests that import the scripts without a batch stay unaffected.

`video_attempt(path)` is this repo's one addition to the shim: the slug and
the attempt number a script event carries, read off the path it works on
(`<batch>/work/<slug>/...`) and the CF-0098 ledger beside it
(`attempts.json`). The number is the attempt the work belongs to
(`current_attempt()`): the ledger's open attempt, or the number
`attempts.begin()` would hand out next when the last one has ended or there
is no ledger yet. `render_video.py` re-annotates with the number begin()
actually hands it, which is the same number.

CF-0177: `video_script(...)` replaces `runlog.script(...)` on this stage's
entry points. Both write `start` and `done`/`failed` around the call, but
`video_script` resolves the slug (and the ledger's attempt) from the command
line *before* the `start` line is written, so both halves of the pair carry
them. `runlog.annotate()` inside `main()` cannot do that - it lands on the
done event alone, and the summary reads the pair from its start event, which
is why the whole stage measured `att/video` = 0 while `footage-indexer`,
which passes `video=` into `runlog.run(...)`, measured correctly.
"""
import contextlib
import functools
import json
import os
import subprocess
import sys
from pathlib import Path

RUNLOG_REL = Path("shared") / "runlog" / "runlog.py"


def factory_root():
    """The factory root: FACTORY_ROOT when it holds shared/runlog/runlog.py,
    else the nearest ancestor of this file that does.

    Video Editor's own tests point FACTORY_ROOT at a synthetic root (a temp
    dir with channels/ and a sound library, for the meme/sound/proof layers)
    that carries no library; the real checkout above this file still does,
    and that is where the accounting goes. Only a root nobody can find at
    all makes this raise."""
    env = os.environ.get("FACTORY_ROOT")
    if env:
        root = Path(env).expanduser().resolve()
        if (root / RUNLOG_REL).is_file():
            return root
    for p in Path(__file__).resolve().parents:
        if (p / RUNLOG_REL).is_file():
            return p
    if env:
        raise RuntimeError(f"factory root not found: FACTORY_ROOT={env} has no {RUNLOG_REL}"
                           " and no ancestor of this checkout does either")
    raise RuntimeError("factory root not found: set FACTORY_ROOT")


class _Silent:
    """runlog's surface with no accounting behind it (root not found)."""

    @staticmethod
    @contextlib.contextmanager
    def run(*args, **kwargs):
        yield {}

    @staticmethod
    def script(*args, **kwargs):
        return lambda fn: fn

    @staticmethod
    @contextlib.contextmanager
    def child(*args, **kwargs):
        yield {}

    @staticmethod
    def run_child(cmd, *, tool=None, batch_dir=None, parent=None, stage=None, step=None,
                  video=None, attempt=None, params=None, **popen_kw):
        return subprocess.run(cmd, **popen_kw)

    @staticmethod
    def annotate(*args, **kwargs):
        return None

    @staticmethod
    def current_id():
        return None


def _load():
    try:
        root = factory_root()
    except RuntimeError as exc:
        sys.stderr.write(f"[runlog] {exc}; run accounting is off for this process\n")
        return _Silent()
    lib_dir = str(root / RUNLOG_REL.parent)
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)
    try:
        import runlog as mod
    except Exception as exc:  # a broken library must not break a render
        sys.stderr.write(f"[runlog] cannot import {lib_dir}/runlog.py ({exc}); "
                         "run accounting is off for this process\n")
        return _Silent()
    return mod


runlog = _load()


def video_context(path):
    """(batch_dir, slug) for a path under <batch>/work/<slug>/..., else None.
    Wider than attempts.batch_context(): a clip in work/<slug>/clips/ or a
    frame in a sub-directory still belongs to the slug."""
    try:
        p = Path(path).expanduser().resolve()
    except (OSError, TypeError):
        return None
    for cand in (p, *p.parents):
        if cand.parent.name == "work" and cand.parent.parent != cand.parent:
            return cand.parent.parent, cand.name
    return None


CAPPED = "capped"        # attempts.RESULT_CAPPED: the marker begin() leaves behind
FAILURES = ("qc_failed", "assets_rejected", "render_failed", "render_broken",
            "abandoned")  # attempts.FAILURES


def current_attempt(batch_dir, slug):
    """The attempt a script running right now belongs to, by the CF-0098
    ledger's own arithmetic:

    * the open attempt's number, while one is open;
    * the number `attempts.begin()` would hand out next (`len(counted) + 1`,
      the `capped` marker excluded, exactly as begin() computes it) when the
      last attempt ended in a failure, or there is no ledger yet - that is
      the attempt this work is preparing;
    * the last attempt's own number when nothing more will be attempted: it
      ended `rendered_ok`, or the cap is used up and begin() would refuse.

    CF-0177 replaced the ledger's *latest* number with this one, and the
    difference is the column `att/video`. The summary counts attempts per (video, step) as the
    distinct attempt numbers on the events, falling back to counting runs
    when none is numbered - and a step that legitimately runs many times per
    attempt (37 `qc-asset` calls, one per candidate frame) then reads as 37
    attempts. Measured on `legacy-film/2026-09-09T2031Z` (the batch
    directory keeps the old channel slug: batch paths are a dated journal and
    were deliberately not renamed with the channel, CF-0180): the ledger's
    latest number leaves the mean at 57.2 attempts per video (the asset
    steps run before the first `begin()`, so their events carry no number at
    all), and this rule brings it to 12.0, against 7.3 and 9.5 in the rows
    written by hand. It is a number this module works out rather than reads,
    which CF-0107 refused to do - but it is the field's own definition ("the
    attempt this event belongs to"), it agrees with what begin() hands out
    moments later (`render_video.py` re-annotates with it), and the
    alternative is a column nobody can compare. The prediction is wrong only
    where a failed attempt is never retried although it could have been -
    the operator walks away mid-batch - and it costs a label, not a count."""
    try:
        data = json.loads((Path(batch_dir) / "work" / slug / "attempts.json").read_text())
        atts = list(data["attempts"])
    except (OSError, ValueError, KeyError, TypeError):
        data, atts = {}, []
    for a in reversed(atts):                     # only the last one can be open
        if a.get("result") is None:
            try:
                return int(a["n"])
            except (KeyError, TypeError, ValueError):
                return None
        break
    counted = sum(1 for a in atts if a.get("result") != CAPPED)
    last = atts[-1].get("result") if atts else None
    if atts and (last not in FAILURES or _exhausted(data, atts)):
        # Nothing more will be attempted - the video is rendered, or the cap
        # is used up and begin() would refuse. What still runs (the batch
        # metadata, an `attempts show`) belongs to the attempt that ended.
        return counted or 1
    return counted + 1


QC_DEGRADE = "qc_degrade"  # attempts.KIND_QC_DEGRADE (CF-0415)
DEFAULT_MAX_QC_DEGRADES = 3  # attempts.DEFAULT_MAX_QC_DEGRADES


def _exhausted(ledger, atts):
    """attempts.exhausted(), read off the file: needs_you, or the attempt cap
    used up with no `qc_degrade` left open to the video (CF-0415: QC's last
    verdict named a degradation and the degrade cap has room)."""
    if ledger.get("needs_you"):
        return True
    renders = [a for a in atts if a.get("result") != CAPPED]
    degrades = sum(1 for a in renders if a.get("kind") == QC_DEGRADE)
    # CF-0305: a render the tool broke before the first frame counts nothing.
    broken = sum(1 for a in renders
                 if a.get("kind") != QC_DEGRADE and a.get("counted", True) is False)
    try:
        if len(renders) - degrades - broken < int(ledger["attempt_cap"]):
            return False
    except (KeyError, TypeError, ValueError):
        return False
    try:
        degrade_cap = int(ledger.get("qc_degrade_cap") or DEFAULT_MAX_QC_DEGRADES)
    except (TypeError, ValueError):
        degrade_cap = DEFAULT_MAX_QC_DEGRADES
    last = renders[-1] if renders else {}
    hint = last.get("result") == "qc_failed" and bool(last.get("qc_hint"))
    return not (hint and degrades < degrade_cap)


def video_attempt(path):
    """{"video": slug, "attempt": n} for runlog.annotate(**...) - only the
    keys that are known, so an unknown one leaves the event's field alone."""
    ctx = video_context(path)
    if ctx is None:
        return {}
    batch_dir, slug = ctx
    out = {"video": slug}
    n = current_attempt(batch_dir, slug)
    if n is not None:
        out["attempt"] = n
    return out


# --------------------------------------------------------------------------
# CF-0177: the stage's entry-point decorator - a per-video event that pairs
# --------------------------------------------------------------------------

def _params(argv):
    """The library's own argv -> params dict, when there is a library."""
    fn = getattr(runlog, "_argv_params", None)
    return fn(list(argv)) if fn else None


def _named_arg(params, which):
    """The value of `which` in a parsed command line: a flag name ("--slug")
    or the index of a positional (`begin <batch> <slug>` -> 2). None when the
    command line does not carry it."""
    if params is None or which is None:
        return None
    if isinstance(which, int):
        pos = params.get("args") or []
        return pos[which] if 0 <= which < len(pos) else None
    v = params.get(which)
    return v if isinstance(v, str) else None


def argv_video_attempt(argv=None, video_arg=None, batch_arg=None, params=None):
    """{"video": slug, "attempt": n} for a command line, before the script it
    starts has parsed anything - only the keys that are known, like
    `video_attempt()`.

    Two ways of naming the video, in this order:

    * `video_arg` names an argument that IS the slug - a flag ("--slug") or a
      positional index. `batch_arg` names the batch dir the CF-0098 ledger is
      read from, the same way; without one the library's own batch lookup
      answers (RUNLOG_BATCH, then the walk up from argv).
    * otherwise the slug is read off the paths on the line, the way
      `video_attempt()` reads it off one path: a script is handed its plan,
      its clip, its frame, and any of them names the video. Exactly one slug
      has to come out. `write_batch_metadata.py --video a .. --video b ..`
      spans two videos and gets `{}` - that event belongs to the batch, which
      is the rule its own `annotate()` call already followed."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if params is None:
        params = _params(argv)
    if video_arg is not None:
        slug = _named_arg(params, video_arg)
        if not slug:
            return {}
        out = {"video": slug}
        bdir = _named_arg(params, batch_arg)
        if bdir is None:
            finder = getattr(runlog, "find_batch_dir", None)
            bdir = finder() if finder else None
        n = current_attempt(bdir, slug) if bdir else None
        if n is not None:
            out["attempt"] = n
        return out
    found = {}
    for a in argv:
        if not isinstance(a, str) or not a or a.startswith("-"):
            continue
        ctx = video_context(a)
        if ctx is not None:
            found.setdefault(ctx[1], ctx[0])
    if len(found) != 1:
        return {}
    slug, batch_dir = next(iter(found.items()))
    out = {"video": slug}
    n = current_attempt(batch_dir, slug)
    if n is not None:
        out["attempt"] = n
    return out


def video_script(stage, step=None, name=None, video_arg=None, batch_arg=None):
    """Decorator for this stage's entry points, in place of
    `runlog.script(...)`: writes `start` and `done`/`failed` around the call
    with the slug and the ledger's attempt already on the `start` line
    (CF-0177), so the pair the summary reads is a per-video pair and the
    attempts per video can be counted. A failed call pairs the same way -
    a failed attempt is exactly what that column has to count.

    The slug comes from `argv_video_attempt()`; `video_arg` / `batch_arg` are
    for the scripts that take the slug as a bare name rather than inside a
    path. `main()` may still `runlog.annotate()` what it learns later (the
    number `attempts.begin()` hands out); that refines the done event."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            argv = sys.argv[1:]
            params = _params(argv)
            va = argv_video_attempt(argv, video_arg=video_arg, batch_arg=batch_arg,
                                    params=params)
            with runlog.run(stage, step=step, video=va.get("video"),
                            attempt=va.get("attempt"), params=params, name=name):
                return fn(*args, **kwargs)
        return wrapper
    return deco
