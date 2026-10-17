// The event form (Events screen and the setup wizard's race step): kind (race, group
// activity, trip, challenge, life event, other) first, then type, name with a web lookup,
// distance, date, where, how important, goal, course and notes. Race-only fields are hidden
// for other kinds; group activities, trips and life events get their own few fields.
import { useState } from 'react'
import { DurationInput } from '@/components/ui/DurationInput'
import { expectForDistance } from '@/lib/duration'
import { CalendarDays, ExternalLink, Flag, Globe, PartyPopper, Search, Tent, Trophy, Users } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, Choice, Field, NumberStepper, OptionCard, areaCls, inputCls } from '@/components/plan/ui'
import { M_PER_FT } from '@/lib/plan'
import {
  COURSE_PROFILES, DISTANCE_LABEL, EVENT_KINDS, INFO_LABEL, KIND_HINT, TYPE_DISTANCES, WEEKDAYS, kindOf, lookupEvent,
  type EventFields, type EventInfo, type EventKind, type EventType, type Recurring, type Weekday,
} from '@/lib/events'
import { cn } from '@/lib/utils'
import { SPORT_TYPE, TYPE_SPORT, sportOf } from '@/lib/sports'
import { SportPicker } from './SportPicker'

const todayIso = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export const KIND_ICON: Record<EventKind, typeof Flag> = {
  race: Flag, group_activity: Users, trip: Tent, challenge: Trophy, milestone: PartyPopper, other: CalendarDays,
}

/** Sensible starting fields when the athlete picks a kind for a new event. */
export function kindDefaults(kind: EventKind, isFirst: boolean): EventFields {
  switch (kind) {
    case 'race': return { kind, type: 'triathlon', distance: '70.3', priority: isFirst ? 'A' : 'B', goal_type: 'finish' }
    case 'group_activity': return { kind, type: 'cycling', distance: '', duration_min: 60, intensity: 'moderate', priority: 'C' }
    case 'challenge': return { kind, type: 'mountaineering', distance: '', priority: 'C', goal_type: 'finish' }
    default: return { kind, type: 'other', distance: '', priority: 'C' }
  }
}

/** Big chips with icons: the first thing the event form asks. */
export function KindPicker({ value, onChange }: { value: EventKind | null; onChange: (k: EventKind) => void }) {
  return (
    <Card>
      <Field label="What is it?" hint={value ? KIND_HINT[value] : 'Races, group workouts, trips and big life days all shape your plan.'}>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Kind of event">
          {EVENT_KINDS.map(([k, label]) => {
            const Icon = KIND_ICON[k]
            const on = value === k
            return (
              <button key={k} type="button" role="radio" aria-checked={on} onClick={() => onChange(k)}
                className={cn('flex min-h-16 items-center gap-2.5 rounded-xl border px-3 py-2.5 text-left text-[0.8235rem] font-medium transition-colors',
                  on ? 'border-(--accent) bg-(--accent-subtle) text-(--accent)' : 'border-(--border) bg-(--bg-surface) text-(--text) active:bg-(--bg-inset)')}>
                <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-lg', on ? 'bg-(--accent) text-(--on-fill)' : 'bg-(--accent-subtle) text-(--accent)')}>
                  <Icon className="size-4.5" />
                </span>
                {label}
              </button>
            )
          })}
        </div>
      </Field>
    </Card>
  )
}

/** Fields only some kinds need: weekly repeat, time, length and effort (group activities),
 * end date (trips, life events), who with and where. */
export function EventKindFields({ value, onChange }: { value: EventFields; onChange: (p: EventFields) => void }) {
  const kind = kindOf(value)
  if (kind === 'race' || kind === 'challenge') return null
  const group = kind === 'group_activity'
  const multi = kind === 'trip' || kind === 'milestone'
  return (
    <Card>
      {multi && (
        <Field label="Last day" hint={kind === 'trip' ? 'Rabbit keeps those days short and easy.' : 'Optional. Rabbit plans rest days around it.'}>
          <input type="date" className={inputCls} value={value.end_date ?? ''} min={value.date || undefined}
            onChange={(e) => onChange({ end_date: e.target.value || null })} />
        </Field>
      )}
      {(group || kind === 'other') && (
        <RepeatFields date={value.date} value={value.recurring ?? null} onChange={(r) => onChange({ recurring: r })}
          hint={group ? 'Leagues, weekly group rides, Tuesday volleyball: Rabbit puts each date on your schedule.' : undefined} />
      )}
      {(group || kind === 'other') && (
        <>
          <Field label="Start time" className="border-t border-(--border)">
            <input type="time" className={inputCls} value={value.time ?? ''} onChange={(e) => onChange({ time: e.target.value || null })} />
          </Field>
          <Field label="How long" className="border-t border-(--border)" hint={kind === 'other' ? 'Add a length and Rabbit counts it as a workout.' : undefined}>
            <NumberStepper label="how long" value={value.duration_min ?? null} min={10} max={600} step={15} suffix="min"
              onChange={(v) => onChange({ duration_min: v })} />
          </Field>
          <Field label="In your training" className="border-t border-(--border)"
            hint={value.in_plan === false ? 'It stays on your calendar; your workouts that day don’t change.'
              : 'Each date counts as a workout in your plan, in place of that day’s workout of the same sport.'}>
            <Choice value={value.in_plan === false ? 'no' : 'yes'} onChange={(v) => onChange({ in_plan: v === 'no' ? false : null })}
              options={[['yes', 'Count as a workout'], ['no', 'Calendar only']]} />
          </Field>
          {value.in_plan !== false && (
            <Field label="Effort" className="border-t border-(--border)">
              <Choice value={value.intensity ?? 'moderate'} onChange={(v) => onChange({ intensity: v ?? 'moderate' })}
                options={[['easy', 'Easy'], ['moderate', 'Moderate'], ['hard', 'Hard']]} />
            </Field>
          )}
        </>
      )}
      {kind !== 'milestone' && (
        <>
          <Field label="With" className={cn((group || multi || kind === 'other') && 'border-t border-(--border)')}>
            <input className={inputCls} value={value.with ?? ''} maxLength={80} placeholder={group ? 'e.g. Golden Cyclery, Tuesday crew' : 'Who’s coming'}
              onChange={(e) => onChange({ with: e.target.value })} />
          </Field>
          <Field label="Meeting spot" className="border-t border-(--border)">
            <input className={inputCls} value={value.at ?? ''} maxLength={80} placeholder={group ? 'e.g. Baker Park courts, the shop' : 'Trailhead, hut, town'}
              onChange={(e) => onChange({ at: e.target.value })} />
          </Field>
          <Field label="Neighborhood" className="border-t border-(--border)" hint="Optional. A public place or area, never a home address.">
            <input className={inputCls} value={value.neighborhood ?? ''} maxLength={80} placeholder="e.g. Baker, Denver"
              onChange={(e) => onChange({ neighborhood: e.target.value })} />
          </Field>
        </>
      )}
    </Card>
  )
}

type RepeatMode = 'none' | 'weekly' | 'biweekly' | 'monthly'
const ORD: [string, string][] = [['1', '1st'], ['2', '2nd'], ['3', '3rd'], ['4', '4th'], ['-1', 'Last']]
const DAY_LONG: Record<Weekday, string> = { mon: 'Monday', tue: 'Tuesday', wed: 'Wednesday', thu: 'Thursday', fri: 'Friday', sat: 'Saturday', sun: 'Sunday' }
const weekdayOf = (d?: string | null): Weekday => {
  const n = d ? new Date(`${d}T12:00:00`).getDay() : 2
  return (['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'] as Weekday[])[Number.isNaN(n) ? 2 : n]!
}
const setposOf = (d?: string | null): 1 | 2 | 3 | 4 | -1 => {
  const day = d ? new Date(`${d}T12:00:00`).getDate() : 1
  const n = Math.floor((day - 1) / 7) + 1
  return n >= 5 ? -1 : (n as 1 | 2 | 3 | 4)
}
export function repeatMode(r: Recurring | null | undefined): RepeatMode {
  if (!r) return 'none'
  if (r.freq === 'monthly') return 'monthly'
  return r.interval === 2 ? 'biweekly' : 'weekly'
}
/** "Every Tuesday and Thursday until Mar 30" (the same words the server uses, for the form). */
export function repeatSummary(r: Recurring): string {
  const days = (r.weekdays?.length ? r.weekdays : r.weekday ? [r.weekday] : []).map((d) => DAY_LONG[d])
  const list = days.length <= 1 ? days[0] ?? '' : `${days.slice(0, -1).join(', ')} and ${days[days.length - 1]}`
  const head = r.freq === 'monthly' ? `Monthly on the ${(ORD.find(([v]) => Number(v) === (r.setpos ?? 1))?.[1] ?? '1st').toLowerCase()} ${days[0] ?? ''}`
    : r.interval === 2 ? `Every 2 weeks on ${list}` : `Every ${list}`
  const end = r.until ? ` until ${new Date(`${r.until}T12:00:00`).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })}`
    : r.count ? `, ${r.count} times` : ''
  return head + end
}

/** How an event repeats: once, weekly (one or more weekdays), every 2 weeks, or monthly on the
 * nth weekday; ending never, on a date, or after a number of times. */
export function RepeatFields({ date, value, onChange, hint }: {
  date?: string | null; value: Recurring | null; onChange: (r: Recurring | null) => void; hint?: string
}) {
  const mode = repeatMode(value)
  const days: Weekday[] = value?.weekdays?.length ? value.weekdays : value?.weekday ? [value.weekday] : [weekdayOf(date)]
  const base = (m: RepeatMode): Recurring | null => {
    const keep = { until: value?.until ?? null, count: value?.count ?? null, except: value?.except ?? [] }
    if (m === 'none') return null
    if (m === 'monthly') return { freq: 'monthly', interval: 1, weekdays: [days[0] ?? weekdayOf(date)], setpos: value?.setpos ?? setposOf(date), ...keep }
    return { freq: 'weekly', interval: m === 'biweekly' ? 2 : 1, weekdays: days, ...keep }
  }
  const ends: 'never' | 'on' | 'after' = value?.until ? 'on' : value?.count ? 'after' : 'never'
  const toggleDay = (d: Weekday) => {
    if (!value) return
    const next = days.includes(d) ? days.filter((x) => x !== d) : [...days, d]
    if (!next.length) return  // at least one day
    onChange({ ...value, weekdays: next, weekday: undefined })
  }
  return (
    <Field label="Repeats" hint={hint}>
      <div className="flex flex-col gap-3">
        <Choice value={mode} onChange={(m) => onChange(base(m ?? 'none'))}
          options={[['none', 'Once'], ['weekly', 'Weekly'], ['biweekly', 'Every 2 weeks'], ['monthly', 'Monthly']]} />
        {value && mode !== 'monthly' && (
          <div className="flex flex-col gap-1.5">
            <span className="text-[0.7059rem] text-(--text-muted)">On</span>
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="Days it repeats on">
              {WEEKDAYS.map(([d, l]) => (
                <button key={d} type="button" aria-pressed={days.includes(d)} aria-label={DAY_LONG[d]} onClick={() => toggleDay(d)}
                  className={cn('flex size-11 items-center justify-center rounded-full border text-[0.7647rem] font-medium',
                    days.includes(d) ? 'border-(--accent) bg-(--accent) text-(--on-fill)' : 'border-(--border) text-(--text)')}>
                  {l.slice(0, 2)}
                </button>
              ))}
            </div>
          </div>
        )}
        {value && mode === 'monthly' && (
          <div className="flex flex-col gap-1.5">
            <span className="text-[0.7059rem] text-(--text-muted)">Which week</span>
            <Choice value={String(value.setpos ?? 1)} onChange={(v) => v && onChange({ ...value, setpos: Number(v) as Recurring['setpos'] })} options={ORD} />
            <span className="text-[0.7059rem] text-(--text-muted)">Day</span>
            <Choice value={days[0]!} onChange={(v) => v && onChange({ ...value, weekdays: [v], weekday: undefined })} options={WEEKDAYS} />
          </div>
        )}
        {value && (
          <div className="flex flex-col gap-1.5">
            <span className="text-[0.7059rem] text-(--text-muted)">Ends</span>
            <Choice value={ends} onChange={(e) => onChange({ ...value,
              until: e === 'on' ? (value.until ?? date ?? todayIso()) : null, count: e === 'after' ? (value.count ?? 10) : null })}
              options={[['never', 'Never'], ['on', 'On a date'], ['after', 'After some dates']]} />
            {ends === 'on' && (
              <input type="date" aria-label="Last date" className={inputCls} value={value.until ?? ''} min={date || undefined}
                onChange={(e) => onChange({ ...value, until: e.target.value || null })} />
            )}
            {ends === 'after' && (
              <NumberStepper label="how many times" value={value.count ?? 10} min={1} max={200} step={1} suffix="times"
                onChange={(v) => onChange({ ...value, count: v ?? 10 })} />
            )}
          </div>
        )}
        {value && <p className="text-[0.7647rem] font-medium text-(--accent)" aria-live="polite">{repeatSummary(value)}</p>}
      </div>
    </Field>
  )
}

/** Type, name + lookup, distance, date, location, website. */
export function EventBasics({ value, onChange, eventId, allowPast }: {
  value: EventFields; onChange: (p: EventFields) => void; eventId?: string; allowPast?: boolean
}) {
  const [busy, setBusy] = useState(false)
  const [found, setFound] = useState<EventInfo | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const type = (value.type ?? 'other') as EventType
  const kind = kindOf(value)
  const raceLike = kind === 'race' || kind === 'challenge'
  const dists = raceLike ? TYPE_DISTANCES[type] : []
  const canLookUp = raceLike || kind === 'trip'

  async function lookup() {
    setBusy(true); setMsg(null); setFound(null)
    try {
      const r = await lookupEvent({ name: value.name ?? '', type, date: value.date || undefined,
        location: value.location || undefined, event_id: eventId })
      setFound(r.info)
      if (eventId) onChange({ info: r.info })
    } catch (e) { setMsg((e as Error).message) }
    finally { setBusy(false) }
  }

  function apply(i: EventInfo) {
    const p: EventFields = { info: i }
    if (i.suggested_type) { p.type = i.suggested_type; if (!value.activity) p.activity = TYPE_SPORT[i.suggested_type] }
    const t = i.suggested_type ?? type
    if (i.suggested_distance && TYPE_DISTANCES[t].includes(i.suggested_distance)) p.distance = i.suggested_distance
    if (i.date && (allowPast || i.date >= todayIso())) p.date = i.date
    if (i.location) p.location = i.location.slice(0, 120)
    if (i.website) p.url = i.website.slice(0, 300)
    if (i.terrain && !value.course) p.course = i.terrain.slice(0, 300)
    if (i.suggested_course_profile && !value.course_profile) p.course_profile = i.suggested_course_profile
    if (i.suggested_elevation_m != null && value.elevation_m == null) p.elevation_m = i.suggested_elevation_m
    onChange(p)
    setFound(null)
    setMsg('Details filled in. Check them before saving.')
  }

  return (
    <>
      <Card>
        {kind !== 'milestone' && (
          <Field label={kind === 'race' ? 'Sport' : 'What sport'}>
            <SportPicker value={sportOf(value)} other={value.activity_other ?? ''}
              onOther={(name) => onChange({ activity_other: name })}
              onChange={(id) => {
                const t = SPORT_TYPE[id]
                onChange({ activity: id, type: t, activity_other: id === 'other' ? value.activity_other ?? '' : '',
                  distance: !raceLike ? '' : TYPE_DISTANCES[t].includes(value.distance ?? '') ? value.distance
                    : TYPE_DISTANCES[t].length === 1 ? TYPE_DISTANCES[t][0] : '' })
              }} />
          </Field>
        )}
        <Field label="Name" className={cn(kind !== 'milestone' && 'border-t border-(--border)')}
          hint={canLookUp ? 'Type the name, then look it up to fill in the date, location and details from the web.' : undefined}>
          <div className="flex gap-2">
            <input className={inputCls} value={value.name ?? ''} maxLength={120} placeholder={NAME_HINT[kind]}
              onChange={(e) => onChange({ name: e.target.value })} />
            {canLookUp && (
              <Button variant="default" className="h-10 shrink-0 gap-1.5 px-3 text-[0.7647rem]" loading={busy}
                disabled={(value.name ?? '').trim().length < 3} onClick={() => void lookup()}>
                <Search className="size-3.5" /> Look up
              </Button>
            )}
          </div>
          {busy && <span className="text-[0.7059rem] text-(--text-muted)">Searching the web. This can take 20 seconds or so.</span>}
          {msg && <span className={cn('text-[0.7059rem]', msg.startsWith('Details') ? 'text-(--accent)' : 'text-(--danger)')}>{msg}</span>}
        </Field>
        {found && (
          <div className="border-t border-(--border) px-4 py-3">
            <InfoBlock info={found} />
            <div className="mt-3 flex gap-2">
              <Button variant="primary" className="h-9 flex-1 text-[0.7647rem]" onClick={() => apply(found)}>Use these details</Button>
              <Button variant="default" className="h-9 px-3 text-[0.7647rem]" onClick={() => setFound(null)}>Dismiss</Button>
            </div>
          </div>
        )}
        {dists.length > 1 && (
          <Field label="Distance" className="border-t border-(--border)">
            <Choice value={value.distance ?? null} options={dists.map((d) => [d, DISTANCE_LABEL[d] ?? d] as [string, string])}
              onChange={(v) => onChange({ distance: v ?? '' })} />
          </Field>
        )}
        <Field label={kind === 'trip' || kind === 'milestone' ? 'First day' : value.recurring ? 'First date' : 'Date'} className="border-t border-(--border)">
          <input type="date" className={inputCls} value={value.date ?? ''} min={allowPast ? undefined : todayIso()}
            onChange={(e) => onChange({ date: e.target.value })} />
        </Field>
        <Field label="Where" className="border-t border-(--border)">
          <input className={inputCls} value={value.location ?? ''} maxLength={120} placeholder="City, state"
            onChange={(e) => onChange({ location: e.target.value })} />
        </Field>
        {kind !== 'milestone' && (
          <Field label="Website" className="border-t border-(--border)">
            <input className={inputCls} type="url" inputMode="url" value={value.url ?? ''} maxLength={300} placeholder="https://"
              onChange={(e) => onChange({ url: e.target.value.trim() })} />
          </Field>
        )}
      </Card>
    </>
  )
}

/** Who can find the event: just you (the default) or people near you (Local, search). */
export function EventVisibility({ value, onChange }: { value: EventFields; onChange: (p: EventFields) => void }) {
  const pub = value.visibility === 'public'
  return (
    <section aria-label="Who can see it" className="flex flex-col gap-2">
      <h3 className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Who can see it</h3>
      <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Who can see it">
        <OptionCard selected={!pub} title="Just me" description="Private: on your calendar and in your plan only."
          onClick={() => onChange({ visibility: 'private' })} />
        <OptionCard selected={pub} title="Public" description="People near you find it in Local and can say they're going. Your notes stay private."
          onClick={() => onChange({ visibility: 'public' })} />
      </div>
    </section>
  )
}

const NAME_HINT: Record<EventKind, string> = {
  race: 'e.g. Leadville Trail 100 Run', group_activity: 'e.g. Tuesday night group ride', trip: 'e.g. Moab training camp',
  challenge: 'e.g. Longs Peak, Colorado Trail FKT', milestone: 'e.g. Our wedding', other: 'e.g. Bike fit',
}

/** Priority, goal type and target time. */
export function EventGoal({ value, onChange, hidePriority, imperial, raceOnly = true }: {
  value: EventFields; onChange: (p: EventFields) => void; hidePriority?: boolean; imperial?: boolean
  /** false for a challenge: goal, course notes and elevation, without race wording */
  raceOnly?: boolean
}) {
  const elev = value.elevation_m ?? null
  return (
    <Card>
      {!hidePriority && (
        <Field label="How important is it?" hint="A: your big race. B: a race that matters, with a short taper. C: a training race.">
          <Choice value={value.priority ?? 'B'} onChange={(v) => onChange({ priority: v ?? 'B' })}
            options={[['A', 'A race'], ['B', 'B race'], ['C', 'Training race']]} />
        </Field>
      )}
      <Field label="Goal" className={hidePriority ? undefined : 'border-t border-(--border)'}>
        <div className="flex flex-col gap-2">
          <OptionCard selected={(value.goal_type ?? 'finish') === 'finish'} title="Finish strong" description="Get to the line healthy and enjoy it." onClick={() => onChange({ goal_type: 'finish' })} />
          <OptionCard selected={value.goal_type === 'time'} title="Hit a time" description="You have a target time in mind." onClick={() => onChange({ goal_type: 'time' })} />
          {raceOnly && <OptionCard selected={value.goal_type === 'compete'} title="Compete" description="Podium, age-group place or a qualifying spot." onClick={() => onChange({ goal_type: 'compete' })} />}
        </div>
      </Field>
      {value.goal_type === 'time' && (
        <Field label="Target time" className="border-t border-(--border)">
          <DurationInput label="Target time" expect={expectForDistance(value.distance)} value={value.target_time} onChange={(v) => onChange({ target_time: v })} />
        </Field>
      )}
      <Field label="Course notes" className="border-t border-(--border)" hint="Hilly, hot, altitude, wetsuit…">
        <textarea className={areaCls} value={value.course ?? ''} maxLength={300} onChange={(e) => onChange({ course: e.target.value })} />
      </Field>
      <Field label="Course profile" className="border-t border-(--border)">
        <Choice value={value.course_profile ?? null} allowNone options={COURSE_PROFILES}
          onChange={(v) => onChange({ course_profile: v })} />
      </Field>
      <Field label={raceOnly ? 'Race elevation' : 'Elevation'} className="border-t border-(--border)" hint="Typical altitude of the course. Race fit uses it for altitude advice.">
        {imperial ? (
          <NumberStepper label="race elevation" value={elev == null ? null : Math.round(elev / M_PER_FT / 10) * 10} min={0} max={18000} step={100}
            onChange={(v) => onChange({ elevation_m: v == null ? null : Math.min(5500, Math.round(v * M_PER_FT)) })} suffix="ft" />
        ) : (
          <NumberStepper label="race elevation" value={elev} min={0} max={5500} step={50}
            onChange={(v) => onChange({ elevation_m: v })} suffix="m" />
        )}
      </Field>
    </Card>
  )
}

/** What the web lookup found, labelled as such, with its sources. */
export function InfoBlock({ info }: { info: EventInfo }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="flex items-center gap-1.5 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--accent)">
        <Globe className="size-3.5" /> Found online{info.fetched_at ? ` · ${new Date(info.fetched_at * 1000).toLocaleDateString([], { month: 'short', day: 'numeric' })}` : ''}
      </p>
      {info.summary && <p className="text-[0.8235rem] leading-snug text-(--text)">{info.summary}</p>}
      <dl className="grid grid-cols-[84px_1fr] gap-x-3 gap-y-1.5 text-[0.7647rem]">
        {INFO_LABEL.filter(([k]) => info[k]).map(([k, label]) => (
          <div key={k} className="contents">
            <dt className="text-(--text-muted)">{label}</dt>
            <dd className="text-(--text-secondary)">{String(info[k])}</dd>
          </div>
        ))}
      </dl>
      {(info.website || info.sources?.length) && (
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-[0.7059rem]">
          {[info.website, ...(info.sources ?? [])].filter((u, i, a): u is string => !!u && a.indexOf(u) === i).slice(0, 4).map((u) => (
            <a key={u} href={u} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-(--accent)">
              {hostOf(u)} <ExternalLink className="size-3" />
            </a>
          ))}
        </div>
      )}
      <p className="text-[0.6471rem] text-(--text-muted)">From a web search. Double-check dates and cutoffs on the official site.</p>
    </div>
  )
}

function hostOf(u: string): string {
  try { return new URL(u).hostname.replace(/^www\./, '') } catch { return u }
}
