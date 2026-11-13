#!/usr/bin/env python3
"""CF-0198: a "channel id or path" argument is read by its shape, not by
whether a file happens to exist.

The recorded failure: a config that moved was passed by its full path, the path
did not exist, so it was taken for a channel id and looked up as
`channels/<full path>.json` - the error read `legacy-film.json.json`, which
sends the reader after whoever glued on a second extension instead of at the
missing file. The same shape in `--signal path:topic_id`: when neither reading
names a file, the error must name the file, not `<path>:<topic>`.

CF-0213: and there is no channel to fall back to. `score_candidates.py` used to
read `batch.get("channel", <first channel>)` and `--channel-config or <first
channel>`, so a second channel's run that forgot the flag scored against the
first channel's feeds. No channel is a refusal now; an id with no
`channels/<id>.json` is a refusal naming both readings. Stand-in roots only.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import _channel_ids  # noqa: E402
import footage_candidates as fc  # noqa: E402
import score_candidates as sc  # noqa: E402


def _raises_missing(fn, *args):
    try:
        fn(*args)
    except FileNotFoundError as exc:
        return str(exc)
    raise AssertionError(f"{fn.__name__}{args} did not raise FileNotFoundError")


def test_shape_decides_path_or_id():
    for arg in ("/x/example-film.json", "channels/example-film", "~/v.json", "example-film.json"):
        assert _channel_ids.looks_like_path(arg), arg
    for arg in ("example-film", "legacy-film", "pop_culture"):
        assert not _channel_ids.looks_like_path(arg), arg


def test_missing_config_path_is_no_such_file_not_a_second_json():
    with tempfile.TemporaryDirectory() as d:
        missing = Path(d) / "moved" / "legacy-film.json"
        msg = _raises_missing(sc.load_channel_config, str(missing))
    assert str(missing) in msg
    assert ".json.json" not in msg


def test_existing_config_path_is_read():
    with tempfile.TemporaryDirectory() as d:
        cfg = Path(d) / "c.json"
        cfg.write_text(json.dumps({"id": "x"}))
        assert sc.load_channel_config(str(cfg)) == {"id": "x"}
        assert _channel_ids.channel_config_arg(cfg) == cfg


def test_a_bare_id_still_goes_through_the_channel_lookup():
    with tempfile.TemporaryDirectory() as d:
        channels = Path(d) / "channels"
        channels.mkdir()
        (channels / "ch-b.json").write_text(json.dumps({"channel_id": "ch-b"}))
        seen = []
        got = _channel_ids.channel_config_arg(
            "ch-b", by_id=lambda c: seen.append(c) or channels / f"{c}.json")
        assert seen == ["ch-b"]
        assert got == channels / "ch-b.json"
        # and score_candidates reads it from its root's channels/ - a stand-in
        # root here, never the live channel file (CF-0609)
        with _project_root(d):
            assert sc.load_channel_config("ch-b") == {"channel_id": "ch-b"}


# --- CF-0213: no channel is a refusal, not the first channel --------------

class _project_root:
    def __init__(self, root):
        self.root = Path(root)

    def __enter__(self):
        self.saved = sc.PROJECT_ROOT
        sc.PROJECT_ROOT = self.root

    def __exit__(self, *exc):
        sc.PROJECT_ROOT = self.saved


def _feeds_config(feeds, house_ceil=2):
    return {"channel_id": "x", "sources": {"rss": {"house_ceil": house_ceil, "feeds": [
        {"url": f"https://{site}/feed", "site": site, "house": house}
        for site, house in feeds]}}}


def test_an_unknown_id_is_refused_with_both_readings_named():
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "channels").mkdir()
        with _project_root(d):
            msg = _raises_missing(sc.load_channel_config, "ghost")
    assert "'ghost'" in msg and str(Path(d) / "channels" / "ghost.json") in msg, msg
    assert "channel id" in msg and "path" in msg, msg
    assert ".json.json" not in msg


def test_no_channel_at_all_is_refused():
    for empty in (None, "", "  "):
        try:
            _channel_ids.channel_config_arg(empty)
        except _channel_ids.MissingChannelError as exc:
            assert "no default channel" in str(exc)
        else:
            raise AssertionError(f"channel_config_arg({empty!r}) picked a channel")


def _batch_dir(d, batch):
    b = Path(d) / "batch"
    b.mkdir()
    (b / "01-trend-hunter.json").write_text(json.dumps(batch))
    return b


def _stderr_of(fn, *args):
    import contextlib
    import io
    err, out = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
        code = fn(*args)
    return code, err.getvalue(), out.getvalue()


def test_replay_of_a_batch_without_a_channel_is_refused():
    with tempfile.TemporaryDirectory() as d:
        b = _batch_dir(d, {"batch_id": "b", "topics": []})
        code, err, _ = _stderr_of(sc._replay, str(b), 40.0, None)
    assert code == 2, code
    assert "no `channel` field" in err and "CF-0213" in err, err


def test_replay_reads_the_batch_s_channel_or_the_flag():
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "channels").mkdir()
        (Path(d) / "channels" / "ch-b.json").write_text(
            json.dumps(_feeds_config([("variety.com", "pmc")])))
        b = _batch_dir(d, {"batch_id": "b", "channel": "ch-b", "topics": []})
        with _project_root(d):
            code, err, out = _stderr_of(sc._replay, str(b), 40.0, None)
            assert code == 0 and "(0 topics)" in out, (code, err, out)
            cfg = Path(d) / "elsewhere.json"
            cfg.write_text(json.dumps(_feeds_config([])))
            b2 = Path(d) / "b2"
            b2.mkdir()
            (b2 / "01-trend-hunter.json").write_text(json.dumps({"batch_id": "b2",
                                                                 "topics": []}))
            code, err, _ = _stderr_of(sc._replay, str(b2), 40.0, str(cfg))
            assert code == 0, (code, err)
            # CF-0627: a channel config without its house ceiling is a refusal
            cfg.write_text(json.dumps(_feeds_config([], house_ceil=None)))
            code, err, _ = _stderr_of(sc._replay, str(b2), 40.0, str(cfg))
            assert code == 2 and "house_ceil" in err, (code, err)


def test_houses_without_a_channel_is_refused():
    saved = sys.argv
    sys.argv = ["score_candidates.py", "--houses", "https://variety.com/a"]
    try:
        code, err, out = _stderr_of(sc._main)
    finally:
        sys.argv = saved
    assert code == 2 and "--channel-config" in err and "CF-0213" in err, (code, err)
    assert not out


def test_houses_reads_the_named_channel_s_feeds():
    with tempfile.TemporaryDirectory() as d:
        cfg = Path(d) / "ch.json"
        cfg.write_text(json.dumps(_feeds_config([("variety.com", "pmc"),
                                                 ("vulture.com", "vox")])))
        saved = sys.argv
        sys.argv = ["score_candidates.py", "--houses", "https://variety.com/a",
                    "https://www.vulture.com/b", "--channel-config", str(cfg)]
        try:
            code, err, out = _stderr_of(sc._main)
        finally:
            sys.argv = saved
    assert code == 0, err
    assert json.loads(out)["distinct_rss_houses"] == 2, out


def test_signal_with_missing_file_names_the_file():
    with tempfile.TemporaryDirectory() as d:
        missing = Path(d) / "feed.json"
        msg = _raises_missing(fc.load_signals, [f"{missing}:t1"])
    assert str(missing) in msg and f"{missing}:t1" in msg
    assert "no signal file" in msg


def test_signal_without_topic_still_reads():
    with tempfile.TemporaryDirectory() as d:
        a = Path(d) / "s.json"
        a.write_text(json.dumps({"query": "Q", "videos": []}))
        assert list(fc.load_signals([str(a)])) == ["Q"]
        assert list(fc.load_signals([f"{a}:t9"])) == ["t9"]


def test_signal_glued_by_zsh_modifier_is_refused_with_the_cause():
    # CF-0862, example-tech/2026-10-25T0934Z: `--signal $f:lf-2026-10-25-$k`
    # under zsh became `footage-003.jsonvsm-2026-10-25-003` (`:t` = tail).
    raw = "footage-003.jsonvsm-2026-10-25-003"
    with tempfile.TemporaryDirectory() as d:
        cwd = os.getcwd()
        os.chdir(d)
        try:
            msg = _raises_missing(fc.load_signals, [raw])
        finally:
            os.chdir(cwd)
    assert raw in msg and "no signal file" in msg, msg
    assert "footage-003.json" in msg and "`:t`" in msg and '"${f}:' in msg, msg


def test_signal_without_binding_or_file_is_refused():
    with tempfile.TemporaryDirectory() as d:
        missing = str(Path(d) / "nothing-here")
        msg = _raises_missing(fc.load_signals, [missing])
    assert missing in msg and "no signal file" in msg and '"${f}:${t}"' in msg, msg


def test_main_refuses_glued_signal_before_writing():
    # The call ends with exit 2 and the refusal on stderr, the batch file
    # untouched - not a FileNotFoundError traceback (the 0934Z crash).
    with tempfile.TemporaryDirectory() as d:
        batch_dir = Path(d) / "b"
        batch_dir.mkdir()
        bf = batch_dir / "01-trend-hunter.json"
        body = json.dumps({"topics": [{"topic_id": "lf-2026-10-25-003"}]})
        bf.write_text(body)
        good = Path(d) / "feed.json"
        good.write_text(json.dumps({"query": "Q", "videos": []}))
        code, err, _ = _stderr_of(fc.main, [str(batch_dir),
                                            "--signal", f"{good}:lf-2026-10-25-003",
                                            "--signal", "footage-003.jsonvsm-2026-10-25-003",
                                            "--write"])
        assert bf.read_text() == body
    assert code == 2, (code, err)
    assert "footage-003.jsonvsm-2026-10-25-003" in err and "`:t`" in err, err
    assert "Traceback" not in err, err


def _run():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {name}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run())
