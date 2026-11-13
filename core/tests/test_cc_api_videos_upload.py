#!/usr/bin/env python3
"""CC-0096: a video of a batch's (or a rebuild's) list names its upload to
YouTube - `upload: {video_id, url, publish_day, publish_at, uploaded_at,
recorded_at, source} | null` - from `publish/uploads.json` through the
journal's own reader (`upload_records.uploads`), by the acceptance key
`<channel>/<batch_id>/<slug>`, never by slug.

In-process against a stand-in factory root in a temp dir
(`tests/test_cc_api_videos.py` `make_batch` over `test_cc_api_batches`
`factory_tree`). Nothing outside the temp dir is read or written; no network.

What is pinned:

* one slug (`delver`) up three times from three batches - a batch, its
  rebuild (`rebuilds/<ts>/delver`, as a rebuild's acceptance key is written)
  and another batch: each video gets its own row, the rebuild's inside its
  source's `rebuilds` too;
* a video with no upload, and one whose only row was replaced, is null;
* a row frozen under a former channel id (`old-reel/...`) is still the video's;
* a journal that does not parse, or is not the journal, is said - `uploads_error`,
  every `upload` null, the list still 200 and the acceptance untouched - with
  no absolute path; no journal at all is no error, every upload null;
* the reads write nothing; the contract has `VideoUpload` and `uploads_error`.
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

from test_cc_api_batches import _w, client, factory_tree    # noqa: E402
from test_cc_api_videos import make_batch                    # noqa: E402

from api import __main__ as cli                               # noqa: E402

B1, RB, B2, B3 = "2026-10-01T1313Z", "2026-10-05T1427Z", "2026-10-09T1208Z", "2026-10-11T0900Z"


def _row(entry, vid, day, source="backfill", **extra):
    ch, batch_id, slug = entry.split("/")
    return dict({"channel": "reel", "entry_id": entry, "batch_id": batch_id, "slug": slug,
                 "topic_id": f"t-{slug}", "video_id": vid,
                 "url": f"https://youtube.com/shorts/{vid}",
                 "publish_at": f"{day}T01:00:00+03:00", "publish_tz": "Europe/Moscow",
                 "publish_day": day, "note": f"publish/reel/{day}/{slug}.md",
                 "source": source, "recorded_at": f"{day}T00:00:00Z"}, **extra)


def tree():
    root = factory_tree()
    make_batch(root, "reel", B1, ("delver", "quiet"))
    make_batch(root, "rebuilds", RB, ("delver",),
               rebuild_of={"channel": "reel", "batch_id": B1, "path": f"pipeline/reel/{B1}"})
    make_batch(root, "reel", B2, ("delver", "swapped"))
    make_batch(root, "reel", B3, ("renamed",))
    _w(root / "publish" / "acceptance-log.json",
       {"note": "test", "task": "CF-0328", "acceptances": []})
    _w(root / "publish" / "uploads.json", {"note": "test", "task": "CF-0586", "format": 1,
                                           "uploads": [
        _row(f"reel/{B1}/delver", "AAAAAAAAAA1", "2026-10-02"),
        _row(f"rebuilds/{RB}/delver", "BBBBBBBBBB2", "2026-10-06", source="studio",
             user_edited=False),
        _row(f"reel/{B2}/delver", "CCCCCCCCCC3", "2026-10-10", source="api",
             uploaded_at="2026-10-09T20:15:00Z"),
        _row(f"reel/{B2}/swapped", "DDDDDDDDDD4", "2026-10-10", removed_at="2026-10-10T09:00Z",
             replaced_by="EEEEEEEEEE5"),
        _row(f"old-reel/{B3}/renamed", "FFFFFFFFFF6", "2026-10-12"),
    ]})
    return root


def _ups(j):
    return {v["slug"]: v["upload"] for v in j["videos"]}


def test_one_slug_up_three_times_each_video_its_own():
    root = tree()
    before = (root / "publish" / "uploads.json").read_bytes()
    c = client(root)
    r = c.get(f"/api/batches/reel/{B1}/videos")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["uploads_error"] is None, j["uploads_error"]
    u = _ups(j)
    assert u["delver"] == {"video_id": "AAAAAAAAAA1",
                           "url": "https://youtube.com/shorts/AAAAAAAAAA1",
                           "publish_day": "2026-10-02",
                           "publish_at": "2026-10-02T01:00:00+03:00", "uploaded_at": None,
                           "recorded_at": "2026-10-02T00:00:00Z", "source": "backfill",
                           "withdrawn": None}, u
    assert u["quiet"] is None, u
    # the rebuild beside its source, and on its own route: its own row
    [rb] = j["rebuilds"]
    assert rb["batch"] == f"rebuilds/{RB}"
    assert rb["videos"][0]["upload"]["video_id"] == "BBBBBBBBBB2", rb["videos"][0]
    assert rb["videos"][0]["upload"]["source"] == "studio"
    j = c.get(f"/api/batches/rebuilds/{RB}/videos").json()
    assert _ups(j)["delver"]["video_id"] == "BBBBBBBBBB2", j
    # the other batch's delver
    j = c.get(f"/api/batches/reel/{B2}/videos").json()
    u = _ups(j)
    assert u["delver"]["video_id"] == "CCCCCCCCCC3" and u["delver"]["source"] == "api"
    assert u["delver"]["uploaded_at"] == "2026-10-09T20:15:00Z", u["delver"]
    assert u["swapped"] is None, "a replaced row is no upload of the video"
    # a row frozen under a former channel id
    j = c.get(f"/api/batches/reel/{B3}/videos").json()
    assert _ups(j)["renamed"]["video_id"] == "FFFFFFFFFF6", j
    assert (root / "publish" / "uploads.json").read_bytes() == before, "read only"


def test_a_journal_that_does_not_read_is_said_and_the_list_stays():
    root = tree()
    c = client(root)
    j = (root / "publish" / "uploads.json")
    for text, word in (("{broken", "JSONDecodeError"), (json.dumps({"rows": []}), "JournalError")):
        j.write_text(text, encoding="utf-8")
        r = c.get(f"/api/batches/reel/{B1}/videos")
        assert r.status_code == 200, r.text
        got = r.json()
        err = got["uploads_error"]
        assert err and "publish/uploads.json не читается" in err and word in err, err
        assert all(v["upload"] is None for v in got["videos"])
        assert all(v["upload"] is None for b in got["rebuilds"] for v in b["videos"])
        assert got["acceptance_error"] is None and got["videos"][0]["acceptance"]
        assert str(root) not in r.text and str(root.resolve()) not in r.text, err
        assert j.read_text(encoding="utf-8") == text
    j.unlink()
    got = c.get(f"/api/batches/reel/{B1}/videos").json()
    assert got["uploads_error"] is None and all(v["upload"] is None for v in got["videos"])


def test_the_contract_has_the_upload():
    spec = json.loads(cli.openapi_text())
    s = spec["components"]["schemas"]
    assert set(s["VideoUpload"]["properties"]) == {
        "video_id", "url", "publish_day", "publish_at", "uploaded_at", "recorded_at", "source",
        "withdrawn"}
    assert s["VideoUpload"]["required"] == ["video_id"]
    assert "upload" in s["Video"]["properties"] and "upload" not in s["Video"].get("required", [])
    assert "uploads_error" in s["BatchVideos"]["properties"]
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
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
