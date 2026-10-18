// Community feed: "Share something" (life-event ideas inside the composer), the milestone drafts tray,
// meetups coming up, and calm post cards (category, text, up to 10 photos, linked event, four
// reactions with a burst, one-level comment threads). Also a club's feed (``clubId``): the
// composer posts to that club. Nothing is ever posted without a tap. Filter chips: All / Friends /
// each feed group / Clubs; a group's own feed (``groupId``) posts to that group only. My fresh
// auto-shared workout is pinned on top for an hour with "Add a photo or caption".
import { confirmAsk } from '@/lib/confirm'
import { useRefreshOnShow } from '@/hooks/useRefreshOnShow'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Ban, CalendarDays, ChevronRight, Ellipsis, EyeOff, Flag, Globe, ImagePlus, Lock, MapPin, MessageCircle, Pencil, Pin, Plus, Reply, Send, SlidersHorizontal, SquarePen, Trash2, UserPlus, Users, UsersRound, X } from 'lucide-react'
import { Avatar } from '@/components/Avatar'
import { EmptyRabbit, HopIn, PullToRefresh, burst } from '@/components/anim'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { areaCls, inputCls } from '@/components/plan/ui'
import { useSheetDrag } from '@/hooks/useSheetDrag'
import { useDialog } from '@/hooks/useDialog'
import { listEvents, type RaceEvent } from '@/lib/events'
import { fmtClimb, fmtDist, fmtDuration, fmtPaceKm, fmtSpeed, fmtSwim100 } from '@/lib/format'
import { listGroups, type FeedGroup } from '@/lib/community2'
import { Sheet } from '@/components/ui/Sheet'
import { blockUser, type SocialUser } from '@/lib/social'
import { cn } from '@/lib/utils'
import { PersonAvatar as TapAvatar, PersonLink } from '@/components/people/PersonLink'
import { openActivity } from '@/lib/activitynav'
import { messagePeople } from '@/lib/dm'
import {
  CATEGORIES, CATEGORY_LABEL, COMMENT_LEN, FEELINGS, REACTIONS, TEMPLATES, TEXT_LEN,
  ago, audienceLabel, communityPhotoUrl, deleteComment, deletePost, dismissDraft,
  getClubs, getCommunityFeed, getDrafts, getMyMeetups, getPost, hidePost, meetupWhen, postPhotoUrls, react,
  reportPost, shareDraft, unreact, updatePost, 
  type Audience, type Category, type ClubSummary, type Draft, type Meetup, type Post, type PostComment,
  type ReactionKind,
} from '@/lib/community'
import { FeedSkeleton } from '@/components/ui/Skeleton'
import { readDraft, useDraft } from '@/lib/drafts'
import { saveDurably } from '@/lib/outbox'
import { counted } from '@/lib/usage'
import { SaveStatus } from '@/components/ui/SaveStatus'
import { useUnsavedGuard } from '@/components/ui/UnsavedGuard'
import { FeedHint } from '@/components/community/FeedHint'
import { PhotoPicker, existingPhotos, usePhotoPicker } from '@/components/community/PhotoPicker'
import { useMentionField } from './MentionField'
import { MentionText } from './MentionText'
import { displayText, tokensIn } from '@/lib/mentions'


export function PersonAvatar({ u, size = 36 }: { u: SocialUser | null; size?: number }) {
  return <Avatar name={u?.name ?? '?'} picture={u?.picture ?? ''} photo={u ? communityPhotoUrl(u) : null} size={size} />
}

type Template = (typeof TEMPLATES)[number]

/** Feed filter: everyone, friends, my clubs' posts, or one feed group (``g:<id>``). */
type Filter = 'all' | 'friends' | 'clubs' | `g:${string}`

export function CommunityFeed({ imperial, clubId, clubName, groupId, groupName, onInvite, onSettings, onOpenClub, onOpenGroup, onNewGroup, groupsKey }: {
  imperial: boolean; clubId?: string; clubName?: string; onInvite?: () => void; onSettings?: () => void
  onOpenClub?: (id: string) => void
  /** a feed group's own feed (GroupPage): reads and posts to that group only */
  groupId?: string; groupName?: string
  onOpenGroup?: (id: string) => void; onNewGroup?: () => void
  /** bump to re-read my groups (created / left one) */
  groupsKey?: number
}) {
  const [items, setItems] = useState<Post[] | null>(null)
  const [next, setNext] = useState<string | null>(null)
  const [following, setFollowing] = useState(0)
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [meetups, setMeetups] = useState<Meetup[]>([])
  const [filter, setFilter] = useState<Filter>('all')
  const [groups, setGroups] = useState<FeedGroup[]>([])
  const [pinned, setPinned] = useState<Post | null>(null)
  const [caption, setCaption] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [more, setMore] = useState(false)
  const [composer, setComposer] = useState<Template | 'blank' | null>(null)
  const main = !clubId && !groupId
  const scope = filter === 'friends' || filter === 'clubs' ? filter : 'all'
  const group = groupId ?? (filter.startsWith('g:') ? filter.slice(2) : undefined)

  useEffect(() => {
    if (!main) return
    listGroups().then((r) => {
      setGroups(r.groups)
      setFilter((f) => (f.startsWith('g:') && !r.groups.some((g) => `g:${g.id}` === f) ? 'all' : f))
    }, () => { /* chips still work without groups */ })
  }, [main, groupsKey])

  const load = useCallback(() => {
    if (main) getMyMeetups().then((r) => setMeetups(r.meetups.filter((m) => m.my_rsvp === 'going').slice(0, 4)), () => { /* a bonus */ })
    return getCommunityFeed(null, clubId, scope, group).then((r) => {
      setItems(r.items); setNext(r.next); setFollowing(r.following); setPinned(r.pinned ?? null); setError(null)
      if (main && r.drafts) return getDrafts().then((d) => setDrafts(d.drafts))
      if (main) setDrafts([])
    }, (e) => setError((e as Error).message))
  }, [clubId, scope, group, main])
  useEffect(() => { void load() }, [load])
  useRefreshOnShow(() => { if (main) void load() })

  async function loadMore() {
    if (!next) return
    setMore(true)
    try { const r = await getCommunityFeed(next, clubId, scope, group); setItems((xs) => [...(xs ?? []), ...r.items]); setNext(r.next) }
    catch (e) { setError((e as Error).message) } finally { setMore(false) }
  }
  const chips: [Filter, string][] = [['all', 'All'], ['friends', 'Friends'],
    ...groups.map((g): [Filter, string] => [`g:${g.id}`, `${g.emoji} ${g.name}`]), ['clubs', 'Clubs']]
  const openGroup = filter.startsWith('g:') ? groups.find((g) => `g:${g.id}` === filter) : undefined
  const put = (p: Post) => setItems((xs) => (xs ?? []).map((x) => (x.id === p.id ? p : x)))
  const drop = (id: string) => setItems((xs) => (xs ?? []).filter((x) => x.id !== id))
  const dropAuthor = (uid: string) => setItems((xs) => (xs ?? []).filter((x) => x.author !== uid))
  const add = (p: Post) => setItems((xs) => [p, ...(xs ?? [])])

  return (
    <>
      {main && <PullToRefresh onRefresh={load} />}
      <div className="flex items-center gap-2">
        <button type="button" onClick={() => setComposer('blank')}
          className="flex min-h-12 flex-1 items-center gap-2.5 rounded-2xl border border-(--border) bg-(--bg-surface) px-4 text-left text-[0.8824rem] text-(--text-muted) active:bg-(--bg-inset)">
          <SquarePen className="size-[18px] text-(--accent)" aria-hidden />
          {clubName ? `Share with ${clubName}…` : groupName ? `Share with ${groupName}…` : 'Share something'}
        </button>
        {main && onInvite && (
          <Button variant="ghost" className="hit-44 h-11 w-11 shrink-0 p-0" aria-label="Find friends" onClick={onInvite}>
            <UserPlus className="size-[18px]" />
          </Button>
        )}
        {onSettings && (
          <Button variant="ghost" className="hit-44 h-11 w-11 shrink-0 p-0" aria-label="Sharing settings" onClick={onSettings}>
            <SlidersHorizontal className="size-[18px]" />
          </Button>
        )}
      </div>
      {drafts.length > 0 && (
        <DraftsTray drafts={drafts} onShared={(d, p) => { setDrafts((xs) => xs.filter((x) => x.id !== d.id)); add(p) }}
          onDismissed={(d) => setDrafts((xs) => xs.filter((x) => x.id !== d.id))} />
      )}
      {meetups.length > 0 && <ComingUp meetups={meetups} onOpenClub={onOpenClub} />}
      {main && (
        <nav aria-label="Whose feed" className="-mx-4 flex items-center gap-1.5 overflow-x-auto px-4 py-0.5 no-scrollbar">
          <div role="radiogroup" aria-label="Show" className="flex items-center gap-1.5">
            {chips.map(([v, label]) => (
              <button key={v} type="button" role="radio" aria-checked={filter === v} onClick={() => setFilter(v)}
                className={cn('inline-flex min-h-11 shrink-0 items-center whitespace-nowrap rounded-full px-4 text-[0.7647rem] font-semibold transition-colors',
                  filter === v ? 'bg-(--accent) text-(--on-fill)' : 'bg-(--bg-inset) text-(--text-secondary) active:bg-(--border)')}>{label}</button>
            ))}
          </div>
          {onNewGroup && (
            <button type="button" onClick={onNewGroup}
              className="inline-flex min-h-11 shrink-0 items-center gap-1 whitespace-nowrap rounded-full border border-dashed border-(--border-strong) px-4 text-[0.7647rem] font-semibold text-(--accent) active:bg-(--bg-inset)">
              <Plus className="size-4" aria-hidden /> New group
            </button>
          )}
        </nav>
      )}
      {main && openGroup && onOpenGroup && (
        <button type="button" onClick={() => onOpenGroup(openGroup.id)}
          className="flex min-h-11 items-center gap-2 rounded-xl border border-(--border) bg-(--bg-surface) px-3 text-left text-[0.7647rem] text-(--text-secondary) active:bg-(--bg-inset)">
          <UsersRound className="size-4 text-(--accent)" aria-hidden />
          <span className="min-w-0 flex-1 truncate">{openGroup.emoji} {openGroup.name} · {openGroup.count} {openGroup.count === 1 ? 'person' : 'people'} · only the group sees these</span>
          <span className="font-semibold text-(--accent)">Members</span>
        </button>
      )}
      {pinned && (
        <section aria-label="Your workout, just synced" className="flex flex-col gap-1.5">
          <p className="flex items-center gap-1 px-1 text-[0.6471rem] font-semibold uppercase tracking-widest text-(--accent)">
            <Pin className="size-3" aria-hidden /> Just synced · pinned for an hour
          </p>
          <PostCard post={pinned} imperial={imperial} onChange={setPinned} onDelete={() => setPinned(null)} />
          {pinned.prompt && (
            <Button variant="primary" className="h-11 gap-1.5 text-[0.7647rem]" onClick={() => setCaption(true)}>
              <ImagePlus className="size-4" /> {pinned.prompt}
            </Button>
          )}
        </section>
      )}
      {error && <ErrorState compact message={error} onRetry={() => void load()} />}
      {items == null ? (error ? null : <FeedSkeleton />) : (
        <>
          {main && (filter === 'all' || filter === 'friends') && !items.some((p) => !p.mine && p.kind === 'workout') && (
            <FeedHint onInvite={items.length > 0 ? onInvite : undefined} onShared={() => void load()} />
          )}
          {items.length === 0 && (
            <EmptyRabbit hero size={60} mode={!main ? 'peek' : 'sleep'} className="rounded-2xl border border-(--border) bg-(--bg-surface) px-5 py-6"
              title={group ? 'Nothing in this group yet' : !main || filter !== 'all' ? 'Quiet in here' : following === 0 ? 'Your crew starts here' : 'Nothing shared yet'}
              body={clubId ? 'Share the first news with the club: a meetup recap, a race, a welcome.'
                : group ? "Members' workouts and posts show up here. Share the plan for Saturday, a photo from the run, a cheer. Only the group sees it."
                : filter === 'clubs' ? 'Posts from clubs you join show up here. Find one in Local.'
                : following === 0 ? "Follow friends to see their workouts here as soon as they sync. Then make a group for your crew."
                : 'Workouts your friends share show up here as soon as they sync. First races, new PRs, comebacks: share yours too.'}
              action={group ? (
                <Button variant="primary" className="mt-1 h-11 gap-1.5 px-4 text-[0.7647rem]" onClick={() => setComposer('blank')}>
                  <SquarePen className="size-4" /> Post to the group
                </Button>
              ) : main && (filter === 'all' || filter === 'friends') && onInvite ? (
                <div className="mt-1 flex flex-wrap justify-center gap-2">
                  <Button variant="primary" className="h-11 gap-1.5 px-4 text-[0.7647rem]" onClick={onInvite}>
                    <UserPlus className="size-4" /> Find friends
                  </Button>
                  {onNewGroup && following > 0 && (
                    <Button variant="default" className="h-11 gap-1.5 px-4 text-[0.7647rem]" onClick={onNewGroup}>
                      <Plus className="size-4" /> New group
                    </Button>
                  )}
                </div>
              ) : undefined} />
          )}
          <div className="flex flex-col gap-3">
            {items.map((p, i) => (
              <HopIn key={p.id} play={i < 4} index={i}>
                <PostCard post={p} imperial={imperial} onChange={put} onDelete={() => drop(p.id)} onBlocked={() => dropAuthor(p.author)} />
              </HopIn>
            ))}
          </div>
          {next && (
            <Button variant="default" className="h-11 text-[0.7647rem]" loading={more} onClick={() => void loadMore()}>Show older</Button>
          )}
        </>
      )}
      {composer && (
        <Composer clubId={clubId} clubName={clubName} groupId={groupId ?? openGroup?.id} groupName={groupName ?? openGroup?.name}
          groups={groups} template={composer === 'blank' ? null : composer}
          onClose={() => setComposer(null)} onPosted={(p) => { add(p); setComposer(null) }} />
      )}
      {caption && pinned && (
        <CaptionSheet post={pinned} onClose={() => setCaption(false)}
          onSaved={(p) => { setPinned({ ...p, prompt: null }); setCaption(false) }} />
      )}
    </>
  )
}

// ------------------------------------------------------------- coming up ---
function ComingUp({ meetups, onOpenClub }: { meetups: Meetup[]; onOpenClub?: (id: string) => void }) {
  return (
    <section aria-label="Meetups you're going to" className="flex flex-col gap-1.5">
      <h3 className="px-1 text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">You're going</h3>
      <div className="-mx-4 flex snap-x gap-2 overflow-x-auto px-4 pb-1">
        {meetups.map((m) => (
          <button key={`${m.id}-${m.next}`} type="button" onClick={() => { if (m.club) onOpenClub?.(m.club.id) }}
            className="flex min-w-[12rem] snap-start flex-col gap-0.5 rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-2 text-left active:bg-(--bg-inset)">
            <span className="text-[0.7059rem] font-semibold text-(--accent)">{m.next ? meetupWhen(m.next) : ''}</span>
            <span className="truncate text-[0.8235rem] font-medium text-(--text)">{m.title}</span>
            <span className="flex items-center gap-1 truncate text-[0.6471rem] text-(--text-muted)">
              <span aria-hidden>{m.club?.emoji}</span>{m.club?.name} · <MapPin className="size-3 shrink-0" />{m.where}
            </span>
          </button>
        ))}
      </div>
    </section>
  )
}

// -------------------------------------------------------------- composer ---
function Composer({ clubId, clubName, groupId, groupName, groups = [], template, onClose, onPosted }: {
  clubId?: string; clubName?: string; groupId?: string; groupName?: string; groups?: FeedGroup[]
  template: Template | null; onClose: () => void; onPosted: (p: Post) => void
}) {
  // Text first, photos right under it, then Post. Category, feeling and a linked event sit
  // behind "Add details". Text, category, feeling, linked event and audience are kept as a
  // draft (lib/drafts) until posted or discarded. Photos can't be kept in a draft.
  type PostDraft = { text: string; category: Category; feeling: string | null; eventId: string; audience: Audience }
  const [d, setD, draft] = useDraft<PostDraft>(`post.${clubId ? `club.${clubId}` : groupId ? `grp.${groupId}` : 'feed'}`, () => ({
    text: template?.text ?? '', category: template?.category ?? 'life', feeling: null, eventId: '',
    audience: clubId ? `club:${clubId}` : groupId ? `grp:${groupId}` : 'friends',
  }), { label: 'post', isEmpty: (v) => !v.text.trim() })
  const { text, category, feeling, eventId, audience } = d
  const setText = (text: string) => setD((x) => ({ ...x, text }))
  const setCategory = (category: Category) => setD((x) => ({ ...x, category }))
  const setFeeling = (feeling: string | null) => setD((x) => ({ ...x, feeling }))
  const setEventId = (eventId: string) => setD((x) => ({ ...x, eventId }))
  const setAudience = (audience: Audience) => setD((x) => ({ ...x, audience }))
  const photos = usePhotoPicker()
  const mention = useMentionField<HTMLTextAreaElement>({ value: text, setValue: setText, where: { audience } })
  const [queued, setQueued] = useState(false)
  const guard = useUnsavedGuard(!!text.trim() || photos.items.length > 0, draft.discard)
  const close = guard.wrap(onClose)
  const fixed = !!clubId || !!groupId
  const [events, setEvents] = useState<RaceEvent[] | null>(null)
  const [clubs, setClubs] = useState<ClubSummary[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [details, setDetails] = useState(() => !!template || !!feeling || !!eventId)
  const drag = useSheetDrag(close)

  useEffect(() => {
    listEvents().then((r) => setEvents(r.events), () => setEvents([]))
    if (!clubId) getClubs().then((g) => setClubs(g.clubs), () => { /* friends / everyone / only me still work */ })
  }, [clubId])

  async function post(el: HTMLElement) {
    setBusy(true); setErr(null); setQueued(false)
    try {
      // Durable + idempotent (lib/outbox): offline / 5xx keeps the text here and retries; a
      // retry can never post twice. Photos are already uploaded, so their ids go along.
      const r = await counted(saveDurably<{ post: Post }>({ method: 'POST', path: '/api/community/posts', label: 'post',
        body: { text: mention.encode(text).trim(), category, feeling, audience, photo_ids: photos.ids, event_id: eventId || null } },
      () => setQueued(true)), 'share', { what: 'post' })
      draft.clear()
      burst(el, 'kudos'); onPosted(r.post)
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false); setQueued(false) }
  }
  const canPost = (!!text.trim() || photos.ids.length > 0) && !photos.busy
  const AudIcon = audience === 'public' ? Globe : audience === 'private' ? Lock : audience.startsWith('club:') || audience.startsWith('grp:') ? UsersRound : Users
  const detailBits = [category !== 'life' || template ? CATEGORY_LABEL[category] : null, feeling, eventId ? 'event linked' : null].filter(Boolean)
  return (
    <div className="modal-overlay" onClick={close}>
      {guard.dialog}
      <div className="modal flex flex-col" onClick={(e) => e.stopPropagation()} {...drag}>
        <div className="sheet-handle" />
        <div className="modal-header">
          <h2 className="modal-title">{clubName ? `Share with ${clubName}` : groupName ? `Share with ${groupName}` : 'Share something'}</h2>
          <button className="modal-close" aria-label="Close" onClick={close}><X className="size-4" /></button>
        </div>
        <div className="modal-body flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
          <div className="relative">
            {mention.list}
            <textarea ref={mention.ref} aria-label="Post text" className={cn(areaCls, 'min-h-[96px] text-[0.9412rem]')} autoFocus maxLength={TEXT_LEN} value={text}
              onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { mention.onKeyDown(e) }} onSelect={mention.onSelect}
              placeholder={category === 'race' ? 'How did it go?' : category === 'gratitude' ? 'Who are you thankful for?' : 'What happened?'} />
            {text.length > TEXT_LEN * 0.8 && <p className="mt-0.5 text-right text-[0.6471rem] text-(--text-muted)">{text.length}/{TEXT_LEN}</p>}
          </div>
          <PhotoPicker picker={photos} />
          {!template && !text.trim() && !photos.items.length && !fixed && (
            <div className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-0.5" aria-label="Ideas">
              {TEMPLATES.map((t) => (
                <button key={t.label} type="button" onClick={() => { setD((x) => ({ ...x, text: t.text, category: t.category })) }}
                  className="inline-flex min-h-9 shrink-0 items-center gap-1 whitespace-nowrap rounded-full border border-(--border) bg-(--bg-surface) px-3 text-[0.7059rem] font-medium text-(--text-secondary) active:bg-(--bg-inset)">
                  <span aria-hidden>{t.emoji}</span>{t.label}
                </button>
              ))}
            </div>
          )}
          <button type="button" aria-expanded={details} onClick={() => setDetails((v) => !v)}
            className="flex min-h-11 items-center gap-2 rounded-xl px-1 text-left text-[0.7647rem] font-medium text-(--text-secondary) active:bg-(--bg-inset)">
            <SlidersHorizontal className="size-4 text-(--text-muted)" aria-hidden />
            <span className="flex-1">{details ? 'Hide details' : 'Add details'}{!details && detailBits.length > 0 && <span className="text-(--text-muted)"> · {detailBits.join(' · ')}</span>}</span>
            <ChevronRight className={cn('size-4 text-(--text-muted) transition-transform', details && 'rotate-90')} aria-hidden />
          </button>
          {details && (
            <div className="flex flex-col gap-3">
              <div className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-0.5" role="radiogroup" aria-label="What is it">
                {CATEGORIES.map(([id, label]) => (
                  <button key={id} type="button" role="radio" aria-checked={category === id} onClick={() => setCategory(id)}
                    className={cn('min-h-9 shrink-0 whitespace-nowrap rounded-full border px-3 text-[0.7059rem] font-medium',
                      category === id ? 'border-(--accent) bg-(--accent-subtle) text-(--accent)' : 'border-(--border) text-(--text-secondary)')}>{label}</button>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-0.5" role="radiogroup" aria-label="Feeling">
                {FEELINGS.map((f) => (
                  <button key={f} type="button" role="radio" aria-checked={feeling === f} aria-label={`Feeling ${f}`}
                    onClick={() => setFeeling(feeling === f ? null : f)}
                    className={cn('hit-44 flex size-9 items-center justify-center rounded-full text-[1.0588rem]', feeling === f ? 'bg-(--accent-subtle) ring-1 ring-(--accent)' : 'opacity-70')}>{f}</button>
                ))}
              </div>
              {events && events.length > 0 && (
                <label className="flex flex-col gap-1 text-[0.6471rem] text-(--text-muted)">Link an event
                  <select className={cn(inputCls, 'text-[0.8235rem]')} value={eventId} onChange={(e) => setEventId(e.target.value)}>
                    <option value="">None</option>
                    {events.map((e) => <option key={e.id} value={e.id}>{e.name} · {e.date}</option>)}
                  </select>
                </label>
              )}
            </div>
          )}
          <p className="text-[0.6471rem] text-(--text-muted)">Never your heart rate, health data or where you trained.</p>
          {draft.restored && (
            <p className="flex flex-wrap items-center gap-x-2 text-[0.6471rem] text-(--text-muted)" role="status">
              <span>Restored your unsaved post. Photos aren't kept in drafts: add them again.</span>
              <button type="button" className="hit-44 underline" onClick={draft.discard}>Discard draft</button>
            </p>
          )}
          {queued && <SaveStatus state="queued" />}
          {err && <p className="text-[0.7059rem] text-(--danger)" role="alert">{err}</p>}
        </div>
        <div className="flex items-center gap-2 border-t border-(--border) bg-(--bg-surface) px-4 pb-[max(12px,env(safe-area-inset-bottom))] pt-3">
          {fixed ? (
            <span className="flex min-w-0 flex-1 items-center gap-1.5 truncate text-[0.7059rem] text-(--text-muted)">
              <UsersRound className="size-4 shrink-0" aria-hidden /> Only {clubName ?? groupName ?? 'members'} see it
            </span>
          ) : (
            <label className="relative flex min-w-0 flex-1 items-center">
              <span className="sr-only">Who can see it</span>
              <AudIcon className="pointer-events-none absolute left-3 size-4 text-(--text-secondary)" aria-hidden />
              <select value={audience} onChange={(e) => setAudience(e.target.value)}
                className="h-11 w-full min-w-0 appearance-none truncate rounded-full border border-(--border) bg-(--bg-surface) pl-9 pr-7 text-[0.7647rem] font-medium text-(--text)">
                <option value="friends">Friends</option>
                {groups.map((g) => <option key={g.id} value={`grp:${g.id}`}>{g.emoji} {g.name}</option>)}
                <option value="public">Everyone on Rabbit</option>
                {clubs.map((g) => <option key={g.id} value={`club:${g.id}`}>{g.name}</option>)}
                <option value="private">Only me</option>
              </select>
              <ChevronRight className="pointer-events-none absolute right-3 size-3.5 rotate-90 text-(--text-muted)" aria-hidden />
            </label>
          )}
          <Button variant="primary" className="h-11 shrink-0 gap-1.5 px-5 text-[0.8235rem]" loading={busy} disabled={!canPost}
            onClick={(e) => void post(e.currentTarget)}>
            <Send className="size-4" /> {photos.busy ? 'Uploading…' : 'Post'}
          </Button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- drafts ---
function DraftsTray({ drafts, onShared, onDismissed }: {
  drafts: Draft[]; onShared: (d: Draft, p: Post) => void; onDismissed: (d: Draft) => void
}) {
  const [open, setOpen] = useState(drafts.length <= 2)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const btns = useRef<Record<string, HTMLButtonElement | null>>({})
  async function share(d: Draft) {
    setBusy(d.id); setErr(null)
    try { const r = await shareDraft(d.id); burst(btns.current[d.id], 'kudos'); onShared(d, r.post) }
    catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }
  async function later(d: Draft) {
    setBusy(d.id)
    try { await dismissDraft(d.id); onDismissed(d) } catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }
  const n = drafts.length
  return (
    <section className="rounded-2xl border border-(--accent)/30 bg-(--accent-subtle) p-3">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="flex min-h-11 w-full items-center gap-2 text-left">
        <span className="celebrate text-[1.0588rem]" aria-hidden>🎉</span>
        <span className="flex-1 text-[0.8235rem] font-medium text-(--text)">Rabbit spotted {n} milestone{n === 1 ? '' : 's'} to share</span>
        <span className="text-[0.7059rem] text-(--accent)">{open ? 'Hide' : 'Show'}</span>
      </button>
      {open && (
        <ul className="mt-1 flex flex-col gap-2">
          {drafts.map((d) => (
            <li key={d.id} className="rounded-xl bg-(--bg-surface) p-3">
              <p className="text-[0.8235rem] leading-snug text-(--text)">{d.text}</p>
              {d.event && <EventChip e={d.event} />}
              <div className="mt-2 flex gap-2">
                <Button variant="default" className="h-11 flex-1 text-[0.7647rem]" disabled={busy != null} onClick={() => void later(d)}>Not now</Button>
                <Button ref={(el) => { btns.current[d.id] = el }} variant="primary" className="h-11 flex-1 text-[0.7647rem]"
                  loading={busy === d.id} disabled={busy != null && busy !== d.id} onClick={() => void share(d)}>Share</Button>
              </div>
            </li>
          ))}
          <li className="px-1 text-[0.6471rem] text-(--text-muted)">Goes to your default audience. Nothing is shared unless you tap Share.</li>
        </ul>
      )}
      {err && <p className="mt-1 text-[0.7059rem] text-(--danger)">{err}</p>}
    </section>
  )
}

function EventChip({ e }: { e: { name: string; date: string } }) {
  return (
    <span className="mt-2 inline-flex max-w-full items-center gap-1.5 rounded-full border border-(--border) px-2.5 py-1 text-[0.7059rem] text-(--text-secondary)">
      <CalendarDays className="size-3.5 shrink-0" />
      <span className="truncate">{e.name}</span>
      <span className="shrink-0 text-(--text-muted)">· {new Date(`${e.date}T12:00:00`).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })}</span>
    </span>
  )
}

// ------------------------------------------------------------------ post ---
export function PostCard({ post: p, imperial, onChange, onDelete, onBlocked, expanded, focusComment }: {
  post: Post; imperial: boolean; onChange: (p: Post) => void; onDelete: () => void; onBlocked?: () => void
  /** comments open (the single-post page) */
  expanded?: boolean
  /** a comment to scroll to and highlight (a mention notification) */
  focusComment?: string
}) {
  const [menu, setMenu] = useState(false)
  const [details, setDetails] = useState(false)  // a friend's workout, read-only
  // Edit and "Add photos" both open the photo + caption sheet (CaptionSheet).
  const [editing, setEditing] = useState<null | 'edit' | 'photos'>(null)
  // An unsent comment is kept per post (lib/drafts); a card with one opens its comments.
  const [comment, setComment, commentDraft] = useDraft<string>(`comment.${p.id}`, '', { label: 'comment', isEmpty: (v) => !v.trim() })
  const [showComments, setShowComments] = useState(() => !!expanded || readDraft<string>(`comment.${p.id}`) != null)
  const [commentQueued, setCommentQueued] = useState(false)
  const [replyTo, setReplyTo] = useState<PostComment | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const reactBtns = useRef<Partial<Record<ReactionKind, HTMLButtonElement | null>>>({})
  const mention = useMentionField<HTMLInputElement>({ value: comment, setValue: setComment, where: { pid: p.id } })
  const input = mention.ref
  // Async replies (comment sent, reaction saved) apply to the post as it is when they land, not
  // as it was when the request went out: a stale copy would drop a comment added meanwhile.
  const latest = useRef(p)
  latest.current = p
  const typed = useRef(comment)
  typed.current = comment
  const name = p.mine ? 'You' : p.user?.name ?? 'Someone'
  const photos = postPhotoUrls(p)

  async function toggle(kind: ReactionKind) {
    const prev = p
    const was = p.my_reaction
    const counts = { ...p.reactions }
    if (was) counts[was] = Math.max(0, counts[was] - 1)
    if (was !== kind) { counts[kind] += 1; burst(reactBtns.current[kind], 'kudos') }
    const total = Object.values(counts).reduce((a, b) => a + b, 0)
    onChange({ ...p, reactions: counts, my_reaction: was === kind ? null : kind, reaction_total: total })
    try { const r = was === kind ? await unreact(p.id) : await react(p.id, kind); onChange({ ...r.post, comments: latest.current.comments }) }
    catch (e) { onChange(prev); setErr((e as Error).message) }
  }
  async function openComments() {
    const next = !showComments
    setShowComments(next)
    if (next && p.comment_count > p.comments.length) {
      try { const r = await getPost(p.id); onChange(r.post) } catch (e) { setErr((e as Error).message) }
    }
  }
  function startReply(c: PostComment) {
    setReplyTo(c); setShowComments(true); window.setTimeout(() => input.current?.focus(), 0)
  }
  async function send() {
    if (busy) return  // one comment at a time; a second Enter while sending does nothing
    const sent = comment
    const t = mention.encode(sent).trim()
    if (!t) return
    setBusy(true); setErr(null); setCommentQueued(false)
    try {
      // Durable + idempotent: kept and retried when offline, never posted twice.
      const r = await saveDurably<{ comment: PostComment }>({ method: 'POST', label: 'comment',
        path: `/api/community/posts/${encodeURIComponent(p.id)}/comments`, body: { text: t, reply_to: replyTo?.id ?? null } },
      () => setCommentQueued(true))
      const now = latest.current
      if (!now.comments.some((c) => c.id === r.comment.id)) {
        onChange({ ...now, comments: [...now.comments, r.comment], comment_count: now.comment_count + 1 })
      }
      // Clear the box only if it still holds what was sent (not something typed since).
      if (typed.current === sent) { setComment(''); commentDraft.clear(); mention.reset() }
      setReplyTo(null)
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false); setCommentQueued(false) }
  }
  async function removeComment(cid: string) {
    try {
      await deleteComment(p.id, cid)
      const now = latest.current
      const gone = now.comments.filter((c) => c.id === cid || c.parent === cid).length
      onChange({ ...now, comments: now.comments.filter((c) => c.id !== cid && c.parent !== cid), comment_count: Math.max(0, now.comment_count - gone) })
    } catch (e) { setErr((e as Error).message) }
  }
  async function remove() {
    setMenu(false)
    if (!(await confirmAsk('Delete this post?', { confirm: 'Delete', danger: true }))) return
    try { await deletePost(p.id); onDelete() } catch (e) { setErr((e as Error).message) }
  }
  async function hide() {
    setMenu(false)
    try { const r = await hidePost(p.id); setNotice(r.message); window.setTimeout(onDelete, 1200) }
    catch (e) { setErr((e as Error).message) }
  }
  async function report() {
    setMenu(false)
    if (!(await confirmAsk('Report this post?', { detail: 'It disappears for you and the Rabbit team takes a look.', confirm: 'Report', danger: true }))) return
    try { const r = await reportPost(p.id); setNotice(r.message); window.setTimeout(onDelete, 1500) }
    catch (e) { setErr((e as Error).message) }
  }
  async function block() {
    setMenu(false)
    if (!(await confirmAsk(`Block ${p.user?.name ?? 'this person'}?`, { detail: "You won't see each other's posts or comments anywhere on Rabbit.", confirm: 'Block', danger: true }))) return
    try { await blockUser(p.author); setNotice('Blocked.'); window.setTimeout(() => (onBlocked ?? onDelete)(), 1000) }
    catch (e) { setErr((e as Error).message) }
  }

  // One-level threads: top-level comments, each with its replies under it.
  const tops = p.comments.filter((c) => !c.parent || !p.comments.some((x) => x.id === c.parent))
  const replies = (id: string) => p.comments.filter((c) => c.parent === id)
  const audience = p.audience === 'public' ? <><Globe className="size-3" /><span>Everyone</span></>
    : p.audience === 'private' ? <><Lock className="size-3" /><span>Only you</span></>
    : p.club ? <><Users className="size-3" /><span className="truncate">{p.club.name}</span></>
    : p.groups?.length ? <><UsersRound className="size-3" /><span className="truncate">{p.groups.map((g) => `${g.emoji} ${g.name}`).join(', ')}</span></> : null

  return (
    <article className="rounded-2xl border border-(--border) bg-(--bg-surface) p-3.5">
      <header className="flex items-center gap-2.5">
        {!p.mine && p.user ? <TapAvatar p={p.user} size={36} /> : <PersonAvatar u={p.user} />}
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[0.8235rem] font-medium text-(--text)">
            {!p.mine && p.user ? <PersonLink id={p.user.id} name={name} /> : name}{p.feeling && <span className="ml-1" aria-label={`feeling ${p.feeling}`}>{p.feeling}</span>}
          </span>
          <span className="flex items-center gap-1 text-[0.6471rem] text-(--text-muted)" title={audienceLabel(p.audience, p.club)}>
            {ago(p.created)}{p.edited ? ' · edited' : ''}{audience && <><span>·</span>{audience}</>}
          </span>
        </span>
        <span className="shrink-0 rounded-full bg-(--accent-subtle) px-2 py-0.5 text-[0.6471rem] font-semibold text-(--accent)">{p.kind === 'workout' ? 'Workout' : CATEGORY_LABEL[p.category]}</span>
        <div className="relative">
          <Button variant="ghost" className="hit-44 h-8 w-8 p-0" aria-label="Post options" aria-expanded={menu} onClick={() => setMenu((m) => !m)}>
            <Ellipsis className="size-4" />
          </Button>
          {menu && (
            <div className="absolute right-0 top-9 z-10 flex w-44 flex-col rounded-xl border border-(--border) bg-(--bg-surface) py-1 shadow-lg" role="menu">
              {p.mine ? (
                <>
                  <MenuItem icon={<ImagePlus className="size-4" />} label={p.photos.length ? 'Photos' : 'Add photos'} onClick={() => { setMenu(false); setEditing('photos') }} />
                  <MenuItem icon={<Pencil className="size-4" />} label="Edit" onClick={() => { setMenu(false); setEditing('edit') }} />
                  <MenuItem icon={<Trash2 className="size-4" />} label="Delete" danger onClick={() => void remove()} />
                </>
              ) : (
                <>
                  <MenuItem icon={<EyeOff className="size-4" />} label="Hide post" onClick={() => void hide()} />
                  <MenuItem icon={<Flag className="size-4" />} label="Report" onClick={() => void report()} />
                  <MenuItem icon={<Ban className="size-4" />} label={`Block ${p.user?.name ?? ''}`.trim()} danger onClick={() => void block()} />
                </>
              )}
            </div>
          )}
        </div>
      </header>

      {p.text ? (
        <p className="mt-2.5 whitespace-pre-wrap break-words text-[0.9412rem] leading-snug text-(--text)"><MentionText text={p.text} mentions={p.mentions} /></p>
      ) : null}
      {photos.length > 0 && <PhotoGrid urls={photos} who={p.mine ? 'your' : `${p.user?.name ?? 'their'}'s`} />}
      {editing && (
        <CaptionSheet post={p} title={editing === 'edit' ? 'Edit post' : p.photos.length ? 'Photos' : 'Add photos'}
          onClose={() => setEditing(null)} onSaved={(np) => { onChange({ ...np, comments: p.comments }); setEditing(null) }} />
      )}
      {p.workout && <WorkoutCard w={p.workout} imperial={imperial}
        onOpen={p.mine && p.workout.activity_id != null ? () => openActivity(p.workout!.activity_id) : () => setDetails(true)} />}
      {details && p.workout && (
        <FriendWorkoutSheet w={p.workout} who={p.user?.name ?? 'They'} imperial={imperial} onClose={() => setDetails(false)}
          onMessage={p.user ? () => { setDetails(false); messagePeople([p.user!.id]) } : undefined} />
      )}
      {p.event && <EventChip e={p.event} />}
      {notice && <p className="mt-2 text-[0.7059rem] text-(--accent)" role="status">{notice}</p>}

      <div className="mt-2.5 flex flex-wrap items-center gap-0.5">
        {REACTIONS.map(([kind, emoji, label]) => {
          const n = p.reactions[kind]
          const on = p.my_reaction === kind
          return (
            <button key={kind} ref={(el) => { reactBtns.current[kind] = el }} type="button" aria-pressed={on}
              aria-label={`${label}${n ? `, ${n}` : ''}`} onClick={() => void toggle(kind)}
              className={cn('hit-44 inline-flex h-8 items-center gap-1 rounded-full px-2.5 text-[0.7059rem] font-medium transition-colors',
                on ? 'bg-(--accent-subtle) text-(--accent)' : 'text-(--text-secondary) active:bg-(--bg-inset)')}>
              <span className={cn('text-[0.9412rem]', on && 'celebrate')} aria-hidden>{emoji}</span>
              {n > 0 && <span className="tabular-nums">{n}</span>}
            </button>
          )
        })}
        <span className="flex-1" />
        {!p.mine && p.user && (
          <button type="button" onClick={() => messagePeople([p.user!.id])} aria-label={`Message ${p.user.name}`}
            className="hit-44 inline-flex h-8 items-center gap-1.5 rounded-full px-2.5 text-[0.7059rem] font-medium text-(--text-secondary) active:bg-(--bg-inset)">
            <Send className="size-4" aria-hidden /> Message
          </button>
        )}
        <button type="button" onClick={() => void openComments()} aria-expanded={showComments}
          className="hit-44 inline-flex h-8 items-center gap-1.5 rounded-full px-2.5 text-[0.7059rem] font-medium text-(--text-secondary) active:bg-(--bg-inset)">
          <MessageCircle className="size-4" /> {p.comment_count > 0 ? p.comment_count : 'Comment'}
        </button>
      </div>

      {(showComments || (p.comments.length > 0 && p.comment_count <= 2)) && p.comments.length > 0 && (
        <ul className="mt-1.5 flex flex-col gap-1.5 border-t border-(--border) pt-2">
          {tops.map((c) => (
            <li key={c.id} id={`comment-${c.id}`} className={cn('flex scroll-mt-24 flex-col gap-1 rounded-lg', focusComment === c.id && 'comment-focus')}>
              <CommentLine c={c} onReply={() => startReply(c)} onDelete={() => void removeComment(c.id)} />
              {replies(c.id).length > 0 && (
                <ul className="ml-4 flex flex-col gap-1 border-l border-(--border) pl-2.5">
                  {replies(c.id).map((r) => (
                    <li key={r.id} id={`comment-${r.id}`} className={cn('scroll-mt-24 rounded-lg', focusComment === r.id && 'comment-focus')}><CommentLine c={r} onReply={() => startReply(c)} onDelete={() => void removeComment(r.id)} /></li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
      {showComments && (
        <div className="mt-2 flex flex-col gap-1">
          {replyTo && (
            <span className="flex items-center gap-1 text-[0.6471rem] text-(--text-muted)">
              <Reply className="size-3" /> Replying to {replyTo.mine ? 'yourself' : replyTo.by.name}
              <button type="button" className="hit-44 ml-1 underline" onClick={() => setReplyTo(null)}>cancel</button>
            </span>
          )}
          <div className="relative flex items-center gap-2">
            {mention.list}
            <input ref={input} aria-label={replyTo ? 'Reply' : 'Comment'} className={cn(inputCls, 'h-11 text-[0.8235rem]')} maxLength={COMMENT_LEN}
              placeholder={replyTo ? 'Write a reply…' : 'Say something… @ to tag'} enterKeyHint="send"
              value={comment} onChange={(e) => setComment(e.target.value)} onSelect={mention.onSelect}
              onKeyDown={(e) => { if (!mention.onKeyDown(e) && e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); void send() } }} />
            <Button variant="primary" className="h-11 w-11 shrink-0 p-0" aria-label="Send comment" loading={busy} disabled={!comment.trim()} onClick={() => void send()}>
              <Send className="size-4" />
            </Button>
          </div>
        </div>
      )}
      {commentQueued && <SaveStatus state="queued" className="mt-1.5" />}
      {err && <p className="mt-1.5 text-[0.7059rem] text-(--danger)">{err}</p>}
    </article>
  )
}

function MenuItem({ icon, label, danger, onClick }: { icon: React.ReactNode; label: string; danger?: boolean; onClick: () => void }) {
  return (
    <button type="button" role="menuitem" onClick={onClick}
      className={cn('flex min-h-11 items-center gap-2 px-3 text-left text-[0.7647rem]', danger && 'text-(--danger)')}>
      {icon}<span className="truncate">{label}</span>
    </button>
  )
}

function CommentLine({ c, onReply, onDelete }: { c: PostComment; onReply: () => void; onDelete: () => void }) {
  return (
    <div className="flex items-start gap-1.5 text-[0.7647rem] leading-snug">
      <span className="min-w-0 flex-1 break-words">
        {c.mine ? <span className="font-medium text-(--text)">You</span> : <PersonLink id={c.by.id} name={c.by.name} className="font-medium text-(--text)" />}{' '}
        <MentionText className="text-(--text-secondary)" text={c.text} mentions={c.mentions} />{' '}
        <span className="whitespace-nowrap text-[0.6471rem] text-(--text-muted)">{ago(c.ts)}</span>
      </span>
      <button type="button" aria-label="Reply" onClick={onReply} className="hit-44 shrink-0 p-0.5 text-(--text-muted)"><Reply className="size-3.5" /></button>
      {c.can_delete && (
        <button type="button" aria-label="Delete comment" onClick={onDelete} className="hit-44 shrink-0 p-0.5 text-(--text-muted)">
          <X className="size-3.5" />
        </button>
      )}
    </div>
  )
}

/** 1 photo full width; 2 side by side; 3 one wide on top; 4+ a 2x2 grid with "+N" on the last. */
function PhotoGrid({ urls, who = 'the' }: { urls: string[]; who?: string }) {
  const [open, setOpen] = useState<number | null>(null)
  const n = urls.length
  const shown = n > 4 ? urls.slice(0, 4) : urls
  return (
    <>
      <div className={cn('mt-2.5 grid gap-1 overflow-hidden rounded-xl', n > 1 ? 'grid-cols-2' : 'grid-cols-1')}>
        {shown.map((u, i) => (
          <button key={u} type="button" aria-label={`Open photo ${i + 1} of ${n}`} onClick={() => setOpen(i)}
            className={cn('relative overflow-hidden bg-(--bg-inset)', n === 3 && i === 0 && 'col-span-2')}>
            <img src={u} alt={`Photo ${i + 1} of ${n} in ${who} post`} loading="lazy"
              className={cn('w-full object-cover', n === 1 ? 'max-h-[28rem]' : n === 3 && i === 0 ? 'aspect-[2/1]' : 'aspect-square')} />
            {n > 4 && i === 3 && (
              <span className="absolute inset-0 flex items-center justify-center bg-black/45 text-[1.4118rem] font-semibold text-white" aria-hidden>+{n - 4}</span>
            )}
          </button>
        ))}
      </div>
      {open != null && <PhotoViewer urls={urls} start={open} who={who} onClose={() => setOpen(null)} />}
    </>
  )
}

const SPORT_EMOJI: Record<string, string> = { run: '🏃', bike: '🚴', swim: '🏊', hike: '🥾', walk: '🚶', strength: '🏋️', ski: '⛷️', brick: '🔁', climb: '🧗', paddle: '🛶' }

const SOURCE_LABEL: Record<string, string> = {
  garmin: 'Garmin', oura: 'Oura', whoop: 'WHOOP', apple: 'Apple Watch', coros: 'COROS', strava: 'Strava', polar: 'Polar', suunto: 'Suunto', wahoo: 'Wahoo',
}

function WorkoutCard({ w, imperial, onOpen }: { w: NonNullable<Post['workout']>; imperial: boolean; onOpen?: () => void }) {
  const pace = w.pace_s_km ? fmtPaceKm(w.pace_s_km, imperial) : w.speed_kmh ? fmtSpeed(w.speed_kmh, imperial)
    : w.pace_s_100m ? fmtSwim100(w.pace_s_100m, imperial) : null
  const stats: [string, string][] = ([
    ['Distance', w.km ? fmtDist(w.km, imperial, w.sport) : null], ['Time', w.minutes ? fmtDuration(w.minutes) : null],
    [w.speed_kmh ? 'Speed' : 'Pace', pace], ['Climb', w.climb_m && w.climb_m >= 30 ? fmtClimb(w.climb_m, imperial) : null],
  ] as [string, string | null][]).filter((x): x is [string, string] => !!x[1])
  const headline = w.headline || w.highlight
  const via = SOURCE_LABEL[w.source ?? 'garmin'] ?? 'Garmin'
  return (
    <div className="mt-2.5 rounded-xl border border-(--border) bg-(--bg-inset) px-3.5 py-3">
      <div className="flex items-center gap-2.5">
        <span aria-hidden className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-(--bg-surface) text-[1.2941rem]">{SPORT_EMOJI[w.sport] ?? '🐇'}</span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[0.9412rem] font-semibold text-(--text)">{w.title}</span>
          <span className="block text-[0.6471rem] text-(--text-muted)">{w.auto ? 'Synced' : 'Shared'} via {via}</span>
        </span>
      </div>
      {headline && <p className="mt-1.5 text-[0.7647rem] font-medium text-(--accent)">{headline}</p>}
      {stats.length > 0 && (
        <dl className="mt-2 grid grid-cols-3 gap-x-3 gap-y-1.5">
          {stats.map(([k, v]) => (
            <div key={k} className="min-w-0">
              <dt className="font-mono text-[0.6471rem] uppercase tracking-wider text-(--text-muted)">{k}</dt>
              <dd className="truncate font-mono text-[1rem] font-semibold tabular-nums text-(--text)">{v}</dd>
            </div>
          ))}
        </dl>
      )}
      {w.splits && w.splits.length >= 2 && <SplitBars splits={w.splits} sport={w.sport} />}
      {onOpen && (
        <button type="button" onClick={onOpen} className="mt-2 flex min-h-11 w-full items-center justify-between border-t border-(--border) pt-1 text-[0.7647rem] font-medium text-(--accent)">
          See all the details <ChevronRight className="size-4" aria-hidden />
        </button>
      )}
    </div>
  )
}

/** A friend's shared workout, read-only: exactly what they share (sport, distance, time, pace,
 *  climb, lap shape). Never heart rate, health data or where they went. */
function FriendWorkoutSheet({ w, who, imperial, onClose, onMessage }: {
  w: NonNullable<Post['workout']>; who: string; imperial: boolean; onClose: () => void; onMessage?: () => void
}) {
  const pace = w.pace_s_km ? fmtPaceKm(w.pace_s_km, imperial) : w.speed_kmh ? fmtSpeed(w.speed_kmh, imperial)
    : w.pace_s_100m ? fmtSwim100(w.pace_s_100m, imperial) : null
  const stats: [string, string][] = ([
    ['Distance', w.km ? fmtDist(w.km, imperial, w.sport) : null], ['Time', w.minutes ? fmtDuration(w.minutes) : null],
    [w.speed_kmh ? 'Speed' : 'Pace', pace], ['Climb', w.climb_m ? fmtClimb(w.climb_m, imperial) : null],
  ] as [string, string | null][]).filter((x): x is [string, string] => !!x[1])
  const laps = (w.splits ?? []).filter((x) => x.km > 0 && x.s > 0)
  return (
    <Sheet title={w.title} onClose={onClose} portal label={`${who}'s workout`}
      bodyClassName="settings flex flex-col gap-4 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
      <p className="text-[0.7647rem] text-(--text-secondary)">
        {who} · {w.date ? new Date(`${w.date.slice(0, 10)}T12:00:00`).toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' }) : ''}
      </p>
      {stats.length > 0 && (
        <dl className="grid grid-cols-2 gap-3 rounded-xl border border-(--border) bg-(--bg-surface) p-4">
          {stats.map(([k, v]) => (
            <div key={k}>
              <dt className="font-mono text-[0.6471rem] uppercase tracking-wider text-(--text-muted)">{k}</dt>
              <dd className="font-mono text-[1.0588rem] font-semibold tabular-nums text-(--text)">{v}</dd>
            </div>
          ))}
        </dl>
      )}
      {laps.length >= 2 && (
        <section aria-label="Laps" className="rounded-xl border border-(--border) bg-(--bg-surface) p-4">
          <h3 className="section-label mb-2">{w.sport === 'bike' ? 'Laps' : 'Splits'}</h3>
          <table className="w-full text-left text-[0.7647rem] tabular-nums">
            <thead><tr className="text-(--text-muted)"><th className="py-1 font-medium">#</th><th className="font-medium">Distance</th><th className="font-medium">Time</th><th className="font-medium">{w.sport === 'bike' ? 'Speed' : 'Pace'}</th></tr></thead>
            <tbody>
              {laps.map((x, i) => (
                <tr key={i} className="border-t border-(--border)">
                  <td className="py-1.5">{i + 1}</td>
                  <td>{fmtDist(x.km, imperial, w.sport, { decimals: 2 })}</td>
                  <td>{`${Math.floor(x.s / 60)}:${String(Math.round(x.s % 60)).padStart(2, '0')}`}</td>
                  <td>{w.sport === 'bike' ? fmtSpeed((x.km / x.s) * 3600, imperial) : fmtPaceKm(x.s / x.km, imperial)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      <p className="text-[0.7059rem] text-(--text-muted)">What {who} shares with friends. Heart rate, health data and where they went stay private.</p>
      {onMessage && (
        <Button variant="primary" className="h-11 gap-1.5 text-[0.8235rem]" onClick={onMessage}>
          <Send className="size-4" aria-hidden /> Message {who}
        </Button>
      )}
    </Sheet>
  )
}

/** A route-less shape of the workout: one bar per lap, taller = faster (pace per km, so a
 * short last lap still compares). No map, no heart rate. */
function SplitBars({ splits, sport }: { splits: { km: number; s: number }[]; sport: string }) {
  const speed = splits.map((x) => (x.km > 0 && x.s > 0 ? x.km / x.s : 0))
  const max = Math.max(...speed), min = Math.min(...speed.filter((v) => v > 0))
  const fastest = speed.indexOf(max)
  return (
    <div className="mt-2" role="img" aria-label={`${splits.length} ${sport === 'bike' ? 'laps' : 'splits'}, fastest is number ${fastest + 1}`}>
      <div className="flex h-10 items-end gap-[2px]" aria-hidden>
        {speed.map((v, i) => (
          <span key={i} className={cn('min-w-[3px] flex-1 rounded-t-sm', i === fastest ? 'bg-(--accent)' : 'bg-(--accent)/40')}
            style={{ height: `${max > min ? 30 + 70 * ((v - min) / (max - min)) : 70}%` }} />
        ))}
      </div>
      <p className="mt-0.5 text-[0.6471rem] text-(--text-muted)">{splits.length} {sport === 'bike' ? 'laps' : 'splits'} · taller is faster</p>
    </div>
  )
}

/** "Add photos or a caption" for my own post (the pinned auto-shared workout, or any workout
 *  post from its ... menu). Keeps the photos already on it. */
function CaptionSheet({ post, title = 'Add photos or a caption', onClose, onSaved }: {
  post: Post; title?: string; onClose: () => void; onSaved: (p: Post) => void
}) {
  // Shown as "@Name" while editing; the saved mentions stay picked (lib/mentions).
  const [text, setText] = useState(() => displayText(post.text))
  const mention = useMentionField<HTMLTextAreaElement>({ value: text, setValue: setText, where: { pid: post.id }, initial: tokensIn(post.text) })
  const photos = usePhotoPicker(existingPhotos(post.photo_ids, postPhotoUrls(post)))
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const changedPhotos = photos.ids.join() !== (post.photo_ids ?? []).join()
  async function save(el: HTMLElement) {
    setBusy(true); setErr(null)
    try {
      const r = await updatePost(post.id, { text: mention.encode(text).trim(), ...(changedPhotos ? { photo_ids: photos.ids } : {}) })
      burst(el, 'kudos'); onSaved({ ...r.post, comments: post.comments })
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <Sheet title={title} onClose={onClose}
      bodyClassName="flex flex-col gap-3 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
      <div className="relative">
        {mention.list}
        <textarea ref={mention.ref} aria-label="Caption" className={cn(areaCls, 'min-h-[90px] text-[0.9412rem]')} autoFocus maxLength={TEXT_LEN} value={text}
          placeholder="How did it feel?" onChange={(e) => setText(e.target.value)} onSelect={mention.onSelect}
          onKeyDown={(e) => { mention.onKeyDown(e) }} />
      </div>
      <PhotoPicker picker={photos} />
      {err && <p className="text-[0.7059rem] text-(--danger)" role="alert">{err}</p>}
      <Button variant="primary" className="h-11 text-[0.8235rem]" loading={busy}
        disabled={photos.busy || (!changedPhotos && mention.encode(text).trim() === post.text.trim())
          || (!text.trim() && !photos.ids.length && !post.workout && !post.milestone)}
        onClick={(e) => void save(e.currentTarget)}>{photos.busy ? 'Uploading…' : 'Save'}</Button>
    </Sheet>
  )
}

/** Full-screen photos: swipe or use the arrows (and arrow keys) to move between them; a
 *  keyboard dialog (focus in, Escape closes, focus returns). */
function PhotoViewer({ urls, start, who, onClose }: { urls: string[]; start: number; who: string; onClose: () => void }) {
  const box = useRef<HTMLDivElement>(null)
  const [i, setI] = useState(start)
  const x0 = useRef<number | null>(null)
  useDialog(box, onClose)
  const n = urls.length
  const go = (d: number) => setI((v) => Math.min(n - 1, Math.max(0, v + d)))
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'ArrowRight') go(1); else if (e.key === 'ArrowLeft') go(-1) }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  })
  const navCls = 'hit-44 absolute top-1/2 flex size-10 -translate-y-1/2 items-center justify-center rounded-full bg-black/55 text-white disabled:opacity-0'
  return (
    // Inline style: .modal-overlay's own background and bottom alignment (for sheets) win over utilities.
    <div ref={box} className="modal-overlay justify-center" style={{ background: 'rgba(0,0,0,0.92)', alignItems: 'center' }}
      onClick={onClose} role="dialog" aria-modal="true" aria-label={`Photo ${i + 1} of ${n}`}
      onTouchStart={(e) => { x0.current = e.touches[0]?.clientX ?? null }}
      onTouchEnd={(e) => {
        const dx = (e.changedTouches[0]?.clientX ?? 0) - (x0.current ?? 0)
        if (x0.current != null && Math.abs(dx) > 50) { e.preventDefault(); go(dx < 0 ? 1 : -1) }
        x0.current = null
      }}>
      <img key={urls[i]} src={urls[i]} alt={`Photo ${i + 1} of ${n} in ${who} post`} className="rb-pop max-h-[86dvh] max-w-full object-contain"
        onClick={(e) => e.stopPropagation()} />
      {n > 1 && (
        <>
          <button type="button" aria-label="Previous photo" disabled={i === 0} className={cn(navCls, 'left-2')}
            onClick={(e) => { e.stopPropagation(); go(-1) }}><ChevronRight className="size-5 rotate-180" /></button>
          <button type="button" aria-label="Next photo" disabled={i === n - 1} className={cn(navCls, 'right-2')}
            onClick={(e) => { e.stopPropagation(); go(1) }}><ChevronRight className="size-5" /></button>
          <span className="absolute bottom-[max(16px,env(safe-area-inset-bottom))] left-1/2 -translate-x-1/2 rounded-full bg-black/55 px-3 py-1 text-[0.7059rem] font-medium text-white tabular-nums" aria-hidden>
            {i + 1} / {n}
          </span>
        </>
      )}
      <button type="button" aria-label="Close" className="hit-44 absolute right-3 top-[max(12px,env(safe-area-inset-top))] flex size-10 items-center justify-center rounded-full bg-black/60 text-white"
        onClick={onClose}><X className="size-5" /></button>
    </div>
  )
}
