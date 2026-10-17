// One direct-message conversation (page): messages newest at the bottom, shared workout / event
// cards inline, reactions on long-press (or the … button), a request banner when someone you
// don't know wrote first, and a composer pinned above the safe area.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { BellOff, Bell, Flag, LogOut, Ellipsis, Send, SmilePlus } from 'lucide-react'
import { Screen } from '@/components/plan/ui'
import { Button } from '@/components/ui/button'
import { RabbitLoader } from '@/components/RabbitLoader'
import { Sheet } from '@/components/ui/Sheet'
import { EventCardView, WorkoutCardView } from './DmCards'
import {
  REACTIONS, convAction, convTitle, dmChanged, getConv, muteConv, reactMsg, reportConv, sendMsg,
  type DMConv, type DMMessage,
} from '@/lib/dm'
import { cn } from '@/lib/utils'

const POLL_MS = 8000

function dayLabel(ts: number): string {
  const d = new Date(ts * 1000)
  const today = new Date()
  const y = new Date(); y.setDate(today.getDate() - 1)
  if (d.toDateString() === today.toDateString()) return 'Today'
  if (d.toDateString() === y.toDateString()) return 'Yesterday'
  return d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })
}

export function ConversationScreen({ id, imperial, onClose }: { id: string; imperial: boolean; onClose: () => void }) {
  const [conv, setConv] = useState<DMConv | null>(null)
  const [msgs, setMsgs] = useState<DMMessage[]>([])
  const [more, setMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const [react, setReact] = useState<DMMessage | null>(null)
  const [menu, setMenu] = useState(false)
  const [reporting, setReporting] = useState<DMMessage | 'conv' | null>(null)
  const end = useRef<HTMLDivElement>(null)
  const stick = useRef(true)

  const load = useCallback(async (quiet = false) => {
    try {
      const r = await getConv(id)
      setConv(r.conv); setMore(r.more)
      setMsgs((old) => {
        const older = old.filter((m) => r.msgs.length && m.ts < r.msgs[0]!.ts)
        return [...older, ...r.msgs]
      })
      setError(null)
      dmChanged()
    } catch (e) { if (!quiet) setError((e as Error).message) }
  }, [id])
  useEffect(() => { void load() }, [load])
  useEffect(() => {  // new messages while open (light polling; stops when the page is hidden)
    const t = window.setInterval(() => { if (document.visibilityState === 'visible') void load(true) }, POLL_MS)
    return () => window.clearInterval(t)
  }, [load])
  useLayoutEffect(() => { if (stick.current) end.current?.scrollIntoView({ block: 'end' }) }, [msgs.length])

  async function older() {
    if (!msgs.length) return
    stick.current = false
    const r = await getConv(id, msgs[0]!.ts).catch(() => null)
    if (r) { setMsgs((m) => [...r.msgs, ...m]); setMore(r.more) }
  }
  async function send() {
    const t = text.trim()
    if (!t || sending) return
    setSending(true); stick.current = true
    try {
      const r = await sendMsg(id, t)
      setMsgs((m) => [...m, r.msg]); setText('')
      dmChanged()
    } catch (e) { setError((e as Error).message) } finally { setSending(false) }
  }
  async function pickReaction(m: DMMessage, emoji: string) {
    setReact(null)
    const r = await reactMsg(id, m.id, emoji).catch(() => null)
    if (r) setMsgs((list) => list.map((x) => (x.id === m.id ? r.msg : x)))
  }
  async function answer(accept: boolean) {
    if (accept) { await convAction(id, 'accept').catch(() => null); void load() }
    else { await convAction(id, 'decline').catch(() => null); dmChanged(); onClose() }
  }

  const nameOf = (uid: string) => conv?.members.find((p) => p.id === uid)?.name ?? 'Someone'
  const group = conv?.kind === 'group'
  const title = conv ? convTitle(conv) : 'Messages'
  const request = conv?.status === 'request'
  const waiting = conv && conv.waiting_on.length > 0

  return (
    <Screen title={title} subtitle={group && conv ? `${conv.members.length + 1} people` : undefined} onClose={onClose}
      headerExtra={conv && (
        <div className="mx-auto flex w-full max-w-xl items-center gap-2 px-4 pb-1.5">
          <p className="min-w-0 flex-1 truncate text-[0.7059rem] text-(--text-muted)">
            {group ? conv.members.map((p) => p.name).join(', ') : conv.muted ? 'Notifications muted' : 'Direct message'}
          </p>
          <button type="button" className="hit-44 inline-flex h-8 items-center gap-1 rounded-full px-2.5 text-[0.7059rem] font-medium text-(--text-secondary) active:bg-(--bg-inset)"
            aria-label="Chat options" onClick={() => setMenu(true)}><Ellipsis className="size-4" aria-hidden /> Options</button>
        </div>
      )}
      footer={!request && conv && (
        <form className="flex w-full items-end gap-2"
          onSubmit={(e) => { e.preventDefault(); void send() }}>
          <textarea value={text} onChange={(e) => setText(e.target.value.slice(0, 2000))} rows={1} enterKeyHint="send"
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !('ontouchstart' in window)) { e.preventDefault(); void send() } }}
            placeholder={`Message ${group ? 'the group' : nameOf(conv.members[0]?.id ?? '')}`} aria-label="Message"
            className="max-h-32 min-h-11 flex-1 resize-none rounded-2xl border border-(--border) bg-(--bg-surface) px-3.5 py-2.5 text-[0.8824rem] text-(--text) outline-none focus:ring-1 focus:ring-(--accent)" />
          <Button type="submit" variant="primary" size="icon" className="size-11 shrink-0 rounded-full" aria-label="Send"
            disabled={!text.trim()} loading={sending}><Send className="size-4" /></Button>
        </form>
      )}>
      {!conv && !error && <RabbitLoader className="py-10" label="Loading messages" />}
      {error && !conv && <p role="alert" className="py-10 text-center text-[0.7647rem] text-(--text-muted)">{error}</p>}
      {conv && (
        <div className="flex flex-col gap-1.5 pb-2">
          {request && (
            <div className="flex flex-col gap-2 rounded-xl border border-(--accent)/30 bg-(--accent-subtle) p-3" role="status">
              <p className="text-[0.8235rem] text-(--text)"><b className="font-semibold">{nameOf(msgs[0]?.by ?? conv.members[0]?.id ?? '')}</b> wants to message you. They won't see that you've read it unless you reply.</p>
              <div className="flex gap-2">
                <Button variant="primary" className="h-11 flex-1 text-[0.8235rem]" onClick={() => void answer(true)}>Accept</Button>
                <Button variant="default" className="h-11 flex-1 text-[0.8235rem]" onClick={() => void answer(false)}>Decline</Button>
              </div>
            </div>
          )}
          {waiting && !request && (
            <p className="rounded-xl bg-(--bg-inset) px-3 py-2 text-[0.7059rem] text-(--text-secondary)">
              {conv.waiting_on.map((p) => p.name).join(', ')} {conv.waiting_on.length === 1 ? 'gets' : 'get'} this as a message request until they accept.
            </p>
          )}
          {more && (
            <button type="button" className="hit-44 self-center text-[0.7647rem] text-(--accent)" onClick={() => void older()}>Show earlier messages</button>
          )}
          {msgs.length === 0 && (
            <p className="py-8 text-center text-[0.7647rem] text-(--text-muted)">No messages yet. Say hi 👋</p>
          )}
          {msgs.map((m, i) => {
            const prev = msgs[i - 1]
            const newDay = !prev || dayLabel(prev.ts) !== dayLabel(m.ts)
            const showName = group && !m.mine && (!prev || prev.by !== m.by || newDay)
            const rx = Object.entries(m.reactions)
            return (
              <div key={m.id} className="flex flex-col">
                {newDay && <p className="my-2 self-center text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">{dayLabel(m.ts)}</p>}
                {showName && <p className="ml-1 text-[0.6471rem] text-(--text-muted)">{nameOf(m.by)}</p>}
                <div className={cn('group flex max-w-[85%] items-end gap-1', m.mine ? 'self-end flex-row-reverse' : 'self-start')}>
                  <div className="flex min-w-0 flex-col gap-1"
                    onContextMenu={(e) => { e.preventDefault(); setReact(m) }}>
                    {m.att && (m.att.type === 'workout'
                      ? <WorkoutCardView card={m.att} imperial={imperial} />
                      : <EventCardView card={m.att} />)}
                    {m.text && (
                      <p className={cn('whitespace-pre-wrap break-words rounded-2xl px-3.5 py-2 text-[0.8824rem] leading-snug',
                        m.mine ? 'rounded-br-md bg-(--accent) text-(--on-fill)' : 'rabbit-dm-in rounded-bl-md border border-(--border) bg-(--bg-surface) text-(--text)')}>
                        {m.text}
                      </p>
                    )}
                  </div>
                  <button type="button" aria-label="React" onClick={() => setReact(m)}
                    className="flex size-8 shrink-0 items-center justify-center rounded-full text-(--text-muted) opacity-60 focus:opacity-100 sm:opacity-0 sm:group-hover:opacity-100">
                    <SmilePlus className="size-4" aria-hidden />
                  </button>
                </div>
                {rx.length > 0 && (
                  <div className={cn('mt-0.5 flex gap-1', m.mine ? 'self-end' : 'self-start')}>
                    {rx.map(([e, r]) => (
                      <button key={e} type="button" onClick={() => void pickReaction(m, e)} aria-pressed={r.mine}
                        aria-label={`${e} ${r.n}${r.mine ? ', yours' : ''}`}
                        className={cn('inline-flex min-h-7 items-center gap-0.5 rounded-full border px-2 text-[0.7647rem]',
                          r.mine ? 'border-(--accent) bg-(--accent-subtle)' : 'border-(--border) bg-(--bg-surface)')}>
                        {e}<span className="tabular-nums text-(--text-secondary)">{r.n}</span>
                      </button>
                    ))}
                  </div>
                )}
                {m.mine && i === msgs.length - 1 && (
                  <p className="mt-0.5 self-end text-[0.6471rem] text-(--text-muted)">
                    {new Date(m.ts * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
                  </p>
                )}
              </div>
            )
          })}
          <div ref={end} />
        </div>
      )}
      {react && (
        <Sheet title="React" onClose={() => setReact(null)} portal bodyClassName="flex flex-col gap-3 p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
          <div className="flex justify-between gap-1" role="group" aria-label="Reactions">
            {REACTIONS.map((e) => (
              <button key={e} type="button" className="flex size-12 items-center justify-center rounded-full text-2xl active:bg-(--bg-inset)"
                aria-label={`React ${e}`} onClick={() => void pickReaction(react, e)}>{e}</button>
            ))}
          </div>
          {!react.mine && (
            <Button variant="ghost" className="h-11 gap-1.5 text-[0.8235rem] text-(--danger)" onClick={() => { setReporting(react); setReact(null) }}>
              <Flag className="size-4" aria-hidden /> Report this message
            </Button>
          )}
        </Sheet>
      )}
      {menu && conv && (
        <Sheet title={title} onClose={() => setMenu(false)} portal bodyClassName="flex flex-col gap-2 p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
          <Button variant="default" className="h-11 justify-start gap-2 text-[0.8235rem]"
            onClick={async () => { const r = await muteConv(id, !conv.muted).catch(() => null); if (r) setConv({ ...conv, muted: r.conv.muted }); setMenu(false) }}>
            {conv.muted ? <Bell className="size-4" aria-hidden /> : <BellOff className="size-4" aria-hidden />}
            {conv.muted ? 'Turn notifications back on' : 'Mute notifications'}
          </Button>
          <Button variant="default" className="h-11 justify-start gap-2 text-[0.8235rem]" onClick={() => { setReporting('conv'); setMenu(false) }}>
            <Flag className="size-4" aria-hidden /> Report
          </Button>
          <Button variant="default" className="h-11 justify-start gap-2 text-[0.8235rem] text-(--danger)"
            onClick={async () => { await convAction(id, 'leave').catch(() => null); dmChanged(); setMenu(false); onClose() }}>
            <LogOut className="size-4" aria-hidden /> {group ? 'Leave the group' : 'Delete this chat'}
          </Button>
          <p className="px-1 text-[0.7059rem] text-(--text-muted)">To stop someone messaging you, block them from their profile in Local › People.</p>
        </Sheet>
      )}
      {reporting && (
        <ReportSheet onClose={() => setReporting(null)}
          onSend={async (why) => { await reportConv(id, reporting === 'conv' ? null : reporting.id, why).catch(() => null); setReporting(null) }} />
      )}
    </Screen>
  )
}

function ReportSheet({ onClose, onSend }: { onClose: () => void; onSend: (why: string) => Promise<void> }) {
  const [why, setWhy] = useState('')
  const [busy, setBusy] = useState(false)
  return (
    <Sheet title="Report" onClose={onClose} portal bodyClassName="flex flex-col gap-3 p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
      <p className="text-[0.7647rem] text-(--text-secondary)">The Rabbit team reviews reports. The person isn't told who reported them.</p>
      <textarea value={why} onChange={(e) => setWhy(e.target.value.slice(0, 300))} placeholder="What happened? (optional)" aria-label="What happened"
        className="min-h-20 rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-2 text-[0.8235rem] text-(--text) outline-none focus:ring-1 focus:ring-(--accent)" />
      <Button variant="primary" className="h-11 text-[0.8235rem]" loading={busy} onClick={async () => { setBusy(true); await onSend(why) }}>Send report</Button>
    </Sheet>
  )
}
