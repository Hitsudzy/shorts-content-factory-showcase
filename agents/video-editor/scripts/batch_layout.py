"""CF-0246: a stage's outputs stay in the batch directory.

On 2026-09-15 (`example-film/2026-09-15T1034Z`) the three finished videos of a
batch landed in `agents/video-editor/videos/` and their working directories in
`agents/video-editor/work/<slug>/`: the stage passes its paths relative
(`work/<slug>/plan.json videos/<slug>.mp4`), the scripts resolve them against
the operator's working directory, and that day the operator stood in the agent
checkout. No script picks these directories itself and `RUNLOG_BATCH` does not
set them, so nothing caught it - the batch had no `videos/` at all and the
driver found the files by hand.

Two checks, both read-only:

- `leaked_paths(batch_dir, paths)` - which of the paths a call names lie
  outside the batch *and* inside a checkout's `work/` or `videos/` (the agent
  checkout this runs from, its main checkout, the factory root, the version
  root). Those are the 15.09 shape exactly. A path outside the batch anywhere
  else (a fixture, a hand-made plan in /tmp) is not judged here.
- `check(batch_dir)` - after the stage: no mp4 in any checkout's `videos/`,
  and every record of `<batch>/05-video-editor.json` has its mp4 on disk
  under `<batch>/videos/`, one mp4 per record.

`write_batch_metadata.py` refuses a `--video` whose plan or mp4 leaked
(exit 2, before anything is written) and prints `check()`'s findings as
warnings after the write. `python3 scripts/batch_layout.py <batch>` runs
`check()` alone: exit 0 clean, 1 with a finding per line.
"""
import json
import sys
from pathlib import Path

import repo_paths

STAGE_DIRS = ("work", "videos")
DEST_NAME = "05-video-editor.json"


def checkouts():
    """Every directory a relative `work/...` / `videos/...` would have
    resolved into on 15.09 or could today: the agent checkout, its main
    checkout, the version root and the factory root."""
    main = repo_paths.MAIN_CHECKOUT
    roots = [repo_paths.AGENT_ROOT, main, repo_paths.FACTORY_ROOT,
             # the production root `<factory>/agents/<name>` sits in
             main.parent.parent]
    if repo_paths.VERSION_ROOT:
        roots.append(repo_paths.VERSION_ROOT)
    seen, out = set(), []
    for r in roots:
        r = Path(r).resolve()
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def leaked_dir(path, roots=None):
    """`<checkout>/work` or `<checkout>/videos` that holds `path`, or None."""
    path = Path(path).resolve()
    for root in roots if roots is not None else checkouts():
        for name in STAGE_DIRS:
            d = root / name
            if _inside(path, d):
                return d
    return None


def leaked_paths(batch_dir, paths, roots=None):
    """[(path, dir)] - the paths outside `batch_dir` that sit in a checkout's
    work/ or videos/."""
    batch = Path(batch_dir).resolve()
    out = []
    for p in paths:
        rp = Path(p).resolve()
        if _inside(rp, batch):
            continue
        d = leaked_dir(rp, roots)
        if d is not None:
            out.append((rp, d))
    return out


def stray_videos(roots=None):
    """mp4 files lying in any checkout's videos/."""
    out = []
    for root in roots if roots is not None else checkouts():
        d = root / "videos"
        if d.is_dir():
            out.extend(sorted(d.rglob("*.mp4")))
    return out


def check(batch_dir, roots=None):
    """Findings, one sentence each; [] when the layout is right."""
    batch = Path(batch_dir).resolve()
    findings = []
    for mp4 in stray_videos(roots):
        findings.append(f"stray video outside any batch: {mp4} (CF-0246: a stage "
                        f"output in a checkout's videos/)")
    dest = batch / DEST_NAME
    if not dest.exists():
        return findings
    try:
        videos = json.loads(dest.read_text(encoding="utf-8")).get("videos") or []
    except (OSError, ValueError) as e:
        return findings + [f"{dest} cannot be read ({e})"]
    vdir = batch / "videos"
    named = set()
    for v in videos:
        sid = v.get("script_id")
        out = v.get("output_path")
        if not out:
            findings.append(f"{sid}: no output_path in {DEST_NAME}")
            continue
        p = Path(out)
        if not _inside(p.resolve(), vdir.resolve()):
            findings.append(f"{sid}: output_path {out} is not under {vdir}")
        elif not p.exists():
            findings.append(f"{sid}: output_path {out} is not on disk")
        named.add(p.resolve())
    # One mp4 per record. An mp4 no record names is accounted for only when its
    # script was refused after the render (CF-0270 / CF-0434: the refusal
    # supersedes the video, the file stays) - `work/<slug>/` holds the refusal
    # sidecar. Anything else is an output the stage did not record.
    on_disk = sorted(vdir.glob("*.mp4")) if vdir.is_dir() else []
    extra = [m for m in on_disk if m.resolve() not in named
             and not any((batch / "work" / m.stem).glob("*refusal.json"))]
    if extra:
        findings.append(f"{len(videos)} record(s) in {DEST_NAME}, {len(on_disk)} mp4 in "
                        f"{vdir}; not in the records and not refused: "
                        f"{', '.join(str(m) for m in extra)}")
    return findings


def leak_message(batch_dir, leaked):
    lines = [f"OUTPUT OUTSIDE THE BATCH - metadata not written (CF-0246): the batch is "
             f"{Path(batch_dir).resolve()}, and"]
    for p, d in leaked:
        lines.append(f"  {p} is in {d}")
    lines.append("  relative paths resolve against the current directory - pass "
                 "\"$RUNLOG_BATCH\"/work/<slug>/plan.json \"$RUNLOG_BATCH\"/videos/<slug>.mp4, "
                 "and move what is already there into the batch first")
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0].startswith("-"):
        print("usage: batch_layout.py <batch-dir>", file=sys.stderr)
        return 2
    findings = check(argv[0])
    for f in findings:
        print(f"LAYOUT: {f}")
    if not findings:
        print(f"LAYOUT: ok - {Path(argv[0]).resolve()}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
