"""CF-0685: a root commit that edits only ANOTHER channel's config is not code
drift for the open batch.

The user's decision of 2026-10-11: the command center refuses an edit of a
channel only while a batch of that same channel is open; an edit of another
channel is allowed and its commit moves the root's HEAD. Such a commit must not
be written to the open batch as `code_drift` (CF-0398/0484) nor counted by
triage as "the video was built off the run's code". An edit of the batch's own
channel, and a commit mixing another channel with code, still are drift. Old
channel names (`former_channel_ids`) resolve to the current id on both sides.

Every repo here is a temp git repo under `_tmproot.tmp_root`; nothing reads the
live tree.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "runlog"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import runlog       # noqa: E402
import triage       # noqa: E402
from _tmproot import tmp_root   # noqa: E402

TMP = tmp_root("code-drift-channel-test-")
_n = [0]

REEL, TECH = "example-film", "example-tech"
OLD_REEL = "legacy-film"            # a former id of REEL


def _repo():
    """A temp factory root: channels/REEL.json (with a former id), TECH.json,
    channels/TECH/ and some code. Returns (dir, git, commit)."""
    _n[0] += 1
    d = TMP / f"root-{_n[0]}"
    d.mkdir()

    def git(*a):
        return subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c",
                               "user.email=t@t", *a], capture_output=True, text=True,
                              check=True).stdout.strip()

    def commit(files, msg="c"):
        for path, text in files.items():
            f = d / path
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8")
        git("add", "-A", "--", *files)
        git("commit", "-q", "-m", msg)
        return git("rev-parse", "HEAD")

    git("init", "-q")
    commit({f"channels/{REEL}.json": json.dumps({"channel_id": REEL,
                                                 "former_channel_ids": [OLD_REEL], "v": 1}),
            f"channels/{TECH}.json": json.dumps({"channel_id": TECH, "v": 1}),
            f"channels/{TECH}/brief.md": "tech 1\n",
            "channels/ACCOUNTS.md": "accounts 1\n",
            "shared/x.py": "a = 1\n"}, "start")
    return d, git, commit


def _tech_edit(commit):
    return commit({f"channels/{TECH}.json": json.dumps({"channel_id": TECH, "v": 2}),
                   f"channels/{TECH}/brief.md": "tech 2\n"}, "tech edit from the center")


# --------------------------------------------------------------------------
# code_paths_moved / code_moved
# --------------------------------------------------------------------------

def test_another_channels_config_is_not_drift_for_this_channel():
    d, git, commit = _repo()
    was = git("rev-parse", "HEAD")
    now = _tech_edit(commit)
    assert runlog.code_paths_moved(d, was, now, channel=REEL) == []
    assert runlog.code_moved("root", was, now, d, channel=REEL) is False


def test_the_batchs_own_channel_config_is_drift():
    d, git, commit = _repo()
    was = git("rev-parse", "HEAD")
    now = _tech_edit(commit)
    assert runlog.code_paths_moved(d, was, now, channel=TECH) == \
        [f"channels/{TECH}.json", f"channels/{TECH}/brief.md"]
    assert runlog.code_moved("root", was, now, d, channel=TECH) is True


def test_a_mixed_commit_of_another_channel_and_code_is_drift():
    d, git, commit = _repo()
    was = git("rev-parse", "HEAD")
    now = commit({f"channels/{TECH}.json": json.dumps({"channel_id": TECH, "v": 3}),
                  "shared/x.py": "a = 2\n"}, "mixed")
    assert runlog.code_paths_moved(d, was, now, channel=REEL) == ["shared/x.py"]
    assert runlog.code_moved("root", was, now, d, channel=REEL) is True


def test_a_shared_file_of_channels_is_code_for_every_channel():
    d, git, commit = _repo()
    was = git("rev-parse", "HEAD")
    now = commit({"channels/ACCOUNTS.md": "accounts 2\n"}, "accounts")
    assert runlog.code_moved("root", was, now, d, channel=REEL) is True


def test_old_channel_names_resolve_to_the_current_id():
    d, git, commit = _repo()
    was = git("rev-parse", "HEAD")
    # the batch named by the former id: its own config (current file name) is drift
    own = commit({f"channels/{REEL}.json": json.dumps({"channel_id": REEL,
                                                       "former_channel_ids": [OLD_REEL],
                                                       "v": 2})}, "reel edit")
    assert runlog.code_moved("root", was, own, d, channel=OLD_REEL) is True
    # a leftover dir under the former id is still REEL's config
    old_dir = commit({f"channels/{OLD_REEL}/legacy.md": "x\n"}, "old-name dir")
    assert runlog.code_moved("root", own, old_dir, d, channel=REEL) is True
    assert runlog.code_moved("root", own, old_dir, d, channel=TECH) is False
    # another channel's edit under a batch named by REEL's former id: not drift
    tech = _tech_edit(commit)
    assert runlog.code_moved("root", old_dir, tech, d, channel=OLD_REEL) is False


def test_without_a_channel_every_channel_config_is_code_as_before():
    d, git, commit = _repo()
    was = git("rev-parse", "HEAD")
    now = _tech_edit(commit)
    assert runlog.code_paths_moved(d, was, now) == \
        [f"channels/{TECH}.json", f"channels/{TECH}/brief.md"]
    assert runlog.code_moved("root", was, now, d) is True


def test_batch_channel_reads_the_pipeline_path():
    d, _, _ = _repo()
    assert runlog.batch_channel(d / "pipeline" / REEL / "2026-10-11T1000Z", d) == REEL
    assert runlog.batch_channel(d / "pipeline" / OLD_REEL / "2026-10-11T1000Z", d) == REEL
    assert runlog.batch_channel(d / "pipeline" / "rebuilds" / "2026-10-11T1000Z", d) is None
    assert runlog.batch_channel(d / "pipeline" / "backfill" / "x", d) is None
    assert runlog.batch_channel(d / "elsewhere" / REEL / "x", d) is None
    assert runlog.batch_channel(None, d) is None


# --------------------------------------------------------------------------
# code_drift on the markers
# --------------------------------------------------------------------------

def _events(start):
    return [{"ts": "2026-10-11T10:00:00.000Z", "kind": "marker", "status": "batch-start",
             "stage": None, "header": {"git": {"root": {"commit": start}}}}]


def test_code_drift_skips_another_channels_edit_and_keeps_its_own():
    d, git, commit = _repo()
    start = git("rev-parse", "HEAD")
    b = d / "pipeline" / REEL / "2026-10-11T1000Z"
    b.mkdir(parents=True)
    evs = _events(start)
    _tech_edit(commit)
    assert runlog.code_drift(evs, b, root=d) == []
    # a batch of TECH sees the same move as drift
    bt = d / "pipeline" / TECH / "2026-10-11T1000Z"
    bt.mkdir(parents=True)
    assert [x["repo"] for x in runlog.code_drift(evs, bt, root=d)] == ["root"]
    # a rebuild has no channel: every channel config is code, as before
    br = d / "pipeline" / "rebuilds" / "2026-10-11T1000Z"
    br.mkdir(parents=True)
    assert [x["repo"] for x in runlog.code_drift(evs, br, root=d)] == ["root"]
    # the batch named by REEL's former id: its own edit is drift
    now = commit({f"channels/{REEL}.json": json.dumps({"channel_id": REEL,
                                                       "former_channel_ids": [OLD_REEL],
                                                       "v": 9})}, "reel edit")
    bo = d / "pipeline" / OLD_REEL / "2026-10-11T1000Z"
    bo.mkdir(parents=True)
    assert runlog.code_drift(evs, bo, root=d) == [{"repo": "root", "was": start, "now": now}]


# --------------------------------------------------------------------------
# triage: a ready video built after another channel's edit
# --------------------------------------------------------------------------

def _built_off(d, channel, start, commit_sha):
    b = d / "pipeline" / channel / f"2026-10-11T1{_n[0]:03d}Z"
    _n[0] += 1
    b.mkdir(parents=True)
    v = {"script_id": "s1", "output_path": "/x/s1.mp4", "qc": {"passed": True},
         "code_shas": {"root": {"commit": commit_sha, "dirty": False}}}
    (b / "05-video-editor.json").write_text(json.dumps({"batch_id": "B", "refusals": [],
                                                        "videos": [v]}), encoding="utf-8")
    return triage.built_off_run_incidents(_events(start), b, ["s1"], root=d)


def test_triage_applies_the_same_rule():
    d, git, commit = _repo()
    start = git("rev-parse", "HEAD")
    tech = _tech_edit(commit)
    assert _built_off(d, REEL, start, tech) == []
    assert [i["key"] for i in _built_off(d, TECH, start, tech)] == \
        ["built_off_run:root:commit"]
    mixed = commit({f"channels/{TECH}.json": "{}", "shared/x.py": "a = 9\n"}, "mixed")
    assert [i["key"] for i in _built_off(d, REEL, start, mixed)] == \
        ["built_off_run:root:commit"]


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
