#!/usr/bin/env python3
"""CF-0110: the cumulative runs table - one row per run, so that "did the fix
make it faster?" is a comparison of two rows and not a memory.

    pipeline/runs.jsonl        machine copy, one JSON object per run (canonical, in git)
    pipeline/RUNS.md           the same table for humans, newest first (in git)

(CF-0499: the Notebook mirror text `pipeline/RUNS.notebook.md` is gone - the
vault is Claude's workspace, not a place for copies of repo files;
tests/test_no_vault_mirror.py keeps it from growing back.)

    runs_table.row(batch_dir)          the record of one batch, from summary.compute()
    runs_table.append(row, root=None)  replace-or-add the row (by batch id) in runs.jsonl,
                                       then regenerate RUNS.md
    runs_table.rebuild(root=None)      rows for every pipeline/<channel>/<batch>/ that
                                       reached batch-done, then the same
    runlog runs [--batch DIR] [--rebuild] [--root DIR] [--stdout]

The root: `root=` / `--root DIR`, else $FACTORY_ROOT, else the repo this file lives
in - and that last, derived root is only written to when it holds at least one
pipeline/<channel>/<batch>/ (CF-0111: a test tree or a bare worktree never gets a
table by accident; the error names the fix).

runlog.marker("batch-done") calls append(row(batch)) after writing RUN_SUMMARY.md,
so the row appears by itself. A batch appended twice replaces its row (same
`batch` key), the file never grows with duplicates.

Row shape (every key present, null when unknown):

    batch            "<channel>/<batch-id>"           key
    id, channel      the two halves
    date             YYYY-MM-DD of batch-start (UTC)
    started, ended   ISO timestamps of the wall
    commit           short root commit, "+dirty" when the tree was dirty
    agents           CF-0479: {agent path: "<rev>@<sha7>"} - the pins of agents.lock.json
                     the run started on (null on a run before the lock)
    version          README version at batch-start
    machine          cpu string from the header, else the machine id of the events
    models           {operator, subagent_default, subagents{name: model}}
    videos           videos the run built (05-video-editor.json, else the slugs of
                     the video-editor events, else header counts) - CF-0176
    videos_qc_passed how many of them passed QC (null when nothing records it)
    wall_s, live_s   seconds; live = wall - gaps
    gaps_s           seconds in gaps
    gaps             {limit: n, unknown: n, ...}  - CF-0377: plus a key per named
                     cause that occurred (`idle_exit`, `<step>_timeout`)
    reset_stops      CF-0739: [{at, task, by, why, from, gaps_s, waits_s}] - the stops that
                     hold a recorded reset of the batch's stages (inside gaps_s/waits_s);
                     no_waiting.dod() sets them aside, named by the reset
    login_stops      CF-0899: [{at, stage, reason, task, resumed, code, gaps_s, waits_s}] -
                     the stops on `claude` not logged in, on the stage that halted (inside
                     gaps_s/waits_s); no_waiting.dod() sets them aside, named
    indexer_s        wall seconds of the footage-indexer stage(s)
    per_video_s      mean wall seconds per video of the video-editor stage (null
                     without one: CF-0176, the fallback used to average the pool)
    attempts_per_video   mean attempts (all sub-steps) per video of that stage
    tokens_total, tokens_fresh   from the usage events (null without them)
    window_5h_pct, window_7d_pct share of the windows the run spent (null without 2 readings)
    markup           generation of the stage markup the run was recorded under (CF-0173):
                     2 = the pre-stage pool work carries `pool-maintenance` markers,
                     1 = it does not and lands in `between`. Rows of different
                     generations are not comparable stage by stage.
    accounting       "complete" | "incomplete" | "manual-runlog" (CF-0111 backfill)
    note             "ручной лог, низкая точность; ..." on a backfilled row, else None
    unattributed_pct % of live outside every stage window and every named wait -
                     the orchestrator between stages, which nothing records (CF-0257)
    summary_at       when the row was computed
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runlog  # noqa: E402

__all__ = ["RUNS_JSONL", "RUNS_MD", "COLUMNS", "row", "read_rows",
           "append", "rebuild", "render_md", "write_tables", "main"]

RUNS_JSONL = "pipeline/runs.jsonl"
# CF-0899: no_waiting.LOGIN_STOP_FIELDS (runs_table does not import no_waiting)
LOGIN_STOP_FIELDS = ("at", "stage", "reason", "task", "resumed", "code", "gaps_s", "waits_s")
RUNS_MD = "pipeline/RUNS.md"

COLUMNS = (
    ("run", "`<channel>/<batch-id>`"),
    ("date", "day of `batch-start` (UTC)"),
    ("commit", "root commit at `batch-start` (`+dirty` when the tree was not clean) / README version"
               " / the agents' pins of `agents.lock.json` (CF-0479)"),
    ("machine", "CPU of the machine"),
    ("models", "operator model; subagent default"),
    ("videos", "videos the run built (`05-video-editor.json`), `n (m ok)` when only m of them passed QC"),
    ("wall", "batch-start .. batch-done"),
    ("live", "wall minus gaps"),
    ("gaps", "gaps > 10 min: total, `limit`/`unknown` and named-cause counts"),
    ("indexer", "wall of the footage-indexer stage(s)"),
    ("per video", "mean wall per video"),
    ("att/video", "mean attempts (all sub-steps) per video"),
    ("tokens", "total tokens of the run (input + cache_write + cache_read + output)"),
    ("fresh", "tokens not served from cache (input + cache_write + output)"),
    ("5h / 7d", "share of the 5-hour / 7-day subscription window the run spent"),
    ("markup", "generation of the stage markup (CF-0173). `2` marks the pre-stage pool work with its "
               "own `pool-maintenance` stage; `1` left it in `between`. Rows of different generations "
               "are not comparable stage by stage - `indexer` and `per video` included"),
    ("accounting", "`complete`, or `incomplete` (live time outside every stage window and every "
                   "named wait is more than 5 % of live - see `## Where the wall went` in "
                   "RUN_SUMMARY.md, CF-0257), "
                   "or `manual-runlog` (backfilled from a hand-written RUN_LOG.txt by `runlog backfill`, CF-0111)"),
    ("note", "`ручной лог, низкая точность` on a backfilled row (plus whether it has tokens); `-` on an instrumented one"),
)
ACC_MANUAL = "manual-runlog"


def _root(root=None):
    return Path(root) if root else runlog.factory_root()


def _explicit(root):
    """True when the root was named (argument or FACTORY_ROOT) rather than derived
    from where this file lives."""
    return bool(root) or bool(os.environ.get(runlog.FACTORY_ROOT_ENV))


def _has_batches(r):
    try:
        return any(runlog._looks_like_batch(d) for d in Path(r).glob("pipeline/*/*") if d.is_dir())
    except OSError:
        return False


def _guard(r, explicit):
    """CF-0111: refuse to write the table into a root that was only *derived* (no
    root= argument, no FACTORY_ROOT) and holds no pipeline/<channel>/<batch>/ at
    all - a test tree, a bare checkout, a worktree - because the derived root is
    this file's repo, and writing there from a test run is exactly the accident
    CF-0110 had. An explicit root is always written to (the check is about
    surprise, not about permission)."""
    if explicit or _has_batches(r):
        return
    raise runlog.RunlogError(
        f"runs table: implicit root {r} has no pipeline/<channel>/<batch>/ - "
        f"pass root= / --root DIR or set {runlog.FACTORY_ROOT_ENV} to say where the table lives")


VE_STAGE = "video-editor"


def _video_counts(batch_dir, header, vids):
    """CF-0176: (videos the run built, how many of them passed QC) - and never
    the distinct `video` values of the whole event stream. That field is
    overloaded: a finished-video slug under `video-editor`, the id of a source
    clip on YouTube under `footage-indexer`, so counting it once made this
    column read 51 for a batch that built 3 (the 51 clips of the pool remeasure).

    In order: `05-video-editor.json`, the stage's own output and the only list
    of finished videos; else the distinct slugs of the `video-editor` events
    (a run whose stage output is gone); else `counts.videos` of the header.
    The QC number is null when nothing records QC."""
    meta = runlog.editor_videos(batch_dir)
    if meta:
        slugs = {m["slug"] for m in meta if m["slug"]}
        passed = {m["slug"] for m in meta if m["slug"] and m["qc_passed"]}
        known = any(m["qc_passed"] is not None for m in meta)
        return (len(slugs) or None), (len(passed) if known else None)
    slugs = {v["video"] for v in vids if v["stage"] == VE_STAGE and v["video"]}
    if slugs:
        return len(slugs), None
    return ((header.get("counts") or {}).get("videos") or None), None


def _run_subagents(subs):
    """CF-0176: only the agents of the pipeline. `~/.claude/agents/*.md` also
    defines the agents that drive *development* (`auto-dev-worker`), and until
    the header stopped reading them (runlog.pipeline_agents) every batch started
    on such a machine carried one in `models.subagents`. A row describes the run,
    not the machine, so old headers are filtered here too."""
    if not subs:
        return None
    known = set(runlog.pipeline_agents())
    return {k: v for k, v in subs.items() if k in known} or None


def _short_model(m):
    if not m:
        return None
    return m[len("claude-"):] if m.startswith("claude-") else m


def _agents_pins(lock):
    """CF-0479: {agent path: "<rev>@<sha7>"} from the header's resolved pins."""
    if not isinstance(lock, dict) or not lock:
        return None
    return {p: f"{(v or {}).get('rev')}@{str((v or {}).get('sha') or '?')[:7]}"
            for p, v in sorted(lock.items())}


def _agents_cell(pins):
    """`agents v1.4` when every agent is on the same rev, else each one."""
    if not pins:
        return None
    revs = {v.rpartition("@")[0] for v in pins.values()}
    if len(revs) == 1:
        return f"agents {revs.pop()}"
    return "agents " + ", ".join(f"{p.rpartition('/')[2]} {v}" for p, v in pins.items())


def row(batch_dir, data=None):
    """The one-line record of a batch (see the module docstring)."""
    summary = runlog.sibling("summary")
    bd = Path(batch_dir)
    c = data or summary.compute(bd)
    h = c["header"] or {}
    T, G, K, W, U = c["times"], c["gaps"], c["tokens"], c["windows"], c["unattributed"]
    WTS = c.get("waits") or {"count": 0, "seconds": 0.0}          # CF-0252
    NW = c.get("no_waiting") or {"codes": [], "unclassified": 0, "verdict": None}   # CF-0317
    git = (h.get("git") or {}).get("root") or {}
    commit = None
    if git.get("commit"):
        commit = git["commit"][:7] + ("+dirty" if git.get("dirty") else "")
    machine = (h.get("machine") or {}).get("cpu")
    if not machine:
        machine = c.get("machine_id")
    models = h.get("models") or {}
    vids = T["videos"]
    ve = [v for v in vids if v["stage"] == VE_STAGE]          # CF-0176: never the whole stream
    n_videos, n_qc = _video_counts(bd, h, vids)
    indexer = sum(w["wall_s"] for w in T["stages"] if (w["stage"] or "").startswith("footage-indexer"))
    tot = K["total"]
    started = T["wall"]["start"]
    batch = c["batch"] if c["batch"] != "?" else f"{bd.parent.name}/{bd.name}"
    channel, _, bid = batch.rpartition("/")
    accounting, note = U["accounting"], None
    if h.get("source") == ACC_MANUAL:                # CF-0111: a backfilled row says so, always
        accounting = ACC_MANUAL
        note = h.get("row_note") or "manual RUN_LOG.txt"
        note += "; токены из транскрипта" if tot else "; токенов нет"
    return {
        "batch": batch,
        "id": bid or bd.name, "channel": channel or bd.parent.name,
        "date": started[:10] if started else None,
        "started": started, "ended": T["wall"]["end"],
        "commit": commit, "version": h.get("version"),
        "agents": _agents_pins(h.get(runlog.HEADER_LOCK_KEY)),         # CF-0479
        "machine": machine,
        "models": {"operator": models.get("operator"),
                   "subagent_default": models.get("subagent_default"),
                   "subagents": _run_subagents(models.get("subagents"))},
        "videos": n_videos, "videos_qc_passed": n_qc,
        "wall_s": T["wall"]["seconds"], "live_s": T["live_s"], "gaps_s": T["gaps_s"],
        # CF-0377: `limit` and `unknown` are always in the row, and a gap that read
        # its cause off its own boundaries (`idle_exit`, `<step>_timeout`) brings
        # its own key - otherwise a named gap would leave the row's counts at zero.
        "gaps": {c_: v_["count"] for c_, v_ in G["by_cause"].items()
                 if v_["count"] or c_ in ("limit", "unknown")},
        # CF-0317: how long this run stood waiting for a human, and under which
        # codes. Beside `gaps_s`/`gaps` and shaped like them, because DoD 1 asks
        # one question of both - a run that showed either did not run to the end
        # unattended. It lives in the row and not only in the batch directory
        # for the reason CF-0318 put its holds in `publish/`: the directory is
        # moved off this disk 31 days after the batch closes (CF-0056) and the
        # row is in git forever. A row without these keys is a row written
        # before this task, and "no key" is not "no wait" - `no_waiting.dod()`
        # calls that `unmeasured` rather than clean.
        "waits_s": WTS["seconds"],
        "waits": {"count": WTS["count"], "codes": NW["codes"],
                  "unclassified": NW["unclassified"], "verdict": NW["verdict"]},
        # CF-0739: the stops that hold a recorded reset of the batch's stages
        # (run-state.json `manual_resets`) - inside `gaps_s` / `waits_s` above,
        # set aside by `no_waiting.dod()` and named by the reset. `[]` on a run
        # with no reset; no key is a row written before CF-0739.
        "reset_stops": [{k: x.get(k) for k in ("at", "task", "by", "why", "from",
                                                "gaps_s", "waits_s")}
                        for x in NW.get("reset_stops") or []],
        # CF-0899: the stops on `claude` not logged in (run-state.json
        # `login_halts`) - inside `gaps_s` / `waits_s` above, on the stage that
        # halted, set aside by `no_waiting.dod()`. `[]` on a run with no such
        # halt; no key is a row written before CF-0899.
        "login_stops": [{k: x.get(k) for k in LOGIN_STOP_FIELDS}
                        for x in NW.get("login_stops") or []],
        "indexer_s": round(indexer, 1) if indexer else None,
        "per_video_s": round(sum(v["wall_s"] for v in ve) / len(ve), 1) if ve else None,
        "attempts_per_video": round(sum(v["attempts_total"] for v in ve) / len(ve), 1) if ve else None,
        "tokens_total": tot["total"] if tot else None,
        "tokens_fresh": tot["fresh"] if tot else None,
        "window_5h_pct": W["run"]["five_hour"], "window_7d_pct": W["run"]["seven_day"],
        "markup": runlog.markup_of(h),                   # CF-0173
        "accounting": accounting, "unattributed_pct": U["pct"],
        # CF-0322: how the batch ended, when this factory can say so without
        # guessing - `no_material` (the stop-cock closed it: the Researcher wrote
        # no script and there was nothing left to substitute) or `videos` (it
        # delivered at least one). Both are normal ends; every other run leaves
        # the field null, because the vocabulary of failure belongs to the triage
        # of CF-0319 and is not invented here. A column of RUNS.md it is not: the
        # JSONL row is where the machine reads, and the table is for a human.
        "outcome": runlog.sibling("stopcock").outcome_of(c.get("stopcock")),
        # CF-0494: the mode the batch was opened with (`batch-start --rerun`), or
        # null - every batch opened without the flag, 1748Z included (its
        # events are not rewritten). Data only: no reader judges by it while
        # `no_waiting.EXEMPT_VERIFICATION_RERUNS` is False.
        "rerun": c.get("rerun"),
        "note": note,
        "summary_at": runlog.now_z(),
    }


def read_rows(root=None):
    p = _root(root) / RUNS_JSONL
    out = []
    if not p.is_file():
        return out
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            runlog._warn(f"{p}:{n}: unreadable row skipped")
    return out


def _sorted(rows):
    return sorted(rows, key=lambda r: (r.get("started") or r.get("date") or "", r.get("batch") or ""))


def _write_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_tables(rows, root=None):
    """runs.jsonl (oldest first) and RUNS.md (newest first). Returns the paths."""
    r = _root(root)
    _guard(r, _explicit(root))
    rows = _sorted(rows)
    for x in rows:                # CF-0173: every row answers which markup generation it is
        if x.get("markup") is None:
            x["markup"] = runlog.MARKUP_LEGACY

    _write_atomic(r / RUNS_JSONL, "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows))
    _write_atomic(r / RUNS_MD, render_md(rows))
    return [r / RUNS_JSONL, r / RUNS_MD]


def append(row_, root=None):
    """Replace-or-add the row (key: batch) and regenerate the tables."""
    rows = [x for x in read_rows(root) if x.get("batch") != row_.get("batch")]
    rows.append(row_)
    return write_tables(rows, root)


def rebuild(root=None):
    """Rows for every pipeline/<channel>/<batch>/RUN_EVENTS.jsonl that has a
    batch-done marker (rows of batches no longer on disk are kept)."""
    r = _root(root)
    keep = {x.get("batch"): x for x in read_rows(r)}
    for ev in sorted((r / "pipeline").glob("*/*/" + runlog.EVENTS_FILE)):
        bd = ev.parent
        events = runlog.read_events(bd)
        if not any(e.get("kind") == runlog.KIND_MARKER and e.get("status") == runlog.M_BATCH_DONE
                   for e in events):
            continue
        try:
            x = row(bd)
        except Exception as e:                       # one bad batch must not lose the table
            runlog._warn(f"{bd}: row not computed ({e.__class__.__name__}: {e})")
            continue
        was = keep.get(x["batch"])
        if was and was.get("accounting") == ACC_MANUAL and x.get("accounting") != ACC_MANUAL:
            # CF-0176: a backfilled row (CF-0111) was reconstructed from the
            # hand-written RUN_LOG.txt and its events live elsewhere; the stale
            # RUN_EVENTS.jsonl still sitting in the batch directory must not
            # overwrite it with a worse row.
            runlog._warn(f"{bd}: kept the {ACC_MANUAL} row, {runlog.EVENTS_FILE} here is not its source")
            continue
        keep[x["batch"]] = x
    return write_tables(list(keep.values()), r)


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def _hms(s):
    return runlog._hms(s) if s is not None else "-"


def _k(n):
    return runlog.sibling("usage")._k(n) if n is not None else "-"


def _pct(v):
    return "-" if v is None else f"{v:g} %"


def _models(m):
    m = m or {}
    op = _short_model(m.get("operator")) or "?"
    sd = _short_model(m.get("subagent_default"))
    return op + (f"; {sd}" if sd and sd != op else "")


def _videos(x):
    """`3 (2 ok)` when the run built 3 videos and 2 of them passed QC (CF-0176)."""
    n, ok = x.get("videos"), x.get("videos_qc_passed")
    if n is None:
        return "-"
    return f"{n} ({ok} ok)" if ok is not None and ok != n else str(n)


def _markup(x):
    """CF-0173: the markup generation of a row. A row written before the field
    existed is generation 1 by the same rule as a header without the stamp."""
    return runlog.markup_of({"markup": x.get("markup")})


def _generations(rows):
    """{generation: [batch, ...]} over the rows, for the comparability warning."""
    out = {}
    for x in rows:
        out.setdefault(_markup(x), []).append(x.get("batch"))
    return out


def _markup_warning(rows):
    """CF-0173: the lines that say the table mixes markup generations - the whole
    point of the table is that two rows can be compared, and across a change of
    the markers the per-stage columns silently cannot be. Empty when every row
    is of one generation."""
    gens = _generations(rows)
    if len(gens) < 2:
        return []
    parts = [f"**{g}**: {len(bs)} run(s)" for g, bs in sorted(gens.items())]
    return ["> **Two generations of stage markup in this table** (" + ", ".join(parts) + ") - "
            "CF-0173. Generation 1 has no marker around the pool work that runs before the first "
            "stage, so in those runs it sits in `between`; generation 2 gives it a "
            f"`{runlog.S_POOL_MAINTENANCE}` stage of its own. **`indexer`, `per video`, `att/video` "
            "and the per-stage sections of `RUN_SUMMARY.md` may not be compared across that "
            "line**; `wall`, `live`, `gaps`, `tokens` and the window shares are whole-run numbers "
            "and stay comparable. `att/video` in particular: every generation-1 run was recorded "
            "before CF-0177, so its `video-editor` scripts carry no attempt numbers, and the "
            "column falls back to counting the calls of each sub-step - 55 `qc-asset` runs read as "
            "55 attempts. It is an upper bound there, not a count (CF-0178). Older rows are not "
            "recomputed: neither the markers nor the numbers were ever written, and no later "
            "reading can invent them.", ""]


def _cells(x):
    g = x.get("gaps") or {}
    gaps = _hms(x.get("gaps_s"))
    if x.get("gaps_s"):
        named = [f"{n} {c}" for c, n in g.items()
                 if n and c not in ("limit", "unknown")]          # CF-0377
        gaps += (" (" + ", ".join([f"{g.get('limit', 0)} limit",
                                   f"{g.get('unknown', 0)} unknown"] + named) + ")")
    commit = x.get("commit") or "-"
    if x.get("version"):
        commit += f" / {x['version']}"
    if _agents_cell(x.get("agents")):
        commit += f" / {_agents_cell(x.get('agents'))}"
    return [
        f"`{x.get('batch')}`", x.get("date") or "-", commit, x.get("machine") or "-",
        _models(x.get("models")), _videos(x),
        _hms(x.get("wall_s")), _hms(x.get("live_s")), gaps, _hms(x.get("indexer_s")),
        _hms(x.get("per_video_s")),
        f"{x['attempts_per_video']:g}" if x.get("attempts_per_video") is not None else "-",
        _k(x.get("tokens_total")), _k(x.get("tokens_fresh")),
        f"{_pct(x.get('window_5h_pct'))} / {_pct(x.get('window_7d_pct'))}",
        str(_markup(x)),
        x.get("accounting") or "-",
        x.get("note") or "-",
    ]


def _table(rows):
    lines = ["| " + " | ".join(c for c, _ in COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    for x in reversed(_sorted(rows)):
        lines.append("| " + " | ".join(str(v).replace("|", "/") for v in _cells(x)) + " |")
    if not rows:
        lines.append("| (no run recorded yet) |" + " |" * (len(COLUMNS) - 1))
    return "\n".join(lines)


def render_md(rows):
    """pipeline/RUNS.md: header explaining the columns, then the table, newest first."""
    L = ["# Runs", "",
         "One row per pipeline run, newest first. Appended by `runlog batch-done` (CF-0110) from",
         "the run's `RUN_EVENTS.jsonl`; `runlog runs --batch DIR` re-adds one run, `runlog runs",
         "--rebuild` recomputes every `pipeline/<channel>/<batch>/` that reached `batch-done`.",
         "The machine copy is `pipeline/runs.jsonl` (same rows, oldest first).",
         "Details of one run: `RUN_SUMMARY.md` in its batch directory. Generated - do not edit.", "",
         "Columns:", ""]
    L += [f"- **{c}** - {d}" for c, d in COLUMNS]
    L += [""] + _markup_warning(rows)
    L += ["", _table(rows), ""]
    return "\n".join(L)


# --------------------------------------------------------------------------

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="runlog runs",
                                 description="the cumulative runs table (CF-0110)")
    ap.add_argument("--batch", default=None, help="add / replace the row of this batch")
    ap.add_argument("--rebuild", action="store_true", help="recompute every finished batch under pipeline/")
    ap.add_argument("--root", default=None, help="factory root (default: FACTORY_ROOT or the repo)")
    ap.add_argument("--stdout", action="store_true", help="print RUNS.md instead of writing")
    ns = ap.parse_args(sys.argv[1:] if argv is None else argv)
    root = _root(ns.root)
    if ns.rebuild:
        paths = rebuild(root)
    elif ns.batch:
        bdir = runlog.find_batch_dir(ns.batch)
        if bdir is None or not runlog.events_path(bdir).is_file():
            sys.stderr.write(f"runlog runs: error: no batch directory with {runlog.EVENTS_FILE} at {ns.batch}\n")
            return 2
        paths = append(row(bdir), root)
    elif ns.stdout:
        sys.stdout.write(render_md(read_rows(root)))
        return 0
    else:
        paths = write_tables(read_rows(root), root)
    if ns.stdout:
        sys.stdout.write(render_md(read_rows(root)))
    else:
        for p in paths:
            print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
