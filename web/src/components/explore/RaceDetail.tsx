// One race from Explore: what it is, its distances, and what to do next: add it to your
// races (then see your race fit), register on the race's own site, or ask Rabbit about it.
// "Your estimated finish" (GET /api/predict, asked lazily; hidden on 404/errors) follows the
// distance you pick. Popular races without a
// confirmed date say "Usually in <month>" and can't be added until you check the date.
import { useState } from 'react'
import { celebrate } from '@/components/fx'
import { CalendarPlus, Check, ExternalLink, Gauge, Globe, MessageCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, Field, Screen } from '@/components/plan/ui'
import { RaceFitScreen } from '@/components/events/RaceFitScreen'
import { cn } from '@/lib/utils'
import { countdown } from '@/lib/events'
import { addRace, distanceText, feeFrom, placeOf, raceDate, type ExploreRace } from '@/lib/explore'
import { CATEGORY_ICON, HINT_CLS } from './icons'
import type { RaceX } from '@/lib/explore2'
import { FinishChip } from './Estimate'
import { whenText } from './ForYou'

export function RaceDetail({ race, imperial, onClose, onAsk, onAdded }: {
  race: ExploreRace
  imperial: boolean
  onClose: () => void
  onAsk: (text: string) => void
  onAdded?: () => void
}) {
  const [closing, setClosing] = useState(false)
  const [pick, setPick] = useState<number | null>(race.events.length === 1 ? 0 : null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [added, setAdded] = useState<{ id: string; already: boolean } | null>(null)
  const [fit, setFit] = useState(false)
  const [logoOk, setLogoOk] = useState(true)
  const close = () => { setClosing(true); setTimeout(onClose, 200) }
  const Icon = CATEGORY_ICON[race.types[0] ?? 'other']
  const place = placeOf(race)
  const fee = feeFrom(race)
  const register = race.url ?? race.website
  const needsPick = race.events.length > 1 && pick === null
  const rx = race as RaceX
  const undated = !!rx.check_dates || !race.date
  const ev = race.events[pick ?? 0]

  async function add() {
    setBusy(true); setError(null)
    try {
      const r = await addRace(race, race.events.length ? pick ?? 0 : null)
      setAdded({ id: r.event.id, already: r.already })
      if (!r.already) celebrate({ x: window.innerWidth / 2, y: window.innerHeight * 0.7 }, 'race')
      onAdded?.()
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }

  const ask = () => onAsk(`Tell me about the ${race.name}${undated ? '' : ` on ${raceDate(race.date)}`}${place ? ` in ${place}` : ''}: `
    + 'is it a good fit for me and how should I prepare?')

  return (
    <>
      <Screen title={race.name} subtitle={undated || race.ongoing ? whenText(rx) : `${raceDate(race.date)} · ${countdown(race.date)}`} closing={closing} onClose={close} onBack={close}
        footer={added ? (
          <Button variant="primary" className="h-11 flex-1 gap-1.5 text-[0.8235rem]" onClick={() => setFit(true)}>
            <Gauge className="size-4" /> See race fit
          </Button>
        ) : (
          <Button variant="primary" className="h-11 flex-1 gap-1.5 text-[0.8235rem]" loading={busy} disabled={needsPick || undated}
            onClick={() => void add()}>
            <CalendarPlus className="size-4" /> {undated ? 'Check the date on the official site' : needsPick ? 'Pick a distance to add' : 'Add to my races'}
          </Button>
        )}>
        <div className="flex items-center gap-3 px-1">
          {race.logo && logoOk ? (
            <img src={race.logo} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setLogoOk(false)}
              className="size-14 shrink-0 rounded-xl border border-(--border) bg-white object-contain p-1" />
          ) : (
            <span className="flex size-14 shrink-0 items-center justify-center rounded-xl bg-(--accent-subtle) text-(--accent)">
              <Icon className="size-6" />
            </span>
          )}
          <div className="min-w-0 flex-1">
            <p className="text-[0.9412rem] font-medium leading-snug text-(--text)">{undated || race.ongoing ? whenText(rx) : raceDate(race.date)}</p>
            {place && <p className="text-[0.7647rem] text-(--text-muted)">{place}</p>}
            <div className="mt-1 flex flex-wrap gap-1">
              {race.registration_open && (
                <span className="rounded-full bg-(--accent-subtle) px-2 py-0.5 text-[0.6471rem] font-semibold text-(--accent)">Registration open</span>
              )}
              {undated && (
                <span className="rounded-full bg-(--warning-subtle) px-2 py-0.5 text-[0.6471rem] font-medium text-(--warning-text)">Check dates</span>
              )}
              {race.source === 'web' && (
                <span className="rounded-full bg-(--bg-elevated) px-2 py-0.5 text-[0.6471rem] text-(--text-secondary)">Found online</span>
              )}
              {(race.hints ?? []).map((h) => (
                <span key={h.id} className={cn('rounded-full px-2 py-0.5 text-[0.6471rem] font-medium', HINT_CLS[h.tone])}>{h.label}</span>
              ))}
            </div>
          </div>
        </div>

        {added && (
          <div className="flex items-start gap-2.5 rounded-xl border border-(--accent)/30 bg-(--accent-subtle) px-3.5 py-3 text-[0.7647rem] leading-snug text-(--accent)">
            <Check className="mt-px size-4 shrink-0" />
            <span>{added.already ? "It's already in your races." : 'Added to your races as a training race. Change its priority any time in Events.'}</span>
          </div>
        )}

        {rx.why && <p className="px-1 text-[0.8235rem] font-medium leading-snug text-(--text)">{rx.why}</p>}
        <FinishChip type={ev?.type} distanceKm={ev?.distance_km} date={undated ? undefined : ev?.date || race.date} />

        {race.summary && <p className="px-1 text-[0.8235rem] leading-relaxed text-(--text-secondary)">{race.summary}</p>}

        {race.events.length > 0 && (
          <Card>
            <Field label={race.events.length > 1 ? (added ? 'Distances' : 'Pick your distance') : 'Distance'}
              hint={fee ? `Entry from ${fee} (before fees).` : undefined}>
              <div className="flex flex-col gap-1.5">
                {race.events.map((e, i) => {
                  const selectable = race.events.length > 1 && !added
                  const on = pick === i
                  const body = (
                    <>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[0.8235rem] font-medium text-(--text)">{e.name}</span>
                        <span className="block truncate text-[0.7059rem] text-(--text-muted)">
                          {[distanceText(e, imperial), e.start_time ? `starts ${e.start_time}` : '', e.date && e.date !== race.date ? raceDate(e.date) : '']
                            .filter(Boolean).join(' · ')}
                        </span>
                      </span>
                      {e.fee_from && <span className="shrink-0 text-[0.7059rem] text-(--text-secondary)">{e.fee_from}</span>}
                    </>
                  )
                  return selectable ? (
                    <button key={i} type="button" aria-pressed={on} onClick={() => setPick(i)}
                      className={cn('flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left transition-colors',
                        on ? 'border-(--accent) bg-(--accent-subtle)' : 'border-(--border) active:bg-(--bg-inset)')}>
                      {body}
                    </button>
                  ) : (
                    <div key={i} className="flex items-center gap-3 rounded-lg bg-(--bg-inset) px-3 py-2">{body}</div>
                  )
                })}
              </div>
            </Field>
          </Card>
        )}

        <div className="flex flex-col gap-2">
          {register && (
            <a href={register} target="_blank" rel="noopener noreferrer"
              className="inline-flex h-11 items-center justify-center gap-1.5 rounded-(--radius) border border-black/15 bg-background text-[0.8235rem] font-medium text-foreground active:scale-[0.97]">
              {race.source === 'web' ? 'Official site' : 'Register'} <ExternalLink className="size-4" />
            </a>
          )}
          {race.website && race.url && race.website !== race.url && (
            <a href={race.website} target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center justify-center gap-1.5 py-1 text-[0.7647rem] text-(--accent) underline-offset-2 hover:underline">
              <Globe className="size-3.5" /> Race website
            </a>
          )}
          <Button variant="default" className="h-11 gap-1.5 text-[0.8235rem]" onClick={ask}>
            <MessageCircle className="size-4" /> Ask Rabbit about this race
          </Button>
        </div>
        {error && <p className="px-1 text-[0.7647rem] text-(--danger)" role="alert">{error}</p>}
      </Screen>
      {fit && added && <RaceFitScreen eventId={added.id} onClose={() => setFit(false)} />}
    </>
  )
}
