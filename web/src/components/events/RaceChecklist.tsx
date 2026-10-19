// "Race checklist" page (server: racechecklist.py): everything to do for a race, counted back from
// race day. The window you're in ("Up now") is open; the others fold. Tap a row to tick it,
// hide items you don't need (Undo; they're listed at the bottom), add your own per window. A
// little hop when a window is all done. Opened from the event page, race cards, the race pack,
// race week and Home (lib/racechecklist openChecklist).
import type React from 'react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, EyeOff, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { RabbitLoader } from '@/components/RabbitLoader'
import { Screen, inputCls } from '@/components/plan/ui'
import { fmtDay } from '@/components/plan/PlanParts'
import { celebrate } from '@/components/fx/motion'
import { cn } from '@/lib/utils'
import { Flag } from 'lucide-react'
import { Related } from '@/components/nav/Related'
import { WhoElse } from '@/components/people/WhoElse'
import { openEvent } from '@/lib/events'
import {
  actChecklist, announceChecklist, dueLabel, getChecklist,
  type BucketId, type Checklist, type ChecklistAction, type ChecklistBucket, type ChecklistItem,
} from '@/lib/racechecklist'

const LOADING = ['Writing your list…', 'Checking the course…', 'Packing the bag…']

/** Done/total as a ring with the count in the middle. */
export function ProgressRing({ done, total, size = 64 }: { done: number; total: number; size?: number }) {
  const r = (size - 8) / 2
  const c = 2 * Math.PI * r
  const pct = total ? done / total : 0
  return (
    <span className="relative inline-flex shrink-0 items-center justify-center" style={{ width: size, height: size }}
      role="img" aria-label={`${done} of ${total} done`}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--border)" strokeWidth={6} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--accent)" strokeWidth={6} strokeLinecap="round"
          className="rb-ring" strokeDasharray={c} strokeDashoffset={c * (1 - pct)} style={{ '--rb-ring': c } as React.CSSProperties} />
      </svg>
      <span className="absolute font-mono text-small font-semibold tabular-nums text-(--text)" aria-hidden>
        {done}/{total}
      </span>
    </span>
  )
}

/** Apply an action to the list locally (instant), before the server answers. */
function optimistic(v: Checklist, a: ChecklistAction): Checklist {
  if (a.action === 'add') return v
  const buckets = v.buckets.map((b) => {
    let items = b.items
    if (a.action === 'check' || a.action === 'uncheck') items = items.map((i) => (i.id === a.item ? { ...i, checked: a.action === 'check' } : i))
    if (a.action === 'hide' || a.action === 'delete') items = items.filter((i) => i.id !== a.item)
    return { ...b, items, done: items.filter((i) => i.checked).length, total: items.length }
  })
  return { ...v, buckets, done: buckets.reduce((n, b) => n + b.done, 0), total: buckets.reduce((n, b) => n + b.total, 0) }
}

export function RaceChecklistScreen({ eventId, onClose }: { eventId: string; onClose: () => void }) {
  const [v, setV] = useState<Checklist | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [closing, setClosing] = useState(false)
  const [open, setOpen] = useState<Set<BucketId>>(new Set())
  const [undo, setUndo] = useState<ChecklistItem | null>(null)
  const load = useCallback(() => {
    setError(null)
    getChecklist(eventId).then((c) => { setV(c); setOpen((o) => (o.size ? o : new Set([c.current]))) }, (e: Error) => setError(e.message))
  }, [eventId])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    if (!undo) return
    const t = window.setTimeout(() => setUndo(null), 5000)
    return () => window.clearTimeout(t)
  }, [undo])
  const close = () => { setClosing(true); window.setTimeout(onClose, 200) }

  async function act(a: ChecklistAction, from?: Element | null) {
    if (!v) return
    const before = v
    const next = optimistic(v, a)
    setV(next); setMsg(null)
    if (a.action === 'check') {
      const b = next.buckets.find((x) => x.items.some((i) => i.id === a.item))
      if (b && b.total > 0 && b.done === b.total) celebrate(from ?? null, 'checkin') // a window all done
    }
    try {
      setV(await actChecklist(eventId, a))
      announceChecklist()
    } catch (e) {
      setV(before)
      setMsg((e as Error).message)
    }
  }
  const toggleOpen = (id: BucketId) => setOpen((o) => { const n = new Set(o); if (n.has(id)) n.delete(id); else n.add(id); return n })

  const ev = v?.event
  const cur = v?.buckets.find((b) => b.current)
  return (
    <Screen title="Race checklist" subtitle={ev ? `${ev.name} · ${fmtDay(ev.date, { weekday: 'short', month: 'short', day: 'numeric' })}` : undefined}
      onClose={close} closing={closing}>
      {!v && !error && (
        <div className="flex flex-col gap-3" aria-busy="true">
          <div className="skeleton h-[96px] rounded-2xl" aria-hidden />
          <div className="skeleton h-[220px] rounded-xl" aria-hidden />
          <RabbitLoader className="py-4" label="Loading your checklist" cycle={LOADING} />
        </div>
      )}
      {error && (
        <div className="flex flex-col items-center gap-3 py-12 text-center">
          <p className="text-body text-(--text-secondary)">{error}</p>
          <Button variant="default" className="h-11 px-4" onClick={load}>Try again</Button>
        </div>
      )}
      {v && (
        <div className="flex flex-col gap-3">
          <section className="flex items-center gap-4 rounded-2xl border border-(--accent)/25 bg-(--accent-subtle) px-4 py-4" aria-label="Progress">
            <ProgressRing done={v.done} total={v.total} />
            <div className="min-w-0 flex-1">
              <p className="font-display text-title-lg leading-tight text-(--brand)">
                {v.days_out > 1 ? `${v.days_out} days to go` : v.days_out === 1 ? 'Tomorrow' : v.days_out === 0 ? 'Race day!' : 'Race done'}
              </p>
              {cur && (
                <p className="text-small text-(--text-secondary)">
                  Up now: <b className="font-semibold text-(--text)">{cur.label}</b> · {cur.done} of {cur.total} done
                </p>
              )}
            </div>
          </section>
          {msg && <p role="alert" className="px-1 text-small text-(--danger)">{msg}</p>}
          {v.buckets.filter((b) => b.total > 0 || b.current).map((b) => (
            <BucketCard key={b.id} b={b} open={open.has(b.id)} onToggle={() => toggleOpen(b.id)}
              onAct={act} onHidden={setUndo} />
          ))}
          {v.hidden.length > 0 && (
            <details className="rounded-xl border border-(--border) bg-(--bg-surface)">
              <summary className="flex min-h-12 cursor-pointer list-none items-center gap-2 px-4 text-body text-(--text-secondary) [&::-webkit-details-marker]:hidden">
                <EyeOff className="size-5" aria-hidden /> <span className="flex-1">{v.hidden.length} hidden</span>
                <ChevronDown className="size-5" aria-hidden />
              </summary>
              <ul className="flex flex-col px-2 pb-2">
                {v.hidden.map((i) => (
                  <li key={i.id} className="flex min-h-11 items-center gap-2 px-2">
                    <span className="min-w-0 flex-1 text-body text-(--text-muted)">{i.text}</span>
                    <Button variant="ghost" className="h-11 gap-1 px-2 text-small" onClick={() => void act({ action: 'unhide', item: i.id })}>
                      <RotateCcw className="size-4" aria-hidden /> Show
                    </Button>
                  </li>
                ))}
              </ul>
            </details>
          )}
          <p className="px-1 text-meta text-(--text-muted)">Saved on your account. Tap a line to tick it; hide what doesn't apply to you.</p>
          {ev && (
            <WhoElse eventName={ev.name} eventDate={ev.date} invite={v.days_out >= 0}
              share={{ type: 'event', ref: { id: eventId }, label: ev.name }} />
          )}
          <Related items={[
            { key: 'race', icon: <Flag className="size-5" />, label: ev ? ev.name : 'The race', sub: 'The race page: details, goal, gear',
              onClick: () => { close(); window.setTimeout(() => openEvent(eventId), 220) } },
          ]} link={{ kind: 'checklist', id: eventId }} />
        </div>
      )}
      {undo && (
        <div role="status" className="pointer-events-none fixed inset-x-0 bottom-[max(16px,env(safe-area-inset-bottom))] z-[80] flex justify-center px-4">
          <div className="pointer-events-auto flex min-h-11 items-center gap-3 rounded-full bg-(--text) px-4 text-small text-(--bg) shadow-lg">
            <span>Hidden</span>
            <button type="button" className="min-h-11 font-semibold underline" onClick={() => { const i = undo; setUndo(null); void act({ action: 'unhide', item: i.id }) }}>Undo</button>
          </div>
        </div>
      )}
    </Screen>
  )
}

function BucketCard({ b, open, onToggle, onAct, onHidden }: {
  b: ChecklistBucket; open: boolean; onToggle: () => void
  onAct: (a: ChecklistAction, from?: Element | null) => Promise<void>; onHidden: (i: ChecklistItem) => void
}) {
  const [adding, setAdding] = useState(false)
  const [text, setText] = useState('')
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => { if (adding) input.current?.focus() }, [adding])
  const all = b.total > 0 && b.done === b.total
  const add = async () => {
    const t = text.trim()
    if (!t) return
    await onAct({ action: 'add', text: t, bucket: b.id })
    setText(''); setAdding(false)
  }
  return (
    <section className={cn('flex flex-col rounded-xl border bg-(--bg-surface)', b.current ? 'border-(--accent)/40' : 'border-(--border)')}
      aria-label={`${b.label}: ${b.done} of ${b.total} done`}>
      <button type="button" aria-expanded={open} onClick={onToggle}
        className="flex min-h-12 items-center gap-2 px-4 py-2 text-left">
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span className="text-body-lg font-semibold text-(--text)">{b.label}</span>
            {b.current && <span className="rounded-full bg-(--accent) px-2.5 py-0.5 text-meta font-semibold text-(--on-fill)">Up now</span>}
          </span>
          <span className="block text-meta text-(--text-muted)">
            {all ? 'All done' : `${b.done} of ${b.total} done`}{!b.past && !all ? ` · ${dueLabel(b.due)}` : ''}
            {b.past && !all ? ' · window passed' : ''}
          </span>
        </span>
        {all && <Check className="rb-tick size-5 text-(--accent)" aria-hidden />}
        <ChevronDown className={cn('size-5 text-(--text-muted) transition-transform', open && 'rotate-180')} aria-hidden />
      </button>
      {open && (
        <div className="flex flex-col border-t border-(--border) pb-2">
          <ul className="flex flex-col">
            {b.items.map((i) => (
              <li key={i.id} className="flex items-stretch">
                <button type="button" role="checkbox" aria-checked={i.checked}
                  onClick={(e) => void onAct({ action: i.checked ? 'uncheck' : 'check', item: i.id }, e.currentTarget)}
                  className="flex min-h-12 min-w-0 flex-1 items-start gap-3 px-4 py-2.5 text-left active:bg-(--bg-inset)">
                  <span aria-hidden className={cn('mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border-2 transition-colors',
                    i.checked ? 'border-(--accent) bg-(--accent) text-(--on-fill)' : 'border-(--border-strong)')}>
                    {i.checked && <Check className="rb-tick size-4" strokeWidth={3} />}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className={cn('block text-body leading-snug', i.checked ? 'text-(--text-muted) line-through' : 'text-(--text)')}>{i.text}</span>
                    {i.note && !i.checked && <span className="mt-0.5 block text-meta leading-snug text-(--text-muted)">{i.note}</span>}
                  </span>
                </button>
                <button type="button" className="flex w-11 shrink-0 items-center justify-center text-(--text-muted)"
                  aria-label={i.custom ? `Delete "${i.text}"` : `Hide "${i.text}"`}
                  onClick={() => { void onAct({ action: i.custom ? 'delete' : 'hide', item: i.id }); if (!i.custom) onHidden(i) }}>
                  {i.custom ? <Trash2 className="size-5" aria-hidden /> : <EyeOff className="size-5" aria-hidden />}
                </button>
              </li>
            ))}
          </ul>
          {adding ? (
            <div className="flex items-center gap-2 px-4 pt-1">
              <input ref={input} className={inputCls} value={text} maxLength={120} placeholder="Something else to do"
                aria-label={`Add your own item to ${b.label}`}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') void add(); if (e.key === 'Escape') setAdding(false) }} />
              <Button variant="primary" className="h-11 shrink-0 px-3 text-small" disabled={!text.trim()} onClick={() => void add()}>Add</Button>
            </div>
          ) : (
            <button type="button" onClick={() => setAdding(true)}
              className="mx-4 mt-1 flex min-h-11 items-center gap-1.5 text-small text-(--accent)">
              <Plus className="size-5" aria-hidden /> Add your own
            </button>
          )}
        </div>
      )}
    </section>
  )
}
