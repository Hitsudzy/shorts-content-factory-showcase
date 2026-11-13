#!/usr/bin/env python3
"""CF-0333: the duration ceiling holds on the fact, inside the download.

A long talk-show recording filed as a trailer candidate came down whole
because the length check before the walk could not answer (no length on the
candidate, none in the cache, and the metadata probe had failed). An
unmeasured length is, rightly, not a refusal - so the ceiling must also hold
inside the download itself, on the length the download request reports.

What is pinned here, all of it offline:

  - `fetch_footage.py --max-duration` hands yt-dlp a match filter and reads
    the length yt-dlp printed in the same request; a video over the limit
    exits TOO_LONG_EXIT with a TOO_LONG line and registers nothing, one
    under it comes down as before, and without the flag nothing changes;
  - `fetch_source()` turns that exit into `TooLong` with the numbers;
  - the report lists a download refusal beside the metadata ones.

No pytest dependency - plain asserts, run directly.
"""
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import fetch_footage as ff          # noqa: E402
import ingest_batch as ib           # noqa: E402

# CF-0505: the batch's `01` is frozen (tests/freeze_live_batches.py), and the
# depth record of the replay (`pool_depth.CACHE`) reads an empty temp pool,
# not the live shared/footage.
import pool_depth                   # noqa: E402
from _tmproot import tmp_root as _tmp_root   # noqa: E402
pool_depth.CACHE = _tmp_root("cf0505-download-")
TOPIC = "topic-004"
TALK_SHOW = "talkshow0001"
TALK_SHOW_SECONDS = 8019
FIRST_SOURCE = "firstsrc001"
SKIPPED = []

# ---------------------------------------------------------------------------
# fetch_footage.py against a fake yt-dlp that honours --match-filter the way
# the real one does (checked against YouTube on 2026-09-26: `pre_process`
# prints run before the filter, a filtered video exits 0 with no file).

from _tmproot import tmp_root  # noqa: E402
TMP = tmp_root("cf0333-")   # CF-0489: removed at exit
from _temp_pool import fence_cache_index  # noqa: E402
# CF-0683: fetch_footage.INDEX (rights_for, measure_candidate) on a temp pool, not the live one.
fence_cache_index(TMP / "ff-pool")
FAKE = TMP / "fake_ytdlp.py"
FAKE.write_text(r'''#!/usr/bin/env python3
import json, os, re, sys
from pathlib import Path
args = sys.argv[1:]
vid = args[0].split("v=")[-1]
length = float(os.environ.get("FAKE_DURATION", "100"))
if "--dump-single-json" in args:
    print(json.dumps({"id": vid, "title": "t", "uploader": "u", "duration": length}))
    sys.exit(0)
Path(os.environ["FAKE_ARGV"]).write_text(json.dumps(args))
home = temp = None
for i, a in enumerate(args):
    if a == "-P" and args[i + 1].startswith("home:"):
        home = Path(args[i + 1][5:])
    if a == "-P" and args[i + 1].startswith("temp:"):
        temp = Path(args[i + 1][5:])
prints = [args[i + 1] for i, a in enumerate(args) if a == "--print"]
for p in prints:
    if p.startswith("pre_process:"):
        print(p[len("pre_process:"):].replace("%(id)s", vid)
              .replace("%(duration)s", str(int(length))))
if "--match-filter" in args:
    m = re.match(r"duration <=\? (\d+)", args[args.index("--match-filter") + 1])
    if m and length > int(m.group(1)):
        sys.exit(0)               # "does not pass filter", nothing downloaded
temp.mkdir(parents=True, exist_ok=True)
(temp / f"{vid}.f1.mp4.part").write_bytes(b"x")
home.mkdir(parents=True, exist_ok=True)
final = home / f"{vid}.mp4"
final.write_bytes(b"m" * 1000)
print(final)
''')
FAKE.chmod(0o755)


def run_fetch(cache, vid, extra=(), length=TALK_SHOW_SECONDS):
    """fetch_footage.main() in-process against `cache`; (code, out, err, argv)."""
    argv_file = TMP / f"argv-{vid}-{len(extra)}.json"
    os.environ["FAKE_DURATION"] = str(length)
    os.environ["FAKE_ARGV"] = str(argv_file)
    old = (ff.CACHE, ff.INDEX if hasattr(ff, "INDEX") else None)
    ff.CACHE = cache
    if hasattr(ff, "INDEX"):
        ff.INDEX = cache / "index.json"
    argv, sys.argv = sys.argv, ["fetch_footage.py",
                                f"https://www.youtube.com/watch?v={vid}",
                                "--ytdlp", str(FAKE),
                                # CF-0598/CF-0597: an empty temp registry root.
                                "--rights-root", str(TMP), *extra]
    out, err, code = io.StringIO(), io.StringIO(), 0
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                ff.main()
            except SystemExit as e:
                if isinstance(e.code, str):
                    print(e.code, file=sys.stderr)
                    code = 1
                else:
                    code = e.code or 0
    finally:
        sys.argv = argv
        ff.CACHE = old[0]
        if old[1] is not None:
            ff.INDEX = old[1]
    got = json.loads(argv_file.read_text()) if argv_file.exists() else []
    return code, out.getvalue(), err.getvalue(), got


def entries(cache):
    idx = cache / "index.json"
    return json.loads(idx.read_text())["entries"] if idx.exists() else []


def test_the_download_refuses_the_talk_show_on_its_own_number():
    cache = Path(tempfile.mkdtemp(prefix="cache-", dir=TMP))
    code, out, err, argv = run_fetch(cache, TALK_SHOW, ["--max-duration", "900"])
    assert code == ff.TOO_LONG_EXIT, (code, err)
    assert "--match-filter" in argv
    assert argv[argv.index("--match-filter") + 1] == "duration <=? 900"
    assert ff.parse_too_long(err) == (TALK_SHOW_SECONDS, 900.0), err
    assert entries(cache) == []                       # nothing registered
    assert not (cache / f"{TALK_SHOW}.mp4").exists()  # nothing came down
    assert not [p for p in cache.iterdir() if p.name.startswith(".fetch-tmp")]


def test_a_source_under_the_ceiling_comes_down_as_before():
    cache = Path(tempfile.mkdtemp(prefix="cache-", dir=TMP))
    code, out, err, _ = run_fetch(cache, FIRST_SOURCE, ["--max-duration", "3600"],
                                  length=304)
    assert code == 0, err
    assert out.startswith("fetched -> ") and out.strip().endswith(f"{FIRST_SOURCE}.mp4")
    assert [e["id"] for e in entries(cache)] == [FIRST_SOURCE]


def test_without_the_flag_the_download_is_unchanged():
    cache = Path(tempfile.mkdtemp(prefix="cache-", dir=TMP))
    code, out, err, argv = run_fetch(cache, TALK_SHOW)
    assert code == 0, err
    assert "--match-filter" not in argv
    assert not any(a.startswith("pre_process:" + ff.DURATION_MARK) for a in argv)


# ---------------------------------------------------------------------------
# fetch_source(): the exit code becomes TooLong

def test_fetch_source_hands_the_ceiling_down_and_reads_the_refusal():
    seen = {}

    def fake_run_child(cmd, **kw):
        seen["cmd"] = cmd
        return SimpleNamespace(returncode=ff.TOO_LONG_EXIT, stdout="",
                               stderr=ff.TOO_LONG_LINE.format(
                                   seconds=8019, limit=900, vid=TALK_SHOW))

    real = ib.runlog.run_child
    ib.runlog.run_child = fake_run_child
    try:
        try:
            ib.fetch_source(TALK_SHOW, "n", max_seconds=900)
        except ib.TooLong as e:
            assert (e.seconds, e.limit) == (8019.0, 900.0)
        else:
            raise AssertionError("no TooLong")
    finally:
        ib.runlog.run_child = real
    cmd = seen["cmd"]
    assert cmd[cmd.index("--max-duration") + 1] == "900"


def test_the_report_lists_a_download_refusal_with_the_metadata_ones():
    rec = {"video_id": TALK_SHOW, "topic_id": TOPIC,
           "reason_code": ib.TOO_LONG_CODE, "error": "e", "nature": "trailer",
           "duration_seconds": TALK_SHOW_SECONDS, "ceiling_seconds": 900,
           "measured_from": ib.RUNG_DOWNLOAD}
    block = ib.ceiling_report(None, [rec], [])
    assert block["refused"][0]["measured_from"] == "download"
    assert "CF-0333" in block["note"]


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    for note in dict.fromkeys(SKIPPED):
        print(f"  note: {note}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
