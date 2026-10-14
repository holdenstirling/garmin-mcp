// Explore -> Near you -> Local: recurring run clubs, group rides, social leagues, swims,
// climbing meetups and outdoor yoga in your city. Found on the web by Rabbit once a week per
// city (shared by everyone there); only "City, ST" is ever sent to the model.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Bike, Dumbbell, ExternalLink, Flower2, Footprints, MessageCircle, Mountain, Volleyball, Waves } from 'lucide-react'
import { ErrorState } from '@/components/ui/ErrorState'
import { RabbitLoader } from '@/components/RabbitLoader'
import { Chip } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import { getLocal, type LocalActivity, type LocalCategory, type LocalResult } from '@/lib/explore2'
import { LocationPrompt } from './LocationPrompt'

const ICON: Record<LocalCategory, typeof Bike> = {
  run: Footprints, ride: Bike, swim: Waves, social_sports: Volleyball, yoga: Flower2, climb: Mountain, other: Dumbbell,
}
const ORDER: LocalCategory[] = ['run', 'ride', 'swim', 'social_sports', 'yoga', 'climb']
const LOOKING = ['Asking around the park…', 'Finding the Tuesday run club…', 'Checking group ride routes…', 'Hopping between rec leagues…']

export function LocalActivities({ onAsk, onSaveZip, onLocationChanged }: {
  onAsk: (text: string) => void
  onSaveZip: (zip: string) => Promise<void>
  onLocationChanged?: () => void
}) {
  const [res, setRes] = useState<LocalResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [only, setOnly] = useState<LocalCategory | null>(null)
  const seq = useRef(0)

  const load = useCallback(() => {
    const n = ++seq.current
    setBusy(true); setError(null)
    getLocal().then((r) => { if (n === seq.current) setRes(r) }, (e) => { if (n === seq.current) setError((e as Error).message) })
      .finally(() => { if (n === seq.current) setBusy(false) })
  }, [])
  useEffect(() => { load() }, [load])

  const chips = useMemo(() => {
    if (!res) return []
    const present = new Set(res.items.map((a) => a.category))
    const first = res.suggested.filter((c) => present.has(c))
    return [...first, ...ORDER.filter((c) => present.has(c) && !first.includes(c))]
  }, [res])
  const shown = (res?.items ?? []).filter((a) => !only || a.category === only)

  if (busy && !res) return <div className="flex justify-center py-14"><RabbitLoader label="Finding things to do near you" cycle={LOOKING} /></div>
  if (error && !res) return <ErrorState message={`Couldn't load local activities: ${error}`} onRetry={load} />
  if (!res) return null
  if (res.needs_location) {
    return <LocationPrompt title="Where do you live? Rabbit will find clubs and groups nearby" onSaveZip={onSaveZip} onChanged={() => { load(); onLocationChanged?.() }} />
  }
  return (
    <section className="flex flex-col gap-3">
      <p className="px-1 text-[0.7647rem] leading-snug text-(--text-secondary)">
        Things to do around <span className="font-medium text-(--text)">{[res.city, res.state].filter(Boolean).join(', ')}</span> every week.
      </p>
      {chips.length > 1 && (
        <div className="no-scrollbar -mx-3 -my-1 flex gap-1.5 overflow-x-auto px-3 py-1">
          <Chip selected={!only} onClick={() => setOnly(null)}><span className="whitespace-nowrap">All</span></Chip>
          {chips.map((c) => {
            const Icon = ICON[c]
            return (
              <Chip key={c} selected={only === c} onClick={() => setOnly(only === c ? null : c)}>
                <span className="inline-flex items-center gap-1 whitespace-nowrap"><Icon className="size-3.5" />{res.chips[c] ?? c}</span>
              </Chip>
            )
          })}
        </div>
      )}
      {shown.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-6 text-center">
          <RabbitLoader decorative gentle size={44} />
          <p className="max-w-xs text-[0.7647rem] leading-snug text-(--text-muted)">Rabbit didn't find regular groups here this week. Check back next week.</p>
        </div>
      ) : (
        <div className="no-scrollbar -mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto scroll-px-4 px-4 pb-1">
          {shown.map((a) => <ActivityCard key={a.id} a={a} suggested={res.suggested.includes(a.category)} onAsk={onAsk} city={res.city} />)}
        </div>
      )}
      <p className="px-1 text-[0.6471rem] text-(--text-muted)">Found on the web — check details before you go.</p>
    </section>
  )
}

function ActivityCard({ a, suggested, onAsk, city }: {
  a: LocalActivity; suggested: boolean; onAsk: (text: string) => void; city: string
}) {
  const Icon = ICON[a.category] ?? Dumbbell
  const meta = [a.when, a.where, a.cost && (a.cost === 'free' ? 'Free' : a.cost)].filter(Boolean).join(' · ')
  return (
    <article className="flex w-[78%] max-w-[300px] shrink-0 snap-start flex-col gap-2 rounded-2xl border border-(--border) bg-(--bg-surface) p-3.5">
      <div className="flex items-start gap-2.5">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-(--accent-subtle) text-(--accent)"><Icon className="size-5" /></span>
        <div className="min-w-0 flex-1">
          <p className="line-clamp-2 text-[0.8824rem] font-medium leading-snug text-(--text)">{a.name}</p>
          {a.organizer && a.organizer !== a.name && <p className="truncate text-[0.7059rem] text-(--text-muted)">{a.organizer}</p>}
        </div>
      </div>
      {meta && <p className="text-[0.7059rem] leading-snug text-(--text-secondary)">{meta}</p>}
      <p className="line-clamp-2 text-[0.7647rem] font-medium leading-snug text-(--text)">
        {a.why || (suggested ? 'Matches what you train' : 'Something new to try')}
      </p>
      <div className="mt-auto flex flex-col gap-1">
        {suggested && <span className={cn('w-fit rounded-full bg-(--accent-subtle) px-2 py-0.5 text-[0.6471rem] font-medium text-(--accent)')}>🥕 Picked for you</span>}
        <a href={a.url} target="_blank" rel="noopener noreferrer"
          className="inline-flex min-h-11 items-center gap-1.5 text-[0.7647rem] font-medium text-(--accent)">
          Website <ExternalLink className="size-3.5" />
        </a>
        <button type="button" className="inline-flex min-h-11 items-center gap-1.5 text-left text-[0.7647rem] font-medium text-(--text-secondary)"
          onClick={() => onAsk(`I found "${a.name}" in ${city}${a.when ? ` (${a.when})` : ''}. How could it fit into my training this week?`)}>
          <MessageCircle className="size-3.5" /> Ask Rabbit how this fits my training
        </button>
      </div>
    </article>
  )
}
