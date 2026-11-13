#!/usr/bin/env python3
"""CC-0054 (CF-0657): every check line the API gives (`CheckLine`) carries the
factory's reason code and Russian line.

In-process (starlette's TestClient) against the stand-in factory of
tests/test_cc_api_channels.py - a temp git repository with `reel` and `demo`;
the live checkout's channels and git are never read or written, the factory's
*code* (inserts/validate_inserts.py `channel_config_findings`,
`check_findings`, CHECK_REASONS_RU) is this checkout's, as in production.

What is pinned, place by place:

* `factory.config_errors` is `channel_config_findings` then the run plan's
  lines under RUN_PLAN_CHECK - {check, code, text, text_ru}, `text` the same
  English line as `channel_config_errors` / `run_plan_errors`;
* a channel's detail, `/check`, a PUT refused `invalid`, a revert refused
  `invalid`: each row {text, field, code, text_ru}, `field` still from `text`;
  the example of the task, `video_editor_invalid` with the field and value;
* the position's check is the factory's (CC-0056, CF-0672 -
  `new_channel.stance_findings` / `stance_text_findings`): `stance_invalid`,
  a file or text that is not JSON `stance_unreadable` with the factory's line
  `stance.json: does not parse: <error>`;
* a new channel (CC-0008): an input's line is the factory's own Russian
  (`text_ru` = `text`, no code); every other line is `new_channel.check()`'s
  findings as they are (the rendered config's, the template's own two -
  `template_has_pipeline`, `template_stance_path` - and the position's); the
  API's own guard of the position's path speaks under `template_stance_path`;
* the walk: every path that makes CheckLine rows, in a temp tree - no row
  with a null `code`/`text_ru` but a new channel's input lines;
* the contract: CheckLine requires `code` and `text_ru` (nullable), 0.16.0 -
  CC-0056 changed no schema.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from api import channels as ch                       # noqa: E402
from api import factory                               # noqa: E402
from test_cc_api_channels import (                    # noqa: E402
    H, client, edit_text, factory_tree, git, head, reel_config)

KEYS = ["code", "field", "text", "text_ru"]
EXAMPLE = ("Настройки монтажёра, поле video_editor.max_attempts_per_video (сейчас 0): "
           "значение не подходит монтажёру - с ним он не соберёт ролик.")


def _bad_attempts():
    bad = reel_config()
    bad["video_editor"]["max_attempts_per_video"] = 0
    return bad


def _bad_plan():
    bad = reel_config()
    bad["run_plan"]["stages"][0]["steps"][0]["argv"] = ["python3", "{root}/scripts/nope.py"]
    return bad


def test_config_errors_are_the_factory_s_findings():
    root = factory_tree()
    vi = factory.validate_inserts()
    path = root / "channels" / "reel.json"
    for cfg in (_bad_attempts(), _bad_plan()):
        got = factory.config_errors(root, "reel", cfg)
        assert got and all(set(f) == {"check", "code", "text", "text_ru"} for f in got), got
        assert [f["text"] for f in got] == (vi.channel_config_errors(cfg, path)
                                            + factory.run_plan_errors(root, "reel", cfg))
        assert all(f["code"] and f["text_ru"] for f in got), got
    ve = factory.config_errors(root, "reel", _bad_attempts())[0]
    assert ve["code"] == "video_editor_invalid" and ve["text_ru"] == EXAMPLE, ve
    rp = factory.config_errors(root, "reel", _bad_plan())
    assert [f["check"] for f in rp] == [vi.RUN_PLAN_CHECK] and rp[0]["code"] == "run_plan_invalid"
    assert rp[0]["text_ru"].startswith("План запуска"), rp
    # a channel with a pipeline and no plan: the reader's own refusal, the same row
    nop = reel_config()
    del nop["run_plan"]
    f = factory.config_errors(root, "reel", nop)
    assert [x["code"] for x in f] == ["run_plan_invalid"] and "run_plan" in f[0]["text_ru"], f
    assert factory.config_errors(root, "reel", reel_config()) == []
    assert vi.RUN_PLAN_CHECK in {r["check"] for r in factory.config_checks()}


def test_detail_and_check_rows_carry_code_and_russian():
    root = factory_tree()
    c = client(root)
    v = c.post("/api/channels/reel/check", headers=H, json={"config": _bad_attempts()}).json()
    row = v["errors"][0]
    assert sorted(row) == KEYS and row["field"] == "video_editor.max_attempts_per_video", v
    assert row["code"] == "video_editor_invalid" and row["text_ru"] == EXAMPLE, row
    assert "must be an integer" in row["text"], row          # the English line, as before
    v = c.post("/api/channels/reel/check", headers=H, json={"config": _bad_plan()}).json()
    assert [(r["field"], r["code"]) for r in v["errors"]] == [("run_plan", "run_plan_invalid")], v
    # the position's check is the factory's (CF-0672): stance_invalid
    v = c.post("/api/channels/reel/check", headers=H,
               json={"stance": {"channel_id": "other", "position": {}}}).json()
    st = [r for r in v["errors"] if r["field"] == "stance.channel_id"]
    assert st and st[0]["code"] == "stance_invalid", v
    assert st[0]["text_ru"].startswith("Позиция канала") and "'other'" in st[0]["text_ru"], st
    assert st[0]["text"].startswith("stance.json.channel_id: must be 'reel'"), st
    assert sorted(st[0]) == KEYS
    # the detail says the same rows of what is on disk now
    cfg = (root / "channels" / "reel.json").read_text()
    (root / "channels" / "reel.json").write_text(
        edit_text(cfg, '"max_attempts_per_video": 3', '"max_attempts_per_video": 0'))
    d = c.get("/api/channels/reel").json()
    assert [(r["code"], r["text_ru"]) for r in d["errors"]] == [("video_editor_invalid",
                                                                  EXAMPLE)], d["errors"]


def test_a_refused_save_and_revert_carry_code_and_russian():
    root = factory_tree()
    c = client(root)
    d = c.get("/api/channels/reel").json()
    start = head(root)
    r = c.put("/api/channels/reel", headers=H, json={"base": d["revision"], "config_text": edit_text(
        d["config_text"], '"max_attempts_per_video": 3', '"max_attempts_per_video": 0')})
    assert r.status_code == 422 and r.json()["code"] == "invalid", r.text
    b = r.json()
    assert [(e["code"], e["text_ru"]) for e in b["errors"]] == [("video_editor_invalid", EXAMPLE)]
    assert b["details"] == [e["text"] for e in b["errors"]], b      # «подробнее»: English, strings
    assert head(root) == start
    # a revert that would bring back a broken value is refused with the same rows
    cfg = (root / "channels" / "reel.json").read_text()
    (root / "channels" / "reel.json").write_text(
        edit_text(cfg, '"max_attempts_per_video": 3', '"max_attempts_per_video": 0'))
    git(root, "commit", "-q", "-am", "by hand, broken")
    d = c.get("/api/channels/reel").json()
    fix = c.put("/api/channels/reel", headers=H, json={"base": d["revision"], "config_text":
                edit_text(d["config_text"], '"max_attempts_per_video": 0',
                          '"max_attempts_per_video": 2')})
    assert fix.status_code == 200, fix.text
    r = c.post(f"/api/channels/reel/history/{fix.json()['commit']}/revert", headers=H)
    assert r.status_code == 422 and r.json()["code"] == "invalid", r.text
    assert [e["code"] for e in r.json()["errors"]] == ["video_editor_invalid"], r.text
    assert r.json()["errors"][0]["text_ru"] == EXAMPLE


def test_a_new_channel_s_rows_carry_code_and_russian():
    root = factory_tree()
    c = client(root)
    r = c.post("/api/channels", headers=H, json={"channel_id": "old-reel",
                                                 "display_name": "Demo", "dry_run": True})
    rows = r.json()["errors"]
    assert rows and all(sorted(e) == KEYS for e in rows), rows
    assert all(e["code"] is None and e["text_ru"] == e["text"] for e in rows), rows
    # the position the wizard sends, of another channel: the factory's check
    r = c.post("/api/channels", headers=H, json={
        "channel_id": "history", "display_name": "ExampleHistory", "dry_run": True,
        "stance_text": json.dumps({"channel_id": "nope", "position": {}})})
    rows = r.json()["errors"]
    assert [(e["field"], e["code"]) for e in rows] == [("stance.channel_id", "stance_invalid")]
    assert rows[0]["text_ru"].startswith("Позиция канала"), rows
    # ... and text that is not JSON: the factory's line, stance_unreadable
    r = c.post("/api/channels", headers=H, json={
        "channel_id": "history", "display_name": "ExampleHistory", "dry_run": True,
        "stance_text": "{not json"})
    rows = r.json()["errors"]
    assert [(e["field"], e["code"]) for e in rows] == [("stance", "stance_unreadable")], rows
    assert rows[0]["text"].startswith("stance.json: does not parse: "), rows
    assert rows[0]["text_ru"].startswith("Позиция канала"), rows
    # a config line of the rendered template: the factory's code and Russian
    nc = factory.new_channel()
    real = nc.render

    def broken(values, created=None):
        out = real(values, created)
        rel = nc.FILES[0][1].format(id=values["channel_id"])
        cfg = json.loads(out[rel])
        cfg["theme"] = "red"
        out[rel] = json.dumps(cfg).encode("utf-8")
        return out
    nc.render = broken
    try:
        r = c.post("/api/channels", headers=H, json={
            "channel_id": "history", "display_name": "ExampleHistory", "dry_run": True})
    finally:
        nc.render = real
    rows = r.json()["errors"]
    assert rows and not r.json()["ok"], r.text
    assert all(e["code"] == "theme_invalid" and e["text_ru"].startswith("Оформление канала")
               for e in rows), rows
    assert all(e["text"].startswith("history.json") for e in rows), rows


class _Rows:
    """Every CheckLine row the walk saw, by where it came from."""
    INPUTS = ("channel_id", "display_name", "language")

    def __init__(self):
        self.seen = []

    def take(self, where, rows, want=None):
        assert rows, f"{where}: no rows"
        for r in rows:
            assert sorted(r) == KEYS, (where, r)
            self.seen.append((where, r))
        if want:
            assert want in {r["code"] for r in rows}, (where, want, rows)
        return rows

    def nulls(self):
        """Rows with a null code or Russian line that are not an input's own."""
        return [(w, r) for w, r in self.seen
                if (r["code"] is None or r["text_ru"] is None)
                and not (r["field"] in self.INPUTS and r["code"] is None
                         and r["text_ru"] == r["text"])]


def _render_with(nc, change):
    real = nc.render

    def patched(values, created=None):
        out = real(values, created)
        rel = nc.FILES[0][1].format(id=values["channel_id"])
        cfg = json.loads(out[rel])
        change(cfg)
        out[rel] = json.dumps(cfg).encode("utf-8")
        return out
    return real, patched


def test_every_check_line_path_has_code_and_russian():
    """CC-0056: each place that makes CheckLine rows, walked in a temp tree -
    no null code/text_ru but a new channel's input lines (the factory's own
    Russian, no check behind them)."""
    root = factory_tree()
    c = client(root)
    seen = _Rows()
    sp = root / "channels" / "reel" / "stance.json"
    good = sp.read_text()

    def commit_by_hand(text, msg):
        sp.write_text(text)
        git(root, "commit", "-q", "-am", msg)

    # /check: the config, the position as an object, as text, not an object
    for body, want in (({"config": _bad_attempts()}, "video_editor_invalid"),
                       ({"config": _bad_plan()}, "run_plan_invalid"),
                       ({"stance": {"channel_id": "x"}}, "stance_invalid"),
                       ({"stance_text": json.dumps({"channel_id": "x"})}, "stance_invalid")):
        r = c.post("/api/channels/reel/check", headers=H, json=body)
        assert r.status_code == 200, r.text
        seen.take(f"check {body}", r.json()["errors"], want)
    # ... a position text that is not a JSON object is refused not_json, with its
    # row (a `stance` that is not an object the app's schema refuses first)
    for body, want in (({"stance_text": "{oops"}, "stance_unreadable"),
                       ({"stance_text": "[1, 2]"}, "stance_invalid")):
        r = c.post("/api/channels/reel/check", headers=H, json=body)
        assert r.status_code == 422 and r.json()["code"] == "not_json", r.text
        rows = seen.take(f"check {body}", r.json()["errors"], want)
        if want == "stance_unreadable":
            assert rows[0]["text"].startswith("stance.json: does not parse: "), rows
    # the detail of what is on disk: a position of another channel, one that does not parse
    commit_by_hand(json.dumps({"channel_id": "x", "position": {}}), "by hand, other id")
    seen.take("detail other id", c.get("/api/channels/reel").json()["errors"], "stance_invalid")
    sp.write_text("{oops")
    rows = seen.take("detail not json", c.get("/api/channels/reel").json()["errors"],
                     "stance_unreadable")
    assert rows[-1]["text"].startswith("stance.json: does not parse: "), rows
    assert rows[-1]["field"] == "stance", rows
    git(root, "checkout", "-q", "--", "channels/reel/stance.json")
    # a PUT refused invalid (the config; the position), refused not_json
    d = c.get("/api/channels/reel").json()
    r = c.put("/api/channels/reel", headers=H, json={"base": d["revision"], "config_text":
              edit_text(d["config_text"], '"max_attempts_per_video": 3',
                        '"max_attempts_per_video": 0')})
    assert r.status_code == 422 and r.json()["code"] == "invalid", r.text
    seen.take("put config", r.json()["errors"], "video_editor_invalid")
    r = c.put("/api/channels/reel", headers=H, json={"base": d["revision"],
              "stance": {"channel_id": "y", "position": {}}})
    assert r.status_code == 422 and r.json()["code"] == "invalid", r.text
    seen.take("put stance", r.json()["errors"], "stance_invalid")
    r = c.put("/api/channels/reel", headers=H, json={"base": d["revision"], "stance_text": "{"})
    assert r.status_code == 422 and r.json()["code"] == "not_json", r.text
    seen.take("put stance not json", r.json()["errors"], "stance_unreadable")
    # a revert refused invalid: undoing the fix of a broken position brings it back
    fix = c.put("/api/channels/reel", headers=H, json={"base": d["revision"],
                "stance_text": good})
    assert fix.status_code == 200, fix.text
    r = c.post(f"/api/channels/reel/history/{fix.json()['commit']}/revert", headers=H)
    assert r.status_code == 422 and r.json()["code"] == "invalid", r.text
    seen.take("revert stance", r.json()["errors"], "stance_invalid")

    # a new channel: inputs (null-coded, their own Russian), the template's lines
    def dry(**body):
        r = c.post("/api/channels", headers=H, json=dict(
            {"channel_id": "history", "display_name": "ExampleHistory", "dry_run": True}, **body))
        assert r.status_code == 200, r.text
        return r.json()["errors"]
    rows = seen.take("new inputs", dry(channel_id="old-reel", display_name="Demo"))
    assert all(r["code"] is None for r in rows), rows
    seen.take("new stance id", dry(stance_text=json.dumps({"channel_id": "z"})), "stance_invalid")
    rows = seen.take("new stance text", dry(stance_text="nope"), "stance_unreadable")
    assert rows[0]["text"].startswith("stance.json: does not parse: "), rows
    nc = factory.new_channel()
    for change, want in ((lambda cfg: cfg.update(theme="red"), "theme_invalid"),
                         (lambda cfg: cfg.pop("status"), "template_has_pipeline"),
                         (lambda cfg: cfg.update(stance="elsewhere.json"),
                          "template_stance_path")):
        real, nc.render = _render_with(nc, change)
        try:
            seen.take(f"new {want}", dry(), want)
            rows = seen.take(f"new {want} + stance", dry(stance_text=good), want)
        finally:
            nc.render = real
        # the API's guard does not say the factory's line twice
        assert sum(r["code"] == "template_stance_path" for r in rows) == (
            want == "template_stance_path"), rows
    # the API's own guard when the factory sees no fault with the path: its code
    real_sp = ch._stance_path
    ch._stance_path = lambda root, cid, cfg: None
    try:
        rows = seen.take("new api guard", dry(stance_text=good), "template_stance_path")
    finally:
        ch._stance_path = real_sp
    assert [r["text_ru"].startswith("Шаблон нового канала") for r in rows] == [True], rows
    # a create refused invalid carries the same rows
    r = c.post("/api/channels", headers=H, json={"channel_id": "history",
               "display_name": "ExampleHistory", "stance_text": "nope"})
    assert r.status_code == 422 and r.json()["code"] == "invalid", r.text
    seen.take("create", r.json()["errors"], "stance_unreadable")

    assert seen.nulls() == [], seen.nulls()
    codes = {r["code"] for _, r in seen.seen}
    assert {"stance_invalid", "stance_unreadable", "template_has_pipeline",
            "template_stance_path"} <= codes, codes


def test_the_contract_requires_code_and_text_ru():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    cl = spec["components"]["schemas"]["CheckLine"]
    assert set(cl["required"]) >= {"text", "field", "code", "text_ru"}, cl
    for k in ("code", "text_ru"):
        assert {"type": "null"} in cl["properties"][k]["anyOf"], cl["properties"][k]
    assert spec["info"]["version"] == "0.79.0"


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
