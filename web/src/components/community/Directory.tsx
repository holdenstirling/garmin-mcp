// Community → Clubs → "Clubs & leagues near you": Rabbit's directory of public club and league
// pages for the athlete's city (clubdir.py). Filter chips, cards with the next session, meet
// spot, pace and cost, "I'm going" for the next session (count + avatars of people you follow),
// "Add to calendar" (weekly .ics), "Visit site", "Start a Rabbit group" (pre-filled club; links
// the listing), "Report outdated", and "Suggest a club or league". List | Map (DirectoryMap:
// geocoded public meet spots; the list stays primary). While Rabbit reads club pages for a new
// city, Explore's cached local groups show meanwhile.
// Search by name at the top ("5280 run club" finds "5280 Runners"); when nothing matches, "Look it
// up" asks Rabbit to find that club online for your city and adds it. Partners (partners.py) show
// first, always labelled "Partner": "Partners near you" above the list, pinned in search.
import { EmptyState } from '@/components/ui/EmptyState'
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Bike, CalendarPlus, Check, Clock, ExternalLink, Flag, Footprints, Globe, MapPin, Medal, Megaphone, Mountain, Plus, Search as SearchIcon, Users, Volleyball, Waves, X,
} from 'lucide-react'
import { Avatar } from '@/components/Avatar'
import { Segmented } from '@/components/nav/Segmented'
import { DirectoryMap } from '@/components/community/DirectoryMap'
import { communityPhotoUrl } from '@/lib/community'
import { RabbitLoader } from '@/components/RabbitLoader'
import { HopIn } from '@/components/anim'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { Chip, Field, inputCls } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import {
  DIR_CHIPS, calendarUrl, getDirectory, lookUpClub, markGoing, nextLabel, reportListing, searchDirectory, suggestClub,
  type DirChip, type DirGoing, type DirKind, type DirListing, type DirLookup, type DirSearch, type DirView, type Partner,
} from '@/lib/clubdir'
import { Sheet } from '@/components/ui/Sheet'
import { FeatureSheet, useIsOwner } from './Featured'
import { PartnerRow, PartnerSheet, PartnersNearYou } from './Partners'

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

function GoingRow({ l, onGoing }: { l: DirListing; onGoing: (g: DirGoing) => void }) {
  const g = l.going
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  if (!g || !l.next) return null
  async function toggle() {
    if (!g || !l.next) return
    setBusy(true); setErr(null)
    try { onGoing((await markGoing(l.id, !g.me, g.date)).going) } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  const names = g.friends.slice(0, 2).map((f) => f.name)
  return (
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" aria-pressed={g.me} disabled={busy} onClick={() => void toggle()}
        className={cn('press inline-flex min-h-11 items-center gap-1.5 rounded-full border px-3.5 text-[0.7647rem] font-medium',
          g.me ? 'border-(--accent) bg-(--accent) text-(--on-fill)' : 'border-(--border) text-(--text)')}>
        {g.me ? <><Check className="size-3.5" aria-hidden /> Going</> : 'I\'m going'}
      </button>
      {g.friends.length > 0 && (
        <span className="flex -space-x-1.5" aria-hidden>
          {g.friends.slice(0, 3).map((f) => <Avatar key={f.id} name={f.name} picture={f.picture} photo={communityPhotoUrl(f)} size={22} />)}
        </span>
      )}
      {g.count > 0 && (
        <span className="text-[0.7059rem] text-(--text-secondary)">
          {g.count} going{names.length ? ` · ${names.join(', ')}` : ''}
        </span>
      )}
      {err && <span className="text-[0.7059rem] text-(--danger)" role="status">{err}</span>}
    </div>
  )
}

function ListingCard({ l, onStart, onReport, onGoing, busy, onFeature }: {
  l: DirListing; onStart: () => void; onReport: () => void; onGoing: (g: DirGoing) => void; busy: boolean
  /** the app owner's "Feature this club" */
  onFeature?: () => void
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
      <GoingRow l={l} onGoing={onGoing} />
      <div className="flex flex-wrap items-center gap-x-4">
        <a href={l.join_url} target="_blank" rel="noopener noreferrer" className={cn(linkCls, 'text-(--accent)')}>
          {l.link_only ? `See on ${l.link_only}` : 'Visit site'} <ExternalLink className="size-3.5" aria-hidden />
        </a>
        {l.calendar && (
          <a href={calendarUrl(l.id)} download className={cn(linkCls, 'text-(--text-secondary)')}>
            <CalendarPlus className="size-3.5" aria-hidden /> Add to calendar
          </a>
        )}
        {l.linked_club ? (
          <span className={cn(linkCls, 'text-(--text-muted)')}><Check className="size-3.5" aria-hidden /> On Rabbit</span>
        ) : (
          <button type="button" className={cn(linkCls, 'text-(--text-secondary)')} onClick={onStart}>
            <Plus className="size-3.5" aria-hidden /> Start a Rabbit group
          </button>
        )}
        {onFeature && (
          <button type="button" className={cn(linkCls, 'text-(--accent)')} onClick={onFeature}>
            <Megaphone className="size-3.5" aria-hidden /> Feature
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
        {l.found_by === 'search' ? ' · Added by a search' : ''}
      </p>
    </article>
  )
}

function SuggestSheet({ city, state, onClose }: { city: string; state: string; onClose: () => void }) {
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
    <Sheet title="Suggest a club or league" onClose={onClose}>
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
    </Sheet>
  )
}

const LOOKING = ['Searching the web…', 'Checking the club\'s site…', 'Reading their schedule…', 'Almost there…']

/** Results for a typed club name: partners pinned, matching listings, then "Look it up". */
function ClubSearch({ q, card, onSuggest }: { q: string; card: (l: DirListing) => React.ReactNode; onSuggest: () => void }) {
  const [res, setRes] = useState<DirSearch | null>(null)
  const [err, setErr] = useState(false)
  const [look, setLook] = useState<{ busy: boolean; out: DirLookup | null; err: string | null }>({ busy: false, out: null, err: null })
  const [partner, setPartner] = useState<Partner | null>(null)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let live = true
    setLook({ busy: false, out: null, err: null })
    const t = window.setTimeout(() => {
      searchDirectory(q).then((r) => { if (live) { setRes(r); setErr(false) } }, () => { if (live) setErr(true) })
    }, 300)
    return () => { live = false; window.clearTimeout(t) }
  }, [q, tick])
  async function lookUp() {
    setLook({ busy: true, out: null, err: null })
    try { setLook({ busy: false, out: await lookUpClub(q), err: null }) } catch (e) { setLook({ busy: false, out: null, err: (e as Error).message }) }
  }
  if (err) return <ErrorState compact message="Couldn't search clubs right now." onRetry={() => { setErr(false); setTick((n) => n + 1) }} />
  if (!res || res.q !== q.trim().replace(/\s+/g, ' ').slice(0, 60)) return <RabbitLoader className="py-4" label="Searching clubs" />
  const found = look.out?.status === 'found' ? look.out.listings : []
  const rows = [...found, ...res.listings.filter((l) => !found.some((f) => f.id === l.id))]
  const lookUpBtn = (label: string) => (
    <Button variant="primary" className="h-11 gap-1.5 text-[0.8235rem]" loading={look.busy} onClick={() => void lookUp()}>
      <Globe className="size-4" aria-hidden /> {label}
    </Button>
  )
  return (
    <div className="flex flex-col gap-2" aria-live="polite">
      {res.partners.map((p) => <PartnerRow key={p.id} p={p} onOpen={() => setPartner(p)} />)}
      {rows.map((l, i) => <HopIn key={l.id} index={i} play={i < 4}>{card(l)}</HopIn>)}
      {look.busy && <RabbitLoader className="py-3" label={`Looking for “${q}” near ${res.metro?.label ?? 'you'}`} cycle={LOOKING} />}
      {!look.busy && look.out && look.out.status !== 'found' && (
        <EmptyState compact
          title={look.out.status === 'none' ? `Rabbit couldn't find “${q}” online` : look.out.status === 'limit' ? "That's plenty of look-ups for today" : "Look-ups aren't available right now"}
          body="Know the club's website? Send it and Rabbit adds it on the next update."
          action="Suggest the club" onAction={onSuggest} />
      )}
      {look.err && <p className="px-1 text-[0.7647rem] text-(--danger)" role="alert">{look.err}</p>}
      {!look.busy && !look.out && rows.length === 0 && (
        <div className="flex flex-col gap-2 rounded-2xl border border-dashed border-(--border-strong) p-4 text-center">
          <p className="text-[0.8235rem] font-medium text-(--text)">No “{q}” in Rabbit's list for {res.metro?.label ?? 'your city'} yet</p>
          <p className="text-[0.7059rem] text-(--text-muted)">Rabbit can look it up online and add it for everyone here. Takes about 20 seconds.</p>
          {res.can_look_up ? lookUpBtn(`Look up “${q}”`) : (
            <Button variant="default" className="h-11 text-[0.8235rem]" onClick={onSuggest}>Suggest the club's website</Button>
          )}
        </div>
      )}
      {!look.busy && !look.out && rows.length > 0 && res.can_look_up && (
        <button type="button" className={cn(linkCls, 'justify-center text-(--accent)')} onClick={() => void lookUp()}>
          <Globe className="size-3.5" aria-hidden /> Not the one? Look up “{q}” online
        </button>
      )}
      {partner && <PartnerSheet p={partner} onClose={() => setPartner(null)} />}
    </div>
  )
}

export function ClubDirectory({ onStartGroup }: { onStartGroup: (l: DirListing | null) => void }) {
  const [chip, setChip] = useState<DirChip | null>(null)
  const [data, setData] = useState<DirView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [suggesting, setSuggesting] = useState(false)
  const [view, setView] = useState<'list' | 'map'>('list')
  const [featuring, setFeaturing] = useState<DirListing | null>(null)
  const [q, setQ] = useState('')
  const searching = q.trim().length >= 2
  const owner = useIsOwner(data?.listings[0] ? { listing: data.listings[0].id } : null)
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

  function setGoing(id: string, g: DirGoing) {
    setData((d) => d && { ...d, listings: d.listings.map((x) => (x.id === id ? { ...x, going: g } : x)) })
  }
  const card = (l: DirListing) => (
    <ListingCard l={l} busy={busy === l.id} onStart={() => onStartGroup(l)} onReport={() => void report(l)}
      onGoing={(g) => setGoing(l.id, g)} onFeature={owner ? () => setFeaturing(l) : undefined} />
  )

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
  const mappable = listings.some((l) => typeof l.lat === 'number')
  return (
    <section aria-label="Clubs and leagues near you" className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2 px-1">
        <h2 className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">
          Clubs & leagues near {metro.label}
        </h2>
        {crawling && listings.length > 0 && <RabbitLoader inline label="Updating" />}
      </div>
      <label className="flex h-11 items-center gap-2 rounded-full border border-(--border) bg-(--bg-surface) px-3.5 focus-within:ring-1 focus-within:ring-(--accent)">
        <SearchIcon className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
        <input type="text" inputMode="search" enterKeyHint="search" value={q} onChange={(e) => setQ(e.target.value.slice(0, 60))}
          placeholder="Search clubs by name" aria-label={`Search clubs and leagues near ${metro.label}`}
          className="min-w-0 flex-1 bg-transparent text-[0.8235rem] text-(--text) outline-none placeholder:text-(--text-muted)" />
        {q && (
          <button type="button" aria-label="Clear club search" onClick={() => setQ('')}
            className="-mr-2 flex size-11 items-center justify-center text-(--text-muted)"><X className="size-4" aria-hidden /></button>
        )}
      </label>
      {searching ? (
        <ClubSearch q={q.trim()} card={card} onSuggest={() => setSuggesting(true)} />
      ) : (<>
      <PartnersNearYou partners={data.partners ?? []} metro={metro.label} />
      <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 py-1" role="group" aria-label="Filter clubs and leagues">
        {DIR_CHIPS.map(([v, label]) => (
          <Chip key={v} selected={chip === v} onClick={() => setChip(chip === v ? null : v)}>{label}</Chip>
        ))}
      </div>
      {mappable && (
        <Segmented label="Show clubs as" value={view} onChange={setView} options={[['list', 'List'], ['map', 'Map']] as const} />
      )}
      {msg && <p className="px-1 text-[0.7647rem] text-(--accent)" role="status">{msg}</p>}
      {listings.length > 0 && mappable && view === 'map' ? (
        <DirectoryMap listings={listings.slice(0, 30)} center={data.center} metroLabel={metro.label} renderCard={card} />
      ) : listings.length > 0 ? (
        <div className="flex flex-col gap-2">
          {listings.slice(0, 30).map((l, i) => (
            <HopIn key={l.id} index={i} play={i < 4}>{card(l)}</HopIn>
          ))}
        </div>
      ) : crawling ? (
        <div className="flex flex-col gap-2">
          <RabbitLoader className="py-4" label={`Finding clubs and leagues in ${metro.label}`} cycle={CRAWLING} />
          <p className="px-1 text-center text-[0.7059rem] text-(--text-muted)">Rabbit is reading club pages for your city. This takes a few minutes.</p>
        </div>
      ) : (
        chip ? (
          <EmptyState compact title="Nothing in this filter yet" action="Show everything" onAction={() => setChip(null)} />
        ) : (
          <EmptyState compact title={data.status === 'unavailable' ? "The directory isn't available right now" : `No clubs listed for ${metro.label} yet`}
            body="Know a club, track night or league? Add it and Rabbit checks it, or start your own group."
            action="Start a group" onAction={() => onStartGroup(null)} />
        )
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
      </>)}
      <div className="flex items-center justify-between gap-2 px-1">
        <p className="text-[0.6471rem] text-(--text-muted)">From public club pages. Times change; check the site.</p>
        <button type="button" className={cn(linkCls, 'shrink-0 text-(--accent)')} onClick={() => setSuggesting(true)}>
          <Plus className="size-3.5" aria-hidden /> Suggest one
        </button>
      </div>
      {suggesting && <SuggestSheet city={metro.city} state={metro.state} onClose={() => setSuggesting(false)} />}
      {featuring && <FeatureSheet name={featuring.name} listingId={featuring.id} onClose={() => setFeaturing(null)} />}
    </section>
  )
}
