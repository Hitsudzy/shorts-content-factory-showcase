#!/usr/bin/env python3
"""CF-0114: restore the media files an insert index lists but the folder lacks.

    python3 scripts/fetch_inserts.py                  # every folder
    python3 scripts/fetch_inserts.py --kind meme      # one folder
    python3 scripts/fetch_inserts.py --dry-run        # say what would be fetched
    python3 scripts/fetch_inserts.py --only meme-id   # one entry

Media under shared/inserts/ is not tracked, so a fresh checkout has the
indexes and no files. This script walks each index, and for every entry
whose `file` is missing downloads it from `download_url`, or - when there is
none - from `source_url`: a Wikimedia Commons `File:` page is resolved to its
original through the Commons API (one request, then the download); any other
URL is fetched as-is and has to be the file itself. A meme with a `clip`
span is a GIF the factory cut from the video at `source_url`: there is no
file to download, so it is reported with the span to recut and counted as
failed, never fetched as a web page.

Polite by construction (CF-0045): one identifying User-Agent, one request at
a time, a pause between downloads, a hard timeout, and nothing is written
until the whole body has arrived. It never touches an entry whose file is
already there, so it is safe to re-run. It fetches only what the index
already records - it is not a discovery tool, and adding entries stays a
person's job (inserts/POLICY.md, CF-0115).

Stdlib only.
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "shared" / "inserts"))
import inserts_lib as lib  # noqa: E402

USER_AGENT = ("shorts-content-factory/CF-0114 fetch_inserts "
              "(https://example.com/shorts-content-factory; contact@example.com)")
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
COMMONS_PAGE_PREFIXES = ("https://commons.wikimedia.org/wiki/File:",
                         "https://commons.m.wikimedia.org/wiki/File:")
DEFAULT_DELAY = 1.5
TIMEOUT = 60
MAX_BYTES = 64 * 1024 * 1024


def _get(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(MAX_BYTES + 1)


def commons_original_url(page_url):
    """The original-file URL behind a Commons File: page, via the API."""
    title = urllib.parse.unquote(page_url.split("/wiki/", 1)[1])
    query = urllib.parse.urlencode({
        "action": "query", "titles": title, "prop": "imageinfo",
        "iiprop": "url", "format": "json"})
    data = json.loads(_get(f"{COMMONS_API}?{query}"))
    for page in data.get("query", {}).get("pages", {}).values():
        info = page.get("imageinfo")
        if info:
            return info[0]["url"].split("?", 1)[0]
    raise RuntimeError(f"Commons has no file behind {page_url}")


def resolve_download_url(entry):
    if entry.get("download_url"):
        return entry["download_url"]
    src = entry["source_url"]
    if src.startswith(COMMONS_PAGE_PREFIXES):
        return commons_original_url(src)
    return src


def fetch_entry(entry, folder, dry_run=False, log=print):
    """Download one entry's file into folder. Returns True when fetched."""
    target = folder / entry["file"]
    if entry.get("clip"):
        c = entry["clip"]
        raise RuntimeError(f"cut from a video, not a file: recut {entry['source_url']} "
                           f"{c['start_s']}-{c['end_s']} s into {target.name} (silent GIF)")
    url = resolve_download_url(entry)
    if dry_run:
        log(f"  would fetch {entry['id']}: {url} -> {target.name}")
        return False
    body = _get(url)
    if len(body) > MAX_BYTES:
        raise RuntimeError(f"{url} exceeds {MAX_BYTES} bytes")
    tmp = target.with_name(target.name + ".part")
    tmp.write_bytes(body)
    tmp.replace(target)
    log(f"  fetched {entry['id']}: {len(body) // 1024} KB -> {target.name}")
    return True


def fetch_kind(kind, root, delay=DEFAULT_DELAY, dry_run=False, only=None, log=print,
               bank=None):
    """`bank` (CF-0393): a channel's own meme bank, memes-<channel>."""
    folder = lib.folder_for(kind, root, bank)
    index = lib.load_index(kind, root, bank)
    missing = [e for e in index["entries"]
               if isinstance(e, dict) and isinstance(e.get("file"), str)
               and not (folder / e["file"]).exists()
               and (only is None or e.get("id") in only)]
    log(f"{kind}: {len(index['entries'])} entries, {len(missing)} missing")
    fetched, failed = 0, []
    for i, entry in enumerate(missing):
        try:
            if fetch_entry(entry, folder, dry_run, log):
                fetched += 1
        except Exception as exc:  # noqa: BLE001
            failed.append(entry.get("id"))
            log(f"  FAILED {entry.get('id')}: {exc}")
        if not dry_run and i < len(missing) - 1:
            time.sleep(delay)
    return fetched, failed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--kind", choices=sorted(lib.KIND_FOLDERS), action="append")
    ap.add_argument("--root", default=str(lib.INSERTS_ROOT))
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                    help=f"seconds between downloads (default {DEFAULT_DELAY})")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", action="append", help="entry id(s) to fetch")
    ap.add_argument("--bank", help="CF-0393: also restore this channel meme bank "
                                   "(memes-<channel>), or every bank with --bank all")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    total_failed = []
    if args.bank:
        banks = lib.meme_banks(root) if args.bank == "all" else [args.bank]
        for bank in banks:
            try:
                bank, _ = lib.meme_bank_folder(None, root, bank=bank)
            except lib.MemeBankError as e:
                ap.error(str(e))
            _, failed = fetch_kind("meme", root, args.delay, args.dry_run, args.only, bank=bank)
            total_failed += failed
    for kind in args.kind or sorted(lib.KIND_FOLDERS):
        if not lib.index_path(kind, root).exists():
            continue
        _, failed = fetch_kind(kind, root, args.delay, args.dry_run, args.only)
        total_failed += failed
    if total_failed:
        print(f"{len(total_failed)} download(s) failed: {', '.join(map(str, total_failed))}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
