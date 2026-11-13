#!/usr/bin/env python3
"""CC-0076: the meme desk's adds, contact sheet and embed as background jobs
in the center (`api/meme_jobs.py` over the factory's CF-0760 plans and
CF-0755 start_job):

    POST /api/memes/{c}/add-image/plan  plan_add_image - http(s) only (bad_url)
    POST /api/memes/{c}/add-image       {confirm} - start_job("add_image")
    POST /api/memes/{c}/add-gif/plan    plan_add_gif, local=False always
    POST /api/memes/{c}/add-gif         {confirm} - start_job("add_gif")
    POST /api/memes/{c}/sheet/plan      plan_sheet, local=False always
    POST /api/memes/{c}/sheet           {confirm} - start_job("sheet")
    POST /api/memes/{c}/embed/plan      the center's own plan (no dry one in the factory)
    POST /api/memes/{c}/embed           {confirm} - start_job("embed")
    GET  /api/memes/{c}/sheets/{name}   <bank>/_desk/sheets/<name>, factory.contained, Range

In-process against the temp banks of `tests/test_cc_api_memes.py` `world`,
with the stand-ins of `tests/test_cc_api_meme_jobs.py`: **no test starts a
real job** (the launcher child is a stand-in), the machine's slot is a temp
`MEME_DESK_JOBS_DIR`, a job "running" is a planted state file whose lock this
test holds. Nothing downloads: the factory's plans read no network by
contract, and every center-side refusal of an address is pinned with the
factory's plan replaced by one that fails the test if it is reached. No
sleeps, no timing.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from test_cc_api_meme_jobs import SLOT, Seams, no_abs, plant, started  # noqa: E402
from test_cc_api_batches import TMP, client                         # noqa: E402
from test_cc_api_memes import _index, desk, get, send, world         # noqa: E402
from test_cc_api_publish import files                                # noqa: E402

import api                                                           # noqa: E402
from api import batches, meme_jobs                                   # noqa: E402
from api.batches import BatchFault                                   # noqa: E402

assert os.environ["MEME_DESK_JOBS_DIR"] == str(SLOT)
IMG = {"id": "new-still", "url": "https://example.org/files/new-still.png",
       "source_url": "https://example.org/page", "description": "a new still",
       "tags": ["a", " b "]}
GIF = {"id": "new-gif", "video": "https://example.org/watch?v=abc", "start": 1.0, "end": 3.5,
       "description": "a new gif", "tags": "x,y"}
SHEET = {"video": "https://example.org/watch?v=abc", "start": 0, "end": 20, "every": 2}
BAD = ("file:///etc/a.png", "/home/someone/a.png", "ftp://example.org/a.png",
       "https:///a.png", "a.png", "https://exa mple.org/a.png", "")
ROUTES = {f"/api/memes/{{channel}}/{a}{x}": {"post"}
          for a in ("add-image", "add-gif", "sheet", "embed") for x in ("/plan", "")}
ROUTES["/api/memes/{channel}/sheets/{name}"] = {"get"}
D = desk()
PROBE, EMBED, MEDIA, FETCH = (D.PROBE_TIMEOUT_SECONDS, D.EMBED_TIMEOUT_SECONDS,
                              D.MEDIA_TIMEOUT_SECONDS, D.FETCH_TIMEOUT_SECONDS)


class NoFactoryPlan:
    """The factory's plans replaced by ones that fail when reached."""
    NAMES = ("plan_add_image", "plan_add_gif", "plan_sheet")

    def __enter__(self):
        self.saved = {n: getattr(D, n) for n in self.NAMES}
        for n in self.NAMES:
            setattr(D, n, self._reached(n))
        return self

    @staticmethod
    def _reached(n):
        def fn(*a, **k):
            raise AssertionError(f"{n} was reached")
        return fn

    def __exit__(self, *exc):
        for n, f in self.saved.items():
            setattr(D, n, f)


def clips(root, url, bank="memes"):
    return root / "shared" / "inserts" / bank / "_desk" / "clips" / (
        hashlib.sha1(url.encode("utf-8")).hexdigest() + ".mp4")


# --------------------------------------------------------------------- the plans
def test_the_add_image_plan_is_the_factorys_and_writes_nothing():
    root = world()
    c = client(root)
    before = files(root)
    code, p = send(c, "POST", "/api/memes/reel/add-image/plan", IMG)
    assert code == 200, p
    assert p["action"] == "meme_add_image" and p["kind"] == "add_image" and p["dry_run"], p
    assert p["bank"] == "memes" and p["id"] == "new-still" and p["file"] == "new-still.png", p
    assert p["will_fetch"] == "url" and p["url"] == IMG["url"] and p["video"] is None, p
    assert p["tags"] == ["a", "b"] and p["span"] is None, p
    assert p["steps"] == ["download", "check", "index", "embedding"], p
    assert p["max_seconds"] == FETCH + PROBE + PROBE + EMBED, p
    assert p["max_seconds_word"] == meme_jobs.human_seconds(p["max_seconds"]) == "до 33 мин"
    assert p["params"] == {"meme_id": "new-still", "url": IMG["url"],
                           "source_url": IMG["source_url"], "description": "a new still",
                           "tags": ["a", " b "]}, p["params"]
    assert p["ok"] is True and p["why"] is None and p["confirm"] and p["job"] is None, p
    assert p["expires_in_s"] == 120 and len(p["fingerprint"]) == 64, p
    notes = " ".join(p["notes"])
    for word in ("по ссылке", "в банк непроверенным", "признаки для поиска похожих мемов",
                 "банк мемов канала Reel", "25 МБ"):
        assert word in notes, (word, p["notes"])
    assert IMG["url"] not in notes and "Худшее время" not in notes, p["notes"]   # CC-0136
    code, p = send(c, "POST", "/api/memes/reel/add-image/plan", dict(IMG, notes="из шаблона"))
    assert code == 200 and p["params"]["notes"] == "из шаблона", p
    assert files(root) == before
    no_abs(root, p)


def test_the_add_gif_plan_says_the_download_or_the_cache():
    root = world()
    c = client(root)
    before = files(root)
    code, p = send(c, "POST", "/api/memes/reel/add-gif/plan", GIF)
    assert code == 200 and p["action"] == "meme_add_gif" and p["kind"] == "add_gif", p
    assert p["file"] == "new-gif.gif" and p["will_fetch"] == "yt-dlp" and p["cached"] is False
    assert p["span"] == {"start_s": 1.0, "end_s": 3.5} and p["tags"] == ["x", "y"], p
    assert p["source_url"] == GIF["video"], p
    assert p["steps"] == ["download", "scenes", "cut", "check", "index", "embedding"], p
    assert p["max_seconds"] == PROBE + MEDIA + MEDIA + MEDIA + PROBE + PROBE + EMBED, p
    assert p["params"] == {"meme_id": "new-gif", "video": GIF["video"], "start": 1.0,
                           "end": 3.5, "description": "a new gif", "tags": "x,y",
                           "local": False}, p["params"]
    assert any("Будет скачано видео по ссылке\u00a0— только картинка, без звука, до 720p" in n
               for n in p["notes"]), p["notes"]
    assert any("Из отрезка 1–3,5 с будет нарезан беззвучный GIF в банк мемов канала Reel." == n
               for n in p["notes"]), p["notes"]
    assert not any(GIF["video"] in n or "Худшее время" in n for n in p["notes"]), p["notes"]
    assert any("Смены сцен внутри отрезка" in n for n in p["notes"]), p["notes"]
    assert p["ok"] and p["confirm"], p
    assert files(root) == before
    no_abs(root, p)
    cache = clips(root, GIF["video"])
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"mp4")
    code, p = send(c, "POST", "/api/memes/reel/add-gif/plan",
                   dict(GIF, source_url="https://example.org/about", notes="n"))
    assert code == 200 and p["cached"] is True, p
    assert p["max_seconds"] == MEDIA + MEDIA + PROBE + PROBE + EMBED, p
    assert any("Видео уже скачано" in n and "GIF режется из уже скачанного видео" in n
               for n in p["notes"]), p["notes"]
    assert p["params"]["source_url"] == "https://example.org/about" and \
        p["params"]["notes"] == "n" and p["params"]["local"] is False, p["params"]


def test_the_sheet_plan_counts_frames_and_names_its_url():
    root = world()
    c = client(root)
    before = files(root)
    code, p = send(c, "POST", "/api/memes/reel/sheet/plan", SHEET)
    assert code == 200 and p["action"] == "meme_sheet" and p["kind"] == "sheet", p
    assert p["file"] == "_desk/sheets/sheet.jpg" and p["id"] is None and p["tags"] is None, p
    assert p["sheet"] == "shared/inserts/memes/_desk/sheets/sheet.jpg", p
    assert p["sheet_url"] == "/api/memes/reel/sheets/sheet.jpg", p
    assert p["span"] == {"start_s": 0.0, "end_s": 20.0, "every_s": 2.0, "frames": 10}, p
    assert p["steps"] == ["download", "frames", "sheet"] and p["overwrites"] is False, p
    assert p["params"] == {"video": SHEET["video"], "local": False, "start": 0, "end": 20,
                           "every": 2}, p["params"]
    assert any("10 кадров" in n for n in p["notes"]), p["notes"]
    assert any("в банк ничего не добавляется" in n for n in p["notes"]), p["notes"]
    assert p["ok"] and p["confirm"], p
    assert files(root) == before
    no_abs(root, p)
    sheets = root / "shared" / "inserts" / "memes" / "_desk" / "sheets"
    sheets.mkdir(parents=True)
    (sheets / "moment.png").write_bytes(b"png")
    code, p = send(c, "POST", "/api/memes/reel/sheet/plan",
                   {"video": SHEET["video"], "out": "moment.png"})
    assert code == 200 and p["span"]["end_s"] is None and p["span"]["frames"] is None, p
    assert p["params"] == {"video": SHEET["video"], "local": False, "out": "moment.png"}, p
    assert p["overwrites"] is True and any("перезаписан" in n for n in p["notes"]), p
    assert any("станет известно после извлечения" in n for n in p["notes"]), p["notes"]
    assert p["sheet_url"] == "/api/memes/reel/sheets/moment.png", p
    code, p = send(c, "POST", "/api/memes/reel/sheet/plan",
                   {"video": SHEET["video"], "start": 1.5, "end": 4, "every": 0.5})
    assert code == 200 and any(n.startswith("Лист: кадр каждые 0,5 с от 1,5 с до 4 с")
                               for n in p["notes"]), p["notes"]          # CC-0136: commas


def test_the_embed_plan_is_the_centers_own():
    root = world()
    c = client(root)
    before = files(root)
    code, p = send(c, "POST", "/api/memes/tech/embed/plan")
    assert code == 200 and p["action"] == "meme_embed" and p["kind"] == "embed", p
    assert p["bank"] == "memes-tech" and p["steps"] == ["embedding"] and p["params"] == {}, p
    assert p["max_seconds"] == PROBE + EMBED and p["max_seconds_word"] == "до 31 мин", p
    assert p["notes"] == [
        "Признаки для поиска похожих мемов будут пересчитаны заново для всего банка мемов "
        "канала Tech; файлы и отметки мемов не меняются.",
        "Заранее посчитать нельзя: перед запуском фабрика проверит, что банк свободен."], p
    assert p["ok"] and p["confirm"] and p["dry_run"] is True, p
    code, r = send(c, "POST", "/api/memes/nobody/embed/plan")
    assert code == 404 and r["code"] == "unknown_channel", r
    assert files(root) == before


def test_human_seconds():
    h = meme_jobs.human_seconds
    assert (h(None), h(45), h(60), h(61), h(3599), h(3600), h(3660), h(7260.5)) == (
        None, "до 45 с", "до 1 мин", "до 2 мин", "до 1 ч", "до 1 ч", "до 1 ч 1 мин",
        "до 2 ч 2 мин")


# --------------------------------------------------------------------- refusals
def test_only_http_addresses_refused_by_the_center_before_the_factory():
    root = world()
    c = client(root)
    before = files(root)
    with NoFactoryPlan():
        for bad in BAD:
            for path, body in (("add-image", dict(IMG, url=bad)), ("add-gif", dict(GIF, video=bad)),
                               ("sheet", dict(SHEET, video=bad))):
                code, r = send(c, "POST", f"/api/memes/reel/{path}/plan", body)
                assert code == 422 and r["code"] == "bad_url", (path, bad, r)
                assert "http(s)" in r["message"] and "локальный путь" in r["message"], r
                assert set(r) == {"message", "code", "details"}, r
                no_abs(root, r)
        for out in ("../x.jpg", "..", "/tmp/x.jpg", "sub/x.jpg", "a\\b.jpg"):
            code, r = send(c, "POST", "/api/memes/reel/sheet/plan", dict(SHEET, out=out))
            assert code == 422 and r["code"] == "bad_params" and "без папок" in r["message"], r
    assert files(root) == before


def test_the_factorys_refusals_pass_with_their_text():
    root = world()
    c = client(root)
    before = files(root)
    for path, body, status, code_, words in (
            ("add-image", dict(IMG, id="old-one"), 409, "duplicate_id", "уже есть в банке"),
            ("add-image", dict(IMG, id="Bad Id"), 422, "bad_entry", "строчные латинские"),
            ("add-image", dict(IMG, description=" "), 422, "bad_entry", "нужно описание"),
            ("add-image", dict(IMG, url="https://example.org/a.gif"), 422, "bad_suffix",
             "GIF добавляется из видео"),
            ("add-image", dict(IMG, source_url="page"), 422, "no_source_url",
             "нужна ссылка на страницу, где файл найден"),
            ("add-gif", dict(GIF, end=1.0), 422, "bad_span", "end должен быть позже start"),
            ("add-gif", dict(GIF, id="a-gif"), 409, "duplicate_id", "уже есть в банке"),
            ("sheet", dict(SHEET, end=1000, every=1), 422, "too_many_frames",
             "не больше 300 кадров"),
            ("sheet", dict(SHEET, every=0), 422, "bad_span", "every > 0"),
            ("sheet", dict(SHEET, out="x.txt"), 422, "bad_suffix", ".jpg или .png")):
        code, r = send(c, "POST", f"/api/memes/reel/{path}/plan", body)
        assert code == status and r["code"] == code_ and words in r["message"], (path, body, r)
        assert any(d.startswith(f"MemeDeskError({code_})") for d in r["details"]), r
        no_abs(root, r)
    # a file of that name already in the bank (not in the index)
    (root / "shared" / "inserts" / "memes" / "new-still.png").write_bytes(b"x")
    code, r = send(c, "POST", "/api/memes/reel/add-image/plan", IMG)
    assert code == 409 and r["code"] == "file_exists", r
    (root / "shared" / "inserts" / "memes" / "new-still.png").unlink()
    assert files(root) == before


# --------------------------------------------------------------------- the confirm
def test_each_confirm_starts_its_job_once_with_local_false():
    root = world()
    c = client(root)
    for path, body, kind, params in (
            ("add-image", IMG, "add_image",
             {"meme_id": "new-still", "url": IMG["url"], "source_url": IMG["source_url"],
              "description": "a new still", "tags": ["a", " b "]}),
            ("add-gif", GIF, "add_gif",
             {"meme_id": "new-gif", "video": GIF["video"], "start": 1.0, "end": 3.5,
              "description": "a new gif", "tags": "x,y", "local": False}),
            ("sheet", SHEET, "sheet", {"video": SHEET["video"], "local": False, "start": 0.0,
                                       "end": 20.0, "every": 2.0}),
            ("embed", None, "embed", {})):
        job_id = f"20261015T130000Z-{kind}-abc123"
        with Seams(launcher=started(root, kind=kind, job_id=job_id)) as s:
            code, p = send(c, "POST", f"/api/memes/reel/{path}/plan", body)
            assert code == 200 and p["confirm"], p
            before = files(root)
            code, r = send(c, "POST", f"/api/memes/reel/{path}", {"confirm": p["confirm"]})
            assert code == 200, r
            assert r["action"] == f"meme_{kind}" and r["kind"] == kind and r["job_id"] == job_id
            assert r["status_url"] == f"/api/memes/reel/jobs/{job_id}", r
            assert r["log"] == f"shared/inserts/memes/_desk/jobs/{job_id}.log", r
            (cmd, cwd, env), = s.calls
            assert cmd[4:7] == [kind, json.dumps(params), "reel"], (kind, cmd)
            assert env["MEME_DESK_JOBS_DIR"] == str(SLOT), env.get("MEME_DESK_JOBS_DIR")
            assert files(root) == before
            code, r = send(c, "POST", f"/api/memes/reel/{path}", {"confirm": p["confirm"]})
            assert code == 409 and r["code"] == "confirm_unknown", r
            assert len(s.calls) == 1


def test_tokens_expire_and_a_moved_plan_is_check_changed():
    root = world()
    c = client(root)
    with Seams(launcher=started(root)) as s:
        _, p = send(c, "POST", "/api/memes/reel/add-image/plan", IMG)
        real = batches._clock
        batches._clock = lambda: real() + batches.CONFIRM_TTL + 1
        try:
            code, r = send(c, "POST", "/api/memes/reel/add-image", {"confirm": p["confirm"]})
        finally:
            batches._clock = real
        assert code == 409 and r["code"] == "confirm_expired", r
        _, p = send(c, "POST", "/api/memes/reel/add-image/plan", IMG)    # another kind's token
        code, r = send(c, "POST", "/api/memes/reel/add-gif", {"confirm": p["confirm"]})
        assert code == 409 and r["code"].startswith("confirm_"), r
        _, p = send(c, "POST", "/api/memes/tech/embed/plan")             # another channel's
        code, r = send(c, "POST", "/api/memes/reel/embed", {"confirm": p["confirm"]})
        assert code == 409 and r["code"] == "confirm_mismatch", r
        # index.json moved
        _, p = send(c, "POST", "/api/memes/reel/add-image/plan", IMG)
        idx = root / "shared" / "inserts" / "memes" / "index.json"
        idx.write_text(idx.read_text() + "\n")
        code, r = send(c, "POST", "/api/memes/reel/add-image", {"confirm": p["confirm"]})
        assert code == 409 and r["code"] == "check_changed", r
        # the video came into the cache since the plan - the plan is another one
        _, p = send(c, "POST", "/api/memes/reel/sheet/plan", SHEET)
        cache = clips(root, SHEET["video"])
        cache.parent.mkdir(parents=True)
        cache.write_bytes(b"mp4")
        code, r = send(c, "POST", "/api/memes/reel/sheet", {"confirm": p["confirm"]})
        assert code == 409 and r["code"] == "check_changed", r
        # the id taken since the plan - the factory's refusal at the re-plan
        _, p = send(c, "POST", "/api/memes/reel/add-gif/plan", GIF)
        inserts = root / "shared" / "inserts"
        doc = json.loads((inserts / "memes" / "index.json").read_text())
        from test_cc_api_memes import entry
        _index(inserts, doc["entries"] + [entry("new-gif", "a-gif.gif",
                                                clip={"start_s": 0.0, "end_s": 1.0})])
        code, r = send(c, "POST", "/api/memes/reel/add-gif", {"confirm": p["confirm"]})
        assert code == 409 and r["code"] == "duplicate_id", r
        assert s.calls == []


def test_a_job_on_the_bank_holds_the_plans_and_the_confirms():
    root = world()
    c = client(root)
    with Seams(launcher=started(root)) as s:
        job_id, fd = plant(root, kind="add_gif", held=True,
                           progress={"step": "scenes", "i": 2, "of": 6, "text": ""})
        try:
            before = files(root)
            for path, body in (("add-image", IMG), ("add-gif", GIF), ("sheet", SHEET),
                               ("embed", None)):
                code, p = send(c, "POST", f"/api/memes/reel/{path}/plan", body)
                assert code == 200 and p["ok"] is False and p["confirm"] is None, (path, p)
                assert p["job"]["job_id"] == job_id and p["job"]["kind_word"] == "нарезка GIF"
                assert "не запустить" in p["why"] and job_id in p["why"], p
                code, r = send(c, "POST", f"/api/memes/reel/{path}", {"confirm": "x"})
                assert code == 409 and r["code"] == "job_active" and job_id in r["message"], r
            assert files(root) == before and s.calls == []
            code, p = send(c, "POST", "/api/memes/tech/embed/plan")       # another bank
            assert code == 200 and p["ok"] is True and p["job"] is None, p
        finally:
            os.close(fd)


def test_an_alive_job_on_another_bank_holds_every_plan():
    """CF-0761 active_job: the machine's slot names a job on memes-tech
    (its lock held here) - every plan of reel (bank memes) is ok false with
    `machine_job`; tech's own plans see it as the bank's `job`; the lock free
    (the process gone) or the slot naming a finished job - nobody is held."""
    root = world()
    c = client(root)
    from test_cc_api_batches import _w
    from test_cc_api_meme_candidates import cand
    _w(root / "shared" / "inserts" / "memes" / "candidates.json",           # not downloaded
       {"listed": "2026-10-12", "candidates": [
           cand("not-there", 800, 800, True, url="https://i.imgflip.com/not-there.png")]})
    job_id, fd = plant(root, bank="memes-tech", kind="sheet", held=True,
                       stamp="20261015T150000Z")
    state = root / "shared" / "inserts" / "memes-tech" / "_desk" / "jobs" / f"{job_id}.json"
    SLOT.mkdir(parents=True, exist_ok=True)
    active = SLOT / "active.json"
    active.write_text(json.dumps({"job_id": job_id, "kind": "sheet", "bank": "memes-tech",
                                  "state_file": str(state), "pid": 999999,
                                  "started_at": "2026-10-15T15:00:00+00:00"}))
    text = (f"На машине идёт задача {job_id} (контактный лист, банк мемов канала Tech)"
            f"\u00a0— одна задача на машину, дождитесь её конца.")
    plans = (("add-image/plan", IMG), ("add-gif/plan", GIF), ("sheet/plan", SHEET),
             ("embed/plan", None), ("cutout/plan", None), ("trim/plan", None),
             ("apply/plan", None), ("candidates/accept/plan", None))
    try:
        with Seams(launcher=started(root)) as s:
            before = files(root)
            for path, body in plans:
                code, p = send(c, "POST", f"/api/memes/reel/{path}", body)
                assert code == 200 and p["ok"] is False and p["confirm"] is None, (path, p)
                assert p["job"] is None and p["why"] == text, (path, p)
                m = p["machine_job"]
                assert m["job_id"] == job_id and m["bank"] == "memes-tech", (path, m)
                assert m["channel"] == "tech" and m["kind_word"] == "контактный лист", (path, m)
                no_abs(root, p)
            code, p = send(c, "POST", "/api/memes/tech/embed/plan")     # the same bank
            assert p["ok"] is False and p["job"]["job_id"] == job_id, p
            assert p["machine_job"] is None and "не запустить" in p["why"], p
            assert files(root) == before and s.calls == []
        os.close(fd)
        fd = None
        for path, body in plans[:4]:                                     # the process gone
            code, p = send(c, "POST", f"/api/memes/reel/{path}", body)
            assert code == 200 and p["ok"] is True and p["machine_job"] is None, (path, p)
        doc = json.loads(state.read_text())
        state.write_text(json.dumps(dict(doc, state="done")))
        code, p = send(c, "POST", "/api/memes/reel/embed/plan")          # a finished job
        assert p["ok"] is True and p["machine_job"] is None, p
    finally:
        if fd is not None:
            os.close(fd)
        active.unlink()


# --------------------------------------------------------------------- the results
def test_the_results_carry_routes_and_no_absolute_path():
    root = world()
    c = client(root)
    bank = root / "shared" / "inserts" / "memes"
    img_id, _ = plant(root, kind="add_image", state="done", stamp="20261015T140000Z", result={
        "bank": "memes", "file": "new-still.png", "size": [600, 600], "trim_note": None,
        "trim_note_ru": None,
        "entry": {"id": "new-still", "file": "new-still.png", "review": "pending"},
        "embedding": {"done": True, "line": f"embedded {bank}/index.json", "error": None,
                      "en": None, "fatal": False}})
    gif_id, _ = plant(root, kind="add_gif", state="done", stamp="20261015T140100Z", result={
        "bank": "memes", "file": "new-gif.gif", "size": [960, 540], "duration_s": 2.5,
        "cuts_inside": [2.1], "entry": {"id": "new-gif", "file": "new-gif.gif"},
        "embedding": None})
    sheet_id, _ = plant(root, kind="sheet", state="done", stamp="20261015T140200Z", result={
        "sheet": str(bank / "_desk" / "sheets" / "moment.jpg"), "scene_cuts": [1.5, 7.25]})
    code, r = get(c, f"/api/memes/reel/jobs/{img_id}")
    assert code == 200 and r["state"] == "done", r
    assert r["result"]["entry"]["urls"] == {"file": "/api/memes/reel/new-still/media?kind=file",
                                            "cut": None,
                                            "thumb": "/api/memes/reel/new-still/thumb"}, r
    assert r["result"]["embedding"]["line"] == "embedded shared/inserts/memes/index.json", r
    assert "trim_note_ru" in r["result"], r            # CF-0762: passes through as the job gave it
    no_abs(root, r)
    code, r = get(c, f"/api/memes/reel/jobs/{gif_id}")
    assert r["result"]["entry"]["urls"]["file"] == "/api/memes/reel/new-gif/media?kind=file", r
    assert r["result"]["cuts_inside"] == [2.1] and r["kind_word"] == "нарезка GIF", r
    code, r = get(c, f"/api/memes/reel/jobs/{sheet_id}")
    assert r["result"]["sheet"] == "shared/inserts/memes/_desk/sheets/moment.jpg", r
    assert r["result"]["sheet_url"] == "/api/memes/reel/sheets/moment.jpg", r
    assert r["result"]["scene_cuts"] == [1.5, 7.25] and r["kind_word"] == "контактный лист", r
    no_abs(root, r)
    code, jobs = get(c, "/api/memes/reel/jobs")
    assert [j["job_id"] for j in jobs["jobs"]] == [sheet_id, gif_id, img_id], jobs
    no_abs(root, jobs)


def test_the_sheet_route_serves_only_the_sheets_folder():
    root = world()
    c = client(root)
    bank = root / "shared" / "inserts" / "memes"
    sheets = bank / "_desk" / "sheets"
    sheets.mkdir(parents=True)
    (sheets / "moment.jpg").write_bytes(b"\xff\xd8" + b"j" * 98)
    (sheets / "notes.txt").write_text("x")
    outside = TMP / "outside-sheet.png"
    outside.write_bytes(b"secret")
    (sheets / "link.png").symlink_to(outside)
    r = c.get("/api/memes/reel/sheets/moment.jpg")
    assert r.status_code == 200 and r.content == b"\xff\xd8" + b"j" * 98, r.status_code
    assert r.headers["content-type"] == "image/jpeg", r.headers
    r = c.get("/api/memes/reel/sheets/moment.jpg", headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and len(r.content) == 10, (r.status_code, r.headers)
    for name, code_ in (("notes.txt", "outside_bank"), ("link.png", "outside_bank"),
                        ("nope.jpg", "no_file")):
        code, r = get(c, f"/api/memes/reel/sheets/{name}")
        assert code == 404 and r["code"] == code_, (name, r)
        no_abs(root, r)
    for path in ("/api/memes/reel/sheets/..%2Findex.json", "/api/memes/reel/sheets/%2Fetc%2Fx.png",
                 "/api/memes/tech/sheets/moment.jpg"):
        r = c.get(path)
        assert r.status_code == 404 and b"secret" not in r.content, (path, r.status_code)
    for name in ("../index.json", "..", "/etc/x.png", str(sheets / "moment.jpg"),
                 "../../memes/_desk/sheets/moment.jpg", "", ".jpg/..", "a\0.png"):
        try:
            meme_jobs.sheet_path(root, "reel", name)
        except BatchFault as e:
            assert e.status == 404 and e.code == "outside_bank", (name, e.code)
        else:
            raise AssertionError(f"{name!r} served")


# --------------------------------------------------------------------- the contract
def test_the_contract_carries_the_add_routes():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    paths = {p: set(v) for p, v in spec["paths"].items() if p in ROUTES}
    assert paths == ROUTES, paths
    for a, model in (("add-image", "MemeAddImagePlan"), ("add-gif", "MemeAddGifPlan"),
                     ("sheet", "MemeSheetPlan"), ("embed", "MemeEmbedPlan")):
        for p, m in ((f"/api/memes/{{channel}}/{a}/plan", model),
                     (f"/api/memes/{{channel}}/{a}", "MemeJobStarted")):
            op = spec["paths"][p]["post"]["responses"]
            assert op["200"]["content"]["application/json"]["schema"]["$ref"].endswith(m), p
            assert "/MemesProblem" in json.dumps(op["409"]), p
            assert "/WritesProblem" in json.dumps(op["409"]), p
    codes = set(spec["components"]["schemas"]["MemesProblem"]["properties"]["code"]["enum"])
    assert {"bad_url", "bad_suffix", "no_source_url", "file_exists", "bad_span",
            "too_many_frames", "duplicate_id", "bad_entry", "video_failed"} <= codes
    started_ = spec["components"]["schemas"]["MemeJobStarted"]["properties"]["action"]["enum"]
    assert set(started_) == set(meme_jobs.ACTIONS), started_
    assert {s["kind"] for s in meme_jobs.SPECS.values()} == set(D.JOB_KINDS)
    for s in meme_jobs.SPECS.values():                  # every param is the factory's own
        need, allowed = D.JOB_PARAMS[s["kind"]]
        p = s["params"]({"id": "i", "url": "u", "source_url": "s", "description": "d",
                         "tags": [], "notes": "n", "video": "v", "start": 0, "end": 1,
                         "every": 1, "out": "o.jpg"})
        assert need <= set(p) <= allowed, (s["kind"], p)


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
