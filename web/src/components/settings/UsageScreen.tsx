// Me -> Usage and traction (owners only; usage.py GET /app/api/usage/summary and traction.py
// GET /app/api/usage/traction, each section with its go threshold). Last 30 days of
// anonymous counts: active people, people coming back, where setup loses people, and what
// gets tapped. Plain numbers and bars; no individual is ever shown.
import { useCallback, useEffect, useState } from 'react'
import { Screen } from '@/components/plan/ui'
import { ErrorState } from '@/components/ui/ErrorState'
import { RowsSkeleton } from '@/components/ui/Skeleton'
import { getJSON } from '@/lib/api'
import type { UsageSummary } from '@/lib/usage'
import { getConnections, type SoonApp } from '@/lib/connections'
import { cn } from '@/lib/utils'
import { HEARD_OPTIONS, getTraction, type Traction } from '@/lib/traction'

const STEP_LABEL: Record<string, string> = {
  intro: 'Started setup', race: 'Race', goal: 'Goal', you: 'About you', numbers: 'Numbers', week: 'Week', review: 'Review', complete: 'Plan built',
}
const CARD_LABEL: Record<string, string> = {
  upnext: 'Up next', ring: 'Weekly ring', race_grade: 'Race grade', reward: 'Workout reward', actions: 'Quick actions',
}
const TAB_LABEL: Record<string, string> = {
  rabbit: 'Today', plan: 'Plan', feed: 'Friends', clubs: 'Near me', community: 'Community (old)', races: 'Events (old)', progress: 'Progress', me: 'Me',
}

function Section({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2 rounded-2xl border border-(--border) bg-(--bg-surface) p-4">
      <h2 className="section-title m-0 px-1">{title}</h2>
      {children}
      {note && <p className="text-small leading-snug text-(--text-secondary)">{note}</p>}
    </section>
  )
}

function Bar({ label, value, max, suffix }: { label: string; value: number; max: number; suffix?: string }) {
  const pct = max > 0 ? Math.max(2, Math.round((100 * value) / max)) : 0
  return (
    <div className="flex items-center gap-2 text-small">
      <span className="w-32 shrink-0 truncate text-(--text-secondary) min-[400px]:w-40" title={label}>{label}</span>
      <span className="relative h-3 flex-1 overflow-hidden rounded-full bg-(--bg-inset)" aria-hidden="true">
        <span className="absolute inset-y-0 left-0 rounded-full bg-(--accent)" style={{ width: `${value ? pct : 0}%` }} />
      </span>
      <span className="w-[4.5rem] shrink-0 whitespace-nowrap text-right font-mono text-meta tabular-nums text-(--text)">{value}{suffix ?? ''}</span>
    </div>
  )
}

function Stat({ n, label }: { n: number | string; label: string }) {
  return (
    <div className="flex flex-1 flex-col items-center rounded-xl bg-(--bg-inset) px-2 py-2.5">
      <span className="font-mono text-title-md tabular-nums text-(--text)">{n}</span>
      <span className="text-meta text-(--text-secondary)">{label}</span>
    </div>
  )
}


/** On track / getting there / not yet, against the go threshold (half of it = iterate). */
function Goal({ value, target, unit = '%' }: { value: number | null; target: number; unit?: string }) {
  const tone = value == null ? 'muted' : value >= target ? 'good' : value >= target / 2 ? 'mid' : 'low'
  const word = { muted: 'No data yet', good: 'On track', mid: 'Getting there', low: 'Not yet' }[tone]
  return (
    <p className="m-0 flex items-center gap-2 text-small">
      <span className={cn('rounded-full px-2 py-0.5 text-meta font-semibold',
        tone === 'good' ? 'bg-(--accent) text-(--on-fill)' : tone === 'mid' ? 'bg-(--warning) text-black' : 'bg-(--bg-inset) text-(--text-secondary)')}>{word}</span>
      <span className="text-(--text-secondary)">Goal: {target}{unit} or more</span>
    </p>
  )
}
const FUNNEL_LABEL: Record<string, string> = { signup: 'Signed up', area_set: 'Set their area', job: 'RSVP or posted a run', plan_built: 'Got a plan' }
const FIRST_LABEL: Record<string, string> = {
  area_set: 'Area set', rsvp: 'First RSVP', run_posted: 'First run posted', plan_built: 'First plan', post: 'First post', follow: 'First follow', watch_connected: 'Watch connected',
}

function TractionSections({ t }: { t: Traction }) {
  const g = t.growth, a = t.activation, o = t.organizers, last = o.weeks[o.weeks.length - 1]
  const srcMax = Math.max(1, ...g.sources.map((x) => x.users))
  const wkMax = Math.max(1, ...t.weeks.map((w) => w.active))
  return (
    <>
      <Section title="Growth" note={`"How did you hear about rabbt?" (optional, ${g.answered} answered). Joins counted from invite links and club pages.`}>
        <div className="flex gap-2">
          <Stat n={g.signups} label="New, 30 days" />
          <Stat n={g.invite_joins} label="From invites" />
          <Stat n={g.club_joins} label="From club pages" />
        </div>
        {g.sources.map((x) => <Bar key={x.id} label={HEARD_OPTIONS.find((h) => h.id === x.id)?.label ?? x.id} value={x.users} max={srcMax} />)}
        {g.club_refs.length > 0 && g.club_refs.slice(0, 5).map((r) => <Bar key={r.slug} label={r.slug} value={r.users} max={g.club_refs[0]!.users} />)}
      </Section>

      <Section title="Activation" note="People who signed up in the last 30 days. A core job is an RSVP, a posted run or a plan.">
        {a.funnel.map((f) => <Bar key={f.id} label={FUNNEL_LABEL[f.id] ?? f.id} value={f.users} max={Math.max(1, a.funnel[0]!.users)} suffix={f.pct != null ? ` · ${f.pct}%` : ''} />)}
        <div className="flex gap-2"><Stat n={a.core7.pct == null ? '–' : `${a.core7.pct}%`} label={`Core job in 7 days (${a.core7.users}/${a.core7.cohort})`} /></div>
        <Goal value={a.core7.pct} target={t.targets.core7_pct} />
        <details className="text-small">
          <summary className="min-h-11 cursor-pointer py-2 font-semibold text-(--accent)">Every first</summary>
          {Object.entries(a.firsts).map(([k, v]) => (
            <div key={k} className="flex justify-between py-0.5"><span className="text-(--text-secondary)">{FIRST_LABEL[k] ?? k}</span><span className="font-mono tabular-nums">{v}</span></div>
          ))}
        </details>
      </Section>

      <Section title="Retention" note="Of people who did a core job, the share still active in their 4th week.">
        <div className="flex gap-2"><Stat n={t.retention.w4.pct == null ? '–' : `${t.retention.w4.pct}%`} label={`Week 4 (${t.retention.w4.users}/${t.retention.w4.cohort})`} /></div>
        <Goal value={t.retention.w4.pct} target={t.targets.w4_pct} />
        {t.weeks.length > 0 && (
          <div className="mt-1 flex h-14 items-end gap-1" role="img" aria-label={`Weekly active people, last ${t.weeks.length} weeks`}>
            {t.weeks.map((w) => <span key={w.week} title={`${w.week}: ${w.active}`} className="flex-1 rounded-t-sm bg-(--accent)/60"
              style={{ height: `${w.active ? Math.max(6, Math.round((100 * w.active) / wkMax)) : 0}%` }} />)}
          </div>
        )}
      </Section>

      <Section title="Organizers" note="Club runs, by week. Healthy = a club whose runs last week averaged 8 or more RSVPs. Repeat attendees came to 2 or more runs.">
        <div className="flex gap-2">
          <Stat n={o.healthy_clubs} label="Healthy clubs" />
          <Stat n={o.clubs} label="Club pages" />
          <Stat n={o.repeat_attendees} label="Repeat attendees" />
        </div>
        <Goal value={o.healthy_clubs} target={t.targets.clubs_weekly} unit=" clubs" />
        <div className="overflow-x-auto">
          <table className="w-full text-left text-small">
            <thead><tr className="text-meta text-(--text-muted)"><th className="py-1 font-medium">Week of</th><th className="font-medium">New clubs</th><th className="font-medium">Runs posted</th><th className="font-medium">Runs held</th><th className="font-medium">RSVPs/run</th><th className="font-medium">Checked in</th></tr></thead>
            <tbody className="font-mono tabular-nums">
              {o.weeks.map((w) => (
                <tr key={w.week} className="border-t border-(--border)"><td className="whitespace-nowrap py-1 pr-2 font-sans">{new Date(`${w.from}T12:00:00`).toLocaleDateString([], { month: 'short', day: 'numeric' })}</td><td>{w.clubs_created}</td><td>{w.runs_posted}</td><td>{w.runs_held}</td><td>{w.rsvps_per_run ?? '–'}</td><td>{w.checkin_pct == null ? '–' : `${w.checkin_pct}%`}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        {last && <p className="m-0 text-meta text-(--text-muted)">Goal: {t.targets.clubs_weekly} clubs posting weekly with {t.targets.rsvps_per_run}+ RSVPs per run.</p>}
      </Section>

      <Section title="Denver share" note="Active last full week with an area in the Denver metro, out of about 94,000 people who run with groups there. Clubs: club pages in Denver out of 26 known clubs.">
        <div className="flex gap-2">
          <Stat n={`${t.denver.pct}%`} label={`${t.denver.active.toLocaleString()} of ${t.denver.runners.toLocaleString()}`} />
          <Stat n={t.denver.clubs_pct == null ? '–' : `${t.denver.clubs_pct}%`} label={`${t.denver.clubs} of ${t.denver.known_clubs} clubs`} />
        </div>
      </Section>

      <Section title="Recommend score" note="Asked once on day 7: how likely to recommend rabbt (0 to 10). Score = % 9-10 minus % 0-6, last 90 days.">
        <div className="flex gap-2">
          <Stat n={t.nps.score ?? '–'} label={`${t.nps.answers} answers`} />
          <Stat n={t.nps.promoters} label="9 or 10" />
          <Stat n={t.nps.detractors} label="0 to 6" />
        </div>
        <Goal value={t.nps.score} target={t.targets.nps} unit="" />
        {t.notes.length > 0 && (
          <div className="flex flex-col gap-2 pt-1">
            <h3 className="m-0 px-1 text-small font-semibold text-(--text)">Notes people left</h3>
            {t.notes.slice(0, 10).map((n, i) => (
              <blockquote key={i} className="m-0 rounded-lg bg-(--bg-inset) px-3 py-2 text-small leading-snug text-(--text)">
                {n.note}<span className="mt-1 block text-meta text-(--text-muted)">{n.name || 'Someone'}{n.score != null ? `, ${n.score}/10` : ''} · {n.date}</span>
              </blockquote>
            ))}
          </div>
        )}
      </Section>
    </>
  )
}

export function UsageScreen({ onClose }: { onClose: () => void }) {
  const [s, setS] = useState<UsageSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(() => {
    setError(null)
    getJSON<UsageSummary>('/api/usage/summary').then(setS, (e: Error) => setError(e.message))
  }, [])
  useEffect(() => { load() }, [load])
  const [t, setT] = useState<Traction | null>(null)
  useEffect(() => { getTraction().then(setT, () => {}) }, [])
  // "I want this" on coming-soon apps (demand.py): one per person; counts are owner-only.
  const [soon, setSoon] = useState<SoonApp[] | null>(null)
  useEffect(() => { getConnections().then((c) => setSoon(c.soon ?? []), () => setSoon([])) }, [])

  const peak = s ? Math.max(1, ...s.series.map((d) => d.dau)) : 1
  const ret = (r: { pct: number | null; returned: number; cohort: number }) => (r.pct == null ? '–' : `${r.pct}%`)
  return (
    <Screen title="Usage and traction" subtitle="Counts only, no individuals. Last 30 days unless noted." onBack={onClose} onClose={onClose}>
      {error && <ErrorState message={`Couldn't load usage: ${error}`} onRetry={load} />}
      {!s && !error && <RowsSkeleton label="Loading usage" count={6} />}
      {s && (
        <div className="flex flex-col gap-3">
          {t && <TractionSections t={t} />}
          <Section title="Active people" note="Daily, 7-day and 30-day unique people (counted with a code that changes every day).">
            <div className="flex gap-2">
              <Stat n={s.now.dau} label="Today" />
              <Stat n={s.now.wau} label="7 days" />
              <Stat n={s.now.mau} label="30 days" />
            </div>
            <div className="mt-1 flex h-16 items-end gap-[2px]" role="img"
              aria-label={`People per day, last 30 days: highest ${peak}, today ${s.now.dau}`}>
              {s.series.map((d) => (
                <span key={d.date} title={`${d.date}: ${d.dau}`}
                  className={cn('flex-1 rounded-t-sm', d.date === s.today ? 'bg-(--accent)' : 'bg-(--accent)/45')}
                  style={{ height: `${d.dau ? Math.max(4, Math.round((100 * d.dau) / peak)) : 0}%` }} />
              ))}
            </div>
            <p className="text-small text-(--text-secondary)">{s.new_users} new {s.new_users === 1 ? 'person' : 'people'} in 30 days</p>
          </Section>

          <Section title="Coming back" note="Of people first seen in the last 30 days, the share who used rabbt again exactly 1 and 7 days later.">
            <div className="flex gap-2">
              <Stat n={ret(s.retention.d1)} label={`Next day (${s.retention.d1.returned}/${s.retention.d1.cohort})`} />
              <Stat n={ret(s.retention.d7)} label={`Day 7 (${s.retention.d7.returned}/${s.retention.d7.cohort})`} />
            </div>
          </Section>

          {soon && soon.some((a) => a.wanted_by != null) && (
            <Section title="Apps people want" note="People who tapped “I want this” on a coming-soon app (each person once).">
              {soon.map((a) => (
                <Bar key={a.id} label={a.name} value={a.wanted_by ?? 0} max={Math.max(1, ...soon.map((x) => x.wanted_by ?? 0))} />
              ))}
            </Section>
          )}

          <Section title="Setup funnel" note="People reaching each plan setup step (share of those who started).">
            {s.funnel[0]?.users ? s.funnel.map((f) => (
              <Bar key={f.step} label={STEP_LABEL[f.step] ?? f.step} value={f.users} max={s.funnel[0]!.users}
                suffix={f.pct != null ? ` · ${f.pct}%` : ''} />
            )) : <p className="text-small text-(--text-muted)">Nobody started setup yet.</p>}
          </Section>

          <Section title="Cards tapped">
            {s.cards.length ? s.cards.map((c) => (
              <Bar key={c.id} label={CARD_LABEL[c.id] ?? c.id} value={c.taps} max={s.cards[0]!.taps} />
            )) : <p className="text-small text-(--text-muted)">No card taps yet.</p>}
          </Section>

          <Section title="Tabs viewed">
            {s.tabs.length ? s.tabs.map((t) => (
              <Bar key={t.id} label={TAB_LABEL[t.id] ?? t.id} value={t.taps} max={s.tabs[0]!.taps} />
            )) : <p className="text-small text-(--text-muted)">No tab views yet.</p>}
          </Section>

          <Section title="Other actions">
            {(['invite_join', 'share', 'cheer', 'rsvp', 'push_open'] as const).map((k) => (
              <div key={k} className="flex justify-between text-small">
                <span className="text-(--text-secondary)">
                  {{ invite_join: 'Joined from an invite', share: 'Shares', cheer: 'Cheers and kudos', rsvp: 'RSVPs', push_open: 'Opened from a notification' }[k]}
                </span>
                <span className="font-mono text-meta tabular-nums">{s.events[k] ?? 0}</span>
              </div>
            ))}
          </Section>
        </div>
      )}
    </Screen>
  )
}
