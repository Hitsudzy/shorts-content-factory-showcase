#!/usr/bin/env python3
"""CC-0103: the meme bank's candidates in the center (`api/memes.py`
`candidates`) - `GET /api/memes/{channel}/candidates`, what
`scripts/meme_desk.py candidates --channel <id>` prints, as data:

    the bank's candidates.json (CF-0393) as written, checked by the desk's own
    candidate_problems (the root's fit box, ceiling and intent vocabulary),
    each row with stretch_now, group and copy_from (the default bank's
    entry and its media routes), the download / copy totals, each row's
    candidates_state status and `accept` (CC-0114); read only.

In-process (starlette's TestClient) against the stand-in roots of
`tests/test_cc_api_memes.py` `world()` (temp dir; the checkout's
`inserts/meme.json` copied in): the candidate lists are written into the
temp banks here. The real banks are never opened; no network - a template's
Imgflip `url` is data, never fetched.

What is pinned: the list and its totals as the CLI counts them; the desk's
problems (a `passes_ceiling` that disagrees, an intent outside the
vocabulary, a url that is not Imgflip's); `copy_from` for an entry the
default bank has and null for one it has not; a bank without the list is
`missing`, not a refusal; a list that does not parse is 409 `bad_candidates`;
an unknown channel 404, a bank that does not open the desk's `bad_bank`;
nothing written; the yes's availability and fingerprint (CC-0114 - the yes
itself is tests/test_cc_api_meme_accept.py); the contract.
"""
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

from test_cc_api_batches import _w, client                         # noqa: E402
from test_cc_api_memes import desk, get, world                      # noqa: E402
from test_cc_api_publish import files                               # noqa: E402

from api import memes                                               # noqa: E402

TECH = ("shared", "inserts", "memes-tech", "candidates.json")


def cand(cid, w, h, passes, **over):
    c = {"id": cid, "name": cid.title(), "imgflip_id": "1", "url":
         f"https://i.imgflip.com/{cid}.jpg", "width": w, "height": h, "stretch": None,
         "passes_ceiling": passes, "bytes": 1000, "blank_band": "none",
         "intents": ["smug"], "use": "when a launch goes sideways"}
    c.update(over)
    return c


def listing():
    return {"schema_note": "test list", "bank": "shared/inserts/memes-tech/",
            "listed": "2026-10-12", "source": {"name": "Imgflip"},
            "summary": {"candidates": 5},
            "candidates": [
                cand("wide-one", 800, 450, True),                          # 1.35x - passes
                cand("copied", 600, 600, True, in_reel_bank="old-one", bytes=2048),
                cand("not-there", 600, 600, True, in_reel_bank="no-such-entry", bytes=10),
                cand("tiny", 100, 100, False, bytes=50),                   # 10.8x - fails
                cand("no-data", None, None, None, imgflip_id=None, url=None, bytes=None),
            ],
            "reel_tail": {"candidates": [cand("tail-one", None, None, None, url=None)]}}


def tech_world(data=None):
    root = world()
    _w(root.joinpath(*TECH), listing() if data is None else data)
    return root


def test_the_list_with_its_totals_as_the_cli_counts_them():
    root = tech_world()
    before = files(root)
    code, r = get(client(root), "/api/memes/tech/candidates")
    assert code == 200, r
    assert (r["channel"], r["bank"], r["default_bank"], r["path"], r["missing"]) == \
        ("tech", "memes-tech", False, "shared/inserts/memes-tech/candidates.json", None), r
    assert r["listed"] == "2026-10-12" and r["summary"] == {"candidates": 5}, r
    assert r["fit_box"] == [1080, 1219] and r["ceiling"] == 2.25, r
    by = {c["id"]: c for c in r["candidates"]}
    assert [c["id"] for c in r["candidates"]] == ["wide-one", "copied", "not-there", "tiny",
                                                  "no-data"]
    assert by["wide-one"]["group"] == "pass" and by["wide-one"]["stretch_now"] == 1.35
    assert by["tiny"]["group"] == "fail" and by["tiny"]["stretch_now"] == 10.8
    assert by["no-data"]["group"] == "unknown" and by["no-data"]["stretch_now"] is None
    assert by["wide-one"]["url"] == "https://i.imgflip.com/wide-one.jpg"     # data, kept whole
    assert by["wide-one"]["use"] == "when a launch goes sideways"           # as written
    assert r["counts"] == {"pass": 3, "fail": 1, "unknown": 1}, r["counts"]
    assert r["download"] == {"files": 1, "bytes": 1000}, r["download"]
    assert r["copy"] == {"files": 2, "bytes": 2058}, r["copy"]
    assert [t["id"] for t in r["tail"]] == ["tail-one"]
    assert r["problems"] == [], r["problems"]
    assert r["fingerprint"] and len(r["fingerprint"]) == 64
    assert files(root) == before                                           # nothing written


def test_copy_from_is_the_default_banks_entry_and_its_routes():
    root = tech_world()
    code, r = get(client(root), "/api/memes/tech/candidates")
    assert code == 200, r
    cc = r["copy_channel"]
    want = desk().resolve_bank(cc, None, root / "shared" / "inserts", root)[0]
    assert cc in ("demo", "reel") and want is None and r["copy_error"] is None, r
    by = {c["id"]: c for c in r["candidates"]}
    assert by["copied"]["copy_from"] == {
        "channel": cc, "id": "old-one",
        "urls": {"file": f"/api/memes/{cc}/old-one/media?kind=file", "cut": None,
                 "thumb": f"/api/memes/{cc}/old-one/thumb"}}, by["copied"]
    assert by["not-there"]["copy_from"] is None and by["wide-one"]["copy_from"] is None
    # the route it points at serves the default bank's file
    code, body = get(client(root), by["copied"]["copy_from"]["urls"]["file"].split("?")[0],
                     kind="file")
    assert code == 200 and isinstance(body, bytes), code


def test_the_desks_problems_are_said():
    data = listing()
    data["candidates"][0]["passes_ceiling"] = False                      # disagrees: 1.35x
    data["candidates"][1]["intents"] = ["not-an-intent"]
    data["candidates"][3]["url"] = "https://example.org/tiny.jpg"
    root = tech_world(data)
    code, r = get(client(root), "/api/memes/tech/candidates")
    assert code == 200, r
    want = desk().candidate_problems(data, box=(1080, 1219), ceiling=2.25,
                                     vocabulary=memes._vocabulary(root))
    assert r["problems"] == want and len(want) == 3, r["problems"]
    joined = " ".join(r["problems"])
    assert "passes_ceiling" in joined and "not-an-intent" in joined and "imgflip" in joined


def test_a_bank_without_the_list_and_a_list_that_does_not_parse():
    root = world()
    code, r = get(client(root), "/api/memes/reel/candidates")
    assert code == 200 and r["candidates"] == [] and r["bank"] == "memes", r
    assert r["missing"] and "нет списка кандидатов" in r["missing"], r
    assert r["fingerprint"] is None and r["accept"]["available"] is False
    _w(root.joinpath(*TECH), "{")
    code, r = get(client(root), "/api/memes/tech/candidates")
    assert code == 409 and r["code"] == "bad_candidates", r
    assert r["message"] and r["details"] and str(root) not in json.dumps(r), r


def test_unknown_channel_and_a_bank_that_does_not_open():
    root = tech_world()
    c = client(root)
    code, r = get(c, "/api/memes/nope/candidates")
    assert code == 404 and r["code"] == "unknown_channel", r
    code, r = get(c, "/api/memes/lost/candidates")
    assert code == 409 and r["code"] == "bad_bank", r


def test_the_get_is_read_only_and_the_yes_has_its_own_routes():
    """CC-0114: the GET says whether the yes is open (candidates_state's
    fingerprint) and writes nothing; the yes is the two POSTs of
    tests/test_cc_api_meme_accept.py."""
    root = tech_world()
    code, r = get(client(root), "/api/memes/tech/candidates")
    a = r["accept"]
    assert a["available"] is True and a["reason"] is None, a
    assert a["fingerprint"].startswith("sha256:") and a["counts"]["total"] == 5, a
    assert a["other_bank"] == ["tail-one"] and a["ready"] == [], a      # no file in the bank
    assert {c["status"] for c in r["candidates"]} == {"not_downloaded"}, r["candidates"]
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    cands = {p: set(v) for p, v in spec["paths"].items() if "candidates" in p}
    assert cands == {"/api/memes/{channel}/candidates": {"get"},
                     "/api/memes/{channel}/candidates/accept/plan": {"post"},
                     "/api/memes/{channel}/candidates/accept": {"post"}}, cands
    import ast
    tree = ast.parse((ROOT / "api" / "memes.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "candidates")
    names = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
    assert not names & {"add_image", "save_index", "write_text", "_locked", "_issue",
                        "accept_candidates", "plan_accept"}, names


def test_the_contract():
    import api
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    op = spec["paths"]["/api/memes/{channel}/candidates"]["get"]["responses"]
    assert op["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/MemeCandidates")
    for status in ("404", "409"):
        assert "/MemesProblem" in json.dumps(op[status]), (status, op[status])
    codes = set(spec["components"]["schemas"]["MemesProblem"]["properties"]["code"]["enum"])
    assert {"bad_candidates", "bad_spec", "bad_bank", "unknown_channel"} <= codes
    props = spec["components"]["schemas"]["MemeCandidates"]["properties"]
    assert {"copy", "download", "counts", "candidates", "problems", "accept", "tail"} <= \
        set(props), sorted(props)
    counts = spec["components"]["schemas"]["MemeCandidateCounts"]["properties"]
    assert set(counts) == {"pass", "fail", "unknown"}, counts


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
