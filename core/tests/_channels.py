"""CF-0562: the channel configs a test walks, split by whether the channel has
a pipeline.

`channels/*.json` holds channels with a pipeline (example-film, example-science
since CF-0659, example-tech since CF-0686) and may hold channels that exist
without one yet (`"status": "no_pipeline"`, `shared/channel_ids.py` - none
today). A test that checks
what a pipeline reads (stance, insert layers, narration budget, ...) walks
`pipeline_configs()`; the stubs are named, not skipped in silence:
`stub_configs()` gives them, and a half-stub (an unknown `status`, a stub that
still carries `run_plan`) raises here instead of being filtered out.

    from _channels import pipeline_configs, stub_configs
    for path, cfg in pipeline_configs(CHANNELS).items(): ...
"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

__all__ = ["pipeline_configs", "stub_configs", "no_pipeline_reason", "stand_in_theme"]


def stand_in_theme():
    """CF-0572: a valid `theme` block for a stand-in channel config (every
    channel config carries one, a stub too - `shared/channel_data.py`
    theme_errors). Made-up colours, nobody's brand; a fresh copy per call."""
    return {
        "bg": "#101010", "accent": "#F0C020", "accent2": "#3060E0",
        "text": "#FAFAFA", "muted": "#A0A0A0",
        "card_ground": ["#303030", "#202020", "#101010"],
        "end_card_ground": ["#383838", "#282828", "#181818"],
        "badge": {"paper": "#F0F0F0", "ink": "#202020", "ink_muted": "#606060",
                  "rule": "#C0C0C0", "accent": "#C03030", "accent_ink": "#FFFFFF"},
        "font": {"display": "Arial, sans-serif", "text": "Arial, sans-serif",
                 "card": "Arial, sans-serif", "badge": "Courier, monospace"},
        "picked": ["bg"], "note": "test stand-in",
    }


def _ids():
    spec = importlib.util.spec_from_file_location(
        "channel_ids_for_tests", ROOT / "shared" / "channel_ids.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_IDS = _ids()


def no_pipeline_reason(cfg, channel=None):
    return _IDS.no_pipeline_reason(cfg, channel)


def _split(channels_dir):
    with_pipe, stubs = {}, {}
    for p in sorted(Path(channels_dir).glob("*.json")):
        cfg = json.loads(p.read_text(encoding="utf-8"))
        (stubs if no_pipeline_reason(cfg, p.stem) else with_pipe)[p] = cfg
    return with_pipe, stubs


def pipeline_configs(channels_dir=ROOT / "channels"):
    """{path: config} of every channel with a pipeline."""
    return _split(channels_dir)[0]


def stub_configs(channels_dir=ROOT / "channels"):
    """{path: config} of every `status: no_pipeline` channel."""
    return _split(channels_dir)[1]
