#!/usr/bin/env python3
"""CF-0090: a failed yt-dlp download must leave nothing in the LRU cache.

Batch 2026-09-03T2037Z, RUN_LOG.txt:7 - `Hk_xChyX9kc` failed to download
and its `Hk_xChyX9kc.f616.mp4` (1.1GB, one stream of a bestvideo+bestaudio
merge) stayed in shared/footage/ next to the real footage, indistinguishable
by name from a finished file and registered nowhere.

Everything here runs against a temp cache with a fake yt-dlp (a tiny script
that writes what the real one would, then exits 0 or 1) - no network:

  - failure: no `<id>.*` file, no temp dir, no LRU entry, one CLEANUP line
    naming the id and what went, and the exit message ingest_batch sees;
  - failure with the old-style partial already in the cache root
    (belt-and-braces): that goes too;
  - an empty final file counts as failure - removed, never registered;
  - success registers exactly the final file, the temp dir is gone;
  - a pre-existing orphan partial is swept on the next fetch with a SWEEP
    line, while a registered final file with all its sidecars, an
    unregistered but complete .mp4, and index.json are never touched;
  - a stale temp dir of a dead process is swept, a live one is not;
  - "cached" needs a registered entry whose file exists and is non-empty.

No pytest dependency - plain asserts, run directly.
"""
import io
import json
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import fetch_footage as ff  # noqa: E402

from _tmproot import tmp_root  # noqa: E402
TMP = tmp_root("cf0090-")   # CF-0489: removed at exit
FAKE = TMP / "fake_ytdlp.py"
VID = "Hk_xChyX9kc"
URL = f"https://www.youtube.com/watch?v={VID}"

# The fake yt-dlp. It honours exactly the options fetch_footage.py passes:
# -P home:/temp:, -o, --print pre_process:%(id)s / after_move:filepath,
# --dump-single-json. FAKE_YTDLP_MODE picks what it leaves behind:
#   fail          intermediates in the temp dir, exit 1
#   fail-in-home  the same, plus the pre-CF-0090 partial in the cache root
#   ok            intermediates in temp, final file in home, exit 0
#   ok-empty      like ok but the final file is zero bytes
FAKE.write_text(r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
url = args[0]
vid = url.split("v=")[-1]
mode = os.environ.get("FAKE_YTDLP_MODE", "ok")
if "--dump-single-json" in args:
    print(json.dumps({"id": vid, "title": "t", "uploader": "u", "duration": 5}))
    sys.exit(0)
paths = {}
for i, a in enumerate(args):
    if a == "-P":
        k, v = args[i + 1].split(":", 1)
        paths[k] = Path(v)
prints = [args[i + 1] for i, a in enumerate(args) if a == "--print"]
if any(p.startswith("pre_process:") for p in prints):
    print(vid)
home, temp = paths["home"], paths.get("temp", paths["home"])
(temp / f"{vid}.f616.mp4").write_bytes(b"v" * 4096)
(temp / f"{vid}.f140.m4a.part").write_bytes(b"a" * 512)
(temp / f"{vid}.f140.m4a.ytdl").write_text("{}")
if mode == "fail-in-home":
    (home / f"{vid}.f616.mp4").write_bytes(b"v" * 8192)
if mode.startswith("fail"):
    print("ERROR: unable to download video data: HTTP Error 403", file=sys.stderr)
    sys.exit(1)
final = home / f"{vid}.mp4"
final.write_bytes(b"" if mode == "ok-empty" else b"m" * 16384)
if any(p.startswith("after_move:") for p in prints):
    print(final)
sys.exit(0)
''')
FAKE.chmod(0o755)


def fresh_cache(name):
    cache = TMP / name
    if cache.exists():
        shutil.rmtree(cache)
    cache.mkdir()
    ff.CACHE = cache
    ff.INDEX = cache / "index.json"
    return cache


def run_fetch(cache, url=URL, mode="ok"):
    """Run fetch_footage.main() in-process against `cache` with the fake
    yt-dlp; returns (exit_code, stdout, stderr)."""
    os.environ["FAKE_YTDLP_MODE"] = mode
    # CF-0598/CF-0597: the strike registry of an empty temp root, never the live one.
    argv, sys.argv = sys.argv, ["fetch_footage.py", url, "--ytdlp", str(FAKE),
                                "--rights-root", str(TMP)]
    out, err = io.StringIO(), io.StringIO()
    code = 0
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                ff.main()
            except SystemExit as e:
                # sys.exit(str) prints the message to stderr and exits 1
                if isinstance(e.code, str):
                    print(e.code, file=sys.stderr)
                    code = 1
                else:
                    code = e.code or 0
    finally:
        sys.argv = argv
    return code, out.getvalue(), err.getvalue()


def entries(cache):
    idx = cache / "index.json"
    return json.load(open(idx))["entries"] if idx.exists() else []


def names(cache):
    return sorted(p.name for p in cache.iterdir())


def register(cache, vid, sidecars=True, url=None):
    final = cache / f"{vid}.mp4"
    final.write_bytes(b"m" * 1000)
    if sidecars:
        final.with_suffix(".shots.json").write_text("[]")
        final.with_suffix(".contact.jpg").write_bytes(b"jpg")
        final.with_suffix(".fingerprint.json").write_text("{}")
    idx = {"entries": entries(cache)}
    idx["entries"].append({"id": vid, "url": url or f"https://www.youtube.com/watch?v={vid}",
                           "path": str(final), "official_channel": False,
                           "fetched_at": "2026-09-01T00:00:00+00:00"})
    json.dump(idx, open(cache / "index.json", "w"))
    return final


# --- the failure the RUN_LOG describes ---------------------------------------

def test_failed_download_leaves_no_partial_and_no_entry():
    cache = fresh_cache("fail")
    code, out, err = run_fetch(cache, mode="fail")
    assert code != 0
    assert not [n for n in names(cache) if n.startswith(VID)], names(cache)
    assert not [n for n in names(cache) if n.startswith(ff.TEMP_PREFIX)], names(cache)
    assert entries(cache) == []
    assert "fetched ->" not in out


def test_failure_logs_one_cleanup_line_naming_id_and_removed_files():
    cache = fresh_cache("fail-log")
    code, out, err = run_fetch(cache, mode="fail")
    lines = [l for l in err.splitlines() if l.startswith("CLEANUP ")]
    assert len(lines) == 1, err
    line = lines[0]
    assert line.startswith(f"CLEANUP {VID}: yt-dlp failed, removed "), line
    assert f"{ff.TEMP_PREFIX}{os.getpid()}/" in line, line
    assert line.endswith("; nothing registered"), line
    # yt-dlp's own stderr is still forwarded, before the CLEANUP line
    assert "HTTP Error 403" in err
    # ingest_batch.fetch_source() reports the LAST stderr line as the
    # failure reason - that is the one that has to say what happened.
    last = err.strip().splitlines()[-1]
    assert last.startswith(f"yt-dlp failed for {URL} - removed "), last
    assert "nothing registered" in last


def test_failure_also_removes_old_style_partial_in_cache_root():
    """Belt-and-braces: if a partial of this id is in the cache root (a
    yt-dlp that ignored --paths, or the exact leftover from 2026-09-03),
    the failure path removes it too and says so."""
    cache = fresh_cache("fail-home")
    code, out, err = run_fetch(cache, mode="fail-in-home")
    assert code != 0
    assert not (cache / f"{VID}.f616.mp4").exists()
    assert not [n for n in names(cache) if n.startswith(VID)], names(cache)
    line = [l for l in err.splitlines() if l.startswith("CLEANUP ")][0]
    assert f"{VID}.f616.mp4 (8192B)" in line, line
    assert entries(cache) == []


def test_empty_final_file_is_a_failure_not_a_cache_entry():
    cache = fresh_cache("empty")
    code, out, err = run_fetch(cache, mode="ok-empty")
    assert code != 0
    assert not (cache / f"{VID}.mp4").exists()
    assert not [n for n in names(cache) if n.startswith(VID)], names(cache)
    assert entries(cache) == []
    line = [l for l in err.splitlines() if l.startswith("CLEANUP ")][0]
    assert f"{VID}.mp4 (empty)" in line, line


# --- success -----------------------------------------------------------------

def test_success_registers_exactly_the_final_file():
    cache = fresh_cache("ok")
    code, out, err = run_fetch(cache, mode="ok")
    assert code == 0, err
    final = cache / f"{VID}.mp4"
    assert out.strip().endswith(f"fetched -> {final}"), out
    assert names(cache) == [f"{VID}.mp4", "index.json"], names(cache)
    es = entries(cache)
    assert len(es) == 1 and es[0]["path"] == str(final) and es[0]["id"] == VID
    assert es[0]["url"] == URL and "last_used" in es[0]
    assert "CLEANUP" not in err and "SWEEP" not in err


def test_second_fetch_of_registered_url_is_a_cache_hit():
    cache = fresh_cache("hit")
    run_fetch(cache, mode="ok")
    os.environ["FAKE_YTDLP_MODE"] = "fail"  # must not even be called
    code, out, err = run_fetch(cache, mode="fail")
    assert code == 0, err
    assert out.strip() == f"cached -> {cache / f'{VID}.mp4'}", out
    assert len(entries(cache)) == 1


# --- the startup sweep -------------------------------------------------------

def test_orphan_partial_is_swept_on_next_fetch_with_a_log_line():
    """The exact leftover: `Hk_xChyX9kc.f616.mp4`, registered nowhere,
    disappears when the next real fetch (of anything) starts."""
    cache = fresh_cache("sweep")
    orphan = cache / f"{VID}.f616.mp4"
    orphan.write_bytes(b"x" * 3000)
    (cache / f"{VID}.f140.m4a.part").write_bytes(b"y" * 10)
    code, out, err = run_fetch(cache, url="https://www.youtube.com/watch?v=other000001", mode="ok")
    assert code == 0, err
    assert not orphan.exists()
    assert not (cache / f"{VID}.f140.m4a.part").exists()
    sweeps = [l for l in err.splitlines() if l.startswith("SWEEP ")]
    assert sweeps == [
        f"SWEEP {VID}: orphan partial removed {VID}.f140.m4a.part (10B)",
        f"SWEEP {VID}: orphan partial removed {VID}.f616.mp4 (3000B)",
    ], sweeps
    assert names(cache) == ["index.json", "other000001.mp4"], names(cache)


def test_sweep_never_touches_registered_footage_or_complete_files():
    cache = fresh_cache("sweep-keep")
    final = register(cache, "Z8uvx6isZhU")           # registered + all sidecars
    loose = cache / "unregistered1.mp4"              # complete file, no entry
    loose.write_bytes(b"m" * 500)
    (cache / "underlay").mkdir()                     # standing asset dir
    (cache / "underlay" / "loop.f1.mp4").write_bytes(b"u")  # never looked at
    orphan = cache / f"{VID}.f616.mp4"
    orphan.write_bytes(b"x")
    before = {n: (cache / n).stat().st_size for n in names(cache) if (cache / n).is_file()}
    removed = ff.sweep_partials(log=lambda m: None)
    assert removed == [(orphan.name, 1)], removed
    after = {n: (cache / n).stat().st_size for n in names(cache) if (cache / n).is_file()}
    before.pop(orphan.name)
    assert after == before, (before, after)
    for s in ff.sidecars(final):
        assert s.exists(), s
    assert loose.exists()
    assert (cache / "underlay" / "loop.f1.mp4").exists()
    assert entries(cache)[0]["path"] == str(final)


def test_sweep_removes_stale_temp_dir_but_not_a_live_one():
    cache = fresh_cache("sweep-tmp")
    # A pid that cannot be alive: far above any real pid_max.
    stale = cache / f"{ff.TEMP_PREFIX}99999999"
    stale.mkdir()
    (stale / f"{VID}.f616.mp4.part").write_bytes(b"p" * 2048)
    live = ff.temp_dir_for()  # this very process
    live.mkdir()
    (live / "abc.f616.mp4.part").write_bytes(b"p")
    lines = []
    removed = ff.sweep_partials(log=lines.append)
    assert removed == [(stale.name + "/", 2048)], removed
    assert not stale.exists() and live.exists()
    assert lines == [f"SWEEP: stale temp dir removed {stale.name} (2048B)"], lines
    shutil.rmtree(live)


def test_sweep_without_a_cache_dir_is_a_noop():
    ff.CACHE = TMP / "does-not-exist"
    ff.INDEX = ff.CACHE / "index.json"
    assert ff.sweep_partials(log=lambda m: None) == []


# --- what "cached" means -----------------------------------------------------

def test_partial_names_are_classified_and_sidecars_never_are():
    for n in [f"{VID}.f616.mp4", f"{VID}.f616.mp4.part", f"{VID}.f140.m4a.ytdl",
              f"{VID}.f616.mp4.part-Frag3", f"{VID}.temp.mp4", f"{VID}.mp4.part"]:
        assert ff.partial_id(n) == VID, n
    for n in [f"{VID}.mp4", f"{VID}.shots.json", f"{VID}.contact.jpg",
              f"{VID}.fingerprint.json", "index.json", f"{VID}.webm"]:
        assert ff.partial_id(n) is None, n


def test_cached_means_registered_and_present_and_non_empty():
    cache = fresh_cache("cached")
    idx = {"entries": []}
    assert ff.cached_entry(idx, URL) is None
    # a partial with the right prefix is not a cache hit
    (cache / f"{VID}.f616.mp4").write_bytes(b"x")
    assert ff.cached_entry(idx, URL) is None
    # registered but the file is gone (evicted, deleted by hand) - not a hit
    idx["entries"].append({"id": VID, "url": URL, "path": str(cache / f"{VID}.mp4")})
    assert ff.cached_entry(idx, URL) is None
    # registered, present, but empty - not a hit
    (cache / f"{VID}.mp4").write_bytes(b"")
    assert ff.cached_entry(idx, URL) is None
    (cache / f"{VID}.mp4").write_bytes(b"m")
    assert ff.cached_entry(idx, URL) is idx["entries"][0]


def test_yt_dlp_is_told_a_relative_template_and_a_temp_path():
    """yt-dlp ignores --paths for an absolute -o (YoutubeDL.prepare_filename,
    'paths is ignored since an absolute path is given'), which would put the
    intermediates straight back into the cache root. Pin the command shape."""
    src = (SCRIPTS / "fetch_footage.py").read_text()
    assert '"-o", "%(id)s.%(ext)s"' in src
    assert 'f"home:{CACHE}"' in src and 'f"temp:{tmp}"' in src
    assert '"pre_process:%(id)s"' in src and '"after_move:filepath"' in src


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
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
