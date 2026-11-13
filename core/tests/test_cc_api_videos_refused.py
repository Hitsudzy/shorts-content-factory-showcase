#!/usr/bin/env python3
"""CC-0116 (CF-0727): a video refused after the render in the command
center's API. The Editor writes it into the batch's 05 `refusals[]`, not
`videos[]` (13.10: example-science/2026-10-12T2001Z - `videos: []`, the QC
score refusal of sophie-adenot, its mp4 and preview frame on disk), so the
list showed nothing and the rebuild could not name it.

In-process (starlette's TestClient) against the stand-in factory root of
`tests/test_cc_api_videos.py` (a temp git repository) with one more batch of
that shape; nothing outside the temp dir read or written, no network.
Pinned:
* `GET .../videos` lists it after the built ones with `refused: {reason_code,
  reason, gate, score_line, score, at}` (the script's last refusal), its slug
  the one `batch_control._source_videos` finds (`work/<slug>/` naming the
  script), the refusal's score line, its mp4 and preview; a built video
  `refused: null`; a refusal without a slug (refused before any work
  directory) or whose script is not in 03 is not listed; a rebuild that made
  it again is in its `rebuilt_in`;
* its mp4 and preview by the same routes, the card route 404 `no_card` (not
  `unknown_video`); a refused one without its mp4 `exists: false`, 404
  `no_mp4`;
* a verdict on it is 409 `video_refused`, the record untouched; a built
  video of the same batch still takes one;
* CC-0119: the refusal leaves through `paths.clean` - the Editor's
  `score.log[].where.shot` / `note` with an absolute clip path (inside the
  root: relative; outside: `.../<name>`; the home `~`), in the list and in a
  rebuild's list; the rebuild's modes and plan carry only the gate;
* the contract: `Video.refused` (`VideoRefusal`), `video_refused` in
  `BatchProblem`, `RebuildModes.videos` (`RebuildSourceVideo`: refused, plan)
  and `RebuildVideo.refused` / `plan`.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import test_cc_api_videos as tv                     # noqa: E402
from test_cc_api_batches import H, _w, client, git  # noqa: E402
from api import factory                              # noqa: E402

RB = "2026-10-12T2001Z"
REBUILT = "2026-10-13T0524Z"
SCORE = {"start": 100, "score": 24, "tier": "F", "threshold": 40, "passed": False,
         "log": [{"rule": "score.frozen_frame", "price": -62}]}
REFUSAL = {"script_id": "t-adenot-script1", "reason_code": "score_below_threshold",
           "reason": "SCORE UNDER THE THRESHOLD after qc: 24 < 40 (tier F)",
           "gate": "score_below_threshold", "at": "2026-10-12T23:52:04+00:00",
           "supersedes_video": True, "numbers": {"score": 24, "threshold": 40, "stage": "qc"},
           "score_line": "F · 24 — −62 зависший кадр (1 блок, хук)", "score": SCORE}


def refused_tree(mp4=True):
    """The videos test's root plus reel/<RB>: one built video (paper-dragon) and
    adenot refused by QC after the render (an older refusal of the same
    script before it), s-011 refused before any work directory, s-999 not in
    03; a rebuild of it that made adenot again."""
    root = tv.tree()
    d = tv.make_batch(root, "reel", RB, ("paper-dragon",))
    doc03 = json.loads((d / "03-content-researcher.json").read_text(encoding="utf-8"))
    doc03["scripts"] += [{"script_id": "t-adenot-script1", "topic_id": "t-adenot"},
                         {"script_id": "t-late-script1", "topic_id": "t-late"}]
    _w(d / "03-content-researcher.json", doc03)
    doc05 = json.loads((d / "05-video-editor.json").read_text(encoding="utf-8"))
    doc05["refusals"] = [dict(REFUSAL, gate="old_gate", score_line="старая", at="earlier"),
                         REFUSAL,
                         {"script_id": "t-late-script1", "gate": "two_source_gate"},
                         {"script_id": "t-999", "gate": "two_source_gate"}]
    _w(d / "05-video-editor.json", doc05)
    w = d / "work" / "adenot"
    _w(w / "order.json", {"script_id": "t-adenot-script1", "topic_id": "t-adenot"})
    _w(w / "plan.json", {"blocks": []})
    if mp4:
        (d / "videos" / "adenot.mp4").write_bytes(tv.MP4)
        (d / "videos" / "adenot.jpg").write_bytes(tv.JPG)
    tv.make_batch(root, "rebuilds", REBUILT, ("adenot",),
                  run_state_of={"channel": "reel", "batch_id": RB, "path": f"pipeline/reel/{RB}"})
    return root


def url(what=""):
    return f"/api/batches/reel/{RB}/videos{what}"


def test_the_list_shows_the_refused_video():
    root = refused_tree()
    c = client(root)
    r = c.get(url())
    assert r.status_code == 200, r.text
    j = r.json()
    assert [v["slug"] for v in j["videos"]] == ["paper-dragon", "adenot"], j["videos"]
    built, ad = j["videos"]
    assert built["refused"] is None and built["score_line"] == "B · 80 — тест", built
    assert ad["script_id"] == "t-adenot-script1" and ad["qc_passed"] is None, ad
    assert ad["refused"] == {"reason_code": "score_below_threshold", "reason": REFUSAL["reason"],
                             "gate": "score_below_threshold", "score_line": REFUSAL["score_line"],
                             "score": SCORE, "at": REFUSAL["at"],
                             "reason_ru": factory.funnel().reason_ru("score_below_threshold")}, \
        ad["refused"]
    assert ad["score_line"] == REFUSAL["score_line"], ad
    assert ad["mp4"]["exists"] is True and ad["mp4"]["bytes"] == len(tv.MP4), ad["mp4"]
    assert ad["mp4"]["path"] == f"pipeline/reel/{RB}/videos/adenot.mp4", ad["mp4"]
    assert ad["preview"]["available"] is True and ad["preview"]["kind"] == "frame", ad["preview"]
    assert ad["card"]["exists"] is False, ad["card"]
    assert ad["rebuilt_in"] == [f"rebuilds/{REBUILT}"], ad
    assert [rb["videos"][0]["slug"] for rb in j["rebuilds"]] == ["adenot"], j["rebuilds"]
    assert j["rebuilds"][0]["videos"][0]["refused"] is None
    assert "/home/" not in r.text and str(root) not in r.text


def test_its_files_go_by_the_same_routes():
    root = refused_tree()
    c = client(root)
    r = c.get(url("/adenot/mp4"))
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp4", r.text[:200]
    assert r.content == tv.MP4
    r = c.get(url("/adenot/mp4"), headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and r.content == tv.MP4[:10], r.status_code
    r = c.get(url("/adenot/preview"))
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg", r.text[:200]
    r = c.get(url("/adenot/card"))
    assert r.status_code == 404 and r.json()["code"] == "no_card", r.text
    for slug in ("t-late-script1", "t-999", "late"):
        r = c.get(url(f"/{slug}/mp4"))
        assert r.status_code == 404 and r.json()["code"] == "unknown_video", (slug, r.text)


def test_a_refused_video_without_its_file():
    root = refused_tree(mp4=False)
    c = client(root)
    ad = tv.by_slug(c.get(url()).json()["videos"])["adenot"]
    assert ad["mp4"]["exists"] is False and ad["mp4"]["bytes"] is None, ad["mp4"]
    r = c.get(url("/adenot/mp4"))
    assert r.status_code == 404 and r.json()["code"] == "no_mp4", r.text
    r = c.get(url("/adenot/preview"))
    assert r.status_code == 404 and r.json()["code"] == "no_preview", r.text


def test_a_refused_video_takes_no_verdict():
    root = refused_tree()
    c = client(root)
    log = root / "publish" / "acceptance-log.json"
    before = log.read_bytes()
    head = git(root, "rev-parse", "HEAD")
    r = c.post(url("/adenot/acceptance"), headers=H,
               json={"verdict": "yes", "words": "adenot принят"})
    assert r.status_code == 409, r.text
    b = r.json()
    assert b["code"] == "video_refused" and "отказан после рендера" in b["message"], b
    assert "score_below_threshold" in b["message"], b
    assert log.read_bytes() == before and git(root, "rev-parse", "HEAD") == head
    r = c.post(url("/paper-dragon/acceptance"), headers=H,
               json={"verdict": "yes", "words": "paper-dragon принят"})
    assert r.status_code == 200, r.text
    assert [x["slug"] for x in tv.log_rows(root)] == ["paper-dragon"]


def test_absolute_paths_in_the_refusal_are_cut():
    """13.10 (CC-0116): the Editor's `refusals[].score.log[].where.shot` and
    `note` carry `/home/.../work/<slug>/clips/a06_….mp4` - the answer cuts
    them as every other path: inside the root relative, outside `.../<name>`."""
    root = refused_tree()
    d = root / "pipeline" / "reel" / RB
    clip = d / "work" / "adenot" / "clips" / "a06_frozen.mp4"
    outside = "/Volumes/Archive/elsewhere/deep/b02_far.mp4"
    score = dict(SCORE, log=[
        {"rule": "score.frozen_frame", "price": -62,
         "where": {"block": 1, "shot": str(clip), "at_s": 2.5},
         "note": f"frozen 1.2 s in {clip} (see {outside})"},
        {"rule": "score.long_shot", "price": -4,
         "where": {"shot": str(clip.resolve())}, "note": f"{Path.home()}/notes/x.txt"}])
    doc05 = json.loads((d / "05-video-editor.json").read_text(encoding="utf-8"))
    doc05["refusals"][1] = dict(REFUSAL, score=score,
                                reason=f"SCORE UNDER THE THRESHOLD after qc: {clip}")
    _w(d / "05-video-editor.json", doc05)
    c = client(root)
    r = c.get(url())
    assert r.status_code == 200, r.text
    ad = next(v for v in r.json()["videos"] if v["slug"] == "adenot")
    rel = f"pipeline/reel/{RB}/work/adenot/clips/a06_frozen.mp4"
    log = ad["refused"]["score"]["log"]
    assert log[0]["where"] == {"block": 1, "shot": rel, "at_s": 2.5}, log[0]
    assert log[0]["note"] == f"frozen 1.2 s in {rel} (see .../b02_far.mp4)", log[0]["note"]
    assert log[1]["where"]["shot"] == rel and log[1]["note"] == "~/notes/x.txt", log[1]
    assert ad["refused"]["reason"] == f"SCORE UNDER THE THRESHOLD after qc: {rel}"
    assert ad["refused"]["score"]["score"] == 24 and log[0]["price"] == -62  # numbers kept
    for bad in (str(root), str(root.resolve()), "/Volumes/", str(Path.home())):
        assert bad not in r.text, bad
    # the rebuild's modes and plan name the gate only - and leave cleaned too
    m = c.get(f"/api/batches/reel/{RB}/rebuild/modes")
    assert m.status_code == 200, m.text
    src = {v["slug"]: v for v in m.json()["videos"]}
    assert src["adenot"]["refused"] == "score_below_threshold", src
    for bad in (str(root), str(root.resolve()), "/Volumes/"):
        assert bad not in m.text, bad


def test_the_contract_carries_the_refusal():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    sch = spec["components"]["schemas"]
    assert "refused" in sch["Video"]["properties"], sch["Video"]
    assert set(sch["VideoRefusal"]["properties"]) == {"reason_code", "reason_ru", "reason",
                                                      "gate", "score_line", "score", "at"}
    assert "video_refused" in sch["BatchProblem"]["properties"]["code"]["enum"]
    assert "videos" in sch["RebuildModes"]["properties"]
    assert {"slug", "script_id", "topic_id", "refused", "plan"} <= \
        set(sch["RebuildSourceVideo"]["properties"])
    assert {"refused", "plan"} <= set(sch["RebuildVideo"]["properties"])


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
