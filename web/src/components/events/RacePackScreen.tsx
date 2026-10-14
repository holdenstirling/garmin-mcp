// Everything for race week on one page. Gear checkboxes are remembered on this device.
import { useEffect, useState } from 'react'
import { CheckSquare, CloudSun, Gauge, ListChecks, Square, Utensils } from 'lucide-react'
import { RabbitLogo } from '@/components/RabbitLogo'
import { Card, Field, Screen } from '@/components/plan/ui'
import { fmtMin } from '@/lib/plan'
import { getRacePack, type RacePack } from '@/lib/racepack'
import { InfoBlock } from './EventForm'
import { RaceFitScreen } from './RaceFitScreen'

const cToF = (c: number) => Math.round(c * 9 / 5 + 32)

function readGear(key: string): string[] | null {
  try {
    const v: unknown = JSON.parse(localStorage.getItem(key) ?? 'null')
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : null
  } catch { return null }
}

export function RacePackScreen({ eventId, imperial, onClose }: { eventId?: string; imperial: boolean; onClose: () => void }) {
  const [p, setP] = useState<RacePack | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [closing, setClosing] = useState(false)
  const [fit, setFit] = useState(false)
  // Gear checks are stored per event, under the event the pack resolved to (also when it
  // was opened as "the main event"), so they follow that race if the main one changes.
  const key = p ? `rabbit.gear.${p.event.id}` : null
  const [checked, setChecked] = useState<string[] | null>(null) // null until the pack loads
  useEffect(() => { getRacePack(eventId).then(setP, (e) => setError((e as Error).message)) }, [eventId])
  useEffect(() => {
    if (!key) return
    // Earlier versions kept the main event's checks under "main".
    setChecked(readGear(key) ?? (eventId ? null : readGear('rabbit.gear.main')) ?? [])
  }, [key, eventId])
  useEffect(() => {
    if (!key || !checked) return
    try { localStorage.setItem(key, JSON.stringify(checked)) } catch { /* ignore */ }
  }, [checked, key])
  const done = checked ?? []
  const close = () => { setClosing(true); setTimeout(onClose, 200) }
  const temp = (c: number | null) => c == null ? '–' : imperial ? `${cToF(c)}°F` : `${Math.round(c)}°C`

  return (
    <Screen title="Race-week pack" subtitle={p ? `${p.event.name} · ${p.days_out > 0 ? `${p.days_out} days to go` : p.days_out === 0 ? 'Race day!' : 'Done'}` : undefined}
      closing={closing} onClose={close}
      headerExtra={p ? (
        <div className="mx-auto mt-2 flex max-w-xl justify-center">
          <button type="button" onClick={() => setFit(true)}
            className="inline-flex items-center gap-1.5 rounded-full bg-(--accent-subtle) px-3 py-1 text-[0.7059rem] font-medium text-(--accent)">
            <Gauge className="size-3.5" /> Race fit and strategy
          </button>
        </div>
      ) : undefined}>
      {!p && !error && <div className="flex justify-center py-16"><RabbitLogo size={56} thinking className="text-(--brand) opacity-60" /></div>}
      {error && <p className="px-1 text-[0.8235rem] text-(--danger)">{error}</p>}
      {p && (
        <>
          <Card>
            <Field label="Pacing by leg">
              <div className="flex flex-col gap-3">
                {p.pacing.map((x) => (
                  <div key={x.leg}>
                    <p className="flex items-baseline gap-2"><Gauge className="size-3.5 shrink-0 translate-y-0.5 text-(--accent)" />
                      <span className="text-[0.8824rem] font-medium text-(--text)">{x.leg}</span>
                      <span className="ml-auto font-display text-[1rem] text-(--accent)">{x.target}</span></p>
                    <p className="pl-5.5 text-[0.7059rem] leading-snug text-(--text-muted)">{x.detail}</p>
                  </div>
                ))}
              </div>
            </Field>
          </Card>
          <Card>
            <Field label="Fueling plan">
              <p className="flex items-center gap-2 text-[0.8235rem] text-(--text)"><Utensils className="size-4 text-(--accent)" />
                {p.fueling.carbs_g_per_h ? <><b className="font-display text-[1.1rem]">{p.fueling.carbs_g_per_h}</b> g carbs/h · about {p.fueling.total_carbs_g} g over ~{fmtMin(p.fueling.expected_hours * 60)}</> : 'Water and a good breakfast are enough.'}
              </p>
              {p.fueling.carbs_g_per_h > 0 && <p className="text-[0.7059rem] text-(--text-muted)">Fluid {p.fueling.fluid_ml_per_h} ml/h · sodium {p.fueling.sodium_mg_per_h} mg/h</p>}
              <ul className="mt-1 flex flex-col gap-1 text-[0.7647rem] leading-snug text-(--text-secondary)">{p.fueling.steps.map((s) => <li key={s}>• {s}</li>)}</ul>
            </Field>
          </Card>
          <Card>
            <Field label="Weather" hint={p.weather ? 'Forecast from Open-Meteo; check again the day before.' : 'A live forecast appears here 2 weeks out.'}>
              {p.weather ? (
                <p className="flex items-center gap-2 text-[0.8235rem] text-(--text)"><CloudSun className="size-4 text-(--accent)" />
                  {p.weather.place}: {temp(p.weather.low_c)} – {temp(p.weather.high_c)}, rain {p.weather.rain_pct ?? '–'}%, wind {p.weather.wind_kmh != null ? (imperial ? `${Math.round(p.weather.wind_kmh / 1.609)} mph` : `${Math.round(p.weather.wind_kmh)} km/h`) : '–'}
                </p>
              ) : p.info.typical_weather ? <p className="text-[0.8235rem] text-(--text)">Typical: {p.info.typical_weather}</p> : null}
              {p.weather_tips.map((t) => <p key={t} className="text-[0.7647rem] text-(--warning)">{t}</p>)}
            </Field>
          </Card>
          <Card>
            <Field label={`Gear checklist · ${done.filter((c) => p.gear.includes(c)).length}/${p.gear.length}`}>
              <div className="flex flex-col">
                {p.gear.map((g) => {
                  const on = done.includes(g)
                  return (
                    <button key={g} type="button"
                      onClick={() => setChecked((c) => on ? (c ?? []).filter((x) => x !== g) : [...(c ?? []), g])}
                      className="flex items-center gap-2.5 py-1.5 text-left text-[0.8235rem]">
                      {on ? <CheckSquare className="size-4 shrink-0 text-(--accent)" /> : <Square className="size-4 shrink-0 text-(--text-muted)" />}
                      <span className={on ? 'text-(--text-muted) line-through' : 'text-(--text)'}>{g}</span>
                    </button>
                  )
                })}
              </div>
            </Field>
          </Card>
          <Card>
            <Field label="Final week">
              <ul className="flex flex-col gap-2">
                {p.timeline.map((t) => (
                  <li key={t.when} className="flex gap-3 text-[0.7647rem]"><ListChecks className="mt-0.5 size-3.5 shrink-0 text-(--accent)" />
                    <span><b className="text-(--text)">{t.when}:</b> <span className="text-(--text-secondary)">{t.what}</span></span></li>
                ))}
              </ul>
              {p.week.length > 0 && (
                <div className="mt-2 border-t border-(--border) pt-2">
                  {p.week.map((s) => (
                    <p key={`${s.date}-${s.title}`} className="flex gap-2 text-[0.7647rem]"><span className="w-20 shrink-0 text-(--text-muted)">{new Date(`${s.date}T12:00:00`).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })}</span>
                      <span className="text-(--text)">{s.title}{s.minutes ? ` · ${fmtMin(s.minutes)}` : ''}</span></p>
                  ))}
                </div>
              )}
            </Field>
          </Card>
          {Object.keys(p.info).length > 0 && <Card className="p-4"><InfoBlock info={p.info} /></Card>}
          {fit && <RaceFitScreen eventId={p.event.id} onClose={() => setFit(false)} />}
        </>
      )}
    </Screen>
  )
}
