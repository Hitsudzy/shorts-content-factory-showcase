#!/usr/bin/env python3
"""CF-0562: the orchestrator of 2.2.1 on several channels, some of which have
no pipeline yet.

ExampleTech and ExampleScience existed (YouTube channels, brand) before their
conveyors (2.3.2/2.3.3). Their configs said so in one key, `"status":
"no_pipeline"` (`shared/channel_ids.py`), carried no `run_plan` and no
`publisher`, and `batch_schedule.enabled` was false; CF-0659 (Science) and
CF-0686 (Tech) gave them their pipelines, so the mark lives on for the next
channel and on the stand-in roots below. What is pinned:

* the mark: a stub is recognised and named («конвейера нет - батча не
  будет»); a half-stub (run_plan or publisher left in, still in the schedule,
  an unknown status) is an error, never a quiet pass;
* the plan (`batch_schedule.plan`) on a stand-in root of three channels - one
  with a pipeline, two stubs: the day goes to the one, each stub is listed with
  its line, nothing fails; with two pipelines and a stub the day goes to the
  channel with the earliest empty slot, and on a tie to the first by name, and
  the plan says which rule decided;
* the tick and the console's button refuse a stub with the line; the settings
  writer refuses to switch a stub into the schedule;
* `run_executor.py run <stub>` and `run_plan.py show <stub>` refuse with
  «у канала нет run_plan»;
* the Studio read's `due` skips a stub with the line, the API switch shows
  it and will not turn on for it (agents/analyst, agents/publisher);
* the factory's state (`shared/factory_state.py`, once the console's data)
  gives the stub its line, no sections, and does not fail;
* the real `channels/`: no stub left (a later one is a valid stub named by its
  brand), the three channels have a pipeline, `run_plan.load` of it is the
  config's block unchanged (the dry run is the same as before CF-0562).

Every root is a synthetic tree under a temp dir; no batch runs, no executor
starts (the tick is a dry run), nothing leaves the machine.
"""
import contextlib
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "shared"))

import batch_schedule as bs         # noqa: E402
import channel_ids                  # noqa: E402
import factory_state as collect    # noqa: E402
import run_executor                 # noqa: E402
import run_plan                     # noqa: E402

from _channels import pipeline_configs, stand_in_theme, stub_configs   # noqa: E402
from _tmproot import tmp_root       # noqa: E402

TMP = tmp_root("channels-without-pipeline-test-")
A, B = "alpha", "beta"
S1, S2 = "gamma", "delta"
SLOT = {"time": "01:00", "tz": "Europe/Moscow", "per_day": 1, "lead_hours": 2}
IN_WINDOW = "2026-10-07T23:30:00Z"          # 08.10 02:30 МСК - inside the default 02:00-05:00
LINE = channel_ids.NO_PIPELINE_LINE
_n = [0]


def _w(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


def _stub(ch, **extra):
    doc = {"channel_id": ch, "display_name": ch.title(), "status": "no_pipeline",
           "status_note": "test stand-in; its conveyor is milestone 9.9.9",
           "batch_schedule": {"enabled": False}, "theme": stand_in_theme()}
    doc.update(extra)
    return doc


def _root(pipes=(A,), stubs=(S1, S2)):
    _n[0] += 1
    r = TMP / f"r{_n[0]}"
    r.mkdir(parents=True)
    for ch in pipes:
        _w(r / "channels" / f"{ch}.json",
           {"channel_id": ch, "publisher": {"slot": SLOT}, "run_plan": {"stages": []}})
    for ch in stubs:
        _w(r / "channels" / f"{ch}.json", _stub(ch))
    return r


def _taken(root, ch, days):
    p = root / "publish" / "uploads.json"
    rows = json.loads(p.read_text())["uploads"] if p.is_file() else []
    for d in days:
        slug = f"{ch}-{d}"
        rows.append({"channel": ch, "entry_id": f"{ch}/2026-10-01T0000Z/{slug}", "slug": slug,
                     "video_id": "V" * 11, "source": "studio",
                     "recorded_at": "2026-10-02T00:00:00Z",
                     "publish_at": f"{d}T01:00:00+03:00", "publish_tz": "Europe/Moscow",
                     "publish_day": d})
    _w(p, {"uploads": rows})


def _aux(r):
    return {"needs_you_dir": r / "no-needs-you", "env_file": r / "no.env",
            "environ": {"PUBLISHER_TOKEN_FILE": str(r / "no" / "t.json"),
                        "PUBLISHER_CLIENT_SECRET_FILE": str(r / "no" / "c.json"),
                        "BATCH_SCHEDULE_STATE_DIR": str(r / "schedule")}}


def _raises(fn, *a, match=""):
    try:
        fn(*a)
    except Exception as e:                                      # noqa: BLE001
        assert match in str(e), (match, str(e))
        return str(e)
    raise AssertionError(f"{fn.__name__}{a} did not raise")


# ------------------------------------------------------------------ the mark
def test_a_stub_is_named_and_a_channel_without_status_is_a_pipeline():
    assert channel_ids.no_pipeline_reason({"channel_id": A, "run_plan": {}}, A) is None
    got = channel_ids.no_pipeline_reason(_stub(S1), S1)
    assert got == f"{LINE} (конвейер - веха 9.9.9)", got


def test_a_half_stub_is_an_error_not_a_pass():
    err = channel_ids.ChannelIdError
    for bad, why in ((_stub(S1, run_plan={"stages": []}), "run_plan"),
                     (_stub(S1, publisher={"slot": SLOT}), "publisher"),
                     (_stub(S1, batch_schedule={"enabled": True}), "batch_schedule.enabled"),
                     (dict(_stub(S1), batch_schedule=None), "batch_schedule.enabled"),
                     (dict(_stub(S1), status="paused"), "unknown `status`"),
                     (dict(_stub(S1), display_name=""), "display_name")):
        try:
            channel_ids.no_pipeline_reason(bad, S1)
        except err as e:
            assert why in str(e), (why, str(e))
            continue
        raise AssertionError(f"half-stub passed: {why}")


def test_the_root_validator_walks_a_stub_as_a_stub():
    sys.path.insert(0, str(ROOT / "inserts"))
    import validate_inserts as vi
    r = _root(pipes=(), stubs=(S1,))
    _w(r / "channels" / "bad.json", _stub("bad", run_plan={"stages": []}))
    saved = vi.CHANNELS_DIR
    vi.CHANNELS_DIR = r / "channels"
    try:
        errs = vi.validate_vocabulary()
        lines = vi.channel_asset_reminder_lines()
    finally:
        vi.CHANNELS_DIR = saved
    assert [e for e in errs if "bad.json" in e and "run_plan" in e], errs
    assert not [e for e in errs if S1 in e], errs
    assert any(S1 in x and LINE in x for x in lines), lines


# ------------------------------------------------------------------ the plan
def test_one_pipeline_and_two_stubs_the_day_goes_to_the_pipeline():
    r = _root()
    p = bs.plan(r, IN_WINDOW, 3, open_rows=[])
    d = p["days"][0]
    assert d["status"] == "planned" and d["channel"] == A, d
    for s in (S1, S2):
        c = p["channels"][s]
        assert c["plannable"] is False and c["no_pipeline"] is True, c
        assert c["why_not"].startswith(LINE), c
        assert bs.channel_line(s, c) == f"{s}: {c['why_not']}", bs.channel_line(s, c)
    text = "\n".join(bs.plan_lines(p))
    assert f"{S1}: {LINE}" in text and f"{S2}: {LINE}" in text, text
    assert all(x["channel"] in (None, A) for x in p["days"]), p["days"]


def test_only_stubs_plan_nothing_and_say_why():
    r = _root(pipes=())
    p = bs.plan(r, IN_WINDOW, 2, open_rows=[])
    assert all(d["status"] == "idle" and d["channel"] is None for d in p["days"]), p["days"]
    assert "некого планировать" in p["days"][0]["why"], p["days"][0]
    assert {c["why_not"].split(" (")[0] for c in p["channels"].values()} == {LINE}


def test_two_pipelines_the_earlier_empty_slot_gets_the_day_and_the_plan_says_so():
    r = _root(pipes=(A, B))
    _taken(r, A, ["2026-10-09", "2026-10-10"])          # A is full until 11.10, B is empty
    p = bs.plan(r, IN_WINDOW, 1, open_rows=[])
    d = p["days"][0]
    assert d["channel"] == B, d
    assert "пусто 09.10 01:00 МСК" in d["why"] and f"раньше, чем у {A}" in d["why"], d["why"]


def test_two_pipelines_on_a_tie_the_first_by_name_and_the_plan_says_so():
    r = _root(pipes=(B, A))
    p = bs.plan(r, IN_WINDOW, 1, open_rows=[])
    d = p["days"][0]
    assert d["channel"] == A, d
    assert f"в то же время у {B} - день по алфавиту канала" in d["why"], d["why"]
    assert "раньше, чем у" not in d["why"], d["why"]
    again = bs.plan(r, IN_WINDOW, 1, open_rows=[])["days"][0]
    assert (again["channel"], again["why"]) == (d["channel"], d["why"])


# ------------------------------------------------------------------ tick, button, settings
def test_the_tick_never_starts_a_stub():
    r = _root(pipes=())
    env = _aux(r)["environ"]
    bs.set_switch(True, "user", "«включай» (тест)", r, now="2026-10-07T10:00:00Z", environ=env)
    code, line, row = bs.tick(r, IN_WINDOW, dry_run=True, open_rows=[], environ=env)
    assert code == 0 and row is None and line.startswith("TICK no:"), line
    assert not (r / "schedule" / "launches.jsonl").exists()


def test_the_button_refuses_a_stub_with_its_line():
    r = _root()
    chk = bs.launch_check(S1, r, IN_WINDOW, open_rows=[], environ=_aux(r)["environ"])
    assert chk["ok"] is False and chk["why"].startswith("у канала нет run_plan - " + LINE), chk
    ok, line, row = bs.manual_launch(S1, r, IN_WINDOW, confirmed=True, open_rows=[],
                                     environ=_aux(r)["environ"])
    assert ok is False and row is None and LINE in line, (ok, line, row)
    assert not (r / "schedule" / "launches.jsonl").exists()


def test_the_settings_writer_will_not_put_a_stub_into_the_schedule():
    r = _root()
    env = _aux(r)["environ"]
    _raises(bs.set_channel_settings, S1, {"enabled": True}, "user", None, r, None, env,
            match=LINE)
    assert not (r / "schedule" / bs.SETTINGS).exists()
    st = bs.channel_settings(S1, r, env)
    assert st.get("enabled") is False, st
    out = io.StringIO()
    bs.main(["settings", "--root", str(r)], out=out)
    assert f"{S1}: {LINE}" in out.getvalue() and f"{A}: участвует" in out.getvalue(), \
        out.getvalue()


# ------------------------------------------------------------------ executor, run plan
def test_the_executor_and_the_dry_run_refuse_a_stub():
    r = _root()
    for mod, argv in ((run_executor, ["run", S1, "--root", str(r)]),
                      (run_plan, ["show", S1, "--root", str(r)])):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = mod.main(argv)
        assert code == 2, (mod.__name__, code)
        assert "у канала нет run_plan" in err.getvalue() and LINE in err.getvalue(), err.getvalue()
    _raises(run_plan.load, S2, r, match="у канала нет run_plan")


# ------------------------------------------------------------------ analyst, publisher
def test_the_studio_read_and_the_api_switch_name_a_stub():
    sys.path.insert(0, str(ROOT / "agents" / "analyst"))
    sys.path.insert(0, str(ROOT / "agents" / "publisher"))
    import api_switch
    import studio_read
    r = _root()
    out = io.StringIO()
    studio_read.main(["due", "--root", str(r), "--now", IN_WINDOW], out=out)
    for s in (S1, S2):
        assert f"skip {s}: {LINE}" in out.getvalue(), out.getvalue()
    env = {"BATCH_SCHEDULE_STATE_DIR": str(r / "schedule")}
    st = {x["channel"]: x for x in api_switch.status(r, env)}
    assert LINE in st[S1]["line"] and "аудита" not in st[S1]["line"], st[S1]
    assert "аудита" in st[A]["line"], st[A]
    _raises(api_switch.set_switch, S1, True, "user", "тест", r, IN_WINDOW, env, match=LINE)


# ------------------------------------------------------------------ the factory's state
def test_the_factory_state_names_a_stub_and_does_not_fail():
    r = _root()
    d = collect.collect(r, IN_WINDOW, open_rows=[], **_aux(r))
    by = {c["id"]: c for c in d["channels"]}
    assert set(by) == {A, S1, S2}, by.keys()
    for s in (S1, S2):
        assert by[s]["no_pipeline"].startswith(LINE), by[s]
        assert "feed" not in by[s] and "acceptance" not in by[s], by[s]
        assert by[s]["schedule"].get("ok"), by[s]["schedule"]
    assert "feed" in by[A] and by[A]["config_error"] is None, by[A]


# ------------------------------------------------------------------ the real channels/




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
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:400]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
