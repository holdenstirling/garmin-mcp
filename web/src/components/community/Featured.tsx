// Featured clubs (featured.py): up to 3 clubs the app owner promotes, shown at the top of
// Community (Feed and Clubs) and in Explore -> For you as one clearly labelled card each: name,
// sport, city, next meetup, members, Join / RSVP. Plus the owner-only "Feature this club" switch
// on a club page and on a directory listing (end date + short tagline).
import { useEffect, useState } from 'react'
import { CalendarCheck, Clock, ExternalLink, Globe, MapPin, Megaphone, Users } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { burst } from '@/components/anim'
import { Row, Switch } from '@/components/settings/Grouped'
import { RowGroup } from './RowGroup'
import { Sheet } from '@/components/ui/Sheet'
import { inputCls } from '@/components/plan/ui'
import { SPORTS, joinClub, meetupWhen, rsvpMeetup, type Sport } from '@/lib/community'
import { nextLabel, type DirListing } from '@/lib/clubdir'
import { getFeatureState, getFeatured, setFeature, type FeatureState, type Featured } from '@/lib/community2'
import { cn } from '@/lib/utils'

const SPORT_LABEL = Object.fromEntries(SPORTS) as Record<Sport, string>

/** The featured strip: snap-scrolling cards (one card fills the row). Renders nothing when empty. */
export function FeaturedStrip({ where = 'community', items: given, onOpenClub, onToast }: {
  where?: 'community' | 'explore'; items?: Featured[]; onOpenClub?: (id: string) => void; onToast?: (m: string) => void
}) {
  const [items, setItems] = useState<Featured[]>(given ?? [])
  useEffect(() => {
    if (given) { setItems(given); return }
    let live = true
    getFeatured(where).then((r) => { if (live) setItems(r.items) }, () => { /* a bonus row */ })
    return () => { live = false }
  }, [where, given])
  if (!items.length) return null
  return (
    <section aria-label="Featured clubs" className={cn('flex gap-2', items.length > 1 && '-mx-5 snap-x overflow-x-auto px-5 pb-1')}>
      {items.map((f) => (
        <FeaturedCard key={f.id} f={f} wide={items.length === 1} onOpenClub={onOpenClub} onToast={onToast}
          onChange={(nf) => setItems((xs) => xs.map((x) => (x.id === nf.id ? nf : x)))} />
      ))}
    </section>
  )
}

function FeaturedCard({ f, wide, onOpenClub, onChange, onToast }: {
  f: Featured; wide: boolean; onOpenClub?: (id: string) => void; onChange: (f: Featured) => void; onToast?: (m: string) => void
}) {
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const say = (m: string) => { setMsg(m); onToast?.(m) }
  const place = f.online ? 'Online' : [f.city, f.state].filter(Boolean).join(', ')
  const sport = f.kind === 'club' ? SPORT_LABEL[(f.sport ?? 'other') as Sport] : f.kind_label
  const meet = f.next_meetup
  const when = f.kind === 'club' ? (meet ? meetupWhen(meet.next) : '') : nextLabel((f.next ?? null) as DirListing['next'])
  const member = !!f.role

  async function join(el: HTMLElement) {
    if (!f.club_id) return
    setBusy(true)
    try {
      const r = await joinClub(f.club_id)
      if (!r.club.requested) burst(el, 'kudos')
      onChange({ ...f, role: r.club.role, requested: r.club.requested, members: r.club.members })
      say(r.message)
    } catch (e) { say((e as Error).message) } finally { setBusy(false) }
  }
  async function rsvp(el: HTMLElement) {
    if (!f.club_id || !meet) return
    setBusy(true)
    try {
      const r = await rsvpMeetup(f.club_id, meet.id, meet.my_rsvp === 'going' ? 'none' : 'going')
      if (r.meetup.my_rsvp === 'going') burst(el, 'kudos')
      onChange({ ...f, next_meetup: { ...meet, my_rsvp: r.meetup.my_rsvp, going: r.meetup.going.length } })
      say(r.meetup.my_rsvp === 'going' ? `You're going to ${meet.title}.` : 'RSVP removed.')
    } catch (e) { say((e as Error).message) } finally { setBusy(false) }
  }

  const action = f.kind === 'listing' ? (
    f.join_url ? (
      <a href={f.join_url} target="_blank" rel="noopener noreferrer"
        className="hit-44 inline-flex h-11 items-center gap-1.5 rounded-xl bg-(--accent) px-4 text-small font-semibold text-(--on-fill)">
        {f.link_only ? `See on ${f.link_only}` : 'Join'} <ExternalLink className="size-4" aria-hidden />
      </a>
    ) : null
  ) : member ? (
    meet ? (
      <Button variant={meet.my_rsvp === 'going' ? 'default' : 'primary'} className="h-11 gap-1.5 px-4 text-small" loading={busy}
        onClick={(e) => void rsvp(e.currentTarget)}>
        <CalendarCheck className="size-5" /> {meet.my_rsvp === 'going' ? "You're going" : 'RSVP'}
      </Button>
    ) : (
      <Button variant="default" className="h-11 px-4 text-small" onClick={() => f.club_id && onOpenClub?.(f.club_id)}>Open club</Button>
    )
  ) : f.requested ? (
    <span className="text-meta text-(--text-muted)">Requested</span>
  ) : f.full ? null : (
    <Button variant="primary" className="h-11 px-4 text-small" loading={busy} onClick={(e) => void join(e.currentTarget)}>
      {f.privacy === 'approval' ? 'Ask to join' : 'Join'}
    </Button>
  )

  return (
    <article aria-label={`Featured: ${f.name}`}
      className={cn('flex shrink-0 snap-start flex-col gap-2 rounded-2xl border border-(--accent)/40 bg-(--accent-subtle) p-3.5',
        wide ? 'w-full' : 'w-[85%] max-w-sm')}>
      <div className="flex items-start gap-2.5">
        <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-(--bg-surface) text-title-lg" aria-hidden>
          {f.kind === 'club' ? (f.emoji || '🐇') : <Users className="size-6 text-(--accent)" />}
        </span>
        <div className="min-w-0 flex-1">
          <span className="inline-flex items-center gap-1 rounded-full bg-(--accent) px-2 py-0.5 text-caption font-semibold text-(--on-fill)">
            <Megaphone className="size-3.5" aria-hidden /> Featured
          </span>
          <button type="button" disabled={f.kind !== 'club' || !onOpenClub} onClick={() => f.club_id && onOpenClub?.(f.club_id)}
            className="mt-1 block w-full text-left disabled:cursor-default">
            <h3 className="line-clamp-2 text-lead font-semibold leading-snug text-(--text)">{f.name}</h3>
          </button>
          <p className="flex flex-wrap items-center gap-x-1.5 text-meta text-(--text-secondary)">
            {sport && <span>{sport}</span>}
            {place && <span className="inline-flex items-center gap-0.5">· {f.online ? <Globe className="size-3.5" aria-hidden /> : <MapPin className="size-3.5" aria-hidden />}{place}</span>}
            {f.members != null && <span>· {f.members} member{f.members === 1 ? '' : 's'}</span>}
          </p>
        </div>
      </div>
      {f.tagline && <p className="text-body leading-snug text-(--text)">{f.tagline}</p>}
      {when && (
        <p className="flex items-center gap-1.5 text-small font-medium text-(--text)">
          <Clock className="size-4 text-(--text-muted)" aria-hidden />
          <span className="truncate">Next: {when}{meet ? ` · ${meet.title}` : ''}{meet?.where ? ` · ${meet.where}` : ''}</span>
          {meet && meet.going > 0 && <span className="shrink-0 text-(--text-muted)">· {meet.going} going</span>}
        </p>
      )}
      <div className="flex items-center gap-2">
        {action}
        {msg && <span className="min-w-0 flex-1 truncate text-meta text-(--accent)" role="status">{msg}</span>}
      </div>
    </article>
  )
}

/** Owner-only "Feature this club" (renders nothing for everyone else). */
export function FeatureSwitch({ clubId, listingId }: { clubId?: string; listingId?: string }) {
  const [s, setS] = useState<FeatureState | null>(null)
  const [until, setUntil] = useState('')
  const [tagline, setTagline] = useState('')
  const [online, setOnline] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null)
  useEffect(() => {
    let live = true
    getFeatureState(clubId ? { club: clubId } : { listing: listingId }).then((r) => {
      if (!live) return
      setS(r); setUntil(r.until ?? ''); setTagline(r.tagline ?? ''); setOnline(!!r.online)
    }, () => { /* not the owner, or not available */ })
    return () => { live = false }
  }, [clubId, listingId])
  if (!s?.owner) return null
  const ref = clubId ? { club_id: clubId } : { listing_id: listingId }

  async function save(on: boolean) {
    setBusy(true); setMsg(null)
    try {
      const r = await setFeature(ref, on ? { on, until: until || null, tagline, online } : { on })
      setS(r)
      setMsg({ text: on ? 'Featured. It shows at the top of Community for people nearby or into the same sport.' : 'No longer featured.', ok: true })
    } catch (e) { setMsg({ text: (e as Error).message, ok: false }) } finally { setBusy(false) }
  }
  const tomorrow = new Date(Date.now() + 86400000).toISOString().slice(0, 10)
  return (
    <RowGroup as="h3" title="App owner" footer={s.featured ? undefined : `${s.slots_left ?? 0} of 3 featured spots free.`}>
      <Row icon={<Megaphone className="size-5 text-(--accent)" />} title="Feature this club"
        subtitle="Top of Community and Explore, labelled Featured"
        trailing={<Switch label="Feature this club" checked={!!s.featured} disabled={busy} onChange={(v) => void save(v)} />} />
      {s.featured && (
        <div className="flex flex-col gap-2 px-3 py-2.5">
          <label className="flex flex-col gap-1 text-caption text-(--text-muted)">Tagline (optional)
            <input className={inputCls} maxLength={80} value={tagline} placeholder="Saturday long runs, all paces"
              onChange={(e) => setTagline(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-caption text-(--text-muted)">Feature until (optional)
            <input type="date" className={inputCls} min={tomorrow} value={until} onChange={(e) => setUntil(e.target.value)} />
          </label>
          <label className="flex min-h-11 items-center gap-2 text-small text-(--text-secondary)">
            <input type="checkbox" className="size-5" checked={online} onChange={(e) => setOnline(e.target.checked)} />
            Online / virtual club (show to everyone)
          </label>
          <Button variant="primary" className="h-11 text-small" loading={busy} onClick={() => void save(true)}>Save</Button>
        </div>
      )}
      {msg && <p className={cn('px-3 pb-2 text-meta', msg.ok ? 'text-(--accent)' : 'text-(--danger)')} role="status">{msg.text}</p>}
    </RowGroup>
  )
}

/** The owner's switch in a sheet (directory listings: one tap from the card). */
export function FeatureSheet({ name, clubId, listingId, onClose }: { name: string; clubId?: string; listingId?: string; onClose: () => void }) {
  return (
    <Sheet title={`Feature ${name}`} onClose={onClose}
      bodyClassName="flex flex-col gap-3 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
      <FeatureSwitch clubId={clubId} listingId={listingId} />
    </Sheet>
  )
}

/** Is the signed-in athlete the app owner? (Asked once, by any listing or club id.) */
export function useIsOwner(ref: { club?: string; listing?: string } | null): boolean {
  const [owner, setOwner] = useState(false)
  const key = ref?.club ?? ref?.listing ?? ''
  useEffect(() => {
    if (!key) return
    let live = true
    getFeatureState(ref ?? {}).then((r) => { if (live) setOwner(r.owner) }, () => { /* not the owner */ })
    return () => { live = false }
  }, [key]) // eslint-disable-line react-hooks/exhaustive-deps
  return owner
}
