#!/usr/bin/env python3
"""CF-0154: the reminder about the two files a channel's owner brings.

The ending clip (CF-0141) and the ambient bed (CF-0153) are the two assets the
factory cannot produce - the user brings them - and both are optional, each
degrading to a floor the factory does own. Until CF-0154 there was nowhere to
learn that when a channel was set up.

There is no channel-creation script to hang the reminder on: CF-0016 creates
the channel on YouTube, not the directory here, and `channels/example-film/`
was assembled by hand over fifteen commits. So the reminder is printed by
`inserts/validate_inserts.py`, which holds the one loop in the root that walks
every channel config - and which a channel config has to pass to be legal at
all, so a new channel meets the reminder by construction rather than by good
will. The reasoning and the alternatives are in
tasks/CF-0154-channel-init-asset-reminder.md.

What these tests hold to:

  * a channel with neither file is reminded of both;
  * every reminder names the path to put the file at AND what its absence
    costs - the acceptance's sharp half, because "put a file here" with no
    consequence reads as a hard requirement and neither file is one;
  * the consequence is stated as a degradation, never as a breakage;
  * a file that is there is not nagged about, by any of its legal names or
    through the config override;
  * the reminder is a report: it carries no errors and cannot move the
    validator's exit code.
"""
import ast
import json
import subprocess
import sys
import tempfile
from _tmproot import tmp_root   # noqa: E402  (CF-0378: this file's temp trees go at exit)
_TMP = tmp_root("channel-asset-reminder-test-")
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "patterns"))
sys.path.insert(0, str(ROOT / "inserts"))

import validate_patterns as vp  # noqa: E402
import validate_inserts as vi  # noqa: E402

EDITOR = ROOT / "agents" / "video-editor" / "scripts"
CHANNEL = "brand-new-channel"


def _root_with_channel(files=()):
    """A throwaway factory root holding one channel directory."""
    tmp = Path(tempfile.mkdtemp(dir=_TMP))
    (tmp / "channels" / CHANNEL).mkdir(parents=True)
    for name in files:
        (tmp / "channels" / CHANNEL / name).write_bytes(b"x")
    return tmp


def _reminder(cfg=None, files=(), root=None):
    root = _root_with_channel(files) if root is None else root
    return vp.channel_asset_reminder(cfg or {}, CHANNEL, root=root)


def _block(lines, asset):
    """The lines of one asset's entry, up to the next asset's."""
    starts = [i for i, l in enumerate(lines)
              if l.strip().startswith(tuple(vp.CHANNEL_BROUGHT_ASSETS))]
    for n, i in enumerate(starts):
        if lines[i].strip().startswith(asset):
            end = starts[n + 1] if n + 1 < len(starts) else len(lines)
            return "\n".join(lines[i:end])
    raise AssertionError(f"no {asset} entry in:\n" + "\n".join(lines))


def test_a_channel_with_neither_file_is_reminded_of_both():
    """The acceptance's first line. A channel set up from scratch has neither
    file, and both have to be named - one reminder is a reminder about one
    file, and the user has two to bring."""
    lines = _reminder()
    for asset in ("ending", "ambient"):
        assert "ABSENT" in _block(lines, asset), (
            f"{asset} is not reported absent for a channel that has no files:\n"
            + "\n".join(lines))


def test_the_reminder_names_the_path_and_the_consequence():
    """The acceptance's second line, and the whole point of the task: not
    "put a file here" but where, and what happens if you do not."""
    lines = _reminder()
    ending, ambient = _block(lines, "ending"), _block(lines, "ambient")
    assert f"channels/{CHANNEL}/ending.mp4" in ending, ending
    assert f"channels/{CHANNEL}/ambient." in ambient, ambient
    for asset, block, floor in (("ending", ending, "end card"),
                                ("ambient", ambient, "generates a bed")):
        assert "without it:" in block, f"{asset}: no consequence at all:\n{block}"
        assert floor in block, (
            f"{asset}: the consequence does not name the floor it falls to "
            f"({floor!r}):\n{block}")


def test_the_consequence_is_a_degradation_and_says_so():
    """Both files are optional. A reminder that reads as a hard requirement
    would be a lie: the factory has a floor under each of them and goes on
    producing videos without either."""
    lines = _reminder()
    for asset in ("ending", "ambient"):
        # The prose is wrapped to the terminal, so the phrase is looked for in
        # the block with its line breaks squeezed out.
        block = " ".join(_block(lines, asset).split())
        assert "Nothing breaks" in block, (
            f"{asset}: the reminder does not say the channel keeps working "
            f"without the file, so it reads as a requirement:\n{block}")


def test_a_file_that_is_there_is_not_nagged_about():
    lines = _reminder(files=("ending.mp4",))
    assert "ok" in _block(lines, "ending"), lines
    assert "ABSENT" in _block(lines, "ambient"), lines


def test_every_ambient_extension_the_editor_decodes_is_recognised():
    """The stem is fixed and the extension is not - the user brings whatever
    their source gave them (CF-0153). A reminder that kept nagging about a
    file already on disk under a legal name would train the user to ignore
    the whole section."""
    for ext in vp.CHANNEL_AMBIENT_EXTS:
        lines = _reminder(files=(f"ambient{ext}",))
        assert "ok" in _block(lines, "ambient"), f"ambient{ext}: {lines}"


def test_the_config_override_is_followed():
    """`video_editor.<asset>.path` (CF-0153) moves the file; the reminder has
    to look where the Editor will look, or it nags about a file the channel
    has deliberately put elsewhere."""
    root = _root_with_channel()
    other = root / "elsewhere" / "closing.mp4"
    other.parent.mkdir()
    other.write_bytes(b"x")
    cfg = {"video_editor": {"ending": {"path": "elsewhere/closing.mp4"}}}
    block = _block(_reminder(cfg=cfg, root=root), "ending")
    assert "ok" in block and "elsewhere/closing.mp4" in block, block
    assert "override" in block, block
    cfg = {"video_editor": {"ending": {"path": "elsewhere/missing.mp4"}}}
    block = _block(_reminder(cfg=cfg, root=root), "ending")
    assert "ABSENT" in block and "elsewhere/missing.mp4" in block, block


def test_a_blank_override_falls_back_to_the_convention():
    """The readers all test `isinstance(str) and strip()` before using an
    override and fall through to the convention when it fails (CF-0153). The
    reminder reads the config the same way, or it would name a path nobody
    will ever read from."""
    root = _root_with_channel(files=("ending.mp4",))
    for bad in ({"path": ""}, {"path": None}, {"paht": "x.mp4"}, {}, "x.mp4"):
        block = _block(_reminder(cfg={"video_editor": {"ending": bad}},
                                 root=root), "ending")
        assert f"channels/{CHANNEL}/ending.mp4" in block, f"{bad!r}: {block}"


def test_logo_is_not_on_the_list():
    """`logo.<ext>` (CF-0117) is brought by a human too, but its absence only
    picks which of the two drawn cards you get - it costs the channel no
    layer. Adding it here would make the reminder a list of everything a
    channel could have, which is how a reminder stops being read."""
    assert set(vp.CHANNEL_BROUGHT_ASSETS) == {"ending", "ambient"}, (
        "CF-0154 reminds about the two files the factory cannot produce and "
        "whose absence costs a layer, not about every optional channel file")


def test_the_reminder_is_a_report_and_never_an_error():
    """It is not part of `validate_vocabulary()`. A channel without these
    files is a channel that sounds and looks worse than it could - not an
    invalid one - and no exit code may say otherwise."""
    before = vi.validate_vocabulary()
    lines = vi.channel_asset_reminder_lines()
    assert lines and vi.validate_vocabulary() == before, (
        "the reminder changed what the validator considers an error")
    joined = " ".join(" ".join(lines).lower().split())
    # `AmbientBedError` is named on purpose - it is what happens to a *wrong*
    # file, not to a missing one - so the class name is not what is looked for
    # here; the vocabulary of a verdict about the absence is.
    for word in ("error(s)", "invalid", " must ", "is required"):
        assert word not in joined, f"the reminder reads as a verdict: {word!r}"


def test_running_the_validator_prints_the_reminder_and_still_exits_zero():
    """End to end, the way a person adding a channel meets it: the config has
    to pass this validator to be legal, and running it prints the section."""
    proc = subprocess.run([sys.executable, str(ROOT / "inserts" / "validate_inserts.py")],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert vp.CHANNEL_ASSET_REMINDER_HEADING in proc.stdout, proc.stdout
    for asset in vp.CHANNEL_BROUGHT_ASSETS:
        assert f"    {asset:<8} " in proc.stdout, (asset, proc.stdout)




def test_the_root_copies_agree_with_the_editor():
    """The root may not import the Editor, so the file names live here twice.
    Skipped when agents/ is not in the checkout (a worktree; the root
    .gitignore excludes it) - where it is, both constants are read off the
    Editor's own source so the two repos cannot drift apart silently."""
    if not EDITOR.exists():
        return
    found = {}
    for module, name in (("ambient_bed.py", "AMBIENT_EXTS"),
                         ("end_card.py", "ENDING_NAME")):
        tree = ast.parse((EDITOR / module).read_text())
        for node in tree.body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and getattr(node.targets[0], "id", None) == name):
                found[name] = ast.literal_eval(node.value)
    assert found.get("ENDING_NAME") == vp.CHANNEL_ENDING_NAME, (
        f"end_card.ENDING_NAME is {found.get('ENDING_NAME')!r}, the root's copy "
        f"is {vp.CHANNEL_ENDING_NAME!r} - the reminder would name the wrong file")
    assert tuple(found.get("AMBIENT_EXTS", ())) == vp.CHANNEL_AMBIENT_EXTS, (
        f"ambient_bed.AMBIENT_EXTS is {found.get('AMBIENT_EXTS')!r}, the root's "
        f"copy is {vp.CHANNEL_AMBIENT_EXTS!r} - the reminder would nag about a "
        f"file the Editor already reads, or promise one it cannot decode")


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
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
