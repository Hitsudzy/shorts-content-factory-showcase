#!/usr/bin/env python3
"""CC-0012: a batch's videos for the acceptance in the command center's API
(`api/videos.py`; `GET /api/batches/{channel}/{batch_id}/videos`,
`.../videos/{slug}/mp4`, `/preview`, `/card`, `POST .../videos/{slug}/acceptance`)
over the factory's own readers and the acceptance record's writer
(`shared/runlog/acceptance.py` `record_and_commit`, CF-0328 / CF-0675).

In-process (starlette's TestClient) against a stand-in factory root in a temp
dir (`tests/test_cc_api_batches.py` `factory_tree`: a git repository with
`reel`), a batch, two rebuilds of it and one of another batch built here.
**Nothing outside the temp dir is read or written**: the record is the temp
root's `publish/acceptance-log.json`; no network; nothing timing-sensitive.

What is pinned:

* the contract: the five routes, version 0.48.0, `BatchProblem` on the
  problems, the mp4 route with 206 / 416, `AcceptIn` = {verdict, words,
  reason?, reason_code?, amend?};
* the list is the 05's videos (`runlog.editor_videos`) with score line, mp4,
  preview, short card and the record's state; a source lists its rebuilds
  beside it (by `run-state.json` `rebuild.of` and by the 05's `rebuild_of`),
  not a rebuild of another batch, and names them on its videos
  (`rebuilt_in`); a rebuild names its source;
* the mp4: `video/mp4`, `Accept-Ranges`, a single range 206 with
  `Content-Range`, open-ended, suffix, past the end 416 `*/<size>`, HEAD;
  only `<batch>/videos/<slug>.mp4` - a slug not in the 05, `..`, a symlink
  out of the tree are 404s;
* the preview (CC-0057, CF-0674): the Editor's `videos/<slug>.jpg` first
  (`kind: frame`, `image/jpeg`, a rebuild's too, a symlink out not served),
  else the frame judge's first sheet as `image/png` with its grid and tile;
  none -> `available: false` and why, the route 404 `no_preview`;
* the card: parsed by the factory (`card_state`, sections, title,
  description's three blocks, tags), the raw text beside; a card
  `publish_note.parse` refuses -> `note_error`, the tags as written; none ->
  404 `no_card`;
* the verdict (CC-0057: `acceptance.record_and_commit`, CF-0675): only by a
  POST behind the guard; `yes` -> accepted with the user's exact words, the
  day and time the factory's; with no batch going exactly one commit of
  `publish/acceptance-log.json` only, HEAD moved by one, the tree clean; under
  a planted open batch the verdict queued (`pending`), HEAD and the record
  untouched, the list showing it pending; the next verdict with no batch
  commits the queue first (`flushed`, two commits); each factory refusal (no
  name in the words, a position, no reason, no code, a code on «принят», a
  second verdict without `amend`) a 422 with the factory's code (CF-0676) and
  `text_ru`, its English words behind, nothing written - under a batch too; a
  record that does not read 409 `record_unreadable`; a commit git refuses 500
  `not_committed`, the record as it was; `amend` replaces it and keeps the
  history; `redo` -> rejected with the «переделать» note, `redo.queued:
  false` and why until CC-0018 sets `REDO_QUEUE`, then the request goes there;
* nothing writes a verdict but `accept`: the reads leave the record
  untouched; `record_and_commit` is named only in `accept`, `record` /
  `write_log` / `commit_pending` nowhere in `api/`.
"""
import ast
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ.pop("ACCEPTANCE_LOG", None)

from test_cc_api_batches import (                    # noqa: E402
    BASE, H, TMP, _w, client, factory_tree, git, marker, state, write_batch)

import api                                           # noqa: E402
from api import factory, videos                      # noqa: E402

BATCH = "2026-10-09T0900Z"
RB1, RB2, RB_OTHER = "2026-10-10T0900Z", "2026-10-10T1000Z", "2026-10-10T1100Z"
SLUGS = ("paper-dragon", "night-owl", "no-file")
MP4 = bytes(range(256)) * 40                         # 10240 bytes, every offset knowable
PNG = b"\x89PNG\r\n\x1a\n" + b"sheet" * 20
JPG = b"\xff\xd8\xff\xe0" + b"frame" * 20 + b"\xff\xd9"


def card_text(slug, title=None, status="not_ready"):
    mark = {"status": status, "slug": slug, "problems": ["title_too_long"],
            "source": {"name": "Wikipedia", "url": "https://en.wikipedia.org/wiki/X"},
            "fact_checks": [], "claims": {"verdict": "not_asked"}, "fingerprint": "x"}
    return (f"# {slug} — карточка публикации\n\nРолик: `x.mp4`\n\n"
            f"## Название\n{title or slug.title() + ': a fact #shorts'}\n\n"
            f"## Описание\nWhat {slug} is about.\n\nThe fact comes from: Wikipedia · "
            f"https://en.wikipedia.org/wiki/X\n\n#{slug.replace('-', '')} #shorts\n\n"
            f"## Теги\n{slug}, film, box office\n\n## Публикация\nСлот не назначен.\n\n"
            f"## Настройки\n- ИИ / синтетический контент: нет\n\n## Карточка\n"
            f"Статус: **НЕ готова**\n<!-- publish_card {json.dumps(mark)} -->\n")


def make_batch(root, dirname, batch_id, slugs, rebuild_of=None, run_state_of=None,
               mp4=True, pack=True, cards=True):
    d = root / "pipeline" / dirname / batch_id
    scripts = [{"script_id": f"t-{s}-script1", "topic_id": f"t-{s}"} for s in slugs]
    _w(d / "03-content-researcher.json", {"channel": "reel", "batch_id": batch_id,
                                          "scripts": scripts})
    doc = {"channel": "reel", "batch_id": batch_id, "videos": [
        {"script_id": f"t-{s}-script1", "output_path": str(d / "videos" / f"{s}.mp4"),
         "qc": {"passed": True}, "duration": 41.5, "score_line": "B · 80 — тест",
         "code_shas": {"root": {"commit": "a" * 40, "dirty": False}}} for s in slugs]}
    if rebuild_of:
        doc["rebuild_of"] = rebuild_of
    _w(d / "05-video-editor.json", doc)
    if run_state_of:
        _w(d / "run-state.json", {"status": "done", "channel": "reel",
                                  "rebuild": {"of": run_state_of}})
    for s in slugs:
        if s == "no-file":
            continue
        if mp4:
            (d / "videos").mkdir(parents=True, exist_ok=True)
            (d / "videos" / f"{s}.mp4").write_bytes(MP4)
        if pack and s == slugs[0]:
            fj = d / "work" / s / "frame-judge"
            _w(fj / "manifest.json", {"schema": "frame-judge-pack/1", "sheets": [
                {"file": "sheet-1.png", "tiles": [1, 6], "grid": {"columns": 3, "rows": 2},
                 "tile": {"width": 360, "height": 640}}]})
            (fj / "sheet-1.png").write_bytes(PNG)
        if cards:
            _w(d / "work" / "publish-card" / f"{s}.md", card_text(s))
    return d


def tree():
    """The root, the batch and its rebuilds; `publish/` committed with an
    empty record, as in the factory."""
    root = factory_tree()
    make_batch(root, "reel", BATCH, SLUGS)
    make_batch(root, "rebuilds", RB1, ("paper-dragon",),
               rebuild_of={"channel": "reel", "batch_id": BATCH,
                           "path": f"pipeline/reel/{BATCH}"})
    make_batch(root, "rebuilds", RB2, ("night-owl",),
               run_state_of={"channel": "reel", "batch_id": BATCH,
                             "path": f"pipeline/reel/{BATCH}"})
    make_batch(root, "rebuilds", RB_OTHER, ("paper-dragon",),
               rebuild_of={"channel": "reel", "batch_id": "2026-10-01T0900Z",
                           "path": "pipeline/reel/2026-10-01T0900Z"})
    _w(root / "publish" / "acceptance-log.json",
       {"note": "test", "task": "CF-0328", "acceptances": []})
    queue = [ln for ln in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
             if "acceptance-pending" in ln or ln.endswith(".mp4") and ln.startswith("publish/")]
    # CF-0738: an accepted video's render is copied into publish/<channel>/_queue/ -
    # gitignored in the factory, so here too
    assert queue, "the factory's .gitignore names the acceptance queue (CF-0675)"
    _w(root / ".gitignore", "/schedule/\n/pipeline/\n" + "\n".join(queue) + "\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "publish/")
    return root


def log_rows(root):
    return json.loads((root / "publish" / "acceptance-log.json").read_text())["acceptances"]


def by_slug(vs):
    return {v["slug"]: v for v in vs}


# --------------------------------------------------------------------- the contract
def test_the_contract_names_the_video_routes():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    base = "/api/batches/{channel}/{batch_id}/videos"
    for path, method in ((base, "get"), (f"{base}/{{slug}}/mp4", "get"),
                         (f"{base}/{{slug}}/preview", "get"), (f"{base}/{{slug}}/card", "get"),
                         (f"{base}/{{slug}}/acceptance", "post")):
        assert sorted(spec["paths"][path]) == [method], (path, spec["paths"][path].keys())
        resp = spec["paths"][path][method]["responses"]
        assert "403" in resp and resp["404"]["content"]["application/json"]["schema"]["$ref"] \
            .endswith("/BatchProblem"), path
    mp4 = spec["paths"][f"{base}/{{slug}}/mp4"]["get"]["responses"]
    assert "video/mp4" in mp4["200"]["content"] and "206" in mp4 and "416" in mp4, mp4
    schemas = spec["components"]["schemas"]
    assert sorted(schemas["AcceptIn"]["required"]) == ["verdict", "words"], schemas["AcceptIn"]
    assert set(schemas["AcceptIn"]["properties"]) == {"verdict", "words", "reason",
                                                      "reason_code", "amend"}
    assert schemas["AcceptIn"]["properties"]["verdict"]["enum"] == ["yes", "no", "redo"]
    enum = schemas["BatchProblem"]["properties"]["code"]["enum"]
    for code in ("unknown_video", "no_mp4", "no_preview", "no_card", "acceptance_broken",
                 "answer_without_name", "verdict_already_given", "not_committed"):
        assert code in enum, code
    assert "acceptance_refused" not in enum
    assert {"pending", "committed", "commit", "subject", "queue", "batches", "flushed"} <= \
        set(schemas["AcceptResult"]["properties"]), schemas["AcceptResult"]
    assert {"pending", "queued_at", "queued_by"} <= set(schemas["VideoAcceptance"]["properties"])
    assert {"videos", "rebuilds", "rebuild_of", "reason_codes", "acceptance_error"} <= \
        set(schemas["BatchVideos"]["properties"])
    assert {"raw", "sections", "ready", "why", "description_blocks", "tags"} <= \
        set(schemas["Card"]["properties"])


# --------------------------------------------------------------------- the list
def test_the_list_is_the_05_with_its_rebuilds_beside():
    root = tree()
    c = client(root)
    r = c.get(f"/api/batches/reel/{BATCH}/videos")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["channel"] == "reel" and j["rebuild_of"] is None and j["acceptance_error"] is None
    vs = by_slug(j["videos"])
    assert [v["slug"] for v in j["videos"]] == list(SLUGS)
    pt = vs["paper-dragon"]
    assert pt["mp4"] == {"url": f"/api/batches/reel/{BATCH}/videos/paper-dragon/mp4",
                         "exists": True, "bytes": len(MP4),
                         "path": f"pipeline/reel/{BATCH}/videos/paper-dragon.mp4"}, pt["mp4"]
    assert pt["preview"]["available"] and pt["preview"]["kind"] == "sheet"
    assert pt["preview"]["media_type"] == "image/png"
    assert pt["preview"]["grid"] == {"columns": 3, "rows": 2}, pt["preview"]
    assert pt["preview"]["tile"] == {"width": 360, "height": 640}
    assert pt["score_line"] and pt["qc_passed"] is True and pt["duration"] == 41.5
    assert pt["card"]["exists"] and pt["card"]["ready"] is False and pt["card"]["why"], pt["card"]
    assert pt["card"]["title"] == "Paper-Dragon: a fact #shorts"
    assert pt["acceptance"]["recorded"] is False and pt["acceptance"]["verdict"] is None
    assert pt["acceptance"]["entry_id"] == f"reel/{BATCH}/paper-dragon"
    assert pt["accept_url"] == f"/api/batches/reel/{BATCH}/videos/paper-dragon/acceptance"
    no = vs["night-owl"]["preview"]
    assert no["available"] is False and no["url"] is None and "кадра превью нет" in no["reason"]
    assert vs["no-file"]["mp4"]["exists"] is False and vs["no-file"]["card"]["exists"] is False
    # the rebuilds of this batch, by the 05's rebuild_of and by run-state rebuild.of
    assert [b["batch"] for b in j["rebuilds"]] == [f"rebuilds/{RB1}", f"rebuilds/{RB2}"], \
        j["rebuilds"]
    assert [v["slug"] for v in j["rebuilds"][0]["videos"]] == ["paper-dragon"]
    assert j["rebuilds"][0]["videos"][0]["mp4"]["url"] == \
        f"/api/batches/rebuilds/{RB1}/videos/paper-dragon/mp4"
    assert pt["rebuilt_in"] == [f"rebuilds/{RB1}"] and \
        vs["night-owl"]["rebuilt_in"] == [f"rebuilds/{RB2}"] and vs["no-file"]["rebuilt_in"] == []
    # a rebuild names its source; it lists no rebuilds of its own
    j = c.get(f"/api/batches/rebuilds/{RB1}/videos").json()
    assert j["rebuild_of"] == {"channel": "reel", "batch_id": BATCH,
                               "batch": f"reel/{BATCH}"}, j["rebuild_of"]
    assert j["rebuilds"] == [] and j["channel"] == "reel"
    j = c.get(f"/api/batches/rebuilds/{RB2}/videos").json()
    assert j["rebuild_of"]["batch"] == f"reel/{BATCH}"


def test_a_batch_without_05_or_record_says_so():
    root = tree()
    _w(root / "pipeline" / "reel" / "2026-10-08T0900Z" / "RUN_EVENTS.jsonl", "")
    c = client(root)
    j = c.get("/api/batches/reel/2026-10-08T0900Z/videos").json()
    assert j["videos"] == [] and "05-video-editor.json нет" in j["editor_error"], j
    (root / "publish" / "acceptance-log.json").write_text("{broken")
    j = c.get(f"/api/batches/reel/{BATCH}/videos").json()
    assert j["acceptance_error"] and "не читается" in j["acceptance_error"], j
    assert all(v["acceptance"] is None for v in j["videos"])
    r = c.post(f"/api/batches/reel/{BATCH}/videos/paper-dragon/acceptance", headers=H,
               json={"verdict": "yes", "words": "paper-dragon - да"})
    assert r.status_code == 409 and r.json()["code"] == "record_unreadable", r.text
    assert "не читается" in r.json()["message"] and "does not parse" in r.json()["details"][0]
    assert (root / "publish" / "acceptance-log.json").read_text() == "{broken"
    assert c.get("/api/batches/reel/nope/videos").status_code == 404


# --------------------------------------------------------------------- the mp4
def test_the_mp4_answers_ranges():
    root = tree()
    c = client(root)
    url = f"/api/batches/reel/{BATCH}/videos/paper-dragon/mp4"
    r = c.get(url)
    assert r.status_code == 200 and r.content == MP4, r.status_code
    assert r.headers["content-type"] == "video/mp4" and r.headers["accept-ranges"] == "bytes"
    assert r.headers["x-content-type-options"] == "nosniff"
    for rng, body, cr in (("bytes=0-99", MP4[:100], "bytes 0-99/10240"),
                          ("bytes=10000-", MP4[10000:], "bytes 10000-10239/10240"),
                          ("bytes=-100", MP4[-100:], "bytes 10140-10239/10240"),
                          ("bytes=500-10239999", MP4[500:], "bytes 500-10239/10240")):
        r = c.get(url, headers={"Range": rng})
        assert r.status_code == 206, (rng, r.status_code)
        assert r.content == body and r.headers["content-range"] == cr, (rng, r.headers)
        assert r.headers["content-length"] == str(len(body)), rng
    r = c.get(url, headers={"Range": "bytes=20000-"})
    assert r.status_code == 416 and r.headers["content-range"] == "*/10240", r.headers
    r = c.head(url)
    assert r.status_code == 200 and r.content == b"" and r.headers["content-length"] == "10240"
    r = c.get(f"/api/batches/rebuilds/{RB1}/videos/paper-dragon/mp4", headers={"Range": "bytes=1-2"})
    assert r.status_code == 206 and r.content == MP4[1:3]


def test_only_the_batch_s_own_mp4_is_served():
    root = tree()
    c = client(root)
    for slug, code in (("nope", "unknown_video"), ("no-file", "no_mp4")):
        r = c.get(f"/api/batches/reel/{BATCH}/videos/{slug}/mp4")
        assert r.status_code == 404 and r.json()["code"] == code, (slug, r.text)
    for bad in ("..", "..%2F..%2Fchannels%2Freel.json"):
        r = c.get(f"/api/batches/reel/{BATCH}/videos/{bad}/mp4")
        assert r.status_code == 404, (bad, r.status_code)
    # a symlink out of the tree, even under the video's own name, is not served
    outside = TMP / "outside.mp4"
    outside.write_bytes(b"secret")
    d = root / "pipeline" / "reel" / BATCH / "videos"
    (d / "night-owl.mp4").unlink()
    (d / "night-owl.mp4").symlink_to(outside)
    r = c.get(f"/api/batches/reel/{BATCH}/videos/night-owl/mp4")
    assert r.status_code == 404 and b"secret" not in r.content, r.status_code
    try:
        videos.mp4_path(root, "reel", BATCH, "night-owl")
        raise AssertionError("served a link out")
    except videos.BatchFault as e:
        assert e.code == "no_mp4"


# --------------------------------------------------------------------- the preview
def test_the_preview_is_the_editor_s_frame_else_the_sheet_else_none():
    """CC-0057 (CF-0674): `videos/<slug>.jpg` first, the judge's sheet for a
    video without it, `available: false` and why for neither."""
    root = tree()
    c = client(root)
    vids = root / "pipeline" / "reel" / BATCH / "videos"
    (vids / "paper-dragon.jpg").write_bytes(JPG)       # it has a sheet too: the frame wins
    (vids / "night-owl.jpg").write_bytes(JPG)         # no sheet
    vs = by_slug(c.get(f"/api/batches/reel/{BATCH}/videos").json()["videos"])
    for slug in ("paper-dragon", "night-owl"):
        pv = vs[slug]["preview"]
        assert pv == {"available": True, "kind": "frame", "media_type": "image/jpeg",
                      "url": f"/api/batches/reel/{BATCH}/videos/{slug}/preview",
                      "path": f"pipeline/reel/{BATCH}/videos/{slug}.jpg", "tile": None,
                      "grid": None, "reason": None}, (slug, pv)
        r = c.get(f"/api/batches/reel/{BATCH}/videos/{slug}/preview")
        assert r.status_code == 200 and r.content == JPG, (slug, r.status_code)
        assert r.headers["content-type"] == "image/jpeg"
    # the frame removed (none could be taken): back to the sheet, or to none
    (vids / "paper-dragon.jpg").unlink()
    (vids / "night-owl.jpg").unlink()
    vs = by_slug(c.get(f"/api/batches/reel/{BATCH}/videos").json()["videos"])
    assert vs["paper-dragon"]["preview"]["kind"] == "sheet"
    assert c.get(f"/api/batches/reel/{BATCH}/videos/paper-dragon/preview").content == PNG
    no = vs["night-owl"]["preview"]
    assert no["available"] is False and "night-owl.jpg нет" in no["reason"], no
    # a frame that is a symlink out of the tree is not served
    outside = TMP / "outside.jpg"
    outside.write_bytes(b"secret")
    (vids / "night-owl.jpg").symlink_to(outside)
    assert by_slug(c.get(f"/api/batches/reel/{BATCH}/videos").json()["videos"])[
        "night-owl"]["preview"]["available"] is False
    r = c.get(f"/api/batches/reel/{BATCH}/videos/night-owl/preview")
    assert r.status_code == 404 and b"secret" not in r.content
    # a rebuild's frame too
    rb = root / "pipeline" / "rebuilds" / RB1 / "videos"
    (rb / "paper-dragon.jpg").write_bytes(JPG)
    r = c.get(f"/api/batches/rebuilds/{RB1}/videos/paper-dragon/preview")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"


def test_the_preview_is_the_judge_s_first_sheet():
    root = tree()
    c = client(root)
    r = c.get(f"/api/batches/reel/{BATCH}/videos/paper-dragon/preview")
    assert r.status_code == 200 and r.content == PNG, r.status_code
    assert r.headers["content-type"] == "image/png"
    r = c.get(f"/api/batches/reel/{BATCH}/videos/night-owl/preview")
    assert r.status_code == 404 and r.json()["code"] == "no_preview", r.text
    assert "Кадра превью нет" in r.json()["message"]
    # a manifest naming a sheet outside the pack is not followed
    man = root / "pipeline" / "reel" / BATCH / "work" / "paper-dragon" / "frame-judge" / \
        "manifest.json"
    man.write_text(json.dumps({"sheets": [{"file": "../../../videos/paper-dragon.mp4"}]}))
    assert c.get(f"/api/batches/reel/{BATCH}/videos/paper-dragon/preview").status_code == 404


# --------------------------------------------------------------------- the card
def test_the_card_is_parsed_by_the_factory():
    root = tree()
    c = client(root)
    r = c.get(f"/api/batches/reel/{BATCH}/videos/paper-dragon/card")
    assert r.status_code == 200, r.text
    j = r.json()
    path = root / "pipeline" / "reel" / BATCH / "work" / "publish-card" / "paper-dragon.md"
    assert j["raw"] == path.read_text(encoding="utf-8")
    assert j["path"] == f"pipeline/reel/{BATCH}/work/publish-card/paper-dragon.md"
    assert j["ready"] is False and "not ready" in j["why"] and j["status"] == "not_ready", j
    assert j["title"] == "Paper-Dragon: a fact #shorts"
    assert len(j["description_blocks"]) == 3 and j["description_blocks"][0] == \
        "What paper-dragon is about.", j["description_blocks"]
    assert j["tags"] == ["paper-dragon", "film", "box office"] and j["note_error"] is None
    assert j["contains_synthetic"] is False and j["publish_at"] is None
    assert [s["name"] for s in j["sections"]] == ["Название", "Описание", "Теги", "Публикация",
                                                  "Настройки", "Карточка"]
    assert j["problems"] == ["title_too_long"] and j["source"]["name"] == "Wikipedia"
    assert j["mark"]["status"] == "not_ready"
    # a card the note's reader refuses: its refusal, the tags as written
    path.write_text(card_text("paper-dragon", title="<b>bad</b>"), encoding="utf-8")
    j = c.get(f"/api/batches/reel/{BATCH}/videos/paper-dragon/card").json()
    assert j["tags"] is None and "'<' or '>'" in j["note_error"], j["note_error"]
    assert j["tags_raw"] == "paper-dragon, film, box office"
    r = c.get(f"/api/batches/reel/{BATCH}/videos/no-file/card")
    assert r.status_code == 404 and r.json()["code"] == "no_card", r.text


# --------------------------------------------------------------------- the verdict
def _post(c, slug, batch=f"reel/{BATCH}", **body):
    return c.post(f"/api/batches/{batch}/videos/{slug}/acceptance", headers=H, json=body)


def test_the_verdict_is_the_user_s_press_written_by_the_factory():
    root = tree()
    c = client(root)
    before = state(root)
    words = "Paper Dragon — да, публикуем"
    r = c.post(f"/api/batches/reel/{BATCH}/videos/paper-dragon/acceptance",
               json={"verdict": "yes", "words": words})
    assert r.status_code == 403, r.text
    r = c.post(f"/api/batches/reel/{BATCH}/videos/paper-dragon/acceptance",
               headers={"Origin": "http://evil.example", "X-CC-Session": "tok"},
               json={"verdict": "yes", "words": words})
    assert r.status_code == 403
    assert log_rows(root) == []
    r = _post(c, "paper-dragon", verdict="yes", words=words)
    assert r.status_code == 200, r.text
    j = r.json()
    row = j["row"]
    assert row["verdict"] == "accepted" and row["answer"] == words and row["answer_verbatim"]
    assert row["entry_id"] == f"reel/{BATCH}/paper-dragon" and row["topic_id"] == "t-paper-dragon"
    assert row["answered_at"] == datetime.now(timezone.utc).date().isoformat()
    assert row["recorded_at"].endswith("Z") and row["task"] == "CF-0328"
    assert row["code_shas"] == {"root": {"commit": "a" * 40, "dirty": False}}
    assert row["note"] == videos.YES_NO_NOTE and j["redo"] is None
    assert j["log"] == "publish/acceptance-log.json"
    assert j["acceptance"]["accepted"] is True and j["acceptance"]["answer"] == words
    assert j["acceptance"]["pending"] is False
    assert [x["entry_id"] for x in log_rows(root)] == [row["entry_id"]]
    # CF-0675: no batch going - one commit of the record and of nothing else
    assert j["pending"] is False and j["committed"] is True and j["batches"] == []
    assert j["flushed"] is None and j["queue"] is None and "pending" not in row
    assert j["subject"] == "Приёмка: paper-dragon принят (user (центр))", j["subject"]
    after = state(root)
    assert after["status"] == "", after["status"]
    assert after["head"] == j["commit"] != before["head"]
    assert git(root, "rev-parse", "HEAD~1") == before["head"], "exactly one commit"
    assert git(root, "show", "--name-only", "--format=", "HEAD") == \
        "publish/acceptance-log.json"
    assert git(root, "log", "-1", "--format=%s") == j["subject"]
    v = by_slug(c.get(f"/api/batches/reel/{BATCH}/videos").json()["videos"])["paper-dragon"]
    assert v["acceptance"]["verdict"] == "accepted" and v["acceptance"]["publishable"] is True
    # a second verdict needs `amend`; with it the old one goes to history
    raw = (root / "publish" / "acceptance-log.json").read_bytes()
    r = _post(c, "paper-dragon", verdict="no", words="paper-dragon нет", reason="мыло",
              reason_code="blurry_footage")
    assert r.status_code == 422 and r.json()["code"] == "verdict_already_given", r.text
    assert "уже есть вердикт" in r.json()["message"] and "already carries" in \
        r.json()["details"][0]
    assert (root / "publish" / "acceptance-log.json").read_bytes() == raw
    assert state(root) == after
    r = _post(c, "paper-dragon", verdict="no", words="paper-dragon всё-таки нет",
              reason="мыльная картинка", reason_code="blurry_footage",
              amend="пересмотрел на большом экране")
    assert r.status_code == 200, r.text
    row = r.json()["row"]
    assert row["verdict"] == "rejected" and row["reason_code"] == "blurry_footage"
    assert len(row["history"]) == 1 and row["history"][0]["verdict"] == "accepted"
    assert len(log_rows(root)) == 1
    codes = c.get(f"/api/batches/reel/{BATCH}/videos").json()["reason_codes"]
    assert [x["code"] for x in codes] == ["blurry_footage"], codes


def test_the_accepted_video_s_kopilka_is_in_the_answer():
    """CC-0122: the factory's `queued` (CF-0738) goes out with the verdict - the
    accepted video's render copied into publish/<c>/_queue/, its Russian line,
    the path relative; a rejection has none."""
    from api.app import ACCEPT_QUEUE_CODES
    assert set(ACCEPT_QUEUE_CODES) == set(factory.collect().acceptance().QUEUE_RU)
    root = tree()
    c = client(root)
    r = _post(c, "paper-dragon", verdict="yes", words="Paper Dragon — да")
    assert r.status_code == 200, r.text
    q = r.json()["queued"]
    assert q["code"] == "placed" and q["ok"] and q["changed"] and not q["refused"], q
    assert "копилку" in q["text_ru"] and "publish/reel/_queue/" in q["text_ru"], q
    assert q["publish_path"].endswith("reel/_queue/paper-dragon.mp4"), q
    assert not q["publish_path"].startswith("/") and str(root) not in json.dumps(q), q
    assert (root / "publish" / "reel" / "_queue" / "paper-dragon.mp4").is_file()
    r = _post(c, "night-owl", verdict="no", words="night-owl нет", reason="мыло",
              reason_code="blurry_footage")
    assert r.status_code == 200 and r.json()["queued"] is None, r.text


def test_the_factory_s_refusals_write_nothing():
    root = tree()
    c = client(root)
    raw = (root / "publish" / "acceptance-log.json").read_bytes()
    head = state(root)["head"]
    for body, code, needle, ru in (
            ({"verdict": "yes", "words": "да"}, "answer_without_name", "does not name",
             "нет имени ролика"),
            ({"verdict": "yes", "words": "1 и 3 - да"}, "answer_is_position",
             "position in a list", "номер в списке"),
            ({"verdict": "no", "words": "night-owl нет"}, "rejection_without_reason",
             "no reason", "без причины"),
            ({"verdict": "no", "words": "night-owl нет", "reason": "скучно"},
             "rejection_without_code", "reason_code", "код причины"),
            ({"verdict": "yes", "words": "night-owl да", "reason_code": "x"},
             "acceptance_with_code", "carries no `reason_code`", "не бывает кода")):
        r = _post(c, "night-owl", **body)
        assert r.status_code == 422, (body, r.text)
        j = r.json()
        assert j["code"] == code and ru in j["message"], (body, j)
        assert needle in j["details"][0], (body, j["details"])
        assert j["message"] == factory.collect().acceptance().REFUSALS_RU[code].format(
            slug="night-owl"), j
    assert (root / "publish" / "acceptance-log.json").read_bytes() == raw
    r = _post(c, "nope", verdict="yes", words="nope да")
    assert r.status_code == 404 and r.json()["code"] == "unknown_video"
    assert _post(c, "night-owl", verdict="maybe", words="night-owl").status_code == 422
    assert (root / "publish" / "acceptance-log.json").read_bytes() == raw
    assert state(root) == {"head": head, "status": ""}


GOING = "2026-10-10T1200Z"


def plant_batch(root):
    """A stand-in batch going now (`batch-start` a few minutes ago, no
    `batch-done`) - `runlog.open_batches` counts it fresh."""
    return write_batch(root, "reel", GOING, [marker("batch-start", hours_ago=0.05)])


def queue_file(root):
    return root / "publish" / "acceptance-pending.jsonl"


def test_under_an_open_batch_the_verdict_is_queued_and_head_stays():
    root = tree()
    c = client(root)
    plant_batch(root)
    before = state(root)
    raw = (root / "publish" / "acceptance-log.json").read_bytes()
    r = _post(c, "paper-dragon", verdict="yes", words="paper-dragon - да")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["pending"] is True and j["committed"] is False and j["commit"] is None, j
    assert j["subject"] is None and j["flushed"] is None
    assert j["queue"] == "publish/acceptance-pending.jsonl"
    assert [b["dir"] for b in j["batches"]] == [f"pipeline/reel/{GOING}"], j["batches"]
    assert j["row"]["pending"] is True and j["row"]["queued_by"] == videos.BY
    assert j["acceptance"]["pending"] is True and j["acceptance"]["queued_at"]
    assert j["acceptance"]["verdict"] == "accepted"
    # HEAD and the tree as batch-start left them; the record untouched
    assert state(root) == before, state(root)
    assert (root / "publish" / "acceptance-log.json").read_bytes() == raw
    assert queue_file(root).is_file()
    # the list shows the queued verdict at once
    v = by_slug(c.get(f"/api/batches/reel/{BATCH}/videos").json()["videos"])["paper-dragon"]
    a = v["acceptance"]
    assert a["pending"] is True and a["verdict"] == "accepted" and a["queued_at"], a
    assert a["queued_by"] == videos.BY
    # a refusal is said at once under the batch too - nothing written, nothing queued
    q = queue_file(root).read_bytes()
    r = _post(c, "night-owl", verdict="no", words="night-owl нет")
    assert r.status_code == 422 and r.json()["code"] == "rejection_without_reason", r.text
    assert queue_file(root).read_bytes() == q and state(root) == before


def test_the_next_verdict_with_no_batch_commits_the_queue_first():
    root = tree()
    c = client(root)
    going = plant_batch(root)
    assert _post(c, "paper-dragon", verdict="yes", words="paper-dragon - да").json()["pending"]
    before = state(root)
    # the batch is done
    with open(going / "RUN_EVENTS.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(marker("batch-done")) + "\n")
    r = _post(c, "night-owl", verdict="no", words="night-owl нет", reason="скучно",
              reason_code="boring")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["pending"] is False and j["committed"] is True and j["batches"] == []
    f = j["flushed"]
    assert f and f["committed"] is True and f["applied"] == [f"reel/{BATCH}/paper-dragon"], f
    assert f["subject"] == "Приёмка: paper-dragon принят (user (центр))" and f["left"] == 0
    assert j["subject"] == "Приёмка: night-owl отклонён (user (центр))"
    # two commits: the queue's, then the verdict's - each the record only
    assert git(root, "rev-parse", "HEAD~2") == before["head"]
    assert git(root, "rev-parse", "HEAD~1") == f["commit"]
    for rev in ("HEAD", "HEAD~1"):
        assert git(root, "show", "--name-only", "--format=", rev) == \
            "publish/acceptance-log.json", rev
    assert state(root)["status"] == "" and not queue_file(root).exists()
    assert sorted(x["entry_id"] for x in log_rows(root)) == \
        [f"reel/{BATCH}/night-owl", f"reel/{BATCH}/paper-dragon"]
    v = by_slug(c.get(f"/api/batches/reel/{BATCH}/videos").json()["videos"])
    assert v["paper-dragon"]["acceptance"]["pending"] is False
    assert v["paper-dragon"]["acceptance"]["verdict"] == "accepted"


def test_a_commit_git_refuses_is_a_500_and_the_record_stays():
    root = tree()
    c = client(root)
    hooks = Path(git(root, "config", "core.hooksPath"))
    (hooks / "pre-commit").write_text("#!/bin/sh\necho no >&2\nexit 1\n")
    (hooks / "pre-commit").chmod(0o755)
    before = state(root)
    raw = (root / "publish" / "acceptance-log.json").read_bytes()
    r = _post(c, "paper-dragon", verdict="yes", words="paper-dragon - да")
    (hooks / "pre-commit").unlink()
    assert r.status_code == 500 and r.json()["code"] == "not_committed", r.text
    assert r.json()["message"] == factory.collect().acceptance().REFUSALS_RU["not_committed"]
    assert (root / "publish" / "acceptance-log.json").read_bytes() == raw
    assert state(root) == before


def test_the_api_s_codes_are_the_factory_s():
    """BatchProblem lists every acceptance refusal code the factory has (CF-0676)."""
    from api import app as app_mod
    assert set(app_mod.ACCEPTANCE_CODES) == set(factory.collect().acceptance().REFUSALS_RU)
    assert not hasattr(videos, "REFUSALS_RU") and not hasattr(videos, "_refusal_ru")


def test_redo_is_a_rejection_and_waits_for_the_queue():
    root = tree()
    c = client(root)
    words = "night-owl переделать, потому что концовка обрывается"
    r = _post(c, "night-owl", verdict="redo", words=words, reason="концовка обрывается",
              reason_code="tail_after_last_anchor")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["row"]["verdict"] == "rejected" and j["row"]["note"] == videos.REDO_NOTE
    assert j["row"]["answer"] == words and j["verdict"] == "redo"
    assert j["redo"] == {"queued": False, "reason": videos.REDO_NOT_YET, "request": None}
    # the seam of CC-0018: once set, the same press enqueues the request
    got = []
    videos.REDO_QUEUE = lambda root_, row, words_, reason: got.append(
        (str(root_), row["entry_id"], words_, reason)) or {"id": "rq-1"}
    try:
        r = _post(c, "paper-dragon", batch=f"rebuilds/{RB1}", verdict="redo",
                  words="paper-dragon переделать: шум в начале", reason="шум",
                  reason_code="noise")
    finally:
        videos.REDO_QUEUE = None
    assert r.status_code == 200, r.text
    assert r.json()["redo"] == {"queued": True, "reason": None, "request": {"id": "rq-1"}}
    assert got == [(str(root), f"reel/{RB1}/paper-dragon", "paper-dragon переделать: шум в начале",
                    "шум")], got
    assert sorted(x["entry_id"] for x in log_rows(root)) == \
        [f"reel/{BATCH}/night-owl", f"reel/{RB1}/paper-dragon"]


def test_nothing_writes_a_verdict_but_the_press():
    root = tree()
    c = client(root)
    p = root / "publish" / "acceptance-log.json"
    raw, mtime = p.read_bytes(), p.stat().st_mtime_ns
    for url in (f"/api/batches/reel/{BATCH}/videos", f"/api/batches/rebuilds/{RB1}/videos",
                f"/api/batches/reel/{BATCH}/videos/paper-dragon/card",
                f"/api/batches/reel/{BATCH}/videos/paper-dragon/mp4",
                f"/api/batches/reel/{BATCH}/videos/paper-dragon/preview"):
        assert c.get(url).status_code == 200, url
    assert p.read_bytes() == raw and p.stat().st_mtime_ns == mtime
    for f in sorted((ROOT / "api").glob("*.py")):
        tree_ = ast.parse(f.read_text(encoding="utf-8"))
        funcs = [n for n in ast.walk(tree_) if isinstance(n, ast.FunctionDef)]
        for name in ("record_and_commit", "record", "write_log", "commit_pending"):
            using = {fn.name for fn in funcs
                     if any(isinstance(a, ast.Attribute) and a.attr == name
                            for a in ast.walk(fn))}
            want = {"accept"} if f.name == "videos.py" and name == "record_and_commit" \
                else set()
            if f.name == "publish_net.py" and name == "record":
                # CC-0066: `studio_fields.record` - the Studio journal row, not a verdict
                # (tests/test_cc_api_publish_net.py pins it to these three)
                want = {"_record_check", "studio_record", "act"}
            if f.name == "studio_entry.py" and name == "record":
                # CC-0074: `studio_read.record` - the Studio read, not a verdict
                # (tests/test_cc_api_studio_entry.py pins it to the confirm)
                want = {"record"}
            if f.name == "app.py" and name == "record":
                # CC-0074: the route of `studio_entry.record` (inside create_app)
                want = {"create_app", "analytics_studio_record"}
            assert using == want, (f.name, name, using)


def test_the_pack_names_are_the_gate_s():
    """The names of the frame judge's pack are the gate's (scripts/frame_judge_gate.py)."""
    src = (ROOT / "scripts" / "frame_judge_gate.py").read_text(encoding="utf-8")
    assert f'PACK_DIRNAME = "{videos.PACK_DIRNAME}"' in src
    assert f'MANIFEST = "{videos.MANIFEST}"' in src
    assert str(factory.collect().card().CARD_DIR) == "work/publish-card"


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
