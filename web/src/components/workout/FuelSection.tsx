// The workout page's "Fuel" section (server: nutrition.fuel_plan): Before / During / After, each
// one bold line plus a few food ideas, the night-before nudge for early long or hard sessions,
// and a "Fueling preferences" sheet (gels or real food, caffeine, diet) that reshapes the ideas.
import { useState } from 'react'
import { Coffee, Moon, SlidersHorizontal, Utensils } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/button'
import { FuelFields } from '@/components/plan/ProfileFields'
import { putAthlete } from '@/lib/api'
import type { AthleteFull } from '@/lib/plan'
import type { FuelPart, FuelPlan } from '@/lib/workout'
import { cn } from '@/lib/utils'

function Chips({ items }: { items: string[] }) {
  if (!items.length) return null
  return (
    <ul className="mt-1.5 flex flex-wrap gap-1.5" aria-label="Ideas">
      {items.map((x) => (
        <li key={x} className="rounded-full bg-(--bg-inset) px-2.5 py-1 text-meta leading-tight text-(--text-secondary)">{x}</li>
      ))}
    </ul>
  )
}

function Row({ label, part, children, first }: { label: string; part: FuelPart; children?: React.ReactNode; first?: boolean }) {
  return (
    <div className={cn('flex gap-3 px-3.5 py-2.5', !first && 'border-t border-(--border)')}>
      <span className="w-[3.6rem] shrink-0 pt-0.5 text-caption font-semibold text-(--accent)">{label}</span>
      <div className="min-w-0 flex-1">
        <p className="text-body leading-snug text-(--text)">
          {part.when ? <><b className="font-semibold">{part.when}: </b>{part.headline}</> : <b className="font-semibold">{part.headline}</b>}
        </p>
        {children}
        <Chips items={part.items} />
        {part.tip && <p className="mt-1.5 text-meta leading-snug text-(--text-muted)">{part.tip}</p>}
      </div>
    </div>
  )
}

export function FuelSection({ fp, ahead, onSaved }: { fp: FuelPlan; ahead: boolean; onSaved: () => void }) {
  const [prefs, setPrefs] = useState(false)
  const d = fp.during
  return (
    <section aria-label="Fuel" className="flex flex-col rounded-xl border border-(--border) bg-(--bg-surface)">
      <div className="flex items-center gap-1.5 px-3.5 pt-3">
        <h4 className="font-sans flex flex-1 items-center gap-1.5 text-caption font-semibold text-(--text-muted)">
          <Utensils className="size-4" aria-hidden />Fuel
        </h4>
        <button type="button" onClick={() => setPrefs(true)}
          className="-my-2 -mr-2 inline-flex min-h-11 items-center gap-1 rounded-full px-2.5 text-meta font-medium text-(--accent) active:bg-(--bg-inset)">
          <SlidersHorizontal className="size-4" aria-hidden /> Preferences
        </button>
      </div>
      {ahead && fp.night_before && (
        <p className="mx-3.5 mt-2 flex items-start gap-2 rounded-lg bg-(--accent-subtle) px-2.5 py-2 text-small leading-snug text-(--text)">
          <Moon className="mt-0.5 size-4 shrink-0 text-(--accent)" aria-hidden />{fp.night_before}
        </p>
      )}
      <div className="mt-1 flex flex-col">
        <Row label="Before" part={fp.before} first>
          {fp.before.hydration && <p className="mt-0.5 text-meta text-(--text-muted)">{fp.before.hydration}</p>}
        </Row>
        <Row label="During" part={{ ...d, when: undefined, tip: d.note ?? null }}>
          <p className="mt-0.5 text-small leading-snug text-(--text-secondary)">
            {d.carbs_g_per_h > 0 ? <><span className="text-(--text)">{d.plan}</span>{d.start ? `. ${d.start}` : ''}</> : d.plan}
          </p>
          {(d.fluids || d.sodium) && (
            <p className="mt-0.5 text-meta text-(--text-muted)">
              {[d.fluids && `Drink ${d.fluids}`, d.sodium].filter(Boolean).join(' · ')}
              {d.total_carbs_g ? ` · ≈${d.total_carbs_g} g carbs in all` : ''}
            </p>
          )}
          {d.heat && <p className="mt-0.5 text-meta text-(--text-muted)">{d.heat}</p>}
        </Row>
        <Row label="After" part={fp.after} />
      </div>
      {(fp.caffeine || fp.learn_more) && (
        <div className="flex flex-col gap-1 border-t border-(--border) px-3.5 pb-3 pt-2.5">
          {fp.caffeine && (
            <p className="flex items-start gap-1.5 text-meta leading-snug text-(--text-muted)">
              <Coffee className="mt-px size-4 shrink-0" aria-hidden />{fp.caffeine}
            </p>
          )}
          {d.carbs_g_per_h > 0 && <p className="text-meta leading-snug text-(--text-muted)">{fp.learn_more}</p>}
        </div>
      )}
      {prefs && <FuelPrefsSheet fp={fp} onClose={() => setPrefs(false)} onSaved={() => { setPrefs(false); onSaved() }} />}
    </section>
  )
}

function FuelPrefsSheet({ fp, onClose, onSaved }: { fp: FuelPlan; onClose: () => void; onSaved: () => void }) {
  const [a, setA] = useState<Partial<AthleteFull>>({
    fuel_style: fp.prefs?.fuel_style ?? null, caffeine: fp.prefs?.caffeine ?? null, diet: fp.prefs?.diet ?? [],
  })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const save = async () => {
    setBusy(true); setErr(null)
    try {
      const patch: Partial<AthleteFull> = { fuel_style: a.fuel_style ?? null, caffeine: a.caffeine ?? null, diet: a.diet ?? [] }
      await putAthlete(patch)
      onSaved()
    } catch (e) { setErr((e as Error).message || "Couldn't save just now.") } finally { setBusy(false) }
  }
  return (
    <Sheet title="Fueling preferences" onClose={onClose} dismissible={!busy} portal
      footer={(
        <div className="flex flex-col gap-2">
          {err && <p role="alert" className="text-small text-(--danger)">{err}</p>}
          <Button variant="primary" className="h-11 w-full" loading={busy} onClick={() => void save()}>Save</Button>
        </div>
      )}>
      <div className="flex flex-col gap-3 p-4">
        <p className="text-small leading-snug text-(--text-secondary)">
          Shapes the food ideas on every workout. Also in Me › Training profile.
        </p>
        <FuelFields a={a} setA={(p) => setA((x) => ({ ...x, ...p }))} />
      </div>
    </Sheet>
  )
}
