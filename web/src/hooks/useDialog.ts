// Keyboard basics for sheets and full-screen pages: on open, focus moves into the dialog;
// Tab cycles within it; Escape closes it; on close, focus returns to where it was.
// Listeners sit on the dialog itself, so a dialog opened inside another one handles its
// own keys first; it marks them handled (preventDefault) so the outer one skips them.
// (No stopPropagation: React's own key handlers listen at the root.)
import { useEffect, useRef, type RefObject } from 'react'

const FOCUSABLE = [
  'a[href]', 'button:not([disabled])', 'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])', 'textarea:not([disabled])', '[tabindex]:not([tabindex="-1"])',
].join(',')

export function useDialog(ref: RefObject<HTMLElement | null>, onClose: () => void) {
  const close = useRef(onClose)
  useEffect(() => { close.current = onClose })

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const before = document.activeElement instanceof HTMLElement ? document.activeElement : null
    if (!el.hasAttribute('tabindex')) el.tabIndex = -1
    if (!el.hasAttribute('role')) el.setAttribute('role', 'dialog')
    if (!el.hasAttribute('aria-modal')) el.setAttribute('aria-modal', 'true')
    if (!el.contains(document.activeElement)) el.focus({ preventScroll: true })

    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return
      if (e.key === 'Escape') {
        e.preventDefault()
        close.current()
        return
      }
      if (e.key !== 'Tab') return
      const nodes = Array.from(el.querySelectorAll<HTMLElement>(FOCUSABLE))
        .filter((n) => !n.closest('[inert]') && n.getClientRects().length > 0)
      if (!nodes.length) { e.preventDefault(); el.focus({ preventScroll: true }); return }
      const first = nodes[0]!
      const last = nodes[nodes.length - 1]!
      const active = document.activeElement
      if (e.shiftKey && (active === first || active === el)) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && active === last) { e.preventDefault(); first.focus() }
    }
    el.addEventListener('keydown', onKey)
    return () => {
      el.removeEventListener('keydown', onKey)
      // Give focus back, unless something else already took it (another dialog, a field).
      const now = document.activeElement
      if (before && before.isConnected && (!now || now === document.body || el.contains(now))) {
        before.focus({ preventScroll: true })
      }
    }
  }, [ref])
}
