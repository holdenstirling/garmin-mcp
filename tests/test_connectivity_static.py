"""Static connectivity check for the web app (web/src): no page type, sheet or button is a dead
end. Cheap enough to run with the Python suite, no browser needed.

  * every page kind in screens/Chat.tsx `type Page` is rendered (`case 'x'`) and opened somewhere
  * every `OPEN_*_EVENT` a lib exports has a listener (addEventListener) in screens/ or components/
  * every lib `openX()` helper that fires one of those events is called somewhere
  * every <Sheet> / <BottomSheet> has an onClose
  * every <button> / <Button> does something: onClick, type="submit", asChild, a spread of props,
    or sits in a form-like role it gets from its parent (disabled placeholders count too)

The live sweep (open every page in a real browser at 375px and tap every control) is
tests/browser_sweep.py (how to run: its docstring, and CLAUDE.md "Connectivity").
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "web" / "src"


def _files(*dirs: str) -> list[Path]:
    out: list[Path] = []
    for d in dirs:
        out += sorted((SRC / d).rglob("*.ts")) + sorted((SRC / d).rglob("*.tsx"))
    return out


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _tags(text: str, name: str) -> list[tuple[int, str]]:
    """Each opening JSX tag `<name ...>` with its attributes (braces and strings respected)."""
    out = []
    for m in re.finditer(rf"(?<![\w.])<{name}(?=[\s>/])", text):
        if re.match(r"\s*[|,>]", text[m.end():]):  # a type argument (useState<Sheet | null>)
            continue
        i, depth, quote = m.end(), 0, ""
        while i < len(text):
            ch = text[i]
            if quote:
                if ch == quote and text[i - 1] != "\\":
                    quote = ""
            elif ch in "\"'`" and depth == 0:
                quote = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif ch == ">" and depth == 0:
                break
            i += 1
        out.append((text.count("\n", 0, m.start()) + 1, text[m.start():i + 1]))
    return out


def test_every_page_kind_is_rendered_and_opened():
    chat = _read(SRC / "screens" / "Chat.tsx")
    decl = re.search(r"type Page = (.*?)\nconst pageKey", chat, re.S)
    assert decl, "type Page not found in Chat.tsx"
    kinds = set(re.findall(r"k: '([a-z]+)'", decl.group(1)))
    assert {"workout", "activity", "checklist", "person", "dm"} <= kinds
    body = chat[decl.end():]
    for k in sorted(kinds - {"screen"}):  # 'screen' renders through its own switch (pg.s)
        assert f"case '{k}'" in body, f"page kind {k!r} is never rendered (renderPage)"
        opened = re.search(rf"k: '{k}'", body) or (k in ("connections", "access", "usage", "partners") and "pushPage({ k: r })" in body)
        assert opened, f"page kind {k!r} is never opened"


def test_every_open_event_has_a_listener():
    libs = _files("lib")
    ui = "\n".join(_read(p) for p in _files("screens", "components", "hooks"))
    alltext = ui + "\n".join(_read(p) for p in libs)
    missing, unused = [], []
    for p in libs:
        t = _read(p)
        for const in re.findall(r"export const (OPEN_[A-Z_]+_EVENT)\b", t):
            if not re.search(rf"addEventListener\(\s*{const}\b", ui):
                missing.append(f"{p.name}:{const}")
            # the helpers that fire it are called from somewhere other than their own definition
            for fn in re.findall(rf"export (?:function|const) (open[A-Za-z]+)\b[^\n]*\n?[^\n]*{const}", t):
                calls = re.findall(rf"(?<!function )\b{fn}\(", alltext)
                if not calls:
                    unused.append(f"{p.name}:{fn}")
    assert not missing, f"events nobody listens for: {missing}"
    assert not unused, f"open helpers nobody calls: {unused}"


def test_every_sheet_can_close():
    bad = []
    for p in _files("screens", "components"):
        t = _read(p)
        for name in ("Sheet", "BottomSheet"):
            for line, tag in _tags(t, name):
                if "onClose" not in tag and "{...props}" not in tag:
                    bad.append(f"{p.relative_to(SRC)}:{line}")
    assert not bad, f"sheets without onClose: {bad}"


_OK = ("onClick", 'type="submit"', "type='submit'", "asChild", "{...", "onPointerDown", "onMouseDown")


def test_no_button_without_a_handler():
    bad = []
    for p in _files("screens", "components"):
        if p.parts[-2] == "ui" and p.name in {"button.tsx"}:
            continue
        t = _read(p)
        for name in ("button", "Button"):
            for line, tag in _tags(t, name):
                if not any(k in tag for k in _OK):
                    bad.append(f"{p.relative_to(SRC)}:{line}: {tag[:80]!r}")
    assert not bad, "buttons that do nothing:\n" + "\n".join(bad)
