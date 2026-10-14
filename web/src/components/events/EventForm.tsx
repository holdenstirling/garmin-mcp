// The event form (Events screen and the setup wizard's race step): type, name with a web
// lookup, distance, date, where, how important, goal, course and notes.
import { useState } from 'react'
import { ExternalLink, Globe, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, Choice, Field, OptionCard, areaCls, inputCls } from '@/components/plan/ui'
import {
  DISTANCE_LABEL, EVENT_TYPES, INFO_LABEL, TYPE_DISTANCES, lookupEvent,
  type EventFields, type EventInfo, type EventType,
} from '@/lib/events'
import { cn } from '@/lib/utils'

const todayIso = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** Type, name + lookup, distance, date, location, website. */
export function EventBasics({ value, onChange, eventId, allowPast }: {
  value: EventFields; onChange: (p: EventFields) => void; eventId?: string; allowPast?: boolean
}) {
  const [busy, setBusy] = useState(false)
  const [found, setFound] = useState<EventInfo | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const type = (value.type ?? 'other') as EventType
  const dists = TYPE_DISTANCES[type]

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
    onChange(p)
    setFound(null)
    setMsg('Details filled in. Check them before saving.')
  }

  return (
    <>
      <Card>
        <Field label="Type of event">
          <Choice value={type} options={EVENT_TYPES}
            onChange={(v) => v && onChange({ type: v, distance: TYPE_DISTANCES[v].includes(value.distance ?? '') ? value.distance : TYPE_DISTANCES[v][0] })} />
        </Field>
        <Field label="Event name" className="border-t border-(--border)"
          hint="Type the name, then look it up to fill in the date, location and course from the web.">
          <div className="flex gap-2">
            <input className={inputCls} value={value.name ?? ''} maxLength={120} placeholder="e.g. Leadville Trail 100 Run"
              onChange={(e) => onChange({ name: e.target.value })} />
            <Button variant="default" className="h-10 shrink-0 gap-1.5 px-3 text-[0.7647rem]" loading={busy}
              disabled={(value.name ?? '').trim().length < 3} onClick={() => void lookup()}>
              <Search className="size-3.5" /> Look up
            </Button>
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
        <Field label="Date" className="border-t border-(--border)">
          <input type="date" className={inputCls} value={value.date ?? ''} min={allowPast ? undefined : todayIso()}
            onChange={(e) => onChange({ date: e.target.value })} />
        </Field>
        <Field label="Where" className="border-t border-(--border)">
          <input className={inputCls} value={value.location ?? ''} maxLength={120} placeholder="City, state"
            onChange={(e) => onChange({ location: e.target.value })} />
        </Field>
        <Field label="Website" className="border-t border-(--border)">
          <input className={inputCls} type="url" inputMode="url" value={value.url ?? ''} maxLength={300} placeholder="https://"
            onChange={(e) => onChange({ url: e.target.value.trim() })} />
        </Field>
      </Card>
    </>
  )
}

/** Priority, goal type and target time. */
export function EventGoal({ value, onChange, hidePriority }: {
  value: EventFields; onChange: (p: EventFields) => void; hidePriority?: boolean
}) {
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
          <OptionCard selected={value.goal_type === 'compete'} title="Compete" description="Podium, age-group place or a qualifying spot." onClick={() => onChange({ goal_type: 'compete' })} />
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
