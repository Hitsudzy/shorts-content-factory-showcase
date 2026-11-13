"""CF-0572: the composition (render/src/Video.jsx) rendered to static markup
under plain node - every colour and face the frame draws is an inline style,
so the markup is what a theme change can be compared on without a browser.

`render_markup(src_dir, cases)` bundles `<src_dir>/Video.jsx` with esbuild
(render/node_modules - the render's own toolchain, no network) against the
`remotion` stand-in in fixtures/cf0572_theme/, runs it under node and returns
one {html} or {error} per case ({plan, frame}). `src_dir` is this repo's
render/src, or a copy of an older one (the copy needs render/node_modules
beside it - `node_modules_beside()` links it).
"""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
RENDER = AGENT_ROOT / "render"
SRC = RENDER / "src"
NODE_MODULES = RENDER / "node_modules"
ESBUILD = NODE_MODULES / ".bin" / "esbuild"
REMOTION_ESM = NODE_MODULES / "remotion" / "dist" / "esm" / "index.mjs"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "cf0572_theme"
NODE = shutil.which("node")


class MarkupUnavailable(AssertionError):
    """No node or no render toolchain: the check did not run (a FAIL, not a
    skip - the theme lives in JavaScript)."""


def node_modules_beside(src_dir):
    """Link render/node_modules next to a copied `src_dir` (its parent), so
    the copy resolves react and remotion the way render/src does."""
    link = Path(src_dir).parent / "node_modules"
    if not link.exists():
        link.symlink_to(NODE_MODULES, target_is_directory=True)


def render_markup(src_dir, cases, timeout=120):
    if not NODE or not ESBUILD.exists() or not REMOTION_ESM.exists():
        raise MarkupUnavailable(
            f"node ({NODE}) and render/node_modules (esbuild, remotion) are needed "
            f"to render the composition's markup - run `npm ci` in {RENDER}")
    src_dir = Path(src_dir).resolve()
    with tempfile.TemporaryDirectory(prefix="ve-cf0572-markup-") as tmp:
        tmp = Path(tmp)
        stub = (FIXTURE / "remotion_stub.jsx").read_text().replace(
            "__REMOTION_ESM__", str(REMOTION_ESM))
        entry = (FIXTURE / "entry.jsx").read_text().replace(
            "__VIDEO__", str(src_dir / "Video.jsx"))
        # Both next to the source tree so react resolves from the same
        # node_modules as the components (one React instance).
        work = src_dir.parent / f".cf0572-markup-{os.getpid()}"
        work.mkdir(exist_ok=True)
        try:
            (work / "remotion_stub.jsx").write_text(stub)
            (work / "entry.jsx").write_text(entry)
            bundle = tmp / "bundle.cjs"
            built = subprocess.run(
                [str(ESBUILD), str(work / "entry.jsx"), "--bundle", "--platform=node",
                 "--format=cjs", "--loader:.js=jsx", "--jsx=automatic",
                 f"--alias:remotion={work / 'remotion_stub.jsx'}",
                 f"--outfile={bundle}", "--log-level=error"],
                capture_output=True, text=True, timeout=timeout, cwd=src_dir.parent)
            if built.returncode != 0:
                raise AssertionError(f"esbuild failed: {built.stderr[-2000:]}")
        finally:
            shutil.rmtree(work, ignore_errors=True)
        cases_path = tmp / "cases.json"
        cases_path.write_text(json.dumps(cases))
        ran = subprocess.run([NODE, str(bundle), str(cases_path)], capture_output=True,
                             text=True, timeout=timeout, env={**os.environ, "NODE_ENV": "production"})
        if ran.returncode != 0:
            raise AssertionError(f"node failed: {ran.stderr[-2000:]}")
        return json.loads(ran.stdout)
