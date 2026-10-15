// Community → Clubs → "Clubs & leagues near you": Rabbit's directory of public club and league
// pages for the athlete's city (clubdir.py). Filter chips, cards with the next session, meet
// spot, pace and cost, "Visit site", "Start a Rabbit group" (pre-filled club; links the
// listing), "Report outdated", and "Suggest a club or league". While Rabbit reads club pages
// for a new city, Explore's cached local groups show meanwhile.
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Bike, Check, Clock, ExternalLink, Flag, Footprints, MapPin, Medal, Mountain, Plus, Users, Volleyball, Waves, X,
} from 'lucide-react'
import { RabbitLoader } from '@/components/RabbitLoader'
import { HopIn } from '@/components/anim'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { Chip, Field, inputCls } from '@/components/plan/ui'
import { useSheetDrag } from '@/hooks/useSheetDrag'
import { cn } from '@/lib/utils'
import {
  DIR_CHIPS, getDirectory, nextLabel, reportListing, suggestClub,
  type DirChip, type DirKind, type DirListing, type DirView,
} from '@/lib/clubdir'

const ICON: Record<DirKind, typeof Bike> = {
  run_club: Footprints, trail: Mountain, tri: Medal, ride: Bike, swim: Waves, league: Volleyball, other: Users,
}
const CRAWLING = ['Lacing up…', 'Reading club pages…', 'Finding the Tuesday group run…', 'Checking league schedules…', 'Hopping between parks…']
const POLL_MS = 8000
const POLL_MAX = 15

const linkCls = 'inline-flex min-h-11 items-center gap-1.5 text-[0.7647rem] font-medium'

function verified(d: string): string {
  return new Date(`${d}T12:00:00`).toLocaleDateString([], { month: 'short', day: 'numeric' })
}

function ListingCard({ l, onStart, onReport, busy }: {
  l: DirListing; onStart: () => void; onReport: () => void; busy: boolean
}) {
  const Icon = ICON[l.kind] ?? Users
  const when = nextLabel(l.next)
  const meta = [l.pace, l.cost === 'free' ? 'Free' : l.cost === 'paid' ? 'Paid' : ''].filter(Boolean).join(' · ')
  return (
    <article className="flex flex-col gap-2 rounded-2xl border border-(--border) bg-(--bg-surface) p-3.5">
      <div className="flex items-start gap-2.5">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-(--accent-subtle) text-(--accent)" aria-hidden>
          <Icon className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="line-clamp-2 text-[0.8824rem] font-medium leading-snug text-(--text)">{l.name}</h3>
          <p className="truncate text-[0.7059rem] text-(--text-muted)">{l.kind_label}{l.sports.length ? ` · ${l.sports.slice(0, 2).join(', ')}` : ''}</p>
        </div>
      </div>
      {when && (
        <p className="flex items-center gap-1.5 text-[0.7647rem] font-medium text-(--text)">
          <Clock className="size-3.5 text-(--text-muted)" aria-hidden /> Next: {when}
        </p>
      )}
      {l.meet_spot && (
        <p className="flex items-center gap-1.5 text-[0.7059rem] text-(--text-secondary)">
          <MapPin className="size-3.5 shrink-0 text-(--text-muted)" aria-hidden /> <span className="truncate">{l.meet_spot}</span>
        </p>
      )}
      {meta && <p className="text-[0.7059rem] text-(--text-secondary)">{meta}</p>}
      {l.description && <p className="text-[0.7059rem] leading-snug text-(--text-secondary)">{l.description}</p>}
      <div className="flex flex-wrap items-center gap-x-4">
        <a href={l.join_url} target="_blank" rel="noopener noreferrer" className={cn(linkCls, 'text-(--accent)')}>
          {l.link_only ? `See on ${l.link_only}` : 'Visit site'} <ExternalLink className="size-3.5" aria-hidden />
        </a>
        {l.linked_club ? (
          <span className={cn(linkCls, 'text-(--text-muted)')}><Check className="size-3.5" aria-hidden /> On Rabbit</span>
        ) : (
          <button type="button" className={cn(linkCls, 'text-(--text-secondary)')} onClick={onStart}>
            <Plus className="size-3.5" aria-hidden /> Start a Rabbit group
          </button>
        )}
        {!l.reported && (
          <button type="button" className={cn(linkCls, 'text-(--text-muted)')} disabled={busy} onClick={onReport}>
            <Flag className="size-3.5" aria-hidden /> Report outdated
          </button>
        )}
      </div>
      <p className="text-[0.6471rem] text-(--text-muted)">
        {l.link_only ? `From web search · ${l.source}` : `Checked ${verified(l.last_verified)} · ${l.source}`}
      </p>
    </article>
  )
}

function SuggestSheet({ city, state, onClose }: { city: string; state: string; onClose: () => void }) {
  const drag = useSheetDrag(onClose)
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null)
  async function send() {
    setBusy(true); setMsg(null)
    try {
      const u = url.trim()
      const r = await suggestClub({ name: name.trim(), url: /^https?:\/\//i.test(u) ? u : `https://${u}`, city, state })
      setMsg({ text: r.message, ok: true }); setName(''); setUrl('')
    } catch (e) { setMsg({ text: (e as Error).message, ok: false }) } finally { setBusy(false) }
  }
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} {...drag}>
        <div className="sheet-handle" />
        <div className="modal-header">
          <h2 className="modal-title">Suggest a club or league</h2>
          <button className="modal-close hit-44" aria-label="Close" onClick={onClose}><X className="size-4" /></button>
        </div>
        <div className="modal-body flex flex-col gap-3 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
          <p className="text-[0.7647rem] text-(--text-secondary)">
            Rabbit reads the club's public page on its next update for {city}, {state} and adds it here.
          </p>
          <Field label="Name"><input className={inputCls} maxLength={80} value={name} onChange={(e) => setName(e.target.value)} placeholder="Sloan Lake Striders" /></Field>
          <Field label="Website" hint="The club's own site. Facebook, Meetup and Strava pages can't be read.">
            <input className={inputCls} inputMode="url" autoCapitalize="none" maxLength={300} value={url}
              onChange={(e) => setUrl(e.target.value)} placeholder="https://…" />
          </Field>
          {msg && <p className={cn('text-[0.7059rem]', msg.ok ? 'text-(--accent)' : 'text-(--danger)')} role="status">{msg.text}</p>}
          <Button variant="primary" className="h-11 text-[0.8235rem]" loading={busy} disabled={!name.trim() || !url.trim()} onClick={() => void send()}>
            Send suggestion
          </Button>
        </div>
      </div>
    </div>
  )
}

export function ClubDirectory({ onStartGroup }: { onStartGroup: (l: DirListing) => void }) {
  const [chip, setChip] = useState<DirChip | null>(null)
  const [data, setData] = useState<DirView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [suggesting, setSuggesting] = useState(false)
  const polls = useRef(0)
  const load = useCallback(() => getDirectory(chip).then((d) => { setData(d); setError(null) },
    (e) => setError((e as Error).message)), [chip])
  useEffect(() => { polls.current = 0; void load() }, [load])
  const crawling = data?.status === 'refreshing' || data?.status === 'queued'
  useEffect(() => {
    if (!crawling || polls.current >= POLL_MAX) return
    const id = window.setTimeout(() => { polls.current += 1; void load() }, POLL_MS)
    return () => window.clearTimeout(id)
  }, [crawling, data, load])

  async function report(l: DirListing) {
    setBusy(l.id); setMsg(null)
    try { setMsg((await reportListing(l.id)).message); await load() } catch (e) { setMsg((e as Error).message) } finally { setBusy(null) }
  }

  if (error && !data) return <ErrorState compact message={error} onRetry={() => void load()} />
  if (!data) return <RabbitLoader className="py-6" label="Loading clubs and leagues" cycle={CRAWLING} />
  if (data.status === 'needs_location' || !data.metro) {
    return (
      <section aria-label="Clubs and leagues near you" className="flex flex-col gap-1.5">
        <h2 className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Clubs & leagues near you</h2>
        <p className="px-1 text-[0.7059rem] text-(--text-muted)">Add your home city in your training profile to see run clubs and leagues near you.</p>
      </section>
    )
  }
  const { metro, listings, fallback } = data
  return (
    <section aria-label="Clubs and leagues near you" className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2 px-1">
        <h2 className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">
          Clubs & leagues near {metro.label}
        </h2>
        {crawling && listings.length > 0 && <RabbitLoader inline label="Updating" />}
      </div>
      <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 py-1" role="group" aria-label="Filter clubs and leagues">
        {DIR_CHIPS.map(([v, label]) => (
          <Chip key={v} selected={chip === v} onClick={() => setChip(chip === v ? null : v)}>{label}</Chip>
        ))}
      </div>
      {msg && <p className="px-1 text-[0.7647rem] text-(--accent)" role="status">{msg}</p>}
      {listings.length > 0 ? (
        <div className="flex flex-col gap-2">
          {listings.slice(0, 30).map((l, i) => (
            <HopIn key={l.id} index={i} play={i < 4}>
              <ListingCard l={l} busy={busy === l.id} onStart={() => onStartGroup(l)} onReport={() => void report(l)} />
            </HopIn>
          ))}
        </div>
      ) : crawling ? (
        <div className="flex flex-col gap-2">
          <RabbitLoader className="py-4" label={`Finding clubs and leagues in ${metro.label}`} cycle={CRAWLING} />
          <p className="px-1 text-center text-[0.7059rem] text-(--text-muted)">Rabbit is reading club pages for your city. This takes a few minutes.</p>
        </div>
      ) : (
        <p className="px-1 text-[0.7059rem] text-(--text-muted)">
          {chip ? 'Nothing in this filter yet.' : data.status === 'unavailable' ? 'The directory isn\'t available right now.'
            : `No clubs or leagues listed for ${metro.label} yet.`}
        </p>
      )}
      {!listings.length && fallback.length > 0 && (
        <div className="flex flex-col gap-1">
          <p className="px-1 text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Meanwhile, from Explore</p>
          {fallback.map((g) => (
            <a key={g.id} href={g.url} target="_blank" rel="noopener noreferrer"
              className="flex min-h-11 items-center justify-between gap-2 rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-2">
              <span className="min-w-0">
                <span className="block truncate text-[0.8235rem] text-(--text)">{g.name}</span>
                {(g.when || g.where) && <span className="block truncate text-[0.7059rem] text-(--text-muted)">{[g.when, g.where].filter(Boolean).join(' · ')}</span>}
              </span>
              <ExternalLink className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
            </a>
          ))}
        </div>
      )}
      <div className="flex items-center justify-between gap-2 px-1">
        <p className="text-[0.6471rem] text-(--text-muted)">From public club pages. Times change; check the site.</p>
        <button type="button" className={cn(linkCls, 'shrink-0 text-(--accent)')} onClick={() => setSuggesting(true)}>
          <Plus className="size-3.5" aria-hidden /> Suggest one
        </button>
      </div>
      {suggesting && <SuggestSheet city={metro.city} state={metro.state} onClose={() => setSuggesting(false)} />}
    </section>
  )
}
