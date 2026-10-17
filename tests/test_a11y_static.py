"""Cheap static accessibility checks over web/src (no browser needed).

Catches the regressions that tend to creep back in:
  * icon-only <button>/<Button> with no aria-label / aria-labelledby / title
  * <input>/<textarea>/<select> with no label (aria-label, aria-labelledby, an id a
    <label htmlFor> can point at, or an enclosing <label>/<Field>)
  * positive tabIndex (breaks the natural tab order)
  * window.confirm / window.alert (use lib/confirm's confirmAsk and toasts instead)
  * <img> with no alt

These are heuristics over the JSX text, not a parser, so the rules are written to
err toward silence. The full browser sweep lives in tests/browser_a11y.py.
"""
import os
import re
import unittest

SRC = os.path.join(os.path.dirname(__file__), '..', 'web', 'src')

# Components that render a <label> around their children.
LABEL_WRAPPERS = ('label', 'Field', 'LabeledField', 'FieldRow', 'Row')


def tsx_files():
    for root, _dirs, files in os.walk(SRC):
        for f in files:
            if f.endswith('.tsx'):
                yield os.path.join(root, f)


def read(p):
    with open(p, encoding='utf-8') as fh:
        return fh.read()


def line_of(text, i):
    return text.count('\n', 0, i) + 1


def open_tag(text, start):
    """Return the opening tag starting at `start` (handles {...} and quotes)."""
    depth = 0
    q = None
    i = start
    while i < len(text):
        c = text[i]
        if q:
            if c == q:
                q = None
        elif c in '"\'`' and depth == 0:
            q = c
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
        elif c == '>' and depth == 0:
            return text[start:i + 1]
        i += 1
    return text[start:]


def has_name(tag):
    return bool(re.search(r'\b(aria-label|aria-labelledby|title)=', tag)) or '{...' in tag


class StaticA11y(unittest.TestCase):

    def test_icon_only_buttons_have_names(self):
        bad = []
        for p in tsx_files():
            t = read(p)
            for m in re.finditer(r'<(button|Button)\b', t):
                tag = open_tag(t, m.start())
                if tag.endswith('/>') or has_name(tag):
                    continue
                end = t.find('</%s>' % m.group(1), m.start() + len(tag))
                if end < 0:
                    continue
                body = t[m.start() + len(tag):end]
                if '<' + m.group(1) in body:   # nested, skip (rare, and ambiguous)
                    continue
                # Any visible text, a {expression}, or an sr-only span counts as a name.
                if '{' in body or 'sr-only' in body:
                    continue
                text = re.sub(r'<[^>]*>', '', body).strip()
                if not text:
                    bad.append('%s:%d' % (os.path.relpath(p, SRC), line_of(t, m.start())))
        self.assertEqual(bad, [], 'icon-only buttons need aria-label:\n' + '\n'.join(bad))

    def test_form_fields_have_labels(self):
        bad = []
        for p in tsx_files():
            t = read(p)
            for m in re.finditer(r'<(input|textarea|select)\b', t):
                tag = open_tag(t, m.start())
                if re.search(r'type="(hidden|file)"', tag) and 'aria-label' not in tag:
                    if 'hidden' in tag or 'className="hidden"' in tag or 'sr-only' in tag:
                        continue
                if has_name(tag) or re.search(r'\bid=', tag):
                    continue
                # Enclosing <label> / <Field> (Field wires aria-labelledby at runtime): the
                # nearest wrapper opening before the field is not yet closed.
                back = t[max(0, m.start() - 2500):m.start()]
                last_open = max((mm.start() for w in LABEL_WRAPPERS
                                 for mm in re.finditer(r'<%s[\s>]' % w, back)), default=-1)
                if last_open >= 0:
                    between = back[last_open:]
                    if not any('</%s>' % w in between for w in LABEL_WRAPPERS) \
                            and not open_tag(back, last_open).endswith('/>'):
                        continue
                bad.append('%s:%d' % (os.path.relpath(p, SRC), line_of(t, m.start())))
        self.assertEqual(bad, [], 'form fields need a label:\n' + '\n'.join(bad))

    def test_no_positive_tabindex(self):
        bad = []
        for p in tsx_files():
            t = read(p)
            for m in re.finditer(r'tabIndex=\{?\s*([0-9]+)', t):
                if int(m.group(1)) > 0:
                    bad.append('%s:%d' % (os.path.relpath(p, SRC), line_of(t, m.start())))
        self.assertEqual(bad, [], 'positive tabIndex:\n' + '\n'.join(bad))

    def test_no_browser_dialogs(self):
        bad = []
        for p in tsx_files():
            t = read(p)
            for m in re.finditer(r'window\.(confirm|alert|prompt)\(', t):
                bad.append('%s:%d' % (os.path.relpath(p, SRC), line_of(t, m.start())))
        self.assertEqual(bad, [], 'use confirmAsk (lib/confirm) instead:\n' + '\n'.join(bad))

    def test_images_have_alt(self):
        bad = []
        for p in tsx_files():
            t = read(p)
            for m in re.finditer(r'<img\b', t):
                tag = open_tag(t, m.start())
                if not re.search(r'\balt=', tag) and '{...' not in tag:
                    bad.append('%s:%d' % (os.path.relpath(p, SRC), line_of(t, m.start())))
        self.assertEqual(bad, [], '<img> needs alt (alt="" if decorative):\n' + '\n'.join(bad))


if __name__ == '__main__':
    unittest.main()
