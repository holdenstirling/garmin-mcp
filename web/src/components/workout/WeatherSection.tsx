// The workout page's "Weather" section (server: weather_web.py): an hourly strip around the
// planned time, what the weather changes (paces adjusted for heat / altitude / wind, labelled
// against the plan's), safety notes and the best time to go. Shown for today and the next 2 days.
import { useEffect, useState } from 'react'
import { Clock, CloudSun, TriangleAlert } from 'lucide-react'
import { paceText } from '@/components/plan/PlanCalendar'
import { RabbitInline } from '@/components/chat/RabbitText'
import { cn } from '@/lib/utils'
import { BADGE, fmtHour, fmtTemp, fmtWind, getSessionWeather, wxIcon, type SessionWeather } from '@/lib/weather'

export function WeatherSection({ sessionId, imperial, onShown }: { sessionId: string; imperial: boolean; onShown?: (shown: boolean) => void }) {
  const [w, setW] = useState<SessionWeather | null>(null)
  useEffect(() => {
    let live = true
    getSessionWeather(sessionId).then((r) => { if (live) { setW(r); onShown?.(r.available) } }, () => { if (live) onShown?.(false) })
    return () => { live = false }
  }, [sessionId]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!w || !w.available) return null
  const a = w.adjust
  const u = imperial ? 'mi' : 'km'
  const hot = a.badges.length > 0
  const Icon = wxIcon(w.day?.code)
  return (
    <section aria-label="Weather" className="flex flex-col gap-3 rounded-xl border border-(--border) bg-(--bg-surface) p-4">
      <div className="flex items-center gap-2">
        <h4 className="font-sans flex flex-1 items-center gap-1.5 text-caption font-semibold text-(--text-muted)">
          <CloudSun className="size-4" aria-hidden />Weather{w.place ? ` · ${w.place}` : ''}
        </h4>
        {w.day && (
          <span className="flex items-center gap-1 text-small text-(--text-secondary)">
            <Icon className="size-5" aria-hidden />{fmtTemp(w.day.hi_c, imperial)} / {fmtTemp(w.day.lo_c, imperial)}
          </span>
        )}
      </div>

      {w.strip.length > 0 && (
        <ol className="no-scrollbar -mx-1 flex gap-1 overflow-x-auto px-1" aria-label="Hourly forecast">
          {w.strip.map((h) => {
            const HI = wxIcon(h.code)
            const planned = w.planned_time && h.t.slice(11, 13) === w.planned_time.slice(0, 2)
            return (
              <li key={h.t} className={cn('flex min-w-14 flex-1 flex-col items-center gap-0.5 rounded-lg px-1.5 py-2 text-center',
                planned ? 'bg-(--accent-subtle) ring-1 ring-(--accent)' : 'bg-(--bg-inset)')}
                aria-label={`${fmtHour(h.t.slice(11, 16), imperial)}: ${fmtTemp(h.temp_c, imperial)}, ${h.summary}${h.rain_pct ? `, ${h.rain_pct}% rain` : ''}${planned ? ', your start' : ''}`}>
                <span className="text-caption text-(--text-muted)" aria-hidden>{fmtHour(h.t.slice(11, 16), imperial)}</span>
                <HI className="size-4 text-(--text-secondary)" aria-hidden />
                <span className="font-mono text-small font-semibold tabular-nums text-(--text)" aria-hidden>{fmtTemp(h.temp_c, imperial)}</span>
                <span className="text-caption text-(--text-muted)" aria-hidden>{h.rain_pct != null && h.rain_pct >= 20 ? `${h.rain_pct}%` : fmtWind(h.wind_kmh, imperial).replace(' ', '')}</span>
              </li>
            )
          })}
        </ol>
      )}

      {hot && (
        <div className="flex flex-wrap gap-1.5">
          {a.badges.map((b) => {
            const B = BADGE[b]
            return (
              <span key={b} className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-meta font-medium',
                B.warn ? 'bg-(--warning-subtle) text-(--warning-text)' : 'bg-(--bg-inset) text-(--text-secondary)')}>
                <B.icon className="size-3.5" aria-hidden />{B.label}
              </span>
            )
          })}
        </div>
      )}

      {a.pace && w.planned_pace && (
        <div className="flex items-center justify-between gap-3 rounded-lg bg-(--bg-inset) px-3 py-2">
          <span className="min-w-0 text-small leading-snug text-(--text-secondary)">
            <span className="block font-semibold text-(--text)">Today's pace</span>
            Adjusted +{a.pct}% for the weather
          </span>
          <span className="shrink-0 text-right">
            <b className="block whitespace-nowrap font-mono text-body tabular-nums text-(--text)">{paceText(a.pace[0], imperial)}–{paceText(a.pace[1], imperial)}/{u}</b>
            <span className="block whitespace-nowrap font-mono text-caption tabular-nums text-(--text-muted)">
              <span className="sr-only">Planned </span><s>{paceText(w.planned_pace.fast, imperial)}–{paceText(w.planned_pace.slow, imperial)}/{u}</s>
            </span>
          </span>
        </div>
      )}

      {a.note && <p className="m-0 text-body leading-snug text-(--text)"><RabbitInline text={a.note} /></p>}
      {a.safety.map((s) => (
        <p key={s} className="m-0 flex gap-1.5 text-small leading-snug text-(--warning-text)">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />{s}
        </p>
      ))}
      {w.best && (w.best.better || !w.planned_time) && (
        <p className="m-0 flex gap-1.5 text-small leading-snug text-(--text-secondary)">
          <Clock className="mt-0.5 size-4 shrink-0 text-(--accent)" aria-hidden />
          <span><b className="font-semibold text-(--text)">Best time to go: {fmtHour(w.best.start, imperial)}–{fmtHour(w.best.end, imperial)}</b> ({w.best.why}).</span>
        </p>
      )}
      {!hot && !a.note && !a.safety.length && <p className="m-0 text-small text-(--text-muted)">Good conditions: train as planned.</p>}
    </section>
  )
}
