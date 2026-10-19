// Athlete side: messages with your coach (general or about a workout) and the notes they shared.
import { useCallback, useEffect, useState } from 'react'
import { ChevronRight, Dumbbell, Flag, MessageSquare, Pin, StickyNote } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { RabbitLoader } from '@/components/RabbitLoader'
import { Card, Screen } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import { athleteChat, getCoachNotes, timeAgo, type CoachLink, type Note, type ThreadSummary } from '@/lib/coach'
import { ThreadView } from './ThreadView'

export function CoachInbox({ onClose, openThreadId, onChanged }: {
  onClose: () => void; openThreadId?: string | null; onChanged?: () => void
}) {
  const [threads, setThreads] = useState<ThreadSummary[] | null>(null)
  const [coaches, setCoaches] = useState<CoachLink[]>([])
  const [notes, setNotes] = useState<Note[]>([])
  const [open, setOpen] = useState<string | null>(openThreadId ?? null)
  const [closing, setClosing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    athleteChat.list().then((r) => { setThreads(r.threads); setCoaches(r.coaches ?? []) }, (e) => setError((e as Error).message))
    getCoachNotes().then((r) => setNotes(r.notes), () => {})
  }, [])
  useEffect(load, [load])
  const close = () => { setClosing(true); setTimeout(() => { onChanged?.(); onClose() }, 200) }
  const active = (threads ?? []).find((t) => t.id === open)

  async function startGeneral(coach: string) {
    try { const r = await athleteChat.open({ coach }); setOpen(r.thread.id); load() }
    catch (e) { setError((e as Error).message) }
  }

  if (open) {
    return (
      <Screen title={active?.event_id ? 'Race chat' : active?.session_id ? 'Workout chat' : 'Coach'} subtitle={active?.coach ?? coaches[0]?.email}
        closing={closing} onClose={close} onBack={() => { setOpen(null); load() }}>
        <ThreadView api={athleteChat} threadId={open} me="athlete" otherName={(active?.coach ?? coaches[0]?.email ?? 'your coach').split('@')[0]!} />
      </Screen>
    )
  }

  return (
    <Screen title="Your coach" subtitle={coaches.map((c) => c.email).join(', ')} closing={closing} onClose={close}>
      {threads === null && !error && <RabbitLoader className="py-16" label="Loading messages…" />}
      {error && <p className="px-1 text-body text-(--danger)">{error}</p>}
      {coaches.length === 0 && threads !== null && (
        <p className="px-1 py-6 text-center text-body text-(--text-muted)">No coach yet. Invite one from Settings › Coaches.</p>
      )}
      {coaches.map((c) => (
        <Button key={c.email} variant="primary" className="h-11 gap-1.5 text-body" onClick={() => void startGeneral(c.email)}>
          <MessageSquare className="size-5" /> Message {c.email.split('@')[0]}
        </Button>
      ))}
      {notes.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="section-title m-0 px-1">Notes from your coach</h2>
          {notes.map((n) => (
            <Card key={n.id} className="px-4 py-4">
              <p className="flex items-start gap-2.5 text-body-lg leading-snug text-(--text)">
                {n.pinned ? <Pin className="mt-0.5 size-5 shrink-0 text-(--accent)" aria-hidden /> : <StickyNote className="mt-0.5 size-5 shrink-0 text-(--text-muted)" aria-hidden />}
                <span className="whitespace-pre-wrap">{n.text}</span>
              </p>
              <p className="mt-2 text-small text-(--text-secondary)">From {n.coach.split('@')[0]}, {timeAgo(n.ts)}. rabbt follows these too.</p>
            </Card>
          ))}
        </section>
      )}
      {(threads ?? []).length > 0 && <ThreadList threads={threads!} onOpen={setOpen} me="athlete" />}
    </Screen>
  )
}

export function ThreadList({ threads, onOpen, me }: { threads: ThreadSummary[]; onOpen: (id: string) => void; me: 'athlete' | 'coach' }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="section-title m-0 px-1">Conversations</h2>
      <Card>
        <div className="divide-y divide-(--border)">
          {threads.map((t) => (
            <button key={t.id} type="button" onClick={() => onOpen(t.id)}
              className="flex w-full items-center gap-3 px-4 py-3 text-left active:bg-(--bg-inset)">
              <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-xl',
                t.session_id || t.event_id ? 'bg-(--accent-subtle) text-(--accent)' : 'bg-(--bg-elevated) text-(--text-secondary)')}>
                {t.event_id ? <Flag className="size-5" /> : t.session_id ? <Dumbbell className="size-5" /> : <MessageSquare className="size-5" />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-body-lg text-(--text)">{t.title}</span>
                <span className="block truncate text-small text-(--text-secondary)">
                  {t.last ? `${t.last.from === me ? 'You: ' : ''}${t.last.text}` : 'No messages yet'}
                </span>
              </span>
              <span className="flex shrink-0 flex-col items-end gap-1">
                <span className="text-meta text-(--text-secondary)">{timeAgo(t.updated)}</span>
                <ChevronRight className="size-5 text-(--text-muted)" />
              </span>
            </button>
          ))}
        </div>
      </Card>
    </section>
  )
}
