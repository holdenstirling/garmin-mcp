// HYROX race card on the plan screen (server: hyrox.py pacing): the division, and when a
// target time is set, an estimated split of 8 x 1 km runs, 8 stations and the roxzone.
import { useState } from 'react'
import { ChevronDown, Dumbbell } from 'lucide-react'
import type { HyroxInfo } from '@/lib/plan'

const DIVISION: Record<HyroxInfo['division'], string> = { open: 'Open', pro: 'Pro', doubles: 'Doubles', relay: 'Relay' }

export function HyroxPacing({ info }: { info: HyroxInfo }) {
  const [open, setOpen] = useState(false)
  const p = info.pacing
  return (
    <section aria-labelledby="hyrox-pacing" className="flex flex-col gap-3 rounded-2xl border border-(--border) bg-(--bg-surface) p-4">
      <div className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-(--accent-subtle) text-(--accent)" aria-hidden>
          <Dumbbell className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 id="hyrox-pacing" className="m-0 text-body font-semibold text-(--text)">HYROX, {DIVISION[info.division] ?? 'Open'} division</h3>
          <p className="m-0 mt-0.5 text-small leading-snug text-(--text-secondary)">
            8 x 1 km runs, each followed by a station. {info.weights_note}
          </p>
        </div>
      </div>
      {p ? (
        <>
          <div className="grid grid-cols-3 gap-2">
            <Stat label="Target" value={p.total} />
            <Stat label="Each 1 km" value={p.run_pace_per_km} />
            <Stat label="Roxzone" value={p.roxzone} />
          </div>
          <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)}
            className="hit-44 flex items-center justify-between gap-2 text-left text-small font-medium text-(--accent)">
            {open ? 'Hide the race splits' : 'See the race splits (estimate)'}
            <ChevronDown className={`size-4 transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden />
          </button>
          {open && (
            <ol className="m-0 flex list-none flex-col divide-y divide-(--border) p-0">
              {p.legs.map((l, i) => (
                <li key={i} className="flex items-center justify-between gap-3 py-2 text-small">
                  <span className="min-w-0 text-(--text)">{l.run}, then {l.station}</span>
                  <span className="shrink-0 font-mono text-(--text-secondary)">{l.run_time} + {l.station_time}</span>
                </li>
              ))}
            </ol>
          )}
          <p className="m-0 text-meta leading-snug text-(--text-muted)">{p.note}</p>
        </>
      ) : (
        <p className="m-0 text-meta text-(--text-muted)">Add a target time to your goal to see an estimated race split.</p>
      )}
    </section>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-xl bg-(--bg-inset) px-3 py-2">
      <span className="text-caption text-(--text-muted)">{label}</span>
      <span className="font-mono text-body font-medium text-(--text)">{value}</span>
    </div>
  )
}
