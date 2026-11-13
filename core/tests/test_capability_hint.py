#!/usr/bin/env python3
"""CF-0653: scripts/capability_hint.py lists a diff's new user capabilities.

A hint for the driver's check by hand at a task's close (new command / flag /
channel key -> an address in api/openapi.json or a CC- task). Checked on a
canned diff and on a throwaway git repository in a tmp directory - no live
repository, no network.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "capability_hint.py"
_spec = importlib.util.spec_from_file_location("capability_hint", SCRIPT)
ch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ch)

DIFF = """\
diff --git a/scripts/runlog b/scripts/runlog
--- a/scripts/runlog
+++ b/scripts/runlog
@@ -10,0 +11,3 @@
+    p = sub.add_parser("pause-channel", help="pause one channel")
+    p.add_argument("channel")
+    p.add_argument("--until", default=None)
@@ -40 +43 @@
-    q.add_argument("--batch", required=True)
+    q.add_argument("--batch", required=True, help="the batch dir")
diff --git a/shared/run_plan.py b/shared/run_plan.py
--- a/shared/run_plan.py
+++ b/shared/run_plan.py
@@ -5 +5 @@
-    sub.add_parser("show")
+    sub.add_parser(name="list")
diff --git a/tests/test_x.py b/tests/test_x.py
--- a/tests/test_x.py
+++ b/tests/test_x.py
@@ -1,0 +2 @@
+    ap.add_argument("--stand-only")
diff --git a/api/__main__.py b/api/__main__.py
--- a/api/__main__.py
+++ b/api/__main__.py
@@ -1,0 +2 @@
+    sub.add_parser("serve")
diff --git a/shared/gone.py b/shared/gone.py
--- a/shared/gone.py
+++ /dev/null
@@ -1 +0,0 @@
-    ap.add_argument("--old")
"""


def test_scan_diff_finds_new_commands_and_flags():
    got = [(i["file"], i["kind"], i["name"]) for i in ch.scan_diff(DIFF)]
    assert got == [
        ("scripts/runlog", "command", "pause-channel"),
        ("scripts/runlog", "argument", "channel"),
        ("scripts/runlog", "flag", "--until"),
        ("shared/run_plan.py", "command", "list"),
    ], got


def test_an_edited_flag_is_not_new():
    names = {i["name"] for i in ch.scan_diff(DIFF)}
    assert "--batch" not in names and "show" not in names


def test_tests_api_and_deleted_files_are_skipped():
    names = {i["name"] for i in ch.scan_diff(DIFF)}
    assert "--stand-only" not in names and "--old" not in names and "serve" not in names


def test_new_json_keys_lists_new_paths_once():
    old = {"a": 1, "video_editor": {"max_attempts_per_video": 3}, "lst": [1]}
    new = {"a": 2, "video_editor": {"max_attempts_per_video": 3, "pace": {"wpm": 150}},
           "lst": [1, 2], "upload": {"hour": 9}}
    assert ch.new_json_keys(old, new) == ["video_editor.pace", "upload"]
    assert ch.new_json_keys({}, {"x": {"y": 1}}) == ["x"]
    assert ch.new_json_keys({"x": 1}, {"x": {"y": 1}}) == ["x.y"]


def test_met_in_openapi_swaps_dashes_and_ignores_case():
    text = '{"paths": {"/api/questions/{qid}/answer": {}}, "x": "pause_channel"}'
    assert ch.met_in_openapi("pause-channel", text)
    assert ch.met_in_openapi("--Answer", text)
    assert ch.met_in_openapi("video_editor.questions", text)
    assert not ch.met_in_openapi("--until", text)
    assert not ch.met_in_openapi("anything", "")


def _git(repo, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env=env, timeout=30)


def test_cli_on_a_tmp_repository():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "r"
        (repo / "scripts").mkdir(parents=True)
        (repo / "channels").mkdir()
        _git(repo, "init", "-q")
        (repo / "scripts" / "tool.py").write_text("import argparse\n")
        (repo / "channels" / "c.json").write_text(json.dumps({"a": 1}))
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "base", "--no-verify")
        (repo / "scripts" / "tool.py").write_text(
            "import argparse\nap = argparse.ArgumentParser()\n"
            "ap.add_argument('--dry-run')\n")
        (repo / "channels" / "c.json").write_text(json.dumps({"a": 2, "upload": {"hour": 9}}))
        _git(repo, "commit", "-qam", "head", "--no-verify")
        api = Path(tmp) / "openapi.json"
        api.write_text('{"paths": {"/api/upload": {}}}')
        cp = subprocess.run([sys.executable, str(SCRIPT), "HEAD~1", "-C", str(repo),
                             "--openapi", str(api), "--json"],
                            capture_output=True, text=True, timeout=60)
        assert cp.returncode == 0, cp.stderr
        rows = {(r["kind"], r["name"], r["in_openapi"]) for r in json.loads(cp.stdout)}
        assert rows == {("flag", "--dry-run", False), ("setting", "upload", True)}, rows
        cp = subprocess.run([sys.executable, str(SCRIPT), "HEAD~1..HEAD", "-C", str(repo),
                             "--openapi", str(api)],
                            capture_output=True, text=True, timeout=60)
        assert cp.returncode == 0 and "NOT in openapi" in cp.stdout, cp.stdout




if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
