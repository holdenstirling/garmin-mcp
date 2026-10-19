// Save feedback that never loses input: "Saving…", a subtle "Saved" tick, or
// "Not saved yet — we'll retry" while lib/outbox holds the request.
//
//   const saver = useSaver()
//   await saver.run({ method: 'PUT', path: '/api/settings', body, label: 'settings', coalesce: 'settings' })
//   <SaveStatus state={saver.state} />
import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, CloudOff } from 'lucide-react'
import { onOutbox, save, type Method, type SaveResult } from '@/lib/outbox'
import { cn } from '@/lib/utils'

export type SaveState = 'idle' | 'saving' | 'saved' | 'queued' | 'error'

export function SaveStatus({ state, error, className }: { state: SaveState; error?: string | null; className?: string }) {
  if (state === 'idle') return null
  return (
    <span role="status" aria-live="polite"
      className={cn('inline-flex items-center gap-1 text-meta',
        state === 'saved' && 'text-(--success)', state === 'queued' && 'text-(--warning-text)',
        state === 'error' && 'text-(--danger)', state === 'saving' && 'text-(--text-muted)', className)}>
      {state === 'saving' && 'Saving…'}
      {state === 'saved' && <><Check className="size-4" aria-hidden /> Saved</>}
      {state === 'queued' && <><CloudOff className="size-4" aria-hidden /> Not saved yet — we'll retry</>}
      {state === 'error' && (error || "Couldn't save")}
    </span>
  )
}

/** One save at a time with feedback; `onSaved(data)` also runs when a queued save goes through later. */
export function useSaver<T = unknown>(onSaved?: (data: T) => void) {
  const [state, setState] = useState<SaveState>('idle')
  const [error, setError] = useState<string | null>(null)
  const waiting = useRef<string | null>(null)
  const done = useRef(onSaved)
  done.current = onSaved
  const fade = useRef<number | null>(null)

  const savedNow = useCallback(() => {
    setState('saved')
    if (fade.current !== null) window.clearTimeout(fade.current)
    fade.current = window.setTimeout(() => setState((s) => s === 'saved' ? 'idle' : s), 2000)
  }, [])

  useEffect(() => onOutbox((e) => {
    if (e.type === 'change' || e.item.id !== waiting.current) return
    waiting.current = null
    if (e.type === 'saved') { savedNow(); done.current?.(e.data as T) }
    else { setError(e.message); setState('error') }
  }), [savedNow])
  useEffect(() => () => { if (fade.current !== null) window.clearTimeout(fade.current) }, [])

  const run = useCallback(async (req: { method: Method; path: string; body?: unknown; label: string; coalesce?: string; id?: string }): Promise<SaveResult<T>> => {
    setState('saving'); setError(null)
    try {
      const r = await save<T>(req)
      if (r.ok) { waiting.current = null; savedNow(); done.current?.(r.data) }
      else { waiting.current = r.id; setState('queued') }
      return r
    } catch (e) {
      setError((e as Error).message); setState('error')
      throw e
    }
  }, [savedNow])

  return { state, error, run, queued: state === 'queued' }
}
