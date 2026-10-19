// "Your threshold moved" (server: paces.py): one sheet with the suggestion, "See why" (the
// efforts used and the ones skipped), Update / Not now / Never for this; after Update it shows
// what changed with Undo (24 h). PaceHost opens it from anywhere via openPaceSuggestion().
import { useEffect, useState } from 'react'
import { Check, ChevronDown, TrendingDown, TrendingUp } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { RabbitLoader } from '@/components/RabbitLoader'
import { fmtPaceKm, fmtSwimPace } from '@/lib/format'
import {
  acceptPace, dismissPace, getPaces, undoPace, SPORT_NAME,
  type PaceAccepted, type PaceOpen, type PaceSport, type PaceSuggestion,
} from '@/lib/paces'

export function fmtThreshold(sport: PaceSport, v: number, imperial: boolean): string {
  if (sport === 'run') return fmtPaceKm(v, imperial)
  if (sport === 'bike') return `${Math.round(v)} W`
  return fmtSwimPace(v)
}

type Done = { summary: string; undoId: string | null; undone?: boolean }

export function PaceSheet({ suggestion, imperial, onClose, onChanged, accepted }: {
  suggestion: PaceSuggestion | null
  imperial: boolean
  onClose: () => void
  /** the profile number changed (accept/undo): `{field: value}` */
  onChanged?: (patch: Record<string, number | null>) => void
  /** already applied (one-tap Update from a moment) */
  accepted?: PaceAccepted | null
}) {
  const s = suggestion
  const [why, setWhy] = useState(false)
  const [busy, setBusy] = useState<'accept' | 'later' | 'never' | 'undo' | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [done, setDone] = useState<Done | null>(accepted ? { summary: accepted.summary, undoId: accepted.undo.id } : null)

  async function act(kind: 'accept' | 'later' | 'never') {
    if (!s) return
    setBusy(kind); setErr(null)
    try {
      if (kind === 'accept') {
        const r = await acceptPace(s.id)
        setDone({ summary: r.summary, undoId: r.undo.id })
        onChanged?.({ [r.field]: r.value })
      } else {
        await dismissPace(s.id, kind === 'never')
        onClose()
      }
    } catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }

  async function undo() {
    if (!done?.undoId) return
    setBusy('undo'); setErr(null)
    try {
      const r = await undoPace(done.undoId)
      setDone({ summary: 'Undone. Your paces are back to what they were.', undoId: null, undone: true })
      onChanged?.({ [r.field]: r.value })
    } catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }

  const Icon = s?.direction === 'slower' ? TrendingDown : TrendingUp
  const footer = done ? (
    <div className="flex gap-2">
      {done.undoId && <Button variant="default" className="h-11 flex-1 text-body" loading={busy === 'undo'} onClick={() => void undo()}>Undo</Button>}
      <Button variant="primary" className="h-11 flex-1 text-body" onClick={onClose}>Done</Button>
    </div>
  ) : s ? (
    <div className="flex flex-col gap-1">
      <div className="flex gap-2">
        <Button variant="default" className="h-11 flex-1 text-body" loading={busy === 'later'} disabled={!!busy} onClick={() => void act('later')}>Not now</Button>
        <Button variant="primary" className="h-11 flex-[1.4] text-body" loading={busy === 'accept'} disabled={!!busy} onClick={() => void act('accept')}>
          {s.direction === 'slower' ? 'Ease my paces' : s.sport === 'bike' ? 'Update my zones' : 'Update my paces'}
        </Button>
      </div>
      <button type="button" disabled={!!busy} onClick={() => void act('never')}
        className="hit-44 mx-auto min-h-11 px-3 text-meta text-(--text-muted) underline-offset-2 hover:underline disabled:opacity-50">
        Never suggest this for {s.sport === 'run' ? 'running' : s.sport === 'bike' ? 'cycling' : 'swimming'}
      </button>
    </div>
  ) : undefined

  return (
    <Sheet title={s ? SPORT_NAME[s.sport] : 'Training paces'} onClose={onClose} dismissible={!busy} footer={footer} portal>
      {done ? (
        <div className="flex items-start gap-3 rounded-xl border border-(--border) bg-(--bg-surface) p-3" role="status">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-(--accent-subtle) text-(--accent)" aria-hidden><Check className="size-6" /></span>
          <div className="min-w-0">
            <p className="m-0 text-body-lg font-medium leading-snug text-(--text)">{done.summary}</p>
            {!done.undone && <p className="m-0 mt-1 text-meta text-(--text-muted)">Past workouts keep the targets they had. You can undo this for 24 hours.</p>}
          </div>
        </div>
      ) : !s ? (
        <p className="m-0 text-body text-(--text-secondary)">That suggestion isn't current any more. Your training paces live in Me → Training profile → Zones.</p>
      ) : (
        <>
          <div className="flex items-start gap-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-(--accent-subtle) text-(--accent)" aria-hidden><Icon className="size-6" /></span>
            <p className="m-0 text-body-lg leading-snug text-(--text)">{s.headline}</p>
          </div>
          <div className="flex items-center justify-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-3">
            {s.old != null && <>
              <span className="text-center">
                <span className="block text-caption text-(--text-muted) font-semibold">Now</span>
                <span className="font-mono text-title-sm tabular-nums text-(--text-secondary)">{fmtThreshold(s.sport, s.old, imperial)}</span>
              </span>
              <span className="text-(--text-muted)" aria-hidden>→</span>
            </>}
            <span className="text-center">
              <span className="block text-caption text-(--accent) font-semibold">New</span>
              <span className="font-mono text-title-sm font-semibold tabular-nums text-(--text)">{fmtThreshold(s.sport, s.new, imperial)}</span>
            </span>
          </div>
          {s.capped && <p className="m-0 px-1 text-meta text-(--text-muted)">Your efforts point even further, so rabbt moves one safe step now and checks again in two weeks.</p>}
          <button type="button" aria-expanded={why} onClick={() => setWhy((v) => !v)}
            className="hit-44 flex min-h-11 items-center gap-1.5 self-start px-1 text-small font-medium text-(--accent)">
            See why <ChevronDown className={`size-5 transition-transform ${why ? 'rotate-180' : ''}`} aria-hidden />
          </button>
          {why && (
            <div className="flex flex-col gap-2 rounded-xl border border-(--border) bg-(--bg-surface) p-3">
              <ul className="m-0 flex list-none flex-col gap-2 p-0">
                {s.efforts.map((e, i) => (
                  <li key={`${e.activity_id ?? 'g'}-${i}`} className="flex flex-col">
                    <span className="text-small font-medium text-(--text)">{e.label[0].toUpperCase() + e.label.slice(1)}</span>
                    <span className="font-mono text-meta tabular-nums text-(--text-secondary)">{e.detail}</span>
                  </li>
                ))}
              </ul>
              {s.skipped.length > 0 && (
                <p className="m-0 text-meta text-(--text-muted)">
                  Left out: {s.skipped.map((k) => `${k.label} (${k.reason})`).join(', ')}.
                </p>
              )}
              <p className="m-0 text-meta text-(--text-muted)">
                rabbt looks at quality efforts from the last 3 weeks (tempo and threshold laps, races, hard 20-60 min efforts) and skips hot, hilly or high-altitude ones. Only today's and future workouts change.
              </p>
            </div>
          )}
        </>
      )}
      {err && <ErrorState compact message={err} />}
    </Sheet>
  )
}

/** Mounted once (Chat.tsx): opens the sheet for `rabbit:pace` events from moment chips. */
export function PaceHost({ onChanged }: { onChanged?: (patch: Record<string, number | null>) => void }) {
  const [open, setOpen] = useState<PaceOpen | null>(null)
  const [state, setState] = useState<{ s: PaceSuggestion | null; imperial: boolean; accepted: PaceAccepted | null } | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    const on = (e: Event) => { setOpen((e as CustomEvent<PaceOpen>).detail ?? {}); setState(null); setErr(null) }
    window.addEventListener('rabbit:pace', on)
    return () => window.removeEventListener('rabbit:pace', on)
  }, [])

  useEffect(() => {
    if (!open) return
    let live = true
    void (async () => {
      try {
        const v = await getPaces()
        const s = v.pending.find((p) => p.id === open.sid) ?? (open.sid ? null : v.pending.find((p) => p.sport === open.sport) ?? null)
        let accepted: PaceAccepted | null = null
        if (s && open.accept) { accepted = await acceptPace(s.id); onChanged?.({ [accepted.field]: accepted.value }) }
        if (live) setState({ s, imperial: v.units !== 'metric', accepted })
      } catch (e) { if (live) setErr((e as Error).message) }
    })()
    return () => { live = false }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!open) return null
  const close = () => { setOpen(null); setState(null) }
  if (!state) {
    return (
      <Sheet title="Training paces" onClose={close} portal>
        {err ? <ErrorState message={err} onRetry={() => setOpen({ ...open })} />
          : <RabbitLoader label={open.accept ? 'Updating your paces' : 'Checking your efforts'} />}
      </Sheet>
    )
  }
  return <PaceSheet suggestion={state.s} imperial={state.imperial} accepted={state.accepted} onClose={close} onChanged={onChanged} />
}
