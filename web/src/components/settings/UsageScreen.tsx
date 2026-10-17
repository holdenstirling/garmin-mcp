// Me -> Usage (owners only; server usage.py, GET /app/api/usage/summary). Last 30 days of
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

const STEP_LABEL: Record<string, string> = {
  intro: 'Started setup', race: 'Race', goal: 'Goal', you: 'About you', numbers: 'Numbers', week: 'Week', review: 'Review', complete: 'Plan built',
}
const CARD_LABEL: Record<string, string> = {
  upnext: 'Up next', ring: 'Weekly ring', race_grade: 'Race grade', reward: 'Workout reward', actions: 'Quick actions',
}
const TAB_LABEL: Record<string, string> = {
  rabbit: 'Rabbit', plan: 'Plan', community: 'Community', races: 'Events', progress: 'Progress', me: 'Me',
}

function Section({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2 rounded-2xl border border-(--border) bg-(--bg-surface) p-4">
      <h2 className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">{title}</h2>
      {children}
      {note && <p className="text-[0.7059rem] leading-snug text-(--text-muted)">{note}</p>}
    </section>
  )
}

function Bar({ label, value, max, suffix }: { label: string; value: number; max: number; suffix?: string }) {
  const pct = max > 0 ? Math.max(2, Math.round((100 * value) / max)) : 0
  return (
    <div className="flex items-center gap-2 text-[0.7647rem]">
      <span className="w-28 shrink-0 truncate text-(--text-secondary)">{label}</span>
      <span className="relative h-3 flex-1 overflow-hidden rounded-full bg-(--bg-inset)" aria-hidden="true">
        <span className="absolute inset-y-0 left-0 rounded-full bg-(--accent)" style={{ width: `${value ? pct : 0}%` }} />
      </span>
      <span className="w-14 shrink-0 text-right font-mono text-[0.7059rem] tabular-nums text-(--text)">{value}{suffix ?? ''}</span>
    </div>
  )
}

function Stat({ n, label }: { n: number | string; label: string }) {
  return (
    <div className="flex flex-1 flex-col items-center rounded-xl bg-(--bg-inset) px-2 py-2.5">
      <span className="font-mono text-[1.2941rem] tabular-nums text-(--text)">{n}</span>
      <span className="text-[0.6471rem] text-(--text-muted)">{label}</span>
    </div>
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
  // "I want this" on coming-soon apps (demand.py): one per person; counts are owner-only.
  const [soon, setSoon] = useState<SoonApp[] | null>(null)
  useEffect(() => { getConnections().then((c) => setSoon(c.soon ?? []), () => setSoon([])) }, [])

  const peak = s ? Math.max(1, ...s.series.map((d) => d.dau)) : 1
  const ret = (r: { pct: number | null; returned: number; cohort: number }) => (r.pct == null ? '–' : `${r.pct}%`)
  return (
    <Screen title="Usage" subtitle="Last 30 days · anonymous counts" onBack={onClose} onClose={onClose}>
      {error && <ErrorState message={`Couldn't load usage: ${error}`} onRetry={load} />}
      {!s && !error && <RowsSkeleton label="Loading usage" count={6} />}
      {s && (
        <div className="flex flex-col gap-3">
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
            <p className="text-[0.7059rem] text-(--text-muted)">{s.new_users} new {s.new_users === 1 ? 'person' : 'people'} in 30 days</p>
          </Section>

          <Section title="Coming back" note="Of people first seen in the last 30 days, the share who used Rabbit again exactly 1 and 7 days later.">
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
            )) : <p className="text-[0.7647rem] text-(--text-muted)">Nobody started setup yet.</p>}
          </Section>

          <Section title="Cards tapped">
            {s.cards.length ? s.cards.map((c) => (
              <Bar key={c.id} label={CARD_LABEL[c.id] ?? c.id} value={c.taps} max={s.cards[0]!.taps} />
            )) : <p className="text-[0.7647rem] text-(--text-muted)">No card taps yet.</p>}
          </Section>

          <Section title="Tabs viewed">
            {s.tabs.length ? s.tabs.map((t) => (
              <Bar key={t.id} label={TAB_LABEL[t.id] ?? t.id} value={t.taps} max={s.tabs[0]!.taps} />
            )) : <p className="text-[0.7647rem] text-(--text-muted)">No tab views yet.</p>}
          </Section>

          <Section title="Other actions">
            {(['invite_join', 'share', 'cheer', 'rsvp', 'push_open'] as const).map((k) => (
              <div key={k} className="flex justify-between text-[0.7647rem]">
                <span className="text-(--text-secondary)">
                  {{ invite_join: 'Joined from an invite', share: 'Shares', cheer: 'Cheers and kudos', rsvp: 'RSVPs', push_open: 'Opened from a notification' }[k]}
                </span>
                <span className="font-mono text-[0.7059rem] tabular-nums">{s.events[k] ?? 0}</span>
              </div>
            ))}
          </Section>
        </div>
      )}
    </Screen>
  )
}
