#!/usr/bin/env python3
"""CC-0075: the meme desk's background jobs in the center (`api/meme_jobs.py`
over the factory's CF-0760/CF-0755 functions):

    POST /api/memes/{c}/cutout/plan     cutout_available + cutout_entries(dry_run)
    POST /api/memes/{c}/cutout          {confirm} - start_job("cutout") in the launcher child
    POST /api/memes/{c}/trim/plan       trim_blank_entries(dry_run)
    POST /api/memes/{c}/trim            {confirm} - start_job("trim_blank")
    GET  /api/memes/{c}/jobs            list_jobs + the running one
    GET  /api/memes/{c}/jobs/{job_id}   job_status + poll_s

In-process (starlette's TestClient) against the temp banks of
`tests/test_cc_api_memes.py` `world`. **No test starts a real job**: the
confirm's launcher child (`meme_jobs.run_launcher`) is a stand-in, except
where the real child runs `start_job` with what the factory refuses before
anything starts (a bad kind, bad params, an unknown id); the machine's slot
(`MEME_DESK_JOBS_DIR`) is a temp dir. A job "running" on a bank is a state
file planted here whose lock this test holds (flock - what `job_status`
reads as alive); none of them has a process. Vision is never called: the
cutout's availability is the factory's own check with `_platform` replaced
(not macOS) or `cutout_available` replaced (available). No network, no
sleeps.

What is pinned: the plans' shapes, nothing written by a plan; Vision
unavailable - the plan says why and gets no token, the confirm refuses; a
token single use, expired, of another channel; `check_changed` when
index.json moved; the factory's refusals of a start (job_running,
spawn_failed, bad_params from the real child) with their Russian text; the
guard while a job runs on the bank (marks, apply, accept, a new start -
`job_active` with the job's id; another bank free); job_status's states
(running, done, failed, interrupted) with poll_s and the routes; no
absolute path in any answer; the contract.
"""
import fcntl
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ.pop("ACCEPTANCE_LOG", None)
os.environ.pop("BATCH_SCHEDULE_STATE_DIR", None)

from test_cc_api_batches import TMP, client                         # noqa: E402
from test_cc_api_memes import _index, _png, desk, entry, get, send, world  # noqa: E402
from test_cc_api_publish import files                                # noqa: E402

import api                                                           # noqa: E402
from api import batches, meme_jobs, memes                            # noqa: E402

SLOT = TMP / "meme-desk-slot"
os.environ["MEME_DESK_JOBS_DIR"] = str(SLOT)     # a safety net: nothing here starts a job
meme_jobs.FACTORY_KW["environ"] = {"MEME_DESK_JOBS_DIR": str(SLOT)}
ROUTES = {"/api/memes/{channel}/cutout/plan": {"post"}, "/api/memes/{channel}/cutout": {"post"},
          "/api/memes/{channel}/trim/plan": {"post"}, "/api/memes/{channel}/trim": {"post"},
          "/api/memes/{channel}/jobs": {"get"}, "/api/memes/{channel}/jobs/{job_id}": {"get"}}


class Seams:
    """The factory's Vision check and the launcher child, replaced for one test."""

    def __init__(self, available=True, launcher=None):
        self.available, self.launcher, self.calls = available, launcher, []

    def __enter__(self):
        d = desk()
        self.saved = (d.cutout_available, d._platform, meme_jobs.run_launcher)
        if self.available:
            d.cutout_available = lambda: (True, "macOS 15.0, stand-in")
        else:
            d._platform = lambda: ("linux", "")
        meme_jobs.run_launcher = self._launch
        return self

    def _launch(self, cmd, cwd, env):
        self.calls.append((cmd, cwd, env))
        if self.launcher is None:
            raise AssertionError("the launcher child was started")
        return self.launcher(cmd, cwd, env)

    def __exit__(self, *exc):
        d = desk()
        d.cutout_available, d._platform, meme_jobs.run_launcher = self.saved


def started(root, bank="memes", kind="cutout", job_id="20261015T120000Z-cutout-abc123"):
    d = root / "shared" / "inserts" / bank / "_desk" / "jobs"

    def launcher(cmd, cwd, env):
        return 0, json.dumps({"ok": True, "job_id": job_id, "bank": bank, "kind": kind,
                              "pid": 4242, "log": str(d / f"{job_id}.log"),
                              "state_file": str(d / f"{job_id}.json")}) + "\n", ""
    return launcher


def plant(root, bank="memes", kind="cutout", state="running", held=False, result=None,
          error=None, stamp="20261015T120000Z", tail="abc123", progress=None, **extra):
    """A job's state file on the bank, its lock held by this test when `held`
    (returns the fd to close) - no process behind it."""
    job_id = f"{stamp}-{kind}-{tail}"
    d = root / "shared" / "inserts" / bank / "_desk" / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    log = d / f"{job_id}.log"
    log.write_text(f"job {job_id}: {kind}\nTraceback: {root}/scripts/meme_desk.py line 1\n",
                   encoding="utf-8")
    doc = {"job_id": job_id, "kind": kind, "bank": bank, "bank_name": None,
           "root": str(root / "shared" / "inserts"), "repo": str(root), "params": {},
           "plan": {}, "by": "user", "via": "center", "state": state,
           "started_at": "2026-10-15T12:00:00+00:00", "attached_at": None,
           "ended_at": None if state == "running" else "2026-10-15T12:01:00+00:00",
           "pid": 999999, "progress": progress, "result": result, "error": error,
           "log": str(log), "machine_dir": str(SLOT), "task": "CF-0755", **extra}
    (d / f"{job_id}.json").write_text(json.dumps(doc), encoding="utf-8")
    fd = None
    if held:
        fd = os.open(str(d / f"{job_id}.lock"), os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
    return job_id, fd


def no_abs(root, body):
    text = json.dumps(body, ensure_ascii=False)
    for p in {str(root), str(Path(root).resolve()), str(Path.home())}:
        assert p not in text, (p, text[:400])


def banded(path, w, h, band):
    """A red still with `band` white rows on top."""
    from PIL import Image
    im = Image.new("RGB", (w, h), "red")
    im.paste((255, 255, 255), (0, 0, w, band))
    im.save(path)


def trim_world():
    """world() + on Tech: a still whose band cut leaves it big enough (trim),
    one the cut would stretch over the ceiling (under), a banded GIF (left)."""
    root = world()
    tech = root / "shared" / "inserts" / "memes-tech"
    banded(tech / "tall.png", 600, 800, 200)
    banded(tech / "small.png", 300, 400, 100)
    from PIL import Image
    im = Image.new("RGB", (600, 800), "red")
    im.paste((255, 255, 255), (0, 0, 600, 200))
    im.save(tech / "band.gif", format="GIF")
    _index(root / "shared" / "inserts",
           [entry("tech-new", "tech-new.png", review="pending"), entry("tech-old", "tech-old.png"),
            entry("tall", "tall.png"), entry("small", "small.png"),
            entry("band-gif", "band.gif", clip={"start_s": 0.0, "end_s": 1.0})], "memes-tech")
    return root


# --------------------------------------------------------------------- the plans
def test_the_cutout_plan_is_the_dry_run_and_writes_nothing():
    root = world()
    c = client(root)
    before = files(root)
    with Seams():
        code, p = send(c, "POST", "/api/memes/reel/cutout/plan")
        assert code == 200, p
        assert p["action"] == "meme_cutout" and p["kind"] == "cutout" and p["dry_run"] is True
        assert p["available"] is True and p["available_reason"] == "macOS 15.0, stand-in", p
        assert sorted(m["id"] for m in p["made"]) == ["old-cut", "refused-cut"], p
        assert all(m["bbox_px"] is None and m["coverage"] is None for m in p["made"]), p
        assert p["refused"] == [] and p["outside_bank"] == [] and p["written"] is False, p
        assert p["ok"] is True and p["why"] is None and p["confirm"], p
        assert p["expires_in_s"] == 120 and p["params"] == {} and p["job"] is None, p
        assert any("только после прогона" in n for n in p["notes"]), p["notes"]
        assert len(p["index_fingerprint"]) == 64 and len(p["fingerprint"]) == 64, p
        code, p = send(c, "POST", "/api/memes/reel/cutout/plan",
                       {"ids": ["old-cut"], "force": True})
        assert code == 200 and p["params"] == {"ids": ["old-cut"], "force": True}, p
        assert [m["id"] for m in p["made"]] == ["old-cut"], p
    assert files(root) == before
    no_abs(root, p)


def test_the_plans_refuse_what_the_user_cannot_ask():
    root = trim_world()
    c = client(root)
    before = files(root)
    with Seams():
        for body, code_ in (({"ids": ["a-gif"]}, "not_cutout"), ({"ids": ["old-one"]}, "not_cutout"),
                            ({"ids": ["nope"]}, "unknown_id"), ({"ids": []}, "bad_ids")):
            code, r = send(c, "POST", "/api/memes/reel/cutout/plan", body)
            assert code == 422 and r["code"] == code_, (body, r)
            assert set(r) == {"message", "code", "details"}, r
        code, r = send(c, "POST", "/api/memes/tech/trim/plan", {"id": "nope"})
        assert code == 422 and r["code"] == "unknown_id", r
        code, r = send(c, "POST", "/api/memes/nobody/trim/plan")
        assert code == 404 and r["code"] == "unknown_channel", r
    assert files(root) == before


def test_vision_unavailable_the_plan_says_why_and_the_confirm_refuses():
    root = world()
    c = client(root)
    with Seams(available=False) as s:
        code, p = send(c, "POST", "/api/memes/reel/cutout/plan")
        assert code == 200 and p["available"] is False, p
        assert "macOS Vision" in p["available_reason"] and "linux" in p["available_reason"], p
        assert p["ok"] is False and p["confirm"] is None, p
        assert p["why"].startswith("Вырезка на этой машине недоступна: вырезка мемов"), p
        assert [m["id"] for m in p["made"]] == ["old-cut", "refused-cut"], p   # what it would
    # a token from a moment the machine could cut; Vision gone by the confirm
    with Seams():
        _, p = send(c, "POST", "/api/memes/reel/cutout/plan")
    with Seams(available=False) as s:
        before = files(root)
        code, r = send(c, "POST", "/api/memes/reel/cutout", {"confirm": p["confirm"]})
        assert code == 409 and r["code"] == "cutout_unavailable", r
        assert "macOS Vision" in r["message"] and r["message"].endswith("Задача не запущена."), r
        assert s.calls == [] and files(root) == before


def test_the_trim_plan_has_trim_left_and_under():
    root = trim_world()
    c = client(root)
    before = files(root)
    code, p = send(c, "POST", "/api/memes/tech/trim/plan")
    assert code == 200 and p["action"] == "meme_trim" and p["kind"] == "trim_blank", p
    assert [r["id"] for r in p["trim"]] == ["tall"], p
    t = p["trim"][0]
    assert t["size"] == [600, 800] and t["trimmed_size"] == [600, 600], t
    assert t["crop"] == [200, 0] and t["stretch"] == 1.8 and t["ceiling"] == 2.25, t
    assert t["recut"] is False and t["phrase"].startswith("top 200 white rows"), t
    # CF-0762: the Russian phrase beside the English one - what the screen shows
    assert t["phrase_ru"].startswith(desk().SIDE_RU["top"] + " 200 ") and \
        "white" not in t["phrase_ru"], t
    assert [r["id"] for r in p["under"]] == ["small"], p
    assert [r["id"] for r in p["left"]] == ["band-gif"] and "GIF" in p["left"][0]["reason"], p
    assert p["changed"] == [] and p["embed"] is True and p["ok"] is True and p["confirm"], p
    assert any("признаки для поиска похожих мемов" in n for n in p["notes"]), p["notes"]
    assert any("папке оригиналов банка" in n for n in p["notes"]), p["notes"]
    assert any("сильнее допустимого (допустимо до " in n for n in p["notes"]), p["notes"]
    assert any("small" in n and "решает пользователь" in n for n in p["notes"]), p["notes"]
    code, p = send(c, "POST", "/api/memes/tech/trim/plan", {"id": "small"})
    assert code == 200 and p["params"] == {"id": "small"} and p["trim"] == [], p
    assert p["ok"] is False and p["confirm"] is None and p["why"].startswith("Резать нечего"), p
    assert files(root) == before
    no_abs(root, p)


# --------------------------------------------------------------------- the confirm
def test_the_confirm_starts_the_job_in_the_launcher_child_once():
    root = world()
    c = client(root)
    with Seams(launcher=started(root)) as s:
        _, p = send(c, "POST", "/api/memes/reel/cutout/plan", {"ids": ["old-cut"]})
        code, r = send(c, "POST", "/api/memes/reel/cutout", {"confirm": p["confirm"]})
        assert code == 200, r
        assert r == {"action": "meme_cutout", "channel": "reel", "kind": "cutout",
                     "bank": "memes", "job_id": "20261015T120000Z-cutout-abc123",
                     "log": "shared/inserts/memes/_desk/jobs/20261015T120000Z-cutout-abc123.log",
                     "poll_s": meme_jobs.POLL_S,
                     "status_url": "/api/memes/reel/jobs/20261015T120000Z-cutout-abc123"}, r
        (cmd, cwd, env), = s.calls
        assert cmd[0] == sys.executable and cmd[1] == "-c" and cwd == str(root), cmd
        assert cmd[3:] == [str(desk().__file__), "cutout", json.dumps({"ids": ["old-cut"]}),
                           "reel", str(root / "shared" / "inserts"), str(root)], cmd
        # CC-0158: the desk's JOB_ARGV is the factory's test seam - the center leaves it be
        assert "JOB_ARGV" not in cmd[2], cmd[2]
        assert 'by="user", via="center"' in cmd[2] and "start_job" in cmd[2], cmd[2]
        assert "commit=True" in cmd[2], cmd[2]
        assert env["MEME_DESK_JOBS_DIR"] == str(SLOT), env.get("MEME_DESK_JOBS_DIR")
        # single use
        code, r = send(c, "POST", "/api/memes/reel/cutout", {"confirm": p["confirm"]})
        assert code == 409 and r["code"] == "confirm_unknown", r
        assert len(s.calls) == 1
    root = trim_world()
    c = client(root)
    with Seams(launcher=started(root, "memes-tech", "trim_blank",
                                "20261015T120000Z-trim_blank-abc123")) as s:
        _, p = send(c, "POST", "/api/memes/tech/trim/plan")
        code, r = send(c, "POST", "/api/memes/tech/trim", {"confirm": p["confirm"]})
        assert code == 200 and r["kind"] == "trim_blank" and r["bank"] == "memes-tech", r
        (cmd, _cwd, _env), = s.calls
        assert cmd[4:7] == ["trim_blank", "{}", "tech"], cmd


def test_tokens_expired_of_another_channel_and_a_changed_index():
    root = trim_world()
    c = client(root)
    with Seams(launcher=started(root)) as s:
        _, p = send(c, "POST", "/api/memes/reel/cutout/plan")
        real = batches._clock
        batches._clock = lambda: real() + batches.CONFIRM_TTL + 1
        try:
            code, r = send(c, "POST", "/api/memes/reel/cutout", {"confirm": p["confirm"]})
        finally:
            batches._clock = real
        assert code == 409 and r["code"] == "confirm_expired", r
        _, p = send(c, "POST", "/api/memes/tech/trim/plan")
        code, r = send(c, "POST", "/api/memes/reel/trim", {"confirm": p["confirm"]})
        assert code == 409 and r["code"] == "confirm_mismatch", r
        _, p = send(c, "POST", "/api/memes/tech/trim/plan")       # a trim token for a cutout
        code, r = send(c, "POST", "/api/memes/tech/cutout", {"confirm": p["confirm"]})
        assert code == 409 and r["code"].startswith("confirm_"), r
        _, p = send(c, "POST", "/api/memes/reel/cutout/plan")
        idx = root / "shared" / "inserts" / "memes" / "index.json"
        idx.write_text(idx.read_text() + "\n")
        before = files(root)
        code, r = send(c, "POST", "/api/memes/reel/cutout", {"confirm": p["confirm"]})
        assert code == 409 and r["code"] == "check_changed", r
        assert "задача не запущена" in r["message"], r
        assert files(root) == before and s.calls == []


def test_the_factorys_refusals_of_a_start_are_its_words():
    root = world()
    c = client(root)

    def refused(code, text, job_id=None):
        return lambda cmd, cwd, env: (0, json.dumps({"ok": False, "code": code, "text": text,
                                                     "en": f"en {code}", "job_id": job_id}), "")
    busy = ("уже идёт задача 20261015T110000Z-trim_blank-ffffff (trim_blank, банк memes-tech) "
            "- одна на машину, отмены нет; дождитесь её конца")
    seen = {}
    for launcher, status, code_, msg in (
            (refused("job_running", busy, "20261015T110000Z-trim_blank-ffffff"), 409,
             "job_running", busy),
            (refused("spawn_failed", "задача не стартовала (boom)"), 500, "spawn_failed",
             "задача не стартовала (boom)"),
            (lambda cmd, cwd, env: (1, "", f"Traceback\n  File {root}/x.py\nOSError: x"), 500,
             "launch_failed", meme_jobs.LAUNCH_FAILED),
            (lambda cmd, cwd, env: (0, "not json\n", ""), 500, "launch_failed",
             meme_jobs.LAUNCH_FAILED)):
        with Seams(launcher=launcher):
            _, p = send(c, "POST", "/api/memes/reel/cutout/plan")
            code, r = send(c, "POST", "/api/memes/reel/cutout", {"confirm": p["confirm"]})
        assert code == status and r["code"] == code_ and r["message"] == msg, r
        no_abs(root, r)
        seen[code_] = r
    assert "running job: 20261015T110000Z-trim_blank-ffffff" in seen["job_running"]["details"]


STAND_IN_DESK = r"""
import json
class MemeDeskError(Exception):
    pass
def start_job(kind, params, **kw):
    return {"job_id": "stand-in", "kind": kind, "params": params, "kw": kw}
"""


def test_the_launcher_asks_the_desk_to_commit_every_kind_with_its_channel():
    """CC-0160: the launcher's own script, run against a stand-in desk
    module (no real job): every kind the center starts goes to start_job
    with `commit=True` and `channel=<cid>`, `by`/`via` the center's (CF-0847:
    the job's commit is the desk's)."""
    import subprocess                                   # noqa: PLC0415
    TMP.mkdir(parents=True, exist_ok=True)
    fake = TMP / "stand_in_meme_desk.py"
    fake.write_text(STAND_IN_DESK)
    kinds = sorted({spec["kind"] for spec in meme_jobs.SPECS.values()})
    assert kinds, meme_jobs.SPECS
    for kind in kinds:
        r = subprocess.run([sys.executable, "-c", meme_jobs._LAUNCHER, str(fake), kind,
                            json.dumps({"x": 1}), "tech", str(TMP / "lib"), str(TMP)],
                           capture_output=True, text=True, timeout=60, check=True)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        assert out["ok"] and out["kind"] == kind and out["params"] == {"x": 1}, out
        assert out["kw"] == {"channel": "tech", "by": "user", "via": "center",
                             "root": str(TMP / "lib"), "repo": str(TMP), "commit": True}, out


def test_the_real_launcher_child_says_the_factorys_refusal():
    """The real child (`child.run`) running start_job with what the factory
    refuses before anything starts: nothing is written, no process left."""
    root = world()
    before = files(root)
    for kind, params, code_ in (("nope", {}, "bad_kind"), ("trim_blank", {"zzz": 1}, "bad_params"),
                                ("trim_blank", {"id": "no-such"}, "unknown_id")):
        try:
            meme_jobs.start(root, "reel", kind, params)
        except batches.BatchFault as e:
            assert e.code == code_ and e.status == 422, (kind, e.code, e.message)
            assert e.message and not e.message.startswith("MemeDeskError"), e.message
        else:
            raise AssertionError(f"{kind} {params} started")
    assert files(root) == before
    assert not SLOT.exists() or not (SLOT / "active.json").exists()


# --------------------------------------------------------------------- the guard
def test_a_job_on_the_bank_refuses_the_centers_writes_there():
    root = world()
    c = client(root)
    with Seams(launcher=started(root)) as s:
        _, apply_plan = send(c, "POST", "/api/memes/reel/apply/plan")
        assert apply_plan["confirm"] and apply_plan["job"] is None, apply_plan
        job_id, fd = plant(root, kind="trim_blank", held=True,
                           progress={"step": "trim", "i": 2, "of": 7, "text": "old-one"})
        try:
            before = files(root)
            _, desk_ = get(c, "/api/memes/reel")
            assert desk_["job"]["job_id"] == job_id and desk_["job"]["kind_word"] == \
                "срез пустых полей", desk_["job"]
            code, r = send(c, "PUT", "/api/memes/reel/marks",
                           {"decisions": {}, "base": desk_["fingerprint"]})
            assert code == 409 and r["code"] == "job_active" and job_id in r["message"], r
            assert "отметки не сохранены" in r["message"], r
            code, r = send(c, "POST", "/api/memes/reel/apply", {"confirm": apply_plan["confirm"]})
            assert code == 409 and r["code"] == "job_active", r
            code, p = send(c, "POST", "/api/memes/reel/apply/plan")
            assert code == 200 and p["ok"] is False and p["confirm"] is None, p
            assert p["job"]["job_id"] == job_id and job_id in p["why"], p
            code, r = send(c, "POST", "/api/memes/reel/candidates/accept",
                           {"confirm": "x", "answer": "да"})
            assert code == 409 and r["code"] == "job_active", r
            for kind in ("cutout", "trim"):
                code, p = send(c, "POST", f"/api/memes/reel/{kind}/plan")
                assert code == 200 and p["ok"] is False and p["confirm"] is None, p
                assert p["job"]["job_id"] == job_id and "не запустить" in p["why"], p
                assert p["why"].startswith("Над банком мемов канала Reel идёт задача "), p
                code, r = send(c, "POST", f"/api/memes/reel/{kind}", {"confirm": "x"})
                assert code == 409 and r["code"] == "job_active", r
            assert files(root) == before and s.calls == []
            # another bank is free
            code, r = send(c, "PUT", "/api/memes/tech/marks", {"decisions": {}, "base": None})
            assert code == 200, r
            code, jobs = get(c, "/api/memes/reel/jobs")
            assert code == 200 and jobs["running"]["job_id"] == job_id, jobs
            assert jobs["poll_s"] == meme_jobs.POLL_S and jobs["bank"] == "memes", jobs
        finally:
            os.close(fd)
        # the job's process gone: the token kept by the refusal works now
        code, r = send(c, "POST", "/api/memes/reel/apply", {"confirm": apply_plan["confirm"]})
        assert code == 200, r


# --------------------------------------------------------------------- the polling
def test_job_status_states_poll_hint_and_routes():
    root = world()
    c = client(root)
    run_id, fd = plant(root, held=True, stamp="20261015T120400Z",
                       progress={"step": "cutout", "i": 1, "of": 2, "text": "old-cut"})
    done_id, _ = plant(root, state="done", stamp="20261015T120300Z", result={
        "bank": "memes", "dry_run": False, "written": True, "unchanged": [], "missing": [],
        "outside_bank": [],
        "made": [{"id": "old-cut", "file": "old-cut.cutout.png", "bbox_px": [0, 0, 40, 30],
                  "coverage": 0.4}],
        "refused": [{"id": "refused-cut", "reason": "две фигуры"}]})
    failed_id, _ = plant(root, kind="trim_blank", state="failed", stamp="20261015T120200Z",
                         error={"code": "job_crashed", "text": "задача упала: RuntimeError: x",
                                "en": "the job crashed", "log_tail": f"File {root}/a.py"})
    gone_id, _ = plant(root, stamp="20261015T120100Z")              # running, lock free
    try:
        code, r = get(c, f"/api/memes/reel/jobs/{run_id}")
        assert code == 200 and r["state"] == "running" and r["alive"] is True, r
        assert r["done"] is False and r["poll_s"] == meme_jobs.POLL_S, r
        assert r["state_word"] == "идёт" and r["kind_word"] == "вырезка", r
        assert r["progress"] == {"step": "cutout", "i": 1, "of": 2, "text": "old-cut"}, r
        assert r["log"] == f"shared/inserts/memes/_desk/jobs/{run_id}.log", r
        code, r = get(c, f"/api/memes/reel/jobs/{done_id}")
        assert code == 200 and r["state"] == "done" and r["poll_s"] is None, r
        made, = r["result"]["made"]
        assert made["urls"]["cut"] == "/api/memes/reel/old-cut/media?kind=cut", made
        assert r["result"]["refused"][0]["urls"]["cut"] is None, r
        code, r = get(c, f"/api/memes/reel/jobs/{failed_id}")
        assert r["state"] == "failed" and r["error"]["code"] == "job_crashed", r
        assert r["error"]["text"].startswith("задача упала") and r["state_word"] == "не удалась"
        assert r["error"]["log_tail"] == "File a.py", r
        code, r = get(c, f"/api/memes/reel/jobs/{gone_id}")
        assert r["state"] == "interrupted" and r["error"]["code"] == "job_interrupted", r
        assert r["state_word"] == "оборвалась" and r["poll_s"] is None, r
        assert "meme_desk.py" in r["error"]["log_tail"], r
        no_abs(root, r)
        code, jobs = get(c, "/api/memes/reel/jobs")
        assert [j["job_id"] for j in jobs["jobs"]] == [run_id, done_id, failed_id, gone_id]
        assert jobs["running"]["job_id"] == run_id, jobs
        no_abs(root, jobs)
        code, jobs = get(c, "/api/memes/reel/jobs", limit=2)
        assert [j["job_id"] for j in jobs["jobs"]] == [run_id, done_id], jobs
        code, r = get(c, "/api/memes/reel/jobs", limit=0)
        assert code == 422 and r["code"] == "bad_limit", r
        code, jobs = get(c, "/api/memes/tech/jobs")
        assert code == 200 and jobs == {"channel": "tech", "bank": "memes-tech", "running": None,
                                        "jobs": [], "poll_s": None}, jobs
        for bad in ("20261015T120400Z-cutout-000000", "nope"):
            code, r = get(c, f"/api/memes/reel/jobs/{bad}")
            assert code == 404 and r["code"] == "unknown_job", r
        code, r = get(c, f"/api/memes/tech/jobs/{run_id}")            # of another bank
        assert code == 404 and r["code"] == "unknown_job", r
    finally:
        os.close(fd)
    code, r = get(c, f"/api/memes/reel/jobs/{run_id}")
    assert r["state"] == "interrupted", r


# ------------------------------------------------------------ CC-0161: the job's commit
SHA = "0123456789abcdef0123456789abcdef01234567"


def test_the_jobs_commit_passes_through_every_shape():
    """CF-0847: `commit_on_done` and `commit` of the desk's job_status /
    list_jobs reach the center as they are - committed, nothing (with and
    without detail), refused, null, and an older desk without either field."""
    root = world()
    c = client(root)
    shapes = {
        "c00001": (True, {"status": "committed", "sha": SHA,
                      "committed": ["shared/inserts/memes/old-cut.cutout.png",
                                    "shared/inserts/memes/index.json"]}),
        "c00002": (True, {"status": "nothing"}),
        "c00003": (True, {"status": "nothing", "detail": "not a git work tree or the bank is "
                                                     "outside it"}),
        "c00004": (True, {"status": "refused", "detail": "fatal: index.lock exists | touched: "
                                                     "shared/inserts/memes/index.json"}),
        "c00005": (False, None),
        "c00006": (True, None),                                       # on, the job failed
    }
    ids = {}
    for i, (tail, (on, commit)) in enumerate(shapes.items()):
        ids[tail], _ = plant(root, state="done" if tail != "c00006" else "failed",
                             stamp=f"20261015T12{i:02d}00Z", tail=tail, result={},
                             commit_on_done=on, commit=commit)
    def full(commit):        # the model's fields the desk left out are null in the answer
        return None if commit is None else {"sha": None, "committed": None, "detail": None,
                                            **commit}
    for tail, (on, commit) in shapes.items():
        code, r = get(c, f"/api/memes/reel/jobs/{ids[tail]}")
        assert code == 200 and r["commit_on_done"] is on, (tail, r)
        assert r["commit"] == full(commit), (tail, r)
        no_abs(root, r)
    code, jobs = get(c, "/api/memes/reel/jobs")
    got = {j["job_id"]: (j["commit_on_done"], j["commit"]) for j in jobs["jobs"]}
    assert got == {ids[t]: (on, full(cm)) for t, (on, cm) in shapes.items()}, got
    # the refused detail stays git's word with the paths cut
    code, r = get(c, f"/api/memes/reel/jobs/{ids['c00004']}")
    assert r["commit"]["detail"].endswith("touched: shared/inserts/memes/index.json"), r
    # an older desk: neither field - both null, the answer validates
    d = desk()
    saved = (d.job_status, d.list_jobs)
    old = {"job_id": ids["c00001"], "kind": "cutout", "bank": "memes", "state": "done",
           "done": True, "alive": False, "result": {}}
    d.job_status = lambda job_id, **kw: dict(old)
    d.list_jobs = lambda **kw: [dict(old)]
    try:
        code, r = get(c, f"/api/memes/reel/jobs/{ids['c00001']}")
        assert code == 200 and r["commit_on_done"] is None and r["commit"] is None, r
        code, jobs = get(c, "/api/memes/reel/jobs")
        j, = jobs["jobs"]
        assert code == 200 and j["commit_on_done"] is None and j["commit"] is None, jobs
    finally:
        d.job_status, d.list_jobs = saved
    # the model refuses a status the desk does not have
    from api.app import MemeJobCommit
    from pydantic import ValidationError
    try:
        MemeJobCommit(status="pushed")
    except ValidationError:
        pass
    else:
        raise AssertionError("status pushed validated")


# --------------------------------------------------------------------- the contract
def test_the_contract_carries_the_job_routes_and_codes():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    paths = {p: set(v) for p, v in spec["paths"].items() if p in ROUTES}
    assert paths == ROUTES, paths
    for p, m, model in (("/api/memes/{channel}/cutout/plan", "post", "MemeCutoutPlan"),
                        ("/api/memes/{channel}/cutout", "post", "MemeJobStarted"),
                        ("/api/memes/{channel}/trim/plan", "post", "MemeTrimPlan"),
                        ("/api/memes/{channel}/trim", "post", "MemeJobStarted"),
                        ("/api/memes/{channel}/jobs", "get", "MemeJobs"),
                        ("/api/memes/{channel}/jobs/{job_id}", "get", "MemeJob")):
        op = spec["paths"][p][m]["responses"]
        assert op["200"]["content"]["application/json"]["schema"]["$ref"].endswith(model), p
        assert "/MemesProblem" in json.dumps(op["409"]), (p, op["409"])
        if m == "post":
            assert "/WritesProblem" in json.dumps(op["409"]), (p, op["409"])
    codes = set(spec["components"]["schemas"]["MemesProblem"]["properties"]["code"]["enum"])
    assert {"job_active", "launch_failed", "cutout_unavailable", "not_cutout", "bad_kind",
            "bad_params", "job_running", "spawn_failed", "unknown_job", "bad_limit"} <= codes
    assert set(meme_jobs.ACTIONS) <= set(batches._ACTIONS)
    assert set(meme_jobs.SPECS) == set(meme_jobs.ACTIONS)
    assert set(memes.JOB_KIND_WORDS) == set(desk().JOB_KINDS)
    job = spec["components"]["schemas"]["MemeJob"]["properties"]
    assert {"commit_on_done", "commit"} <= set(job), sorted(job)
    commit = spec["components"]["schemas"]["MemeJobCommit"]["properties"]
    assert set(commit["status"]["enum"]) == {"committed", "nothing", "refused"}, commit
    assert {"sha", "committed", "detail"} <= set(commit), commit
    assert set(desk().COMMIT_STATES) == set(commit["status"]["enum"])


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
