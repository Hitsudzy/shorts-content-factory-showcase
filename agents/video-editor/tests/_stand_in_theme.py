"""CF-0572: a channel theme for stand-in channel configs.

`build_render_plan.py` refuses a channel without a `theme` (the on-screen
palette is the channel's, `scripts/channel_theme.py`), so every stand-in
config a test hands the planner carries this one. It is nobody's palette - a
made-up valid block (the root's `shared/channel_data.py theme_errors` passes
it: every key, #RRGGBB, the contrast floors) - so a test cannot pass by
drawing ExampleFilm's colours by accident.
"""
import copy

STAND_IN_THEME = {
    "bg": "#101418",
    "accent": "#F0A030",
    "accent2": "#3070D0",
    "text": "#F8F8F0",
    "muted": "#A0A8B0",
    "card_ground": ["#283038", "#181E24", "#101418"],
    "end_card_ground": ["#303840", "#20262C", "#181C20"],
    "badge": {"paper": "#E8E8DC", "ink": "#202020", "ink_muted": "#606060",
              "rule": "#C8C8BC", "accent": "#B03020", "accent_ink": "#FFFFFF"},
    "font": {"display": "\"Arial Black\", sans-serif",
             "text": "Helvetica, Arial, sans-serif",
             "card": "Helvetica, Arial, sans-serif",
             "badge": "\"Courier Prime\", monospace"},
    "procedural_palettes": [{"bg": "#0A0A20", "a": "#20C0A0", "b": "#C02080", "c": "#E0E040"}],
}


def stand_in_theme():
    """A fresh copy (a test may change it)."""
    return copy.deepcopy(STAND_IN_THEME)


def with_theme(cfg):
    """`cfg` with the stand-in theme added (a new dict; a theme already there
    stays)."""
    return {"theme": stand_in_theme(), **cfg}
