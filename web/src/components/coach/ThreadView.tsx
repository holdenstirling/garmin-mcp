// One athlete <-> coach conversation: messages and a composer. Polls while open.
import { useCallback, useEffect, useRef, useState } from 'react'
import { Dumbbell, Flag, Send } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { RabbitLoader } from '@/components/RabbitLoader'
import { cn } from '@/lib/utils'
import { timeAgo, type ChatApi, type Thread } from '@/lib/coach'

const POLL_MS = 15_000

export function ThreadView({ api, threadId, me, otherName, draft }: {
  api: ChatApi; threadId: string; me: 'athlete' | 'coach'; otherName: string
  /** prefilled message (e.g. "Ask your coach" from race readiness); the athlete edits and sends */
  draft?: string
}) {
  const [t, setT] = useState<Thread | null>(null)
  const [text, setText] = useState(draft ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // A failed poll shows until the next one succeeds.
  const [pollError, setPollError] = useState<string | null>(null)
  const end = useRef<HTMLDivElement>(null)

  const load = useCallback(() => {
    api.get(threadId).then((r) => { setT(r.thread); setPollError(null) }, (e) => setPollError((e as Error).message))
  }, [api, threadId])
  useEffect(() => {
    load()
    const id = window.setInterval(() => { if (document.visibilityState === 'visible') load() }, POLL_MS)
    return () => window.clearInterval(id)
  }, [load])
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }) }, [t?.messages.length])

  async function send() {
    const body = text.trim()
    if (!body) return
    setBusy(true); setError(null)
    try {
      const r = await api.post(threadId, body)
      setT((x) => x ? { ...x, messages: [...x.messages, r.message] } : x)
      setText('')
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }

  return (
    <div className="flex flex-col gap-3">
      {(t?.session_id || t?.event_id) && (
        <div className="flex items-center gap-2 rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-2 text-[0.7647rem] text-(--text-secondary)">
          {t.event_id ? <Flag className="size-4 text-(--accent)" /> : <Dumbbell className="size-4 text-(--accent)" />} About: {t.title}
        </div>
      )}
      <div className="flex min-h-[200px] flex-col gap-2">
        {!t && !pollError && <RabbitLoader className="py-12" label="Loading messages…" />}
        {t && t.messages.length === 0 && (
          <p className="py-8 text-center text-[0.7647rem] text-(--text-muted)">No messages yet. Say hi to {otherName}.</p>
        )}
        {t?.messages.map((m) => {
          const mine = m.from === me
          return (
            <div key={m.id} className={cn('flex flex-col', mine ? 'items-end' : 'items-start')}>
              <div className={cn('max-w-[85%] whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-[0.8824rem] leading-snug',
                mine ? 'rounded-br-sm bg-(--accent) text-(--on-fill) dark:bg-(--accent-subtle) dark:text-(--text)' : 'rounded-bl-sm border border-(--border) bg-(--bg-surface) text-(--text)')}>
                {m.text}
              </div>
              <span className="mt-0.5 px-1 text-[0.6471rem] text-(--text-muted)">{mine ? 'You' : otherName} · {timeAgo(m.ts)}</span>
            </div>
          )
        })}
        <div ref={end} />
      </div>
      {(error ?? pollError) && <p className="text-[0.7647rem] text-(--danger)" role="alert">{error ?? pollError}</p>}
      <div className="sticky bottom-0 flex items-end gap-2 bg-(--bg) pb-1 pt-1">
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} maxLength={4000}
          placeholder={`Message ${otherName}`} aria-label="Message"
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void send() }}
          className="min-h-[44px] flex-1 resize-none rounded-xl border border-input bg-transparent px-3 py-2 text-base text-(--text) placeholder:text-(--text-muted) focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" />
        <Button variant="primary" size="icon" className="size-11 shrink-0" aria-label="Send" loading={busy}
          disabled={!text.trim()} onClick={() => void send()}><Send className="size-4" /></Button>
      </div>
    </div>
  )
}
