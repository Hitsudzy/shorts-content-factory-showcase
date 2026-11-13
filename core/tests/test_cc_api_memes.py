#!/usr/bin/env python3
"""CC-0024: the meme desk of the center (`api/memes.py`) - review a channel's
meme bank through the factory's desk functions (CF-0693):

    GET  /api/memes                               the channels, their banks, the counts
    GET  /api/memes/{c}                           desk_state + fingerprints + media urls
    GET  /api/memes/{c}/{id}/media?kind=file|cut  the file inside the bank, HTTP Range
    GET  /api/memes/{c}/{id}/thumb                thumb() (a cached JPEG / the GIF)
    PUT  /api/memes/{c}/marks                     save_marks(by user, via center), `base`
    POST /api/memes/{c}/apply/plan                plan_apply + a confirm token
    POST /api/memes/{c}/apply                     the same fingerprint, then apply_marks

In-process (starlette's TestClient) against stand-in factory roots in a temp
dir (`tests/test_cc_api_batches.py` `factory_tree`) with two temp banks - the
default `shared/inserts/memes/` (Reel, Demo) and `memes-tech/` (Tech) - tiny
media made here, the checkout's `inserts/meme.json` copied in. The real banks
are never opened; no network, no ffmpeg (a thumbnail is a cached one or a GIF).

What is pinned: the overview's counts per channel and a bank that does not
open as that row's error; the desk as desk_state says it, with fingerprints;
media served with Range (206, 416), a cut-out, a path out of the bank refused
(`..`, absolute, a link out) - for `thumb` too; in a linked worktree (the
bank's media and `_desk/` links `agents sync` declared) `media` and `thumb`
both served, a `_desk` linked elsewhere refused (CC-0078); the marks saved whole with the center's stamp,
a stale `base` refused and nothing written, the desk's refusals with their
codes and Russian text (the factory's own `outside_bank` a 404, CC-0080); the plan writes nothing, the confirm applies it; a
token spent, expired, of another channel; a bank changed between plan and
confirm is `check_changed`; an invalid index gets no token; a read-only copy
refuses every write before the factory; the contract.
"""
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ.pop("ACCEPTANCE_LOG", None)
os.environ.pop("BATCH_SCHEDULE_STATE_DIR", None)

from test_cc_api_batches import H, _w, client, factory_tree, git    # noqa: E402
from test_cc_api_publish import files                                # noqa: E402

from api import batches, factory, memes                              # noqa: E402


def desk():
    return factory.meme_desk()


def lib():
    return desk().lib


def leader():
    return next(iter(desk().leaders_of(None, ROOT)))


def _png(path, w=40, h=30):
    from PIL import Image
    Image.new("RGB", (w, h), "red").save(path)


def _gif(path):
    from PIL import Image
    Image.new("RGB", (40, 30), "blue").save(path, format="GIF")


def entry(eid, file, **over):
    e = {"id": eid, "file": file, "kind": "meme", "description": f"synthetic meme {eid}",
         "tags": ["x", "y"], "source_url": f"https://example.org/{file}", "added": "2026-10-12"}
    e.update(over)
    return e


CUT = {"source_sha256": "0" * 64, "method": "vision", "made": "2026-10-12", "coverage": 0.3}


def _index(inserts, entries, bank=None):
    idx = lib().empty_index("meme")
    idx["entries"] = entries
    lib().save_index(idx, "meme", inserts, bank)


def _draft(folder, dec):
    _w(folder / "_desk" / "decisions.json",
       json.dumps(dec, ensure_ascii=False, indent=1, sort_keys=True))


def world():
    """A factory root with channels reel (the default bank), demo (no layer -
    the default bank too), tech (its own `memes-tech`) and lost (a bank not on
    disk); the banks with a few entries and tiny media."""
    root = factory_tree()
    shutil.copy(ROOT / "inserts" / "meme.json", _w(root / "inserts" / "meme.json", "{}"))
    _w(root / "channels" / "tech.json", {"channel_id": "tech", "display_name": "Tech",
                                         "insert_layers": {"meme": {
                                             "enabled": False,
                                             "bank": "shared/inserts/memes-tech/"}}})
    _w(root / "channels" / "lost.json", {"channel_id": "lost", "display_name": "Lost",
                                         "insert_layers": {"meme": {
                                             "bank": "shared/inserts/memes-lost/"}}})
    inserts = root / "shared" / "inserts"
    reel = inserts / "memes"
    reel.mkdir(parents=True)
    lead = leader()
    entries = [entry("new-keep", "new-keep.png", review="pending"),
               entry("new-drop", "new-drop.png", review="pending"),
               entry("old-one", "old-one.png"),
               entry(lead, "leader.png"),
               entry("old-cut", "old-cut.png", cutout=True,
                     cutout_asset=dict(CUT, file="old-cut.cutout.png", bbox_px=[0, 0, 40, 30])),
               entry("refused-cut", "refused-cut.png", cutout=True,
                     cutout_asset=dict(CUT, file=None, refused="two figures")),
               entry("a-gif", "a-gif.gif", clip={"start_s": 1.0, "end_s": 2.0})]
    for e in entries:
        (_gif if e["file"].endswith(".gif") else _png)(reel / e["file"])
    _png(reel / "old-cut.cutout.png")
    _index(inserts, entries)
    _draft(reel, {"new-keep": {"v": "keep"}, "new-drop": {"v": "drop"}, lead: {"v": "drop"},
                  "old-cut": {"cut": False, "note": "слишком пёстрый"}, "gone": {"v": "drop"}})
    tech = inserts / "memes-tech"
    tech.mkdir()
    t_entries = [entry("tech-new", "tech-new.png", review="pending"),
                 entry("tech-old", "tech-old.png")]
    for e in t_entries:
        _png(tech / e["file"], 64, 64)
    _index(inserts, t_entries, "memes-tech")
    return root


def get(c, path, **params):
    r = c.get(path, params=params)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.content


#: CC-0134: what the center's own `notes` / `why` of a plan never say - a
#: path of the bank, a word of the code («эмбеддинг», «потолок»).
JARGON = ("_desk", "эмбеддинг", "потолк")
PLAIN_NOT = ("review:", "yt-dlp", "кэш")


def plain_words(p):
    """The center's own words of a plan (`notes`, `why` without the factory's
    texts it quotes: available_reason, refused[].text, errors) - no JARGON,
    and a dash is «\u00a0—», never « - » or « —»."""
    if not isinstance(p, dict):
        return
    theirs = [p.get("available_reason")] + list(p.get("errors") or []) + \
             [r.get("text") for r in p.get("refused") or [] if isinstance(r, dict)]
    why = p.get("why") or ""
    for t in theirs:
        if isinstance(t, str) and t:
            why = why.replace(t, "")
    notes = p.get("notes") if isinstance(p.get("notes"), list) else []
    for text in notes + [why]:
        low = text.lower()
        assert not any(w in low for w in JARGON), ("jargon", text)
        assert " - " not in text and " —" not in text, ("dash", text)
        # CC-0136: no field values, tool names, the cache, a decimal dot or a file name
        assert not any(w in low for w in PLAIN_NOT), ("plain", text)
        assert not re.search(r"\d\.\d", text), ("decimal dot", text)
        assert not re.search(r"\.(jpe?g|png|gif|mp4|webp)\b", low), ("file name", text)


def send(c, method, path, body=None):
    r = c.request(method, path, headers=H, json=body if body is not None else {})
    out = r.json()
    if path.split("?")[0].endswith("/plan"):
        plain_words(out)
    return r.status_code, out


def draft(root, bank="memes"):
    p = root / "shared" / "inserts" / bank / "_desk" / "decisions.json"
    return json.loads(p.read_text()) if p.exists() else None


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# --------------------------------------------------------------------- reading
def test_overview_counts_each_channels_bank():
    root = world()
    before = files(root)
    code, r = get(client(root), "/api/memes")
    assert code == 200, r
    rows = {x["channel"]: x for x in r["channels"]}
    assert set(rows) == {"reel", "demo", "tech", "lost"}, rows
    reel = rows["reel"]
    assert (reel["bank"], reel["default_bank"], reel["entries"], reel["pending"], reel["keep"],
            reel["drop"], reel["cut_diff"], reel["stale"], reel["error"]) == \
        ("memes", True, 7, 2, 1, 2, 1, 1, None), reel
    assert {k: v for k, v in rows["demo"].items() if k != "channel"} == \
        {k: v for k, v in reel.items() if k != "channel"}, rows["demo"]   # the same bank
    tech = rows["tech"]
    assert (tech["bank"], tech["default_bank"], tech["layer_enabled"], tech["entries"],
            tech["pending"], tech["keep"]) == ("memes-tech", False, False, 2, 1, 0), tech
    lost = rows["lost"]
    assert lost["bank"] is None and lost["error"]["code"] == "bad_bank", lost
    assert lost["error"]["message"].startswith("банк мемов недоступен"), lost
    assert files(root) == before                                          # nothing written


def test_state_is_desk_state_with_fingerprints_and_urls():
    root = world()
    before = files(root)
    code, s = get(client(root), "/api/memes/reel")
    assert code == 200, s
    want = desk().desk_state("reel", root=root / "shared" / "inserts", repo=root)
    assert (s["bank"], s["default_bank"], s["channel"]) == ("memes", True, "reel"), s
    assert s["folder"] == "shared/inserts/memes", s["folder"]
    # the contract's nullable notes are null when the desk had Pillow and gave none
    got_status = {k: v for k, v in s["status"].items()
                  if not (k in ("blank_bands_note", "blank_bands_note_en") and v is None)}
    assert s["decisions"] == want["decisions"] and got_status == want["status"], s
    assert [{k: v for k, v in e.items() if k != "urls"} for e in s["entries"]] == \
        want["entries"]
    assert s["fingerprint"] == sha(root / "shared/inserts/memes/_desk/decisions.json")
    assert s["index_fingerprint"] == sha(root / "shared/inserts/memes/index.json")
    by = {e["id"]: e for e in s["entries"]}
    assert by["old-cut"]["urls"] == {"file": "/api/memes/reel/old-cut/media?kind=file",
                                     "cut": "/api/memes/reel/old-cut/media?kind=cut",
                                     "thumb": "/api/memes/reel/old-cut/thumb"}, by["old-cut"]
    assert by["refused-cut"]["urls"]["cut"] is None and \
        by["refused-cut"]["cut_refused"] == "two figures"
    # CF-0762: the record's English line beside the Russian one (an unknown
    # refusal is shown as recorded in both)
    assert by["refused-cut"]["cut_refused_en"] == "two figures", by["refused-cut"]
    assert all("cut_refused_en" in e for e in s["entries"]), s["entries"]
    assert by["a-gif"]["gif"] is True and by["a-gif"]["clip"] == {"start_s": 1.0, "end_s": 2.0}
    assert files(root) == before
    # Tech: its own bank, no draft yet
    code, t = get(client(root), "/api/memes/tech")
    assert code == 200 and t["bank"] == "memes-tech" and t["fingerprint"] is None, t
    assert t["status"]["pending"] == ["tech-new"], t["status"]


def test_unknown_channel_and_a_bank_that_does_not_open():
    root = world()
    c = client(root)
    code, r = get(c, "/api/memes/nope")
    assert code == 404 and r["code"] == "unknown_channel", r
    code, r = get(c, "/api/memes/lost")
    assert code == 409 and r["code"] == "bad_bank", r
    assert r["message"].startswith("банк мемов недоступен") and r["details"], r


# --------------------------------------------------------------------- media
def test_media_is_served_with_range():
    root = world()
    c = client(root)
    body = (root / "shared/inserts/memes/new-keep.png").read_bytes()
    r = c.get("/api/memes/reel/new-keep/media")
    assert r.status_code == 200 and r.content == body, r.status_code
    assert r.headers["content-type"] == "image/png" and r.headers["accept-ranges"] == "bytes"
    r = c.get("/api/memes/reel/new-keep/media", headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and r.content == body[:10], r.status_code
    assert r.headers["content-range"] == f"bytes 0-9/{len(body)}", r.headers
    r = c.get("/api/memes/reel/new-keep/media", headers={"Range": f"bytes={len(body) + 5}-"})
    assert r.status_code == 416, r.status_code
    r = c.get("/api/memes/reel/a-gif/media")
    assert r.status_code == 200 and r.headers["content-type"] == "image/gif"
    r = c.get("/api/memes/reel/old-cut/media", params={"kind": "cut"})
    assert r.status_code == 200 and \
        r.content == (root / "shared/inserts/memes/old-cut.cutout.png").read_bytes()
    code, r = get(c, "/api/memes/reel/refused-cut/media", kind="cut")
    assert code == 404 and r["code"] == "no_cut" and "two figures" in r["message"], r
    code, r = get(c, "/api/memes/reel/nobody/media")
    assert code == 404 and r["code"] == "unknown_id", r
    code, r = get(c, "/api/memes/reel/new-keep/media", kind="clip")
    assert code == 422, r
    (root / "shared/inserts/memes/old-one.png").unlink()
    code, r = get(c, "/api/memes/reel/old-one/media")
    assert code == 404 and r["code"] == "no_file", r
    # Tech's file is Tech's: the same id is not looked up in another bank
    code, r = get(c, "/api/memes/tech/new-keep/media")
    assert code == 404 and r["code"] == "unknown_id", r


def test_a_path_out_of_the_bank_is_refused():
    root = world()
    inserts = root / "shared" / "inserts"
    secret = _w(root / "secret.txt", "not a meme")
    outside = root.parent / f"{root.name}-outside.png"
    _png(outside)
    (inserts / "memes-tech" / "linked.png").symlink_to(outside)
    out_gif = root.parent / f"{root.name}-outside.gif"
    _gif(out_gif)
    shutil.copy(out_gif, root / "secret.gif")
    (inserts / "memes-tech" / "linked.gif").symlink_to(out_gif)
    _index(inserts, [entry("up", "../../../secret.txt"), entry("abs", str(secret)),
                     entry("linked", "linked.png"), entry("up-gif", "../../../secret.gif"),
                     entry("linked-gif", "linked.gif")], "memes-tech")
    c = client(root)
    for mid in ("up", "abs", "linked"):
        r = c.get(f"/api/memes/tech/{mid}/media")
        assert r.status_code == 404 and r.json()["code"] == "outside_bank", (mid, r.text)
        assert b"not a meme" not in r.content
    # CC-0078: thumb() hands back the GIF's own path - the same guard as the
    # media: `..` normalized out of the bank, an undeclared link out, refused
    gif = out_gif.read_bytes()
    for mid in ("up-gif", "linked-gif"):
        r = c.get(f"/api/memes/tech/{mid}/thumb")
        assert r.status_code == 404 and r.json()["code"] == "outside_bank", (mid, r.text)
        assert r.content != gif
    # an id that is not the bank's entry never reaches a path
    r = c.get("/api/memes/tech/..%2F..%2Fsecret.gif/thumb")
    assert r.status_code == 404 and r.content != gif, r.text


def test_a_linked_worktree_serves_media_and_thumb():
    """CC-0078: in a worktree `scripts/agents sync` links the bank's media and
    `_desk/` to the working copy's same bank (`links.root`
    `shared/inserts/*/*`) - `media` and `thumb` both serve them; a `_desk`
    linked anywhere else is still `outside_bank`."""
    wc = world()
    _w(wc / "agents.lock.json", {"agents": {"x": {"path": "agents/x", "rev": "main"}},
                                 "links": {"root": ["shared/inserts/*/*"]}})
    _w(wc / ".gitignore", "/schedule/\n/shared/inserts/memes-tech/*.png\n"
                          "/shared/inserts/memes-tech/_desk/\n")
    tech = wc / "shared" / "inserts" / "memes-tech"
    jpg = _w(tech / "_desk" / "thumbs" / "tech-old.jpg", "cached jpeg")
    os.utime(jpg, (os.stat(tech / "tech-old.png").st_mtime + 10,) * 2)
    git(wc, "add", "-A")
    git(wc, "commit", "-q", "-m", "the bank and the lock")
    wt = wc.parent / f"{wc.name}-wt"
    git(wc, "worktree", "add", "-q", "-b", f"{wc.name}-wt", str(wt))
    bank = wt / "shared" / "inserts" / "memes-tech"
    assert (bank / "index.json").is_file() and not (bank / "_desk").exists()
    for name in ("tech-new.png", "tech-old.png", "_desk"):          # as sync makes them
        (bank / name).symlink_to(tech / name)
    assert factory.declared_link(wt, "shared/inserts/memes-tech/_desk")
    c = client(wt)
    r = c.get("/api/memes/tech/tech-new/media")
    assert r.status_code == 200 and r.content == (tech / "tech-new.png").read_bytes(), r.text
    r = c.get("/api/memes/tech/tech-old/thumb")
    assert r.status_code == 200 and r.content == b"cached jpeg", r.text
    # a `_desk` linked to somewhere that is not the working copy's same bank
    other = wc.parent / f"{wc.name}-other-desk"
    _w(other / "thumbs" / "tech-old.jpg", "planted jpeg")
    os.utime(other / "thumbs" / "tech-old.jpg", (os.stat(jpg).st_mtime,) * 2)
    (bank / "_desk").unlink()
    (bank / "_desk").symlink_to(other)
    assert not factory.declared_link(wt, "shared/inserts/memes-tech/_desk")
    r = c.get("/api/memes/tech/tech-old/thumb")
    assert r.status_code == 404 and r.json()["code"] == "outside_bank", r.text
    assert r.content != b"planted jpeg"


def test_thumb_is_the_factorys_cached_jpeg_or_the_gif():
    root = world()
    c = client(root)
    reel = root / "shared" / "inserts" / "memes"
    r = c.get("/api/memes/reel/a-gif/thumb")
    assert r.status_code == 200 and r.content == (reel / "a-gif.gif").read_bytes()
    # a fresh cached thumbnail: thumb() hands it back without ffmpeg
    jpg = _w(reel / "_desk" / "thumbs" / "new-keep.jpg", "jpeg bytes")
    os.utime(jpg, (os.stat(reel / "new-keep.png").st_mtime + 10,) * 2)
    r = c.get("/api/memes/reel/new-keep/thumb")
    assert r.status_code == 200 and r.content == b"jpeg bytes", r.status_code
    assert r.headers["content-type"] == "image/jpeg"
    code, r = get(c, "/api/memes/reel/nobody/thumb")
    assert code == 404 and r["code"] == "unknown_id" and "нет в банке" in r["message"], r
    d = desk()
    real = d._make_thumb
    d._make_thumb = lambda src, out: False
    try:
        code, r = get(c, "/api/memes/reel/old-one/thumb")
    finally:
        d._make_thumb = real
    assert code == 500 and r["code"] == "thumb_failed", r
    assert r["message"] == "миниатюра old-one не сделана (ffmpeg)", r


def test_the_factorys_own_outside_bank_is_404():
    """CC-0080: since CF-0697 the factory's desk itself refuses media outside
    the bank (`MemeDeskError("outside_bank")`) - on `thumb()` that reaches the
    client as 404 with the factory's code and Russian text, the same status as
    the API's own guard, not the 409 of an unmapped code."""
    root = world()
    c = client(root)
    d = desk()
    real = d.thumb
    calls = []

    def refuse(*a, **k):
        calls.append(a)
        raise d.MemeDeskError("outside_bank", "медиа old-one лежит вне банка",
                              "old-one: media outside the bank")
    d.thumb = refuse
    try:
        code, r = get(c, "/api/memes/reel/old-one/thumb")
    finally:
        d.thumb = real
    assert calls, "the factory's thumb() was not called"
    assert code == 404, (code, r)
    assert set(r) == {"message", "code", "details"}, r
    assert r["code"] == "outside_bank" and r["message"] == "медиа old-one лежит вне банка", r
    assert r["details"] == ["MemeDeskError(outside_bank): old-one: media outside the bank"], r
    assert memes._fault(d.MemeDeskError("outside_bank", "x")).status == 404


# --------------------------------------------------------------------- the marks
def test_marks_are_saved_whole_with_the_centers_stamp():
    root = world()
    c = client(root)
    _, s = get(c, "/api/memes/reel")
    dec = dict(s["decisions"])
    dec.pop("gone")
    dec["old-one"] = {"v": "drop", "note": "устарел"}
    code, r = send(c, "PUT", "/api/memes/reel/marks", {"decisions": dec,
                                                       "base": s["fingerprint"]})
    assert code == 200, r
    assert (r["channel"], r["saved"], r["bank"]) == ("reel", len(dec), "memes"), r
    saved = draft(root)
    assert r["fingerprint"] == sha(root / "shared/inserts/memes/_desk/decisions.json")
    assert "gone" not in saved
    assert (saved["old-one"]["v"], saved["old-one"]["marked_by"], saved["old-one"]["via"]) == \
        ("drop", "user", "center"), saved["old-one"]
    assert saved["new-keep"] == {"v": "keep"}, saved["new-keep"]       # unchanged: no stamp
    # the next save chains on the returned fingerprint
    dec["new-keep"] = {"v": "drop"}
    code, r2 = send(c, "PUT", "/api/memes/reel/marks", {"decisions": dec,
                                                        "base": r["fingerprint"]})
    assert code == 200 and draft(root)["new-keep"]["via"] == "center", r2
    # Tech has no draft yet: base null
    code, r = send(c, "PUT", "/api/memes/tech/marks",
                   {"decisions": {"tech-new": {"v": "keep", "cut": True}}, "base": None})
    assert code == 200 and draft(root, "memes-tech")["tech-new"]["v"] == "keep", r
    assert draft(root) == json.loads((root / "shared/inserts/memes/_desk/decisions.json")
                                     .read_text())


def test_a_stale_base_is_refused_and_nothing_written():
    root = world()
    c = client(root)
    _, s = get(c, "/api/memes/reel")
    p = root / "shared/inserts/memes/_desk/decisions.json"
    other = dict(s["decisions"], **{"old-one": {"v": "keep"}})          # the terminal's desk
    p.write_text(json.dumps(other))
    before = p.read_bytes()
    code, r = send(c, "PUT", "/api/memes/reel/marks", {"decisions": {}, "base": s["fingerprint"]})
    assert code == 409 and r["code"] == "check_changed", r
    assert "не сохранены" in r["message"], r
    assert p.read_bytes() == before
    # no draft seen, but there is one now
    code, r = send(c, "PUT", "/api/memes/reel/marks", {"decisions": {}, "base": None})
    assert code == 409 and r["code"] == "check_changed", r
    # base is required
    code, r = send(c, "PUT", "/api/memes/reel/marks", {"decisions": {}})
    assert code == 422, r
    assert p.read_bytes() == before


def test_the_desks_refusals_reach_the_client_with_its_code():
    root = world()
    c = client(root)
    _, s = get(c, "/api/memes/reel")
    before = files(root)
    for dec, code_, want in (
            ({"new-keep": {"v": "maybe"}}, 422, "bad_decisions"),
            ({"new-keep": {"cut": "yes"}}, 422, "bad_decisions"),
            ({"new-keep": {"v": "keep", "colour": "red"}}, 422, "bad_decisions"),
            ({"nobody": {"v": "keep"}}, 422, "unknown_id")):
        code, r = send(c, "PUT", "/api/memes/reel/marks", {"decisions": dec,
                                                           "base": s["fingerprint"]})
        assert (code, r["code"]) == (code_, want), (dec, r)
        assert r["details"][0].startswith(f"MemeDeskError({want})"), r
    code, r = send(c, "PUT", "/api/memes/reel/marks",
                   {"decisions": {"nobody": {"v": "keep"}}, "base": s["fingerprint"]})
    assert r["message"] == "мема 'nobody' нет в банке", r
    assert files(root) == before


# --------------------------------------------------------------------- apply
def test_plan_writes_nothing_and_the_confirm_applies_it():
    root = world()
    c = client(root)
    before = files(root)
    code, plan = send(c, "POST", "/api/memes/reel/apply/plan")
    assert code == 200, plan
    assert files(root) == before                                        # nothing written
    assert (plan["action"], plan["channel"], plan["ok"], plan["why"], plan["bank"],
            plan["drop"]) == ("meme_apply", "reel", True, None, "memes", False), plan
    assert plan["confirm"] and plan["expires_in_s"] == int(batches.CONFIRM_TTL), plan
    assert plan["accept"] == ["new-keep"] and plan["remove"] == ["new-drop"], plan
    assert plan["refused"] == [], plan              # an accepted entry stays without drop
    assert plan["cutout_changed"] == ["old-cut"], plan
    assert sorted(plan["files_to_delete"]) == ["new-drop.png", "old-cut.cutout.png"], plan
    assert plan["errors"] == [] and plan["held"] == [], plan
    want = desk().plan_apply("reel", root=root / "shared" / "inserts", repo=root)
    assert {k: plan[k] for k in want} == want
    code, r = send(c, "POST", "/api/memes/reel/apply", {"confirm": plan["confirm"]})
    assert code == 200, r
    assert r["written"] is True and r["accept"] == ["new-keep"] and r["remove"] == ["new-drop"]
    reel = root / "shared" / "inserts" / "memes"
    idx = {e["id"]: e for e in json.loads((reel / "index.json").read_text())["entries"]}
    assert "new-drop" not in idx and "review" not in idx["new-keep"], idx
    assert idx["old-cut"]["cutout"] is False and "cutout_asset" not in idx["old-cut"]
    assert not (reel / "new-drop.png").exists() and not (reel / "old-cut.cutout.png").exists()
    assert "new-drop" not in draft(root)
    assert r["decisions_fingerprint"] == sha(reel / "_desk" / "decisions.json")
    assert r["index_fingerprint"] == sha(reel / "index.json")
    # the token is spent
    code, r = send(c, "POST", "/api/memes/reel/apply", {"confirm": plan["confirm"]})
    assert code == 409 and r["code"] == "confirm_unknown", r


def committed_world():
    """CC-0156: the world committed as the factory's .gitignore keeps a bank -
    its index.json and candidates.json tracked, the media and _desk/ ignored."""
    root = world()
    gi = root / ".gitignore"
    gi.write_text(gi.read_text(encoding="utf-8") + "shared/inserts/*/*\n"
                  "!shared/inserts/*/index.json\n!shared/inserts/*/candidates.json\n",
                  encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the banks")
    assert git(root, "status", "--porcelain", "--untracked-files=all") == ""
    return root


def test_the_apply_is_committed_and_the_tree_stays_clean():
    """CC-0156: apply wrote <bank>/index.json and left it uncommitted. Now one
    commit of exactly the index, Cc-Channel / Cc-Action: meme_apply; a stray
    edit of another bank's index stays out."""
    root = committed_world()
    stray = root / "shared" / "inserts" / "memes-tech" / "index.json"
    stray.write_text(stray.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    h = git(root, "rev-parse", "HEAD")
    c = client(root)
    code, plan = send(c, "POST", "/api/memes/reel/apply/plan")
    code, r = send(c, "POST", "/api/memes/reel/apply", {"confirm": plan["confirm"]})
    assert code == 200, r
    assert git(root, "rev-parse", "HEAD~1") == h, "one commit on top"
    assert git(root, "show", "--name-only", "--format=", "HEAD") == \
        "shared/inserts/memes/index.json"
    assert git(root, "status", "--porcelain", "--untracked-files=all") == \
        "M shared/inserts/memes-tech/index.json"
    msg = git(root, "log", "-1", "--format=%B")
    assert msg.startswith("Мемы reel: отметки применены (user, center)"), msg
    assert "Cc-Channel: reel" in msg and "Cc-Action: meme_apply" in msg, msg
    assert "Приняты: new-keep" in msg, msg


def test_an_apply_git_refuses_is_refused_and_nothing_stays_staged():
    root = committed_world()
    h = git(root, "rev-parse", "HEAD")
    hooks = root.parent / f"refusing-hooks-memes-{root.name}"
    hooks.mkdir()
    (hooks / "pre-commit").write_text("#!/bin/sh\necho no >&2\nexit 1\n", encoding="utf-8")
    (hooks / "pre-commit").chmod(0o755)
    git(root, "config", "core.hooksPath", str(hooks))
    c = client(root)
    code, plan = send(c, "POST", "/api/memes/reel/apply/plan")
    code, r = send(c, "POST", "/api/memes/reel/apply", {"confirm": plan["confirm"]})
    assert code == 409 and r["code"] == "refused", r
    assert "commit_refused" in r["details"], r["details"]
    assert git(root, "rev-parse", "HEAD") == h, "no commit"
    assert git(root, "diff", "--cached", "--name-only") == "", "nothing left staged"
    assert git(root, "status", "--porcelain") == "M shared/inserts/memes/index.json"


def test_drop_is_bound_to_the_token():
    root = world()
    c = client(root)
    _, s = get(c, "/api/memes/reel")
    # a stale mark (an id no longer in the bank) is the desk's unknown_id - the
    # screen leaves status.stale out of the draft it saves
    dec = dict(s["decisions"], **{"old-one": {"v": "drop"}})
    code, r = send(c, "PUT", "/api/memes/reel/marks", {"decisions": dec, "base": s["fingerprint"]})
    assert code == 422 and r["code"] == "unknown_id", r
    dec = {k: v for k, v in dec.items() if k not in s["status"]["stale"]}
    code, r = send(c, "PUT", "/api/memes/reel/marks", {"decisions": dec, "base": s["fingerprint"]})
    assert code == 200, r
    _, plan = send(c, "POST", "/api/memes/reel/apply/plan")
    assert plan["held"] == ["old-one"] and "old-one" not in plan["remove"], plan
    code, plan = send(c, "POST", "/api/memes/reel/apply/plan", {"drop": True})
    assert code == 200 and plan["drop"] is True and "old-one" in plan["remove"], plan
    lead = leader()
    assert plan["refused"] == [{"id": lead, "intent": desk().leaders_of(None, ROOT)[lead]}]
    code, r = send(c, "POST", "/api/memes/reel/apply", {"confirm": plan["confirm"]})
    assert code == 200 and "old-one" in r["remove"] and r["drop"] is True, r
    assert not (root / "shared/inserts/memes/old-one.png").exists()


def test_tokens_expired_of_another_channel_and_a_changed_bank():
    root = world()
    c = client(root)
    reel = root / "shared" / "inserts" / "memes"
    # expired
    _, plan = send(c, "POST", "/api/memes/reel/apply/plan")
    real = batches._clock
    batches._clock = lambda: real() + batches.CONFIRM_TTL + 1
    try:
        before = files(root)
        code, r = send(c, "POST", "/api/memes/reel/apply", {"confirm": plan["confirm"]})
    finally:
        batches._clock = real
    assert code == 409 and r["code"] == "confirm_expired", r
    assert files(root) == before
    # of another channel
    _, plan = send(c, "POST", "/api/memes/tech/apply/plan")
    code, r = send(c, "POST", "/api/memes/reel/apply", {"confirm": plan["confirm"]})
    assert code == 409 and r["code"] == "confirm_mismatch", r
    assert files(root) == before
    # the draft changed between plan and confirm
    _, plan = send(c, "POST", "/api/memes/reel/apply/plan")
    _draft(reel, {"new-keep": {"v": "drop"}})
    before = files(root)
    code, r = send(c, "POST", "/api/memes/reel/apply", {"confirm": plan["confirm"]})
    assert code == 409 and r["code"] == "check_changed" and "не применены" in r["message"], r
    assert files(root) == before
    # the index changed between plan and confirm
    _, plan = send(c, "POST", "/api/memes/reel/apply/plan")
    p = reel / "index.json"
    p.write_text(p.read_text() + "\n")
    before = files(root)
    code, r = send(c, "POST", "/api/memes/reel/apply", {"confirm": plan["confirm"]})
    assert code == 409 and r["code"] == "check_changed", r
    assert files(root) == before
    code, r = send(c, "POST", "/api/memes/reel/apply", {"confirm": "made-up"})
    assert code == 409 and r["code"] == "confirm_unknown", r


def test_an_invalid_index_gets_no_token():
    root = world()
    inserts = root / "shared" / "inserts"
    _index(inserts, [entry("tech-new", "tech-new.png", review="pending"),
                     entry("tech-twin", "tech-new.png")], "memes-tech")
    c = client(root)
    before = files(root)
    code, plan = send(c, "POST", "/api/memes/tech/apply/plan")
    assert code == 200 and plan["ok"] is False and plan["confirm"] is None, plan
    assert plan["errors"] and plan["why"].startswith("Применить нельзя"), plan
    assert files(root) == before


def test_a_read_only_copy_refuses_every_write_before_the_factory():
    root = world()
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the banks")
    wt = root.parent / f"wt-{root.name}-memes"
    git(root, "worktree", "add", "-q", "-b", "dev-memes", str(wt))
    called = []
    saved = {n: getattr(memes, n) for n in ("save", "apply_plan", "apply")}
    for n in saved:
        setattr(memes, n, lambda *a, _n=n, **k: called.append(_n))
    c = client(wt)
    before = files(wt)
    try:
        for m, path, body in (("PUT", "/api/memes/reel/marks", {"decisions": {}, "base": None}),
                              ("POST", "/api/memes/reel/apply/plan", {}),
                              ("POST", "/api/memes/reel/apply", {"confirm": "x"})):
            code, r = send(c, m, path, body)
            assert code == 409 and r["code"] == "not_working_factory", (path, r)
        assert get(c, "/api/memes/reel")[0] == 200                      # reading is fine
    finally:
        for n, f in saved.items():
            setattr(memes, n, f)
    assert called == []
    assert files(wt) == before


# --------------------------------------------------------------------- the contract
ROUTES = {"/api/memes": {"get"}, "/api/memes/{channel}": {"get"},
          "/api/memes/{channel}/{meme_id}/media": {"get"},
          "/api/memes/{channel}/{meme_id}/thumb": {"get"},
          "/api/memes/{channel}/candidates": {"get"},       # CC-0103, read only
          # CC-0114: the candidates' yes
          "/api/memes/{channel}/candidates/accept/plan": {"post"},
          "/api/memes/{channel}/candidates/accept": {"post"},
          "/api/memes/{channel}/marks": {"put"},
          "/api/memes/{channel}/apply/plan": {"post"},
          "/api/memes/{channel}/apply": {"post"},
          # CC-0075: the background jobs (tests/test_cc_api_meme_jobs.py)
          "/api/memes/{channel}/cutout/plan": {"post"}, "/api/memes/{channel}/cutout": {"post"},
          "/api/memes/{channel}/trim/plan": {"post"}, "/api/memes/{channel}/trim": {"post"},
          "/api/memes/{channel}/jobs": {"get"}, "/api/memes/{channel}/jobs/{job_id}": {"get"},
          # CC-0076: the adds, the sheet, the embed (tests/test_cc_api_meme_adds.py)
          **{f"/api/memes/{{channel}}/{a}{x}": {"post"}
             for a in ("add-image", "add-gif", "sheet", "embed") for x in ("/plan", "")},
          "/api/memes/{channel}/sheets/{name}": {"get"}}


def test_the_centers_words_name_the_channel_by_its_display_name():
    """CC-0136: «канала ExampleTech», not the slug; the slug when the config
    has no display name, does not read, or the name is not a plain one."""
    root = world()
    assert memes.channel_title(root, "tech") == "Tech"
    _w(root / "channels" / "bare.json", {"channel_id": "bare", "display_name": "  "})
    (root / "channels" / "broken.json").write_text("{not json")
    for cid in ("bare", "broken", "nobody", "../channels/tech", ".hidden", None):
        assert memes.channel_title(root, cid) == cid, cid


def test_the_contract_carries_the_routes_and_the_codes():
    import api
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    paths = {p: set(v) for p, v in spec["paths"].items() if p.startswith("/api/memes")}
    assert paths == ROUTES, paths
    for p, model in (("/api/memes", "MemesOverview"), ("/api/memes/{channel}", "MemeDesk")):
        ok = spec["paths"][p]["get"]["responses"]["200"]["content"]["application/json"]
        assert ok["schema"]["$ref"].endswith(f"/{model}"), (p, ok)
    for p, m, model in (("/api/memes/{channel}/marks", "put", "MemeMarksResult"),
                        ("/api/memes/{channel}/apply/plan", "post", "MemeApplyPlan"),
                        ("/api/memes/{channel}/apply", "post", "MemeApplyResult")):
        op = spec["paths"][p][m]["responses"]
        assert op["200"]["content"]["application/json"]["schema"]["$ref"].endswith(model)
        for status in ("404", "409", "422"):
            ref = op[status]["content"]["application/json"]["schema"]
            assert "/MemesProblem" in json.dumps(ref), (p, status, ref)
        assert "/WritesProblem" in json.dumps(op["409"]), (p, op["409"])
    codes = set(spec["components"]["schemas"]["MemesProblem"]["properties"]["code"]["enum"])
    desk_codes = {"bank_conflict", "no_channel", "bad_bank", "bad_index", "bad_draft",
                  "bad_spec", "bad_decisions", "unknown_id", "invalid_index", "no_file",
                  "thumb_failed"}
    assert desk_codes | {"unknown_channel", "no_cut", "outside_bank", "check_changed",
                         "confirm_unknown", "confirm_expired", "confirm_mismatch"} <= codes
    assert set(memes.ACTIONS) <= set(batches._ACTIONS)


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
