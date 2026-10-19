// The one bottom sheet. Every sheet gets the same pieces and behavior:
//   * the dimmed backdrop (tap to close) and the slide-up `.modal` panel (globals.css),
//   * a drag handle; drag down anywhere (in the body once it's scrolled to the top) to
//     dismiss, with the release-velocity rules of hooks/useSheetDrag,
//   * the same header: `.modal-title` h2 (or your own `header`), optional `actions`, then the
//     44px close button,
//   * keyboard dialog semantics from useDialog (role=dialog, aria-modal, named by its title,
//     focus moves in and is trapped, Escape closes, focus returns),
//   * the scrolling `.modal-body` with the safe-area bottom padding.
// Open sheets also pause page gestures underneath (pull to refresh, tab swipes: lib/overlays).
//
// Closing: by default the Sheet runs its own exit animation and then calls `onClose`. Parents
// that already drive the exit (`closing` + `onDismissed`, as in Chat.tsx's sheets) pass both:
// `onClose` then starts their exit and `onDismissed` unmounts at once after a drag.
// `dismissible={false}` (e.g. while saving) ignores backdrop taps, drags and Escape; keep it
// tied to the in-flight request (reset in `finally`) so the X can never stay disabled.
// A controlled parent must unmount the sheet after `closing` (timer) and on `onDismissed`.
// An uncontrolled sheet whose parent doesn't unmount it after `onClose` reappears.
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { useSheetDrag } from '@/hooks/useSheetDrag'
import { prefersReducedMotion } from '@/lib/overlays'
import { cn } from '@/lib/utils'

const EXIT_MS = 200
// A sheet's events still bubble to its React parents (maybe another sheet whose drag would
// follow this one's finger): keep touches (and, when portaled, keys) to itself.
const own = (e: React.SyntheticEvent) => e.stopPropagation()

export function Sheet({
  title, header, actions, below, children, footer, extra, onClose, onDismissed, closing, dismissible = true,
  closeLabel = 'Close', label, className, bodyClassName, bodyDrags, portal = false,
}: {
  title?: React.ReactNode
  /** replaces the title (e.g. a tappable goal header); keep a `.modal-title` inside to name the dialog */
  header?: React.ReactNode
  /** extra header buttons, left of the close button */
  actions?: React.ReactNode
  /** between the header and the body (tabs, a segmented control) */
  below?: React.ReactNode
  children: React.ReactNode
  /** pinned under the body */
  footer?: React.ReactNode
  /** inside the panel after everything else (an inline confirm dialog) */
  extra?: React.ReactNode
  onClose: () => void
  onDismissed?: () => void
  closing?: boolean
  dismissible?: boolean
  closeLabel?: string
  /** accessible name when the title isn't plain text */
  label?: string
  className?: string
  bodyClassName?: string
  bodyDrags?: boolean
  /** render into <body> (for sheets opened from inside another overlay) */
  portal?: boolean
}) {
  const [exiting, setExiting] = useState(false)
  const controlled = closing !== undefined
  const shut = controlled ? !!closing : exiting
  const timer = useRef<number | null>(null)
  useEffect(() => () => { if (timer.current !== null) window.clearTimeout(timer.current) }, [])

  const can = useRef(dismissible)
  can.current = dismissible
  const requestClose = () => {
    if (!can.current) return
    if (controlled) { onClose(); return }
    if (exiting) return
    if (prefersReducedMotion()) { onClose(); return }
    setExiting(true)
    timer.current = window.setTimeout(() => {
      onClose()
      // Still here a moment later: the parent didn't unmount us (it refused or failed). Come
      // back instead of sitting invisible over the app.
      timer.current = window.setTimeout(() => { timer.current = null; setExiting(false) }, 400)
    }, EXIT_MS)
  }
  const dismissNow = () => { if (can.current) (onDismissed ?? onClose)() }
  const drag = useSheetDrag(dismissNow, { bodyDrags, onEscape: requestClose })
  const { ref, ...touch } = drag

  const sheet = (
    <div className={cn('modal-overlay', shut && 'modal-overlay--exit')}
      onClick={(e) => { e.stopPropagation(); requestClose() }}
      onTouchStart={own} onTouchMove={own} onTouchEnd={own} onTouchCancel={own}
      {...(portal ? { onKeyDown: own } : {})}>
      <div ref={ref} className={cn('modal', shut && 'modal--exit', className)} aria-label={label}
        onClick={(e) => e.stopPropagation()} {...(dismissible ? touch : {})}>
        <div className="sheet-handle" aria-hidden="true" />
        <div className="modal-header">
          {header ?? <h2 className="modal-title min-w-0 truncate">{title}</h2>}
          <div className="sheet-actions">
            {actions}
            <button type="button" className="modal-close" aria-label={closeLabel} onClick={requestClose} disabled={!dismissible}>
              <X className="size-5" />
            </button>
          </div>
        </div>
        {below}
        <div className={cn('modal-body flex flex-col gap-3 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]', bodyClassName)}>
          {children}
        </div>
        {footer && <div className="shrink-0 border-t border-(--border) px-4 pb-[max(12px,env(safe-area-inset-bottom))] pt-3">{footer}</div>}
        {extra}
      </div>
    </div>
  )
  return portal && typeof document !== 'undefined' ? createPortal(sheet, document.body) : sheet
}
