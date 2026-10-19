// "Fueling" on the workout page and the recorded-workout page (sessions of an hour or more,
// long sessions and bricks): what you took (product chips or grams), fluids, sodium, how
// often, how your gut felt and your energy late on. Saved per session/activity (body.py);
// after saving, Rabbit's learnings across long sessions (carbs/hour that work for you).
import { useEffect, useState } from 'react'
import { Minus, Plus, Utensils } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { RabbitNote } from '@/components/ui/brand'
import { RabbitInline } from '@/components/chat/RabbitText'
import { cn } from '@/lib/utils'
import { haptic } from '@/lib/haptics'
import {
  deleteFuel, fromFluidUnit, getFuel, openBody, saveFuel, toFluidUnit,
  type FuelEntry, type FuelLearnings, type Product,
} from '@/lib/body'

const GI = [['great', 'Gut felt great'], ['ok', 'OK'], ['issues', 'Gut issues']] as const
const ENERGY = [['strong', 'Strong to the end'], ['faded', 'Faded'], ['bonked', 'Bonked']] as const
const EVERY = [10, 15, 20, 30, 45, 60]

/** Show the log for long-ish sessions only (an hour or more, long sessions, bricks). */
export function wantsFuelLog(minutes: number | null | undefined, kind?: string | null, sport?: string | null): boolean {
  return (minutes ?? 0) >= 60 || kind === 'long' || sport === 'brick'
}

export function FuelLog({ fuelKey, minutes, sport, title, date, imperial, plannedGh }: {
  /** "s:<session id>" or "a:<activity key>" */
  fuelKey: string; minutes: number; sport: string; title: string; date: string; imperial: boolean
  /** the plan's fueling target for this session (g/h), if any */
  plannedGh?: number | null
}) {
  const [products, setProducts] = useState<Record<string, Product> | null>(null)
  const [entry, setEntry] = useState<FuelEntry | null>(null)
  const [learn, setLearn] = useState<FuelLearnings | null>(null)
  const [open, setOpen] = useState(false)
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [grams, setGrams] = useState<Record<string, number>>({})
  const [carbs, setCarbs] = useState<string>('')
  const [fluid, setFluid] = useState<string>('')
  const [sodium, setSodium] = useState<string>('')
  const [every, setEvery] = useState<number | null>(null)
  const [gi, setGi] = useState<FuelEntry['gi']>(null)
  const [energy, setEnergy] = useState<FuelEntry['energy']>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [mins, setMins] = useState(minutes)

  useEffect(() => {
    let live = true
    getFuel(fuelKey).then((r) => { if (live) { setProducts(r.products); setEntry(r.entry) } }, () => { if (live) setProducts({}) })
    return () => { live = false }
  }, [fuelKey])

  function startEdit() {
    const e = entry
    const c: Record<string, number> = {}
    const g: Record<string, number> = {}
    for (const it of e?.items ?? []) { c[it.product] = it.count; g[it.product] = it.g }
    setCounts(c); setGrams(g)
    setCarbs(e && !(e.items?.length) ? String(e.carbs_g) : '')
    setFluid(e?.fluids_ml != null ? String(toFluidUnit(e.fluids_ml, imperial)) : '')
    setSodium(e?.sodium_mg != null ? String(e.sodium_mg) : '')
    setEvery(e?.every_min ?? null); setGi(e?.gi ?? null); setEnergy(e?.energy ?? null); setNote(e?.note ?? '')
    setMins(e?.minutes ?? minutes); setErr(null); setOpen(true)
  }

  const itemTotal = Object.entries(counts).reduce((t, [p, n]) => t + n * (grams[p] ?? products?.[p]?.g ?? 0), 0)
  const totalCarbs = carbs.trim() ? Number(carbs) : itemTotal
  const gh = mins > 0 ? Math.round(totalCarbs / (mins / 60)) : 0

  async function save() {
    setBusy(true); setErr(null)
    try {
      const items = Object.entries(counts).filter(([, n]) => n > 0).map(([p, n]) => ({ product: p, count: n, g: grams[p] ?? products?.[p]?.g }))
      const num = (v: string) => (v.trim() ? Number(v) : undefined)
      const r = await saveFuel(fuelKey, {
        minutes: mins, items, carbs_g: carbs.trim() ? Number(carbs) : undefined,
        fluids_ml: fluid.trim() ? fromFluidUnit(Number(fluid), imperial) : undefined,
        sodium_mg: num(sodium), every_min: every ?? undefined, gi: gi ?? undefined, energy: energy ?? undefined,
        note, sport: ['run', 'bike', 'swim', 'brick'].includes(sport) ? sport : 'other', title, date,
      })
      setEntry(r.entry); setLearn(r.learnings); setOpen(false); haptic()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  async function remove() {
    setBusy(true)
    try { await deleteFuel(fuelKey); setEntry(null); setOpen(false) } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  if (products === null) return <div className="skeleton h-[72px] rounded-xl" aria-hidden />
  const fl = imperial ? 'fl oz' : 'ml'
  return (
    <section aria-label="Fueling" className="flex flex-col gap-3 rounded-xl border border-(--border) bg-(--bg-surface) p-3.5">
      <div className="flex items-center gap-2">
        <Utensils className="size-5 text-(--accent)" aria-hidden />
        <h4 className="font-sans flex-1 text-caption font-semibold text-(--text-muted)">Fueling</h4>
        {plannedGh ? <span className="text-meta text-(--text-muted)">Plan: {plannedGh} g/h</span> : null}
      </div>

      {!open && entry && (
        <div className="flex flex-col gap-2">
          <p className="m-0 text-body text-(--text)">
            <b className="font-semibold">{entry.g_per_h ?? 0} g carbs/h</b>
            {entry.ml_per_h != null && <> · {toFluidUnit(entry.ml_per_h, imperial)} {fl}/h</>}
            {entry.mg_per_h != null && <> · {entry.mg_per_h} mg sodium/h</>}
          </p>
          <p className="m-0 text-meta text-(--text-muted)">
            {[entry.carbs_g ? `${entry.carbs_g} g in ${entry.minutes} min` : '', entry.every_min ? `every ${entry.every_min} min` : '',
              entry.gi ? GI.find(([v]) => v === entry.gi)?.[1] : '', entry.energy ? ENERGY.find(([v]) => v === entry.energy)?.[1] : '']
              .filter(Boolean).join(' · ')}
          </p>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="hit-44 text-small font-medium text-(--accent)" onClick={startEdit}>Edit</button>
            <button type="button" className="hit-44 text-small font-medium text-(--accent)" onClick={() => openBody({ view: 'fueling' })}>What rabbt's learned</button>
          </div>
        </div>
      )}
      {!open && !entry && (
        <div className="flex flex-col gap-2">
          <p className="m-0 text-small text-(--text-secondary)">Log what you ate and drank. rabbt learns which carbs per hour work for you before race day.</p>
          <Button variant="default" className="h-11 gap-1.5 text-body" onClick={startEdit}><Plus className="size-5" aria-hidden />Log fueling</Button>
        </div>
      )}

      {open && (
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <span className="text-small text-(--text)">What you took</span>
            <ul className="flex flex-col gap-1">
              {Object.entries(products).map(([id, p]) => {
                const n = counts[id] ?? 0
                return (
                  <li key={id} className="flex min-h-11 items-center gap-2">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-body text-(--text)">{p.label}</span>
                      <span className="flex items-center gap-1 text-meta text-(--text-muted)">
                        <input type="number" inputMode="numeric" min={0} max={150} aria-label={`${p.label}: grams of carbs each`}
                          value={grams[id] ?? p.g} onChange={(e) => setGrams((g) => ({ ...g, [id]: Number(e.target.value) || 0 }))}
                          className="h-9 w-14 rounded border border-input bg-transparent px-1 text-center text-meta tabular-nums" />g carbs each
                      </span>
                    </span>
                    <button type="button" className="flex size-11 items-center justify-center rounded-md border border-input disabled:opacity-40"
                      aria-label={`One less ${p.label}`} disabled={!n} onClick={() => setCounts((c) => ({ ...c, [id]: Math.max(0, n - 1) }))}><Minus className="size-5" aria-hidden /></button>
                    <span className="w-6 text-center font-mono text-body tabular-nums" aria-live="polite">{n}</span>
                    <button type="button" className="flex size-11 items-center justify-center rounded-md border border-input"
                      aria-label={`One more ${p.label}`} onClick={() => setCounts((c) => ({ ...c, [id]: n + 1 }))}><Plus className="size-5" aria-hidden /></button>
                  </li>
                )
              })}
            </ul>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Num label="Total carbs (g)" value={carbs} placeholder={String(itemTotal)} onChange={setCarbs} />
            <Num label={`Fluids (${fl})`} value={fluid} placeholder={imperial ? '24' : '700'} onChange={setFluid} />
            <Num label="Sodium (mg, optional)" value={sodium} placeholder="400" onChange={setSodium} />
            <Num label="Duration (min)" value={String(mins)} onChange={(v) => setMins(Number(v) || 0)} />
          </div>
          <p className="m-0 text-small text-(--text-secondary)" aria-live="polite">
            That's <b className="font-semibold text-(--text)">{gh} g carbs per hour</b>{plannedGh ? ` (plan: ${plannedGh} g/h)` : ''}.
          </p>
          <Chips label="How often" value={every === null ? null : String(every)} options={EVERY.map((m) => [String(m), `${m} min`] as const)}
            onChange={(v) => setEvery(v === null ? null : Number(v))} />
          <Chips label="Your gut" value={gi} options={GI} onChange={(v) => setGi(v as FuelEntry['gi'])} />
          <Chips label="Energy late on" value={energy} options={ENERGY} onChange={(v) => setEnergy(v as FuelEntry['energy'])} />
          <textarea value={note} onChange={(e) => setNote(e.target.value.slice(0, 300))} rows={2} aria-label="Fueling note"
            placeholder="Products, flavours, what you'd change (optional)"
            className="min-h-11 w-full rounded-md border border-input bg-transparent px-3 py-2 text-body text-(--text) placeholder:text-(--text-muted) focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" />
          {err && <p className="m-0 text-meta text-(--danger)" role="alert">{err}</p>}
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" className="h-11 flex-1 text-body" loading={busy} disabled={mins <= 0} onClick={() => void save()}>Save fueling</Button>
            <Button variant="ghost" className="h-11 px-3 text-body" onClick={() => setOpen(false)}>Cancel</Button>
            {entry && <Button variant="ghost" className="h-11 px-3 text-body text-(--danger)" onClick={() => void remove()}>Delete</Button>}
          </div>
        </div>
      )}

      {!open && learn && learn.lines.length > 0 && (
        <RabbitNote title="What rabbt's learned" compact>
          {learn.lines.slice(0, 3).map((l) => <p key={l} className="m-0 text-small text-(--text-secondary)"><RabbitInline text={l} /></p>)}
        </RabbitNote>
      )}
    </section>
  )
}

function Num({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-meta text-(--text-muted)">{label}</span>
      <input type="number" inputMode="numeric" min={0} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)}
        className="h-11 w-full rounded-md border border-input bg-transparent px-3 text-body tabular-nums text-(--text) placeholder:text-(--text-muted) focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" />
    </label>
  )
}

export function Chips<T extends string>({ label, value, options, onChange }: {
  label: string; value: T | null; options: readonly (readonly [T, string])[]; onChange: (v: T | null) => void
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-small text-(--text)">{label}</span>
      <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={label}>
        {options.map(([v, l]) => (
          <button key={v} type="button" role="radio" aria-checked={value === v} onClick={() => onChange(value === v ? null : v)}
            className={cn('plan-chip min-h-11', value === v && 'plan-chip--on')}>{l}</button>
        ))}
      </div>
    </div>
  )
}
