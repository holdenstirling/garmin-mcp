// "Keep editing / Discard" when someone closes a form with unsaved edits. Drafts
// (lib/drafts) keep everything else safe, so Discard is the only action that loses input.
//
//   const guard = useUnsavedGuard(draft.dirty, draft.discard)
//   <Screen onClose={guard.wrap(close)} ...>  ...  {guard.dialog}
import { useCallback, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Button } from '@/components/ui/button'
import { useDialog } from '@/hooks/useDialog'

export function useUnsavedGuard(dirty: boolean, onDiscard?: () => void) {
  const [pending, setPending] = useState<(() => void) | null>(null)
  const live = useRef(dirty)
  live.current = dirty
  const discardRef = useRef(onDiscard)
  discardRef.current = onDiscard

  /** Wrap a close handler: runs it right away when nothing is unsaved, else asks first. */
  const wrap = useCallback((close: () => void) => () => {
    if (!live.current) { close(); return }
    setPending(() => close)
  }, [])

  const dialog = pending ? (
    <DiscardDialog
      onKeep={() => setPending(null)}
      onDiscard={() => { const close = pending; setPending(null); discardRef.current?.(); close() }} />
  ) : null
  return { wrap, dialog, asking: pending !== null }
}

function DiscardDialog({ onKeep, onDiscard }: { onKeep: () => void; onDiscard: () => void }) {
  const box = useRef<HTMLDivElement>(null)
  useDialog(box, onKeep)
  return createPortal(
    <div className="fixed inset-0 z-(--z-dialog) flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onKeep} />
      <div ref={box} role="alertdialog" aria-modal="true" aria-labelledby="unsaved-title" aria-describedby="unsaved-desc"
        className="relative z-10 mx-4 w-full max-w-sm rounded-lg border bg-background p-5 shadow-lg">
        <h3 id="unsaved-title" className="text-[0.9412rem] font-semibold text-(--text)">You have unsaved changes</h3>
        <p id="unsaved-desc" className="mt-1.5 text-[0.8235rem] text-(--text-muted)">
          Keep editing to finish, or discard what you changed.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" className="h-11" onClick={onDiscard}>Discard</Button>
          <Button variant="primary" className="h-11" onClick={onKeep}>Keep editing</Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

/** "Restored your unsaved draft · Discard" line for the top of a form. */
export function DraftRestored({ onDiscard, note }: { onDiscard: () => void; note?: string }) {
  return (
    <p className="flex flex-wrap items-center gap-x-2 px-1 text-[0.7059rem] text-(--text-muted)" role="status">
      <span>Restored your unsaved draft{note ? ` · ${note}` : ''}.</span>
      <button type="button" className="hit-44 underline" onClick={onDiscard}>Discard draft</button>
    </p>
  )
}
