// Is a sheet or overlay page open on top of `el`? Gestures on the page underneath (pull to
// refresh, swipe between tabs) stand down while one is. Sheets are `.modal-overlay`s and
// overlay pages are aria-modal dialogs (useDialog); a dialog that contains `el` is el's own page.
// A sheet or screen playing its exit animation no longer counts.
export function overlayOver(el: Element | null): boolean {
  if (typeof document === 'undefined') return false
  for (const d of Array.from(document.querySelectorAll('.modal-overlay, [aria-modal="true"]'))) {
    if (d.matches('.modal-overlay--exit, .plan-screen--exit') || d.closest('.modal-overlay--exit, .plan-screen--exit')) continue
    if (d.closest('[data-tab-hidden]')) continue  // a sheet left open in a tab that's kept mounted but not shown
    if (!el || !d.contains(el)) return true
  }
  return false
}

export function prefersReducedMotion(): boolean {
  try { return !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches } catch { return false }
}

// ------------------------------------------------------------ Back closes overlays ---
// Every open dialog (useDialog: sheets, overlay screens, photo viewer, confirms) registers
// here. While at least one is open, one extra history entry (same URL) sits on top of the
// app's own, so the phone's Back (Android back button/gesture, browser back, history.back
// in an installed web app) pops that entry instead of leaving Rabbit, and we close the
// topmost overlay. When the last overlay closes some other way (X, backdrop, Escape, drag),
// the entry is dropped again with history.back(), so the history the user sees never grows.
// Deep links (?open=...) are read on load before any overlay registers; the extra entry
// keeps whatever URL is current and never changes it.

type Entry = { el: Element; close: () => void; closingUntil: number }
const stack: Entry[] = []
let guard = false    // our entry is the current history entry
let leaving = false  // we called history.back() to drop it; the next popstate is ours
let leaveTimer = 0
let scheduled = false
let listening = false

const now = () => Date.now()
const open = () => stack.filter((e) => e.closingUntil <= now())

function sync() {
  scheduled = false
  if (leaving || typeof window === 'undefined') return
  const want = open().length > 0
  try {
    if (want && !guard) {
      window.history.pushState({ ...(window.history.state ?? {}), rabbitOverlay: true }, '')
      guard = true
    } else if (!want && guard) {
      guard = false
      leaving = true
      // If the popstate never comes (history API refused), don't wait on it forever.
      leaveTimer = window.setTimeout(() => { leaving = false; schedule() }, 800)
      window.history.back()
    }
  } catch { /* history API unavailable (sandboxed frame): Back just isn't intercepted */ }
}

function schedule() {
  if (scheduled) return
  scheduled = true
  window.setTimeout(sync, 0)
}

/** The overlay drawn on top: last in document order (a nested dialog comes after its parent,
 *  portals at the end of <body>). */
function topmost(): Entry | undefined {
  let top: Entry | undefined
  for (const e of open()) {
    if (!top || (top.el.compareDocumentPosition(e.el) & Node.DOCUMENT_POSITION_FOLLOWING)) top = e
  }
  return top
}

function onPopState() {
  if (leaving) {
    leaving = false
    window.clearTimeout(leaveTimer)
    schedule()
    return
  }
  if (!guard) return // not our entry (the user went back past the app's own history)
  guard = false
  const top = topmost()
  if (top) {
    // Mark it closing so a second Back closes the next one, not this one again while it
    // animates out. If it refuses to close (busy saving), it counts as open again after a beat.
    top.closingUntil = now() + 700
    window.setTimeout(schedule, 750)
    try { top.close() } catch { /* a broken close handler must not break Back */ }
  }
  schedule()
}

// ------------------------------------------------------------ One layer shows ---
// Sheets never pile up: only the topmost layer (last in document order among open sheets and
// overlay pages) is drawn. A sheet under another sheet, or under a page opened over it, is
// marked `data-covered`: its panel hides and its backdrop goes clear (globals.css), so nothing
// peeks out and backdrops never double-dim. When the top one closes (or starts its exit), the
// one underneath shows again exactly as it was. Confirms drawn inside a sheet aren't layers.
const LAYERS = '.modal-overlay, .plan-screen:not(.plan-screen--tab)'
const EXITING = '.modal-overlay--exit, .plan-screen--exit'
let watching = false
let framed = false

export function markCovered(): void {
  framed = false
  if (typeof document === 'undefined') return
  const layers = Array.from(document.querySelectorAll(LAYERS)).filter((l) => !l.closest(EXITING) && !l.closest('[data-tab-hidden]'))
  const top = layers[layers.length - 1]
  for (const l of Array.from(document.querySelectorAll('.modal-overlay'))) {
    const covered = !!top && l !== top && layers.includes(l)
    if (covered !== l.hasAttribute('data-covered')) {
      if (covered) l.setAttribute('data-covered', '')
      else l.removeAttribute('data-covered')
    }
  }
}

function watchLayers() {
  if (watching || typeof MutationObserver === 'undefined' || typeof document === 'undefined') return
  watching = true
  new MutationObserver(() => {
    if (framed) return
    if (!stack.length && !document.querySelector('[data-covered]')) return
    framed = true
    window.requestAnimationFrame(markCovered)
  }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] })
}

/** Register an open dialog; returns the unregister function. */
export function registerOverlay(el: Element, close: () => void): () => void {
  if (typeof window === 'undefined') return () => {}
  if (!listening) { window.addEventListener('popstate', onPopState); listening = true }
  watchLayers()
  const entry: Entry = { el, close, closingUntil: 0 }
  stack.push(entry)
  schedule()
  window.requestAnimationFrame(markCovered)
  return () => {
    const i = stack.indexOf(entry)
    if (i >= 0) stack.splice(i, 1)
    schedule()
    window.requestAnimationFrame(markCovered)
  }
}

/** Number of open overlays (tests, debugging). */
export function openOverlayCount(): number { return open().length }
