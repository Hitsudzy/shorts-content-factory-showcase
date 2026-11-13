#!/usr/bin/env python3
"""CC-0008: a new channel from the factory's template (`shared/new_channel.py`,
`shared/channel_template/`).

Every root is a stand-in in a temp dir: a `channels/` with one channel of its
own (with a former id) - the live checkout's channels are never read. The
factory's *code* (the template, the validators) is this checkout's.

What is pinned:

* the template renders a channel laid out as a channel is - the config, the
  position under `channels/<id>/`, the brand folder - with the inputs filled
  in, a display name with quotes still valid JSON;
* the rendered config passes the factory's own check of a channel
  (`validate_inserts.channel_config_errors`) and is a stub: `no_pipeline_reason`
  says «конвейера нет», and it is off the schedule in the schedule's own reader
  (`batch_schedule.window_config` -> enabled False);
* the inputs: the id's form, a taken id, another channel's former id, a
  directory already on disk, a non-channel name under pipeline/, a reserved
  name, the display name of another channel, a bad language - each refused
  with its field, and the config is not checked then;
* `create` writes the files and nothing else; `check` writes nothing;
* there is one template: the API carries none of its own.
"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from _channels import stand_in_theme                  # noqa: E402
from _tmproot import tmp_root                         # noqa: E402

TMP = tmp_root("new-channel-test-")


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


nc = _load("new_channel_under_test", "shared/new_channel.py")
ids = _load("channel_ids_new_channel_test", "shared/channel_ids.py")
bs = _load("batch_schedule_new_channel_test", "shared/batch_schedule.py")

_N = [0]


def tree():
    _N[0] += 1
    root = TMP / f"root-{_N[0]}"
    (root / "channels").mkdir(parents=True)
    cfg = {"channel_id": "reel", "former_channel_ids": ["old-reel"], "display_name": "Reel",
           "theme": stand_in_theme(), "status": "no_pipeline", "status_note": "stub",
           "batch_schedule": {"enabled": False}}
    (root / "channels" / "reel.json").write_text(json.dumps(cfg), encoding="utf-8")
    return root


VALUES = {"channel_id": "example-history", "display_name": 'Example "History"'}


def test_the_template_renders_a_channel_laid_out_as_a_channel_is():
    files = nc.render(VALUES, created="2026-10-10")
    assert sorted(files) == ["channels/example-history.json",
                             "channels/example-history/brand/description.md",
                             "channels/example-history/stance.json"]
    cfg = json.loads(files["channels/example-history.json"])
    assert cfg["channel_id"] == "example-history"
    assert cfg["display_name"] == 'Example "History"'
    assert cfg["language"] == "en"                       # the default
    assert cfg["stance"] == "example-history/stance.json"
    assert "2026-10-10" in cfg["status_note"]
    stance = json.loads(files["channels/example-history/stance.json"])
    assert stance["channel_id"] == "example-history"
    md = files["channels/example-history/brand/description.md"].decode("utf-8")
    assert md.startswith('# Example "History"')
    for data in files.values():
        assert b"{{" not in data, data[:200]


def test_the_new_channel_passes_the_factory_s_check_and_is_off_the_schedule():
    root = tree()
    res = nc.check(root, VALUES, created="2026-10-10")
    assert res["ok"], (res["input_errors"], res["errors"])
    cfg = json.loads(res["files"]["channels/example-history.json"])
    assert ids.no_pipeline_reason(cfg, "example-history").startswith(ids.NO_PIPELINE_LINE)
    assert "run_plan" not in cfg and "publisher" not in cfg
    assert cfg["batch_schedule"]["enabled"] is False
    w = bs.window_config("example-history", root, doc=cfg, overlay={"channels": {}})
    assert w["enabled"] is False
    # the check is the factory's: the same function the vocabulary walk runs
    vi = nc._validate_inserts()
    assert vi.channel_config_errors(cfg, root / "channels" / "example-history.json") == []
    broken = dict(cfg, theme=dict(cfg["theme"], text="#111111"))
    assert vi.channel_config_errors(broken, root / "channels" / "x.json")


def test_every_line_of_the_check_has_the_factory_s_code_and_russian():
    """CF-0672: a broken render - a channel with a pipeline, the position file
    not named, the position of another channel - gives each line as a finding
    with a code and Russian text; `errors` stays the English lines."""
    root = tree()
    assert nc.check(root, VALUES, created="2026-10-10")["findings"] == []
    files = nc.render(VALUES, created="2026-10-10")
    cfg = json.loads(files["channels/example-history.json"])
    cfg.pop("status")
    cfg["stance"] = "elsewhere.json"
    files["channels/example-history.json"] = json.dumps(cfg).encode("utf-8")
    files["channels/example-history/stance.json"] = b'{"channel_id": "reel"}'
    found = nc.config_findings(root, "example-history", files)
    codes = [f["code"] for f in found]
    for code in ("template_has_pipeline", "template_stance_path", "stance_invalid"):
        assert code in codes, (code, found)
    assert all(f["code"] and f["text_ru"] for f in found), found
    assert nc.config_errors(root, "example-history", files) == [f["text"] for f in found]

def test_check_writes_nothing_and_create_writes_the_files_only():
    root = tree()
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    assert nc.main(["check", "example-history", "--name", "History", "--root", str(root)]) == 0
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == before
    assert nc.main(["create", "example-history", "--name", "History", "--root", str(root)]) == 0
    made = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    assert made == ["channels/reel.json", "channels/example-history.json",
                    "channels/example-history/brand/description.md",
                    "channels/example-history/stance.json"]
    # now it is taken
    assert nc.main(["create", "example-history", "--name", "History 2", "--root", str(root)]) == 1


def _fields(res):
    return [r["field"] for r in res["input_errors"]]


def test_the_inputs_are_refused_with_their_field():
    root = tree()
    (root / "pipeline" / "ghost").mkdir(parents=True)
    cases = {
        "": ["channel_id"], "A-b": ["channel_id"], "x": ["channel_id"], "ab-": ["channel_id"],
        "a--b": ["channel_id"], "9lives": ["channel_id"], "a" * 41: ["channel_id"],
        "reel": ["channel_id"],                      # a channel
        "old-reel": ["channel_id"],                  # its former id - the same channel
        "ghost": ["channel_id"],                     # pipeline/ghost/ is on disk
        "rebuilds": ["channel_id"],                  # not a channel
        "template": ["channel_id"],                  # reserved by the caller
    }
    for cid, want in cases.items():
        res = nc.check(root, {"channel_id": cid, "display_name": "Fresh"},
                       reserved=("template",))
        assert _fields(res) == want, (cid, res["input_errors"])
        assert not res["ok"] and res["files"] == {} and res["errors"] == []
    (root / "channels" / "half").mkdir()
    assert _fields(nc.check(root, {"channel_id": "half", "display_name": "Half"})) == ["channel_id"]
    for name in ("", "reel", "REEL", "two\nlines", "x" * 61):
        res = nc.check(root, {"channel_id": "fresh", "display_name": name})
        assert _fields(res) == ["display_name"], (name, res["input_errors"])
    for lang in ("english", "EN", "e"):
        res = nc.check(root, {"channel_id": "fresh", "display_name": "Fresh", "language": lang})
        assert _fields(res) == ["language"], (lang, res["input_errors"])
    res = nc.check(root, {"channel_id": " fresh ", "display_name": " Fresh ", "language": "pt-BR"})
    assert res["ok"] and res["values"] == {"channel_id": "fresh", "display_name": "Fresh",
                                           "language": "pt-BR"}


def test_the_form_s_inputs_and_files_come_from_the_template():
    t = nc.template()
    assert [i["name"] for i in t["inputs"]] == ["channel_id", "display_name", "language"]
    assert all(i["note"] for i in t["inputs"])
    assert t["status"] == ids.NO_PIPELINE and t["batch_schedule"]["enabled"] is False
    for f in t["files"]:
        assert (ROOT / f["template"]).is_file(), f


def test_there_is_one_template_and_the_api_has_none():
    api = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "api").glob("*.py"))
    cfg = json.loads((ROOT / "shared" / "channel_template" / "config.json").read_text())
    for needle in (cfg["theme"]["bg"], cfg["theme"]["accent"], cfg["theme"]["badge"]["paper"],
                   "the template's neutral palette", "stance_note"):
        assert needle not in api, needle


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
