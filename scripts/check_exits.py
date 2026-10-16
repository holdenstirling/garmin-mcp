#!/usr/bin/env python3
"""Static check: every overlay in the web app has a working way out.

Scans web/src/**/*.tsx as plain text (no Node needed) and reports:

  noop-close     an `onClose`/`onBack` that does nothing (`() => {}`, `noop`, ...) outside a
                 <TabScreen> block: its X / back arrow would be dead.
  page-no-close  a <Screen> with neither onClose nor onBack that isn't a tab page: no way out.
                 Allowed inside a <TabScreen> block, or in a component that is only ever
                 rendered inside <TabScreen> blocks.
  page-usage     a component whose own Screen has an optional onClose (a tab page that can
                 also be an overlay) used without onClose outside a <TabScreen> block.
  dead-button    a close/back button (an X / ChevronLeft / ArrowLeft icon, or aria-label
                 Close/Back/Dismiss) with no onClick, a no-op onClick, type="submit" or
                 disabled={true}.
  no-escape      a file that draws a raw `.modal-overlay` without useDialog/useSheetDrag
                 (no Escape, no phone Back).

Usage: python3 scripts/check_exits.py [--root web/src]   (exit 1 when anything is found)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass

NOOP = re.compile(r"^\s*(?:noop|\(\s*\)\s*=>\s*(?:\{\s*\}|undefined|null|void\s+0|\(\s*\{\s*\}\s*\)))\s*$")
CLOSE_ICONS = re.compile(r"<(?:X|ChevronLeft|ArrowLeft)\b")
CLOSE_LABEL = re.compile(r"""aria-label=(?:"|\{['"`])(?:Close|Back|Dismiss)\b""")
IDENT = re.compile(r"[A-Za-z0-9_$.]")


@dataclass
class Tag:
    name: str
    start: int          # index of '<'
    end: int            # index just past '>'
    attrs: str          # raw text between the name and '>'
    self_closing: bool


@dataclass
class Finding:
    kind: str
    file: str
    line: int
    text: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.kind}: {self.text}"


def _skip_string(s: str, i: int) -> int:
    """i points at a quote; return the index just past the closing quote."""
    q = s[i]
    i += 1
    while i < len(s):
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if q == "`" and s.startswith("${", i):
            i = _skip_braces(s, i + 1)
            continue
        if c == q:
            return i + 1
        i += 1
    return i


def _skip_braces(s: str, i: int) -> int:
    """i points at '{'; return the index just past the matching '}'."""
    depth = 0
    while i < len(s):
        c = s[i]
        if c in "\"'`":
            i = _skip_string(s, i)
            continue
        if s.startswith("/*", i):
            j = s.find("*/", i + 2)
            i = len(s) if j < 0 else j + 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return i


def tags(src: str) -> list[Tag]:
    """JSX opening tags (components and <button>), with their raw attribute text."""
    out: list[Tag] = []
    for m in re.finditer(r"<([A-Z][A-Za-z0-9_.]*|button)\b", src):
        i = m.start()
        # `Foo<Bar>` is a generic, not JSX.
        if i > 0 and IDENT.match(src[i - 1]):
            continue
        j = m.end()
        while j < len(src):
            c = src[j]
            if c == "{":
                j = _skip_braces(src, j)
                continue
            if c in "\"'":
                j = _skip_string(src, j)
                continue
            if c == ">":
                break
            if c == "<":  # not a tag after all (e.g. a comparison)
                j = -1
                break
            j += 1
        if j < 0 or j >= len(src):
            continue
        attrs = src[m.end():j]
        out.append(Tag(m.group(1), i, j + 1, attrs, attrs.rstrip().endswith("/")))
    return out


def attr(t: Tag, name: str) -> str | None:
    """The value of attribute `name` ('{...}' content or quoted string), '' when bare, None when absent."""
    a = t.attrs
    for m in re.finditer(r"(?:^|\s)" + re.escape(name) + r"(=|(?=[\s/]|$))", a):
        if m.group(1) != "=":
            return ""
        k = m.end()
        if k < len(a) and a[k] == "{":
            e = _skip_braces(a, k)
            return a[k + 1:e - 1]
        if k < len(a) and a[k] in "\"'":
            e = _skip_string(a, k)
            return a[k + 1:e - 1]
    return None


def has_spread(t: Tag) -> bool:
    return re.search(r"\{\s*\.\.\.", t.attrs) is not None


def tab_blocks(src: str) -> list[tuple[int, int]]:
    """[start, end) spans of <TabScreen ...> ... </TabScreen> blocks."""
    spans = []
    for m in re.finditer(r"<TabScreen\b", src):
        depth, i = 0, m.start()
        for t in re.finditer(r"<TabScreen\b|</TabScreen>", src[m.start():]):
            depth += 1 if t.group(0) != "</TabScreen>" else -1
            if depth == 0:
                i = m.start() + t.end()
                break
        spans.append((m.start(), i))
    return spans


def inside(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(a <= pos < b for a, b in spans)


def line_of(src: str, pos: int) -> int:
    return src.count("\n", 0, pos) + 1


def enclosing_component(src: str, pos: int) -> str | None:
    best = None
    for m in re.finditer(r"(?:^|\n)\s*(?:export\s+)?function\s+([A-Z]\w*)\s*\(", src):
        if m.start() > pos:
            break
        best = m.group(1)
    return best


def button_body(src: str, t: Tag) -> str:
    if t.self_closing:
        return ""
    close = "</button>" if t.name == "button" else f"</{t.name}>"
    e = src.find(close, t.end)
    return src[t.end:e] if e >= 0 else ""


def scan(root: str) -> list[Finding]:
    files: dict[str, str] = {}
    for d, _, names in os.walk(root):
        for n in names:
            if n.endswith(".tsx"):
                p = os.path.join(d, n)
                with open(p, encoding="utf-8") as f:
                    files[os.path.relpath(p, root)] = f.read()

    findings: list[Finding] = []
    parsed = {rel: (src, tags(src), tab_blocks(src)) for rel, src in files.items()}

    # Components rendered where (for page-no-close / page-usage).
    usages: dict[str, list[tuple[str, Tag, bool]]] = {}
    for rel, (src, ts, spans) in parsed.items():
        for t in ts:
            usages.setdefault(t.name, []).append((rel, t, inside(t.start, spans)))

    def only_in_tabs(comp: str | None) -> bool:
        uses = usages.get(comp or "", [])
        return bool(uses) and all(in_tab for _, _, in_tab in uses)

    optional_close_pages: set[str] = set()

    for rel, (src, ts, spans) in parsed.items():
        for t in ts:
            in_tab = inside(t.start, spans)
            # noop-close
            for name in ("onClose", "onBack", "onDismissed"):
                v = attr(t, name)
                if v is not None and NOOP.match(v) and not in_tab:
                    findings.append(Finding("noop-close", rel, line_of(src, t.start),
                                            f"<{t.name} {name}={{{v.strip()}}}> does nothing"))
            # page-no-close
            if t.name == "Screen" and attr(t, "onClose") is None and attr(t, "onBack") is None and not has_spread(t):
                comp = enclosing_component(src, t.start)
                if not in_tab and not only_in_tabs(comp):
                    findings.append(Finding("page-no-close", rel, line_of(src, t.start),
                                            f"<Screen> in {comp or '?'} has no onClose/onBack and isn't a tab page"))
            # dead-button
            if t.name in ("button", "Button"):
                body = button_body(src, t)
                if CLOSE_ICONS.search(body) or CLOSE_LABEL.search(t.attrs):
                    click = attr(t, "onClick")
                    why = None
                    if attr(t, "aria-hidden") is not None:
                        why = None
                    elif click is None and not has_spread(t):
                        why = "has no onClick"
                    elif click is not None and NOOP.match(click):
                        why = "has a no-op onClick"
                    elif (attr(t, "type") or "") == "submit":
                        why = 'is type="submit"'
                    elif (attr(t, "disabled") or "").strip() == "true":
                        why = "is always disabled"
                    if why:
                        findings.append(Finding("dead-button", rel, line_of(src, t.start), f"close/back <{t.name}> {why}"))
        # Components whose Screen takes an optional onClose (tab page or overlay).
        for m in re.finditer(r"(?:^|\n)\s*export\s+function\s+([A-Z]\w*)\s*\(", src):
            comp = m.group(1)
            nxt = re.search(r"\n\s*(?:export\s+)?function\s+[A-Z]\w*\s*\(", src[m.end():])
            body = src[m.start(): m.end() + (nxt.start() if nxt else len(src))]
            # (`if (onClose)` = it renders something else, not a Screen, without one: CoachApp)
            if "<Screen" in body and re.search(r"\bonClose\?\s*:", body) and not re.search(r"\bif\s*\(\s*onClose\s*\)", body):
                optional_close_pages.add(comp)
        # no-escape
        if re.search(r"""className=[{"`'][^>]*\bmodal-overlay\b""", src) and not re.search(r"\buse(?:Dialog|SheetDrag)\(", src):
            findings.append(Finding("no-escape", rel, 1, "draws a .modal-overlay without useDialog/useSheetDrag"))

    # page-usage
    for comp in sorted(optional_close_pages):
        for rel, t, in_tab in usages.get(comp, []):
            if attr(t, "onClose") is None and not has_spread(t) and not in_tab:
                findings.append(Finding("page-usage", rel, line_of(parsed[rel][0], t.start),
                                        f"<{comp}> without onClose outside a <TabScreen>: no way out"))
    return sorted(findings, key=lambda f: (f.file, f.line, f.kind))


def main(argv: list[str] | None = None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=os.path.join(here, "..", "web", "src"))
    args = ap.parse_args(argv)
    found = scan(os.path.normpath(args.root))
    for f in found:
        print(f)
    if found:
        print(f"{len(found)} overlay exit problem(s)", file=sys.stderr)
        return 1
    print("check_exits: every overlay has a way out")
    return 0


if __name__ == "__main__":
    sys.exit(main())
