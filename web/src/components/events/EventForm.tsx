// The event form (Events screen and the setup wizard's race step): kind (race, group
// activity, trip, challenge, life event, other) first, then type, name with a web lookup,
// distance, date, where, how important, goal, course and notes. Race-only fields are hidden
// for other kinds; group activities, trips and life events get their own few fields.
import { useState } from 'react'
import { CalendarDays, ExternalLink, Flag, Globe, PartyPopper, Search, Tent, Trophy, Users } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, Choice, Field, NumberStepper, OptionCard, areaCls, inputCls } from '@/components/plan/ui'
import { M_PER_FT } from '@/lib/plan'
import {
  COURSE_PROFILES, DISTANCE_LABEL, EVENT_KINDS, EVENT_TYPES, INFO_LABEL, KIND_HINT, TYPE_DISTANCES, WEEKDAYS, kindOf, lookupEvent,
  type EventFields, type EventInfo, type EventKind, type EventType, type Weekday,
} from '@/lib/events'
import { cn } from '@/lib/utils'

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
      <Field label="What is it?" hint={value ? KIND_HINT[value] : 'Races, group sessions, trips and big life days all shape your plan.'}>
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
  const rec = value.recurring ?? null
  const weekdayOf = (d?: string): Weekday => {
    const n = d ? new Date(`${d}T12:00:00`).getDay() : 2
    return (['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'] as Weekday[])[Number.isNaN(n) ? 2 : n]!
  }
  return (
    <Card>
      {multi && (
        <Field label="Last day" hint={kind === 'trip' ? 'Rabbit keeps those days short and easy.' : 'Optional. Rabbit plans rest days around it.'}>
          <input type="date" className={inputCls} value={value.end_date ?? ''} min={value.date || undefined}
            onChange={(e) => onChange({ end_date: e.target.value || null })} />
        </Field>
      )}
      {group && (
        <Field label="Repeats weekly" hint="Leagues and weekly group rides: Rabbit puts each one in your plan.">
          <div className="flex flex-col gap-2">
            <ChoiceRow on={!!rec} onToggle={(on) => onChange({ recurring: on ? { weekday: weekdayOf(value.date), until: value.date || todayIso() } : null })} />
            {rec && (
              <>
                <Choice value={rec.weekday} options={WEEKDAYS} onChange={(v) => v && onChange({ recurring: { ...rec, weekday: v } })} />
                <label className="flex flex-col gap-1 text-[0.7059rem] text-(--text-muted)">Until
                  <input type="date" className={inputCls} value={rec.until} min={value.date || undefined}
                    onChange={(e) => onChange({ recurring: { ...rec, until: e.target.value } })} />
                </label>
              </>
            )}
          </div>
        </Field>
      )}
      {(group || kind === 'other') && (
        <>
          <Field label="Start time" className={cn((group || multi) && 'border-t border-(--border)')}>
            <input type="time" className={inputCls} value={value.time ?? ''} onChange={(e) => onChange({ time: e.target.value || null })} />
          </Field>
          <Field label="How long" className="border-t border-(--border)" hint={kind === 'other' ? 'Add a length and Rabbit counts it as a session.' : undefined}>
            <NumberStepper label="how long" value={value.duration_min ?? null} min={10} max={600} step={15} suffix="min"
              onChange={(v) => onChange({ duration_min: v })} />
          </Field>
          <Field label="Effort" className="border-t border-(--border)">
            <Choice value={value.intensity ?? 'moderate'} onChange={(v) => onChange({ intensity: v ?? 'moderate' })}
              options={[['easy', 'Easy'], ['moderate', 'Moderate'], ['hard', 'Hard']]} />
          </Field>
        </>
      )}
      {kind !== 'milestone' && (
        <>
          <Field label="With" className={cn((group || multi || kind === 'other') && 'border-t border-(--border)')}>
            <input className={inputCls} value={value.with ?? ''} maxLength={80} placeholder={group ? 'e.g. Golden Cyclery, Tuesday crew' : 'Who’s coming'}
              onChange={(e) => onChange({ with: e.target.value })} />
          </Field>
          <Field label="Meeting spot" className="border-t border-(--border)">
            <input className={inputCls} value={value.at ?? ''} maxLength={80} placeholder={group ? 'e.g. the shop, Washington Park' : 'Trailhead, hut, town'}
              onChange={(e) => onChange({ at: e.target.value })} />
          </Field>
        </>
      )}
    </Card>
  )
}

function ChoiceRow({ on, onToggle }: { on: boolean; onToggle: (on: boolean) => void }) {
  return (
    <Choice value={on ? 'yes' : 'no'} onChange={(v) => onToggle(v === 'yes')}
      options={[['no', 'One time'], ['yes', 'Every week']]} />
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
    if (i.suggested_type) p.type = i.suggested_type
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
          <Field label={kind === 'race' ? 'Type of event' : 'Sport'}>
            <Choice value={type} options={EVENT_TYPES}
              onChange={(v) => v && onChange({ type: v, distance: !raceLike ? '' : TYPE_DISTANCES[v].includes(value.distance ?? '') ? value.distance
                : TYPE_DISTANCES[v].length === 1 ? TYPE_DISTANCES[v][0] : '' })} />
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
        <Field label="Target time" className="border-t border-(--border)" hint="Hours:minutes:seconds, or minutes:seconds.">
          <input className={inputCls} inputMode="numeric" placeholder="5:30:00" value={value.target_time ?? ''}
            onChange={(e) => onChange({ target_time: e.target.value })} />
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
