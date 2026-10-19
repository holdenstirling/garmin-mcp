// "Your plan" for a plan built in Rabbit: the season at a glance, week by week sessions you
// can edit, add or delete, and syncing the next few weeks to your Garmin calendar.
import { useCallback, useEffect, useState } from 'react'
import { CalendarDays, FileUp, MessageCircle, Plane, RefreshCw, Thermometer, Trash2, Undo2, Watch } from 'lucide-react'
import { SICK_CHANGED_EVENT, openSick } from '@/lib/sick'
import { SickBanner } from './SickHost'
import { Button } from '@/components/ui/button'
import { GarminEmpty } from '@/components/garmin/GarminEmpty'
import { Group, Icon, Row } from '@/components/settings/Grouped'
import { Section } from '@/components/ui/section'
import { BlocksEntry } from '@/components/blocks/BlocksEntry'
import { RabbitLoader } from '@/components/RabbitLoader'
import type { Me, Sport } from '@/lib/api'
import {
  deletePlan, planApi, rebuildPlan, removeFromGarmin, sportsFor, syncGarmin, type PlanApi,
  type BuiltPlan, type PlanSession, type SyncResult,
} from '@/lib/plan'
import { Field, Screen } from './ui'
import { fmtDay, planToday, sessionMinutes } from './PlanParts'
import { PlanCalendar, paceText, type MoveTarget } from './PlanCalendar'
import { PLAN_CHANGED_EVENT, getCalendar as getPlanCal, type CalView } from '@/lib/plancal'
import { listEvents, type RaceEvent } from '@/lib/events'
import { DayEvents, eventsOn } from './DayEvents'
import { PACES_CHANGED_EVENT } from '@/lib/paces'
import { fmtDist, fmtDuration } from '@/lib/format'
import { SessionSheet, type SessionDraft } from './SessionSheet'
import { SyncSummary } from './SetupWizard'
import { OPEN_TRAVEL_EVENT, takeTravelRequest } from '@/lib/plantools'
import { TravelSheet } from './TravelSheet'
import { AdjustCard } from './AdjustCard'
import { getAdjust, type Proposal } from '@/lib/adjust'
import { addTravel, getCalendar, removeTravel, type CalendarSummary } from '@/lib/calendar'
import { athleteChat } from '@/lib/coach'
import { OwnPlanImport } from './PlanImport'
import { importApi, type ImportStatus } from '@/lib/planimport'
import { TPCalendarList, TPDayItems, TPPlanBar, TPWorkoutSheet, useTrainingPeaks } from './TPItems'
import { AdjustPlanSheet, RaceSwitcher, UndoBar, WeekCheckCard } from './PlanFlow'
import { PLAN_RELOAD_EVENT } from '@/lib/planflow'
import { useCalInsights } from '@/lib/calinsights'
import { CalendarInsightsCard, DayLoadChip } from './CalendarInsights'
import type { AthleteFull } from '@/lib/plan'

type Editing = { session: PlanSession | null; date: string }
const OWN = planApi()
const OWN_IMPORT = importApi('/api')

export function PlanEditor({ me, goalTitle, onClose, onRebuild, onAsk, onChanged, onMeChanged, onOpenEvents, api = OWN, coachMode, readOnly, onMessage, messageLabel, onOpenWorkout, addRequest, onAddHandled, onOpenEvent }: {
  me: Me
  goalTitle: string
  /** none when it is the Plan tab page (no X) */
  onClose?: () => void
  onRebuild: () => void
  onAsk: (text: string) => void
  onChanged: () => void
  /** kept for callers; Garmin now connects in the app's connect popup, which refreshes /me */
  onMeChanged?: () => void
  onOpenEvents: () => void
  api?: PlanApi
  coachMode?: boolean      // a coach viewing an athlete's plan: no Garmin, no plan actions
  readOnly?: boolean       // no edit permission
  onMessage?: (s: { id: string; title: string; date: string }) => void
  messageLabel?: string
  /** today's session: open the pre-workout screen */
  onOpenWorkout?: (sessionId: string) => void
  /** Schedule "+ Add" -> A workout: open the session editor on that day (once per n) */
  addRequest?: { date: string; n: number } | null
  onAddHandled?: () => void
  /** an event shown on a calendar day was tapped */
  onOpenEvent?: (id: string) => void
}) {
  const [plan, setPlan] = useState<BuiltPlan | null | undefined>(undefined)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [closing, setClosing] = useState(false)
  const [weekIdx, setWeekIdx] = useState<number | null>(null)
  const [editing, setEditing] = useState<Editing | null>(null)
  // Events on calendar days (lib/events), so a day shows the race / group run / trip it holds.
  const [events, setEvents] = useState<RaceEvent[]>([])
  useEffect(() => {
    if (coachMode) return
    let live = true
    const load = () => { listEvents().then((r) => { if (live) setEvents(r.events) }, () => { /* the calendar works without */ }) }
    load()
    window.addEventListener(PLAN_CHANGED_EVENT, load)
    return () => { live = false; window.removeEventListener(PLAN_CHANGED_EVENT, load) }
  }, [coachMode])
  // Schedule "+ Add" -> A workout: the session editor on that day, once the plan is here.
  useEffect(() => {
    if (!addRequest || !plan || readOnly || coachMode) return
    const first = plan.first_day || plan.start
    const d = addRequest.date < first ? first
      : addRequest.date > plan.race_date ? plan.race_date : addRequest.date
    setEditing({ session: null, date: d })
    onAddHandled?.()
  }, [addRequest?.n, !!plan]) // eslint-disable-line react-hooks/exhaustive-deps
  const [sheetClosing, setSheetClosing] = useState(false)
  const [syncDays, setSyncDays] = useState(14)
  const [sync, setSync] = useState<{ busy: 'sync' | 'remove' | null; result: SyncResult | null; removed: number | null; error: string | null }>(
    { busy: null, result: null, removed: null, error: null })
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [rebuilding, setRebuilding] = useState(false)
  const [cal, setCal] = useState<CalendarSummary | null>(null)
  const [travel, setTravel] = useState<{ start: string; end: string; label: string } | 'new' | null>(null)
  const [travelClosing, setTravelClosing] = useState(false)
  // Travel mode from "+ Add", Adjust my plan or anywhere else (lib/plantools openTravel).
  useEffect(() => {
    if (coachMode || readOnly) return
    if (takeTravelRequest()) setTravel('new')
    const on = () => { takeTravelRequest(); setTravel('new') }
    window.addEventListener(OPEN_TRAVEL_EVENT, on)
    return () => window.removeEventListener(OPEN_TRAVEL_EVENT, on)
  }, [coachMode, readOnly])
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const [note, setNote] = useState<string | null>(null)
  // Plan calendar data (athlete only: status, distance, pace, notes, mileage) and the Move sheet.
  const [planCal, setPlanCal] = useState<CalView | null>(null)
  const [moving, setMoving] = useState<MoveTarget | null>(null)
  const imperial = coachMode ? false : me.athlete?.units !== 'metric'
  const loadCal = useCallback(() => { if (!coachMode) getPlanCal().then((r) => setPlanCal(r.cal), () => {}) }, [coachMode])
  // Sessions with a coach reply the athlete hasn't read yet (athlete side only).
  const [unread, setUnread] = useState<string[]>([])
  const canMessage = !!onMessage
  const tp = useTrainingPeaks(!coachMode)  // TrainingPeaks workouts on this calendar (TPItems.tsx)
  // Loading a plan from a file (athlete side) and the last import's summary.
  const [imp, setImp] = useState<{ status: ImportStatus; open: boolean } | null>(null)
  const loadImport = (open: boolean) => OWN_IMPORT.status().then((st) => setImp({ status: st, open }), (e) => setLoadError((e as Error).message))
  useEffect(() => { if (!coachMode && plan?.origin) void OWN_IMPORT.status().then((st) => setImp((x) => ({ status: st, open: x?.open ?? false })), () => {}) }, [coachMode, plan?.origin])
  useEffect(() => {
    if (coachMode || !canMessage) return
    athleteChat.list().then((r) => setUnread(r.threads.filter((t) => t.session_id && t.last?.from === 'coach' &&
      t.read?.athlete !== t.last.id).map((t) => t.session_id!)), () => {})
  }, [coachMode, canMessage])
  useEffect(() => {
    if (coachMode) return
    const fetchAdjust = () => { getAdjust().then(setProposal, () => {}) }
    fetchAdjust()
    // Sick mode on/off changes what Rabbit suggests (nothing while sick or easing back).
    window.addEventListener(SICK_CHANGED_EVENT, fetchAdjust)
    return () => window.removeEventListener(SICK_CHANGED_EVENT, fetchAdjust)
  }, [coachMode])
  useEffect(() => {
    if (coachMode || !me.calendar?.connected) return
    getCalendar(56).then(setCal, () => {})
  }, [coachMode, me.calendar?.connected])

  const load = useCallback(() => {
    api.getPlan().then((r) => {
      setPlan(r.plan)
      if (r.plan?.garmin.window) setSyncDays(r.plan.garmin.window)
      setWeekIdx((cur) => cur ?? r.plan?.current_week ?? r.plan?.weeks[0]?.index ?? null)
    }, (e) => setLoadError((e as Error).message))
  }, [api])
  useEffect(load, [load])
  useEffect(loadCal, [loadCal])
  // New training paces accepted (Day view, Profile, a moment): targets on every session change.
  useEffect(() => {
    const on = () => { load(); loadCal() }
    window.addEventListener(PACES_CHANGED_EVENT, on)
    window.addEventListener(PLAN_RELOAD_EVENT, on)
    return () => { window.removeEventListener(PACES_CHANGED_EVENT, on); window.removeEventListener(PLAN_RELOAD_EVENT, on) }
  }, [load, loadCal])
  // Adjust my plan (levers), its Undo, and the weekly check-in on demand.
  const [adjusting, setAdjusting] = useState(false)
  const [undo, setUndo] = useState<string | null>(null)
  const [checkIn, setCheckIn] = useState(false)

  const close = onClose && (() => { setClosing(true); setTimeout(onClose, 200) })
  const closeSheet = () => { setSheetClosing(true); setTimeout(() => { setEditing(null); setSheetClosing(false) }, 200) }
  const applied = (p: BuiltPlan) => { setPlan(p); loadCal(); onChanged() }
  // Calendar insights (calinsights.py): the week vs Google Calendar, with one-tap fixes.
  const calIns = useCalInsights(plan)  // re-checked after every plan change
  const calDay = (d: string) => calIns.data?.days.find((x) => x.date === d)

  if (plan === undefined || plan === null) {
    return (
      <Screen title="Your plan" closing={closing} onClose={close}>
        {plan === undefined && !loadError ? (
          <RabbitLoader className="py-16" label="Loading plan" cycle={['Opening your plan…', 'Lining up your weeks…', 'Checking your watch…']} />
        ) : (
          <div className="flex flex-col items-center gap-3 py-12 text-center">
            <p className="text-body text-(--text-secondary)">{loadError ?? (coachMode ? "Your athlete hasn't built a plan in rabbt yet." : "There's no plan built in rabbt for this goal yet.")}</p>
            {!loadError && !coachMode && <Button variant="primary" className="h-11 px-6 text-body" onClick={onRebuild}>Build my plan</Button>}
            {!loadError && !coachMode && <Button variant="ghost" className="h-11 px-4 text-small" onClick={() => void loadImport(true)}>I have a plan</Button>}
          </div>
        )}
        {plan === null && <TPCalendarList tp={tp} today={planToday(plan)} imperial={imperial} />}
        <TPWorkoutSheet tp={tp} today={planToday(plan)} imperial={imperial} />
        {imp?.open && <OwnPlanImport api={OWN_IMPORT} status={imp.status} hasPlan={false} onClose={() => setImp(null)} onApplied={() => { setImp(null); load(); onChanged() }} />}
      </Screen>
    )
  }

  const week = plan.weeks.find((w) => w.index === weekIdx) ?? plan.weeks[0]!
  const today = planToday(plan)
  const sports = sportsFor(plan.distance)
  const raceDay = fmtDay(plan.race_date, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
  const daysToRace = Math.round((new Date(`${plan.race_date}T12:00:00`).getTime() - new Date(`${today}T12:00:00`).getTime()) / 86_400_000)
  const lastSync = plan.garmin.synced_at ? new Date(plan.garmin.synced_at * 1000) : null

  async function doSync() {
    setSync((s) => ({ ...s, busy: 'sync', error: null, removed: null }))
    try {
      const r = await syncGarmin(syncDays)
      setPlan(r.plan)
      setSync((s) => ({ ...s, busy: null, result: r.result }))
    } catch (e) { setSync((s) => ({ ...s, busy: null, error: (e as Error).message })) }
  }
  async function doRemove() {
    setSync((s) => ({ ...s, busy: 'remove', error: null, result: null }))
    try {
      const r = await removeFromGarmin()
      setPlan(r.plan)
      setSync((s) => ({ ...s, busy: null, removed: r.result.removed }))
    } catch (e) { setSync((s) => ({ ...s, busy: null, error: (e as Error).message })) }
  }
  async function doRebuild() {
    setRebuilding(true)
    try { applied((await rebuildPlan()).plan) }
    catch (e) { setSync((s) => ({ ...s, error: (e as Error).message })) }
    finally { setRebuilding(false) }
  }
  async function doDelete() {
    setDeleting(true)
    try {
      await deletePlan()
      onChanged()
      close?.()
    } catch (e) { setSync((s) => ({ ...s, error: (e as Error).message })); setDeleting(false) }
  }

  async function saveSession(d: SessionDraft, changed: Partial<SessionDraft>) {
    if (!editing) return
    if (editing.session) {
      const r = await api.updateSession(editing.session.id, changed)
      applied(r.plan)
    } else {
      const r = await api.addSession({ date: d.date, sport: d.sport, kind: d.kind, minutes: d.minutes, title: d.title || undefined, time: d.time || undefined })
      applied(r.plan)
    }
    // Follow a session moved into another week.
    const target = plan?.weeks.find((x) => x.days.some((day) => day.date === d.date))
    if (target && target.index !== week.index) setWeekIdx(target.index)
  }

  const closeTravel = () => { setTravelClosing(true); setTimeout(() => { setTravel(null); setTravelClosing(false) }, 200) }
  const coveredBy = (t: { start: string; end: string }) => plan.trips.some((x) => x.start <= t.end && x.end >= t.start)
  const suggestions = (cal?.travel ?? []).filter((t) => t.end >= today && !coveredBy(t)).slice(0, 2)
  const busyLabel = (d: string) => {
    const m = cal?.busy?.[d] ?? 0
    return m >= 60 ? `${Math.round(m / 60)}h busy` : m >= 30 ? `${m}m busy` : ''
  }

  const sessionMeta = (s: PlanSession) => {
    const c = planCal?.sessions[s.id]
    const dist = c ? Object.entries(c.km).filter(([, v]) => (v ?? 0) > 0).map(([sp, v]) => fmtDist(v!, imperial, sp)).join(' + ') : ''
    const mins = sessionMinutes(s)
    const pace = c?.pace ? `${paceText(c.pace.fast, imperial)}–${paceText(c.pace.slow, imperial)}/${imperial ? 'mi' : 'km'}` : ''
    const size = [dist, mins ? fmtDuration(mins) : ''].filter(Boolean).join(' · ')
    return [size, pace ? `Pace ${pace}` : ''].filter(Boolean).join('\n')
  }
  const canMove = (s: PlanSession, date: string) => {
    const st = planCal?.sessions[s.id]?.status
    return !coachMode && !readOnly && !!planCal && s.sport !== 'rest' && s.kind !== 'race' &&
      st !== 'done' && st !== 'skipped' && (date >= today || st === 'missed')
  }

  const synced = plan.weeks.reduce((n, w) => n + w.days.reduce((m, d) => m + d.sessions.filter((s) => s.synced).length, 0), 0)

  return (
    <Screen title="Your plan" subtitle={`${goalTitle} · ${raceDay}`} closing={closing} onClose={close}>
      {/* Which race the plan trains for (switch: each race keeps its plan) + Adjust my plan */}
      {coachMode ? (
        <div className="px-1">
          <p className="text-body text-(--text-secondary)">
            <span className="font-semibold text-(--brand)">{daysToRace > 0 ? `${daysToRace} day${daysToRace === 1 ? '' : 's'} to go` : daysToRace === 0 ? 'Race day!' : 'Race done'}</span>
            {plan.current_week ? ` · week ${plan.current_week} of ${plan.weeks.length}` : ` · ${plan.weeks.length} weeks`}
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <RaceSwitcher title={goalTitle} date={plan.race_date}
            sub={[daysToRace > 0 ? `${daysToRace} day${daysToRace === 1 ? '' : 's'} to go` : daysToRace === 0 ? 'Race day!' : 'Race done',
              plan.current_week ? `Week ${plan.current_week} of ${plan.weeks.length}` : `${plan.weeks.length} weeks`]}
            onSwitched={(p) => { if (p) { setPlan(p); setWeekIdx(p.current_week ?? p.weeks[0]?.index ?? null); loadCal() } onChanged(); onMeChanged?.() }}
            onAddRace={onOpenEvents} onBuild={onRebuild} onAdjust={readOnly ? undefined : () => setAdjusting(true)} />
          {undo && <UndoBar id={undo} onUndone={(p) => { setUndo(null); applied(p) }} onDone={() => setUndo(null)} />}
          {!readOnly && <SickBanner />}
          {!readOnly && <WeekCheckCard onApplied={(p) => applied(p)} />}
        </div>
      )}
      {plan.origin && (
        <div className="px-1">
          <p className="mt-1 flex flex-wrap items-center gap-x-2 text-small text-(--text-secondary)">
            {plan.origin.kind === 'coach' ? `Loaded by ${plan.origin.by_name}` : plan.origin.kind === 'block' ? `Built for ${plan.origin.name ?? 'your training block'}` : `Loaded from your file (${plan.origin.source})`} on {new Date(plan.origin.at * 1000).toLocaleDateString([], { month: 'short', day: 'numeric' })}
            {imp?.status.last && imp.status.last.at === plan.origin.at && ` · +${imp.status.last.added} new, ${imp.status.last.changed} changed, ${imp.status.last.removed} removed`}
            {!coachMode && imp?.status.undo && <Button variant="ghost" className="h-11 gap-1 px-2 text-meta" onClick={() => void OWN_IMPORT.undo().then(() => { setImp(null); load(); onChanged() }, (e) => setSync((x) => ({ ...x, error: (e as Error).message })))}><Undo2 className="size-4" /> Undo</Button>}
          </p>
        </div>
      )}
      {!coachMode && proposal && <AdjustCard p={proposal} onDone={(p, msg) => { if (p) applied(p); setProposal(null); setNote(msg) }} />}
      {note && <p className="px-1 text-small text-(--accent)" role="status">{note}</p>}
      {!coachMode && !readOnly && (
        <CalendarInsightsCard data={calIns.data} onReload={calIns.reload}
          onApplied={(p) => applied(p)} onAdjust={() => setAdjusting(true)}
          onTravel={(t) => setTravel({ start: t.start < today ? today : t.start, end: t.end, label: t.label.slice(0, 60) })} />
      )}
      {!coachMode && !calIns.data?.connected && suggestions.map((t) => (
        <div key={t.start} className="flex items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-2.5">
          <Plane className="size-5 shrink-0 text-(--accent)" />
          <p className="min-w-0 flex-1 text-small leading-snug text-(--text-secondary)">
            On your calendar: <span className="text-(--text)">{t.title}</span>, {fmtDay(t.start, { month: 'short', day: 'numeric' })}{t.end !== t.start ? ` – ${fmtDay(t.end, { month: 'short', day: 'numeric' })}` : ''}
          </p>
          <Button variant="default" className="h-8 px-3 text-meta" onClick={() => setTravel({ start: t.start < today ? today : t.start, end: t.end, label: t.title.slice(0, 60) })}>Plan around it</Button>
        </div>
      ))}
      {!coachMode && (plan.events_changed || plan.race_changed) && (
        <div className="flex items-center gap-3 rounded-xl border border-(--accent)/30 bg-(--accent-subtle) px-3.5 py-2.5">
          <p className="min-w-0 flex-1 text-small leading-snug text-(--accent)">
            {plan.race_changed ? 'Your race date or distance changed since this plan was built.' : 'Your events changed since this plan was built.'}
            {' '}Rebuild to fit {plan.race_changed ? 'it' : 'them'} in (session edits are replaced).</p>
          <Button variant="primary" className="h-8 px-3 text-meta" loading={rebuilding} onClick={() => void doRebuild()}>Rebuild</Button>
        </div>
      )}

      <TPPlanBar tp={tp} onToast={setNote} />
      {/* Week / month calendar (plancal.py): drag or Move sessions, fixes, mileage */}
      <PlanCalendar plan={plan} cal={planCal} imperial={imperial} today={today} week={week} onWeek={setWeekIdx}
        onAdjust={!coachMode && !readOnly ? () => setAdjusting(true) : undefined}
        editable={!coachMode && !readOnly} unread={unread} busyLabel={busyLabel}
        onOpen={(s, date) => setEditing({ session: s, date })}
        onAdd={readOnly ? undefined : (date) => setEditing({ session: null, date })}
        onResult={(r) => { setPlan(r.plan); setPlanCal(r.cal); onChanged() }}
        moving={moving} onMoving={setMoving}
        hidden={tp.hidden} dayExtra={(d) => {
          const tpItems = tp.itemsOn(d).length ? <TPDayItems tp={tp} date={d} imperial={imperial} /> : null
          const evs = eventsOn(events, d)
          const load = coachMode ? null : <DayLoadChip day={calDay(d)} />
          const hasLoad = !coachMode && !!calDay(d) && (calDay(d)!.travel || calDay(d)!.load === 'heavy' || calDay(d)!.load === 'packed')
          return tpItems || evs.length || hasLoad ? <>{hasLoad && load}{evs.length > 0 && <DayEvents events={evs} onOpen={onOpenEvent ?? (() => onOpenEvents())} />}{tpItems}</> : null
        }}
        onStart={onOpenWorkout && !coachMode ? (s) => onOpenWorkout(s.id) : undefined}
        onAsk={coachMode ? undefined : (s, date) => { close?.(); onAsk(`About my ${s.title} on ${fmtDay(date, { weekday: 'long', month: 'short', day: 'numeric' })}: `) }} />

      {/* The season (phases, hours by week, events in the plan) is the calendar's "Plan overview" sheet. */}

      {!coachMode && <>
      {/* Garmin */}
      <Section title="Send to your watch" description={me.garmin.connected
        ? 'Upcoming workouts go to your Garmin calendar with steps and targets. Moved or edited workouts update on the next sync.'
        : 'Connect Garmin to get each workout on your watch.'}>
      <Group>
        <Field label={me.garmin.connected ? (lastSync ? `Last synced ${lastSync.toLocaleDateString([], { month: 'short', day: 'numeric' })} · ${synced} on your calendar` : 'Not synced yet') : 'Connect Garmin'}>
          {me.garmin.connected ? (
            <div className="flex flex-col gap-2.5">
              <div className="flex gap-2">
                <select aria-label="How far ahead" value={syncDays} onChange={(e) => setSyncDays(Number(e.target.value))}
                  className="h-11 shrink-0 rounded-md border border-input bg-transparent px-2 text-body text-(--text)">
                  {[7, 14, 28].map((n) => <option key={n} value={n}>Next {n} days</option>)}
                </select>
                <Button variant="default" className="h-11 flex-1 gap-1.5 text-body font-semibold text-(--accent)" loading={sync.busy === 'sync'}
                  disabled={sync.busy != null} onClick={() => void doSync()}>
                  <Watch className="size-5" /> Sync
                </Button>
                {(synced > 0 || plan.pending_removals > 0) && (
                  <Button variant="default" className="h-11 px-4 text-body" loading={sync.busy === 'remove'}
                    disabled={sync.busy != null} onClick={() => void doRemove()}>Remove</Button>
                )}
              </div>
              {sync.busy === 'sync' && <RabbitLoader inline className="text-small" label="Sending to your watch…" />}
              {plan.pending_removals > 0 && !sync.result && (
                <p className="text-meta text-(--text-muted)">{plan.pending_removals} old workout{plan.pending_removals === 1 ? '' : 's'} will be cleared from Garmin on the next sync.</p>
              )}
              {sync.result && <SyncSummary result={sync.result} />}
              {sync.removed != null && <p className="text-small text-(--accent)">Removed {sync.removed} workout{sync.removed === 1 ? '' : 's'} from your Garmin calendar.</p>}
            </div>
          ) : me.garmin.can_connect ? (
            <GarminEmpty what="workout" compact />
          ) : <p className="text-small text-(--text-muted)">Garmin isn't available on this server.</p>}
        </Field>
      </Group>
      {sync.error && <p className="px-1 text-small text-(--danger)" role="alert">{sync.error}</p>}
      </Section>

      <BlocksEntry compact />

      {/* Plan actions */}
      <Section title="Plan tools" description="Ask about it, plan around trips or sick days, or start over.">
      <Group>
        <Row icon={<Icon><MessageCircle /></Icon>} title="Ask rabbt about my plan" subtitle="Questions, swaps, travel weeks"
          onClick={() => { close?.(); onAsk('About my plan: ') }} />
        <Row icon={<Icon><CalendarDays /></Icon>} title="Events" subtitle="Add B and C races, group sessions and trips; they go into the plan"
          onClick={onOpenEvents} />
        <Row icon={<Icon><Plane /></Icon>} title="Travel mode" subtitle="Days away: swap sessions for hotel gym, treadmill or runs"
          onClick={() => setTravel('new')} />
        {!readOnly && (
          <Row icon={<Icon><Thermometer /></Icon>} title="I'm sick" subtitle={plan.sick?.active ? `Sick mode on · day ${plan.sick.day}` : 'Rest or short easy days, then an easy return'}
            onClick={openSick} />
        )}
        {plan.trips.map((t) => (
          <Row key={t.id} title={`${t.label}`} subtitle={`${fmtDay(t.start, { month: 'short', day: 'numeric' })} – ${fmtDay(t.end, { month: 'short', day: 'numeric' })} · travel mode on`}
            trailing={<Button variant="ghost" className="h-8 gap-1 px-2 text-meta" onClick={() => void removeTravel(t.id).then((r) => applied(r.plan), (e) => setSync((x) => ({ ...x, error: (e as Error).message })))}><Undo2 className="size-4" /> Undo</Button>} />
        ))}
        <Row icon={<Icon><FileUp /></Icon>} title="Add a plan" subtitle="A file, pasted text, Zwift workouts or a template"
          onClick={() => void loadImport(true)} />
        <Row icon={<Icon><RefreshCw /></Icon>} title="Change race or answers" subtitle="Rebuilds the plan from the setup questions"
          onClick={onRebuild} />
        {confirmDelete ? (
          <div className="flex items-center gap-2 px-4 py-3">
            <span className="min-w-0 flex-1 text-body text-(--text)">Delete this plan{synced ? ' and its Garmin workouts' : ''}?</span>
            <Button variant="default" className="h-9 px-3 text-small" onClick={() => setConfirmDelete(false)}>Keep</Button>
            <Button variant="destructive" className="h-9 px-3 text-small" loading={deleting} onClick={() => void doDelete()}>Delete</Button>
          </div>
        ) : (
          <Row icon={<Icon tone="danger"><Trash2 /></Icon>} title="Delete plan" danger onClick={() => setConfirmDelete(true)} />
        )}
      </Group>
      </Section>
      </>}

      {imp?.open && <OwnPlanImport api={OWN_IMPORT} status={imp.status} hasPlan onClose={() => setImp((x) => x && { ...x, open: false })} onApplied={() => { setImp(null); load(); onChanged() }} />}
      {travel && (
        <TravelSheet initial={travel === 'new' ? undefined : travel} raceDate={plan.race_date} today={today} closing={travelClosing}
          onClose={closeTravel} onDismissed={() => { setTravel(null); setTravelClosing(false) }}
          onApply={async (b) => { applied((await addTravel(b)).plan) }} />
      )}
      {editing && (
        <SessionSheet key={editing.session?.id ?? `new-${editing.date}`}
          session={editing.session} date={editing.date} kinds={plan.kinds} sports={sports as Sport[]}
          raceDate={plan.race_date} today={today} closing={sheetClosing} onClose={closeSheet}
          onDismissed={() => { setEditing(null); setSheetClosing(false) }}
          onSave={saveSession}
          onDelete={editing.session && editing.session.kind !== 'race' ? async () => {
            const r = await api.deleteSession(editing.session!.id)
            applied(r.plan)
          } : undefined}
          readOnly={readOnly}
          note={editing.session ? planCal?.sessions[editing.session.id]?.note : undefined}
          meta={editing.session ? sessionMeta(editing.session) : undefined}
          onMove={editing.session && canMove(editing.session, editing.date) ? () => {
            const t = { session: editing.session!, date: editing.date }
            setEditing(null)
            setMoving(t)
          } : undefined}
          checkIn={!coachMode && !!editing.session && editing.date <= today}
          onOpenWorkout={editing.session && onOpenWorkout && !coachMode ? () => {
            const id = editing.session!.id
            setEditing(null)
            onOpenWorkout(id)
          } : undefined}
          onMessage={editing.session && onMessage ? () => {
            const s = editing.session!
            setEditing(null)
            onMessage({ id: s.id, title: s.title, date: editing.date })
          } : undefined}
          messageLabel={editing.session && unread.includes(editing.session.id) ? 'New reply from your coach' : messageLabel}
          onAsk={editing.session && !coachMode ? () => {
            const s = editing.session!
            setEditing(null); close?.()
            onAsk(`About my ${s.title} on ${fmtDay(editing.date, { weekday: 'long', month: 'short', day: 'numeric' })}: `)
          } : undefined} />
      )}
      <TPWorkoutSheet tp={tp} today={today} imperial={imperial} onToast={setNote} />
      {adjusting && <AdjustPlanSheet athlete={me.athlete as Partial<AthleteFull>} onClose={() => setAdjusting(false)}
        onApplied={(p, id) => { applied(p); setUndo(id); setWeekIdx(p.current_week ?? p.weeks[0]?.index ?? null) }}
        onCheckIn={() => setCheckIn(true)} />}
      {checkIn && <WeekCheckCard force onApplied={(p) => applied(p)} onClose={() => setCheckIn(false)} />}
    </Screen>
  )
}
