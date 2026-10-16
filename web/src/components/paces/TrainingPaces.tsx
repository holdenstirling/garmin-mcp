// Profile -> Zones: the paces/power your workouts target right now (run pace zones, bike power
// zones, swim pace), where each number came from, and Rabbit's pending suggestion if any.
// The numbers themselves are edited in the fields below this card (manual edit).
import { useCallback, useEffect, useState } from 'react'
import { ChevronDown, TrendingUp } from 'lucide-react'
import { Card } from '@/components/plan/ui'
import { ErrorState } from '@/components/ui/ErrorState'
import { Skeleton } from '@/components/ui/Skeleton'
import { fmtPaceKm, fmtSwimPace } from '@/lib/format'
import { getPaces, setPaceSuggestions, undoPace, SPORT_NAME, type PaceRow, type PaceSport, type PacesView, type PaceSuggestion } from '@/lib/paces'
import { PaceSheet, fmtThreshold } from './PaceSheet'

const ORDER: PaceSport[] = ['run', 'bike', 'swim']
const EMPTY: Record<PaceSport, string> = {
  run: 'Add your threshold pace below, or Rabbit will suggest one after a couple of tempo runs or a race.',
  bike: 'Add your FTP below, or Rabbit will suggest one after a couple of rides with a power meter.',
  swim: 'Add your CSS below, or Rabbit will suggest one from your pool sets.',
}

function zoneText(sport: PaceSport, lo: number, hi: number, imperial: boolean): string {
  if (sport === 'run') return `${fmtPaceKm(lo, imperial, false)}–${fmtPaceKm(hi, imperial)}`
  if (sport === 'bike') return `${lo}–${hi} W`
  return `${fmtSwimPace(lo, false)}–${fmtSwimPace(hi)}`
}

function Row({ sport, row, imperial, onToggle }: { sport: PaceSport; row: PaceRow; imperial: boolean; onToggle: (on: boolean) => void }) {
  const [open, setOpen] = useState(false)
  const id = `paces-${sport}`
  return (
    <div className="border-t border-(--border) px-4 py-3 first:border-t-0">
      <button type="button" aria-expanded={open} aria-controls={id} disabled={row.value == null} onClick={() => setOpen((v) => !v)}
        className="flex min-h-11 w-full items-center gap-3 text-left">
        <span className="min-w-0 flex-1">
          <span className="block text-[0.8235rem] font-medium text-(--text)">{SPORT_NAME[sport]}</span>
          <span className="block text-[0.6471rem] text-(--text-muted)">
            {row.value == null ? 'Not set' : row.source ? row.source.label : 'Set in your profile'}
          </span>
        </span>
        {row.value != null && <span className="font-mono text-[0.9412rem] tabular-nums text-(--text)">{fmtThreshold(sport, row.value, imperial)}</span>}
        {row.value != null && <ChevronDown className={`size-4 shrink-0 text-(--text-muted) transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden />}
      </button>
      {row.value == null && <p className="m-0 mt-1 text-[0.7059rem] leading-snug text-(--text-muted)">{EMPTY[sport]}</p>}
      {open && row.value != null && (
        <div id={id} className="mt-1">
          <ul className="m-0 grid list-none grid-cols-[auto_1fr_auto] gap-x-3 gap-y-1 p-0 text-[0.7059rem]">
            {row.zones.map((z) => (
              <li key={z.zone} className="contents">
                <span className="font-mono text-(--text-muted)">Z{z.zone}</span>
                <span className="capitalize text-(--text-secondary)">{z.name}</span>
                <span className="text-right font-mono tabular-nums text-(--text)">{zoneText(sport, z.lo, z.hi, imperial)}</span>
              </li>
            ))}
          </ul>
          <label className="mt-2 flex min-h-11 items-center justify-between gap-3 text-[0.7059rem] text-(--text-secondary)">
            Suggest updates from my workouts
            <input type="checkbox" className="size-5 accent-(--accent)" checked={row.suggestions} onChange={(e) => onToggle(e.target.checked)} />
          </label>
        </div>
      )}
    </div>
  )
}

export function TrainingPaces({ refreshKey, onChanged }: {
  refreshKey?: unknown
  /** the profile numbers changed (accept/undo): `{field: value}` */
  onChanged?: (patch: Record<string, number | null>) => void
}) {
  const [v, setV] = useState<PacesView | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [sheet, setSheet] = useState<PaceSuggestion | null>(null)
  const [busy, setBusy] = useState(false)
  const load = useCallback(() => {
    setErr(null)
    getPaces().then(setV, (e) => setErr((e as Error).message))
  }, [])
  useEffect(load, [load, refreshKey])

  if (err) return <ErrorState compact message={err} onRetry={load} />
  if (!v) return <Skeleton className="h-40 rounded-xl" />
  const imperial = v.units === 'imperial'
  const changed = (patch: Record<string, number | null>) => { load(); onChanged?.(patch) }

  async function undo() {
    if (!v?.undo) return
    setBusy(true)
    try { const r = await undoPace(v.undo.id); changed({ [r.field]: r.value }) } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  return (<>
    {v.pending.map((p) => (
      <button key={p.id} type="button" onClick={() => setSheet(p)}
        className="flex items-center gap-3 rounded-xl border border-(--accent)/40 bg-(--accent-subtle) px-4 py-3 text-left active:opacity-80">
        <TrendingUp className="size-5 shrink-0 text-(--accent)" aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="block text-[0.8235rem] font-medium text-(--text)">{SPORT_NAME[p.sport]}: {p.old != null ? `${fmtThreshold(p.sport, p.old, imperial)} → ` : ''}{fmtThreshold(p.sport, p.new, imperial)}</span>
          <span className="block text-[0.6471rem] text-(--text-secondary)">Rabbit suggests an update. Tap to see why.</span>
        </span>
      </button>
    ))}
    {v.undo && (
      <div className="flex items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-4 py-2" role="status">
        <p className="m-0 min-w-0 flex-1 text-[0.7059rem] text-(--text-secondary)">{v.undo.summary}</p>
        <button type="button" disabled={busy} onClick={() => void undo()}
          className="hit-44 min-h-11 shrink-0 px-2 text-[0.7647rem] font-medium text-(--accent) disabled:opacity-50">Undo</button>
      </div>
    )}
    <Card>
      {ORDER.map((s) => (
        <Row key={s} sport={s} row={v[s]} imperial={imperial}
          onToggle={(on) => { setPaceSuggestions(s, on).then(load, (e) => setErr((e as Error).message)) }} />
      ))}
    </Card>
    {sheet && <PaceSheet suggestion={sheet} imperial={imperial} onClose={() => { setSheet(null); load() }} onChanged={changed} />}
  </>)
}
