// "Your plan" for a plan built in Rabbit: the season at a glance, week by week sessions you
// can edit, add or delete, and syncing the next few weeks to your Garmin calendar.
import { useCallback, useEffect, useState } from 'react'
import { CalendarDays, ChevronLeft, ChevronRight, MessageCircle, Plane, Plus, RefreshCw, Trash2, Undo2, Watch } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ConnectGarmin } from '@/components/ConnectGarmin'
import { Group, Icon, Row } from '@/components/settings/Grouped'
import { RabbitLogo } from '@/components/RabbitLogo'
import { cn } from '@/lib/utils'
import type { Me, Sport } from '@/lib/api'
import {
  deletePlan, planApi, rebuildPlan, removeFromGarmin, sportsFor, syncGarmin, type PlanApi,
  type BuiltPlan, type PlanSession, type SyncResult,
} from '@/lib/plan'
import { Card, Chip, ChipRow, Field, Screen } from './ui'
import { PhaseStrip, SessionLine, fmtDay, todayStr, weekPhaseLabel } from './PlanParts'
import { SessionSheet, type SessionDraft } from './SessionSheet'
import { SyncSummary } from './SetupWizard'
import { TravelSheet } from './TravelSheet'
import { AdjustCard } from './AdjustCard'
import { getAdjust, type Proposal } from '@/lib/adjust'
import { addTravel, getCalendar, removeTravel, type CalendarSummary } from '@/lib/calendar'

type Editing = { session: PlanSession | null; date: string }
const OWN = planApi()

export function PlanEditor({ me, goalTitle, onClose, onRebuild, onAsk, onChanged, onMeChanged, onOpenEvents, api = OWN, coachMode, readOnly, onMessage, messageLabel }: {
  me: Me
  goalTitle: string
  onClose: () => void
  onRebuild: () => void
  onAsk: (text: string) => void
  onChanged: () => void
  onMeChanged: () => void
  onOpenEvents: () => void
  api?: PlanApi
  coachMode?: boolean      // a coach viewing an athlete's plan: no Garmin, no plan actions
  readOnly?: boolean       // no edit permission
  onMessage?: (s: { id: string; title: string; date: string }) => void
  messageLabel?: string
}) {
  const [plan, setPlan] = useState<BuiltPlan | null | undefined>(undefined)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [closing, setClosing] = useState(false)
  const [weekIdx, setWeekIdx] = useState<number | null>(null)
  const [editing, setEditing] = useState<Editing | null>(null)
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
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const [note, setNote] = useState<string | null>(null)
  useEffect(() => {
    if (coachMode) return
    getAdjust().then(setProposal, () => {})
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

  const close = () => { setClosing(true); setTimeout(onClose, 200) }
  const closeSheet = () => { setSheetClosing(true); setTimeout(() => { setEditing(null); setSheetClosing(false) }, 200) }
  const applied = (p: BuiltPlan) => { setPlan(p); onChanged() }

  if (plan === undefined || plan === null) {
    return (
      <Screen title="Your plan" closing={closing} onClose={close}>
        {plan === undefined && !loadError ? (
          <div className="flex justify-center py-16" role="status" aria-label="Loading plan">
            <RabbitLogo size={56} thinking className="text-(--brand) opacity-60" />
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3 py-12 text-center">
            <p className="text-[0.8235rem] text-(--text-secondary)">{loadError ?? "There's no plan built in Rabbit for this goal yet."}</p>
            {!loadError && <Button variant="primary" className="h-11 px-6 text-[0.8235rem]" onClick={onRebuild}>Build my plan</Button>}
          </div>
        )}
      </Screen>
    )
  }

  const week = plan.weeks.find((w) => w.index === weekIdx) ?? plan.weeks[0]!
  const pos = plan.weeks.indexOf(week)
  const today = todayStr()
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
      close()
    } catch (e) { setSync((s) => ({ ...s, error: (e as Error).message })); setDeleting(false) }
  }

  async function saveSession(d: SessionDraft, changed: Partial<SessionDraft>) {
    if (!editing) return
    if (editing.session) {
      const r = await api.updateSession(editing.session.id, changed)
      applied(r.plan)
    } else {
      const r = await api.addSession({ date: d.date, sport: d.sport, kind: d.kind, minutes: d.minutes, title: d.title || undefined })
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

  const synced = plan.weeks.reduce((n, w) => n + w.days.reduce((m, d) => m + d.sessions.filter((s) => s.synced).length, 0), 0)

  return (
    <Screen title="Your plan" subtitle={`${goalTitle} · ${raceDay}`} closing={closing} onClose={close}>
      {/* Season */}
      <div className="px-1">
        <p className="font-display text-[1.4118rem] leading-tight text-(--brand)">
          {daysToRace > 0 ? `${daysToRace} day${daysToRace === 1 ? '' : 's'} to go` : daysToRace === 0 ? 'Race day!' : 'Race done'}
        </p>
        <p className="mt-1 text-[0.7647rem] text-(--text-muted)">
          {plan.weeks.length} weeks · about {plan.start_hours}h building to {plan.peak_hours}h a week
          {plan.current_week ? ` · you're in week ${plan.current_week}` : ''}
        </p>
      </div>
      {!coachMode && proposal && <AdjustCard p={proposal} onDone={(p, msg) => { if (p) applied(p); setProposal(null); setNote(msg) }} />}
      {note && <p className="px-1 text-[0.7647rem] text-(--accent)" role="status">{note}</p>}
      {!coachMode && suggestions.map((t) => (
        <div key={t.start} className="flex items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-2.5">
          <Plane className="size-4 shrink-0 text-(--accent)" />
          <p className="min-w-0 flex-1 text-[0.7647rem] leading-snug text-(--text-secondary)">
            On your calendar: <span className="text-(--text)">{t.title}</span>, {fmtDay(t.start, { month: 'short', day: 'numeric' })}{t.end !== t.start ? ` – ${fmtDay(t.end, { month: 'short', day: 'numeric' })}` : ''}
          </p>
          <Button variant="default" className="h-8 px-3 text-[0.7059rem]" onClick={() => setTravel({ start: t.start < today ? today : t.start, end: t.end, label: t.title.slice(0, 60) })}>Plan around it</Button>
        </div>
      ))}
      {!coachMode && (plan.events_changed || plan.race_changed) && (
        <div className="flex items-center gap-3 rounded-xl border border-(--accent)/30 bg-(--accent-subtle) px-3.5 py-2.5">
          <p className="min-w-0 flex-1 text-[0.7647rem] leading-snug text-(--accent)">
            {plan.race_changed ? 'Your race date or distance changed since this plan was built.' : 'Your events changed since this plan was built.'}
            {' '}Rebuild to fit {plan.race_changed ? 'it' : 'them'} in (session edits are replaced).</p>
          <Button variant="primary" className="h-8 px-3 text-[0.7059rem]" loading={rebuilding} onClick={() => void doRebuild()}>Rebuild</Button>
        </div>
      )}
      {plan.events.length > 0 && (
        <p className="-mb-2 px-1 text-[0.7059rem] text-(--text-muted)">
          Also in this plan: {plan.events.map((e) => `${e.name} (${fmtDay(e.date, { month: 'short', day: 'numeric' })}, ${e.priority === 'C' ? 'training race' : 'B race'})`).join(' · ')}
        </p>
      )}
      <Card className="p-4">
        <PhaseStrip plan={plan} selected={week.index} onSelect={setWeekIdx} />
      </Card>

      {/* Week */}
      <section className="flex flex-col gap-1.5">
        <div className="flex items-center gap-1 px-1">
          <button type="button" className="modal-close" aria-label="Previous week" disabled={pos <= 0}
            onClick={() => setWeekIdx(plan.weeks[pos - 1]!.index)}><ChevronLeft className="size-4" /></button>
          <div className="min-w-0 flex-1 text-center">
            <p className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">
              Week {week.index} of {plan.weeks.length} · {weekPhaseLabel(week)} · {week.hours}h
            </p>
            <p className="text-[0.7059rem] text-(--text-muted)">
              {fmtDay(week.days[0]!.date, { month: 'short', day: 'numeric' })} – {fmtDay(week.days[week.days.length - 1]!.date, { month: 'short', day: 'numeric' })}
              {week.index === plan.current_week && ' · this week'}
            </p>
          </div>
          <button type="button" className="modal-close" aria-label="Next week" disabled={pos >= plan.weeks.length - 1}
            onClick={() => setWeekIdx(plan.weeks[pos + 1]!.index)}><ChevronRight className="size-4" /></button>
        </div>
        <Card>
          {week.focus && <p className="border-b border-(--border) px-4 py-2.5 text-[0.7647rem] leading-snug text-(--text-secondary)">{week.focus}</p>}
          <div className="divide-y divide-(--border)">
            {week.days.map((d) => {
              const past = d.date < today
              const isToday = d.date === today
              const canAdd = !readOnly && !past && d.date <= plan.race_date && d.sessions.length < 4
              return (
                <div key={d.date} className={cn('flex gap-3 px-4 py-2', isToday && 'bg-(--accent-subtle)', past && 'opacity-60')}>
                  <span className="w-10 shrink-0 pt-2 text-center leading-tight">
                    <span className={cn('block text-[0.6471rem] font-semibold uppercase', isToday ? 'text-(--accent)' : 'text-(--text-muted)')}>
                      {fmtDay(d.date, { weekday: 'short' })}
                    </span>
                    <span className="block text-[0.7647rem] text-(--text-secondary)">{fmtDay(d.date, { day: 'numeric' })}</span>
                    {busyLabel(d.date) && <span className="mt-0.5 block text-[0.5294rem] leading-tight text-(--warning)">{busyLabel(d.date)}</span>}
                    {plan.trips.some((t) => t.start <= d.date && d.date <= t.end) && <Plane className="mx-auto mt-0.5 size-3 text-(--accent)" aria-label="Travel day" />}
                  </span>
                  <div className="min-w-0 flex-1">
                    {d.sessions.map((s) => (
                      <SessionLine key={s.id} s={s} onClick={s.sport === 'rest' && past ? undefined : () => setEditing({ session: s, date: d.date })} />
                    ))}
                    {!d.sessions.length && <p className="py-2 text-[0.7647rem] text-(--text-muted)">Rest</p>}
                  </div>
                  {canAdd && (
                    <button type="button" aria-label={`Add a session on ${fmtDay(d.date)}`}
                      onClick={() => setEditing({ session: null, date: d.date })}
                      className="mt-1.5 flex size-7 shrink-0 items-center justify-center rounded-full border border-dashed border-(--border-strong) text-(--text-muted) active:bg-(--bg-inset)">
                      <Plus className="size-3.5" />
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        </Card>
        <p className="px-4 text-[0.7647rem] leading-snug text-(--text-muted)">Tap a session to see the workout, change it or move it. Edited sessions stay as you set them.</p>
      </section>

      {!coachMode && <>
      {/* Garmin */}
      <Group label="Garmin calendar" footer={me.garmin.connected
        ? 'Rabbit adds upcoming sessions as structured workouts with your zones. Sync again after changes; edited and moved sessions get updated.'
        : undefined}>
        <Field label={me.garmin.connected ? (lastSync ? `Last synced ${lastSync.toLocaleDateString([], { month: 'short', day: 'numeric' })} · ${synced} on your calendar` : 'Not synced yet') : 'Connect Garmin'}>
          {me.garmin.connected ? (
            <div className="flex flex-col gap-2.5">
              <ChipRow>
                {[7, 14, 28].map((n) => <Chip key={n} selected={syncDays === n} onClick={() => setSyncDays(n)}>Next {n} days</Chip>)}
              </ChipRow>
              <div className="flex gap-2">
                <Button variant="primary" className="h-11 flex-1 gap-1.5 text-[0.8235rem]" loading={sync.busy === 'sync'}
                  disabled={sync.busy != null} onClick={() => void doSync()}>
                  <Watch className="size-4" /> Sync to Garmin
                </Button>
                {(synced > 0 || plan.pending_removals > 0) && (
                  <Button variant="default" className="h-11 px-4 text-[0.8235rem]" loading={sync.busy === 'remove'}
                    disabled={sync.busy != null} onClick={() => void doRemove()}>Remove</Button>
                )}
              </div>
              {plan.pending_removals > 0 && !sync.result && (
                <p className="text-[0.7059rem] text-(--text-muted)">{plan.pending_removals} old workout{plan.pending_removals === 1 ? '' : 's'} will be cleared from Garmin on the next sync.</p>
              )}
              {sync.result && <SyncSummary result={sync.result} />}
              {sync.removed != null && <p className="text-[0.7647rem] text-(--accent)">Removed {sync.removed} workout{sync.removed === 1 ? '' : 's'} from your Garmin calendar.</p>}
            </div>
          ) : me.garmin.can_connect ? (
            <ConnectGarmin cooldownUntil={me.garmin.cooldown_until} onConnected={onMeChanged} />
          ) : <p className="text-[0.7647rem] text-(--text-muted)">Garmin isn't available on this server.</p>}
        </Field>
      </Group>
      {sync.error && <p className="-mt-3 px-4 text-[0.7647rem] text-(--danger)" role="alert">{sync.error}</p>}

      {/* Plan actions */}
      <Group label="Plan">
        <Row icon={<Icon><MessageCircle /></Icon>} title="Ask Rabbit about my plan" subtitle="Questions, swaps, travel weeks"
          onClick={() => { close(); onAsk('About my plan: ') }} />
        <Row icon={<Icon><CalendarDays /></Icon>} title="Events" subtitle="Add B and C races; they go into the plan"
          onClick={onOpenEvents} />
        <Row icon={<Icon><Plane /></Icon>} title="Travel mode" subtitle="Days away: swap sessions for hotel gym, treadmill or runs"
          onClick={() => setTravel('new')} />
        {plan.trips.map((t) => (
          <Row key={t.id} title={`${t.label}`} subtitle={`${fmtDay(t.start, { month: 'short', day: 'numeric' })} – ${fmtDay(t.end, { month: 'short', day: 'numeric' })} · travel mode on`}
            trailing={<Button variant="ghost" className="h-8 gap-1 px-2 text-[0.7059rem]" onClick={() => void removeTravel(t.id).then((r) => applied(r.plan), (e) => setSync((x) => ({ ...x, error: (e as Error).message })))}><Undo2 className="size-3.5" /> Undo</Button>} />
        ))}
        <Row icon={<Icon><RefreshCw /></Icon>} title="Change race or answers" subtitle="Rebuilds the plan from the setup questions"
          onClick={onRebuild} />
        {confirmDelete ? (
          <div className="flex items-center gap-2 px-4 py-3">
            <span className="min-w-0 flex-1 text-[0.8235rem] text-(--text)">Delete this plan{synced ? ' and its Garmin workouts' : ''}?</span>
            <Button variant="default" className="h-9 px-3 text-[0.7647rem]" onClick={() => setConfirmDelete(false)}>Keep</Button>
            <Button variant="destructive" className="h-9 px-3 text-[0.7647rem]" loading={deleting} onClick={() => void doDelete()}>Delete</Button>
          </div>
        ) : (
          <Row icon={<Icon tone="danger"><Trash2 /></Icon>} title="Delete plan" danger onClick={() => setConfirmDelete(true)} />
        )}
      </Group>
      </>}

      {travel && (
        <TravelSheet initial={travel === 'new' ? undefined : travel} raceDate={plan.race_date} closing={travelClosing}
          onClose={closeTravel} onDismissed={() => { setTravel(null); setTravelClosing(false) }}
          onApply={async (b) => { applied((await addTravel(b)).plan) }} />
      )}
      {editing && (
        <SessionSheet key={editing.session?.id ?? `new-${editing.date}`}
          session={editing.session} date={editing.date} kinds={plan.kinds} sports={sports as Sport[]}
          raceDate={plan.race_date} closing={sheetClosing} onClose={closeSheet}
          onDismissed={() => { setEditing(null); setSheetClosing(false) }}
          onSave={saveSession}
          onDelete={editing.session && editing.session.kind !== 'race' ? async () => {
            const r = await api.deleteSession(editing.session!.id)
            applied(r.plan)
          } : undefined}
          readOnly={readOnly}
          onMessage={editing.session && onMessage ? () => {
            const s = editing.session!
            setEditing(null)
            onMessage({ id: s.id, title: s.title, date: editing.date })
          } : undefined}
          messageLabel={messageLabel}
          onAsk={editing.session && !coachMode ? () => {
            const s = editing.session!
            setEditing(null); close()
            onAsk(`About my ${s.title} on ${fmtDay(editing.date, { weekday: 'long', month: 'short', day: 'numeric' })}: `)
          } : undefined} />
      )}
    </Screen>
  )
}
