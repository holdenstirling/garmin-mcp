// Weekly recap (server: recap.py): XP, streak, plan adherence, badges, best workout and
// next week's focus, for any of the last 8 weeks.
import { useEffect, useState } from 'react'
import { Award, CalendarCheck, ChevronLeft, ChevronRight, Flame, MessageCircle, Trophy, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, Screen } from '@/components/plan/ui'
import { RabbitLogo } from '@/components/RabbitLogo'
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
  useEffect(() => {
    let live = true
    setError(null)
    getRecap(week).then((x) => { if (live) setR(x) }, (e) => { if (live) setError((e as Error).message) })
    return () => { live = false }
  }, [week])
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
            className="inline-flex items-center gap-0.5 text-[0.6471rem] text-(--text-muted) disabled:opacity-30">
            <ChevronLeft className="size-3.5" /> Earlier
          </button>
          <span className="text-[0.6471rem] text-(--text-muted)">{r?.current ? 'This week' : r ? 'Week in review' : ''}</span>
          <button type="button" disabled={!canNext} onClick={() => next && setWeek(next)} aria-label="Next week"
            className="inline-flex items-center gap-0.5 text-[0.6471rem] text-(--text-muted) disabled:opacity-30">
            Later <ChevronRight className="size-3.5" />
          </button>
        </div>
      }>
      {error && <p className="px-1 text-[0.8235rem] text-(--danger)" role="alert">{error}</p>}
      {!error && loading && (
        <div className="flex justify-center py-16" role="status" aria-label="Loading recap">
          <RabbitLogo size={40} thinking />
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
  return (
    <>
      <div className="celebrate flex flex-col items-center gap-1 rounded-2xl border border-(--border) bg-(--bg-surface) px-4 py-5 text-center">
        <p className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--accent)">XP earned</p>
        <p className="font-display text-[3rem] leading-none text-(--brand)">+{r.xp.toLocaleString()}</p>
        <p className="mt-1 text-[0.7059rem] text-(--text-muted)">
          Level {r.level.level} {r.level.name} · {r.level.to_next.toLocaleString()} XP to level {r.level.level + 1}
        </p>
        <span className="mt-1.5 block h-1.5 w-full max-w-60 overflow-hidden rounded-full bg-(--bg-elevated)">
          <span className="block h-full rounded-full bg-(--accent)" style={{ width: `${pct}%` }} />
        </span>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <Tile label="day streak" value={String(r.streak)}
          icon={<Flame className={cn('size-5', r.streak ? 'text-(--accent)' : 'text-(--text-muted)')} />} />
        <Tile label={`workout${r.workouts === 1 ? '' : 's'} · ${r.hours} h`} value={String(r.workouts)}
          icon={<CalendarCheck className="size-5 text-(--accent)" />} />
        {ad && ad.planned > 0 ? (
          <Tile label="plan sessions" value={`${ad.pct ?? 0}%`} icon={<WeekRing done={ad.done} target={ad.planned} size={34} />} />
        ) : (
          <Tile label="active days" value={`${r.active_days}/7`} icon={<WeekRing done={r.active_days} target={7} size={34} />} />
        )}
      </div>

      {r.badges.length > 0 && (
        <Card>
          <div className="flex flex-col gap-2 px-4 py-3">
            <Label>Badges earned</Label>
            <div className="flex flex-wrap gap-2">
              {r.badges.map((b) => (
                <span key={b.id} title={b.description}
                  className="inline-flex items-center gap-1.5 rounded-full border border-(--accent)/40 bg-(--accent-subtle) px-2.5 py-1 text-[0.7059rem] font-medium text-(--accent)">
                  <Award className="size-3.5" />{b.title}
                </span>
              ))}
            </div>
          </div>
        </Card>
      )}

      {r.best && (
        <Card>
          <div className="flex items-center gap-3 px-4 py-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-(--brand) text-white"><Trophy className="size-4" /></span>
            <span className="min-w-0 flex-1">
              <Label>Best workout</Label>
              <span className="block truncate text-[0.8235rem] font-medium text-(--text)">{r.best.name}</span>
              <span className="block text-[0.6471rem] text-(--text-muted)">
                {fmtDay(r.best.date, { weekday: 'long' })} · {r.best.minutes} min{r.best.km ? ` · ${r.best.km} km` : ''}
              </span>
            </span>
          </div>
        </Card>
      )}
      {!r.workouts && (
        <p className="px-1 text-center text-[0.7647rem] text-(--text-muted)">A quiet week. Every streak starts with one workout.</p>
      )}

      <Card>
        <div className="flex flex-col gap-2 px-4 py-3">
          <Label>Next week{nw.phase ? ` · ${nw.phase}${nw.recovery ? ' (recovery)' : ''}` : ''}</Label>
          {nw.focus && <p className="text-[0.7647rem] leading-snug text-(--text)">{nw.focus}</p>}
          {nw.sessions.length > 0 ? (
            <ul className="flex flex-col divide-y divide-(--border)">
              {nw.sessions.map((s) => (
                <li key={`${s.date}-${s.title}`} className="flex items-baseline gap-2 py-1.5 text-[0.7647rem]">
                  <span className="w-9 shrink-0 font-mono text-[0.5882rem] uppercase text-(--text-muted)">{fmtDay(s.date, { weekday: 'short' })}</span>
                  <span className="min-w-0 flex-1 truncate text-(--text)">{s.title}</span>
                  {s.minutes ? <span className="shrink-0 text-[0.6471rem] text-(--text-muted)">{s.minutes}′</span> : null}
                </li>
              ))}
            </ul>
          ) : nw.target ? <p className="text-[0.7647rem] leading-snug text-(--text)">{nw.target}</p> : null}
          <Button variant="default" className="mt-1 h-9 gap-1.5"
            onClick={() => onAsk('About next week: ')}>
            <MessageCircle className="size-4" /> Ask Rabbit about next week
          </Button>
        </div>
      </Card>
    </>
  )
}

function Tile({ label, value, icon }: { label: string; value: string; icon: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-1 rounded-xl border border-(--border) bg-(--bg-surface) px-2 py-3 text-center">
      {icon}
      <span className="font-display text-[1.3rem] leading-none text-(--text)">{value}</span>
      <span className="text-[0.5882rem] leading-tight text-(--text-muted)">{label}</span>
    </div>
  )
}

function Label({ children }: { children: React.ReactNode }) {
  return <span className="block font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">{children}</span>
}

/** Small home pill: Sunday noon through Monday, dismissible per week. */
export function RecapPill({ onOpen, onDismiss }: { onOpen: () => void; onDismiss: () => void }) {
  return (
    <div className="coach-pins mx-4 mt-2.5 flex shrink-0 items-center gap-2 rounded-full border border-(--accent)/30 bg-(--accent-subtle) py-1 pl-3 pr-1 text-[0.7059rem] text-(--accent)">
      <button type="button" onClick={onOpen} className="flex min-w-0 flex-1 items-center gap-1.5 text-left font-medium">
        <CalendarCheck className="size-3.5 shrink-0" /><span className="truncate">Your week in review</span>
        <ChevronRight className="size-3.5 shrink-0" />
      </button>
      <button type="button" onClick={onDismiss} aria-label="Dismiss weekly recap" className="rounded-full p-1 text-(--text-muted)">
        <X className="size-3.5" />
      </button>
    </div>
  )
}
