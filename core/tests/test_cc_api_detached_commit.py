#!/usr/bin/env python3
"""CC-0156: the detached writes of the center commit when they end well -
`api/detached_commit.py`, a channel's ending render (CC-0158: the meme jobs'
commit is the factory's own, CF-0847 - not here).

Each test runs the module's real bootstrap (`argv_head` - `python3 -c` with
this checkout's `api` first) as a child, the way `child.detach` starts it,
against a stand-in factory root in a temp dir (a git repo of its own, hooks
off): `brand_ending.py` is a stand-in file there - no render, no network.

What is pinned: a render that ends with 0 commits the clip (Cc-Channel /
Cc-Action), one that fails commits nothing; the meme-job kind is gone;
git's refusal is said in the output (`cc-commit: refused`), nothing staged;
the ending's `_running` reads the render's own last line past the
`cc-commit:` lines.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from test_cc_api_batches import TMP, factory_tree, git                      # noqa: E402

from api import detached_commit, ending                                     # noqa: E402

#: brand_ending.py's stand-in: writes --out and prints it, or fails as ffmpeg would.
SCRIPT = r'''
import sys
from pathlib import Path

args = sys.argv[1:]
out = Path(args[args.index("--out") + 1])
if "--fail" in args:
    sys.exit("ffmpeg failed")
out.write_bytes(b"a new clip")
print(out)
'''


def world():
    """A committed root with a channel's clip."""
    root = factory_tree()
    (root / "channels" / "reel").mkdir(parents=True, exist_ok=True)
    (root / "channels" / "reel" / "ending.mp4").write_bytes(b"the old clip")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the world")
    side = TMP / f"stand-ins-{root.name}"
    side.mkdir()
    (side / "brand_ending.py").write_text(SCRIPT, encoding="utf-8")
    return root, side


def run(argv, cwd):
    cp = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, timeout=120)
    return cp.returncode, cp.stdout + cp.stderr


def refusing(root):
    hooks = TMP / f"refusing-hooks-{root.name}"
    hooks.mkdir()
    (hooks / "pre-commit").write_text("#!/bin/sh\necho no >&2\nexit 1\n", encoding="utf-8")
    (hooks / "pre-commit").chmod(0o755)
    git(root, "config", "core.hooksPath", str(hooks))


def ending_argv(root, side, *extra):
    out = root / "channels" / "reel" / "ending.mp4"
    return detached_commit.argv_head(detached_commit.ENDING, root, "reel", out,
                                     side / "brand_ending.py") + \
        ["reel", "--out", str(out), *extra]


# --------------------------------------------------------------------- the ending
def test_a_render_that_ends_with_0_commits_the_clip():
    root, side = world()
    h = git(root, "rev-parse", "HEAD")
    rc, out = run(ending_argv(root, side), root)
    assert rc == 0, out
    assert git(root, "rev-parse", "HEAD~1") == h, "one commit on top"
    assert git(root, "show", "--name-only", "--format=", "HEAD") == "channels/reel/ending.mp4"
    msg = git(root, "log", "-1", "--format=%B")
    assert msg.startswith("Концовка reel: отрендерена (user, center)"), msg
    assert "Cc-Channel: reel" in msg and "Cc-Action: ending_render" in msg, msg
    assert git(root, "status", "--porcelain", "--untracked-files=all") == ""
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert lines[0] == str(root / "channels" / "reel" / "ending.mp4"), lines
    assert lines[-1].startswith("cc-commit: committed"), lines


def test_a_render_that_fails_commits_nothing():
    root, side = world()
    h = git(root, "rev-parse", "HEAD")
    rc, out = run(ending_argv(root, side, "--fail"), root)
    assert rc == 1 and "ffmpeg failed" in out, out
    assert git(root, "rev-parse", "HEAD") == h
    assert git(root, "status", "--porcelain", "--untracked-files=all") == ""


def test_a_clip_commit_git_refuses_is_said_and_nothing_stays_staged():
    root, side = world()
    refusing(root)
    h = git(root, "rev-parse", "HEAD")
    rc, out = run(ending_argv(root, side), root)
    assert rc == 0, out
    assert git(root, "rev-parse", "HEAD") == h
    assert git(root, "diff", "--cached", "--name-only") == ""
    assert "cc-commit: refused" in out, out
    assert git(root, "status", "--porcelain") == "M channels/reel/ending.mp4"


def test_the_running_render_reads_past_the_commit_lines():
    root, side = world()
    log = root / "render.log"
    out = root / "channels" / "reel" / "ending.mp4"
    log.write_text(f"{out}\ncc-commit: committed 0123456789ab: channels/reel/ending.mp4\n",
                   encoding="utf-8")
    key = (str(root.resolve()), "reel")
    with ending._CACHE_LOCK:
        ending._STARTED[key] = {"pid": 1, "log": str(log), "out": str(out),
                                "at": ending._clock(), "started_at": "2026-10-22T01:00:00Z"}
    try:
        assert ending._running(root, "reel") is None, "the render's own last line is the clip"
        log.write_text("rendering ...\n", encoding="utf-8")
        assert ending._running(root, "reel") is not None
    finally:
        with ending._CACHE_LOCK:
            ending._STARTED.pop(key, None)


def test_the_meme_job_kind_is_gone():
    """CC-0158: the meme jobs' commit is the factory's (CF-0847) - no such kind."""
    assert not hasattr(detached_commit, "MEME") and not hasattr(detached_commit, "meme_job")
    rc, out = run(detached_commit.argv_head("meme_job", "desk.py", "reel", "meme_cutout",
                                            "state.json"), TMP)
    assert rc == 2 and "unknown kind 'meme_job'" in out, out


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
