// Keyboard basics for sheets and full-screen pages: role=dialog + aria-modal, named by its
// title (.modal-title / h1 / h2) unless labelled; on open, focus moves into the dialog;
// Tab cycles within it; Escape closes it; on close, focus returns to where it was.
// Listeners sit on the dialog itself, so a dialog opened inside another one handles its
// own keys first; it marks them handled (preventDefault) so the outer one skips them.
// (No stopPropagation: React's own key handlers listen at the root.)
// Every open dialog is also registered in lib/overlays, so the phone's Back (Android back,
// history.back) closes the topmost one instead of leaving the app.
// The element may mount later than the hook's component (a sheet rendered conditionally next
// to the hook): it is picked up after the commit that mounts it, and let go when it unmounts.
import { useEffect, useRef, type RefObject } from 'react'
import { registerOverlay } from '@/lib/overlays'

const FOCUSABLE = [
  'a[href]', 'button:not([disabled])', 'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])', 'textarea:not([disabled])', '[tabindex]:not([tabindex="-1"])',
].join(',')

function attach(el: HTMLElement, close: { current: (() => void) | undefined }): () => void {
  const before = document.activeElement instanceof HTMLElement ? document.activeElement : null
  if (!el.hasAttribute('tabindex')) el.tabIndex = -1
  if (!el.hasAttribute('role')) el.setAttribute('role', 'dialog')
  if (!el.hasAttribute('aria-modal')) el.setAttribute('aria-modal', 'true')
  // Name it by its title when it has no label of its own.
  if (!el.hasAttribute('aria-label') && !el.hasAttribute('aria-labelledby')) {
    const title = el.querySelector<HTMLElement>('.modal-title, h1, h2')
    if (title) {
      if (!title.id) title.id = `dlg-${Math.random().toString(36).slice(2, 9)}`
      el.setAttribute('aria-labelledby', title.id)
    }
  }
  if (!el.contains(document.activeElement)) el.focus({ preventScroll: true })

  const onKey = (e: KeyboardEvent) => {
    if (e.defaultPrevented) return
    if (e.key === 'Escape') {
      e.preventDefault()
      close.current?.()
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
  const unregister = close.current ? registerOverlay(el, () => close.current?.()) : () => {}
  return () => {
    unregister()
    el.removeEventListener('keydown', onKey)
    // Give focus back, unless something else already took it (another dialog, a field).
    const now = document.activeElement
    if (before && before.isConnected && (!now || now === document.body || el.contains(now))) {
      before.focus({ preventScroll: true })
    }
  }
}

export function useDialog(ref: RefObject<HTMLElement | null>, onClose: (() => void) | undefined) {
  const close = useRef(onClose)
  useEffect(() => { close.current = onClose })
  const live = useRef<{ el: HTMLElement; detach: () => void } | null>(null)

  // After every commit: attach when the element appeared or changed, detach when it's gone.
  useEffect(() => {
    const el = ref.current
    if (live.current?.el === el) return
    live.current?.detach()
    live.current = el ? { el, detach: attach(el, close) } : null
  })
  useEffect(() => () => { live.current?.detach(); live.current = null }, [])
}

/** For light popovers that aren't dialogs (long-press menus, the week drawer): Escape and the
 *  phone's Back close them, without the dialog role, focus move or trap. */
export function useDismiss(ref: RefObject<HTMLElement | null>, onClose: () => void, active = true) {
  const close = useRef(onClose)
  useEffect(() => { close.current = onClose })
  useEffect(() => {
    const el = ref.current
    if (!active || !el) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return
      e.preventDefault()
      close.current()
    }
    document.addEventListener('keydown', onKey)
    const unregister = registerOverlay(el, () => close.current())
    return () => { unregister(); document.removeEventListener('keydown', onKey) }
  }, [ref, active])
}
