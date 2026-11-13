#!/usr/bin/env python3
"""CC-0101 / CC-0114: a channel's ending clip, its data and its render
(`api/ending.py`, on CF-0722):

    GET  /api/channels/{channel}/ending        end_card.ending_path / ending_seconds /
                                               probe_ending / check_ending, brand.json's
                                               `ending`, brand_ending.render_plan
    POST /api/channels/{channel}/ending/plan   the plan afresh, the guards, a token
    POST /api/channels/{channel}/ending        {confirm} - brand_ending.py detached

In-process (the TestClient) against a stand-in factory root in a temp dir.
The factory's reader runs in a child interpreter (`ending.run_reader`): most
tests put a stand-in there and look at what it was given; one runs the real
child on the temp tree - it imports the Video Editor's `end_card.py` and
`brand_ending.py` of this checkout and probes a clip of garbage bytes (a
local ffprobe at most, nothing rendered, no network). Nothing is written.

What is pinned: the clip's place by the factory's route, its bytes, mtime and
sha256, the declared and probed length and the check, the root's path never
leaving; the data block and the render block from the factory's plan - each
refusal code with its Russian line and no code in it, Reel's «made by hand»;
no media URL; the child's cwd outside the root and without RUNLOG_BATCH; the
answer kept until the clip or brand.json changes; an unknown channel; a
reader that fails. The render: plan -> confirm, the launcher a stand-in
(`ending.run_launcher` - nothing is ever rendered), the token's life, an open
batch, a render still running, a plan that changed; `child.detach` itself on
a harmless `print` in a temp root.
"""
import time
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ.pop("FACTORY_ROOT", None)

from test_cc_api_batches import _w, client, factory_tree                    # noqa: E402
from test_cc_api_publish import files                                        # noqa: E402

from test_cc_api_batches import H                                            # noqa: E402

from api import batches, child, detached_commit, ending                      # noqa: E402

URL = "/api/channels/reel/ending"
PROBE = {"seconds": 5.166667, "width": 1080, "height": 1920, "fps": 30.0, "has_audio": True}


class Reader:
    """A stand-in for the child: the answer the factory's functions would give."""

    def __init__(self, answer=None, rc=0):
        self.answer, self.rc, self.calls = answer, rc, []

    def __enter__(self):
        self.saved = ending.run_reader
        ending.run_reader = self
        ending._CACHE.clear()
        return self

    def __call__(self, cmd, cwd, env):
        self.calls.append((cmd, cwd, env))
        return self.rc, (json.dumps(self.answer) + "\n") if self.answer else "", "boom\n"

    def __exit__(self, *exc):
        ending.run_reader = self.saved
        ending._CACHE.clear()


def answer(root, **kw):
    a = {"path": str(root / "channels" / "reel" / "ending.mp4"), "source": "convention",
         "path_error": None, "declared": 5.167, "probe": PROBE, "probe_error": None,
         "check_error": None, "brand_error": None,
         "brand": {"channels": ["example-science", "example-tech"], "width": 1080, "height": 1920,
                   "fps": 30, "frames": 155,
                   "motifs": {"example-science": "stars", "example-tech": "circuit"}},
         "data": {"exists": False, "section": None, "errors": [], "error": None},
         "plan": {"ok": False, "plan": None,
                  "refusal": {"code": "ending_no_generator",
                              "message": "ending_no_generator: 'reel' has no row in "
                                         "brand_ending.BRANDS"}}}
    a.update(kw)
    return a


SHA = "a" * 64


def section(root, render=True):
    return {"clip": "channels/reel/ending.mp4", "clip_sha256": SHA,
            "render": None if not render else
            {"fonts": "shared/brand/fonts", "track": "channels/reel/brand/ending-track.mp3",
             "track_sha256": "b" * 64, "audio_start": 300.0, "audio_gain_db": 0.0},
            "note": "n"}


def plan_ok(root):
    out = root / "channels" / "reel" / "ending.mp4"
    track = root / "channels" / "reel" / "brand" / "ending-track.mp3"
    return {"ok": True, "refusal": None,
            "plan": {"channel": "reel", "fonts": str(root / "shared" / "brand" / "fonts"),
                     "audio": str(track), "audio_start": 300.0, "audio_gain_db": 0.0,
                     "out": str(out), "command": ["ffmpeg", "-i", str(track), str(out)],
                     "sources": {"fonts": "data", "audio": "data", "audio_start": "data",
                                 "audio_gain_db": "data", "out": "data"},
                     "clip_sha256": SHA}}


def refused(code, message):
    return {"ok": False, "plan": None, "refusal": {"code": code, "message": message}}


class Launcher:
    """A stand-in for `child.detach`: records what it was given, starts nothing."""

    def __init__(self, fail=None):
        self.fail, self.calls = fail, []

    def __enter__(self):
        self.saved = ending.run_launcher
        ending.run_launcher = self
        ending._STARTED.clear()
        return self

    def __call__(self, argv, root, day, label, env):
        self.calls.append((argv, root, day, label, env))
        if self.fail:
            raise self.fail
        log = Path(root) / "schedule" / "logs" / f"{day}-{label}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("", encoding="utf-8")
        return 4242, str(log)

    def __exit__(self, *exc):
        ending.run_launcher = self.saved
        ending._STARTED.clear()


def test_the_clip_as_the_factory_sees_it_and_no_render():
    root = factory_tree()
    clip = root / "channels" / "reel" / "ending.mp4"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"clip" * 100)
    _w(root / "channels" / "reel" / "SOURCES.md",
       "the command:\n    python3 scripts/brand_ending.py reel --fonts <dir>\n")
    before = files(root)
    os.environ["RUNLOG_BATCH"] = str(root / "pipeline" / "reel" / "x")
    try:
        with Reader(answer(root)) as rd:
            c = client(root)
            r = c.get(URL)
            assert r.status_code == 200, r.text
            v = r.json()
            assert (v["channel"], v["path"], v["source"], v["exists"]) == \
                ("reel", "channels/reel/ending.mp4", "convention", True), v
            assert v["bytes"] == 400 and v["sha256"] == hashlib.sha256(b"clip" * 100).hexdigest()
            assert v["mtime"].endswith("Z") and v["cached"] is False, v
            assert v["declared_seconds"] == 5.167 and v["probe"] == PROBE, v
            assert v["check"] == {"ok": True, "error": None,
                                  "against": {"width": 1080, "height": 1920, "fps": 30.0}}, v
            assert v["media_url"] is None
            g = v["generator"]
            assert g["script"] == "scripts/brand_ending.py" and g["renders_channel"] is False
            assert g["channels"] == ["example-science", "example-tech"] and g["frames"] == 155
            rn = v["render"]
            assert rn["available"] is False and rn["refusal"]["code"] == "ending_no_generator"
            assert rn["why"] == rn["refusal"]["message"] and "ending_" not in rn["why"], rn
            assert [n["arg"] for n in rn["needs"]] == ["--fonts", "--audio", "--audio-start",
                                                       "--audio-gain-db"], rn
            assert [n["key"] for n in rn["needs"]] == [
                "ending.render.fonts", "ending.render.track", "ending.render.audio_start",
                "ending.render.audio_gain_db"], rn
            assert not any(n["stored"] for n in rn["needs"]) and rn["factory_ask"] is None
            assert rn["sources_docs"] == ["channels/reel/SOURCES.md"], rn
            assert rn["plan"] is None and rn["by_hand"] is False and rn["last_run"] is None
            assert v["data"] == {"path": "channels/reel/brand.json", "exists": False,
                                 "section": False, "clip": None, "clip_sha256": None,
                                 "clip_matches": None, "render": None, "note": None,
                                 "errors": [], "error": None}, v["data"]
            assert str(root) not in r.text
            # the child: the factory's reader of this checkout, outside the root, no batch
            (cmd, cwd, env), = rd.calls
            assert cmd[1] == "-c" and cmd[-3].endswith("scripts/brand_ending.py"), cmd
            assert cmd[-2].endswith("shared/channel_data.py") and cmd[-1] == "reel", cmd
            assert not str(Path(cwd).resolve()).startswith(str(root.resolve())), cwd
            assert "RUNLOG_BATCH" not in env
            # kept while nothing changed; a changed clip is read again
            r = c.get(URL)
            assert r.json()["cached"] is True and len(rd.calls) == 1
            clip.write_bytes(b"other clip")
            r = c.get(URL)
            assert r.json()["cached"] is False and len(rd.calls) == 2
            assert r.json()["bytes"] == 10
            clip.write_bytes(b"clip" * 100)
            # brand.json is in the key too
            c.get(URL)
            r = c.get(URL)
            assert r.json()["cached"] is True
            _w(root / "channels" / "reel" / "brand.json", {"channel_id": "reel"})
            r = c.get(URL)
            assert r.json()["cached"] is False, r.json()
            (root / "channels" / "reel" / "brand.json").unlink()
    finally:
        os.environ.pop("RUNLOG_BATCH", None)
    assert files(root) == before, "a read writes nothing"


def test_the_data_and_each_refusal_in_russian():
    root = factory_tree()
    clip = root / "channels" / "reel" / "ending.mp4"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"clip")
    data = {"exists": True, "section": section(root, render=False), "errors": [], "error": None}
    # Reel: made by hand - the data says so before brand_ending's own refusal
    with Reader(answer(root, data=data)):
        v = client(root).get(URL).json()
        rn, d = v["render"], v["data"]
        assert rn["available"] is False and rn["by_hand"] is True, rn
        assert rn["refusal"]["code"] == "ending_by_hand", rn
        assert rn["why"].startswith("Концовка канала reel сделана вручную - рендер не нужен"), rn
        assert d["section"] is True and d["render"] is None and d["clip_sha256"] == SHA, d
        assert d["clip"] == "channels/reel/ending.mp4" and d["clip_matches"] is False, d
    good = {"exists": True, "section": section(root), "errors": [], "error": None}
    cases = {
        "ending_file_missing": "файлов для него нет в дереве",
        "ending_sha256_mismatch": "sha256 не совпадает",
        "ending_args_missing": "не хватает аргументов",
        "ending_no_generator": "не рисует концовку",
        "plan_broken": "План рендера не прочитан",
    }
    for code, words in cases.items():
        with Reader(answer(root, data=good, plan=refused(code, f"{code}: the factory's line "
                                                               f"{root}/x"))):
            r = client(root).get(URL)
            rn = r.json()["render"]
            assert rn["available"] is False and rn["refusal"]["code"] == code, rn
            assert words in rn["why"] and code not in rn["why"], (code, rn["why"])
            assert any("the factory's line" in x for x in rn["refusal"]["details"]), rn
            assert str(root) not in r.text
            if code == "ending_file_missing":
                assert rn["factory_ask"].startswith("Файлов нет в дереве"), rn
                assert "channels/reel/brand.json" in rn["factory_ask"]
                assert all(n["stored"] for n in rn["needs"]), rn["needs"]
                assert [n["present"] for n in rn["needs"]] == [False, False, None, None]
                assert rn["needs"][2]["value"] == 300.0
    # a section the factory refuses
    bad = {"exists": True, "section": None, "errors": ["`ending` has no `clip`"],
           "error": {"code": "ending_invalid", "line": "the ending of 'reel': no clip"}}
    with Reader(answer(root, data=bad)):
        v = client(root).get(URL).json()
        rn = v["render"]
        assert rn["refusal"]["code"] == "ending_invalid" and "не проходит проверку" in rn["why"]
        assert "ending_errors: `ending` has no `clip`" in rn["refusal"]["details"], rn
        assert v["data"]["error"]["code"] == "ending_invalid" and v["data"]["errors"], v["data"]
    # ok: the plan, paths from the root
    with Reader(answer(root, data=good, plan=plan_ok(root))):
        r = client(root).get(URL)
        rn = r.json()["render"]
        assert rn["available"] is True and rn["why"] is None and rn["refusal"] is None, rn
        assert rn["plan"]["fonts"] == "shared/brand/fonts", rn["plan"]
        assert rn["plan"]["out"] == "channels/reel/ending.mp4" and rn["factory_ask"] is None
        assert str(root) not in r.text


def test_the_render_plan_confirm_and_its_guards():
    root = factory_tree()
    os.environ["RUNLOG_BATCH"] = str(root / "pipeline" / "reel" / "x")
    good = {"exists": True, "section": section(root), "errors": [], "error": None}
    try:
        with Reader(answer(root, data=good, plan=plan_ok(root))) as rd, Launcher() as ln:
            c = client(root)
            r = c.post(URL + "/plan", headers=H)
            assert r.status_code == 200, r.text
            p = r.json()
            assert p["ok"] is True and p["action"] == "ending_render" and p["confirm"], p
            assert p["expires_in_s"] == int(batches.CONFIRM_TTL) and p["batches"] == []
            assert p["argv"][1].endswith("scripts/brand_ending.py") and p["argv"][2] == "reel"
            assert p["argv"][3:] == ["--fonts", "shared/brand/fonts", "--audio",
                                     "channels/reel/brand/ending-track.mp3", "--audio-start",
                                     "300.0", "--audio-gain-db", "0.0", "--out",
                                     "channels/reel/ending.mp4"], p["argv"]
            assert str(root) not in r.text and ln.calls == []
            # no writes header: refused
            assert c.post(URL + "/plan").status_code in (401, 403)
            r = c.post(URL, headers=H, json={"confirm": p["confirm"]})
            assert r.status_code == 200, r.text
            res = r.json()
            assert res["ok"] is True and res["pid"] == 4242, res
            assert res["log"].startswith("schedule/logs/") and res["log"].endswith(
                "-reel-ending.log"), res
            assert res["out"] == "channels/reel/ending.mp4" and str(root) not in r.text
            (argv, lroot, day, label, env), = ln.calls
            assert label == "reel-ending" and "RUNLOG_BATCH" not in env
            # CC-0156: api/detached_commit.py before the script - the clip's commit when it
            # ends with 0; the script's own argv after it, as the plan's
            assert argv[:3] == [sys.executable, "-c", detached_commit.BOOTSTRAP], argv
            assert argv[4:7] == ["ending_render", str(root.resolve()), "reel"], argv
            assert argv[7].endswith("channels/reel/ending.mp4"), argv
            assert argv[8].endswith("scripts/brand_ending.py") and argv[9] == "reel", argv
            assert argv[10] == "--fonts" and argv[11] == str(root / "shared" / "brand" / "fonts")
            assert Path(lroot) == root.resolve()
            # spent
            r = c.post(URL, headers=H, json={"confirm": p["confirm"]})
            assert r.status_code == 409 and r.json()["code"] == "confirm_unknown", r.text
            # running: the view says so, the plan refuses
            v = c.get(URL).json()
            assert v["render"]["last_run"]["pid"] == 4242 and v["render"]["last_run"]["running"]
            p2 = c.post(URL + "/plan", headers=H).json()
            assert p2["ok"] is False and p2["refusal"]["code"] == "render_running", p2
            assert "уже рендерится" in p2["why"] and p2["confirm"] is None
            # its log names the clip: over
            Path(root / res["log"]).write_text(str(root / "channels" / "reel" / "ending.mp4")
                                               + "\n", encoding="utf-8")
            p3 = c.post(URL + "/plan", headers=H).json()
            assert p3["ok"] is True, p3
            # CC-0161: the last `cc-commit:` line of the log said refused - git's word, paths
            # cut; a later word (committed, nothing) or none: null
            lr = c.get(URL).json()["render"]["last_run"]
            assert lr["running"] is False and lr["commit_refused"] is None, lr
            clip = str(root / "channels" / "reel" / "ending.mp4")
            for lines, want in (
                    ([clip, f"cc-commit: refused - git refused the commit fatal: index.lock "
                            f"| touched: {clip}"],
                     "git refused the commit fatal: index.lock | touched: "
                     "channels/reel/ending.mp4"),
                    ([clip, "cc-commit: refused - x", "cc-commit: committed 0123456789ab: "
                                                     "channels/reel/ending.mp4"], None),
                    ([clip, "cc-commit: nothing to commit"], None),
                    ([clip], None)):
                Path(root / res["log"]).write_text("\n".join(lines) + "\n", encoding="utf-8")
                r = c.get(URL)
                lr = r.json()["render"]["last_run"]
                assert lr["commit_refused"] == want and lr["running"] is False, (lines, lr)
                assert str(root) not in r.text
            Path(root / res["log"]).write_text(clip + "\n", encoding="utf-8")
            # the plan changed between the plan and the confirm
            rd.answer = answer(root, data=good, plan=dict(plan_ok(root), plan=dict(
                plan_ok(root)["plan"], audio_start=12.0)))
            r = c.post(URL, headers=H, json={"confirm": p3["confirm"]})
            assert r.status_code == 409 and r.json()["code"] == "check_changed", r.text
            # the factory refuses at the confirm
            p4 = c.post(URL + "/plan", headers=H).json()
            rd.answer = answer(root, data=good, plan=refused("ending_sha256_mismatch", "x"))
            r = c.post(URL, headers=H, json={"confirm": p4["confirm"]})
            assert r.status_code == 409 and r.json()["code"] == "ending_sha256_mismatch"
            assert "sha256 не совпадает" in r.json()["message"]
            # expired
            rd.answer = answer(root, data=good, plan=plan_ok(root))
            p5 = c.post(URL + "/plan", headers=H).json()
            real = batches._clock
            batches._clock = lambda: real() + batches.CONFIRM_TTL + 1
            try:
                r = c.post(URL, headers=H, json={"confirm": p5["confirm"]})
            finally:
                batches._clock = real
            assert r.status_code == 409 and r.json()["code"] == "confirm_expired", r.text
            # an open batch of the channel
            saved = ending.channels.lock
            ending.channels.lock = lambda root_, cid, fresh=False, scan=None: {
                "locked": True, "message": f"Идёт батч канала {cid} (b1): пока он не "
                                           f"закончится, конфиг и позицию менять нельзя.",
                "batches": [{"dir": str(root / "pipeline" / cid / "b1")}]}
            try:
                p6 = c.post(URL + "/plan", headers=H)
            finally:
                ending.channels.lock = saved
            p6t, p6 = p6.text, p6.json()
            assert p6["ok"] is False and p6["refusal"]["code"] == "batch_open", p6
            assert p6["why"].startswith("Идёт батч канала reel") and p6["confirm"] is None
            assert p6["batches"] == ["pipeline/reel/b1"] and str(root) not in p6t
            assert len(ln.calls) == 1
        # Reel by hand: the plan refuses, no token
        bh = {"exists": True, "section": section(root, render=False), "errors": [], "error": None}
        with Reader(answer(root, data=bh)), Launcher() as ln:
            p = client(root).post(URL + "/plan", headers=H).json()
            assert p["ok"] is False and p["by_hand"] is True and p["confirm"] is None, p
            assert p["refusal"]["code"] == "ending_by_hand" and "вручную" in p["why"]
        # the launcher fails
        with Reader(answer(root, data=good, plan=plan_ok(root))), \
                Launcher(fail=child.Detach("no", ["launcher: exit 1", "boom"])):
            c = client(root)
            p = c.post(URL + "/plan", headers=H).json()
            r = c.post(URL, headers=H, json={"confirm": p["confirm"]})
            assert r.status_code == 500 and r.json()["code"] == "start_failed", r.text
            assert "boom" in r.json()["details"]
        with Reader(answer(root)):
            r = client(root).post("/api/channels/nobody/ending/plan", headers=H)
            assert r.status_code == 404 and r.json()["code"] == "unknown_channel", r.text
    finally:
        os.environ.pop("RUNLOG_BATCH", None)


def test_detach_starts_through_the_factory_and_answers_at_once():
    """`child.detach` for real on a harmless argv in a temp root: the factory's
    own detached start, the pid and the log under <root>/schedule/logs."""
    root = factory_tree()
    pid, log = child.detach([sys.executable, "-c", "print('hello from detach')"],
                            root=str(root), day="2026-10-13-000000", label="reel-ending")
    assert pid > 0 and Path(log) == root / "schedule" / "logs" / \
        "2026-10-13-000000-reel-ending.log", log
    for _ in range(50):
        if "hello from detach" in Path(log).read_text(encoding="utf-8"):
            break
        time.sleep(0.1)
    assert "hello from detach" in Path(log).read_text(encoding="utf-8")
    try:
        child.detach(["x"], root=str(root / "nowhere"), day="d", label="l")
    except (OSError, child.Detach):
        pass
    else:
        raise AssertionError("a root that is not there: no start")


def test_a_failed_check_no_clip_and_the_problems():
    root = factory_tree()
    with Reader(answer(root, check_error="the ending clip x is not the composition's format")):
        c = client(root)
        v = c.get(URL).json()
        assert v["check"]["ok"] is False and "format" in v["check"]["error"], v
        assert v["exists"] is False and v["bytes"] is None, v
    with Reader(answer(root, path=None, source=None, probe=None)):
        v = client(root).get(URL).json()
        assert (v["source"], v["probe"], v["check"], v["exists"]) == (None, None, None, False)
        assert v["path"] == "channels/reel/ending.mp4", v
    with Reader(answer(root)):
        r = client(root).get("/api/channels/nobody/ending")
        assert r.status_code == 404 and r.json()["code"] == "unknown_channel", r.text
        assert set(r.json()) == {"message", "code", "details"}
    with Reader(None, rc=1):
        r = client(root).get(URL)
        assert r.status_code == 500 and r.json()["code"] == "factory_broken", r.text
        assert str(root) not in r.text and "boom" in " ".join(r.json()["details"])


def test_the_real_reader_on_a_temp_tree():
    """The factory's own functions in the child: a clip that is no video, and a
    config that names a clip that is not there."""
    root = factory_tree()
    clip = root / "channels" / "reel" / "ending.mp4"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"not a video")
    cfg = json.loads((root / "channels" / "demo.json").read_text(encoding="utf-8"))
    cfg["video_editor"] = {"ending": {"path": "channels/demo/missing.mp4"}}
    _w(root / "channels" / "demo.json", cfg)
    ending._CACHE.clear()
    c = client(root)
    r = c.get(URL)
    assert r.status_code == 200, r.text
    v = r.json()
    assert (v["path"], v["source"], v["exists"]) == ("channels/reel/ending.mp4", "convention",
                                                     True), v
    assert v["probe"] is None and v["probe_error"] and v["check"] is None, v
    assert "example-science" in v["generator"]["channels"] and v["generator"]["error"] is None, v
    assert str(root) not in r.text
    r = c.get("/api/channels/demo/ending")
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["source"] is None and "missing.mp4" in v["path_error"] and not v["exists"], v
    assert str(root) not in r.text
    ending._CACHE.clear()


def test_the_real_plan_on_a_temp_tree():
    """brand.json and brand_ending.render_plan for real (the channel_data of
    this checkout copied into the temp tree, as render_plan loads it from the
    root): Reel by hand, a missing track, a swapped one, then an ok plan -
    render_plan renders nothing."""
    import shutil
    root = factory_tree()
    for f in ("channel_data.py", "channel_ids.py"):
        (root / "shared").mkdir(exist_ok=True)
        shutil.copy(ROOT / "shared" / f, root / "shared" / f)
    _w(root / "channels" / "reel" / "brand.json",
       {"channel_id": "reel", "ending": section(root, render=False)})
    _w(root / "channels" / "example-science.json",
       {"channel_id": "example-science", "display_name": "Science", "status": "no_pipeline",
        "status_note": "a stand-in", "batch_schedule": {"enabled": False}})
    track = b"not really an mp3"
    sec = {"clip": "channels/example-science/ending.mp4", "clip_sha256": SHA,
           "render": {"fonts": "shared/brand/fonts",
                      "track": "channels/example-science/brand/ending-track.mp3",
                      "track_sha256": hashlib.sha256(track).hexdigest(), "audio_start": 300.0,
                      "audio_gain_db": 0.0}}
    _w(root / "channels" / "example-science" / "brand.json",
       {"channel_id": "example-science", "ending": sec})
    ending._CACHE.clear()
    c = client(root)
    v = c.get(URL).json()
    assert v["render"]["refusal"]["code"] == "ending_by_hand", v["render"]
    assert v["data"]["section"] is True and v["data"]["render"] is None, v["data"]
    url = "/api/channels/example-science/ending"
    r = c.get(url)
    assert r.status_code == 200, r.text
    rn = r.json()["render"]
    assert rn["refusal"]["code"] == "ending_file_missing", rn
    assert "ending_file_missing" not in rn["why"] and str(root) not in r.text
    fonts = root / "shared" / "brand" / "fonts"
    fonts.mkdir(parents=True)
    for f in ("Poppins-ExtraBold.ttf", "Poppins-Bold.ttf"):
        (fonts / f).write_bytes(b"font")
    t = root / "channels" / "example-science" / "brand" / "ending-track.mp3"
    t.parent.mkdir(parents=True)
    t.write_bytes(b"somebody else's bytes")
    rn = c.get(url).json()["render"]
    assert rn["refusal"]["code"] == "ending_sha256_mismatch", rn
    t.write_bytes(track)
    r = c.get(url)
    rn = r.json()["render"]
    assert rn["available"] is True and rn["refusal"] is None, rn
    assert rn["plan"]["audio"] == "channels/example-science/brand/ending-track.mp3", rn["plan"]
    assert rn["plan"]["sources"]["audio"] == "data" and rn["plan"]["audio_start"] == 300.0
    assert [n["present"] for n in rn["needs"]] == [True, True, None, None], rn["needs"]
    assert not (root / "channels" / "example-science" / "ending.mp4").exists()
    assert str(root) not in r.text
    ending._CACHE.clear()


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                                  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
