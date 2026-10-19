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
  if (!data) return <div className="skeleton h-[220px] rounded-xl" aria-hidden />
  if (!data.available && data.days.every((d) => d.sessions.length === 0)) return null
  const imperial = data.units !== 'metric'
  return (
    <div role="group" aria-label="Next 3 days" className="settings-group flex flex-col overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface) shadow-[var(--shadow-sm)]">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 border-b border-(--border) px-4 py-3">
        <h3 className="m-0 text-body-lg font-semibold text-(--text)">Next 3 days</h3>
        {data.place && <span className="text-small text-(--text-muted)">Weather for {data.place}</span>}
      </div>
      <ul className="flex flex-col">
        {data.days.map((d, i) => {
          const w = d.weather
          const WI = wxIcon(w?.code)
          const day = label(d.date, data.today, i)
          return (
            <li key={d.date} className={cn('flex flex-col px-4 py-3', i > 0 && 'border-t border-(--border)')}>
              {/* The day and its weather on one line; tap for the day in Schedule. */}
              <button type="button" onClick={() => openPlanDay(d.date)}
                aria-label={`${day}${w ? `: ${w.summary}, high ${fmtTemp(w.hi_c, imperial)}, low ${fmtTemp(w.lo_c, imperial)}${w.rain_pct ? `, ${w.rain_pct}% rain` : ''}` : ''}. Open this day`}
                className="-mx-1 flex min-h-11 items-center gap-2 rounded-lg px-1 text-left active:bg-(--bg-inset)">
                <span className="text-body font-semibold text-(--text)">{day}</span>
                {w ? (
                  <span className="ml-auto flex items-center gap-1.5 text-small text-(--text-secondary)" aria-hidden>
                    <WI className="size-5 text-(--accent)" />{fmtTemp(w.hi_c, imperial)}<span className="text-(--text-muted)">/ {fmtTemp(w.lo_c, imperial)}</span>
                    {w.rain_pct != null && w.rain_pct >= 30 && <span className="text-(--text-muted)">· {w.rain_pct}% rain</span>}
                  </span>
                ) : <span className="ml-auto text-small text-(--text-muted)" aria-hidden>No forecast</span>}
              </button>
              {d.sessions.length === 0 && <p className="m-0 pb-1 text-body text-(--text-muted)">{data.has_plan ? 'Rest day' : w?.summary ?? ''}</p>}
              {d.sessions.map((s) => {
                const I = SPORT_ICON[s.sport as Sport] ?? SPORT_ICON.other
                const warn = s.badges.filter((b) => b !== 'rain' || s.badges.length === 1).slice(0, 2)
                const when = [s.time ? fmtHour(s.time, imperial) : null, s.minutes ? fmtDuration(s.minutes) : null].filter(Boolean).join(' · ')
                return (
                  <button key={s.id} type="button" onClick={() => openWorkout(s.id, d.date)}
                    aria-label={`${s.title}${s.time ? ` at ${fmtHour(s.time, imperial)}` : ''}${s.minutes ? `, ${fmtDuration(s.minutes)}` : ''}${warn.length ? `. Weather: ${warn.map((b) => BADGE[b].label).join(', ')}` : ''}. Open workout`}
                    className="-mx-1 flex min-h-12 items-center gap-3 rounded-lg px-1 py-1.5 text-left active:bg-(--bg-inset)">
                    <I className="size-5 shrink-0 text-(--text-secondary)" aria-hidden />
                    <span className="min-w-0 flex-1" aria-hidden>
                      <span className="block text-body leading-snug text-(--text)">{s.title}</span>
                      {(when || warn.length > 0) && (
                        <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-meta text-(--text-muted)">
                          {when && <span>{when}</span>}
                          {warn.map((b) => {
                            const B = BADGE[b]
                            return (
                              <span key={b} className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-caption font-medium',
                                B.warn ? 'bg-(--warning-subtle) text-(--warning-text)' : 'bg-(--bg-inset) text-(--text-secondary)')}>
                                <B.icon className="size-3.5" />{b === 'heat' && s.pct ? `+${Math.round(s.pct)}%` : B.label}
                              </span>
                            )
                          })}
                        </span>
                      )}
                    </span>
                    <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
                  </button>
                )
              })}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
