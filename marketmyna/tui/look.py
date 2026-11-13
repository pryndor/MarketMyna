"""Colour themes for the terminal app.

Each theme sets Textual's base colours plus a few of our own variables that
the CSS uses ($rail-bg, $heading, ...). PAL holds the colours of the active
theme for text built in Python (rich Text: gains, losses, labels, figures).
"""

from __future__ import annotations

from typing import Any

THEMES: dict[str, dict[str, Any]] = {
    # Deep-space navy, cyan glow, silver icon rail.
    "neon": {
        "base": dict(primary="#00E5FF", secondary="#FF2E97", accent="#7C4DFF", warning="#FFB020",
                     error="#FF3B5C", success="#00FF9C", foreground="#DDE6F5", background="#05070D",
                     surface="#0A0F1C", panel="#141C33", boost="#0E1528", dark=True),
        "vars": {"rail-bg": "#B9C0CB", "rail-fg": "#0A0F1C", "rail-hover": "#D6DBE3", "rail-active-bg": "#00E5FF",
                 "rail-active-fg": "#001018", "rail-edge": "#7E8794", "heading": "#00E5FF", "figure": "#7DD3FC",
                 "muted": "#6B7A99", "line": "#1E2A4A", "glow": "#00E5FF", "bar-bg": "#03050A",
                 "tape-bg": "#070B16", "row-even": "#0A1120", "panel-bg": "#070B15", "brand-2": "#FF2E97"},
    },
    # Classic research terminal: black, amber headings, cyan figures.
    "amber": {
        "base": dict(primary="#FF9F1C", secondary="#38BDF8", accent="#FF9F1C", warning="#F59E0B",
                     error="#EF4444", success="#22C55E", foreground="#E5E7EB", background="#0A0A0A",
                     surface="#101010", panel="#2A2A2A", boost="#161616", dark=True),
        "vars": {"rail-bg": "#C0C0C0", "rail-fg": "#111111", "rail-hover": "#D8D8D8", "rail-active-bg": "#FF9F1C",
                 "rail-active-fg": "#000000", "rail-edge": "#8A8A8A", "heading": "#FF9F1C", "figure": "#38BDF8",
                 "muted": "#9CA3AF", "line": "#2A2A2A", "glow": "#FF9F1C", "bar-bg": "#050505",
                 "tape-bg": "#0C0C0C", "row-even": "#121212", "panel-bg": "#0D0D0D", "brand-2": "#E5E7EB"},
    },
    # Light: brushed silver panels, gunmetal rail, blue accents.
    "silver": {
        "base": dict(primary="#0F62FE", secondary="#7C3AED", accent="#0F62FE", warning="#B45309",
                     error="#DC2626", success="#059669", foreground="#111827", background="#E6EAF0",
                     surface="#F4F6F9", panel="#C9CFD8", boost="#DDE2E9", dark=False),
        "vars": {"rail-bg": "#2B3240", "rail-fg": "#E5E7EB", "rail-hover": "#3A4354", "rail-active-bg": "#0F62FE",
                 "rail-active-fg": "#FFFFFF", "rail-edge": "#1C222C", "heading": "#0F62FE", "figure": "#075985",
                 "muted": "#6B7280", "line": "#B8C0CC", "glow": "#0F62FE", "bar-bg": "#D3D9E2",
                 "tape-bg": "#DCE1E8", "row-even": "#EEF1F5", "panel-bg": "#FFFFFF", "brand-2": "#7C3AED"},
    },
}
ORDER = list(THEMES)
DEFAULT = "neon"

PAL: dict[str, str] = {}


def textual_theme(name: str) -> Any:
    from textual.theme import Theme

    t = THEMES[name]
    return Theme(name=f"marketmyna-{name}", variables=dict(t["vars"]), **t["base"])


def use(name: str) -> str:
    """Make name the palette for Python-built text; returns the Textual theme name."""
    t = THEMES.get(name) or THEMES[DEFAULT]
    b, v = t["base"], t["vars"]
    PAL.clear()
    PAL.update(up=b["success"], down=b["error"], flat=b["warning"], primary=b["primary"], heading=v["heading"],
               figure=v["figure"], muted=v["muted"], fg=b["foreground"], brand2=v["brand-2"], accent=b["accent"],
               secondary=b["secondary"])
    return f"marketmyna-{name if name in THEMES else DEFAULT}"


use(DEFAULT)
