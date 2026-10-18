"""Smooth-UI guards over web/src (plain text checks, no Node): one loading pattern (the running
rabbit, shown only after 300 ms), buttons that keep their size while busy, tabs kept mounted
once visited, and forms whose save button stays reachable."""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "web" / "src"


def tsx() -> list[tuple[Path, str]]:
    return [(p, p.read_text()) for p in SRC.rglob("*.tsx")]


def test_no_ad_hoc_loading_text() -> None:
    """Loading states use RabbitLoader or skeletons, not a bare "Loading…" string."""
    bad = []
    for p, s in tsx():
        for m in re.finditer(r">\s*Loading(?:…|\.\.\.)?\s*<", s):
            bad.append(f"{p.relative_to(SRC)}: {m.group(0)!r}")
    assert not bad, bad


def test_loader_waits_300ms_before_showing() -> None:
    css = (SRC / "styles" / "globals.css").read_text()
    block = css[css.index(".rabbit-loader {"):]
    block = block[:block.index("}")]
    m = re.search(r"animation:\s*rl-appear\s+[\d.]+s\s+\S+\s+([\d.]+)s", block)
    assert m and float(m.group(1)) >= 0.3, block
    assert "rl-show" in css  # reduced motion: no movement, same delay


def test_busy_buttons_keep_their_size() -> None:
    s = (SRC / "components" / "ui" / "button.tsx").read_text()
    assert "invisible" in s and "absolute animate-spin" in s


def test_tabs_stay_mounted_once_visited() -> None:
    s = (SRC / "screens" / "Chat.tsx").read_text()
    for tab in ("plan", "feed", "clubs", "progress"):
        assert f"visited.has('{tab}')" in s, tab
        assert f"tab === '{tab}' && <div className=\"tab-page" not in s, tab
    assert "data-tab-hidden" in s and "TAB_SHOWN_EVENT" in s
    overlays = (SRC / "lib" / "overlays.ts").read_text()
    assert overlays.count("[data-tab-hidden]") >= 2


def test_session_sheet_save_is_pinned() -> None:
    s = (SRC / "components" / "plan" / "SessionSheet.tsx").read_text()
    head = s[s.index("<Sheet title={session ? session.title : 'Add a workout'}"):]
    head = head[:head.index("bodyClassName")]
    assert "footer=" in head and "Add workout" in head


def test_tab_bar_children_never_take_the_tap() -> None:
    # The Home tab's rabbit remounts on pointer-down (twitch); if it took the tap, the click was lost.
    css = (SRC / "styles" / "rabbit.css").read_text()
    assert ".tab-bar__item > * { pointer-events: none; }" in css


def test_design_tokens_launch_screen_and_rabbit_voice() -> None:
    css = (SRC / "styles" / "globals.css").read_text()
    for t in ("caption", "small", "meta", "body", "lead", "title", "heading", "page", "display"):
        assert f"--text-{t}:" in css
    html = (SRC.parent / "index.html").read_text()
    assert 'id="splash"' in html and "<script>" not in html  # CSP: the launch screen needs no inline JS
    assert "hideSplash()" in (SRC / "App.tsx").read_text()
    assert "rabbit-voice" in (SRC / "components" / "chat" / "MessageBubble.tsx").read_text()


def test_no_off_scale_font_sizes() -> None:
    # Root is 17px: every rem size is a 17px step (or 1rem); arbitrary ones like 1.3rem drift.
    import re
    ok = {round(px / 17, 4) for px in range(9, 60)} | {1.0}
    bad = []
    for p, src in tsx():
        for m in re.finditer(r"text-\[([0-9.]+)rem\]", src):
            if round(float(m.group(1)), 4) not in ok:
                bad.append(f"{p.name}: {m.group(0)}")
    assert not bad, bad


def test_header_icons_have_their_own_tap_areas() -> None:
    # The bell sat 4px into its neighbours with enlarged tap areas (size="icon" + -mx-1), so a tap
    # near it could open Chats. Header icons are plain 44px buttons side by side.
    chat = (SRC / "screens" / "Chat.tsx").read_text()
    block = chat[chat.index("const meButton = ("):chat.index("function renderHeader(")]
    assert "-mx-1" not in block and 'size="icon"' not in block
    assert block.count("className={HEADER_ICON}") >= 2
