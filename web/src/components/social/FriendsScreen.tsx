// Friends: a feed of the people you follow (their recent workouts, kudos, short cheers) and
// People (invite code, add by email/code, requests, following/followers, privacy settings).
import { openPerson } from '@/lib/people'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Activity, Ban, Bike, Check, Copy, Dumbbell, Flag, Flame, Footprints, Heart, Layers, MessageCircle, Mountain, Send, Share2, Ship, Snowflake, Trash2, UserMinus, UserPlus, Waves, X } from 'lucide-react'
import { Avatar } from '@/components/Avatar'
import { RabbitLoader } from '@/components/RabbitLoader'
import { EmptyRabbit, PullToRefresh, burst } from '@/components/anim'
import { Button } from '@/components/ui/button'
import { messagePeople } from '@/lib/dm'
import { ErrorState } from '@/components/ui/ErrorState'
import { Group, Row, Switch } from '@/components/settings/Grouped'
import { Card, Field, Screen, inputCls } from '@/components/plan/ui'
import { LevelBadge } from '@/components/progress/Progress'
import { useSheetDrag } from '@/hooks/useSheetDrag'
import { InviteToRaceSheet } from '@/components/events/RacePeople'
import { cn } from '@/lib/utils'
import {
  acceptRequest, addCheer, blockUser, declineRequest, deleteCheer, follow, friendPhotoUrl, getFeed, getFriend,
  getPeople, giveKudos, markSocialSeen, newInviteCode, putSocialSettings, relativeDay, removeFollower, takeKudos,
  unblockUser, unfollow, workoutLine,
  type FeedItem, type FriendCard as FriendCardData, type People, type PersonEdge, type SocialSettings, type SocialUser,
} from '@/lib/social'

const SPORT_ICON: Record<string, typeof Bike> = {
  run: Footprints, bike: Bike, swim: Waves, brick: Layers, strength: Dumbbell, ski: Snowflake,
  climb: Mountain, hike: Mountain, paddle: Ship, other: Activity,
}
const LOADING = ['Finding your crew…', 'Lacing up…', 'Checking who trained today…']
const SEEN_EVENT = 'rabbit:social-seen'

function FriendAvatar({ u, size = 36 }: { u: SocialUser; size?: number }) {
  return <Avatar name={u.name} picture={u.picture} photo={friendPhotoUrl(u)} size={size} />
}

export function FriendsScreen({ imperial, onClose, onChanged }: { imperial: boolean; onClose: () => void; onChanged?: () => void }) {
  const [closing, setClosing] = useState(false)
  const [tab, setTab] = useState<'feed' | 'people'>('feed')
  const [feed, setFeed] = useState<FeedItem[] | null>(null)
  const [following, setFollowing] = useState(0)
  const [people, setPeople] = useState<People | null>(null)
  const [error, setError] = useState<string | null>(null)
  const close = () => { setClosing(true); setTimeout(onClose, 200) }

  const loadFeed = useCallback(() => {
    return getFeed().then((r) => { setFeed(r.items); setFollowing(r.following); setError(null) }, (e) => setError((e as Error).message))
  }, [])
  const loadPeople = useCallback(() => {
    return getPeople().then((p) => { setPeople(p); setError(null) }, (e) => setError((e as Error).message))
  }, [])
  useEffect(() => {
    loadFeed(); loadPeople()
    void markSocialSeen().then(() => window.dispatchEvent(new Event(SEEN_EVENT)), () => { /* badge just stays */ })
  }, [loadFeed, loadPeople])

  const pending = people?.pending_in.length ?? 0
  const tabs = (
    <div role="tablist" aria-label="Friends" className="mx-auto mt-2 flex max-w-xl gap-1 rounded-full bg-(--bg-inset) p-0.5">
      {(['feed', 'people'] as const).map((t) => (
        <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
          className={cn('hit-44 flex-1 rounded-full py-1.5 text-[0.7059rem] font-medium transition-colors',
            tab === t ? 'bg-(--bg-surface) text-(--text) shadow-sm' : 'text-(--text-muted)')}>
          {t === 'feed' ? 'Feed' : 'People'}
          {t === 'people' && pending > 0 && (
            <span className="ml-1 rounded-full bg-(--accent) px-1.5 text-[0.6471rem] font-semibold text-(--on-fill)">{pending}</span>
          )}
        </button>
      ))}
    </div>
  )

  return (
    <Screen title="Friends" subtitle="Train together, cheer each other on" closing={closing} onClose={close} headerExtra={tabs}>
      <PullToRefresh onRefresh={() => Promise.all([loadFeed(), loadPeople()])} />
      {error && <ErrorState compact message={error} onRetry={() => { void loadFeed(); void loadPeople() }} />}
      {tab === 'feed' ? (
        feed == null ? (error ? null : <RabbitLoader className="py-10" label="Loading your friends' workouts" cycle={LOADING} />) : (
          <FeedList items={feed} following={following} imperial={imperial} onOpen={openPerson}
            onInvite={() => setTab('people')} onChange={setFeed} />
        )
      ) : (
        people == null ? (error ? null : <RabbitLoader className="py-10" label="Loading people" cycle={LOADING} />) : (
          <PeopleTab people={people} onOpen={openPerson}
            onChanged={() => { void loadPeople(); void loadFeed(); onChanged?.() }} setPeople={setPeople} />
        )
      )}
    </Screen>
  )
}

// ------------------------------------------------------------------ feed ---
function FeedList({ items, following, imperial, onOpen, onInvite, onChange }: {
  items: FeedItem[]; following: number; imperial: boolean; onOpen: (id: string) => void
  onInvite: () => void; onChange: (f: FeedItem[]) => void
}) {
  const update = (it: FeedItem, patch: Partial<FeedItem>) =>
    onChange(items.map((x) => (x.id === it.id && x.user.id === it.user.id ? { ...x, ...patch } : x)))
  const theirs = items.filter((i) => !i.mine)
  return (
    <>
      {following === 0 && (
        <EmptyRabbit hero size={60} className="celebrate rounded-2xl border border-(--border) bg-(--bg-surface) px-5 py-6"
          title="Training's better together"
          body="Follow a friend to see their workouts here and send kudos. Share your invite code so they can follow you back."
          action={<Button variant="primary" className="mt-1 h-10 gap-1.5 px-4 text-[0.7647rem]" onClick={onInvite}>
            <UserPlus className="size-4" /> Add a friend
          </Button>} />
      )}
      {following > 0 && theirs.length === 0 && (
        <p className="px-1 text-center text-[0.7647rem] text-(--text-muted)">No workouts from your friends in the last two weeks yet.</p>
      )}
      <div className="flex flex-col gap-3">
        {items.map((it) => <FeedCard key={`${it.user.id}:${it.id}`} it={it} imperial={imperial} onOpen={onOpen} onUpdate={(p) => update(it, p)} />)}
      </div>
    </>
  )
}

function FeedCard({ it, imperial, onOpen, onUpdate, compact }: {
  it: FeedItem; imperial: boolean; onOpen?: (id: string) => void; onUpdate: (p: Partial<FeedItem>) => void; compact?: boolean
}) {
  const Icon = SPORT_ICON[it.sport] ?? Activity
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const line = workoutLine(it, imperial)

  const kudosBtn = useRef<HTMLButtonElement>(null)
  const [bump, setBump] = useState(false) // the count bumps after your tap, not on first paint
  async function toggleKudos() {
    if (it.mine || busy) return
    setBusy(true); setErr(null)
    const was = it.you_kudoed
    setBump(true)
    if (!was) burst(kudosBtn.current, 'kudos') // carrots + paws from the heart (and a haptic tap)
    onUpdate({ you_kudoed: !was, kudos: it.kudos + (was ? -1 : 1) })
    try {
      const r = was ? await takeKudos(it.user.id, it.id) : await giveKudos(it.user.id, it.id)
      onUpdate({ you_kudoed: r.you_kudoed, kudos: r.count })
    } catch (e) { onUpdate({ you_kudoed: was, kudos: it.kudos }); setErr((e as Error).message) }
    finally { setBusy(false) }
  }
  async function send() {
    const t = text.trim()
    if (!t) return
    setBusy(true); setErr(null)
    try {
      const r = await addCheer(it.user.id, it.id, t)
      onUpdate({ cheers: [...it.cheers, r.cheer], kudos: it.kudos })
      setText(''); setOpen(false)
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  async function remove(id: string) {
    try { await deleteCheer(it.user.id, it.id, id); onUpdate({ cheers: it.cheers.filter((c) => c.id !== id) }) }
    catch (e) { setErr((e as Error).message) }
  }

  return (
    <article className="rounded-2xl border border-(--border) bg-(--bg-surface) p-3.5">
      {!compact && (
        <button type="button" disabled={it.mine || !onOpen} onClick={() => onOpen?.(it.user.id)}
          className="flex w-full items-center gap-2.5 text-left">
          <FriendAvatar u={it.user} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[0.8235rem] font-medium text-(--text)">{it.mine ? 'You' : it.user.name}</span>
            <span className="block text-[0.6471rem] text-(--text-muted)">{relativeDay(it.date, it.time)}</span>
          </span>
          {it.user.level != null && <LevelBadge level={it.user.level} size="sm" />}
        </button>
      )}
      <div className={cn('flex items-start gap-2.5', !compact && 'mt-2.5')}>
        <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-(--accent-subtle) text-(--accent)"><Icon className="size-[18px]" /></span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[0.9412rem] font-medium text-(--text)">{it.title}</span>
          <span className="block text-[0.7059rem] text-(--text-secondary)">
            {line || (compact ? relativeDay(it.date, it.time) : 'Workout')}
            {compact && line ? ` · ${relativeDay(it.date, it.time)}` : ''}
            {it.race && <span className="ml-1.5 rounded-full bg-(--accent-subtle) px-1.5 py-0.5 text-[0.6471rem] font-semibold text-(--accent)">Race</span>}
          </span>
        </span>
        {it.xp != null && <span className="shrink-0 text-[0.6471rem] font-semibold text-(--accent)">+{it.xp} XP</span>}
      </div>
      <div className="mt-2.5 flex items-center gap-1">
        <button ref={kudosBtn} type="button" onClick={() => void toggleKudos()} disabled={it.mine} aria-pressed={it.you_kudoed}
          aria-label={it.mine ? `${it.kudos} kudos` : it.you_kudoed ? 'Take back kudos' : 'Give kudos'}
          className={cn('hit-44 inline-flex h-8 items-center gap-1.5 rounded-full px-2.5 text-[0.7059rem] font-medium transition-colors',
            it.you_kudoed ? 'bg-(--accent-subtle) text-(--accent)' : 'text-(--text-secondary) active:bg-(--bg-inset)',
            it.mine && 'opacity-80')}>
          <Heart key={it.you_kudoed ? `on${it.kudos}` : 'off'} className={cn('size-4', it.you_kudoed && 'celebrate fill-current')} />
          <span key={it.kudos} className={cn('tabular-nums', bump && 'rb-bump')}>{it.kudos}</span>
        </button>
        {!it.mine && (
          <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
            className="hit-44 inline-flex h-8 items-center gap-1.5 rounded-full px-2.5 text-[0.7059rem] font-medium text-(--text-secondary) active:bg-(--bg-inset)">
            <MessageCircle className="size-4" /> Cheer
          </button>
        )}
      </div>
      {it.cheers.length > 0 && (
        <ul className="mt-1.5 flex flex-col gap-1 border-t border-(--border) pt-2">
          {it.cheers.map((c) => (
            <li key={c.id} className="flex items-start gap-1.5 text-[0.7647rem] leading-snug">
              <span className="min-w-0 flex-1"><span className="font-medium text-(--text)">{c.mine ? 'You' : c.by.name}</span>{' '}
                <span className="text-(--text-secondary)">{c.text}</span></span>
              {c.can_delete && (
                <button type="button" aria-label="Delete cheer" onClick={() => void remove(c.id)} className="hit-44 shrink-0 p-0.5 text-(--text-muted)">
                  <X className="size-3.5" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {open && (
        <div className="mt-2 flex items-center gap-2">
          <input aria-label="Cheer" className={cn(inputCls, 'h-11 text-[0.8235rem]')} maxLength={140} autoFocus placeholder="Nice work!"
            value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void send() }} />
          <Button variant="primary" className="h-9 w-9 shrink-0 p-0" aria-label="Send cheer" loading={busy} disabled={!text.trim()} onClick={() => void send()}>
            <Send className="size-4" />
          </Button>
        </div>
      )}
      {err && <p className="mt-1.5 text-[0.7059rem] text-(--danger)">{err}</p>}
    </article>
  )
}

// ---------------------------------------------------------------- people ---
const PRIVACY: [keyof SocialSettings, string, string][] = [
  ['workouts', 'Workouts', 'Your recent workouts in their feed'],
  ['distance', 'Distance & climbing', 'How far you went and how much you climbed'],
  ['times', 'Times', 'How long you trained and when'],
  ['streak', 'Streak & level', 'Your day streak and Rabbit level'],
  ['races', 'Races', 'Workouts you tagged as races'],
]

export function PeopleTab({ people, onOpen, onChanged, setPeople }: {
  people: People; onOpen: (id: string) => void; onChanged: () => void; setPeople: (p: People) => void
}) {
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null)
  const [copied, setCopied] = useState(false)
  const [confirm, setConfirm] = useState<string | null>(null)
  const code = people.invite_code
  const canShare = typeof navigator !== 'undefined' && typeof navigator.share === 'function'

  async function run(key: string, fn: () => Promise<unknown>, ok?: string) {
    setBusy(key); setMsg(null)
    try { await fn(); if (ok) setMsg({ text: ok, ok: true }); onChanged(); return true }
    catch (e) { setMsg({ text: (e as Error).message, ok: false }); return false }
    finally { setBusy(null) }
  }
  async function add() {
    const v = value.trim()
    if (!v) return
    setBusy('add'); setMsg(null)
    try { const r = await follow(v); setMsg({ text: r.message, ok: true }); setValue(''); onChanged() }
    catch (e) { setMsg({ text: (e as Error).message, ok: false }) }
    finally { setBusy(null) }
  }
  async function copy() {
    try { await navigator.clipboard.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 1500) }
    catch { setMsg({ text: `Your code is ${code}`, ok: true }) }
  }
  async function share() {
    try { await navigator.share({ title: 'Follow me on Rabbit', text: `Follow my training on Rabbit. My invite code: ${code}`, url: `${window.location.origin}/app/` }) }
    catch { /* cancelled */ }
  }
  async function setSetting(k: keyof SocialSettings, v: boolean) {
    setPeople({ ...people, settings: { ...people.settings, [k]: v } })
    try { const r = await putSocialSettings({ [k]: v }); setPeople({ ...people, settings: r.settings }) }
    catch (e) { setMsg({ text: (e as Error).message, ok: false }); setPeople(people) }
  }

  const person = (e: PersonEdge, trailing: React.ReactNode, subtitle?: string) => {
    const u = e.user
    return (
      <Row key={e.edge_id} icon={u ? <FriendAvatar u={u} size={30} /> : <span className="flex size-[30px] items-center justify-center rounded-full bg-(--bg-inset) text-(--text-muted)"><UserPlus className="size-4" /></span>}
        title={u ? u.name : e.email ?? 'Someone'} subtitle={subtitle} trailing={trailing} />
    )
  }

  return (
    <>
      <Card className="p-4">
        <p className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Your invite code</p>
        <div className="mt-2 flex items-center gap-2">
          <code className="min-w-0 flex-1 rounded-lg bg-(--bg-inset) px-3 py-2 text-center font-mono text-[1.1765rem] tracking-[0.25em] text-(--brand)">{code}</code>
          <Button variant="default" className="h-10 w-10 p-0" aria-label="Copy code" onClick={() => void copy()}>
            {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
          </Button>
          {canShare && (
            <Button variant="default" className="h-10 w-10 p-0" aria-label="Share code" onClick={() => void share()}><Share2 className="size-4" /></Button>
          )}
        </div>
        <button type="button" className="hit-44 mt-2 text-[0.6471rem] text-(--text-muted) underline-offset-2 hover:underline" disabled={busy === 'code'}
          onClick={() => void run('code', newInviteCode, 'New code made. The old one no longer works.')}>Make a new code</button>
      </Card>

      <Card>
        <Field label="Add by email or code" hint="Friends need a Rabbit invite before they can join.">
          <div className="flex items-center gap-2">
            <input className={inputCls} autoComplete="off" autoCapitalize="none" placeholder="friend@example.com or ABCD2345"
              value={value} onChange={(e) => setValue(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void add() }} />
            <Button variant="primary" className="h-10 shrink-0 gap-1.5 px-3 text-[0.7647rem]" loading={busy === 'add'} disabled={!value.trim()} onClick={() => void add()}>
              <UserPlus className="size-4" /> Follow
            </Button>
          </div>
        </Field>
      </Card>
      {msg && <p className={cn('px-1 text-[0.7647rem]', msg.ok ? 'text-(--accent)' : 'text-(--danger)')} role="status">{msg.text}</p>}

      {people.pending_in.length > 0 && (
        <Group label="Requests">
          {people.pending_in.map((e) => person(e, (
            <span className="flex shrink-0 gap-1.5">
              <Button variant="default" className="h-8 px-2.5" aria-label="Decline" disabled={busy != null}
                onClick={() => void run(e.edge_id, () => declineRequest(e.edge_id))}><X className="size-4" /></Button>
              <Button variant="primary" className="h-8 gap-1 px-2.5" loading={busy === e.edge_id}
                onClick={() => void run(e.edge_id, () => acceptRequest(e.edge_id), 'They can see your training now.')}><Check className="size-4" /> Accept</Button>
            </span>
          ), 'Wants to follow you'))}
        </Group>
      )}

      <Group label={`Following · ${people.following.length}`}
        footer={people.following.length === 0 ? 'Nobody yet. Add a friend above.' : undefined}>
        {people.following.map((e) => (
          <div key={e.edge_id} className="flex items-center">
            <button type="button" className="min-w-0 flex-1 text-left" onClick={() => e.user && onOpen(e.user.id)}>
              {person(e, null)}
            </button>
            {e.user && (
              <Button variant="ghost" className="h-11 w-11 p-0" aria-label={`Message ${e.user.name}`} onClick={() => messagePeople([e.user!.id])}>
                <MessageCircle className="size-4" aria-hidden />
              </Button>
            )}
            <Button variant="ghost" className="mr-2 h-8 px-2" aria-label={`Unfollow ${e.user?.name ?? ''}`} disabled={busy != null}
              onClick={() => void run(e.edge_id, () => unfollow(e.edge_id))}><UserMinus className="size-4" /></Button>
          </div>
        ))}
        {people.pending_out.map((e) => person(e, (
          <Button variant="ghost" className="h-8 px-2 text-[0.6471rem]" disabled={busy != null}
            onClick={() => void run(e.edge_id, () => unfollow(e.edge_id))}>Cancel</Button>
        ), 'Requested'))}
      </Group>

      <Group label={`Followers · ${people.followers.length}`}>
        {people.followers.length === 0 && <Row title="No followers yet" subtitle="Share your code so friends can follow you." />}
        {people.followers.map((e) => confirm === e.edge_id ? (
          <div key={e.edge_id} className="flex flex-wrap items-center gap-2 px-4 py-3">
            <span className="min-w-0 flex-1 text-[0.8235rem]">Remove {e.user?.name}?</span>
            <Button variant="default" className="h-8 px-2.5" onClick={() => setConfirm(null)}>Keep</Button>
            <Button variant="default" className="h-8 gap-1 px-2.5" disabled={busy != null}
              onClick={() => void run(e.edge_id, () => removeFollower(e.edge_id), 'Removed.').then(() => setConfirm(null))}>
              <Trash2 className="size-3.5" /> Remove</Button>
            <Button variant="destructive" className="h-8 gap-1 px-2.5" disabled={busy != null || !e.user}
              onClick={() => e.user && void run(e.edge_id, () => blockUser(e.user!.id), 'Blocked. They can’t follow you again.').then(() => setConfirm(null))}>
              <Ban className="size-3.5" /> Block</Button>
          </div>
        ) : person(e, (
          <Button variant="ghost" className="h-8 px-2" aria-label={`Remove ${e.user?.name ?? 'follower'}`} onClick={() => setConfirm(e.edge_id)}>
            <UserMinus className="size-4" />
          </Button>
        )))}
      </Group>

      <Group label="What followers see" footer="Never your heart rate, health data or where you trained.">
        {PRIVACY.map(([k, title, sub]) => (
          <Row key={k} title={title} subtitle={sub}
            trailing={<Switch label={title} checked={people.settings[k]} onChange={(v) => void setSetting(k, v)} />} />
        ))}
        <Row title="Auto-accept" subtitle="Accept requests from people I follow"
          trailing={<Switch label="Auto-accept from people I follow" checked={people.settings.auto_accept} onChange={(v) => void setSetting('auto_accept', v)} />} />
      </Group>

      {people.blocked.filter(Boolean).length > 0 && (
        <Group label="Blocked">
          {people.blocked.filter((u): u is SocialUser => !!u).map((u) => (
            <Row key={u.id} icon={<FriendAvatar u={u} size={30} />} title={u.name}
              trailing={<Button variant="ghost" className="h-8 px-2 text-[0.6471rem]" onClick={() => void run(u.id, () => unblockUser(u.id))}>Unblock</Button>} />
          ))}
        </Group>
      )}
    </>
  )
}

// ----------------------------------------------------------- friend card ---
export function FriendCard({ id, imperial, onClose }: { id: string; imperial: boolean; onClose: () => void }) {
  const [card, setCard] = useState<FriendCardData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [raceInvite, setRaceInvite] = useState(false)
  const drag = useSheetDrag(onClose)
  useEffect(() => { getFriend(id).then(setCard, (e) => setError((e as Error).message)) }, [id])
  const u = card?.user
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} {...drag}>
        <div className="sheet-handle" />
        <div className="modal-header">
          <h2 className="modal-title">{u?.name ?? 'Friend'}</h2>
          <button className="modal-close" aria-label="Close" onClick={onClose}><X className="size-4" /></button>
        </div>
        <div className="modal-body flex flex-col gap-4 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
          {error && <ErrorState compact message={error} onRetry={() => { setError(null); getFriend(id).then(setCard, (e) => setError((e as Error).message)) }} />}
          {!card && !error && <RabbitLoader className="py-6" label="Loading" cycle={LOADING} />}
          {card && u && (
            <>
              <div className="flex items-center gap-3">
                <FriendAvatar u={u} size={56} />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-display text-[1.2941rem] text-(--brand)">{u.name}</p>
                  {u.streak != null && (
                    <p className="flex items-center gap-1 text-[0.7647rem] text-(--accent)"><Flame className="size-4" />{u.streak} day streak</p>
                  )}
                </div>
                {u.level != null && <LevelBadge level={u.level} />}
              </div>
              <div className="flex gap-2">
                <Button variant="primary" className="h-11 flex-1 gap-1.5 text-[0.7647rem]" onClick={() => messagePeople([u.id])}>
                  <MessageCircle className="size-4" aria-hidden /> Message
                </Button>
                <Button variant="default" className="h-11 flex-1 gap-1.5 text-[0.7647rem]" onClick={() => setRaceInvite(true)}>
                  <Flag className="size-4" /> Invite to an event
                </Button>
              </div>
              {card.week && (
                <div className="grid grid-cols-2 gap-2">
                  <Stat value={String(card.week.workouts)} label="workouts this week" />
                  <Stat value={card.week.hours != null ? `${card.week.hours} h` : '–'} label="this week" />
                </div>
              )}
              <div className="flex flex-col gap-2">
                <p className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Recent workouts</p>
                {card.recent.length === 0 && <p className="text-[0.7647rem] text-(--text-muted)">Nothing shared in the last two weeks.</p>}
                {card.recent.map((it) => (
                  <FeedCard key={it.id} it={it} imperial={imperial} compact
                    onUpdate={(p) => setCard((c) => c && { ...c, recent: c.recent.map((x) => (x.id === it.id ? { ...x, ...p } : x)) })} />
                ))}
              </div>
            </>
          )}
        </div>
      </div>
      {raceInvite && u && <InviteToRaceSheet friend={u} onClose={() => setRaceInvite(false)} />}
    </div>
  )
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="flex flex-col items-center gap-1 rounded-xl border border-(--border) bg-(--bg-surface) px-2 py-3 text-center">
      <span className="font-display text-[1.2941rem] leading-none text-(--text)">{value}</span>
      <span className="text-[0.6471rem] leading-tight text-(--text-muted)">{label}</span>
    </div>
  )
}
