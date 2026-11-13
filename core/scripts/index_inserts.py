#!/usr/bin/env python3
"""CF-0114: bring shared/inserts/*/index.json up to date and validate it.

    python3 scripts/index_inserts.py                 # all three folders
    python3 scripts/index_inserts.py --kind meme     # one folder
    python3 scripts/index_inserts.py --no-embed      # skip CLIP (stdlib only)
    python3 scripts/index_inserts.py --force         # recompute what is there
    python3 scripts/index_inserts.py --strict        # a missing file is an error

For every entry: a sound gets `duration_s` measured (WAV header, else
ffprobe); an image, GIF (first frame) or loop video (one frame via ffmpeg)
gets `embedding`. Then the index is validated against
shared/inserts/inserts_lib.py and written back only if something changed -
a second run is a no-op, and an index with errors is reported and *not*
written, so a bad entry never lands on disk half-fixed.

Embeddings are computed the way agents/footage-indexer/scripts/index_footage.py
computes them, deliberately replicated rather than imported (that repo is not
a package): `openai/clip-vit-base-patch32` through transformers on CPU under
torch.no_grad(), image features L2-normalised, 512 floats rounded to 5
decimals under the field name `embedding`. A text query embedded the same way
(`embed_texts` below, or match_anchors.py's own) ranks these entries by dot
product, so CF-0067's meme matching can reuse match_anchors' arithmetic.

Needs a venv with torch, transformers and Pillow for the embedding step
(the footage-indexer's own, or one made in the repo root). Everything else
is stdlib.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "shared" / "inserts"))
import inserts_lib as lib  # noqa: E402

MODEL = lib.EMBEDDING_MODEL


# --------------------------------------------------------------------------
# CLIP - same recipe as index_footage.py / match_anchors.py
# --------------------------------------------------------------------------

def clip_model():
    """Memoised (model, processor, tokenizer). Loads from the HF cache;
    no network once the model has been fetched once."""
    if not hasattr(clip_model, "_cached"):
        import torch  # noqa: F401  (import error surfaces here, once)
        from transformers import CLIPModel, CLIPProcessor, CLIPTokenizer
        model = CLIPModel.from_pretrained(MODEL).eval()
        processor = CLIPProcessor.from_pretrained(MODEL)
        tokenizer = CLIPTokenizer.from_pretrained(MODEL)
        clip_model._cached = (model, processor, tokenizer)
    return clip_model._cached


def _rounded(vecs):
    return [[round(float(x), lib.EMBEDDING_DECIMALS) for x in row] for row in vecs.tolist()]


def embed_images(paths):
    """L2-normalised CLIP image vectors, one list of 512 floats per path.
    GIFs and other multi-frame images contribute their first frame."""
    import torch
    from PIL import Image
    model, processor, _ = clip_model()
    images = []
    for p in paths:
        with Image.open(p) as im:
            im.seek(0)
            images.append(im.convert("RGB"))
    with torch.no_grad():
        inputs = processor(images=images, return_tensors="pt")
        vecs = model.get_image_features(**inputs)
        vecs = vecs / vecs.norm(dim=-1, keepdim=True)
    return _rounded(vecs)


def embed_texts(texts):
    """L2-normalised CLIP text vectors - the query side of
    lib.rank_by_embedding, identical to match_anchors.py's text path."""
    import torch
    model, _, tokenizer = clip_model()
    with torch.no_grad():
        inputs = tokenizer(list(texts), padding=True, truncation=True, return_tensors="pt")
        vecs = model.get_text_features(**inputs)
        vecs = vecs / vecs.norm(dim=-1, keepdim=True)
    return _rounded(vecs)


def video_frame(path, at_seconds=1.0):
    """One frame of a loop video as a temporary PNG (caller deletes)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", str(at_seconds), "-i", str(path),
           "-frames:v", "1", tmp.name]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if out.returncode != 0 or not Path(tmp.name).stat().st_size:
        # A clip shorter than at_seconds: take its first frame instead.
        cmd[4:6] = ["-ss", "0"]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if out.returncode != 0:
            Path(tmp.name).unlink(missing_ok=True)
            raise RuntimeError(f"ffmpeg could not read a frame of {path}: {out.stderr.strip()}")
    return Path(tmp.name)


# --------------------------------------------------------------------------
# one folder
# --------------------------------------------------------------------------

def update_kind(kind, root, embed=True, force=False, strict=False, log=print, bank=None):
    """Measure / embed / validate one folder. Returns (changed, errors).
    `bank` (CF-0393) is a channel's own meme bank, memes-<channel>."""
    folder = lib.folder_for(kind, root, bank)
    path = lib.index_path(kind, root, bank)
    if not path.exists():
        log(f"{kind}: no {path.relative_to(root) if path.is_relative_to(root) else path} - skipped")
        return False, []
    index = json.loads(path.read_text())
    before = json.dumps(index, sort_keys=True, ensure_ascii=False)
    errors = []
    entries = index.get("entries", [])
    if not isinstance(entries, list):
        return False, ["entries must be a list"]

    missing = []
    to_embed = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
            continue
        f = folder / entry["file"]
        if not f.exists():
            missing.append(entry.get("id", entry["file"]))
            continue
        suffix = f.suffix.lower()
        if kind == "sound":
            if force or entry.get("duration_s") is None:
                try:
                    entry["duration_s"] = round(lib.measure_duration(f), 3)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{kind}:{entry.get('id')}: could not measure duration: {exc}")
        elif embed and (force or entry.get("embedding") is None):
            if suffix in lib.IMAGE_SUFFIXES or (kind == "loop" and suffix in lib.VIDEO_SUFFIXES):
                to_embed.append((entry, f))

    if to_embed:
        temps = []
        batch_paths = []
        try:
            for entry, f in to_embed:
                if f.suffix.lower() in lib.VIDEO_SUFFIXES:
                    frame = video_frame(f)
                    temps.append(frame)
                    batch_paths.append(frame)
                else:
                    batch_paths.append(f)
            log(f"{kind}: embedding {len(batch_paths)} file(s) with {MODEL}")
            for start in range(0, len(batch_paths), 16):
                chunk = batch_paths[start:start + 16]
                vecs = embed_images(chunk)
                for (entry, _), vec in zip(to_embed[start:start + 16], vecs):
                    entry["embedding"] = vec
            index["embedding_model"] = MODEL
        finally:
            for t in temps:
                t.unlink(missing_ok=True)

    if missing:
        msg = f"{kind}: {len(missing)} indexed file(s) not on disk: {', '.join(missing[:8])}" \
              f"{' ...' if len(missing) > 8 else ''} (scripts/fetch_inserts.py restores them)"
        if strict:
            errors.append(msg)
        else:
            log("  note: " + msg)

    errors += lib.validate_index(index, kind, folder if strict else None)
    if errors:
        return False, errors
    changed = json.dumps(index, sort_keys=True, ensure_ascii=False) != before
    if changed:
        lib.save_index(index, kind, root, bank)
    return changed, []


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--kind", choices=sorted(lib.KIND_FOLDERS), action="append",
                    help="folder(s) to process; default all")
    ap.add_argument("--root", default=str(lib.INSERTS_ROOT), help="library root")
    ap.add_argument("--no-embed", action="store_true", help="skip CLIP embeddings")
    ap.add_argument("--force", action="store_true", help="recompute embeddings and durations")
    ap.add_argument("--strict", action="store_true", help="a missing media file is an error")
    ap.add_argument("--bank", help="CF-0393: a channel's own meme bank (memes-<channel>); "
                                   "implies --kind meme")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    kinds = args.kind or sorted(lib.KIND_FOLDERS)
    bank = None
    if args.bank:
        if args.kind and args.kind != ["meme"]:
            ap.error("--bank is a meme bank: only --kind meme goes with it")
        try:
            bank, _ = lib.meme_bank_folder(None, root, bank=args.bank)
        except lib.MemeBankError as e:
            ap.error(str(e))
        kinds = ["meme"]
    failed = 0
    for kind in kinds:
        changed, errors = update_kind(kind, root, embed=not args.no_embed,
                                      force=args.force, strict=args.strict, bank=bank)
        n = len(lib.load_index(kind, root, bank)["entries"])
        if errors:
            failed += 1
            print(f"{kind}: {n} entries - {len(errors)} error(s), index NOT written")
            for e in errors:
                print("  " + e)
        else:
            print(f"{kind}: {n} entries - {'updated' if changed else 'up to date'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
