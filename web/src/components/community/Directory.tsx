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
  CalendarPlus, Check, ChevronDown, Clock, ExternalLink, Flag, Globe, MapPin, Megaphone, Plus, Search as SearchIcon, X,
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
  TIME_OF_DAY, WEEKDAY_LABEL, calendarUrl, getDirectory, lookUpClub, markGoing, nextLabel, reportListing, searchDirectory, suggestClub,
  type DirFilters, type DirGoing, type DirListing, type DirLookup, type DirSearch, type DirView, type Partner, type TimeOfDay, type Weekday,
} from '@/lib/clubdir'
import { ACTIVITIES, ACTIVITY_LABEL, distanceLabel, radiusLabel, type ActivityId } from '@/lib/activity'
import { ActivityTile } from '@/components/local/ActivityIcon'
import { AreaBar, useAreaChanged } from '@/components/local/AreaBar'
import { AreaInline } from '@/components/local/AreaInline'
import { requestPostRun } from '@/lib/events'
import { nativeShare } from '@/lib/sharelinks'
import { Sheet } from '@/components/ui/Sheet'
import { FeatureSheet, useIsOwner } from './Featured'
import { PartnerRow, PartnerSheet, PartnersNearYou, SponsoredCard } from './Partners'

const CRAWLING = ['Lacing up…', 'Reading club pages…', 'Finding the Tuesday group run…', 'Checking league schedules…', 'Hopping between parks…']
const POLL_MS = 8000
const POLL_MAX = 15

const linkCls = 'inline-flex min-h-11 items-center gap-1.5 text-small font-medium'

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
        className={cn('press inline-flex min-h-11 items-center gap-1.5 rounded-full border px-3.5 text-small font-medium',
          g.me ? 'border-(--accent) bg-(--accent) text-(--on-fill)' : 'border-(--border) text-(--text)')}>
        {g.me ? <><Check className="size-4" aria-hidden /> Going</> : 'I\'m going'}
      </button>
      {g.friends.length > 0 && (
        <span className="flex -space-x-1.5" aria-hidden>
          {g.friends.slice(0, 3).map((f) => <Avatar key={f.id} name={f.name} picture={f.picture} photo={communityPhotoUrl(f)} size={22} />)}
        </span>
      )}
      {g.count > 0 && (
        <span className="text-meta text-(--text-secondary)">
          {g.count} going{names.length ? ` · ${names.join(', ')}` : ''}
        </span>
      )}
      {err && <span className="text-meta text-(--danger)" role="status">{err}</span>}
    </div>
  )
}

function ListingCard({ l, imperial, onStart, onReport, onGoing, busy, onFeature }: {
  l: DirListing; imperial: boolean; onStart: () => void; onReport: () => void; onGoing: (g: DirGoing) => void; busy: boolean
  /** the app owner's "Feature this club" */
  onFeature?: () => void
}) {
  const [more, setMore] = useState(false)
  const when = nextLabel(l.next)
  const what = [l.type_label ?? l.kind_label, l.activity && l.activity !== 'other' ? ACTIVITY_LABEL[l.activity] : null].filter(Boolean).join(' · ')
  const meta = [l.pace, l.cost === 'free' ? 'Free' : l.cost === 'paid' ? 'Paid' : ''].filter(Boolean).join(' · ')
  return (
    <article className="flex flex-col gap-3 rounded-xl border border-(--border) bg-(--bg-surface) p-4">
      <div className="flex items-start gap-3">
        <ActivityTile activity={l.activity} size={44} />
        <div className="min-w-0 flex-1">
          <h3 className="m-0 text-lead font-semibold leading-snug text-(--text)">{l.name}</h3>
          {what && <p className="m-0 mt-0.5 text-meta text-(--text-secondary)">{what}</p>}
          {l.distance_km !== undefined && (
            <p className="m-0 text-meta text-(--text-muted)">{distanceLabel(l.distance_km, imperial)} away</p>
          )}
        </div>
      </div>
      {when && (
        <p className="flex items-center gap-1.5 text-small font-medium text-(--text)">
          <Clock className="size-4 text-(--text-muted)" aria-hidden /> Next: {when}
        </p>
      )}
      {l.meet_spot && (
        <p className="flex items-center gap-1.5 text-meta text-(--text-secondary)">
          <MapPin className="size-4 shrink-0 text-(--text-muted)" aria-hidden /> <span className="truncate">{l.meet_spot}</span>
        </p>
      )}
      {meta && <p className="text-meta text-(--text-secondary)">{meta}</p>}
      {l.description && <p className="text-meta leading-snug text-(--text-secondary)">{l.description}</p>}
      <GoingRow l={l} onGoing={onGoing} />
      <div className="flex flex-wrap items-center gap-x-4">
        <a href={l.join_url} target="_blank" rel="noopener noreferrer" className={cn(linkCls, 'text-(--accent)')}>
          {l.link_only ? `See on ${l.link_only}` : 'Visit site'} <ExternalLink className="size-4" aria-hidden />
        </a>
        {l.calendar && (
          <a href={calendarUrl(l.id)} download className={cn(linkCls, 'text-(--text-secondary)')}>
            <CalendarPlus className="size-4" aria-hidden /> Add to calendar
          </a>
        )}
        {l.linked_club && <span className={cn(linkCls, 'text-(--text-muted)')}><Check className="size-4" aria-hidden /> On rabbt</span>}
        <button type="button" aria-expanded={more} className={cn(linkCls, 'ml-auto text-(--text-muted)')} onClick={() => setMore((v) => !v)}>
          More <ChevronDown className={cn('size-4 transition-transform', more && 'rotate-180')} aria-hidden />
        </button>
      </div>
      {more && (
        <div className="flex flex-wrap items-center gap-x-4 border-t border-(--border) pt-1">
          {!l.linked_club && (
            <button type="button" className={cn(linkCls, 'text-(--text-secondary)')} onClick={onStart}>
              <Plus className="size-4" aria-hidden /> Start a rabbt group
            </button>
          )}
          {onFeature && (
            <button type="button" className={cn(linkCls, 'text-(--accent)')} onClick={onFeature}>
              <Megaphone className="size-4" aria-hidden /> Feature
            </button>
          )}
          {!l.reported && (
            <button type="button" className={cn(linkCls, 'text-(--text-muted)')} disabled={busy} onClick={onReport}>
              <Flag className="size-4" aria-hidden /> Report outdated
            </button>
          )}
        </div>
      )}
      <p className="text-caption text-(--text-muted)">
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
          <p className="text-small text-(--text-secondary)">
            rabbt reads the club's public page on its next update for {city}, {state} and adds it here.
          </p>
          <Field label="Name"><input className={inputCls} maxLength={80} value={name} onChange={(e) => setName(e.target.value)} placeholder="Sloan Lake Striders" /></Field>
          <Field label="Website" hint="The club's own site. Facebook, Meetup and Strava pages can't be read.">
            <input className={inputCls} inputMode="url" autoCapitalize="none" maxLength={300} value={url}
              onChange={(e) => setUrl(e.target.value)} placeholder="https://…" />
          </Field>
          {msg && <p className={cn('text-meta', msg.ok ? 'text-(--accent)' : 'text-(--danger)')} role="status">{msg.text}</p>}
          <Button variant="primary" className="h-11 text-body" loading={busy} disabled={!name.trim() || !url.trim()} onClick={() => void send()}>
            Send suggestion
          </Button>
    </Sheet>
  )
}

const LOOKING = ['Searching the web…', 'Checking the club\'s site…', 'Reading their schedule…', 'Almost there…']

/** Results for a typed club name: partners pinned, matching listings, then "Look it up". */
function ClubSearch({ q, filters, card, onSuggest }: { q: string; filters: DirFilters; card: (l: DirListing) => React.ReactNode; onSuggest: () => void }) {
  const [res, setRes] = useState<DirSearch | null>(null)
  const [err, setErr] = useState(false)
  const [look, setLook] = useState<{ busy: boolean; out: DirLookup | null; err: string | null }>({ busy: false, out: null, err: null })
  const [partner, setPartner] = useState<Partner | null>(null)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let live = true
    setLook({ busy: false, out: null, err: null })
    const t = window.setTimeout(() => {
      searchDirectory(q, filters).then((r) => { if (live) { setRes(r); setErr(false) } }, () => { if (live) setErr(true) })
    }, 300)
    return () => { live = false; window.clearTimeout(t) }
  }, [q, tick, filters.activity, filters.weekday, filters.when]) // eslint-disable-line react-hooks/exhaustive-deps
  async function lookUp() {
    setLook({ busy: true, out: null, err: null })
    try { setLook({ busy: false, out: await lookUpClub(q), err: null }) } catch (e) { setLook({ busy: false, out: null, err: (e as Error).message }) }
  }
  if (err) return <ErrorState compact message="Couldn't search clubs right now." onRetry={() => { setErr(false); setTick((n) => n + 1) }} />
  if (!res || res.q !== q.trim().replace(/\s+/g, ' ').slice(0, 60)) return <RabbitLoader className="py-4" label="Searching clubs" />
  const found = look.out?.status === 'found' ? look.out.listings : []
  const rows = [...found, ...res.listings.filter((l) => !found.some((f) => f.id === l.id))]
  const lookUpBtn = (label: string) => (
    <Button variant="primary" className="h-11 gap-1.5 text-body" loading={look.busy} onClick={() => void lookUp()}>
      <Globe className="size-5" aria-hidden /> {label}
    </Button>
  )
  return (
    <div className="flex flex-col gap-2" aria-live="polite">
      {/* A sponsored partner shows once, disclosed: for a zip in a partner's area, or a club search near one. */}
      {(/^\d{5}$/.test(q) || res.partners.some((p) => p.sponsored)) && <SponsoredCard placement="local" zip={/^\d{5}$/.test(q) ? q : undefined} />}
      {res.partners.filter((p) => !p.sponsored).map((p) => <PartnerRow key={p.id} p={p} onOpen={() => setPartner(p)} />)}
      {rows.map((l, i) => <HopIn key={l.id} index={i} play={i < 4}>{card(l)}</HopIn>)}
      {look.busy && <RabbitLoader className="py-3" label={`Looking for “${q}” near ${res.metro?.label ?? 'you'}`} cycle={LOOKING} />}
      {!look.busy && look.out && look.out.status !== 'found' && (
        <EmptyState compact
          title={look.out.status === 'none' ? `rabbt couldn't find “${q}” online` : look.out.status === 'limit' ? "That's plenty of look-ups for today" : "Look-ups aren't available right now"}
          body="Know the club's website? Send it and rabbt adds it on the next update."
          action="Suggest the club" onAction={onSuggest} />
      )}
      {look.err && <p className="px-1 text-small text-(--danger)" role="alert">{look.err}</p>}
      {!look.busy && !look.out && rows.length === 0 && (
        <div className="flex flex-col gap-2 rounded-2xl border border-dashed border-(--border-strong) p-4 text-center">
          <p className="text-body font-medium text-(--text)">No “{q}” in rabbt's list for {res.metro?.label ?? 'your city'} yet</p>
          <p className="text-meta text-(--text-muted)">rabbt can look it up online and add it for everyone here. Takes about 20 seconds.</p>
          {res.can_look_up ? lookUpBtn(`Look up “${q}”`) : (
            <Button variant="default" className="h-11 text-body" onClick={onSuggest}>Suggest the club's website</Button>
          )}
        </div>
      )}
      {(res.farther ?? 0) > 0 && (
        <p className="px-1 text-meta text-(--text-muted)">
          {res.farther} more {res.farther === 1 ? 'match is' : 'matches are'} farther away. Widen your area above to see {res.farther === 1 ? 'it' : 'them'}.
        </p>
      )}
      {!look.busy && !look.out && rows.length > 0 && res.can_look_up && (
        <button type="button" className={cn(linkCls, 'justify-center text-(--accent)')} onClick={() => void lookUp()}>
          <Globe className="size-4" aria-hidden /> Not the one? Look up “{q}” online
        </button>
      )}
      {partner && <PartnerSheet p={partner} onClose={() => setPartner(null)} />}
    </div>
  )
}

export function ClubDirectory({ onStartGroup, imperial = true }: { onStartGroup: (l: DirListing | null) => void; imperial?: boolean }) {
  const [activity, setActivity] = useState<ActivityId | null>(null)
  const [weekday, setWeekday] = useState<Weekday | null>(null)
  const [when, setWhen] = useState<TimeOfDay | null>(null)
  const [more, setMore] = useState(false)
  const filters: DirFilters = { activity, weekday, when }
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
  const load = useCallback(() => getDirectory({ activity, weekday, when }).then((d) => { setData(d); setError(null) },
    (e) => setError((e as Error).message)), [activity, weekday, when])
  useEffect(() => { polls.current = 0; void load() }, [load])
  useAreaChanged(useCallback(() => { setData(null); void load() }, [load]))
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
    <ListingCard l={l} imperial={imperial} busy={busy === l.id} onStart={() => onStartGroup(l)} onReport={() => void report(l)}
      onGoing={(g) => setGoing(l.id, g)} onFeature={owner ? () => setFeaturing(l) : undefined} />
  )
  const bar = <AreaBar imperial={imperial} />
  async function inviteOrganizer() {
    const url = `${window.location.origin}/app/`
    const text = 'Post your club runs on rabbt so people near you can find them and RSVP:'
    const r = await nativeShare('Your club on rabbt', text, url)
    if (r !== 'unsupported') return
    try { await navigator.clipboard.writeText(`${text} ${url}`); setMsg('Link copied. Send it to your organizer.') }
    catch { setMsg(url) }
  }

  if (error && !data) return <div className="flex flex-col gap-2">{bar}<ErrorState compact message={error} onRetry={() => void load()} /></div>
  if (!data) return <div className="flex flex-col gap-2">{bar}<RabbitLoader className="py-6" label="Loading clubs and leagues" cycle={CRAWLING} /></div>
  if (data.status === 'needs_location' || !data.metro) {
    return (
      <section aria-label="Clubs, leagues and meetups near you" className="flex flex-col gap-2">
        <AreaInline />
      </section>
    )
  }
  const { metro, listings, fallback } = data
  const mappable = listings.some((l) => typeof l.lat === 'number')
  const counts = data.activities ?? {}
  const shownActs = ACTIVITIES.filter(([id]) => (counts[id] ?? 0) > 0 || id === activity)
  const extraOn = (weekday ? 1 : 0) + (when ? 1 : 0)
  const radius = data.area ? radiusLabel(data.area.radius_mi, imperial) : ''
  return (
    <section aria-label="Clubs, leagues and meetups near you" className="flex flex-col gap-3">
      {bar}
      <label className="flex h-12 items-center gap-2.5 rounded-full border border-(--border) bg-(--bg-surface) px-4 focus-within:ring-1 focus-within:ring-(--accent)">
        <SearchIcon className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
        <input type="text" inputMode="search" enterKeyHint="search" value={q} onChange={(e) => setQ(e.target.value.slice(0, 60))}
          placeholder="Search clubs and meetups" aria-label={`Search clubs, leagues and meetups near ${data.area?.label || metro.label}`}
          className="min-w-0 flex-1 bg-transparent text-body text-(--text) outline-none placeholder:text-(--text-muted)" />
        {q && (
          <button type="button" aria-label="Clear search" onClick={() => setQ('')}
            className="-mr-2 flex size-11 items-center justify-center text-(--text-muted)"><X className="size-5" aria-hidden /></button>
        )}
      </label>
      <div className="no-scrollbar -mx-5 flex gap-2 overflow-x-auto px-5 py-1" role="group" aria-label="Filter by activity">
        <Chip selected={activity === null} onClick={() => setActivity(null)}>All</Chip>
        {(shownActs.length ? shownActs : ACTIVITIES).map(([id, label]) => (
          <Chip key={id} selected={activity === id} onClick={() => setActivity(activity === id ? null : id)}>
            {label}{counts[id] ? <span className="ml-1 text-(--text-muted)">{counts[id]}</span> : null}
          </Chip>
        ))}
        <Chip selected={more || extraOn > 0} onClick={() => setMore((v) => !v)}>
          <span className="inline-flex items-center gap-1">{extraOn ? `Day & time · ${extraOn}` : 'Day & time'}
            <ChevronDown className={cn('size-4 transition-transform', more && 'rotate-180')} aria-hidden /></span>
        </Chip>
      </div>
      {more && (
        <div className="flex flex-col gap-2 rounded-xl border border-(--border) bg-(--bg-surface) p-3">
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Day of the week">
            <Chip selected={weekday === null} onClick={() => setWeekday(null)}>Any day</Chip>
            {(Object.keys(WEEKDAY_LABEL) as Weekday[]).map((d) => (
              <Chip key={d} selected={weekday === d} onClick={() => setWeekday(weekday === d ? null : d)}>{WEEKDAY_LABEL[d]}</Chip>
            ))}
          </div>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Time of day">
            <Chip selected={when === null} onClick={() => setWhen(null)}>Any time</Chip>
            {TIME_OF_DAY.map(([v, label]) => <Chip key={v} selected={when === v} onClick={() => setWhen(when === v ? null : v)}>{label}</Chip>)}
          </div>
        </div>
      )}
      {searching ? (
        <ClubSearch q={q.trim()} filters={filters} card={card} onSuggest={() => setSuggesting(true)} />
      ) : (<>
      {/* One "Sponsored partner" card per screen: at the top while there are clubs (or Rabbit is still
          finding them), inside the empty state otherwise. Other partners keep their own spot. */}
      {(listings.length > 0 || crawling) && <SponsoredCard placement="local" />}
      <PartnersNearYou partners={(data.partners ?? []).filter((p) => !p.sponsored)} metro={metro.label} />
      <div className="flex items-end justify-between gap-3 px-1 pt-2">
        <div className="min-w-0">
          <h2 className="section-title m-0">{activity ? ACTIVITY_LABEL[activity] : 'Clubs and meetups'}</h2>
          {radius && <p className="m-0 mt-0.5 text-small text-(--text-muted)">Within {radius} of you</p>}
        </div>
        {crawling && listings.length > 0 && <RabbitLoader inline label="Updating" />}
      </div>
      {mappable && (
        <div className="w-full"><Segmented label="Show clubs as" value={view} onChange={setView} options={[['list', 'List'], ['map', 'Map']] as const} /></div>
      )}
      {msg && <p className="px-1 text-small text-(--accent)" role="status">{msg}</p>}
      {listings.length > 0 && mappable && view === 'map' ? (
        <DirectoryMap listings={listings.slice(0, 30)} center={data.center} metroLabel={metro.label} renderCard={card} />
      ) : listings.length > 0 ? (
        <div className="flex flex-col gap-3">
          {listings.slice(0, 30).map((l, i) => (
            <HopIn key={l.id} index={i} play={i < 4}>{card(l)}</HopIn>
          ))}
        </div>
      ) : crawling ? (
        <div className="flex flex-col gap-2">
          <RabbitLoader className="py-4" label={`Finding clubs and leagues in ${metro.label}`} cycle={CRAWLING} />
          <p className="px-1 text-center text-meta text-(--text-muted)">rabbt is reading club pages for your city. This takes a few minutes.</p>
        </div>
      ) : (
        activity || weekday || when ? (
          <EmptyState compact title={`Nothing like that within ${radius || 'your area'}`}
            body={(data.farther ?? 0) > 0 ? 'There are more farther away: widen your area above.' : undefined}
            action="Clear filters" onAction={() => { setActivity(null); setWeekday(null); setWhen(null) }} />
        ) : (
          <>
            <EmptyState compact mode="peek"
              title={data.status === 'unavailable' ? "The directory isn't available right now" : `Nothing listed yet near ${data.area?.label || metro.label}`}
              body="Be the first: post a run and people nearby can join. Or invite the organizer of your club."
              action="Post the first run" onAction={requestPostRun}
              secondary="Invite your club organizer" onSecondary={() => void inviteOrganizer()} />
            <SponsoredCard placement="directory_empty" />
          </>
        )
      )}
      {listings.length > 0 && (data.farther ?? 0) > 0 && (
        <p className="px-1 text-meta text-(--text-muted)">
          {data.farther} more {data.farther === 1 ? 'is' : 'are'} farther than {radius}. Widen your area above to see {data.farther === 1 ? 'it' : 'them'}.
        </p>
      )}
      {!listings.length && fallback.length > 0 && (
        <div className="flex flex-col gap-1">
          <h3 className="section-title section-title--sm m-0 px-1">Meanwhile, from Explore</h3>
          {fallback.map((g) => (
            <a key={g.id} href={g.url} target="_blank" rel="noopener noreferrer"
              className="flex min-h-11 items-center justify-between gap-2 rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-2">
              <span className="min-w-0">
                <span className="block truncate text-body text-(--text)">{g.name}</span>
                {(g.when || g.where) && <span className="block truncate text-meta text-(--text-muted)">{[g.when, g.where].filter(Boolean).join(' · ')}</span>}
              </span>
              <ExternalLink className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
            </a>
          ))}
        </div>
      )}
      </>)}
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-1">
        <p className="m-0 text-meta text-(--text-muted)">From public club pages. Times change, so check the site.</p>
        <button type="button" className={cn(linkCls, 'shrink-0 text-(--accent)')} onClick={() => setSuggesting(true)}>
          <Plus className="size-4" aria-hidden /> Suggest one
        </button>
      </div>
      {suggesting && <SuggestSheet city={metro.city} state={metro.state} onClose={() => setSuggesting(false)} />}
      {featuring && <FeatureSheet name={featuring.name} listingId={featuring.id} onClose={() => setFeaturing(null)} />}
    </section>
  )
}
