// Is a sheet or overlay page open on top of `el`? Gestures on the page underneath (pull to
// refresh, swipe between tabs) stand down while one is. Sheets are `.modal-overlay`s and
// overlay pages are aria-modal dialogs (useDialog); a dialog that contains `el` is el's own page.
export function overlayOver(el: Element | null): boolean {
  if (typeof document === 'undefined') return false
  for (const d of Array.from(document.querySelectorAll('.modal-overlay, [aria-modal="true"]'))) {
    if (!el || !d.contains(el)) return true
  }
  return false
}

export function prefersReducedMotion(): boolean {
  try { return !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches } catch { return false }
}
