// Loading a whole plan: one "Add a plan" button opens AddPlan.tsx (upload a file, paste text
// or a Google link, build week by week in Rabbit, or start from a template). Every path ends
// in the editable review (PlanReview.tsx), then Apply, with undo for 7 days. Used by a coach on
// an athlete's Plan tab and by the athlete from their plan (same component).
import { useCallback, useEffect, useState } from 'react'
import { BookmarkPlus, CalendarRange, Check, Download, Plus, Undo2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { RabbitLoader } from '@/components/RabbitLoader'
import type { BuiltPlan, PlanApi } from '@/lib/plan'
import { addDays, importApi, type ImportApi, type ImportStatus } from '@/lib/planimport'
import { Card, Screen, inputCls } from './ui'
import { fmtDay } from './PlanParts'
import { AddPlanFlow } from './AddPlan'

type Who = 'coach' | 'athlete'
const short = (d: string) => fmtDay(d, { month: 'short', day: 'numeric' })

/** The coach's Plan tab for one athlete (or the athlete's own "load a plan" entry). */
export function PlanImportHub({ api, plans, who, athleteName, onOpenPlan, onChanged }: {
  api: ImportApi; plans: PlanApi; who: Who; athleteName: string
  onOpenPlan: () => void; onChanged?: () => void
}) {
  const [status, setStatus] = useState<ImportStatus | null>(null)
  const [plan, setPlan] = useState<BuiltPlan | null | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const load = useCallback(() => {
    setError(null)
    Promise.all([api.status(), plans.getPlan()]).then(([s, p]) => { setStatus(s); setPlan(p.plan) },
      (e) => setError((e as Error).message))
  }, [api, plans])
  useEffect(load, [load])
  const first = athleteName.split(' ')[0] || 'your athlete'

  if (error) return <ErrorState message={error} onRetry={load} />
  if (!status || plan === undefined) return <RabbitLoader className="py-16" label="Opening the plan" cycle={['Opening the plan…', 'Counting weeks…']} />

  const lastWeek = plan?.weeks[plan.weeks.length - 1]
  return (
    <>
      {status.undo && <UndoBanner api={api} status={status} who={who} onDone={() => { load(); onChanged?.() }} />}
      {plan ? (
        <Card className="px-4 py-3.5">
          <p className="text-[0.9412rem] font-medium text-(--text)">{plan.weeks.length} weeks · {short(plan.first_day)} – {lastWeek ? short(addDays(lastWeek.start, 6)) : ''}</p>
          <p className="mt-0.5 text-[0.7647rem] text-(--text-muted)">
            {plan.origin ? `Loaded by ${plan.origin.kind === 'coach' ? plan.origin.by_name : `${first} (from a file)`}` : 'Built in Rabbit'}
            {plan.current_week ? ` · week ${plan.current_week} now` : ''}
          </p>
          <Button variant="default" className="mt-3 h-11 w-full text-[0.8235rem]" onClick={onOpenPlan}>Open plan</Button>
        </Card>
      ) : (
        <div className="px-1">
          <p className="font-display text-[1.2941rem] leading-tight text-(--brand)">{who === 'coach' ? `Load ${first}'s plan` : 'Load your plan'}</p>
          <p className="mt-1 text-[0.7647rem] leading-snug text-(--text-muted)">A file, pasted text, a template or week by week. You'll see every week before anything changes, and you can undo for 7 days.</p>
        </div>
      )}
      {!status.can_edit ? (
        <p className="px-1 text-[0.7647rem] text-(--text-muted)">View only: {first} hasn't given you edit access to the plan.</p>
      ) : (
        <AddPlanButton hasPlan={!!plan} onClick={() => setOpen(true)} />
      )}
      {plan && status.can_edit && status.can_save_templates && <SaveAsTemplate api={api} />}
      {plan && (
        <div className="flex flex-wrap items-center gap-x-3 px-1 text-[0.7059rem] text-(--text-muted)">
          <span>Download the plan:</span>
          <a className="inline-flex min-h-11 items-center gap-1 font-medium text-(--accent)" href={api.exportUrl('csv')} download><Download className="size-3.5" /> CSV</a>
          <a className="inline-flex min-h-11 items-center gap-1 font-medium text-(--accent)" href={api.exportUrl('ics')} download><CalendarRange className="size-3.5" /> Calendar (.ics)</a>
        </div>
      )}
      {open && (
        <AddPlanFlow api={api} status={status} who={who} athleteName={first} hasPlan={!!plan}
          onClose={() => setOpen(false)} onApplied={() => { setOpen(false); load(); onChanged?.() }} />
      )}
    </>
  )
}

/** The one way in: a big "Add a plan" button. */
export function AddPlanButton({ hasPlan, onClick }: { hasPlan: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick}
      className="flex min-h-20 w-full items-center gap-3 rounded-2xl border border-(--accent) bg-(--accent-subtle) px-4 py-4 text-left shadow-sm active:opacity-80">
      <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-(--accent) text-(--on-fill)"><Plus className="size-6" /></span>
      <span className="min-w-0 flex-1">
        <span className="block text-[1.0588rem] font-semibold text-(--accent)">Add a plan</span>
        <span className="block text-[0.7059rem] leading-snug text-(--text-muted)">
          {hasPlan ? 'Replace it, add to it or fill empty days: a file, pasted text, a template or week by week.'
            : 'Upload a file, paste text, start from a template or build it week by week.'}
        </span>
      </span>
    </button>
  )
}

/** Coach: keep the athlete's current plan as "my template" (reuse it for other athletes). */
function SaveAsTemplate({ api }: { api: ImportApi }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  async function save() {
    setBusy(true); setError(null)
    try { const r = await api.saveMine(name.trim(), { from: 'plan' }); setDone(r.template.label); setOpen(false) } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  if (done) return <p className="flex items-center gap-1.5 px-1 text-[0.7647rem] text-(--accent)"><Check className="size-4" /> Saved “{done}” to your templates.</p>
  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className="flex min-h-11 items-center gap-1.5 self-start px-1 text-[0.7647rem] font-medium text-(--accent)">
        <BookmarkPlus className="size-4" /> Save this plan as my template
      </button>
    )
  }
  return (
    <Card className="flex flex-col gap-2 px-4 py-3">
      <p className="text-[0.7647rem] leading-snug text-(--text-muted)">Sessions from today on, kept as weeks 1, 2, 3… Use it for any athlete from any start date.</p>
      <input aria-label="Template name" className={inputCls} placeholder="Template name (e.g. 12-week half block)" maxLength={60} value={name} onChange={(e) => setName(e.target.value)} autoFocus />
      {error && <p className="text-[0.7059rem] text-(--danger)" role="alert">{error}</p>}
      <div className="flex gap-2">
        <Button variant="default" className="h-11 flex-1 text-[0.7647rem]" onClick={() => setOpen(false)}>Cancel</Button>
        <Button variant="primary" className="h-11 flex-1 text-[0.7647rem]" loading={busy} disabled={!name.trim()} onClick={() => void save()}>Save template</Button>
      </div>
    </Card>
  )
}

function UndoBanner({ api, status, who, onDone }: { api: ImportApi; status: ImportStatus; who: Who; onDone: () => void }) {
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const u = status.undo!
  const until = new Date(u.until * 1000).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })
  const what = u.restores === 'previous plan' ? 'puts the previous plan back' : 'removes this plan'
  async function run() {
    setBusy(true); setError(null)
    try { await api.undo(); onDone() } catch (e) { setError((e as Error).message) } finally { setBusy(false); setConfirm(false) }
  }
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-(--accent)/30 bg-(--accent-subtle) px-3.5 py-2.5">
      <div className="flex items-center gap-3">
        <Undo2 className="size-4 shrink-0 text-(--accent)" />
        <p className="min-w-0 flex-1 text-[0.7647rem] leading-snug text-(--text-secondary)">
          {who === 'coach' && u.by_name ? `${u.by_name} loaded this plan.` : 'This plan was loaded from outside the builder.'} Undo {what} (until {until}).
        </p>
        {!confirm && <Button variant="default" className="h-11 px-3 text-[0.7647rem]" onClick={() => setConfirm(true)}>Undo</Button>}
      </div>
      {confirm && (
        <div className="flex gap-2">
          <Button variant="default" className="h-11 flex-1 text-[0.7647rem]" onClick={() => setConfirm(false)}>Keep it</Button>
          <Button variant="destructive" className="h-11 flex-1 text-[0.7647rem]" loading={busy} onClick={() => void run()}>Undo the import</Button>
        </div>
      )}
      {error && <p className="text-[0.7059rem] text-(--danger)" role="alert">{error}</p>}
    </div>
  )
}

/** The athlete's own entry point (from the plan screen): Add plan -> review -> apply. */
export function OwnPlanImport({ api, status, hasPlan, onClose, onApplied }: {
  api: ImportApi; status: ImportStatus; hasPlan: boolean; onClose: () => void; onApplied: () => void
}) {
  return <AddPlanFlow api={api} status={status} who="athlete" athleteName="" hasPlan={hasPlan} onClose={onClose} onApplied={onApplied} />
}

/** "Add a plan" from anywhere (Plan tab with no plan yet): loads the status, then the flow. */
export function AddPlanLauncher({ onClose, onApplied }: { onClose: () => void; onApplied: () => void }) {
  const [api] = useState(() => importApi('/api'))
  const [status, setStatus] = useState<ImportStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { api.status().then(setStatus, (e) => setError((e as Error).message)) }, [api])
  if (error) return <Screen title="Add a plan" onClose={onClose}><ErrorState message={error} /></Screen>
  if (!status) return <Screen title="Add a plan" onClose={onClose}><RabbitLoader className="py-16" label="Opening" /></Screen>
  return <AddPlanFlow api={api} status={status} who="athlete" athleteName="" hasPlan={false} onClose={onClose} onApplied={onApplied} />
}
