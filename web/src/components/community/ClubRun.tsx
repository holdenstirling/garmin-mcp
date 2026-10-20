// Club runs: the card people RSVP on (tags, pace groups, spots and waitlist, waiver, add to
// calendar, report), the "Post a club run" sheet (under 30 seconds: title, when, where with a map
// pin, pace groups, walkers, capacity, who can see it, optional waiver and cost note), and the
// organizer's sheet (who's coming, check-in, message everyone, skip or copy a week, waiver export,
// the public club link) plus the club dashboard.
import { useEffect, useMemo, useState } from 'react'
import {
  CalendarPlus, Check, Copy, Flag, Link2, MapPin, Plus, Repeat, Send, SkipForward, Trash2, Users, X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet } from '@/components/ui/Sheet'
import { ErrorState } from '@/components/ui/ErrorState'
import { RabbitLoader } from '@/components/RabbitLoader'
import { Card, Field, inputCls } from '@/components/plan/ui'
import { Switch } from '@/components/settings/Grouped'
import { SlippyMap, type Bounds } from '@/components/local/SlippyMap'
import { burst } from '@/components/anim'
import { confirmAsk } from '@/lib/confirm'
import { useDraft } from '@/lib/drafts'
import { useUnsavedGuard, DraftRestored } from '@/components/ui/UnsavedGuard'
import { cn } from '@/lib/utils'
import { countClubRun } from '@/lib/plan'
import {
  LEVELS, RUN_SEE, addMeetup, checkIn, deleteMeetup, duplicateRun, getClubDashboard, getClubLink, getRoster,
  meetupWhen, messageRunners, reportRun, rsvpMeetup, runTags, skipWeek, waiverCsvUrl,
  type ClubDashboard, type Level, type Meetup, type MeetupInput, type PaceGroup, type Roster, type RunSee,
} from '@/lib/community'
import { Choice } from './Choice'
import { PersonAvatar } from './Feed'

const LEVEL_LABEL = Object.fromEntries(LEVELS) as Record<Level, string>
const SEE_LABEL = Object.fromEntries(RUN_SEE) as Record<RunSee, string>

/** An .ics file for one occurrence (local time, floating), saved by the browser. */
export function downloadIcs(m: Pick<Meetup, 'id' | 'title' | 'where' | 'next' | 'notes'>, club?: string) {
  if (!m.next) return
  const d = m.next.replace(/[-:]/g, '').slice(0, 13) + '00'
  const endD = new Date(new Date(m.next).getTime() + 60 * 60000)
  const pad = (n: number) => String(n).padStart(2, '0')
  const end = `${endD.getFullYear()}${pad(endD.getMonth() + 1)}${pad(endD.getDate())}T${pad(endD.getHours())}${pad(endD.getMinutes())}00`
  const esc = (s: string) => s.replace(/[\\;,]/g, (c) => `\\${c}`).replace(/\n/g, '\\n')
  const body = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//rabbt//club run//EN', 'BEGIN:VEVENT',
    `UID:${m.id}-${d}@rabbt`, `DTSTART:${d}`, `DTEND:${end}`, `SUMMARY:${esc(club ? `${club}: ${m.title}` : m.title)}`,
    `LOCATION:${esc(m.where)}`, ...(m.notes ? [`DESCRIPTION:${esc(m.notes)}`] : []), 'END:VEVENT', 'END:VCALENDAR'].join('\r\n')
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([body], { type: 'text/calendar' }))
  a.download = `${m.title.replace(/[^\w]+/g, '-').slice(0, 40) || 'club-run'}.ics`
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 4000)
}

const mapsUrl = (m: Pick<Meetup, 'lat' | 'lng' | 'where'>) => m.lat != null && m.lng != null
  ? `https://www.openstreetmap.org/?mlat=${m.lat}&mlon=${m.lng}#map=17/${m.lat}/${m.lng}`
  : `https://www.openstreetmap.org/search?query=${encodeURIComponent(m.where)}`

function spotsLine(m: Meetup): string | null {
  if (m.my_rsvp === 'waitlist') return m.wait_pos ? `You're number ${m.wait_pos} on the waitlist` : "You're on the waitlist"
  if (!m.capacity) return null
  if ((m.spots_left ?? 0) > 0) return `${m.spots_left} of ${m.capacity} spots left`
  return m.waitlist ? `Full, ${m.waitlist} on the waitlist` : 'Full. Tap Going to join the waitlist'
}

/** A club run you can RSVP to. ``admin`` shows Organize; ``onPlanned`` after "Count it". */
export function RunCard({ m, clubId, clubName, admin, onChanged, onError, onOrganize }: {
  m: Meetup; clubId: string; clubName?: string; admin: boolean; onChanged: () => void; onError: (t: string) => void
  onOrganize?: (m: Meetup) => void
}) {
  const [mt, setMt] = useState(m)
  const [busy, setBusy] = useState(false)
  const [waiver, setWaiver] = useState(false)
  const [offer, setOffer] = useState<'ask' | 'busy' | 'done' | null>(null)
  useEffect(() => setMt(m), [m])
  async function rsvp(status: 'going' | 'maybe', el: HTMLElement | null, accept = false) {
    const next = mt.my_rsvp === status || (status === 'going' && mt.my_rsvp === 'waitlist') ? 'none' : status
    if (next === 'going' && mt.waiver && !mt.waiver_signed && !accept) { setWaiver(true); return }
    setBusy(true)
    try {
      const r = await rsvpMeetup(clubId, mt.id, next, accept)
      setMt(r.meetup)
      if (r.meetup.my_rsvp === 'going') {
        if (el) burst(el, 'kudos')
        setOffer('ask')
      } else setOffer(null)
    } catch (e) { onError((e as Error).message) } finally { setBusy(false) }
  }
  async function count() {
    setOffer('busy')
    try { await countClubRun(clubId, mt.id); setOffer('done') } catch (e) { setOffer(null); onError((e as Error).message) }
  }
  async function cancel() {
    if (!(await confirmAsk(`Cancel "${mt.title}"?`, { detail: "Anyone who said they're going gets a heads-up.", confirm: 'Cancel it', cancel: 'Keep it', danger: true }))) return
    try { await deleteMeetup(clubId, mt.id); onChanged() } catch (e) { onError((e as Error).message) }
  }
  async function report() {
    if (!(await confirmAsk('Report this run?', { detail: 'rabbt looks at every report. The organizers are not told who reported it.', confirm: 'Report', cancel: 'Not now', danger: true }))) return
    try { await reportRun(clubId, mt.id); onError('Thanks. We got your report.') } catch (e) { onError((e as Error).message) }
  }
  const going = mt.going.filter((u): u is NonNullable<typeof u> => !!u)
  const tags = runTags(mt)
  const spots = spotsLine(mt)
  const count_ = mt.count ?? going.length
  const day = mt.next ? new Date(mt.next).toLocaleDateString([], { weekday: 'long' }) : 'that day'
  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-meta font-semibold text-(--accent)">{mt.next ? meetupWhen(mt.next) : ''}
            {mt.repeat === 'weekly' && <span className="ml-1.5 inline-flex items-center gap-0.5 font-normal text-(--text-muted)"><Repeat className="size-3.5" aria-hidden />weekly</span>}
          </p>
          <p className="text-lead font-medium text-(--text)">{mt.title}</p>
          <a href={mapsUrl(mt)} target="_blank" rel="noopener noreferrer"
            className="flex min-h-11 items-center gap-1 text-meta text-(--text-secondary) underline-offset-2 active:underline">
            <MapPin className="size-5 shrink-0" aria-hidden /><span className="min-w-0 break-words">{mt.where}</span>
          </a>
        </div>
        {(admin || mt.mine) ? (
          <Button variant="ghost" className="h-11 w-11 shrink-0 p-0" aria-label="Cancel club run" onClick={() => void cancel()}><Trash2 className="size-5" /></Button>
        ) : (
          <Button variant="ghost" className="h-11 w-11 shrink-0 p-0" aria-label="Report this run" onClick={() => void report()}><Flag className="size-5" /></Button>
        )}
      </div>
      {(tags.length > 0 || mt.see === 'public' || mt.see === 'private') && (
        <div className="flex flex-wrap gap-1.5">
          {tags.map((t) => <span key={t} className="rounded-full bg-(--accent-subtle) px-2.5 py-1 text-meta text-(--accent)">{t}</span>)}
          {mt.see && mt.see !== 'club' && <span className="rounded-full bg-(--bg-inset) px-2.5 py-1 text-meta text-(--text-secondary)">{mt.see === 'public' ? 'Open to anyone' : 'Invite only'}</span>}
        </div>
      )}
      {(mt.groups ?? []).length > 0 ? (
        <div className="flex flex-col gap-0.5">
          <p className="text-meta text-(--text-muted)">Pace groups</p>
          {(mt.groups ?? []).map((g, i) => (
            <p key={i} className="text-small text-(--text)">{g.label}{g.pace ? <span className="text-(--text-secondary)"> at {g.pace}</span> : null}</p>
          ))}
        </div>
      ) : (
        <p className="text-meta text-(--text-muted)">{[LEVEL_LABEL[mt.level], mt.pace].filter(Boolean).join(' · ')}</p>
      )}
      {mt.notes && <p className="text-small text-(--text-secondary)">{mt.notes}</p>}
      {mt.paid && <p className="text-small text-(--text-secondary)">Cost: {mt.paid}</p>}
      {spots && <p className={cn('text-meta', mt.my_rsvp === 'waitlist' ? 'font-semibold text-(--accent)' : 'text-(--text-secondary)')}>{spots}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <span className="flex -space-x-1.5">{going.slice(0, 5).map((u) => <PersonAvatar key={u.id} u={u} size={24} />)}</span>
        <span className="min-w-0 flex-1 text-meta text-(--text-muted)">
          {count_ ? `${count_} going` : 'Be the first'}{mt.maybe ? `, ${mt.maybe} maybe` : ''}
        </span>
        <div className="flex gap-2">
          <Button variant={mt.my_rsvp === 'maybe' ? 'primary' : 'default'} className="h-11 px-3 text-meta" disabled={busy}
            aria-pressed={mt.my_rsvp === 'maybe'} onClick={(e) => void rsvp('maybe', e.currentTarget)}>Maybe</Button>
          <Button variant={mt.my_rsvp === 'going' || mt.my_rsvp === 'waitlist' ? 'primary' : 'default'} className="h-11 gap-1 px-3 text-meta" disabled={busy}
            aria-pressed={mt.my_rsvp === 'going' || mt.my_rsvp === 'waitlist'} onClick={(e) => void rsvp('going', e.currentTarget)}>
            {(mt.my_rsvp === 'going' || mt.my_rsvp === 'waitlist') && <Check className="size-4" aria-hidden />}
            {mt.my_rsvp === 'waitlist' ? 'Waitlist' : 'Going'}
          </Button>
        </div>
      </div>
      {offer && (
        <div className="flex flex-col gap-2 rounded-lg bg-(--accent-subtle) p-3">
          {offer === 'done' ? (
            <p className="text-small text-(--text)" role="status">Done. {day}'s plan now counts this club run, and the week's load stays about the same.</p>
          ) : (
            <>
              <p className="text-small text-(--text)">Count {day}'s club run as your easy run? rabbt trims the week so it doesn't add up to too much.</p>
              <div className="flex gap-2">
                <Button variant="default" className="h-11 flex-1 text-meta" loading={offer === 'busy'} onClick={() => void count()}>Count it</Button>
                <Button variant="ghost" className="h-11 px-3 text-meta" onClick={() => setOffer(null)}>No thanks</Button>
              </div>
            </>
          )}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {mt.next && mt.my_rsvp === 'going' && (
          <Button variant="ghost" className="h-11 gap-1.5 px-2 text-meta" onClick={() => downloadIcs(mt, clubName)}>
            <CalendarPlus className="size-5" aria-hidden /> Add to calendar
          </Button>
        )}
        {(admin || mt.mine) && onOrganize && (
          <Button variant="ghost" className="h-11 gap-1.5 px-2 text-meta" onClick={() => onOrganize(mt)}>
            <Users className="size-5" aria-hidden /> Organize
          </Button>
        )}
      </div>
      {waiver && (
        <Sheet title="Waiver" onClose={() => setWaiver(false)}
          footer={<Button variant="primary" className="h-12 w-full text-body" loading={busy}
            onClick={() => { setWaiver(false); void rsvp('going', null, true) }}>I accept, count me in</Button>}>
          <p className="whitespace-pre-line text-body text-(--text)">{mt.waiver}</p>
          <p className="text-meta text-(--text-muted)">The organizers keep a record that you accepted it, with the date.</p>
        </Sheet>
      )}
    </Card>
  )
}

// ----------------------------------------------------------------- post --
type Draft = {
  title: string; start: string; weekly: boolean; place: string; lat: number | null; lng: number | null
  groups: PaceGroup[]; level: Level; walk: boolean; beginner: boolean; women: boolean
  capacity: string; see: RunSee; waiver: string; paid: string; notes: string; more: boolean
}

function nextWeekday(hour = 18): string {
  const t = new Date(Date.now() + 86400000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${t.getFullYear()}-${pad(t.getMonth() + 1)}-${pad(t.getDate())}T${pad(hour)}:00`
}

/** "Post a club run": the essentials first; the rest under "More options". */
export function RunSheet({ clubId, privateClub, center, onClose, onSaved }: {
  clubId: string; privateClub?: boolean; center?: { lat: number; lon: number } | null
  onClose: () => void; onSaved: (m: Meetup) => void
}) {
  const [d, setD, draft] = useDraft<Draft>(`clubrun.${clubId}`, () => ({
    title: '', start: nextWeekday(), weekly: true, place: '', lat: null, lng: null, groups: [], level: 'all',
    walk: false, beginner: false, women: false, capacity: '', see: privateClub ? 'club' : 'public', waiver: '', paid: '',
    notes: '', more: false,
  }), { label: 'club run' })
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }))
  const guard = useUnsavedGuard(draft.dirty, draft.discard)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [pin, setPin] = useState(d.lat != null)
  const [view, setView] = useState<Bounds | null>(null)
  const cap = d.capacity.trim() ? Number(d.capacity) : null
  const capBad = cap != null && (!Number.isInteger(cap) || cap < 1 || cap > 500)
  async function save(e: React.MouseEvent<HTMLElement>) {
    const el = e.currentTarget
    setBusy(true); setErr(null)
    const body: MeetupInput = {
      title: d.title.trim(), start: d.start, repeat: d.weekly ? 'weekly' : 'none', where: d.place.trim(), level: d.level,
      notes: d.notes.trim(), groups: d.groups.filter((g) => g.label.trim() || g.pace.trim()).map((g) => ({ label: g.label.trim(), pace: g.pace.trim() })),
      walk: d.walk, beginner: d.beginner, women: d.women, capacity: cap, see: d.see, waiver: d.waiver.trim(), paid: d.paid.trim(),
      lat: d.lat, lng: d.lng,
    }
    try {
      const r = await addMeetup(clubId, body)
      burst(el, 'kudos')
      draft.clear()
      onSaved(r.meetup)
    } catch (x) { setErr((x as Error).message) } finally { setBusy(false) }
  }
  function dropPin() {
    if (!view) return
    setD((x) => ({ ...x, lat: Math.round(((view.north + view.south) / 2) * 1e5) / 1e5, lng: Math.round(((view.east + view.west) / 2) * 1e5) / 1e5 }))
  }
  const ready = d.title.trim() && d.place.trim() && d.start && !capBad
  return (
    <Sheet title="Post a club run" onClose={guard.wrap(onClose)} extra={guard.dialog}
      footer={<Button variant="primary" className="h-12 w-full text-body" loading={busy} disabled={!ready} onClick={(e) => void save(e)}>Post club run</Button>}>
      {draft.restored && <DraftRestored onDiscard={draft.discard} />}
      <Field label="What"><input className={inputCls} maxLength={60} value={d.title} onChange={(e) => set('title', e.target.value)} placeholder="Tuesday social 5k" /></Field>
      <Field label="When"><input type="datetime-local" className={inputCls} value={d.start} onChange={(e) => set('start', e.target.value.slice(0, 16))} /></Field>
      <Field label="Repeats">
        <Choice label="Repeats" value={d.weekly ? 'weekly' : 'none'} options={[['weekly', 'Every week'], ['none', 'Just once']]} onChange={(v) => set('weekly', v === 'weekly')} />
      </Field>
      <Field label="Meeting spot" hint="A park, shop or trailhead. Never a home address.">
        <input className={inputCls} maxLength={120} value={d.place} onChange={(e) => set('place', e.target.value)} placeholder="Wash Park boathouse" />
      </Field>
      {pin ? (
        <div className="flex flex-col gap-2">
          <div className="relative overflow-hidden rounded-lg">
            <SlippyMap pins={[]} center={d.lat != null && d.lng != null ? { lat: d.lat, lon: d.lng } : center ?? { lat: 39.74, lon: -104.99 }}
              onSelect={() => {}} onMoved={setView} height={220} />
            <MapPin aria-hidden className="pointer-events-none absolute left-1/2 top-1/2 size-8 -translate-x-1/2 -translate-y-full text-(--accent) drop-shadow" />
          </div>
          <p className="text-meta text-(--text-muted)">Move the map so the pin sits on the meeting spot.</p>
          <div className="flex gap-2">
            <Button variant="default" className="h-11 flex-1 gap-1.5 text-meta" disabled={!view} onClick={dropPin}>
              <MapPin className="size-5" aria-hidden /> {d.lat != null ? 'Move the pin here' : 'Pin it here'}
            </Button>
            <Button variant="ghost" className="h-11 px-3 text-meta" onClick={() => { setPin(false); setD((x) => ({ ...x, lat: null, lng: null })) }}>Remove pin</Button>
          </div>
          {d.lat != null && <p className="text-meta text-(--accent)" role="status">Pinned. People get a map link.</p>}
        </div>
      ) : (
        <Button variant="ghost" className="h-11 justify-start gap-1.5 px-2 text-meta" onClick={() => setPin(true)}>
          <MapPin className="size-5" aria-hidden /> Add a map pin
        </Button>
      )}
      <Field label="Pace groups" hint="Optional. Up to 4, like Chatty at 11:00/mi.">
        <div className="flex flex-col gap-2">
          {d.groups.map((g, i) => (
            <div key={i} className="flex gap-2">
              <input className={cn(inputCls, 'min-w-0 flex-1')} maxLength={30} value={g.label} aria-label={`Group ${i + 1} name`} placeholder="Chatty"
                onChange={(e) => set('groups', d.groups.map((x, j) => j === i ? { ...x, label: e.target.value } : x))} />
              <input className={cn(inputCls, 'w-28 shrink-0')} maxLength={20} value={g.pace} aria-label={`Group ${i + 1} pace`} placeholder="11:00/mi"
                onChange={(e) => set('groups', d.groups.map((x, j) => j === i ? { ...x, pace: e.target.value } : x))} />
              <Button variant="ghost" className="h-11 w-11 shrink-0 p-0" aria-label={`Remove group ${i + 1}`}
                onClick={() => set('groups', d.groups.filter((_, j) => j !== i))}><X className="size-5" /></Button>
            </div>
          ))}
          {d.groups.length < 4 && (
            <Button variant="ghost" className="h-11 justify-start gap-1.5 px-2 text-meta"
              onClick={() => set('groups', [...d.groups, { label: '', pace: '' }])}><Plus className="size-5" aria-hidden /> Add a pace group</Button>
          )}
        </div>
      </Field>
      <div className="flex flex-col gap-1">
        <SwitchLine label="No one left behind" sub="Beginner friendly: the group waits." checked={d.beginner} onChange={(v) => set('beginner', v)} />
        <SwitchLine label="Walkers welcome" sub="There's a walk option." checked={d.walk} onChange={(v) => set('walk', v)} />
      </div>
      <Field label="Who can see it">
        <Choice label="Who can see it" value={d.see}
          options={(privateClub ? RUN_SEE.filter(([k]) => k !== 'public') : RUN_SEE) as [RunSee, string][]} onChange={(v) => set('see', v)} />
      </Field>
      {d.see === 'public' && <p className="-mt-2 text-meta text-(--text-muted)">Anyone with your club link can see it and RSVP with a name and email. Names stay private.</p>}
      {d.see === 'private' && <p className="-mt-2 text-meta text-(--text-muted)">Only people you send the run's link to (and organizers) can see it.</p>}
      <Button variant="ghost" className="h-11 justify-start px-2 text-meta" aria-expanded={d.more} onClick={() => set('more', !d.more)}>
        {d.more ? 'Fewer options' : 'More options: spots, waiver, cost, women only'}
      </Button>
      {d.more && (
        <>
          <Field label="Spots (optional)" hint="Leave empty for no limit. When it's full, people join a waitlist and move up when someone drops.">
            <input className={inputCls} inputMode="numeric" maxLength={3} value={d.capacity} onChange={(e) => set('capacity', e.target.value.replace(/\D/g, ''))} placeholder="No limit" />
          </Field>
          {capBad && <p className="text-meta text-(--danger)">Spots can be 1 to 500.</p>}
          <Field label="Level"><Choice label="Level" value={d.level} options={LEVELS} onChange={(v) => set('level', v)} /></Field>
          <SwitchLine label="Women only" sub="On the honor system." checked={d.women} onChange={(v) => set('women', v)} />
          <Field label="Waiver (optional)" hint="People accept it before they can RSVP. You can export who accepted and when.">
            <textarea className={cn(inputCls, 'min-h-24 py-2')} maxLength={1500} value={d.waiver} onChange={(e) => set('waiver', e.target.value)}
              placeholder="I take part at my own risk..." />
          </Field>
          <Field label="Cost (optional)" hint="Just a note. rabbt doesn't take payments.">
            <input className={inputCls} maxLength={80} value={d.paid} onChange={(e) => set('paid', e.target.value)} placeholder="$5 at the door or Venmo @club" />
          </Field>
          <Field label="Notes (optional)"><input className={inputCls} maxLength={200} value={d.notes} onChange={(e) => set('notes', e.target.value)} placeholder="Coffee after at Steam" /></Field>
        </>
      )}
      {err && <p className="text-meta text-(--danger)" role="alert">{err}</p>}
    </Sheet>
  )
}

function SwitchLine({ label, sub, checked, onChange }: { label: string; sub: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex min-h-14 items-center gap-3 py-1">
      <div className="min-w-0 flex-1">
        <p className="text-body text-(--text)">{label}</p>
        <p className="text-meta text-(--text-muted)">{sub}</p>
      </div>
      <Switch checked={checked} onChange={onChange} label={label} />
    </div>
  )
}

// -------------------------------------------------------------- organize --
export function OrganizeSheet({ clubId, run, onClose, onChanged }: {
  clubId: string; run: Meetup; onClose: () => void; onChanged: () => void
}) {
  const [roster, setRoster] = useState<Roster | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [link, setLink] = useState<string | null>(null)
  useEffect(() => { getRoster(clubId, run.id).then((r) => setRoster(r.roster), (e) => setErr((e as Error).message)) }, [clubId, run.id])
  async function act(key: string, fn: () => Promise<unknown>, done?: string) {
    setBusy(key); setErr(null); setNote(null)
    try { await fn(); if (done) setNote(done) } catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }
  const dateKey = roster?.date ?? run.next?.slice(0, 10) ?? null
  const shareUrl = useMemo(() => {
    if (!link) return null
    if (run.see === 'public' || !run.token) return link
    return `${link}/r/${run.id}?t=${run.token}`
  }, [link, run])
  async function copyLink() {
    await act('link', async () => {
      const r = await getClubLink(clubId)
      setLink(r.url)
      const url = run.see === 'public' || !run.token ? r.url : `${r.url}/r/${run.id}?t=${run.token}`
      try { await navigator.clipboard.writeText(url); setNote('Link copied. Put it in your Instagram bio or group chat.') }
      catch { setNote(url) }
    })
  }
  return (
    <Sheet title={run.title} onClose={onClose}>
      <p className="text-small text-(--text-secondary)">{run.next ? meetupWhen(run.next) : ''}. {SEE_LABEL[run.see ?? 'club']} can see it.</p>
      {err && <ErrorState compact message={err} />}
      {note && <p className="break-words text-meta text-(--accent)" role="status">{note}</p>}
      <div className="flex flex-col gap-2">
        <Button variant="default" className="h-11 justify-start gap-2 text-body" loading={busy === 'link'} onClick={() => void copyLink()}>
          <Link2 className="size-5" aria-hidden /> {run.see === 'public' ? 'Copy the club link' : "Copy this run's private link"}
        </Button>
        {shareUrl && <p className="break-all text-meta text-(--text-muted)">{shareUrl}</p>}
      </div>
      <section className="flex flex-col gap-2" aria-label="Who's coming">
        <h3 className="section-title text-title-sm">Who's coming</h3>
        {!roster && !err && <RabbitLoader className="py-4" label="Loading the list" />}
        {roster && (
          <p className="text-meta text-(--text-muted)">{roster.going} going, {roster.checked_in} checked in{roster.waitlist ? `, ${roster.waitlist} waiting` : ''}</p>
        )}
        {roster && roster.rows.length === 0 && <p className="text-small text-(--text-muted)">No one yet. Share the link to get the first RSVPs.</p>}
        {roster && roster.rows.length > 0 && (
          <Card>
            {roster.rows.map((r) => (
              <div key={r.id} className="flex min-h-14 items-center gap-3 border-b border-(--border) px-4 py-2 last:border-b-0">
                {r.user ? <PersonAvatar u={r.user} size={30} /> : <span className="flex size-[30px] items-center justify-center rounded-full bg-(--bg-inset) text-meta text-(--text-secondary)" aria-hidden>{(r.name ?? '?').slice(0, 1)}</span>}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-body text-(--text)">{r.name ?? 'Runner'}</p>
                  <p className="truncate text-meta text-(--text-muted)">
                    {r.status === 'waitlist' ? 'Waitlist' : r.status === 'maybe' ? 'Maybe' : 'Going'}{r.kind === 'guest' ? ', from the web' : ''}{r.waiver ? ', waiver signed' : ''}
                  </p>
                  {r.email && <p className="truncate text-meta text-(--text-muted)">{r.email}</p>}
                </div>
                {r.status === 'going' && (
                  <Button variant={r.checked_in ? 'primary' : 'default'} className="h-11 shrink-0 gap-1 px-3 text-meta" aria-pressed={r.checked_in}
                    loading={busy === r.id}
                    onClick={() => void act(r.id, async () => setRoster((await checkIn(clubId, run.id, r.id, !r.checked_in)).roster))}>
                    {r.checked_in && <Check className="size-4" aria-hidden />} {r.checked_in ? 'Here' : 'Check in'}
                  </Button>
                )}
              </div>
            ))}
          </Card>
        )}
      </section>
      <section className="flex flex-col gap-2" aria-label="Message everyone">
        <h3 className="section-title text-title-sm">Message everyone</h3>
        <textarea className={cn(inputCls, 'min-h-20 py-2')} maxLength={280} value={text} onChange={(e) => setText(e.target.value)}
          placeholder="Meet at the north lot tonight" aria-label="Message to everyone going" />
        <Button variant="default" className="h-11 gap-1.5 text-body" disabled={!text.trim()} loading={busy === 'msg'}
          onClick={() => void act('msg', async () => { const r = await messageRunners(clubId, run.id, text); setText(''); setNote(`Sent to ${r.sent} ${r.sent === 1 ? 'person' : 'people'}.`) })}>
          <Send className="size-5" aria-hidden /> Send
        </Button>
        <p className="text-meta text-(--text-muted)">People going, maybe or on the waitlist get a notification. Web sign-ups don't.</p>
      </section>
      <section className="flex flex-col gap-2" aria-label="This week">
        <h3 className="section-title text-title-sm">This week</h3>
        {run.repeat === 'weekly' && dateKey && (
          <Button variant="default" className="h-11 justify-start gap-2 text-body" loading={busy === 'skip'}
            onClick={() => void act('skip', async () => {
              if (!(await confirmAsk(`Skip ${new Date(`${dateKey}T12:00`).toLocaleDateString([], { month: 'short', day: 'numeric' })}?`, { detail: 'Everyone who RSVPd gets told.', confirm: 'Skip it', cancel: 'Keep it' }))) return
              await skipWeek(clubId, run.id, dateKey, true); onChanged(); onClose()
            })}>
            <SkipForward className="size-5" aria-hidden /> Skip this week
          </Button>
        )}
        <Button variant="default" className="h-11 justify-start gap-2 text-body" loading={busy === 'dup'}
          onClick={() => void act('dup', async () => { await duplicateRun(clubId, run.id); onChanged() }, 'Copied to the week after. Edit it from the club page.')}>
          <Copy className="size-5" aria-hidden /> Copy to next week
        </Button>
        {run.waiver && (
          <a href={waiverCsvUrl(clubId, run.id)} download className="inline-flex h-11 items-center gap-2 rounded-lg px-2 text-body text-(--accent)">
            <Flag className="size-5" aria-hidden /> Export waivers (CSV)
          </a>
        )}
      </section>
    </Sheet>
  )
}

/** Organizer dashboard: members, join requests, upcoming runs, attendance by week. */
export function ClubDashboardCard({ clubId, onRequests }: { clubId: string; onRequests?: () => void }) {
  const [d, setD] = useState<ClubDashboard | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { getClubDashboard(clubId).then((r) => setD(r.dashboard), (e) => setErr((e as Error).message)) }, [clubId])
  if (err) return <ErrorState compact message={err} />
  if (!d) return null
  const max = Math.max(1, ...d.attendance.map((a) => a.going))
  return (
    <section className="flex flex-col gap-3" aria-label="Organizer dashboard">
      <h3 className="section-title text-title-sm">Organizer dashboard</h3>
      <Card className="flex flex-col gap-4 p-4">
        <div className="grid grid-cols-3 gap-2">
          <Stat label="Members" value={d.members} />
          <Stat label="Waiting to join" value={d.requests} onClick={d.requests ? onRequests : undefined} />
          <Stat label="Upcoming runs" value={d.runs.length} />
        </div>
        {d.attendance.length > 0 ? (
          <div className="flex flex-col gap-1.5">
            <p className="text-meta text-(--text-muted)">Going each run date (checked in is the darker part)</p>
            <div className="flex h-24 items-end gap-1" role="img"
              aria-label={`Attendance: ${d.attendance.map((a) => `${a.date} ${a.going} going, ${a.checkins} checked in`).join('; ')}`}>
              {d.attendance.map((a) => (
                <div key={a.date} className="relative flex-1 rounded-t bg-(--accent-subtle)" style={{ height: `${Math.max(6, (a.going / max) * 100)}%` }}>
                  <div className="absolute inset-x-0 bottom-0 rounded-t bg-(--accent)" style={{ height: `${a.going ? Math.min(100, (a.checkins / a.going) * 100) : 0}%` }} />
                </div>
              ))}
            </div>
            <p className="text-caption text-(--text-muted)">Last {d.attendance.length} run dates</p>
          </div>
        ) : <p className="text-small text-(--text-muted)">Attendance shows here after your first run.</p>}
      </Card>
    </section>
  )
}

function Stat({ label, value, onClick }: { label: string; value: number; onClick?: () => void }) {
  const inner = (
    <>
      <span className="text-title text-(--text)">{value}</span>
      <span className="text-caption text-(--text-muted)">{label}</span>
    </>
  )
  return onClick ? (
    <button type="button" onClick={onClick} className="flex min-h-14 flex-col items-start rounded-lg text-left active:bg-(--bg-inset)">{inner}</button>
  ) : <div className="flex min-h-14 flex-col items-start">{inner}</div>
}

