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
      {error && <p className="px-1 text-[0.8235rem] text-(--danger)">{error}</p>}
      {coaches.length === 0 && threads !== null && (
        <p className="px-1 py-6 text-center text-[0.8235rem] text-(--text-muted)">No coach yet. Invite one from Settings › Coaches.</p>
      )}
      {coaches.map((c) => (
        <Button key={c.email} variant="primary" className="h-11 gap-1.5 text-[0.8235rem]" onClick={() => void startGeneral(c.email)}>
          <MessageSquare className="size-4" /> Message {c.email.split('@')[0]}
        </Button>
      ))}
      {notes.length > 0 && (
        <section className="flex flex-col gap-2">
          <h2 className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Notes from your coach</h2>
          {notes.map((n) => (
            <Card key={n.id} className="px-4 py-3">
              <p className="flex items-start gap-2 text-[0.8235rem] leading-snug text-(--text)">
                {n.pinned ? <Pin className="mt-0.5 size-3.5 shrink-0 text-(--accent)" /> : <StickyNote className="mt-0.5 size-3.5 shrink-0 text-(--text-muted)" />}
                <span className="whitespace-pre-wrap">{n.text}</span>
              </p>
              <p className="mt-1 text-[0.6471rem] text-(--text-muted)">{n.coach.split('@')[0]} · {timeAgo(n.ts)} · Rabbit follows these too</p>
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
      <h2 className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Conversations</h2>
      <Card>
        <div className="divide-y divide-(--border)">
          {threads.map((t) => (
            <button key={t.id} type="button" onClick={() => onOpen(t.id)}
              className="flex w-full items-center gap-3 px-4 py-3 text-left active:bg-(--bg-inset)">
              <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-xl',
                t.session_id || t.event_id ? 'bg-(--accent-subtle) text-(--accent)' : 'bg-(--bg-elevated) text-(--text-secondary)')}>
                {t.event_id ? <Flag className="size-4" /> : t.session_id ? <Dumbbell className="size-4" /> : <MessageSquare className="size-4" />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[0.8824rem] text-(--text)">{t.title}</span>
                <span className="block truncate text-[0.7059rem] text-(--text-muted)">
                  {t.last ? `${t.last.from === me ? 'You: ' : ''}${t.last.text}` : 'No messages yet'}
                </span>
              </span>
              <span className="flex shrink-0 flex-col items-end gap-1">
                <span className="text-[0.6471rem] text-(--text-muted)">{timeAgo(t.updated)}</span>
                <ChevronRight className="size-4 text-(--text-muted)" />
              </span>
            </button>
          ))}
        </div>
      </Card>
    </section>
  )
}
