// Race people (racepeople.py): the "People" row on race cards and Race readiness, the invite
// sheet (Friends / Share link / Pending), "Racing together" (teammates, opt-in grade and
// finish, group chat, cheers), the invites inbox and "Events you're following" on the Events tab,
// and "Invite to an event" from a friend's card.
import type React from 'react'
import { PersonLink } from '@/components/people/PersonLink'
import { openPerson } from '@/lib/people'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, Copy, ExternalLink, Flag, Link2, Megaphone, Send, UserPlus, Users, X } from 'lucide-react'
import { Avatar } from '@/components/Avatar'
import { RabbitLoader } from '@/components/RabbitLoader'
import { burst } from '@/components/anim'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { Switch } from '@/components/settings/Grouped'
import { Card, Field, areaCls, inputCls } from '@/components/plan/ui'
import { Sheet as UISheet } from '@/components/ui/Sheet'
import { cn } from '@/lib/utils'
import { countdown, daysUntil, listEvents, type RaceEvent } from '@/lib/events'
import { friendPhotoUrl, getPeople, type SocialUser } from '@/lib/social'
import {
  ROLE_LABEL, ROLE_OPTIONS, answerRaceInvite, cheerTeam, getFollowedRaces, getRaceInvites, getRaceMessages, getRacePeople,
  getPeopleSummary, getTogether, inviteLine, inviteToRace, leaveRace, makeCrewLink, postRaceMessage, putCrew, racePhotoUrl, removeRacePerson,
  stopCrewLink,
  type CrewSettings, type FollowedRace, type PeopleSummary, type RaceInvite, type RaceMsg, type RacePeopleView, type RaceRole,
  type Together,
} from '@/lib/racepeople'

const label = 'text-caption font-semibold text-(--text-muted)'
const shortDate = (d: string) => new Date(`${d}T12:00:00`).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })

function PersonAvatar({ u, size = 32, friend }: { u: SocialUser; size?: number; friend?: boolean }) {
  return <Avatar name={u.name} picture={u.picture} photo={friend ? friendPhotoUrl(u) : racePhotoUrl(u)} size={size} />
}

function AvatarStack({ people, size = 24 }: { people: SocialUser[]; size?: number }) {
  return (
    <span className="flex -space-x-2" aria-hidden>
      {people.slice(0, 4).map((u) => <span key={u.id} className="rounded-full ring-2 ring-(--bg-surface)"><PersonAvatar u={u} size={size} /></span>)}
    </span>
  )
}

/** The "People" row under a race card / on Race readiness. */
export function PeopleRow({ s, onOpen, className }: { s?: PeopleSummary; onOpen: () => void; className?: string }) {
  const n = s?.count ?? 0
  const text = !s || (n === 0 && !s.pending) ? (s?.link ? 'Crew link on · invite friends' : 'Invite to this event')
    : `${s.racing ? `${s.racing} racing with you` : `${n} ${n === 1 ? 'person' : 'people'}`}${s.pending ? ` · ${s.pending} invited` : ''}`
  return (
    <button type="button" onClick={onOpen}
      className={cn('flex min-h-12 w-full items-center gap-2.5 border-t border-(--border) px-4 py-2.5 text-left text-body font-medium active:bg-(--bg-inset)', className)}>
      {s && s.people.length > 0 ? <AvatarStack people={s.people} /> : <Users className="size-5 shrink-0 text-(--accent)" />}
      <span className="min-w-0 flex-1 text-(--text-secondary)">{text}</span>
      <span className="flex shrink-0 items-center gap-1 rounded-full bg-(--accent-subtle) px-3 py-1.5 text-meta font-semibold text-(--accent)">
        <UserPlus className="size-4" /> Invite
      </span>
    </button>
  )
}

function Sheet({ title, onClose, children, tabs }: { title: string; onClose: () => void; children: React.ReactNode; tabs?: React.ReactNode }) {
  return <UISheet title={title} label={title} onClose={onClose} below={tabs} bodyClassName="gap-4">{children}</UISheet>
}

function Tabs<T extends string>({ value, options, onChange }: { value: T; options: [T, string, number?][]; onChange: (t: T) => void }) {
  return (
    <div role="tablist" className="mx-4 mb-1 seg flex rounded-full bg-(--bg-inset) p-0.5" style={{ '--seg-i': Math.max(0, options.findIndex(([t]) => t === value)), '--seg-n': options.length } as React.CSSProperties}>
      <span className="seg__pill" aria-hidden />
      {options.map(([t, name, badge]) => (
        <button key={t} type="button" role="tab" aria-selected={value === t} onClick={() => onChange(t)}
          className={cn('hit-44 flex-1 rounded-full py-1.5 text-meta font-medium transition-colors',
            value === t ? 'text-(--text)' : 'text-(--text-muted)')}>
          {name}
          {!!badge && <span className="ml-1 rounded-full bg-(--accent) px-1.5 text-caption font-semibold text-(--on-fill)">{badge}</span>}
        </button>
      ))}
    </div>
  )
}

function RoleChips({ value, onChange }: { value: RaceRole; onChange: (r: RaceRole) => void }) {
  const hint = ROLE_OPTIONS.find(([r]) => r === value)?.[2]
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap gap-2">
        {ROLE_OPTIONS.map(([r, name]) => (
          <button key={r} type="button" onClick={() => onChange(r)} aria-pressed={value === r}
            className={cn('plan-chip', value === r && 'plan-chip--on')}>{name}</button>
        ))}
      </div>
      {hint && <p className="text-meta text-(--text-muted)">{hint}</p>}
    </div>
  )
}

// --------------------------------------------------------------- the sheet --
export function PeopleSheet({ eventId, eventName, onClose, onChanged }: {
  eventId: string; eventName: string; onClose: () => void; onChanged?: () => void
}) {
  const [v, setV] = useState<RacePeopleView | null>(null)
  const [friends, setFriends] = useState<SocialUser[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<'friends' | 'link' | 'pending'>('friends')
  const load = useCallback(() => {
    setError(null)
    getRacePeople(eventId).then(setV, (e) => setError((e as Error).message))
    getPeople().then((p) => {
      const seen = new Map<string, SocialUser>()
      for (const x of [...p.following, ...p.followers]) if (x.user) seen.set(x.user.id, x.user)
      setFriends([...seen.values()])
    }, () => setFriends([]))
  }, [eventId])
  useEffect(() => { load() }, [load])
  const update = (x: RacePeopleView) => { setV(x); onChanged?.() }
  const pending = v?.people.filter((p) => p.status === 'invited') ?? []
  return (
    <Sheet title={`People · ${eventName}`} onClose={onClose}
      tabs={<Tabs value={tab} onChange={setTab} options={[['friends', 'Friends'], ['link', 'Share link'], ['pending', 'Pending', pending.length]]} />}>
      {error && <ErrorState compact message={error} onRetry={load} />}
      {!v && !error && <RabbitLoader className="py-6" label="Loading" cycle={['Finding your crew…', 'Checking the start list…']} />}
      {v && tab === 'friends' && <FriendsTab eventId={eventId} v={v} friends={friends} onUpdate={update} />}
      {v && tab === 'link' && <LinkTab eventId={eventId} v={v} onUpdate={update} />}
      {v && tab === 'pending' && <PendingTab eventId={eventId} people={pending} onUpdate={update} />}
    </Sheet>
  )
}

function FriendsTab({ eventId, v, friends, onUpdate }: {
  eventId: string; v: RacePeopleView; friends: SocialUser[] | null; onUpdate: (x: RacePeopleView) => void
}) {
  const [role, setRole] = useState<RaceRole>('crew')
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null)
  const [other, setOther] = useState('')
  const taken = new Set(v.people.map((p) => p.user_id).filter(Boolean))
  const coming = v.people.filter((p) => p.status === 'accepted')
  async function invite(key: string, body: Parameters<typeof inviteToRace>[1], el?: HTMLElement | null) {
    setBusy(key); setMsg(null)
    try {
      const r = await inviteToRace(eventId, body)
      onUpdate(r); setMsg({ text: r.message ?? 'Invite sent.', ok: true })
      if (el) burst(el, 'kudos')
      if (key === 'other') setOther('')
    } catch (e) { setMsg({ text: (e as Error).message, ok: false }) } finally { setBusy(null) }
  }
  async function remove(pid: string) {
    setBusy(pid)
    try { onUpdate(await removeRacePerson(eventId, pid)) } catch (e) { setMsg({ text: (e as Error).message, ok: false }) } finally { setBusy(null) }
  }
  const pickable = (friends ?? []).filter((f) => !taken.has(f.id))
  return (
    <>
      {coming.length > 0 && (
        <section className="flex flex-col gap-1.5">
          <p className={label}>Coming</p>
          {coming.map((p) => (
            <div key={p.id} className="flex min-h-11 items-center gap-2.5">
              {p.user ? <PersonAvatar u={p.user} /> : <Users className="size-6 text-(--accent)" />}
              <span className="min-w-0 flex-1 truncate text-body text-(--text)">
                {p.user?.name ?? p.coach_email ?? p.email ?? 'Someone'}
              </span>
              <span className="rounded-full bg-(--bg-elevated) px-2 py-0.5 text-caption font-semibold text-(--text-secondary)">{ROLE_LABEL[p.role]}</span>
              <button type="button" aria-label="Remove" className="hit-44 flex size-11 items-center justify-center text-(--text-muted)"
                disabled={busy === p.id} onClick={() => void remove(p.id)}><X className="size-5" /></button>
            </div>
          ))}
        </section>
      )}
      <section className="flex flex-col gap-2">
        <p className={label}>Invite as</p>
        <RoleChips value={role} onChange={setRole} />
      </section>
      <section className="flex flex-col gap-1.5">
        <p className={label}>Your friends</p>
        {friends === null && <div className="skeleton h-11" aria-hidden />}
        {friends !== null && pickable.length === 0 && (
          <p className="text-small text-(--text-muted)">
            {friends.length === 0 ? 'Follow friends (Local → People) to invite them here, or share a link with family and crew.' : 'Everyone on your list is already invited.'}
          </p>
        )}
        {pickable.map((f) => (
          <div key={f.id} className="flex min-h-11 items-center gap-2.5">
            <PersonAvatar u={f} friend />
            <span className="min-w-0 flex-1 truncate text-body text-(--text)">{f.name}</span>
            <Button variant="default" className="h-11 gap-1 px-3 text-meta" loading={busy === f.id}
              onClick={(e) => { const el = e.currentTarget; void invite(f.id, { role, user_id: f.id }, el) }}>
              <UserPlus className="size-4" /> Invite
            </Button>
          </div>
        ))}
      </section>
      {v.coaches.length > 0 && (
        <section className="flex flex-col gap-1.5">
          <p className={label}>Your coach</p>
          {v.coaches.map((c) => (
            <div key={c} className="flex min-h-11 items-center gap-2.5">
              <span className="min-w-0 flex-1 truncate text-body text-(--text)">{c.split('@')[0]}</span>
              <Button variant="default" className="h-11 px-3 text-meta" loading={busy === c}
                onClick={() => void invite(c, { role: 'coach', coach_email: c })}>Add as coach</Button>
            </div>
          ))}
        </section>
      )}
      <Field label="Someone else on rabbt" hint="Their email or invite code. Only friends you follow, or who follow you, get it.">
        <div className="flex gap-2">
          <input className={inputCls} value={other} onChange={(e) => setOther(e.target.value)} placeholder="email or code" autoCapitalize="off" />
          <Button variant="primary" className="h-11 px-3" aria-label="Send invite" disabled={!other.trim()} loading={busy === 'other'}
            onClick={() => void invite('other', other.includes('@') ? { role, email: other.trim() } : { role, code: other.trim() })}>
            <Send className="size-5" />
          </Button>
        </div>
      </Field>
      {msg && <p className={cn('text-small', msg.ok ? 'text-(--accent)' : 'text-(--danger)')} role="status">{msg.text}</p>}
    </>
  )
}

function LinkTab({ eventId, v, onUpdate }: { eventId: string; v: RacePeopleView; onUpdate: (x: RacePeopleView) => void }) {
  const [s, setS] = useState<CrewSettings>(v.settings)
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null)
  const dirty = s.crew_notes !== v.settings.crew_notes || s.tracking_url !== v.settings.tracking_url
  async function run(key: string, fn: () => Promise<Partial<RacePeopleView>>, ok?: string) {
    setBusy(key); setMsg(null)
    try { onUpdate({ ...v, ...(await fn()) }); if (ok) setMsg({ text: ok, ok: true }) }
    catch (e) { setMsg({ text: (e as Error).message, ok: false }) } finally { setBusy(null) }
  }
  const toggle = (k: 'show_finish' | 'show_grade' | 'show_week', val: boolean) => {
    setS((x) => ({ ...x, [k]: val }))
    void run(k, async () => ({ settings: (await putCrew(eventId, { [k]: val })).settings }))
  }
  return (
    <>
      <p className="text-small leading-snug text-(--text-secondary)">
        A private page for crew and family without rabbt: the race, your countdown and your crew notes. Never health data or chats.
      </p>
      {v.share_url ? (
        <div className="flex flex-col gap-2">
          <div className="flex gap-2">
            <input className={cn(inputCls, 'text-small')} readOnly value={v.share_url} onFocus={(e) => e.currentTarget.select()} aria-label="Crew link" />
            <Button variant="primary" className="h-11 gap-1 px-3 text-meta"
              onClick={() => { void navigator.clipboard?.writeText(v.share_url!).then(() => setMsg({ text: 'Link copied.', ok: true }), () => {}) }}>
              <Copy className="size-4" /> Copy
            </Button>
          </div>
          <div className="flex gap-2">
            <Button variant="default" className="h-11 flex-1 text-meta" loading={busy === 'new'}
              onClick={() => void run('new', async () => ({ share_url: (await makeCrewLink(eventId)).url }), 'New link made. The old one stopped working.')}>New link</Button>
            <Button variant="ghost" className="h-11 flex-1 text-meta text-(--danger)" loading={busy === 'off'}
              onClick={() => void run('off', async () => { await stopCrewLink(eventId); return { share_url: null } }, 'Link turned off.')}>Turn off</Button>
          </div>
        </div>
      ) : (
        <Button variant="primary" className="h-11 gap-1.5 text-small" loading={busy === 'new'}
          onClick={() => void run('new', async () => ({ share_url: (await makeCrewLink(eventId)).url }))}>
          <Link2 className="size-5" /> Create crew link
        </Button>
      )}
      <Card>
        <ToggleRow title="Show estimated finish" sub="With a simple pace chart for meeting you" checked={s.show_finish} onChange={(x) => toggle('show_finish', x)} />
        <ToggleRow title="Show readiness grade" sub="Just the letter" checked={s.show_grade} onChange={(x) => toggle('show_grade', x)} />
        <ToggleRow title="Show training this week" sub="Session names and minutes" checked={s.show_week} onChange={(x) => toggle('show_week', x)} />
      </Card>
      <Field label="Crew notes" hint={`Where to meet, aid-station plan, what to hand you. ${1000 - s.crew_notes.length} characters left.`}>
        <textarea className={areaCls} maxLength={1000} value={s.crew_notes} placeholder="e.g. Twin Lakes ~10am: swap bottles, new socks"
          onChange={(e) => setS((x) => ({ ...x, crew_notes: e.target.value }))} />
      </Field>
      <Field label="Official tracking link" hint="Shown on race day. rabbt has no live tracking of its own.">
        <input className={inputCls} value={s.tracking_url} placeholder="https://" inputMode="url" autoCapitalize="off"
          onChange={(e) => setS((x) => ({ ...x, tracking_url: e.target.value }))} />
      </Field>
      <Button variant="primary" className="h-11 text-small" disabled={!dirty} loading={busy === 'save'}
        onClick={() => void run('save', async () => ({ settings: (await putCrew(eventId, { crew_notes: s.crew_notes, tracking_url: s.tracking_url })).settings }), 'Saved.')}>
        Save crew info
      </Button>
      {msg && <p className={cn('text-small', msg.ok ? 'text-(--accent)' : 'text-(--danger)')} role="status">{msg.text}</p>}
    </>
  )
}

function ToggleRow({ title, sub, checked, onChange }: { title: string; sub: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex min-h-11 items-center gap-3 border-b border-(--border) px-4 py-2.5 last:border-b-0">
      <span className="min-w-0 flex-1">
        <span className="block text-body text-(--text)">{title}</span>
        <span className="block text-meta text-(--text-muted)">{sub}</span>
      </span>
      <Switch checked={checked} onChange={onChange} label={title} />
    </div>
  )
}

function PendingTab({ eventId, people, onUpdate }: { eventId: string; people: RacePeopleView['people']; onUpdate: (x: RacePeopleView) => void }) {
  const [busy, setBusy] = useState<string | null>(null)
  if (people.length === 0) return <p className="py-4 text-center text-small text-(--text-muted)">No invites waiting.</p>
  return (
    <section className="flex flex-col gap-1.5">
      {people.map((p) => (
        <div key={p.id} className="flex min-h-11 items-center gap-2.5">
          {p.user ? <PersonAvatar u={p.user} /> : <Users className="size-6 text-(--text-muted)" />}
          <span className="min-w-0 flex-1">
            <span className="block truncate text-body text-(--text)">{p.user?.name ?? p.email}</span>
            <span className="block text-caption text-(--text-muted)">{ROLE_LABEL[p.role]} · waiting</span>
          </span>
          <Button variant="ghost" className="h-11 px-3 text-meta" loading={busy === p.id}
            onClick={async () => { setBusy(p.id); try { onUpdate(await removeRacePerson(eventId, p.id)) } finally { setBusy(null) } }}>Cancel</Button>
        </div>
      ))}
      <p className="text-meta text-(--text-muted)">Invites by email only show the address you typed.</p>
    </section>
  )
}

// ------------------------------------------------------- racing together --
export function RacingTogether({ eventId }: { eventId: string }) {
  const [t, setT] = useState<Together | null>(null)
  const [msgs, setMsgs] = useState<RaceMsg[]>([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [all, setAll] = useState(false)
  const cheerRef = useRef<HTMLButtonElement>(null)
  const load = useCallback(() => {
    getTogether(eventId).then((x) => {
      setT(x)
      if (x.members.length) getRaceMessages(eventId).then((m) => setMsgs(m.messages), () => {})
    }, () => setT(null))
  }, [eventId])
  useEffect(() => { load() }, [load])
  if (!t || t.members.length === 0) return null
  async function send() {
    setBusy('send'); setErr(null)
    try { const r = await postRaceMessage(eventId, text.trim()); setMsgs((m) => [...m, r.message]); setText('') }
    catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }
  async function cheer() {
    setBusy('cheer'); setErr(null)
    try { const r = await cheerTeam(eventId); setMsgs((m) => [...m, r.message]); if (cheerRef.current) burst(cheerRef.current, 'kudos') }
    catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }
  async function share(k: 'team_grade' | 'team_finish', v: boolean) {
    setT((x) => x && { ...x, me: { ...x.me, [k]: v } })
    try { await putCrew(eventId, { [k]: v }) } catch (e) { setErr((e as Error).message) }
  }
  const shown = all ? msgs : msgs.slice(-6)
  return (
    <Card>
      <Field label="Racing together">
        <div className="flex flex-col gap-2">
          {t.members.map((m, i) => m.user && (
            <div key={m.user.id + i} className="flex min-h-11 items-center gap-2.5">
              <button type="button" className="shrink-0 rounded-full" aria-label={`Open ${m.user.name}'s profile`} onClick={() => openPerson(m.user!.id)}><PersonAvatar u={m.user} size={36} /></button>
              <span className="min-w-0 flex-1">
                <PersonLink id={m.user.id} name={m.user.name} className="block truncate text-body-lg font-medium text-(--text)" />
                <span className="block text-meta text-(--text-muted)">{countdown(m.date)}{m.finish ? ` · ~${m.finish}` : ''}</span>
              </span>
              {m.grade && <span className="rounded-full bg-(--accent-subtle) px-2 py-0.5 font-mono text-meta font-semibold text-(--accent)">{m.grade}</span>}
            </div>
          ))}
          <Button ref={cheerRef} variant="default" className="press h-11 w-fit gap-1.5 text-small" loading={busy === 'cheer'} onClick={() => void cheer()}>
            <Megaphone className="size-5" /> Cheer
          </Button>
        </div>
        <div className="flex flex-col gap-1.5 border-t border-(--border) pt-2.5">
          <p className={label}>Race chat</p>
          {msgs.length > 6 && !all && (
            <button type="button" className="hit-44 w-fit text-meta text-(--accent)" onClick={() => setAll(true)}>Show all {msgs.length}</button>
          )}
          {shown.length === 0 && <p className="text-small text-(--text-muted)">Say hi, plan the drive, swap pacing ideas.</p>}
          {shown.map((m) => (
            <p key={m.id} className={cn('max-w-[85%] rounded-xl px-3 py-1.5 text-body leading-snug',
              m.mine ? 'self-end bg-(--accent-subtle) text-(--text)' : 'self-start bg-(--bg-inset) text-(--text)')}>
              {!m.mine && <b className="mr-1 text-meta text-(--text-secondary)">{m.by.name}</b>}
              {m.kind === 'cheer' ? `📣 ${m.text || 'Let’s go!'}` : m.text}
            </p>
          ))}
          <div className="flex gap-2">
            <input className={inputCls} value={text} maxLength={500} placeholder="Message your teammates" aria-label="Message"
              onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && text.trim()) void send() }} />
            <Button variant="primary" className="h-11 px-3" aria-label="Send" disabled={!text.trim()} loading={busy === 'send'} onClick={() => void send()}>
              <Send className="size-5" />
            </Button>
          </div>
        </div>
        <div className="border-t border-(--border) pt-1">
          <ToggleRow title="Share my readiness grade" sub="With teammates on this event" checked={t.me.team_grade} onChange={(v) => void share('team_grade', v)} />
          <ToggleRow title="Share my estimated finish" sub="With teammates on this event" checked={t.me.team_finish} onChange={(v) => void share('team_finish', v)} />
        </div>
        {err && <p className="text-meta text-(--danger)" role="alert">{err}</p>}
      </Field>
    </Card>
  )
}

// ------------------------------------------------------- races tab: inbox --
export function RaceInvitesInbox({ onChanged }: { onChanged?: () => void }) {
  const [inv, setInv] = useState<RaceInvite[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { getRaceInvites().then((r) => setInv(r.invites), () => {}) }, [])
  if (inv.length === 0) return null
  async function answer(i: RaceInvite, accept: boolean, el: HTMLElement) {
    setBusy(i.id); setErr(null)
    try {
      await answerRaceInvite(i.id, accept)
      if (accept) burst(el, 'race')
      setInv((x) => x.filter((y) => y.id !== i.id)); onChanged?.()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }
  return (
    <section className="flex flex-col gap-2" aria-label="Event invites">
      {inv.map((i) => (
        <div key={i.id} className="flex flex-col gap-2 rounded-xl border border-(--accent)/40 bg-(--accent-subtle) px-3.5 py-3">
          <div className="flex items-center gap-2.5">
            {i.from && <PersonAvatar u={i.from} size={36} />}
            <p className="min-w-0 flex-1 text-body leading-snug text-(--text)">
              {inviteLine(i.from?.name ?? 'A friend', i.role, i.event.name)}
              <span className="block text-meta text-(--text-muted)">{shortDate(i.event.date)}{i.event.location ? ` · ${i.event.location}` : ''}</span>
            </p>
          </div>
          {i.role === 'racing' && <p className="text-meta text-(--text-secondary)">Accepting adds it to your events.</p>}
          <div className="flex gap-2">
            <Button variant="primary" className="press h-11 flex-1 text-small" loading={busy === i.id}
              onClick={(e) => { const el = e.currentTarget; void answer(i, true, el) }}>Accept</Button>
            <Button variant="default" className="h-11 flex-1 text-small" disabled={busy === i.id}
              onClick={(e) => { const el = e.currentTarget; void answer(i, false, el) }}>Decline</Button>
          </div>
        </div>
      ))}
      {err && <p className="px-1 text-meta text-(--danger)" role="alert">{err}</p>}
    </section>
  )
}

// ------------------------------------------------- races tab: following --
export function FollowingRaces({ refreshKey = 0 }: { refreshKey?: number }) {
  const [races, setRaces] = useState<FollowedRace[]>([])
  useEffect(() => { getFollowedRaces().then((r) => setRaces(r.races.filter((x) => daysUntil(x.event.date) >= -1)), () => {}) }, [refreshKey])
  if (races.length === 0) return null
  return (
    <section className="flex flex-col gap-2">
      <h2 className="font-sans px-1 text-caption font-semibold text-(--text-muted)">Events you're following</h2>
      {races.map((r) => <FollowedCard key={r.id} r={r} onLeave={() => setRaces((x) => x.filter((y) => y.id !== r.id))} />)}
    </section>
  )
}

function FollowedCard({ r, onLeave }: { r: FollowedRace; onLeave: () => void }) {
  const [open, setOpen] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const n = daysUntil(r.event.date)
  const link = r.tracking_url || r.event.url
  return (
    <div className="overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)">
      {n === 0 && (
        <div className="flex flex-col gap-1 bg-(--accent) px-3.5 py-2.5 text-(--on-fill)">
          <p className="flex items-center gap-1.5 text-body font-semibold"><Flag className="size-5" /> Race day!</p>
          <p className="text-meta leading-snug opacity-90">
            rabbt doesn't do live tracking. {link ? 'Follow along on the ' : ''}
            {link && <a href={link} target="_blank" rel="noopener noreferrer" className="underline">{r.tracking_url ? 'official tracker' : 'race website'}</a>}
          </p>
        </div>
      )}
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="flex min-h-11 w-full items-center gap-3 px-3.5 py-3 text-left active:bg-(--bg-inset)">
        {r.athlete && <PersonAvatar u={r.athlete} size={36} />}
        <span className="min-w-0 flex-1">
          <span className="block truncate text-lead font-medium text-(--text)">{r.event.name}</span>
          <span className="block truncate text-meta text-(--text-muted)">
            {r.athlete?.name ?? 'Friend'} · {shortDate(r.event.date)}{r.event.location ? ` · ${r.event.location}` : ''}
          </span>
        </span>
        <span className="flex shrink-0 flex-col items-end gap-1">
          <span className="rounded-full bg-(--bg-elevated) px-2 py-0.5 text-caption font-semibold text-(--text-secondary)">{ROLE_LABEL[r.role]}</span>
          <span className="text-caption text-(--text-muted)">{countdown(r.event.date)}</span>
        </span>
      </button>
      {open && (
        <div className="flex flex-col gap-2 border-t border-(--border) px-3.5 py-3 text-small">
          <p className={label}>Crew notes</p>
          <p className="whitespace-pre-wrap leading-snug text-(--text)">{r.crew_notes || 'No crew notes yet.'}</p>
          {r.event.start_time && <p className="text-(--text-secondary)">Start: {r.event.start_time}</p>}
          {link && n !== 0 && (
            <a href={link} target="_blank" rel="noopener noreferrer" className="hit-44 flex w-fit items-center gap-1 text-(--accent)">
              <ExternalLink className="size-4" /> {r.tracking_url ? 'Tracking link' : 'Race website'}
            </a>
          )}
          {confirm ? (
            <div className="flex items-center gap-2">
              <span className="flex-1 text-(--text-secondary)">Stop following this event?</span>
              <Button variant="default" className="h-11 px-3 text-meta" onClick={() => setConfirm(false)}>Keep</Button>
              <Button variant="destructive" className="h-11 px-3 text-meta"
                onClick={() => { void leaveRace(r.id).then(onLeave, () => setConfirm(false)) }}>Stop</Button>
            </div>
          ) : (
            <button type="button" className="hit-44 w-fit text-meta text-(--text-muted)" onClick={() => setConfirm(true)}>Stop following</button>
          )}
        </div>
      )}
    </div>
  )
}

// -------------------------------------------------- friends: invite to race --
export function InviteToRaceSheet({ friend, onClose }: { friend: SocialUser; onClose: () => void }) {
  const [events, setEvents] = useState<RaceEvent[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [role, setRole] = useState<RaceRole>('racing')
  const [busy, setBusy] = useState<string | null>(null)
  const [done, setDone] = useState<Record<string, string>>({})
  useEffect(() => {
    listEvents().then((r) => setEvents(r.events.filter((e) => daysUntil(e.date) >= 0)), (e) => setError((e as Error).message))
  }, [])
  async function invite(e: RaceEvent) {
    setBusy(e.id)
    try { const r = await inviteToRace(e.id, { role, user_id: friend.id }); setDone((d) => ({ ...d, [e.id]: r.message ?? 'Invite sent.' })) }
    catch (x) { setDone((d) => ({ ...d, [e.id]: (x as Error).message })) } finally { setBusy(null) }
  }
  return (
    <Sheet title={`Invite ${friend.name} to an event`} onClose={onClose}>
      <RoleChips value={role} onChange={setRole} />
      {error && <ErrorState compact message={error} />}
      {!events && !error && <div className="skeleton h-14" aria-hidden />}
      {events && events.length === 0 && <p className="text-small text-(--text-muted)">Add an event in Schedule → Events first.</p>}
      {events?.map((e) => (
        <div key={e.id} className="flex min-h-11 items-center gap-2.5">
          <span className="min-w-0 flex-1">
            <span className="block truncate text-body-lg text-(--text)">{e.name}</span>
            <span className="block truncate text-meta text-(--text-muted)">{done[e.id] ?? `${shortDate(e.date)} · ${countdown(e.date)}`}</span>
          </span>
          <Button variant={done[e.id] ? 'ghost' : 'default'} className="h-11 gap-1 px-3 text-meta" loading={busy === e.id}
            disabled={!!done[e.id]} onClick={() => void invite(e)}>
            {done[e.id] ? <Check className="size-5" /> : <><UserPlus className="size-4" /> Invite</>}
          </Button>
        </div>
      ))}
    </Sheet>
  )
}

// ------------------------------------------------- race readiness section --
/** Race readiness: the People row (opens the invite sheet) + "Racing together". */
export function RacePeopleSection({ eventId, eventName }: { eventId: string; eventName: string }) {
  const [s, setS] = useState<PeopleSummary | undefined>(undefined)
  const [open, setOpen] = useState(false)
  const [key, setKey] = useState(0)
  useEffect(() => { getPeopleSummary().then((r) => setS(r.events[eventId]), () => {}) }, [eventId, key])
  return (
    <>
      <div className="overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)">
        <PeopleRow s={s} onOpen={() => setOpen(true)} className="border-t-0" />
      </div>
      <RacingTogether key={key} eventId={eventId} />
      {open && <PeopleSheet eventId={eventId} eventName={eventName} onClose={() => setOpen(false)} onChanged={() => setKey((k) => k + 1)} />}
    </>
  )
}
