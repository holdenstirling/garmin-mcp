// Home "Next 3 days" (server: weather_web.py next_days): today, tomorrow and the day after, each
// with the day's weather (icon, high/low, rain chance) and the planned workouts with a heat /
// wind / storm badge when the weather changes them. Tap a workout for its page (with the full
// weather section and adjusted paces); tap the day for the Schedule day.
import { useEffect, useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { SPORT_ICON } from '@/components/plan/PlanParts'
import type { Sport } from '@/lib/api'
import { fmtDay } from '@/components/plan/PlanParts'
import { fmtDuration } from '@/lib/format'
import { PLAN_CHANGED_EVENT, openPlanDay } from '@/lib/plancal'
import { openWorkout } from '@/lib/workoutnav'
import { cn } from '@/lib/utils'
import { BADGE, fmtHour, fmtTemp, getNextDays, wxIcon, type NextDays as Data } from '@/lib/weather'

const label = (date: string, today: string, i: number) =>
  i === 0 || date === today ? 'Today' : i === 1 ? 'Tomorrow' : fmtDay(date, { weekday: 'long' })

export function NextDays({ refreshKey }: { refreshKey?: number }) {
  const [data, setData] = useState<Data | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let live = true
    const load = (fresh: boolean) => getNextDays(fresh).then((d) => { if (live) { setData(d); setFailed(false) } }, () => { if (live) setFailed(true) })
    void load(!!refreshKey)
    const onChange = () => { void load(true) }
    window.addEventListener(PLAN_CHANGED_EVENT, onChange)
    return () => { live = false; window.removeEventListener(PLAN_CHANGED_EVENT, onChange) }
  }, [refreshKey])
  if (failed) return null
  if (!data) return <div className="skeleton h-[188px] rounded-xl" aria-hidden />
  if (!data.available && data.days.every((d) => d.sessions.length === 0)) return null
  const imperial = data.units !== 'metric'
  return (
    <section aria-label="Next 3 days" className="flex flex-col rounded-xl border border-(--border) bg-(--bg-surface)">
      <h2 className="font-sans flex items-center justify-between px-3.5 pt-3 pb-1 text-caption font-semibold text-(--text-muted)">
        <span>Next 3 days</span>
        {data.place && <span className="truncate pl-2 font-sans normal-case tracking-normal">{data.place}</span>}
      </h2>
      <ul className="flex flex-col">
        {data.days.map((d, i) => {
          const w = d.weather
          const WI = wxIcon(w?.code)
          return (
            <li key={d.date} className={cn('flex gap-3 px-3.5 py-2', i > 0 && 'border-t border-(--border)')}>
              <button type="button" onClick={() => openPlanDay(d.date)}
                aria-label={`${label(d.date, data.today, i)}${w ? `: ${w.summary}, high ${fmtTemp(w.hi_c, imperial)}, low ${fmtTemp(w.lo_c, imperial)}${w.rain_pct ? `, ${w.rain_pct}% rain` : ''}` : ''}. Open this day`}
                className="flex w-[4.75rem] shrink-0 flex-col items-start gap-0.5 rounded-lg py-1 text-left active:bg-(--bg-inset)">
                <span className="text-small font-semibold text-(--text)">{label(d.date, data.today, i)}</span>
                {w ? (
                  <span className="flex items-center gap-1 text-meta text-(--text-secondary)" aria-hidden>
                    <WI className="size-4 text-(--accent)" />{fmtTemp(w.hi_c, imperial)}<span className="text-(--text-muted)">/{fmtTemp(w.lo_c, imperial)}</span>
                  </span>
                ) : <span className="text-caption text-(--text-muted)" aria-hidden>No forecast</span>}
                {w?.rain_pct != null && w.rain_pct >= 30 && <span className="text-caption text-(--text-muted)" aria-hidden>{w.rain_pct}% rain</span>}
              </button>
              <div className="flex min-w-0 flex-1 flex-col justify-center gap-1">
                {d.sessions.length === 0 && <span className="py-2 text-small text-(--text-muted)">{data.has_plan ? 'Rest day' : w?.summary ?? ''}</span>}
                {d.sessions.map((s) => {
                  const I = SPORT_ICON[s.sport as Sport] ?? SPORT_ICON.other
                  const warn = s.badges.filter((b) => b !== 'rain' || s.badges.length === 1).slice(0, 2)
                  return (
                    <button key={s.id} type="button" onClick={() => openWorkout(s.id, d.date)}
                      aria-label={`${s.title}${s.time ? ` at ${fmtHour(s.time, imperial)}` : ''}${s.minutes ? `, ${fmtDuration(s.minutes)}` : ''}${warn.length ? `. Weather: ${warn.map((b) => BADGE[b].label).join(', ')}` : ''}. Open workout`}
                      className="flex min-h-11 w-full items-center gap-2 rounded-lg text-left active:bg-(--bg-inset)">
                      <I className="size-5 shrink-0 text-(--text-secondary)" aria-hidden />
                      <span className="min-w-0 flex-1" aria-hidden>
                        <span className="block truncate text-body text-(--text)">{s.title}</span>
                        <span className="block truncate text-caption text-(--text-muted)">
                          {[s.time ? fmtHour(s.time, imperial) : null, s.minutes ? fmtDuration(s.minutes) : null].filter(Boolean).join(' · ')}
                        </span>
                      </span>
                      {warn.map((b) => {
                        const B = BADGE[b]
                        return (
                          <span key={b} aria-hidden className={cn('inline-flex shrink-0 items-center gap-0.5 rounded-full px-1.5 py-0.5 text-caption font-medium',
                            B.warn ? 'bg-(--warning-subtle) text-(--warning-text)' : 'bg-(--bg-inset) text-(--text-secondary)')}>
                            <B.icon className="size-3" />{b === 'heat' && s.pct ? `+${Math.round(s.pct)}%` : B.label}
                          </span>
                        )
                      })}
                      <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
                    </button>
                  )
                })}
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
