// Community → Clubs: your clubs (race groups appear on their own), invites, clubs near you,
// "Clubs & leagues near you" (Rabbit's public-web directory, Directory.tsx), create / join by code, and a club page
// (feed, meetups with RSVP, club challenges, members and join requests).
import type React from 'react'
import { confirmAsk } from '@/lib/confirm'
import { useRefreshOnShow } from '@/hooks/useRefreshOnShow'
import { useCallback, useEffect, useState } from 'react'
import { useDraft } from '@/lib/drafts'
import { saveDurably } from '@/lib/outbox'
import { SaveStatus } from '@/components/ui/SaveStatus'
import { DraftRestored, useUnsavedGuard } from '@/components/ui/UnsavedGuard'
import {
  Check, ChevronRight, Copy, Flag, LogOut, MapPin, Plus, Repeat, Trash2, Trophy, UserPlus, X,
} from 'lucide-react'
import { RabbitLoader } from '@/components/RabbitLoader'
import { EmptyRabbit, HopIn, burst } from '@/components/anim'
import { Button } from '@/components/ui/button'
import { ShareButton } from '@/components/ui/ShareSheet'
import { ErrorState } from '@/components/ui/ErrorState'
import { Group, Row } from '@/components/settings/Grouped'
import { Card, Field, OptionCard, Screen, inputCls } from '@/components/plan/ui'
import { PublicEventsNear } from '@/components/events/PublicEventsNear'
import { getChallenges, targetLine, type Suggestion } from '@/lib/challenges'
import { getPeople, type SocialUser } from '@/lib/social'
import { cn } from '@/lib/utils'
import {
  LEVELS, SPORTS, answerClubInvite, cancelJoinRequest, decideRequest, deleteClub, deleteMeetup,
  getClub, getClubs, inviteToClub, joinClub, joinClubByCode, joinClubChallenge, leaveClub, meetupWhen, newClubCode,
  removeMember, rsvpMeetup, setMemberRole, startClubChallenge,
  type ClubDetail, type ClubInput, type ClubSummary, type ClubsView, type Level, type Meetup, type Sport,
} from '@/lib/community'
import { clubSport, linkListing, type DirListing } from '@/lib/clubdir'
import { Choice } from './Choice'
import { ClubDirectory } from './Directory'
import { FeatureSwitch } from './Featured'
import { CommunityFeed, PersonAvatar } from './Feed'
import { Sheet } from '@/components/ui/Sheet'
import { PersonAvatar as TapAvatar, PersonLink } from '@/components/people/PersonLink'
import { Related } from '@/components/nav/Related'
import { openClubChat } from '@/lib/people'
import { openConversation } from '@/lib/dm'
import { MessagesSquare, Users } from 'lucide-react'

const LOADING = ['Rounding up the crew…', 'Finding clubs near you…', 'Lacing up…']
const EMOJIS = ['🐇', '🏃', '🏃‍♀️', '🚴', '🏊', '⛰️', '🏔️', '🌅', '🔥', '🏁', '💪', '🌲', '☕', '🍻']
const SPORT_LABEL = Object.fromEntries(SPORTS) as Record<Sport, string>
const LEVEL_LABEL = Object.fromEntries(LEVELS) as Record<Level, string>

function ClubIcon({ c, size = 40 }: { c: Pick<ClubSummary, 'emoji'>; size?: number }) {
  return (
    <span className="flex shrink-0 items-center justify-center rounded-xl bg-(--accent-subtle)"
      style={{ width: size, height: size, fontSize: size * 0.5 }} aria-hidden>{c.emoji || '🐇'}</span>
  )
}

const where = (c: Pick<ClubSummary, 'city' | 'state'>) => [c.city, c.state].filter(Boolean).join(', ')
const sub = (c: ClubSummary) => [SPORT_LABEL[c.sport] ?? null, where(c) || null, `${c.members} member${c.members === 1 ? '' : 's'}`]
  .filter(Boolean).join(' · ')

export function ClubsTab({ imperial, openId, onOpen }: { imperial: boolean; openId: string | null; onOpen: (id: string | null) => void }) {
  const [data, setData] = useState<ClubsView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [startFrom, setStartFrom] = useState<DirListing | null>(null)
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null)
  const load = useCallback(() => getClubs().then((d) => { setData(d); setError(null) }, (e) => setError((e as Error).message)), [])
  useEffect(() => { void load() }, [load])
  useRefreshOnShow(() => load())

  async function run(key: string, fn: () => Promise<{ message?: string } | unknown>, ok?: string) {
    setBusy(key); setMsg(null)
    try {
      const r = await fn()
      const m = (r && typeof r === 'object' && 'message' in r && typeof r.message === 'string') ? r.message : ok
      if (m) setMsg({ text: m, ok: true })
      await load()
    } catch (e) { setMsg({ text: (e as Error).message, ok: false }) } finally { setBusy(null) }
  }
  if (error && !data) return <ErrorState compact message={error} onRetry={() => void load()} />
  if (!data) return <RabbitLoader className="py-10" label="Loading clubs" cycle={LOADING} />
  const races = data.clubs.filter((c) => c.kind === 'race')
  const mine = data.clubs.filter((c) => c.kind === 'club')
  const near = data.discover
  const home = where(data.home)
  const joinBtn = (c: ClubSummary) => c.requested ? (
    <Button variant="default" className="h-11 px-3 text-meta" loading={busy === c.id}
      onClick={() => void run(c.id, () => cancelJoinRequest(c.id), 'Request withdrawn.')}>Requested</Button>
  ) : (
    <Button variant="primary" className="h-11 px-3 text-meta" loading={busy === c.id}
      onClick={(e) => { const el = e.currentTarget; void run(c.id, async () => { const r = await joinClub(c.id); if (!r.club.requested) burst(el, 'kudos'); return r }) }}>
      {c.privacy === 'open' ? 'Join' : 'Ask to join'}
    </Button>
  )
  return (
    <>
      {msg && <p className={cn('px-1 text-small', msg.ok ? 'text-(--accent)' : 'text-(--danger)')} role="status">{msg.text}</p>}
      {data.invites.length > 0 && (
        <Group label="Invites">
          {data.invites.map((c) => (
            <Row key={c.id} icon={<ClubIcon c={c} size={30} />} title={c.name}
              subtitle={c.invited_by ? `${c.invited_by.name} invited you` : sub(c)}
              trailing={
                <span className="flex shrink-0 gap-1.5">
                  <Button variant="default" className="h-11 w-11 p-0" aria-label="Decline" disabled={busy != null}
                    onClick={() => void run(c.id, () => answerClubInvite(c.id, false))}><X className="size-5" /></Button>
                  <Button variant="primary" className="h-11 gap-1 px-3" loading={busy === c.id}
                    onClick={() => void run(c.id, () => answerClubInvite(c.id, true), `Welcome to ${c.name}!`)}><Check className="size-5" /> Join</Button>
                </span>
              } />
          ))}
        </Group>
      )}

      {mine.length > 0 && (
        <Group label="Your clubs">
          {mine.map((c) => (
            <Row key={c.id} icon={<ClubIcon c={c} size={30} />} title={c.name}
              subtitle={`${sub(c)}${c.requests ? ` · ${c.requests} waiting` : ''}`}
              trailing={<ChevronRight className="size-5 text-(--text-muted)" />} onClick={() => onOpen(c.id)} />
          ))}
        </Group>
      )}
      {races.length > 0 && (
        <Group label="Race crews" footer="Everyone racing the same event with you.">
          {races.map((c) => (
            <Row key={c.id} icon={<ClubIcon c={c} size={30} />} title={c.name} subtitle={`${c.members} racing`}
              trailing={<ChevronRight className="size-5 text-(--text-muted)" />} onClick={() => onOpen(c.id)} />
          ))}
        </Group>
      )}
      {/* One search (names, partners, public listings) lives in the directory, partners first. */}
      <ClubDirectory imperial={imperial} onStartGroup={(l) => (l ? setStartFrom(l) : setCreating(true))} />
      <PublicEventsNear />

      {near.length > 0 && (
        <Group label={home ? `rabbt clubs near ${home}` : 'rabbt clubs to join'}>
          {near.map((c, i) => (
            <HopIn key={c.id} index={i} play={i < 5}>
              <Row icon={<ClubIcon c={c} size={30} />} title={c.name} subtitle={c.description || sub(c)}
                onClick={() => onOpen(c.id)} trailing={joinBtn(c)} />
            </HopIn>
          ))}
        </Group>
      )}

      <section aria-label="Your own club" className="flex flex-col gap-3 rounded-xl border border-(--border) bg-(--bg-surface) p-4">
        <div>
          <p className="text-body font-semibold text-(--text)">Have your own crew?</p>
          <p className="text-meta text-(--text-muted)">Start a club for your Saturday group, or join one with its code.</p>
        </div>
        <Button variant="default" className="h-11 gap-1.5 text-small" onClick={() => setCreating(true)}>
          <Plus className="size-5" /> Start a club
        </Button>
        <div className="flex items-center gap-2">
          <input className={inputCls} aria-label="Club code" autoCapitalize="characters" autoComplete="off" placeholder="Club code, like ABCD2345" value={code}
            onChange={(e) => setCode(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && code.trim()) void run('code', () => joinClubByCode(code.trim()).then((r) => { setCode(''); return r }), "You're in!") }} />
          <Button variant="default" className="h-11 shrink-0 px-3 text-small" loading={busy === 'code'} disabled={!code.trim()}
            onClick={() => void run('code', () => joinClubByCode(code.trim()).then((r) => { setCode(''); return r }), "You're in!")}>Join</Button>
        </div>
      </section>
      {(creating || startFrom) && (
        <ClubSheet home={data.home}
          prefill={startFrom ? { name: startFrom.name.slice(0, 40), sport: clubSport(startFrom.kind), description: startFrom.description.slice(0, 300) } : undefined}
          onClose={() => { setCreating(false); setStartFrom(null) }}
          onSaved={(c) => {
            if (startFrom) void linkListing(startFrom.id, c.id).catch(() => undefined)
            setCreating(false); setStartFrom(null); void load(); onOpen(c.id)
          }} />
      )}
      {openId && <ClubPage id={openId} imperial={imperial} onClose={() => { onOpen(null); void load() }} />}
    </>
  )
}

function ClubSheet({ initial, prefill, home, onClose, onSaved }: {
  initial?: ClubSummary; prefill?: ClubInput; home?: { city: string; state: string }; onClose: () => void; onSaved: (c: ClubSummary) => void
}) {
  const [f, setF, draft] = useDraft<Required<ClubInput>>(`club.${initial?.id ?? 'new'}`, () => ({
    name: initial?.name ?? prefill?.name ?? '', sport: initial?.sport ?? prefill?.sport ?? 'running', city: initial?.city ?? home?.city ?? '',
    state: initial?.state ?? home?.state ?? '', description: initial?.description ?? prefill?.description ?? '', emoji: initial?.emoji || '🐇',
    privacy: initial?.privacy ?? 'open', visibility: initial?.visibility ?? 'public',
  }), { label: initial ? 'club changes' : 'new club' })
  const guard = useUnsavedGuard(draft.dirty, draft.discard)
  const [busy, setBusy] = useState(false)
  const [queued, setQueued] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const set = <K extends keyof ClubInput>(k: K, v: Required<ClubInput>[K]) => setF((x) => ({ ...x, [k]: v }))
  async function save() {
    setBusy(true); setErr(null); setQueued(false)
    try {
      const b = { ...f, name: f.name.trim(), description: f.description.trim(), city: f.city.trim(), state: f.state.trim() }
      const r = await saveDurably<{ club: ClubSummary }>(initial
        ? { method: 'PATCH', path: `/api/community/clubs/${encodeURIComponent(initial.id)}`, body: b, label: 'club', coalesce: `club.${initial.id}` }
        : { method: 'POST', path: '/api/community/clubs', body: b, label: 'club' }, () => setQueued(true))
      draft.clear()
      onSaved(r.club)
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false); setQueued(false) }
  }
  return (
    <Sheet title={initial ? 'Edit club' : 'Start a club'} onClose={guard.wrap(onClose)} extra={guard.dialog}
      footer={
        <Button variant="primary" className="h-11 w-full text-body" loading={busy} disabled={!f.name.trim()} onClick={() => void save()}>
          {!f.name.trim() ? 'Give your club a name' : initial ? 'Save changes' : 'Start club'}
        </Button>
      }>
      {draft.restored && <DraftRestored onDiscard={draft.discard} />}
      <Field label="Name"><input className={inputCls} maxLength={40} value={f.name} onChange={(e) => set('name', e.target.value)} placeholder="Wash Park Run Club" /></Field>
      <Field label="Sport"><Choice label="Sport" value={f.sport} options={SPORTS} onChange={(v) => set('sport', v)} /></Field>
      <div className="grid grid-cols-[2fr_1fr] gap-2">
        <Field label="City"><input className={inputCls} maxLength={40} value={f.city} onChange={(e) => set('city', e.target.value)} placeholder="Denver" /></Field>
        <Field label="State"><input className={inputCls} maxLength={20} value={f.state} onChange={(e) => set('state', e.target.value)} placeholder="CO" /></Field>
      </div>
      <Field label="What's it about? (optional)">
        <input className={inputCls} maxLength={300} value={f.description} onChange={(e) => set('description', e.target.value)} placeholder="Easy miles Saturdays, coffee after" />
      </Field>
      <Field label="Icon">
        <div className="flex flex-wrap gap-1" role="radiogroup" aria-label="Icon">
          {EMOJIS.map((e) => (
            <button key={e} type="button" role="radio" aria-checked={f.emoji === e} onClick={() => set('emoji', e)}
              className={cn('flex size-11 items-center justify-center rounded-xl text-title-md', f.emoji === e ? 'bg-(--accent-subtle) ring-1 ring-(--accent)' : 'bg-(--bg-inset)')}>{e}</button>
          ))}
        </div>
      </Field>
      <section aria-label="Who can find and join it" className="flex flex-col gap-2">
        <h2 className="px-1 text-caption font-semibold text-(--text-muted)">Who can find and join it</h2>
        <OptionCard selected={f.visibility !== 'private' && f.privacy === 'open'} title="Public · anyone can join"
          description="Shows up in Local and search for people nearby." onClick={() => setF((x) => ({ ...x, visibility: 'public', privacy: 'open' }))} />
        <OptionCard selected={f.visibility !== 'private' && f.privacy === 'approval'} title="Public · ask to join"
          description="People nearby find it and ask; you or an admin say yes." onClick={() => setF((x) => ({ ...x, visibility: 'public', privacy: 'approval' }))} />
        <OptionCard selected={f.visibility === 'private'} title="Private · invite only"
          description="Hidden from Local and search. People join with an invite or the club code." onClick={() => setF((x) => ({ ...x, visibility: 'private', privacy: 'open' }))} />
      </section>
      {queued && <SaveStatus state="queued" />}
      {err && <p className="text-meta text-(--danger)" role="alert">{err}</p>}
    </Sheet>
  )
}

// ------------------------------------------------------------- club page ---
type ClubView = 'feed' | 'meetups' | 'challenges' | 'members'

function ClubPage({ id, imperial, onClose }: { id: string; imperial: boolean; onClose: () => void }) {
  const [c, setC] = useState<ClubDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<ClubView>('feed')
  const [closing, setClosing] = useState(false)
  const [sheet, setSheet] = useState<'edit' | 'invite' | 'meetup' | 'challenge' | null>(null)
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)
  const close = () => { setClosing(true); setTimeout(onClose, 200) }
  const load = useCallback(() => getClub(id).then((r) => { setC(r.club); setError(null) }, (e) => setError((e as Error).message)), [id])
  useEffect(() => { void load() }, [load])

  const admin = c?.role === 'owner' || c?.role === 'admin'
  const member = !!c?.role
  const canInvite = !!c && c.kind === 'club' && member && (admin || c.privacy === 'open')
  async function act(fn: () => Promise<unknown>, ok?: string, after?: () => void) {
    setMsg(null)
    try {
      const r = await fn()
      if (r && typeof r === 'object' && 'club' in r && r.club && typeof r.club === 'object' && 'people' in r.club) setC(r.club as ClubDetail)
      if (ok) setMsg({ text: ok, ok: true })
      if (after) after(); else void load()
    } catch (e) { setMsg({ text: (e as Error).message, ok: false }) }
  }
  const [chatBusy, setChatBusy] = useState(false)
  async function groupChat() {
    if (!c) return
    setChatBusy(true)
    try { const r = await openClubChat(c.id); openConversation(r.conv.id) } catch (e) { setMsg({ text: (e as Error).message, ok: false }) } finally { setChatBusy(false) }
  }
  async function copy(code: string) {
    try { await navigator.clipboard.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 1500) }
    catch { setMsg({ text: `The code is ${code}`, ok: true }) }
  }
  const tabs: [ClubView, string][] = c?.kind === 'race' ? [['feed', 'Feed'], ['members', 'Crew']]
    : [['feed', 'Feed'], ['meetups', 'Meetups'], ['challenges', 'Challenges'], ['members', 'Members']]
  const seg = member ? (
    <div role="tablist" aria-label="Club" className="mx-auto mt-2 seg flex max-w-xl rounded-full bg-(--bg-inset) p-0.5" style={{ '--seg-i': Math.max(0, tabs.findIndex(([v]) => v === view)), '--seg-n': tabs.length } as React.CSSProperties}>
      <span className="seg__pill" aria-hidden />
      {tabs.map(([v, label]) => (
        <button key={v} type="button" role="tab" aria-selected={view === v} onClick={() => setView(v)}
          className={cn('min-h-11 flex-1 rounded-full text-meta font-medium', view === v ? 'text-(--text)' : 'text-(--text-muted)')}>
          {label}{v === 'members' && c?.pending.length ? ` · ${c.pending.length}` : ''}
        </button>
      ))}
    </div>
  ) : undefined
  const subtitle = c ? [c.kind === 'club' ? SPORT_LABEL[c.sport] : null, where(c) || null, `${c.members} member${c.members === 1 ? '' : 's'}`].filter(Boolean).join(' · ') : undefined
  return (
    <Screen title={c?.name ?? 'Club'} subtitle={subtitle} closing={closing} onBack={close} onClose={close} headerExtra={seg}>
      {error && <ErrorState compact message={error} onRetry={() => void load()} />}
      {!c && !error && <RabbitLoader className="py-10" label="Loading club" cycle={LOADING} />}
      {c && !member && (
        <Card className="flex flex-col items-center gap-3 p-5 text-center">
          <ClubIcon c={c} size={64} />
          <p className="font-display text-title-md text-(--brand)">{c.name}</p>
          {c.description && <p className="text-body text-(--text-secondary)">{c.description}</p>}
          <p className="text-meta text-(--text-muted)">{c.visibility === 'private' ? 'A private club: you were invited.' : c.privacy === 'open' ? 'Anyone on rabbt can join.' : 'Admins approve new members.'}</p>
          {c.requested ? (
            <Button variant="default" className="h-11 px-5 text-small" loading={busy}
              onClick={() => { setBusy(true); void act(() => cancelJoinRequest(c.id), 'Request withdrawn.').finally(() => setBusy(false)) }}>Requested · withdraw</Button>
          ) : (
            <Button variant="primary" className="h-11 px-5 text-small" loading={busy}
              onClick={(e) => { const el = e.currentTarget; setBusy(true); void act(async () => { const r = await joinClub(c.id); if (!r.club.requested) burst(el, 'kudos'); setMsg({ text: r.message, ok: true }) }).finally(() => setBusy(false)) }}>
              {c.privacy === 'open' ? 'Join club' : 'Ask to join'}
            </Button>
          )}
        </Card>
      )}
      {msg && <p className={cn('px-1 text-small', msg.ok ? 'text-(--accent)' : 'text-(--danger)')} role="status">{msg.text}</p>}
      {c && c.kind === 'club' && (!member || view === 'members') && <FeatureSwitch clubId={c.id} />}
      {c && member && (
        <>
          {view === 'feed' && (
            <>
              <Button variant="default" className="h-11 gap-1.5 text-small" loading={chatBusy} onClick={() => void groupChat()}>
                <MessagesSquare className="size-5" aria-hidden /> {c.kind === 'race' ? 'Crew chat' : 'Club chat'}
              </Button>
              {c.upcoming.length > 0 && (
                <section aria-label="Upcoming races" className="-mx-4 flex snap-x gap-2 overflow-x-auto px-4 pb-1">
                  {c.upcoming.map((u) => (
                    <div key={`${u.name}-${u.date}`} className="flex min-w-[11rem] snap-start flex-col gap-1 rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-2">
                      <span className="flex items-center gap-1 text-caption font-semibold text-(--accent)"><Flag className="size-3.5" /> Racing</span>
                      <span className="truncate text-body font-medium text-(--text)">{u.name}</span>
                      <span className="text-meta text-(--text-muted)">{new Date(`${u.date}T12:00:00`).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })}</span>
                      <span className="flex -space-x-1.5">{u.people.slice(0, 5).map((p, i) => <PersonAvatar key={p?.id ?? i} u={p} size={22} />)}</span>
                    </div>
                  ))}
                </section>
              )}
              {c.meetups && c.meetups.length > 0 && (
                <MeetupCard m={c.meetups[0]} clubId={c.id} admin={admin} onChanged={load} onError={(t) => setMsg({ text: t, ok: false })} />
              )}
              <CommunityFeed imperial={imperial} clubId={c.id} clubName={c.name} />
            </>
          )}
          {view === 'meetups' && (
            <>
              {admin && (
                <Button variant="primary" className="h-11 gap-1.5 text-small" onClick={() => setSheet('meetup')}>
                  <Plus className="size-5" /> Plan a meetup
                </Button>
              )}
              {(c.meetups ?? []).length === 0 ? (
                <EmptyRabbit size={48} mode="peek" title="No meetups planned"
                  body={admin ? 'Plan a group run or ride: when, where and the pace.' : 'When an admin plans one, it shows up here.'} />
              ) : (c.meetups ?? []).map((m) => (
                <MeetupCard key={m.id} m={m} clubId={c.id} admin={admin} onChanged={load} onError={(t) => setMsg({ text: t, ok: false })} />
              ))}
            </>
          )}
          {view === 'challenges' && (
            <>
              {c.can_challenge && (
                <Button variant="primary" className="h-11 gap-1.5 text-small" onClick={() => setSheet('challenge')}>
                  <Trophy className="size-5" /> Start a club challenge
                </Button>
              )}
              {c.challenges.length === 0 ? (
                <EmptyRabbit size={48} mode="peek" title="No club challenges yet"
                  body={c.can_challenge ? 'Pick one of your challenges and the whole club can join in.' : 'When an admin starts one, everyone can join.'} />
              ) : c.challenges.map((ch) => (
                <Card key={ch.id} className="flex flex-col gap-2 p-3.5">
                  <div className="flex items-start gap-2">
                    <Trophy className="mt-0.5 size-5 shrink-0 text-(--accent)" />
                    <div className="min-w-0 flex-1">
                      <p className="text-body-lg font-medium text-(--text)">{ch.name}</p>
                      <p className="text-meta text-(--text-muted)">{targetLine(ch, imperial)} · {ch.participants} in · +{ch.xp} XP</p>
                    </div>
                    {ch.joined ? <span className="text-meta font-medium text-(--accent)">You're in</span> : (
                      <Button variant="primary" className="h-11 px-3 text-meta"
                        onClick={(e) => { const el = e.currentTarget; void act(async () => { const r = await joinClubChallenge(c.id, ch.id); burst(el, 'challenge'); return r }, "You're in. Progress counts from your Garmin.") }}>Join</Button>
                    )}
                  </div>
                  {ch.leaders.some((l) => l.pct != null) && (
                    <ol className="flex flex-col gap-1">
                      {ch.leaders.map((l, i) => (
                        <li key={l.user_id} className="flex items-center gap-2 text-small">
                          <span className="w-4 text-right tabular-nums text-(--text-muted)">{i + 1}</span>
                          <span className={cn('min-w-0 flex-1 truncate', l.me && 'font-semibold text-(--accent)')}>{l.me ? 'You' : l.name}</span>
                          <span className="tabular-nums text-(--text-secondary)">{l.pct != null ? `${l.pct}%` : '–'}</span>
                        </li>
                      ))}
                    </ol>
                  )}
                </Card>
              ))}
            </>
          )}
          {view === 'members' && (
            <>
              {admin && c.pending.length > 0 && (
                <Group label="Asking to join">
                  {c.pending.filter((u): u is SocialUser => !!u).map((u) => (
                    <Row key={u.id} icon={<TapAvatar p={u} size={30} />} title={<PersonLink id={u.id} name={u.name} />}
                      trailing={
                        <span className="flex gap-1.5">
                          <Button variant="default" className="h-11 w-11 p-0" aria-label={`Decline ${u.name}`}
                            onClick={() => void act(() => decideRequest(c.id, u.id, false))}><X className="size-5" /></Button>
                          <Button variant="primary" className="h-11 gap-1 px-3" onClick={() => void act(() => decideRequest(c.id, u.id, true), `${u.name} is in.`)}>
                            <Check className="size-5" /> Let in
                          </Button>
                        </span>
                      } />
                  ))}
                </Group>
              )}
              {(canInvite || c.code) && c.kind === 'club' && (
                <Card className="flex flex-col gap-2 p-3.5">
                  {canInvite && (
                    <Button variant="primary" className="h-11 gap-1.5 text-small" onClick={() => setSheet('invite')}>
                      <UserPlus className="size-5" /> Invite friends
                    </Button>
                  )}
                  {(c.visibility !== 'private' || admin) && (
                    <ShareButton label="Text the club to someone" target={{ kind: 'club', ref: c.id, label: c.name }} />
                  )}
                  {c.code && (
                    <div className="flex items-center gap-2">
                      <span className="text-meta text-(--text-muted)">Club code</span>
                      <code className="min-w-0 flex-1 rounded-lg bg-(--bg-inset) px-3 py-2 text-center font-mono text-lead tracking-[0.2em] text-(--brand)">{c.code}</code>
                      <Button variant="default" className="h-11 w-11 p-0" aria-label="Copy code" onClick={() => void copy(c.code!)}>
                        {copied ? <Check className="size-5" /> : <Copy className="size-5" />}
                      </Button>
                    </div>
                  )}
                  {admin && c.code && (
                    <button type="button" className="hit-44 self-start text-caption text-(--text-muted) underline-offset-2 hover:underline"
                      onClick={() => void act(() => newClubCode(c.id), 'New code made. The old one no longer works.')}>Make a new code</button>
                  )}
                </Card>
              )}
              <Group label={c.kind === 'race' ? 'Racing together' : 'Members'}>
                {c.people.map((p) => (
                  <Row key={p.user_id} icon={p.user ? <TapAvatar p={p.user} size={30} /> : <PersonAvatar u={null} size={30} />}
                    title={<PersonLink id={p.user ? p.user_id : null} name={p.user?.name ?? 'Member'} />}
                    subtitle={p.role === 'member' ? undefined : p.role === 'owner' ? 'Owner' : 'Admin'}
                    trailing={c.kind === 'club' && admin && p.role !== 'owner' && !(c.role === 'admin' && p.role === 'admin') ? (
                      <span className="flex gap-1">
                        {c.role === 'owner' && (
                          <Button variant="ghost" className="h-11 px-2 text-caption"
                            onClick={() => void act(() => setMemberRole(c.id, p.user_id, p.role === 'admin' ? 'member' : 'admin'))}>
                            {p.role === 'admin' ? 'Make member' : 'Make admin'}
                          </Button>
                        )}
                        <Button variant="ghost" className="h-11 w-11 p-0" aria-label={`Remove ${p.user?.name ?? 'member'}`}
                          onClick={() => { void confirmAsk(`Remove ${p.user?.name ?? 'them'} from ${c.name}?`, { confirm: 'Remove', danger: true }).then((ok) => { if (ok) void act(() => removeMember(c.id, p.user_id), 'Removed.') }) }}>
                          <X className="size-5" />
                        </Button>
                      </span>
                    ) : undefined} />
                ))}
              </Group>
              {c.kind === 'club' && (
                <Group>
                  {admin && <Row title="Edit club" subtitle="Name, sport, city, who can join" onClick={() => setSheet('edit')} />}
                  <Row icon={<LogOut className="size-5" />} title="Leave club" danger
                    onClick={() => { void confirmAsk(`Leave ${c.name}?`, { confirm: 'Leave', danger: true }).then((ok) => { if (ok) void act(() => leaveClub(c.id), undefined, close) }) }} />
                  {c.role === 'owner' && (
                    <Row icon={<Trash2 className="size-5" />} title="Delete club" danger
                      onClick={() => { void confirmAsk(`Delete ${c.name} for everyone?`, { detail: 'Posts stay with their authors.', confirm: 'Delete', danger: true }).then((ok) => { if (ok) void act(() => deleteClub(c.id), undefined, close) }) }} />
                  )}
                </Group>
              )}
              {c.kind === 'race' && <p className="px-1 text-meta text-(--text-muted)">Race crews follow the race. Leave from the race's people in Events.</p>}
            </>
          )}
        </>
      )}
      {c && member && (
        <Related items={[
          { key: 'chat', icon: <MessagesSquare className="size-5" />, label: c.kind === 'race' ? 'Crew chat' : 'Club chat', sub: 'One group chat for everyone in it', onClick: () => void groupChat() },
          { key: 'members', icon: <Users className="size-5" />, label: c.kind === 'race' ? 'The crew' : 'Members', sub: `${c.members} in it`, onClick: view !== 'members' ? () => setView('members') : null },
        ]} link={{ kind: 'club', id: c.id }} />
      )}
      {sheet === 'edit' && c && <ClubSheet initial={c} onClose={() => setSheet(null)} onSaved={() => { setSheet(null); void load() }} />}
      {sheet === 'invite' && c && <InviteSheet club={c} onClose={() => { setSheet(null); void load() }} />}
      {sheet === 'meetup' && c && <MeetupSheet clubId={c.id} onClose={() => setSheet(null)} onSaved={() => { setSheet(null); setMsg({ text: 'Meetup planned. Members can RSVP now.', ok: true }); void load() }} />}
      {sheet === 'challenge' && c && <ChallengeSheet clubId={c.id} imperial={imperial} onClose={() => setSheet(null)} onStarted={(d) => { setSheet(null); setC(d); setMsg({ text: 'Club challenge on! Everyone can join.', ok: true }) }} />}
    </Screen>
  )
}

function MeetupCard({ m, clubId, admin, onChanged, onError }: {
  m: Meetup; clubId: string; admin: boolean; onChanged: () => void; onError: (t: string) => void
}) {
  const [mt, setMt] = useState(m)
  const [busy, setBusy] = useState(false)
  useEffect(() => setMt(m), [m])
  async function rsvp(status: 'going' | 'maybe', el: HTMLElement) {
    setBusy(true)
    try {
      const next = mt.my_rsvp === status ? 'none' : status
      const r = await rsvpMeetup(clubId, mt.id, next)
      setMt(r.meetup)
      if (next === 'going') burst(el, 'kudos')
    } catch (e) { onError((e as Error).message) } finally { setBusy(false) }
  }
  async function cancel() {
    if (!(await confirmAsk(`Cancel "${mt.title}"?`, { detail: "Anyone who said they're going gets a heads-up.", confirm: 'Cancel it', cancel: 'Keep it', danger: true }))) return
    try { await deleteMeetup(clubId, mt.id); onChanged() } catch (e) { onError((e as Error).message) }
  }
  const going = mt.going.filter((u): u is SocialUser => !!u)
  return (
    <Card className="flex flex-col gap-2 p-3.5">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-meta font-semibold text-(--accent)">{mt.next ? meetupWhen(mt.next) : ''}
            {mt.repeat === 'weekly' && <span className="ml-1.5 inline-flex items-center gap-0.5 font-normal text-(--text-muted)"><Repeat className="size-3.5" />weekly</span>}
          </p>
          <p className="text-lead font-medium text-(--text)">{mt.title}</p>
          <p className="flex items-center gap-1 text-meta text-(--text-secondary)"><MapPin className="size-4 shrink-0" />{mt.where}</p>
          <p className="text-meta text-(--text-muted)">{[LEVEL_LABEL[mt.level], mt.pace].filter(Boolean).join(' · ')}</p>
          {mt.notes && <p className="mt-1 text-small text-(--text-secondary)">{mt.notes}</p>}
        </div>
        {(admin || mt.mine) && (
          <Button variant="ghost" className="h-11 w-11 shrink-0 p-0" aria-label="Cancel meetup" onClick={() => void cancel()}><Trash2 className="size-5" /></Button>
        )}
      </div>
      <div className="flex items-center gap-2">
        <span className="flex -space-x-1.5">{going.slice(0, 6).map((u) => <PersonAvatar key={u.id} u={u} size={24} />)}</span>
        <span className="flex-1 text-meta text-(--text-muted)">
          {going.length ? `${going.length} going` : 'Be the first'}{mt.maybe ? ` · ${mt.maybe} maybe` : ''}
        </span>
        <Button variant={mt.my_rsvp === 'maybe' ? 'primary' : 'default'} className="h-11 px-3 text-meta" disabled={busy}
          aria-pressed={mt.my_rsvp === 'maybe'} onClick={(e) => void rsvp('maybe', e.currentTarget)}>Maybe</Button>
        <Button variant={mt.my_rsvp === 'going' ? 'primary' : 'default'} className="h-11 gap-1 px-3 text-meta" disabled={busy}
          aria-pressed={mt.my_rsvp === 'going'} onClick={(e) => void rsvp('going', e.currentTarget)}>
          {mt.my_rsvp === 'going' && <Check className="size-4" />} Going
        </Button>
      </div>
    </Card>
  )
}

function MeetupSheet({ clubId, onClose, onSaved }: { clubId: string; onClose: () => void; onSaved: () => void }) {
  const tomorrow = new Date(Date.now() + 86400000)
  const pad = (n: number) => String(n).padStart(2, '0')
  type M = { title: string; start: string; weekly: boolean; place: string; pace: string; level: Level; notes: string }
  const [m, setM, draft] = useDraft<M>(`meetup.${clubId}`, () => ({ title: '', weekly: false, place: '', pace: '', level: 'all', notes: '',
    start: `${tomorrow.getFullYear()}-${pad(tomorrow.getMonth() + 1)}-${pad(tomorrow.getDate())}T07:00` }), { label: 'meetup' })
  const { title, start, weekly, place, pace, level, notes } = m
  const setTitle = (title: string) => setM((x) => ({ ...x, title }))
  const setStart = (start: string) => setM((x) => ({ ...x, start }))
  const setWeekly = (weekly: boolean) => setM((x) => ({ ...x, weekly }))
  const setPlace = (place: string) => setM((x) => ({ ...x, place }))
  const setPace = (pace: string) => setM((x) => ({ ...x, pace }))
  const setLevel = (level: Level) => setM((x) => ({ ...x, level }))
  const setNotes = (notes: string) => setM((x) => ({ ...x, notes }))
  const guard = useUnsavedGuard(draft.dirty, draft.discard)
  const [busy, setBusy] = useState(false)
  const [queued, setQueued] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  async function save() {
    setBusy(true); setErr(null); setQueued(false)
    try {
      await saveDurably({ method: 'POST', path: `/api/community/clubs/${encodeURIComponent(clubId)}/meetups`, label: 'meetup',
        body: { title: title.trim(), start, repeat: weekly ? 'weekly' : 'none', where: place.trim(), pace: pace.trim(), level, notes: notes.trim() } },
      () => setQueued(true))
      draft.clear()
      onSaved()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false); setQueued(false) }
  }
  return (
    <Sheet title="Plan a meetup" onClose={guard.wrap(onClose)} extra={guard.dialog}>
      {draft.restored && <DraftRestored onDiscard={draft.discard} />}
      <Field label="What"><input className={inputCls} maxLength={60} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Saturday long run" /></Field>
      <Field label="When"><input type="datetime-local" className={inputCls} value={start} onChange={(e) => setStart(e.target.value.slice(0, 16))} /></Field>
      <Field label="Repeats">
        <Choice label="Repeats" value={weekly ? 'weekly' : 'none'} options={[['none', 'Just once'], ['weekly', 'Every week']]} onChange={(v) => setWeekly(v === 'weekly')} />
      </Field>
      <Field label="Where" hint="A park, shop or public meeting spot. Never a home address.">
        <input className={inputCls} maxLength={120} value={place} onChange={(e) => setPlace(e.target.value)} placeholder="Wash Park boathouse" />
      </Field>
      <Field label="Level"><Choice label="Level" value={level} options={LEVELS} onChange={setLevel} /></Field>
      <Field label="Pace (optional)"><input className={inputCls} maxLength={40} value={pace} onChange={(e) => setPace(e.target.value)} placeholder="9:30–10:00 /mi, no-drop" /></Field>
      <Field label="Notes (optional)"><input className={inputCls} maxLength={200} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Coffee after at Steam" /></Field>
      {queued && <SaveStatus state="queued" />}
      {err && <p className="text-meta text-(--danger)" role="alert">{err}</p>}
      <Button variant="primary" className="h-11 text-body" loading={busy} disabled={!title.trim() || !place.trim() || !start} onClick={() => void save()}>Plan it</Button>
    </Sheet>
  )
}

function ChallengeSheet({ clubId, imperial, onClose, onStarted }: {
  clubId: string; imperial: boolean; onClose: () => void; onStarted: (c: ClubDetail) => void
}) {
  const [items, setItems] = useState<Suggestion[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  useEffect(() => {
    getChallenges().then((v) => setItems([...v.periods.week.suggestions, ...v.periods.month.suggestions]), (e) => setErr((e as Error).message))
  }, [])
  async function start(s: Suggestion, el: HTMLElement) {
    setBusy(s.template); setErr(null)
    try { const r = await startClubChallenge(clubId, s.template, s.period); burst(el, 'challenge'); onStarted(r.club) }
    catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }
  return (
    <Sheet title="Club challenge" onClose={onClose}>
      <p className="text-small text-(--text-secondary)">Pick one of your challenges. You join it, and everyone in the club can join with the same target.</p>
      {err && <ErrorState compact message={err} />}
      {!items && !err && <RabbitLoader className="py-6" label="Loading challenges" />}
      {items && items.length === 0 && <p className="text-small text-(--text-muted)">No challenges on offer right now. Check back next week.</p>}
      {items?.map((s) => (
        <Card key={`${s.period}-${s.template}`} className="flex items-center gap-3 p-3">
          <div className="min-w-0 flex-1">
            <p className="text-body font-medium text-(--text)">{s.name}</p>
            <p className="text-meta text-(--text-muted)">{targetLine(s, imperial)} · +{s.xp} XP</p>
          </div>
          <Button variant="primary" className="h-11 px-3 text-meta" loading={busy === s.template} disabled={busy != null}
            onClick={(e) => void start(s, e.currentTarget)}>Start</Button>
        </Card>
      ))}
    </Sheet>
  )
}

function InviteSheet({ club, onClose }: { club: ClubDetail; onClose: () => void }) {
  const [people, setPeople] = useState<SocialUser[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sent, setSent] = useState<Set<string>>(new Set())
  useEffect(() => {
    getPeople().then((p) => {
      const seen = new Set(club.people.map((x) => x.user_id))
      const all: SocialUser[] = []
      for (const e of [...p.following, ...p.followers]) {
        if (e.user && !seen.has(e.user.id)) { seen.add(e.user.id); all.push(e.user) }
      }
      setPeople(all)
    }, (e) => setError((e as Error).message))
  }, [club.people])
  async function invite(u: SocialUser, el: HTMLElement) {
    try { await inviteToClub(club.id, u.id); setSent((s) => new Set(s).add(u.id)); burst(el, 'kudos') }
    catch (e) { setError((e as Error).message) }
  }
  return (
    <Sheet title={`Invite to ${club.name}`} onClose={onClose}>
      {error && <ErrorState compact message={error} />}
      {!people && !error && <RabbitLoader className="py-6" label="Loading friends" />}
      {people && people.length === 0 && <p className="text-small text-(--text-muted)">Everyone you follow is already here. Share the club code instead.</p>}
      {people && people.length > 0 && (
        <Group footer="People you follow or who follow you.">
          {people.map((u) => (
            <Row key={u.id} icon={<PersonAvatar u={u} size={30} />} title={u.name}
              trailing={sent.has(u.id) ? <span className="text-meta text-(--accent)">Invited</span> : (
                <Button variant="default" className="h-11 px-3 text-meta" onClick={(e) => void invite(u, e.currentTarget)}>Invite</Button>
              )} />
          ))}
        </Group>
      )}
    </Sheet>
  )
}
