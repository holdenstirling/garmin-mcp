"""Every overlay in the web app has a way out: scripts/check_exits.py over web/src (plain text
TSX parsing, no Node), its rules on small synthetic screens, and the structural fixes it
relies on (tab page claim, Back closes overlays)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_exits.py"
SRC = ROOT / "web" / "src"


def run(root: Path | None = None) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(SCRIPT)] + (["--root", str(root)] if root else [])
    return subprocess.run(args, capture_output=True, text=True, timeout=120)


def test_web_src_has_no_dead_exits() -> None:
    r = run()
    assert r.returncode == 0, r.stdout + r.stderr


def write(tmp: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        p = tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp


def test_noop_close_outside_a_tab_is_reported(tmp_path: Path) -> None:
    root = write(tmp_path, {"A.tsx": """
export function Page() {
  return <Screen title="Community" onClose={() => {}}><Feed /></Screen>
}
export function Other({ x }: { x: boolean }) {
  return x ? <Sheet title="t" onClose={noop}>hi</Sheet> : null
}
"""})
    r = run(root)
    assert r.returncode == 1
    assert r.stdout.count("noop-close") == 2, r.stdout


def test_noop_close_inside_a_tab_screen_is_allowed(tmp_path: Path) -> None:
    root = write(tmp_path, {"Chat.tsx": """
export function Chat() {
  return (
    <TabScreen key="mine" title="Events">
      <EventsScreen onClose={noop} imperial={imperial} />
    </TabScreen>
  )
}
"""})
    r = run(root)
    assert r.returncode == 0, r.stdout


def test_screen_without_close_must_be_a_tab_page(tmp_path: Path) -> None:
    root = write(tmp_path, {
        "Community.tsx": """
export function CommunityScreen() {
  return <Screen title="Community">{x}</Screen>
}
export function Lost() {
  return <Screen title="Lost">{x}</Screen>
}
""",
        "Chat.tsx": """
export function Chat() {
  return <>
    <TabScreen key="community"><CommunityScreen /></TabScreen>
    {open && <Lost />}
  </>
}
""",
    })
    r = run(root)
    assert r.returncode == 1
    assert "page-no-close" in r.stdout and "Lost" in r.stdout
    assert "CommunityScreen has no" not in r.stdout


def test_optional_close_page_used_as_overlay_without_close(tmp_path: Path) -> None:
    root = write(tmp_path, {
        "Stats.tsx": """
export function StatsScreen({ onClose }: { onClose?: () => void }) {
  const close = onClose && (() => onClose())
  return <Screen title="Progress" onClose={close}>{x}</Screen>
}
""",
        "Chat.tsx": """
export function Chat() {
  return <>
    <TabScreen key="overview"><StatsScreen /></TabScreen>
    {stats && <StatsScreen />}
  </>
}
""",
    })
    r = run(root)
    assert r.returncode == 1
    assert r.stdout.count("page-usage") == 1 and "Chat.tsx:5" in r.stdout, r.stdout


def test_dead_close_buttons(tmp_path: Path) -> None:
    root = write(tmp_path, {"B.tsx": """
export function B() {
  return <div className="modal-header">
    <button className="modal-close" aria-label="Close"><X className="size-4" /></button>
    <button type="button" onClick={() => {}}><X className="size-4" /></button>
    <button type="submit" onClick={done} aria-label="Close">x</button>
    <Button variant="ghost" disabled={true} onClick={close}><ChevronLeft /></Button>
    <button type="button" aria-label="Close" onClick={close}><X className="size-4" /></button>
    <span className="modal-close invisible" aria-hidden />
  </div>
}
"""})
    r = run(root)
    assert r.returncode == 1
    lines = [ln for ln in r.stdout.splitlines() if "dead-button" in ln]
    assert len(lines) == 4, r.stdout
    assert any("has no onClick" in ln for ln in lines)
    assert any("no-op onClick" in ln for ln in lines)
    assert any('type="submit"' in ln for ln in lines)
    assert any("always disabled" in ln for ln in lines)


def test_raw_overlay_needs_escape_and_back(tmp_path: Path) -> None:
    root = write(tmp_path, {
        "Raw.tsx": """
export function Raw({ onClose }: { onClose: () => void }) {
  return <div className="modal-overlay" onClick={onClose}><div className="modal">x</div></div>
}
""",
        "Ok.tsx": """
export function Ok({ onClose }: { onClose: () => void }) {
  const drag = useSheetDrag(onClose)
  return <div className="modal-overlay" onClick={onClose}><div className="modal" {...drag}>x</div></div>
}
""",
    })
    r = run(root)
    assert r.returncode == 1
    assert "Raw.tsx:1: no-escape" in r.stdout and "Ok.tsx" not in r.stdout


def test_generics_and_arrows_dont_confuse_the_parser(tmp_path: Path) -> None:
    root = write(tmp_path, {"G.tsx": """
export function G() {
  const [x] = useState<Record<string, number>>({})
  const f = (a: number) => a > 1
  return <Sheet title="t" onClose={() => { setOpen(false); if (a > b) go() }}>
    {items.map((i) => <Row key={i} onClick={() => i > 2 && pick(i)} />)}
  </Sheet>
}
"""})
    r = run(root)
    assert r.returncode == 0, r.stdout


# ------------------------------------------------------- structural fixes --
def test_tab_page_claim_happens_in_a_layout_effect_not_during_render() -> None:
    ui = (SRC / "components" / "plan" / "ui.tsx").read_text()
    screen = ui[ui.index("export function Screen("):ui.index("export function Progress(")]
    # The only write to the claim is inside useLayoutEffect (a thrown-away render, e.g. while a
    # lazy chunk suspends, must not leave a stale owner and turn the page into a dead overlay).
    effect = screen[screen.index("useLayoutEffect("):]
    effect = effect[:effect.index("}, [")]
    writes = re.findall(r"claim\.owner\s*=(?!=)|\bc\.owner\s*=(?!=)", screen)
    assert writes and all(w in effect for w in writes)
    assert len(re.findall(r"\bc\.owner\s*=(?!=)", effect)) == 2  # claim + release
    assert "embed.claim.owner = id" not in screen
    # Children of any Screen never see the tab's context; no close action -> no X.
    assert "<EmbedCtx.Provider value={null}>" in screen
    assert "!onClose ?" in screen or "|| !onClose" in screen


def test_back_closes_the_topmost_overlay() -> None:
    ov = (SRC / "lib" / "overlays.ts").read_text()
    assert "addEventListener('popstate'" in ov and "pushState(" in ov and "history.back()" in ov
    dialog = (SRC / "hooks" / "useDialog.ts").read_text()
    assert "registerOverlay(" in dialog


def test_lazy_screen_fallback_keeps_a_way_out() -> None:
    lazy = (SRC / "screens" / "lazyScreens.tsx").read_text()
    assert 'aria-label="Close"' in lazy and "getDerivedStateFromError" in lazy


def test_finished_animations_leave_no_transform_trap() -> None:
    css = (SRC / "styles" / "globals.css").read_text() + (SRC / "styles" / "rabbit.css").read_text()
    assert not re.search(r"animation:\s*modal-slide-up[^;]*\b(forwards|both)\b", css)
    assert re.search(r"\.modal-overlay--exit\s*\{[^}]*pointer-events:\s*none", css)
