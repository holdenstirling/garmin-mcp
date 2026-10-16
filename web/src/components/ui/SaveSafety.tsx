// App-wide save safety net (mounted once in App.tsx):
//   * OutboxPill: "1 change not saved yet — we'll retry" while lib/outbox holds requests;
//     tap = retry now. Hidden when nothing is waiting.
//   * ResumeNote: after a sign-in that had to leave the page (session ran out, popup blocked),
//     "Welcome back: your unsaved <thing> is kept" so people know to reopen it.
import { useEffect, useState } from 'react'
import { CloudOff, X } from 'lucide-react'
import { flush, onOutbox, pendingCount } from '@/lib/outbox'
import { RESUME_KEY } from '@/components/ui/SessionLost'

export function OutboxPill() {
  const [n, setN] = useState(() => pendingCount())
  const [failed, setFailed] = useState<string | null>(null)
  useEffect(() => onOutbox((e) => {
    if (e.type === 'change') setN(e.pending)
    if (e.type === 'failed') setFailed(`${e.item.label}: ${e.message}`)
  }), [])
  if (!n && !failed) return null
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-[calc(env(safe-area-inset-bottom)+4.5rem)] z-(--z-toast) flex justify-center px-4">
      {n > 0 ? (
        <button type="button" onClick={() => void flush()}
          className="hit-44 pointer-events-auto inline-flex items-center gap-1.5 rounded-full border border-(--border) bg-background px-3 py-1.5 text-[0.7647rem] text-(--warning-text) shadow-md">
          <CloudOff className="size-3.5" aria-hidden />
          {n === 1 ? '1 change' : `${n} changes`} not saved yet — we'll retry
        </button>
      ) : (
        <p role="alert" className="pointer-events-auto inline-flex items-center gap-2 rounded-full border border-(--border) bg-background px-3 py-1.5 text-[0.7647rem] text-(--danger) shadow-md">
          Couldn't save {failed}
          <button type="button" aria-label="Dismiss" className="hit-44" onClick={() => setFailed(null)}><X className="size-3.5" /></button>
        </p>
      )}
    </div>
  )
}

export function ResumeNote({ userId }: { userId: string }) {
  const [label, setLabel] = useState<string | null>(null)
  useEffect(() => {
    try {
      const r = JSON.parse(window.localStorage.getItem(RESUME_KEY) ?? 'null') as { user: string; at: number; label: string | null } | null
      window.localStorage.removeItem(RESUME_KEY)
      if (r && r.user === userId && Date.now() - r.at < 2 * 3600_000) setLabel(r.label ?? 'changes')
    } catch { /* ignore */ }
  }, [userId])
  if (!label) return null
  return (
    <div className="fixed inset-x-0 top-[calc(env(safe-area-inset-top)+0.5rem)] z-(--z-toast) flex justify-center px-4">
      <p role="status" className="inline-flex items-center gap-2 rounded-full border border-(--border) bg-background px-3 py-1.5 text-[0.7647rem] text-(--text) shadow-md">
        Welcome back. Your unsaved {label} is kept: open it again to finish.
        <button type="button" aria-label="Dismiss" className="hit-44" onClick={() => setLabel(null)}><X className="size-3.5" /></button>
      </p>
    </div>
  )
}
