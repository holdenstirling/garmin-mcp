// Weekly recap (server: recap.py): workouts and plan adherence first, then XP, streak, badges,
// best workout and next week's focus, for any of the last 8 weeks.
import { useEffect, useState } from 'react'
import { Award, Carrot, ChevronLeft, ChevronRight, Flame, MessageCircle, Trophy } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, Screen } from '@/components/plan/ui'
import { RabbitLoader } from '@/components/RabbitLoader'
import { ErrorState } from '@/components/ui/ErrorState'
import { InfoTip } from '@/components/ui/InfoTip'
import { fmtDist, fmtDuration } from '@/lib/format'
import { WeekRing } from '@/components/progress/Progress'
import { cn } from '@/lib/utils'
import { getRecap, shiftWeek, type Recap } from '@/lib/live'

const fmtDay = (d: string, opts: Intl.DateTimeFormatOptions) => new Date(`${d}T12:00:00`).toLocaleDateString([], opts)

function weekLabel(r: Recap): string {
  return `${fmtDay(r.week_start, { month: 'short', day: 'numeric' })} – ${fmtDay(r.week_end, { month: 'short', day: 'numeric' })}`
}

export function RecapSheet({ week: initialWeek, onClose, onAsk }: {
  week?: string; onClose: () => void; onAsk: (text: string) => void
}) {
  const [week, setWeek] = useState<string | undefined>(initialWeek)
  const [r, setR] = useState<Recap | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [closing, setClosing] = useState(false)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let live = true
    setError(null)
    getRecap(week).then((x) => { if (live) setR(x) }, (e) => { if (live) setError((e as Error).message) })
    return () => { live = false }
  }, [week, attempt])
  const close = () => { setClosing(true); setTimeout(onClose, 200) }
  const prev = r ? shiftWeek(r.week_start, -1) : null
  const next = r ? shiftWeek(r.week_start, 1) : null
  const canPrev = !!r && !!prev && prev >= r.browse.oldest
  const canNext = !!r && !!next && next <= r.browse.newest
  const loading = !r || (week !== undefined && r.week_start !== week)

  return (
    <Screen title="Your week" subtitle={r ? weekLabel(r) : undefined} closing={closing} onClose={close}
      headerExtra={
        <div className="mx-auto mt-1.5 flex max-w-xl items-center justify-between">
          <button type="button" disabled={!canPrev} onClick={() => prev && setWeek(prev)} aria-label="Previous week"
            className="hit-44 inline-flex items-center gap-0.5 text-meta text-(--text-secondary) disabled:opacity-30">
            <ChevronLeft className="size-4" /> Earlier
          </button>
          <span className="text-meta text-(--text-secondary)">{r?.current ? 'This week' : r ? 'Week in review' : ''}</span>
          <button type="button" disabled={!canNext} onClick={() => next && setWeek(next)} aria-label="Next week"
            className="hit-44 inline-flex items-center gap-0.5 text-meta text-(--text-secondary) disabled:opacity-30">
            Later <ChevronRight className="size-4" />
          </button>
        </div>
      }>
      {error && <ErrorState message={`Couldn't load your week: ${error}`} onRetry={() => setAttempt((n) => n + 1)} />}
      {!error && loading && (
        <div className="flex justify-center py-16">
          <RabbitLoader label="Loading your week" cycle={['Tallying your XP…', 'Counting the miles…', 'Planning next week…']} />
        </div>
      )}
      {!error && !loading && r && <RecapBody r={r} onAsk={onAsk} />}
    </Screen>
  )
}

function RecapBody({ r, onAsk }: { r: Recap; onAsk: (text: string) => void }) {
  const pct = Math.max(2, Math.min(100, Math.round((100 * r.level.level_xp) / Math.max(1, r.level.level_span))))
  const ad = r.adherence
  const nw = r.next_week
  const imperial = r.units !== 'metric'
  const planned = ad && ad.planned > 0 ? ad : null
  return (
    <>
      <div className="celebrate flex items-center gap-4 rounded-2xl border border-(--border) bg-(--bg-surface) px-4 py-5">
        {planned ? <WeekRing done={planned.done} target={planned.planned} size={64} /> : <WeekRing done={r.active_days} target={7} size={64} />}
        <div className="min-w-0 flex-1">
          <p className="font-display text-display-xl leading-none text-(--brand)">
            {r.workouts} <span className="text-title-sm">workout{r.workouts === 1 ? '' : 's'}</span>
          </p>
          <p className="mt-1.5 text-body text-(--text-secondary)">
            {[r.hours ? fmtDuration(r.hours * 60) : '', r.km ? fmtDist(r.km, imperial) : ''].filter(Boolean).join(', ') || 'No training logged'}
          </p>
          <p className="mt-1 flex flex-wrap items-center gap-1 text-body font-medium text-(--text)">
            {planned
              ? <>Plan: {planned.done} of {planned.planned} sessions{planned.pct != null ? ` (${planned.pct}%)` : ''}<InfoTip term="adherence" align="end" /></>
              : `Active ${r.active_days} of 7 days`}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Tile label={`XP this week. ${r.level.to_next.toLocaleString()} to level ${r.level.level + 1}`} value={`+${r.xp.toLocaleString()}`}
          icon={<Carrot className="size-6 text-(--accent)" aria-hidden />} tip={<InfoTip term="xp" />}>
          <span className="mt-1 block h-1.5 w-full max-w-20 overflow-hidden rounded-full bg-(--bg-elevated)">
            <span className="block h-full rounded-full bg-(--accent)" style={{ width: `${pct}%` }} />
          </span>
        </Tile>
        <Tile label="day streak" value={String(r.streak)} tip={<InfoTip term="streak" />}
          icon={<Flame className={cn('size-6', r.streak ? 'text-(--accent)' : 'text-(--text-muted)')} />} />
      </div>

      {r.challenges && r.challenges.items.length > 0 && (
        <div className="flex items-start gap-2.5 px-1 text-body text-(--text-secondary)">
          <Trophy className="mt-0.5 size-5 shrink-0 text-(--accent)" aria-hidden />
          <div className="min-w-0">
            <p className="m-0 font-medium text-(--text)">Challenges</p>
            {r.challenges.joined ? <p className="m-0">{r.challenges.done} of {r.challenges.joined} weekly done</p> : null}
            {r.challenges.items.some((i) => i.period === 'month' && i.done) && (
              <p className="m-0">Finished: {r.challenges.items.filter((i) => i.period === 'month' && i.done).map((i) => i.name).join(', ')}</p>
            )}
            {r.challenges.xp ? <p className="m-0 font-medium text-(--accent)">+{r.challenges.xp} XP</p> : null}
          </div>
        </div>
      )}
      {r.badges.length > 0 && (
        <Card>
          <div className="flex flex-col gap-3 px-4 py-4">
            <Label>Badges earned</Label>
            <div className="flex flex-wrap gap-2">
              {r.badges.map((b) => (
                <span key={b.id} title={b.description}
                  className="inline-flex items-center gap-1.5 rounded-full border border-(--accent)/40 bg-(--accent-subtle) px-3 py-1.5 text-small font-medium text-(--accent)">
                  <Award className="size-4" />{b.title}
                </span>
              ))}
            </div>
          </div>
        </Card>
      )}

      {r.best && (
        <Card>
          <div className="flex items-start gap-3.5 px-4 py-4">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-(--brand) text-(--on-fill)"><Trophy className="size-5" aria-hidden /></span>
            <span className="min-w-0 flex-1">
              <Label>Best workout</Label>
              <span className="mt-0.5 block text-body-lg font-semibold leading-snug text-(--text)">{r.best.name}</span>
              <span className="block text-small text-(--text-secondary)">{fmtDay(r.best.date, { weekday: 'long' })}</span>
              <span className="block text-small text-(--text-secondary)">
                {fmtDuration(r.best.minutes)}{r.best.km ? `, ${fmtDist(r.best.km, imperial, r.best.sport)}` : ''}
              </span>
            </span>
          </div>
        </Card>
      )}
      {!r.workouts && (
        <p className="px-1 text-center text-body text-(--text-secondary)">A quiet week. Every streak starts with one workout.</p>
      )}

      <Card>
        <div className="flex flex-col gap-3 px-4 py-4">
          <Label>Next week{nw.phase ? `: ${nw.phase}${nw.recovery ? ' (recovery)' : ''}` : ''}</Label>
          {nw.focus && <p className="text-body leading-snug text-(--text)">{nw.focus}</p>}
          {nw.sessions.length > 0 ? (
            <ul className="flex flex-col divide-y divide-(--border)">
              {nw.sessions.map((s) => (
                <li key={`${s.date}-${s.title}`} className="flex items-baseline gap-3 py-2.5 text-body">
                  <span className="w-10 shrink-0 text-small font-medium text-(--text-secondary)">{fmtDay(s.date, { weekday: 'short' })}</span>
                  <span className="min-w-0 flex-1 text-(--text)">{s.title}</span>
                  {s.minutes ? <span className="shrink-0 text-small text-(--text-secondary)">{fmtDuration(s.minutes)}</span> : null}
                </li>
              ))}
            </ul>
          ) : nw.target ? <p className="text-body leading-snug text-(--text)">{nw.target}</p> : null}
          <Button variant="default" className="mt-1 h-11 gap-1.5"
            onClick={() => onAsk('About next week: ')}>
            <MessageCircle className="size-5" /> Ask rabbt about next week
          </Button>
        </div>
      </Card>
    </>
  )
}

function Tile({ label, value, icon, tip, children }: {
  label: string; value: string; icon: React.ReactNode; tip?: React.ReactNode; children?: React.ReactNode
}) {
  return (
    <div className="flex flex-col items-center gap-1.5 rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-4 text-center">
      {icon}
      <span className="font-display text-title-md leading-none text-(--text)">{value}</span>
      <span className="text-small leading-snug text-(--text-secondary)">{label}{tip && <> {tip}</>}</span>
      {children}
    </div>
  )
}

function Label({ children }: { children: React.ReactNode }) {
  return <span className="block text-body font-semibold text-(--text)">{children}</span>
}
