#!/usr/bin/env python3
"""CC-0108: the diversity of the feed of accepted videos in the command
center's API (`api/analytics.py` `diversity`, `GET /api/analytics/diversity`).

Everything runs in-process (starlette's TestClient) against a stand-in
factory root in a temp dir: a `publish/acceptance-log.json` written by the
test, one batch directory for a row whose profile is not written yet. The
factory's *code* (`shared/runlog/publish_profile.py`) is this checkout's;
nothing of the live factory is read, no network.

What is pinned:

* the contract: the route, GET only, its `last` (default = the CLI's
  DEFAULT_LAST, 0 - the whole feed), version 0.48.0, `AnalyticsProblem`;
* the answer is what `runlog diversity --last N --root <root> --json` prints
  (its `main` run on the same root) - the axes as `{value, count, share}`
  in the factory's order, its lines verbatim; a rejected, a pulled (amended
  to rejected) and an older acceptance of the same name do not count;
* a row without a profile is read from its batch on the spot (`read_live`)
  and nothing is written; a row whose batch is gone counts as `unknown`;
* a missing log is an empty feed (`log_exists: false`), a broken one too
  (`log_read: false`); no absolute path in the answer;
* CC-0119 (CF-0719): `?channel=` is `runlog diversity --channel C` - that
  channel's rows only (a former id resolved, both ways), `channel` today's
  id; an unknown channel is 404 `unknown_channel` in Russian; `log_error`
  goes out through `paths.clean` (an absolute path in the factory's reason
  is cut).
"""
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fastapi.testclient import TestClient            # noqa: E402

import api                                           # noqa: E402
from _tmproot import tmp_root                        # noqa: E402
from api import analytics, factory                   # noqa: E402
from api.app import create_app                       # noqa: E402
from api.settings import Settings                    # noqa: E402

TMP = tmp_root("cc-api-diversity-test-")
LOCAL = ("127.0.0.1", 50000)
BASE = "http://127.0.0.1:8790"
ROUTE = "/api/analytics/diversity"
_N = [0]


def _w(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False),
                    encoding="utf-8")
    return path


def _prof(kind, pattern, rhythm, hook):
    return {"fact_kind": kind, "pattern": pattern, "rhythm": rhythm, "hook_opener": hook}


def _row(slug, at, verdict="accepted", profile=None, batch="2026-10-01T0000Z"):
    r = {"entry_id": f"reel/{batch}/{slug}", "slug": slug, "channel": "reel",
         "batch_id": batch, "verdict": verdict, "answered_at": at, "recorded_at": at}
    if profile is not None:
        r["profile"] = profile
    return r


def factory_root(rows=None, raw=None):
    _N[0] += 1
    root = TMP / f"factory-{_N[0]}"
    _w(root / "channels" / "reel.json", {"channel_id": "reel"})
    if raw is not None:
        _w(root / "publish" / "acceptance-log.json", raw)
    elif rows is not None:
        _w(root / "publish" / "acceptance-log.json", {"acceptances": rows})
    return root


def feed_rows():
    return [
        _row("alpha", "2026-10-01T10:00:00Z", profile=_prof("production", "list", "hold", "q")),
        _row("beta", "2026-10-02T10:00:00Z", profile=_prof("production", "reveal", "hold", None)),
        _row("gamma", "2026-10-03T10:00:00Z", profile=_prof("cast", "list", "fast", "q")),
        _row("delta", "2026-10-04T10:00:00Z", verdict="rejected",
             profile=_prof("cast", "list", "fast", "q")),
        # an older acceptance of alpha's name - the latest one counts, in its place
        _row("alpha", "2026-09-01T10:00:00Z", profile=_prof("trivia", "x", "y", "z")),
        # no profile and no batch on disk - read on the spot, `unknown`
        _row("ghost", "2026-10-05T10:00:00Z", batch="2026-01-01T0000Z"),
    ]


def client(root):
    return TestClient(create_app(Settings(factory_root=root), token="tok"), client=LOCAL,
                      base_url=BASE)


def _cli(root, last):
    out = io.StringIO()
    with redirect_stdout(out):
        rc = factory.publish_profile().main(["diversity", "--root", str(root), "--last",
                                             str(last), "--json"])
    assert rc == 0
    return json.loads(out.getvalue())


def _files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


# --------------------------------------------------------------------- the contract
def test_the_contract_names_the_diversity_route_get_only():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    assert sorted(spec["paths"][ROUTE]) == ["get"]
    get_ = spec["paths"][ROUTE]["get"]
    last, channel = get_["parameters"]
    assert last["name"] == "last" and last["schema"]["default"] == analytics.DIVERSITY_LAST
    assert channel["name"] == "channel" and channel["in"] == "query"
    assert channel.get("required") is not True
    assert analytics.DIVERSITY_LAST == factory.publish_profile().DEFAULT_LAST
    ref = get_["responses"]["404"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/AnalyticsProblem"), ref
    props = spec["components"]["schemas"]["FeedDiversity"]["properties"]
    assert set(props) == {"last", "channel", "n", "videos", "read_live", "axes", "lines",
                          "log", "log_exists", "log_read", "log_error"}


# --------------------------------------------------------------------- the answer
def test_the_answer_is_the_cli_s_json_and_its_lines():
    root = factory_root(feed_rows())
    before = _files(root)
    for last in (10, 2, 0):
        r = client(root).get(ROUTE, params={"last": last})
        assert r.status_code == 200, r.text
        got = r.json()
        cli = _cli(root, last)
        assert got["last"] == last and got["n"] == cli["n"]
        assert got["videos"] == cli["videos"] and got["read_live"] == cli["read_live"]
        pp = factory.publish_profile()
        assert [a["key"] for a in got["axes"]] == [k for k, _ in pp.AXES]
        assert {a["key"]: [[v["value"], v["count"], v["share"]] for v in a["values"]]
                for a in got["axes"]} == cli["axes"]
        assert got["lines"] == pp.render_diversity(cli)
        assert got["log"] == "publish/acceptance-log.json" and got["log_exists"] is True
        assert got["log_read"] is True
        assert str(root.resolve()) not in json.dumps(got, ensure_ascii=False)
    assert _files(root) == before, "a GET wrote something"


def test_the_feed_counts_the_latest_standing_acceptance():
    root = factory_root(feed_rows())
    got = client(root).get(ROUTE).json()
    assert got["videos"] == ["alpha", "beta", "gamma", "ghost"], got["videos"]
    assert "delta" not in got["videos"] and got["n"] == len(got["videos"])
    assert got["read_live"] == ["ghost"]
    kinds = {v["value"]: v for v in next(a for a in got["axes"]
                                         if a["key"] == "fact_kind")["values"]}
    assert kinds["unknown"]["count"] == 1 and "trivia" not in kinds, kinds
    assert got["lines"][0].startswith("Разнообразие ленты: последние"), got["lines"]
    two = client(root).get(ROUTE, params={"last": 2}).json()
    assert two["videos"] == got["videos"][-2:] and two["n"] == 2


def test_a_missing_or_broken_log_is_an_empty_feed():
    for root, exists in ((factory_root(), False), (factory_root(raw="{not json"), True),
                         (factory_root(raw="[1, 2]"), True)):
        r = client(root).get(ROUTE)
        assert r.status_code == 200, r.text
        got = r.json()
        assert got["n"] == 0 and got["videos"] == [] and got["log_exists"] is exists
        assert got["log_read"] is False
        # CF-0719: a broken log says which file and why; a missing one does not
        if exists:
            assert got["log_error"].startswith("publish/acceptance-log.json: "), got
            assert str(root) not in got["log_error"], got["log_error"]
        else:
            assert got["log_error"] is None, got
        assert all(a["values"] == [] for a in got["axes"]), got["axes"]
    r = client(factory_root()).get(ROUTE, params={"last": -1})
    assert r.status_code == 422, r.text


# --------------------------------------------------------------------- one channel (CC-0119)
def _two_channel_root():
    rows = feed_rows() + [
        dict(_row("omega", "2026-10-06T10:00:00Z", profile=_prof("cast", "duel", "slow", "w")),
             channel="old-other", entry_id="old-other/2026-10-01T0000Z/omega"),
        dict(_row("sigma", "2026-10-07T10:00:00Z", profile=_prof("cast", "list", "slow", "w")),
             channel="other", entry_id="other/2026-10-01T0000Z/sigma"),
    ]
    root = factory_root(rows)
    _w(root / "channels" / "other.json",
       {"channel_id": "other", "former_channel_ids": ["old-other"]})
    return root


def test_one_channel_s_feed_is_the_cli_s_channel():
    root = _two_channel_root()
    c = client(root)
    whole = c.get(ROUTE).json()
    assert whole["channel"] is None and "omega" in whole["videos"] and "alpha" in whole["videos"]
    for asked in ("other", "old-other"):
        r = c.get(ROUTE, params={"channel": asked, "last": 0})
        assert r.status_code == 200, r.text
        got = r.json()
        assert got["channel"] == "other" and got["videos"] == ["omega", "sigma"], got
        out = io.StringIO()
        with redirect_stdout(out):
            rc = factory.publish_profile().main(["diversity", "--root", str(root), "--last", "0",
                                                 "--channel", asked, "--json"])
        assert rc == 0
        cli = json.loads(out.getvalue())
        assert cli["channel"] == "other" and got["videos"] == cli["videos"]
        assert got["lines"] == factory.publish_profile().render_diversity(cli)
        assert got["lines"][0].startswith("Разнообразие ленты канала other"), got["lines"]
    reel = c.get(ROUTE, params={"channel": "reel", "last": 2}).json()
    assert reel["channel"] == "reel" and reel["videos"] == ["gamma", "ghost"], reel
    empty = c.get(ROUTE, params={"channel": ""}).json()
    assert empty["channel"] is None and empty["n"] == whole["n"]


def test_an_unknown_channel_is_a_russian_problem():
    root = _two_channel_root()
    r = client(root).get(ROUTE, params={"channel": "nosuch"})
    assert r.status_code == 404, r.text
    got = r.json()
    assert set(got) == {"message", "code", "details"} and got["code"] == "unknown_channel"
    assert "nosuch" in got["message"] and any("А" <= ch <= "я" for ch in got["message"]), got
    text = json.dumps(got, ensure_ascii=False)
    assert str(root) not in text and str(root.resolve()) not in text, text


def test_the_log_error_goes_through_paths_clean():
    """The factory's reason may name the file absolutely; it leaves cut."""
    root = factory_root(raw="{not json")
    pp = factory.publish_profile()
    saved = pp._load

    def broken(path):
        raise pp.PublishProfileError(path, f"cannot read {Path(path).resolve()} "
                                           f"(see {Path.home()}/notes.txt)")
    pp._load = broken
    try:
        got = client(root).get(ROUTE).json()
    finally:
        pp._load = saved
    err = got["log_error"]
    assert err.startswith("publish/acceptance-log.json: cannot read "), err
    assert str(root) not in err and str(root.resolve()) not in err and str(Path.home()) not in err
    assert "publish/acceptance-log.json (see ~/notes.txt)" in err, err


if __name__ == "__main__":
    tests = [(k, fn) for k, fn in list(globals().items()) if k.startswith("test_") and callable(fn)]
    fails = 0
    for k, fn in tests:
        try:
            fn()
            print("ok  ", k)
        except Exception as e:                          # noqa: BLE001
            fails += 1
            print("FAIL", k, type(e).__name__, e)
    print(f"{len(tests) - fails}/{len(tests)} passed")
    sys.exit(1 if fails else 0)
