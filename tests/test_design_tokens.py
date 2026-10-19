"""Design-system guards over web/src (plain text checks, no Node), from web/DESIGN.md: text sizes
come from the type tokens (nothing below 13px, no arbitrary text-[..] sizes), labels are sentence
case (no tracked ALL-CAPS), and the tokens themselves keep the readable scale."""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "web" / "src"
STYLES = SRC / "styles"

# Root is 17px (rabbit.css), so 0.7647rem is 13px: the smallest text the app may use.
MIN_REM = 0.7647
TOKENS = {
    "caption": 0.7647, "meta": 0.8235, "small": 0.8824, "body": 0.9412, "body-lg": 1.0,
    "lead": 1.0588, "title-sm": 1.1765, "title": 1.2941, "title-md": 1.4118, "title-lg": 1.5294,
    "display-sm": 1.6471, "display": 1.7647,
}


def sources() -> list[tuple[Path, str]]:
    return [(p, p.read_text()) for p in sorted(SRC.rglob("*.ts*"))]


def test_text_sizes_use_the_tokens() -> None:
    """No text-[0.8rem] / text-[13px] style sizes: only text-caption ... text-display. SVG
    <text> labels inside charts are the one exception (they scale with the chart)."""
    bad = []
    for p, s in sources():
        for n, line in enumerate(s.splitlines(), 1):
            for m in re.finditer(r"text-\[(\d+(?:\.\d+)?)(rem|px|em)\]", line):
                if m.group(2) == "px" and ("<text" in line or "fill-(" in line):
                    continue  # an SVG chart label
                bad.append(f"{p.relative_to(SRC)}:{n}: {m.group(0)}")
    assert not bad, bad


def test_no_tailwind_default_sizes() -> None:
    """text-xs / text-sm / text-base ... are off the scale (and text-xs is under 13px)."""
    bad = []
    for p, s in sources():
        for m in re.finditer(r"(?<![\w-])text-(xs|sm|base|lg|xl|[2-9]xl)(?![\w-])", s):
            bad.append(f"{p.relative_to(SRC)}: {m.group(0)}")
    assert not bad, bad


def test_labels_are_sentence_case() -> None:
    """No tracked ALL-CAPS labels (they read as noise and are hard to scan)."""
    bad = []
    for p, s in sources():
        for m in re.finditer(r"(['\"`])([^'\"`\n]*)\1", s):
            cls = m.group(2).split()
            if "uppercase" in cls and any(re.fullmatch(r"tracking-(wide|wider|widest|\[[\d.]+em\])", c) for c in cls):
                bad.append(f"{p.relative_to(SRC)}: {m.group(2)[:80]}")
    assert not bad, bad


def test_css_font_sizes_are_tokens() -> None:
    """Stylesheets size text with var(--text-*) (or em); a bare rem size must not go below 13px."""
    bad = []
    for css in STYLES.glob("*.css"):
        for n, line in enumerate(css.read_text().splitlines(), 1):
            for m in re.finditer(r"font-size:\s*(?:min\()?\s*(\d+(?:\.\d+)?)rem", line):
                if float(m.group(1)) < MIN_REM:
                    bad.append(f"{css.name}:{n}: {line.strip()}")
    assert not bad, bad


def test_type_scale_tokens() -> None:
    """The scale itself: body 16px, nothing under 13px, steps in order."""
    css = (STYLES / "globals.css").read_text()
    theme = css[css.index("@theme {"):]
    theme = theme[:theme.index("\n}\n")]
    got = {}
    for name in TOKENS:
        m = re.search(rf"--text-{re.escape(name)}:\s*([\d.]+)rem;", theme)
        assert m, f"--text-{name} missing from @theme"
        got[name] = float(m.group(1))
    assert got == TOKENS, got
    assert min(got.values()) >= MIN_REM
    values = list(got.values())
    assert values == sorted(values)


def test_section_labels_are_not_tracked_caps() -> None:
    """The shared label styles (.section-label, .section-title, .rabbit-voice__label) stay
    sentence case, in the sans."""
    css = (STYLES / "rabbit.css").read_text()
    for cls in (".section-label", ".section-title", ".rabbit-voice__label"):
        block = css[css.index(cls + " {"):]
        block = block[:block.index("}")]
        assert "uppercase" not in block and "letter-spacing: 0.1" not in block, cls
        assert "mono" not in block, cls
