// New message / "Send to a friend": pick one or more people (friends and club mates; anyone you
// can't message freely gets a request), or, when sharing a workout or event, one of your recent
// chats. Then the chat opens (and a shared card goes in first).
import { useEffect, useMemo, useState } from 'react'
import { Check, Search as SearchIcon, Send, X } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/button'
import { RabbitLoader } from '@/components/RabbitLoader'
import { PersonAvatar } from '@/components/community/Feed'
import { inputCls } from '@/components/plan/ui'
import { convTitle, dmChanged, dmPeople, listConvs, sendMsg, startConv, type DMConv, type DMPerson, type DMShare } from '@/lib/dm'
import { cn } from '@/lib/utils'

export function NewMessageSheet({ to, share, onClose, onOpened }: {
  /** preselected people */
  to?: string[]
  share?: DMShare
  onClose: () => void
  onOpened: (convId: string) => void
}) {
  const [people, setPeople] = useState<DMPerson[] | null>(null)
  const [convs, setConvs] = useState<DMConv[]>([])
  const [q, setQ] = useState('')
  const [picked, setPicked] = useState<string[]>(to ?? [])
  const [name, setName] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    dmPeople().then((r) => setPeople(r.people), () => setPeople([]))
    if (share) listConvs().then((r) => setConvs(r.convs.slice(0, 6)), () => {})
  }, [share])
  // Preselected people who aren't in the list (no follow or club yet) still show as chips.
  const known = useMemo(() => new Map((people ?? []).map((p) => [p.id, p])), [people])
  const shown = (people ?? []).filter((p) => !q.trim() || p.name.toLowerCase().includes(q.trim().toLowerCase()))
  const toggle = (id: string) => setPicked((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id].slice(0, 11)))
  const att = share ? { type: share.type, ref: share.ref } : undefined

  async function start() {
    if (!picked.length) return
    setBusy('start'); setErr(null)
    try {
      const r = await startConv(picked, { name: picked.length > 1 ? name.trim() : undefined, text: note.trim() || undefined, att })
      dmChanged()
      onOpened(r.conv.id)
    } catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }
  async function sendTo(c: DMConv) {
    if (!att) return
    setBusy(c.id); setErr(null)
    try {
      await sendMsg(c.id, note.trim(), att)
      dmChanged()
      onOpened(c.id)
    } catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }

  return (
    <Sheet title={share ? 'Send to a friend' : 'New message'} onClose={onClose} label={share ? 'Send to a friend' : 'New message'}
      bodyClassName="settings flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4"
      footer={
        <div className="flex flex-col gap-2 border-t border-(--border) bg-(--bg) px-4 pt-3 pb-[max(12px,env(safe-area-inset-bottom))]">
          {err && <p role="alert" className="text-meta text-(--danger)">{err}</p>}
          <Button variant="primary" className="h-11 gap-1.5 text-body" disabled={!picked.length || busy != null}
            loading={busy === 'start'} onClick={() => void start()}>
            <Send className="size-5" aria-hidden />
            {!picked.length ? 'Pick someone' : share ? `Send to ${picked.length === 1 ? (known.get(picked[0]!)?.name ?? '1 person') : `${picked.length} people`}`
              : picked.length === 1 ? `Message ${known.get(picked[0]!)?.name ?? ''}`.trim() : `Start a group of ${picked.length + 1}`}
          </Button>
        </div>
      }>
      {share && (
        <p className="rounded-xl bg-(--accent-subtle) px-3 py-2 text-small text-(--text)">
          Sharing <b className="font-semibold">{share.label}</b>. Friends see the sport, distance, time and pace, never your heart rate or where you went.
        </p>
      )}
      {share && convs.length > 0 && (
        <section aria-label="Recent chats" className="flex flex-col gap-1">
          <h3 className="section-label">Recent chats</h3>
          <ul className="flex flex-col divide-y divide-(--border) overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)">
            {convs.map((c) => (
              <li key={c.id}>
                <button type="button" onClick={() => void sendTo(c)} disabled={busy != null}
                  className="flex min-h-12 w-full items-center gap-3 px-3 py-2 text-left active:bg-(--bg-inset) disabled:opacity-50">
                  <span className="min-w-0 flex-1 truncate text-body text-(--text)">{convTitle(c)}</span>
                  {busy === c.id ? <RabbitLoader inline label="Sending" /> : <Send className="size-5 text-(--accent)" aria-hidden />}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      {picked.length > 0 && (
        <div className="flex flex-wrap gap-1.5" aria-label="Picked">
          {picked.map((id) => (
            <button key={id} type="button" onClick={() => toggle(id)} aria-label={`Remove ${known.get(id)?.name ?? 'person'}`}
              className="inline-flex min-h-9 items-center gap-1 rounded-full bg-(--accent-subtle) px-3 text-small text-(--accent)">
              {known.get(id)?.name ?? 'Someone'} <X className="size-4" aria-hidden />
            </button>
          ))}
        </div>
      )}
      {picked.length > 1 && !share && (
        <input className={inputCls} value={name} maxLength={40} onChange={(e) => setName(e.target.value)}
          placeholder="Group name (optional), like Saturday crew" aria-label="Group name" />
      )}
      <label className="flex h-11 items-center gap-2 rounded-full border border-(--border) bg-(--bg-surface) px-3.5 focus-within:ring-1 focus-within:ring-(--accent)">
        <SearchIcon className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
        <input type="text" inputMode="search" value={q} onChange={(e) => setQ(e.target.value.slice(0, 40))}
          placeholder="Search friends and club mates" aria-label="Search friends and club mates"
          className="min-w-0 flex-1 bg-transparent text-body text-(--text) outline-none placeholder:text-(--text-muted)" />
      </label>
      {people == null ? (
        <RabbitLoader className="py-6" label="Loading friends" />
      ) : shown.length === 0 ? (
        <p className="px-1 text-small text-(--text-muted)">
          {q ? `No friends or club mates match “${q.trim()}”.` : 'Follow friends or join a club to message them. People you follow back and club mates show here.'}
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-(--border) overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)" aria-label="People">
          {shown.map((p) => {
            const on = picked.includes(p.id)
            return (
              <li key={p.id}>
                <button type="button" aria-pressed={on} onClick={() => toggle(p.id)}
                  className={cn('flex min-h-14 w-full items-center gap-3 px-3 py-2 text-left active:bg-(--bg-inset)', on && 'bg-(--accent-subtle)')}>
                  <PersonAvatar u={{ ...p, photo: p.photo ?? null, picture: p.picture ?? '' }} size={36} />
                  <span className="min-w-0 flex-1 truncate text-body text-(--text)">{p.name}</span>
                  <span className={cn('flex size-6 shrink-0 items-center justify-center rounded-full border', on ? 'border-(--accent) bg-(--accent) text-(--on-fill)' : 'border-(--border-strong)')} aria-hidden>
                    {on && <Check className="rb-tick size-4" />}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
      {picked.length > 0 && (
        <textarea className={cn(inputCls, 'min-h-20 py-2')} value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)}
          placeholder={share ? 'Add a note (optional)' : 'Write a message (optional)'} aria-label="Message" />
      )}
    </Sheet>
  )
}
