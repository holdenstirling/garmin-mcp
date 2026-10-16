// Gear garage: shoes, bikes and the rest, with mileage toward a retirement distance.
// Mileage comes from the server (workouts since each item was added, or Garmin's own
// total for imported gear); this screen lists, adds, edits, retires and imports.
import { useCallback, useEffect, useState } from 'react'
import { useDraft } from '@/lib/drafts'
import { saveDurably } from '@/lib/outbox'
import { SaveStatus } from '@/components/ui/SaveStatus'
import { DraftRestored, useUnsavedGuard } from '@/components/ui/UnsavedGuard'
import { Backpack, Bike, ChevronRight, CircleDot, Flag, Footprints, MessageCircle, Plus, RefreshCw, Trash2, Watch, Waves, Zap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { RabbitLoader } from '@/components/RabbitLoader'
import { EmptyRabbit } from '@/components/anim'
import { Card, Choice, Field, MultiChoice, Screen, areaCls, inputCls } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import {
  BIKE_TYPE_LABEL, DEFAULT_SPORT, KIND_GROUP, KIND_LABEL, KIND_ORDER, KM_PER_MI, SHOE_TYPE_LABEL, SPORT_LABEL,
  deleteGear, fmtDist, gearName, getGear, importGarminGear, retireGear,
  type BikeType, type GearCatalog, type GearFields, type GearItem, type GearKind, type GearList, type GearSport, type ShoeType,
} from '@/lib/gear'

const KIND_ICON: Record<GearKind, typeof Bike> = {
  shoes: Footprints, bike: Bike, wetsuit: Waves, watch: Watch, power_meter: Zap, helmet: CircleDot, other: Backpack,
}
const STATUS_LABEL = { soon: 'Retire soon', retire: 'Time to retire' } as const

export function GearScreen({ onClose, imperial, onAsk }: {
  onClose: () => void; imperial: boolean
  /** pre-fills Rabbit's composer ("Ask Rabbit" on an item) */
  onAsk?: (text: string) => void
}) {
  const [items, setItems] = useState<GearItem[] | null>(null)
  const [catalog, setCatalog] = useState<GearCatalog | null>(null)
  const [statsOk, setStatsOk] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [closing, setClosing] = useState(false)
  const [editing, setEditing] = useState<GearItem | 'new' | null>(null)
  const [showRetired, setShowRetired] = useState(false)
  const [importing, setImporting] = useState(false)

  const apply = useCallback((r: GearList) => { setItems(r.items); setStatsOk(r.stats_ok) }, [])
  const load = useCallback(() => {
    setError(null)
    getGear().then((r) => { apply(r); setCatalog(r) }, (e) => setError((e as Error).message))
  }, [apply])
  useEffect(load, [load])

  const close = () => { setClosing(true); setTimeout(onClose, 200) }
  async function runImport() {
    setImporting(true); setNote(null); setError(null)
    try {
      const r = await importGarminGear()
      apply(r)
      const n = r.imported
      setNote(!n || n.created + n.updated === 0 ? 'No gear found in Garmin Connect.'
        : `From Garmin: ${n.created} new, ${n.updated} updated.`)
    } catch (e) { setError((e as Error).message) }
    finally { setImporting(false) }
  }

  const active = (items ?? []).filter((g) => !g.retired)
  const retired = (items ?? []).filter((g) => g.retired)
  const attention = active.filter((g) => g.status !== 'ok').length
  const full = !!catalog && (items?.length ?? 0) >= catalog.max_items

  return (
    <>
      <Screen title="Gear garage"
        subtitle={items && items.length > 0 ? `${active.length} in use${attention ? ` · ${attention} need${attention === 1 ? 's' : ''} attention` : ''}` : 'Shoes, bikes and the rest'}
        closing={closing} onClose={close}
        footer={<>
          <Button variant="default" className="h-11 gap-1.5 px-3.5 text-[0.7647rem]" loading={importing}
            disabled={items === null} onClick={() => void runImport()}>
            <RefreshCw className="size-4" /> Import from Garmin
          </Button>
          <Button variant="primary" className="h-11 flex-1 gap-1.5 text-[0.8235rem]" disabled={items === null || full}
            onClick={() => setEditing('new')}>
            <Plus className="size-4" /> Add gear
          </Button>
        </>}>
        {items === null && !error ? (
          <RabbitLoader className="py-16" label="Loading gear" cycle={['Checking the gear closet…', 'Counting miles on your shoes…']} />
        ) : items === null ? (
          <ErrorState message={`Couldn't load your gear: ${error}`} onRetry={load} />
        ) : (
          <>
            {error && <p className="px-1 text-[0.7647rem] text-(--danger)" role="alert">{error}</p>}
            {note && <p className="rounded-xl border border-(--accent)/30 bg-(--accent-subtle) px-3.5 py-2.5 text-[0.7647rem] text-(--accent)">{note}</p>}
            {active.length === 0 && (
              <EmptyRabbit className="py-10" title="Your garage is empty"
                body="Add your shoes to track every mile and get a heads-up before they wear out." />
            )}
            {KIND_ORDER.map((k) => {
              const list = active.filter((g) => g.kind === k)
              if (!list.length) return null
              return (
                <section key={k} className="flex flex-col gap-2">
                  <h3 className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">{KIND_GROUP[k]}</h3>
                  {list.map((g) => <GearRow key={g.id} g={g} imperial={imperial} onClick={() => setEditing(g)} />)}
                </section>
              )
            })}
            {retired.length > 0 && (
              <section className="flex flex-col gap-2">
                <button type="button" onClick={() => setShowRetired((v) => !v)} aria-expanded={showRetired}
                  className="hit-44 flex items-center gap-1 px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">
                  Retired ({retired.length}) <ChevronRight className={cn('size-3.5 transition-transform', showRetired && 'rotate-90')} />
                </button>
                {showRetired && retired.map((g) => <GearRow key={g.id} g={g} imperial={imperial} onClick={() => setEditing(g)} />)}
              </section>
            )}
            {!statsOk && active.length > 0 && (
              <p className="px-1 text-[0.7059rem] leading-snug text-(--text-muted)">
                Workouts couldn't be read from Garmin just now, so distances may be behind.
              </p>
            )}
          </>
        )}
      </Screen>
      {editing && catalog && (
        <GearEditor item={editing === 'new' ? null : editing} catalog={catalog} imperial={imperial}
          onClose={() => setEditing(null)} onSaved={apply} onAsk={onAsk} />
      )}
    </>
  )
}

function GearRow({ g, imperial, onClick }: { g: GearItem; imperial: boolean; onClick: () => void }) {
  const Icon = KIND_ICON[g.kind] ?? Backpack
  const pct = g.pct_of_alert
  const warn = g.status !== 'ok' && !g.retired
  const meta = [g.size, g.shoe_type ? SHOE_TYPE_LABEL[g.shoe_type] : g.bike_type ? BIKE_TYPE_LABEL[g.bike_type] : '',
    g.default_for.length ? `Default for ${g.default_for.map((s) => SPORT_LABEL[s].toLowerCase()).join(', ')}` : '']
    .filter(Boolean).join(' · ')
  return (
    <button type="button" onClick={onClick}
      className={cn('flex w-full flex-col gap-2 rounded-xl border bg-(--bg-surface) px-3.5 py-3 text-left active:bg-(--bg-inset)',
        warn ? 'border-(--warning)/50' : 'border-(--border)', g.retired && 'opacity-70')}>
      <span className="flex w-full items-center gap-3">
        <span className={cn('flex size-10 shrink-0 items-center justify-center rounded-xl',
          warn ? 'bg-(--warning-subtle) text-(--warning-text)' : 'bg-(--accent-subtle) text-(--accent)')}>
          <Icon className="size-5" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[0.9412rem] font-medium text-(--text)">
            {gearName(g)}
            {g.nickname && gearName(g) !== g.nickname && <span className="font-normal text-(--text-muted)"> ({g.nickname})</span>}
          </span>
          {meta && <span className="block truncate text-[0.7059rem] text-(--text-muted)">{meta}</span>}
        </span>
        {warn ? (
          <span className="shrink-0 rounded-full bg-(--warning-subtle) px-2 py-0.5 font-mono text-[0.6471rem] font-semibold uppercase tracking-wider text-(--warning-text)">
            {STATUS_LABEL[g.status as 'soon' | 'retire']}
          </span>
        ) : <ChevronRight className="size-4 shrink-0 text-(--text-muted)" />}
      </span>
      <span className="flex w-full flex-col gap-1">
        {g.alert_km != null && pct != null && (
          <span className="block h-1.5 w-full overflow-hidden rounded-full bg-(--bg-elevated)"
            role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.min(100, pct)} aria-label="Distance toward retirement">
            <span className={cn('block h-full rounded-full transition-[width] duration-700',
              g.status === 'retire' ? 'bg-(--danger)' : g.status === 'soon' ? 'bg-(--warning)' : 'bg-(--accent)')}
              style={{ width: `${Math.max(2, Math.min(100, pct))}%` }} />
          </span>
        )}
        <span className="flex justify-between gap-2 text-[0.6471rem] text-(--text-muted)">
          <span>
            <b className="font-semibold text-(--text-secondary)">{fmtDist(g.total_km, imperial)}</b>
            {g.alert_km != null ? ` of ${fmtDist(g.alert_km, imperial)}` : ''}
          </span>
          <span>
            {g.activities} workout{g.activities === 1 ? '' : 's'}
            {g.last_used ? ` · last ${new Date(`${g.last_used}T12:00:00`).toLocaleDateString([], { month: 'short', day: 'numeric' })}` : ''}
          </span>
        </span>
      </span>
    </button>
  )
}

type Form = {
  kind: GearKind; brand: string; model: string; nickname: string; size: string
  bike_type: BikeType | null; shoe_type: ShoeType | null; default_for: GearSport[]
  start: string; alert: string; notes: string
}

function GearEditor({ item, catalog, imperial, onClose, onSaved, onAsk }: {
  item: GearItem | null; catalog: GearCatalog; imperial: boolean
  onClose: () => void; onSaved: (r: GearList) => void; onAsk?: (text: string) => void
}) {
  const unit = imperial ? 'mi' : 'km'
  const toUnit = (km: number) => String(Math.round((imperial ? km / KM_PER_MI : km) * 10) / 10)
  const defaultAlert = (k: GearKind) => {
    const km = catalog.default_alert_km[k]
    if (km == null) return ''
    return imperial ? String(Math.round(km / KM_PER_MI / 50) * 50) : String(km)
  }
  // Kept as a draft per item (or the new one) on this device until saved or discarded.
  const [f, setF, draft] = useDraft<Form>(`gear.${item?.id ?? 'new'}`, () => item ? {
    kind: item.kind, brand: item.brand, model: item.model, nickname: item.nickname, size: item.size,
    bike_type: item.bike_type, shoe_type: item.shoe_type, default_for: item.default_for,
    start: item.start_km ? toUnit(item.start_km) : '', alert: item.alert_km != null ? toUnit(item.alert_km) : '', notes: item.notes,
  } : {
    kind: 'shoes', brand: '', model: '', nickname: '', size: '', bike_type: null, shoe_type: null,
    default_for: ['run'], start: '', alert: defaultAlert('shoes'), notes: '',
  }, { label: item ? 'gear changes' : 'new gear' })
  const guard = useUnsavedGuard(draft.dirty, draft.discard)
  const [queued, setQueued] = useState(false)
  const [closing, setClosing] = useState(false)
  const [busy, setBusy] = useState<'save' | 'retire' | 'delete' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const set = (p: Partial<Form>) => setF((x) => ({ ...x, ...p }))
  const close = () => { setClosing(true); setTimeout(onClose, 200) }
  const setKind = (k: GearKind) => {
    const sport = DEFAULT_SPORT[k]
    set({ kind: k, alert: defaultAlert(k), default_for: sport ? [sport] : [], size: '', bike_type: null, shoe_type: null })
  }

  async function run(kind: 'save' | 'retire' | 'delete', fn: () => Promise<GearList>) {
    setBusy(kind); setError(null); setQueued(false)
    try { const r = await fn(); draft.clear(); onSaved(r); close() }
    catch (e) { setError((e as Error).message) }
    finally { setBusy(null); setQueued(false) }
  }

  function dist(text: string, label: string, allowEmpty: boolean): number | null {
    const t = text.trim().replace(',', '.')
    if (t === '') return allowEmpty ? null : 0
    const n = Number(t)
    if (!Number.isFinite(n) || n < 0) throw new Error(`${label} must be a number.`)
    return Math.round((imperial ? n * KM_PER_MI : n) * 10) / 10
  }

  function fieldsOrNull(): GearFields | null {
    try {
      return {
        brand: f.brand, model: f.model, nickname: f.nickname, size: f.size, notes: f.notes,
        bike_type: f.kind === 'bike' ? f.bike_type : null, shoe_type: f.kind === 'shoes' ? f.shoe_type : null,
        default_for: f.default_for,
        start_km: dist(f.start, 'Starting distance', false) ?? 0,
        alert_km: dist(f.alert, 'Retirement distance', true),
      }
    } catch (e) { setError((e as Error).message); return null }
  }

  function save() {
    const fields = fieldsOrNull()
    if (!fields) return
    // Durable (lib/outbox): offline / 5xx -> "Not saved yet — we'll retry", sent once.
    void run('save', () => saveDurably<GearList>(item
      ? { method: 'PATCH', path: `/api/gear/${encodeURIComponent(item.id)}`, body: fields, label: 'gear', coalesce: `gear.${item.id}` }
      : { method: 'POST', path: '/api/gear', body: { ...fields, kind: f.kind }, label: 'gear' }, () => setQueued(true)))
  }

  const brands = catalog.brands[f.kind] ?? []
  const sizes = catalog.sizes[f.kind] ?? []
  const named = !!(f.brand.trim() || f.model.trim() || f.nickname.trim())
  const sportOptions = catalog.sports.map((s) => [s, SPORT_LABEL[s]] as const)

  return (
    <Screen title={item ? gearName(item) : 'Add gear'} subtitle={item?.retired ? 'Retired' : item ? KIND_LABEL[item.kind] : undefined}
      closing={closing} onClose={guard.wrap(close)} onBack={guard.wrap(close)}
      footer={<Button variant="primary" className="h-11 flex-1 text-[0.8235rem]" loading={busy === 'save'} disabled={!named}
        onClick={save}>{item ? 'Save changes' : 'Add to garage'}</Button>}>
      {guard.dialog}
      {draft.restored && <DraftRestored onDiscard={draft.discard} />}
      {queued && <SaveStatus state="queued" className="px-1" />}
      {!item && (
        <Card>
          <Field label="What is it?">
            <Choice value={f.kind} options={KIND_ORDER.map((k) => [k, KIND_LABEL[k]] as const)} onChange={(k) => k && setKind(k)} />
          </Field>
        </Card>
      )}
      <Card>
        <Field label="Brand">
          <input className={inputCls} value={f.brand} maxLength={60} list={`gear-brands-${f.kind}`} autoComplete="off"
            placeholder={f.kind === 'bike' ? 'e.g. Canyon' : f.kind === 'shoes' ? 'e.g. Hoka' : ''} onChange={(e) => set({ brand: e.target.value })} />
          {brands.length > 0 && <datalist id={`gear-brands-${f.kind}`}>{brands.map((b) => <option key={b} value={b} />)}</datalist>}
        </Field>
        <Field label="Model" className="border-t border-(--border)">
          <input className={inputCls} value={f.model} maxLength={60} autoComplete="off"
            placeholder={f.kind === 'bike' ? 'e.g. Aeroad CF SLX' : f.kind === 'shoes' ? 'e.g. Clifton 9' : ''} onChange={(e) => set({ model: e.target.value })} />
        </Field>
        <Field label="Nickname" className="border-t border-(--border)" hint="Optional. Handy when you have two of the same.">
          <input className={inputCls} value={f.nickname} maxLength={60} autoComplete="off" placeholder="e.g. Race day pair"
            onChange={(e) => set({ nickname: e.target.value })} />
        </Field>
        {f.kind !== 'watch' && f.kind !== 'power_meter' && (
          <Field label="Size" className="border-t border-(--border)">
            <input className={inputCls} value={f.size} maxLength={20} list={`gear-sizes-${f.kind}`} autoComplete="off"
              placeholder={f.kind === 'shoes' ? 'e.g. US 10.5' : f.kind === 'bike' ? 'e.g. 56 cm' : 'e.g. M'} onChange={(e) => set({ size: e.target.value })} />
            {sizes.length > 0 && <datalist id={`gear-sizes-${f.kind}`}>{sizes.map((s) => <option key={s} value={s} />)}</datalist>}
          </Field>
        )}
        {f.kind === 'shoes' && (
          <Field label="Type" className="border-t border-(--border)">
            <Choice allowNone value={f.shoe_type} options={catalog.shoe_types.map((t) => [t, SHOE_TYPE_LABEL[t]] as const)}
              onChange={(t) => set({ shoe_type: t })} />
          </Field>
        )}
        {f.kind === 'bike' && (
          <Field label="Type" className="border-t border-(--border)">
            <Choice allowNone value={f.bike_type} options={catalog.bike_types.map((t) => [t, BIKE_TYPE_LABEL[t]] as const)}
              onChange={(t) => set({ bike_type: t })} />
          </Field>
        )}
      </Card>
      <Card>
        <Field label="Default for" hint="New workouts in these sports count toward this item. You can only have one default per sport.">
          <MultiChoice value={f.default_for} options={sportOptions} onChange={(v) => set({ default_for: v })} />
        </Field>
        <div className="grid grid-cols-2 border-t border-(--border)">
          <Field label={`Already on it (${unit})`}>
            <input className={inputCls} inputMode="decimal" value={f.start} placeholder="0" onChange={(e) => set({ start: e.target.value })} />
          </Field>
          <Field label={`Retire at (${unit})`} className="border-l border-(--border)">
            <input className={inputCls} inputMode="decimal" value={f.alert} placeholder="No alert" onChange={(e) => set({ alert: e.target.value })} />
          </Field>
        </div>
        {f.kind === 'shoes' && (
          <p className="px-4 pb-3.5 text-[0.7059rem] leading-snug text-(--text-muted)">
            Most running shoes last {imperial ? '300 to 500 mi' : '500 to 800 km'}. You'll get a heads-up at 80%.
          </p>
        )}
      </Card>
      <Card>
        <Field label="Notes">
          <textarea className={areaCls} value={f.notes} maxLength={300} placeholder="Where you bought it, what it's best for, fit notes"
            onChange={(e) => set({ notes: e.target.value })} />
        </Field>
      </Card>
      {item && (
        <p className="px-1 text-[0.7059rem] text-(--text-muted)">
          {fmtDist(item.total_km, imperial)} over {item.activities} workout{item.activities === 1 ? '' : 's'}
          {item.source === 'garmin' ? ' (from Garmin Connect)' : ''} · added {new Date(`${item.added}T12:00:00`).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })}
        </p>
      )}
      {item && onAsk && (
        <Button variant="default" className="h-11 gap-1.5 text-[0.8235rem]"
          onClick={() => onAsk(`My ${gearName(item)} has ${fmtDist(item.total_km, imperial)}. `
            + 'When should I replace it and what should I consider next?')}>
          <MessageCircle className="size-4" /> Ask Rabbit
        </Button>
      )}
      {item && (
        <Button variant="default" className="h-11 gap-1.5 text-[0.8235rem]" loading={busy === 'retire'}
          onClick={() => void run('retire', () => retireGear(item.id, !item.retired))}>
          <Flag className="size-4" /> {item.retired ? 'Bring it back' : 'Retire it'}
        </Button>
      )}
      {item && (confirmDelete ? (
        <div className="flex items-center gap-2 rounded-xl border border-(--border) bg-(--bg-surface) px-4 py-3">
          <span className="min-w-0 flex-1 text-[0.8235rem]">Delete {gearName(item)}? Retiring keeps its history.</span>
          <Button variant="default" className="h-9 px-3 text-[0.7647rem]" onClick={() => setConfirmDelete(false)}>Keep</Button>
          <Button variant="destructive" className="h-9 px-3 text-[0.7647rem]" loading={busy === 'delete'}
            onClick={() => void run('delete', () => deleteGear(item.id))}>Delete</Button>
        </div>
      ) : (
        <Button variant="ghost" className="h-10 gap-1.5 text-[0.7647rem] text-(--danger)" onClick={() => setConfirmDelete(true)}>
          <Trash2 className="size-4" /> Delete
        </Button>
      ))}
      {error && <p className="px-1 text-[0.7647rem] text-(--danger)" role="alert">{error}</p>}
    </Screen>
  )
}
