// Community feed: "Share something" (life-event ideas inside the composer), the milestone drafts tray,
// meetups coming up, and calm post cards (category, text, up to 10 photos, linked event, four
// reactions with a burst, one-level comment threads). Also a club's feed (``clubId``): the
// composer posts to that club. Nothing is ever posted without a tap. Filter chips: All / Friends /
// each feed group / Clubs; a group's own feed (``groupId``) posts to that group only. My fresh
// auto-shared workout is pinned on top for an hour with "Add a photo or caption".
import { confirmAsk } from '@/lib/confirm'
import { useRefreshOnShow } from '@/hooks/useRefreshOnShow'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Ban, CalendarDays, Check, ChevronDown, ChevronRight, Ellipsis, EyeOff, Flag, Globe, ImagePlus, Lock, MapPin, MessageCircle, Pencil, Pin, Plus, Reply, Send, SlidersHorizontal, SquarePen, Trash2, UserPlus, Users, UsersRound, X } from 'lucide-react'
import { Avatar } from '@/components/Avatar'
import { EmptyRabbit, HopIn, PullToRefresh, burst } from '@/components/anim'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { areaCls, inputCls } from '@/components/plan/ui'
import { useSheetDrag } from '@/hooks/useSheetDrag'
import { useDialog } from '@/hooks/useDialog'
import { listEvents, type RaceEvent } from '@/lib/events'
import { fmtDist, fmtPaceKm, fmtSwim100 } from '@/lib/format'
import { FAMILY_NAME, famDist, legLine, sportFamily, splitsOk, statsFor } from '@/lib/sportstats'
import { SportTile } from '@/components/ui/SportTile'
import { listGroups, type FeedGroup } from '@/lib/community2'
import { Sheet } from '@/components/ui/Sheet'
import { blockUser, type SocialUser } from '@/lib/social'
import { cn } from '@/lib/utils'
import { PersonAvatar as TapAvatar, PersonLink } from '@/components/people/PersonLink'
import { openActivity } from '@/lib/activitynav'
import { RouteMini } from '@/components/route/RouteMap'
import { ShareNudge } from '@/components/community/ShareNudge'
import { messagePeople } from '@/lib/dm'
import {
  CATEGORIES, CATEGORY_LABEL, COMMENT_LEN, FEELINGS, REACTIONS, TEMPLATES, TEXT_LEN,
  ago, audienceLabel, communityPhotoUrl, deleteComment, deletePost, dismissDraft, editComment, likeComment,
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
import { CommentThreads, threadsOf } from './Comments'
import { openTarget } from '@/lib/people'
import { RabbitLoader } from '@/components/RabbitLoader'

/** Conversations shown inline on a feed card; a longer one continues on the post's own page. */
const INLINE_THREADS = 20
import { haptic } from '@/lib/haptics'
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
      <div className="flex flex-col gap-3">
        <button type="button" onClick={() => setComposer('blank')}
          className="flex min-h-14 w-full items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-4 py-3 text-left active:bg-(--bg-inset)">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-(--accent-subtle) text-(--accent)" aria-hidden>
            <SquarePen className="size-5" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-body-lg font-semibold text-(--text)">
              {clubName ? `Share with ${clubName}` : groupName ? `Share with ${groupName}` : 'Share something'}
            </span>
            <span className="block text-meta text-(--text-muted)">A photo, a race, a thank you</span>
          </span>
        </button>
        {main && (onInvite || onSettings) && (
          <div className="flex gap-2">
            {onInvite && (
              <Button variant="default" className="h-11 flex-1 gap-2 px-4 text-body" onClick={onInvite}>
                <UserPlus className="size-5" aria-hidden /> Find friends
              </Button>
            )}
            {onSettings && (
              <Button variant="default" className="h-11 shrink-0 gap-2 px-3.5 text-body" aria-label="Sharing settings" onClick={onSettings}>
                <SlidersHorizontal className="size-5" aria-hidden /><span className="hidden min-[360px]:inline">Sharing</span>
              </Button>
            )}
          </div>
        )}
      </div>
      {drafts.length > 0 && (
        <DraftsTray drafts={drafts} onShared={(d, p) => { setDrafts((xs) => xs.filter((x) => x.id !== d.id)); add(p) }}
          onDismissed={(d) => setDrafts((xs) => xs.filter((x) => x.id !== d.id))} />
      )}
      {meetups.length > 0 && <ComingUp meetups={meetups} onOpenClub={onOpenClub} />}
      {main && (
        <nav aria-label="Whose feed" className="-mx-5 flex items-center gap-2 overflow-x-auto px-5 py-0.5 no-scrollbar">
          <div role="radiogroup" aria-label="Show" className="flex items-center gap-1.5">
            {chips.map(([v, label]) => (
              <button key={v} type="button" role="radio" aria-checked={filter === v} onClick={() => setFilter(v)}
                className={cn('inline-flex min-h-11 shrink-0 items-center whitespace-nowrap rounded-full px-4 text-small font-semibold transition-colors',
                  filter === v ? 'bg-(--accent) text-(--on-fill)' : 'bg-(--bg-inset) text-(--text-secondary) active:bg-(--border)')}>{label}</button>
            ))}
          </div>
          {onNewGroup && (
            <button type="button" onClick={onNewGroup}
              className="inline-flex min-h-11 shrink-0 items-center gap-1 whitespace-nowrap rounded-full border border-dashed border-(--border-strong) px-4 text-small font-semibold text-(--accent) active:bg-(--bg-inset)">
              <Plus className="size-5" aria-hidden /> New group
            </button>
          )}
        </nav>
      )}
      {main && openGroup && onOpenGroup && (
        <button type="button" onClick={() => onOpenGroup(openGroup.id)}
          className="flex min-h-14 items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-4 py-3 text-left active:bg-(--bg-inset)">
          <UsersRound className="size-5 shrink-0 text-(--accent)" aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="block text-body font-semibold text-(--text)">{openGroup.emoji} {openGroup.name}</span>
            <span className="block text-meta text-(--text-muted)">{openGroup.count} {openGroup.count === 1 ? 'person' : 'people'}. Only the group sees these posts.</span>
          </span>
          <span className="shrink-0 text-body font-semibold text-(--accent)">Members</span>
        </button>
      )}
      {pinned && (
        <section aria-label="Your workout, just synced" className="flex flex-col gap-3">
          <div className="flex items-start gap-2 px-1">
            <Pin className="mt-0.5 size-5 shrink-0 text-(--accent)" aria-hidden />
            <div className="min-w-0">
              <h2 className="section-title m-0">Your workout just synced</h2>
              <p className="m-0 mt-0.5 text-small text-(--text-muted)">It stays at the top of your feed for an hour.</p>
            </div>
          </div>
          <PostCard post={pinned} imperial={imperial} onChange={setPinned} onDelete={() => setPinned(null)} />
          {pinned.prompt && (
            <Button variant="primary" className="h-12 gap-2 text-body" onClick={() => setCaption(true)}>
              <ImagePlus className="size-5" /> {pinned.prompt}
            </Button>
          )}
        </section>
      )}
      {error && <ErrorState compact message={error} onRetry={() => void load()} />}
      {items == null ? (error ? null : <FeedSkeleton />) : (
        <>
          {main && following > 0 && (filter === 'all' || filter === 'friends') && !items.some((p) => !p.mine && p.kind === 'workout') && (
            <FeedHint onInvite={items.length > 0 ? onInvite : undefined} onShared={() => void load()} />
          )}
          {main && (filter === 'all' || filter === 'friends') && items.some((p) => !p.mine && p.kind === 'workout') && (
            <ShareNudge onShared={() => void load()} />
          )}
          {items.length === 0 && (
            <EmptyRabbit hero size={60} mode={!main ? 'peek' : 'sleep'} className="rounded-2xl border border-(--border) bg-(--bg-surface) px-5 py-6"
              title={group ? 'Nothing in this group yet' : !main || filter !== 'all' ? 'Quiet in here' : following === 0 ? 'Find your people' : 'Nothing shared yet'}
              body={clubId ? 'Share the first news with the club: a meetup recap, a race, a welcome.'
                : group ? "Members' workouts and posts show up here. Share the plan for Saturday, a photo from the run, a cheer. Only the group sees it."
                : filter === 'clubs' ? 'Posts from clubs you join show up here. Find one in Near me.'
                : following === 0 ? "Follow friends to see their runs here and cheer them on. Not on rabbt yet? Invite them by text from Find friends."
                : 'Workouts your friends share show up here as soon as they sync. First races, new PRs, comebacks: share yours too.'}
              action={group ? (
                <Button variant="primary" className="mt-1 h-11 gap-1.5 px-4 text-small" onClick={() => setComposer('blank')}>
                  <SquarePen className="size-5" /> Post to the group
                </Button>
              ) : main && (filter === 'all' || filter === 'friends') && onInvite ? (
                <div className="mt-1 flex flex-wrap justify-center gap-2">
                  <Button variant="primary" className="h-11 gap-1.5 px-4 text-small" onClick={onInvite}>
                    <UserPlus className="size-5" /> Find friends
                  </Button>
                  {onNewGroup && following > 0 && (
                    <Button variant="default" className="h-11 gap-1.5 px-4 text-small" onClick={onNewGroup}>
                      <Plus className="size-5" /> New group
                    </Button>
                  )}
                </div>
              ) : undefined} />
          )}
          <div className="flex flex-col gap-5">
            {items.map((p, i) => (
              <HopIn key={p.id} play={i < 4} index={i}>
                <PostCard post={p} imperial={imperial} onChange={put} onDelete={() => drop(p.id)} onBlocked={() => dropAuthor(p.author)} />
              </HopIn>
            ))}
          </div>
          {next && (
            <Button variant="default" className="h-12 text-body" loading={more} onClick={() => void loadMore()}>Show older posts</Button>
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
    <section aria-labelledby="going-h" className="flex flex-col gap-3">
      <h2 id="going-h" className="section-title m-0 px-1">You're going</h2>
      <div className="-mx-5 flex snap-x gap-3 overflow-x-auto px-5 pb-1 no-scrollbar">
        {meetups.map((m) => (
          <button key={`${m.id}-${m.next}`} type="button" onClick={() => { if (m.club) onOpenClub?.(m.club.id) }}
            className="flex w-[15rem] shrink-0 snap-start flex-col gap-1 rounded-xl border border-(--border) bg-(--bg-surface) p-4 text-left active:bg-(--bg-inset)">
            <span className="text-meta font-semibold text-(--accent)">{m.next ? meetupWhen(m.next) : ''}</span>
            <span className="line-clamp-2 text-body-lg font-semibold leading-snug text-(--text)">{m.title}</span>
            {m.club && <span className="truncate text-meta text-(--text-secondary)"><span aria-hidden>{m.club.emoji} </span>{m.club.name}</span>}
            {m.where && (
              <span className="flex items-center gap-1 text-meta text-(--text-muted)">
                <MapPin className="size-4 shrink-0" aria-hidden /><span className="truncate">{m.where}</span>
              </span>
            )}
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
          <button className="modal-close" aria-label="Close" onClick={close}><X className="size-5" /></button>
        </div>
        <div className="modal-body flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-5 py-4">
          <div className="relative">
            {mention.list}
            <textarea ref={mention.ref} aria-label="Post text" className={cn(areaCls, 'min-h-[96px] text-lead')} autoFocus maxLength={TEXT_LEN} value={text}
              onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { mention.onKeyDown(e) }} onSelect={mention.onSelect}
              placeholder={category === 'race' ? 'How did it go?' : category === 'gratitude' ? 'Who are you thankful for?' : 'What happened?'} />
            {text.length > TEXT_LEN * 0.8 && <p className="mt-0.5 text-right text-caption text-(--text-muted)">{text.length}/{TEXT_LEN}</p>}
          </div>
          <PhotoPicker picker={photos} />
          {!template && !text.trim() && !photos.items.length && !fixed && (
            <div className="flex flex-col gap-2">
              <p className="m-0 text-meta font-semibold text-(--text-secondary)">Need an idea? Tap one to start.</p>
              <div className="no-scrollbar -mx-5 flex gap-2 overflow-x-auto px-5 pb-0.5" aria-label="Ideas">
                {TEMPLATES.map((t) => (
                  <button key={t.label} type="button" onClick={() => { setD((x) => ({ ...x, text: t.text, category: t.category })) }}
                    className="inline-flex min-h-11 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border border-(--border) bg-(--bg-surface) px-4 text-small font-medium text-(--text-secondary) active:bg-(--bg-inset)">
                    <span aria-hidden>{t.emoji}</span>{t.label}
                  </button>
                ))}
              </div>
            </div>
          )}
          <button type="button" aria-expanded={details} onClick={() => setDetails((v) => !v)}
            className="flex min-h-12 items-center gap-2.5 rounded-xl px-1 text-left text-body font-medium text-(--text-secondary) active:bg-(--bg-inset)">
            <SlidersHorizontal className="size-5 text-(--text-muted)" aria-hidden />
            <span className="flex-1">{details ? 'Hide details' : 'Add details'}{!details && detailBits.length > 0 && <span className="block text-meta text-(--text-muted)">{detailBits.join(', ')}</span>}</span>
            <ChevronRight className={cn('size-5 text-(--text-muted) transition-transform', details && 'rotate-90')} aria-hidden />
          </button>
          {details && (
            <div className="flex flex-col gap-4">
              <p className="-mb-2 m-0 text-meta font-semibold text-(--text-secondary)">What is it?</p>
              <div className="no-scrollbar -mx-5 flex gap-2 overflow-x-auto px-5 pb-0.5" role="radiogroup" aria-label="What is it">
                {CATEGORIES.map(([id, label]) => (
                  <button key={id} type="button" role="radio" aria-checked={category === id} onClick={() => setCategory(id)}
                    className={cn('min-h-11 shrink-0 whitespace-nowrap rounded-full border px-4 text-small font-medium',
                      category === id ? 'border-(--accent) bg-(--accent-subtle) text-(--accent)' : 'border-(--border) text-(--text-secondary)')}>{label}</button>
                ))}
              </div>
              <p className="-mb-2 m-0 text-meta font-semibold text-(--text-secondary)">How do you feel?</p>
              <div className="flex flex-wrap items-center gap-1" role="radiogroup" aria-label="Feeling">
                {FEELINGS.map((f) => (
                  <button key={f} type="button" role="radio" aria-checked={feeling === f} aria-label={`Feeling ${f}`}
                    onClick={() => setFeeling(feeling === f ? null : f)}
                    className={cn('flex size-11 items-center justify-center rounded-full text-title-sm', feeling === f ? 'bg-(--accent-subtle) ring-1 ring-(--accent)' : 'opacity-80')}>{f}</button>
                ))}
              </div>
              {events && events.length > 0 && (
                <label className="flex flex-col gap-2 text-meta font-semibold text-(--text-secondary)">Link an event
                  <select className={cn(inputCls, 'text-body')} value={eventId} onChange={(e) => setEventId(e.target.value)}>
                    <option value="">None</option>
                    {events.map((e) => <option key={e.id} value={e.id}>{e.name}, {e.date}</option>)}
                  </select>
                </label>
              )}
            </div>
          )}
          <p className="m-0 text-meta text-(--text-muted)">Never your heart rate, health data or where you trained.</p>
          {draft.restored && (
            <p className="flex flex-wrap items-center gap-x-2 text-caption text-(--text-muted)" role="status">
              <span>Restored your unsaved post. Photos aren't kept in drafts: add them again.</span>
              <button type="button" className="hit-44 underline" onClick={draft.discard}>Discard draft</button>
            </p>
          )}
          {queued && <SaveStatus state="queued" />}
          {err && <p className="text-meta text-(--danger)" role="alert">{err}</p>}
        </div>
        <div className="flex items-center gap-2 border-t border-(--border) bg-(--bg-surface) px-5 pb-[max(12px,env(safe-area-inset-bottom))] pt-3">
          {fixed ? (
            <span className="flex min-w-0 flex-1 items-center gap-1.5 truncate text-meta text-(--text-muted)">
              <UsersRound className="size-5 shrink-0" aria-hidden /> Only {clubName ?? groupName ?? 'members'} see it
            </span>
          ) : (
            <label className="relative flex min-w-0 flex-1 items-center">
              <span className="sr-only">Who can see it</span>
              <AudIcon className="pointer-events-none absolute left-3 size-5 text-(--text-secondary)" aria-hidden />
              <select value={audience} onChange={(e) => setAudience(e.target.value)}
                className="h-12 w-full min-w-0 appearance-none truncate rounded-full border border-(--border) bg-(--bg-surface) pl-10 pr-8 text-body font-medium text-(--text)">
                <option value="friends">Friends</option>
                {groups.map((g) => <option key={g.id} value={`grp:${g.id}`}>{g.emoji} {g.name}</option>)}
                <option value="public">Everyone on rabbt</option>
                {clubs.map((g) => <option key={g.id} value={`club:${g.id}`}>{g.name}</option>)}
                <option value="private">Only me</option>
              </select>
              <ChevronRight className="pointer-events-none absolute right-3 size-4 rotate-90 text-(--text-muted)" aria-hidden />
            </label>
          )}
          <Button variant="primary" className="h-12 shrink-0 gap-2 px-5 text-body" loading={busy} disabled={!canPost}
            onClick={(e) => void post(e.currentTarget)}>
            <Send className="size-5" /> {photos.busy ? 'Uploading…' : 'Post'}
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
        <span className="celebrate text-title-sm" aria-hidden>🎉</span>
        <span className="flex-1 text-body font-medium text-(--text)">rabbt spotted {n} milestone{n === 1 ? '' : 's'} to share</span>
        <span className="text-meta text-(--accent)">{open ? 'Hide' : 'Show'}</span>
      </button>
      {open && (
        <ul className="mt-1 flex flex-col gap-2">
          {drafts.map((d) => (
            <li key={d.id} className="rounded-xl bg-(--bg-surface) p-3">
              <p className="text-body leading-snug text-(--text)">{d.text}</p>
              {d.event && <EventChip e={d.event} />}
              <div className="mt-2 flex gap-2">
                <Button variant="default" className="h-11 flex-1 text-small" disabled={busy != null} onClick={() => void later(d)}>Not now</Button>
                <Button ref={(el) => { btns.current[d.id] = el }} variant="primary" className="h-11 flex-1 text-small"
                  loading={busy === d.id} disabled={busy != null && busy !== d.id} onClick={() => void share(d)}>Share</Button>
              </div>
            </li>
          ))}
          <li className="px-1 text-caption text-(--text-muted)">Goes to your default audience. Nothing is shared unless you tap Share.</li>
        </ul>
      )}
      {err && <p className="mt-1 text-meta text-(--danger)">{err}</p>}
    </section>
  )
}

function EventChip({ e }: { e: { name: string; date: string } }) {
  return (
    <span className="mt-2 inline-flex max-w-full items-center gap-1.5 rounded-full border border-(--border) px-2.5 py-1 text-meta text-(--text-secondary)">
      <CalendarDays className="size-4 shrink-0" />
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
  // Comments stay folded away on the feed until someone taps "Comments"; then the whole thread
  // opens right inside the card (no new page). The post's own page always shows them.
  const [showComments, setShowComments] = useState(() => !!expanded || !!focusComment || readDraft<string>(`comment.${p.id}`) != null)
  const [loadingComments, setLoadingComments] = useState(false)
  const [editingComment, setEditingComment] = useState<PostComment | null>(null)
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
  /** Open the thread inline (loading the whole conversation: the feed only carries a preview) and
   * focus the box; tap again to fold it away. On the post's own page it just focuses the box. */
  async function toggleComments() {
    if (showComments && !expanded) { setShowComments(false); setReplyTo(null); return }
    setShowComments(true)
    window.setTimeout(() => input.current?.focus({ preventScroll: true }), 0)
    const now = latest.current
    if (expanded || now.comments.length >= now.comment_count) return
    setLoadingComments(true)
    try {
      const r = await getPost(p.id)
      const cur = latest.current
      // Keep anything added while loading (an inline comment that landed first).
      const extra = cur.comments.filter((c) => !r.post.comments.some((x) => x.id === c.id))
      onChange({ ...cur, comments: [...r.post.comments, ...extra], comment_count: Math.max(r.post.comment_count, cur.comment_count) })
    } catch (e) { setErr((e as Error).message) } finally { setLoadingComments(false) }
  }
  /** Reply to ``c``; a reply to a reply joins the same thread and starts with "@Name". */
  function startReply(c: PostComment, thread: PostComment) {
    setEditingComment(null)
    setReplyTo(thread); setShowComments(true)
    if (c.id !== thread.id && !c.mine) {
      const first = c.by.name.split(' ')[0]
      mention.add({ id: c.by.id, name: first })
      if (!comment.startsWith(`@${first}`)) setComment(`@${first} ${comment}`)
    }
    window.setTimeout(() => input.current?.focus(), 0)
  }
  function startEdit(c: PostComment) {
    setReplyTo(null); setEditingComment(c); setShowComments(true)
    mention.reset()
    for (const m of c.mentions ?? []) mention.add(m)
    setComment(displayText(c.text))
    window.setTimeout(() => input.current?.focus(), 0)
  }
  function cancelCompose() {
    setReplyTo(null)
    if (editingComment) { setEditingComment(null); setComment(''); commentDraft.clear(); mention.reset() }
  }
  async function toggleLike(c: PostComment) {
    const on = !c.liked
    const patch = (x: PostComment): PostComment => (x.id === c.id ? { ...x, liked: on, like_count: Math.max(0, (x.like_count ?? 0) + (on ? 1 : -1)) } : x)
    onChange({ ...latest.current, comments: latest.current.comments.map(patch) })
    if (on) haptic()
    try {
      const r = await likeComment(p.id, c.id, on)
      const now = latest.current
      onChange({ ...now, comments: now.comments.map((x) => (x.id === c.id ? { ...x, liked: r.comment.liked, like_count: r.comment.like_count } : x)) })
    } catch (e) {
      const now = latest.current
      onChange({ ...now, comments: now.comments.map((x) => (x.id === c.id ? c : x)) })
      setErr((e as Error).message)
    }
  }
  async function send() {
    if (busy) return  // one comment at a time; a second Enter while sending does nothing
    const sent = comment
    const t = mention.encode(sent).trim()
    if (!t) return
    setBusy(true); setErr(null); setCommentQueued(false)
    if (editingComment) {
      try {
        const r = await editComment(p.id, editingComment.id, t)
        const now = latest.current
        onChange({ ...now, comments: now.comments.map((x) => (x.id === r.comment.id ? { ...x, ...r.comment } : x)) })
        if (typed.current === sent) { setComment(''); commentDraft.clear(); mention.reset() }
        setEditingComment(null)
      } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
      return
    }
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
    if (!(await confirmAsk('Delete this comment?', { detail: 'Replies to it go too.', confirm: 'Delete', danger: true }))) return
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
    if (!(await confirmAsk('Report this post?', { detail: 'It disappears for you and the rabbt team takes a look.', confirm: 'Report', danger: true }))) return
    try { const r = await reportPost(p.id); setNotice(r.message); window.setTimeout(onDelete, 1500) }
    catch (e) { setErr((e as Error).message) }
  }
  async function block() {
    setMenu(false)
    if (!(await confirmAsk(`Block ${p.user?.name ?? 'this person'}?`, { detail: "You won't see each other's posts or comments anywhere on rabbt.", confirm: 'Block', danger: true }))) return
    try { await blockUser(p.author); setNotice('Blocked.'); window.setTimeout(() => (onBlocked ?? onDelete)(), 1000) }
    catch (e) { setErr((e as Error).message) }
  }

  const threads = threadsOf(p.comments)
  // Inline on the feed: up to the newest 20 conversations; a longer one continues on the post's page.
  const shownThreads = expanded ? threads : threads.slice(-INLINE_THREADS)
  const more = threads.length - shownThreads.length
  const commentActions = {
    onReply: startReply, onLike: (c: PostComment) => void toggleLike(c),
    onDelete: (c: PostComment) => void removeComment(c.id), onEdit: startEdit,
  }
  const audience = p.audience === 'public' ? <><Globe className="size-4" aria-hidden /><span>Everyone</span></>
    : p.audience === 'private' ? <><Lock className="size-4" aria-hidden /><span>Only you</span></>
    : p.club ? <><Users className="size-4" aria-hidden /><span className="truncate">{p.club.name}</span></>
    : p.groups?.length ? <><UsersRound className="size-4" aria-hidden /><span className="truncate">{p.groups.map((g) => `${g.emoji} ${g.name}`).join(', ')}</span></>
    : <><Users className="size-4" aria-hidden /><span>Friends</span></>

  return (
    <article className="flex flex-col gap-4 rounded-xl border border-(--border) bg-(--bg-surface) p-4">
      <header className="flex items-start gap-3">
        {!p.mine && p.user ? <TapAvatar p={p.user} size={44} /> : <PersonAvatar u={p.user} size={44} />}
        <span className="min-w-0 flex-1">
          <span className="block text-body-lg font-semibold leading-snug text-(--text)">
            {!p.mine && p.user ? <PersonLink id={p.user.id} name={name} /> : name}{p.feeling && <span className="ml-1.5" aria-label={`feeling ${p.feeling}`}>{p.feeling}</span>}
          </span>
          <span className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-meta text-(--text-muted)" title={audienceLabel(p.audience, p.club)}>
            <span>{ago(p.created)}{p.edited ? ', edited' : ''}</span>
            <span className="inline-flex min-w-0 items-center gap-1">{audience}</span>
          </span>
        </span>
        <div className="relative -mr-2 -mt-1 shrink-0">
          <Button variant="ghost" className="size-11 p-0" aria-label="Post options" aria-expanded={menu} onClick={() => setMenu((m) => !m)}>
            <Ellipsis className="size-5" />
          </Button>
          {menu && (
            <div className="absolute right-0 top-12 z-10 flex w-52 flex-col rounded-xl border border-(--border) bg-(--bg-surface) py-1 shadow-lg" role="menu">
              {p.mine ? (
                <>
                  <MenuItem icon={<ImagePlus className="size-5" />} label={p.photos.length ? 'Photos' : 'Add photos'} onClick={() => { setMenu(false); setEditing('photos') }} />
                  <MenuItem icon={<Pencil className="size-5" />} label="Edit post" onClick={() => { setMenu(false); setEditing('edit') }} />
                  <MenuItem icon={<Trash2 className="size-5" />} label="Delete post" danger onClick={() => void remove()} />
                </>
              ) : (
                <>
                  {p.user && <MenuItem icon={<Send className="size-5" />} label={`Message ${p.user.name.split(' ')[0]}`} onClick={() => { setMenu(false); messagePeople([p.user!.id]) }} />}
                  <MenuItem icon={<EyeOff className="size-5" />} label="Hide post" onClick={() => void hide()} />
                  <MenuItem icon={<Flag className="size-5" />} label="Report" onClick={() => void report()} />
                  <MenuItem icon={<Ban className="size-5" />} label={`Block ${p.user?.name ?? ''}`.trim()} danger onClick={() => void block()} />
                </>
              )}
            </div>
          )}
        </div>
      </header>

      {p.kind !== 'workout' && p.category !== 'other' && (
        <span className="-mt-1 self-start rounded-full bg-(--accent-subtle) px-3 py-1 text-meta font-semibold text-(--accent)">{CATEGORY_LABEL[p.category]}</span>
      )}
      {p.text ? (
        <p className="m-0 whitespace-pre-wrap break-words text-body-lg leading-normal text-(--text)"><MentionText text={p.text} mentions={p.mentions} /></p>
      ) : null}
      {photos.length > 0 && <PhotoGrid urls={photos} who={p.mine ? 'your' : `${p.user?.name ?? 'their'}'s`} />}
      {editing && (
        <CaptionSheet post={p} title={editing === 'edit' ? 'Edit post' : p.photos.length ? 'Photos' : 'Add photos'}
          onClose={() => setEditing(null)} onSaved={(np) => { onChange({ ...np, comments: p.comments }); setEditing(null) }} />
      )}
      {p.workout && <WorkoutCard w={p.workout} imperial={imperial} who={p.mine ? null : p.user?.name ?? null}
        onOpen={p.mine && p.workout.activity_id != null ? () => openActivity(p.workout!.activity_id)
          // a friend's Garmin workout: its own page, as they share it (server checks this post is visible)
          : /^\d+$/.test(String(p.workout.activity_id ?? '')) && (p.workout.source ?? 'garmin') === 'garmin'
            ? () => openActivity(p.workout!.activity_id, p.author) : () => setDetails(true)} />}
      {details && p.workout && (
        <FriendWorkoutSheet w={p.workout} who={p.user?.name ?? 'They'} imperial={imperial} onClose={() => setDetails(false)}
          onMessage={p.user ? () => { setDetails(false); messagePeople([p.user!.id]) } : undefined} />
      )}
      {p.event && <EventChip e={p.event} />}
      {notice && <p className="m-0 text-body text-(--accent)" role="status">{notice}</p>}

      <div className="-mx-1 flex items-center gap-0.5 border-t border-(--border) pt-3">
        {REACTIONS.map(([kind, emoji, label]) => {
          const n = p.reactions[kind]
          const on = p.my_reaction === kind
          return (
            <button key={kind} ref={(el) => { reactBtns.current[kind] = el }} type="button" aria-pressed={on}
              aria-label={`${label}${n ? `, ${n}` : ''}`} onClick={() => void toggle(kind)}
              className={cn('inline-flex min-h-11 min-w-11 items-center justify-center gap-1 rounded-full px-2.5 text-body font-semibold transition-colors',
                on ? 'bg-(--accent-subtle) text-(--accent)' : 'text-(--text-secondary) active:bg-(--bg-inset)')}>
              <span className={cn('text-title-sm leading-none', on && 'celebrate')} aria-hidden>{emoji}</span>
              {n > 0 && <span className="tabular-nums">{n}</span>}
            </button>
          )
        })}
      </div>
      {/* Comments stay folded on the feed: one clear row opens (and hides) the thread right here. */}
      <button type="button" onClick={() => void toggleComments()} aria-expanded={expanded ? undefined : showComments}
        aria-controls={`comments-${p.id}`}
        className={cn('-mx-1 -mt-2 flex min-h-11 items-center gap-2 rounded-lg px-2 text-left text-small font-semibold active:bg-(--bg-inset)',
          showComments && !expanded ? 'text-(--accent)' : 'text-(--text-secondary)')}>
        <MessageCircle className="size-5 shrink-0" aria-hidden />
        <span className="min-w-0 flex-1">
          {showComments && !expanded ? 'Hide comments'
            : p.comment_count > 0 ? `${p.comment_count} ${p.comment_count === 1 ? 'comment' : 'comments'}` : 'Write a comment'}
        </span>
        {!expanded && <ChevronDown className={cn('size-5 shrink-0 transition-transform', showComments && 'rotate-180')} aria-hidden />}
      </button>

      {showComments && (
      <div id={`comments-${p.id}`} className={cn('flex flex-col gap-4', !expanded && 'comments-open')}>
      {loadingComments && shownThreads.length === 0 && <RabbitLoader inline className="py-1" label="Loading comments" />}
      {more > 0 && (
        <button type="button" onClick={() => openTarget({ k: 'post', id: p.id })}
          className="self-start rounded-full py-2 text-body font-semibold text-(--accent) active:opacity-70">
          See the {more} earlier {more === 1 ? 'conversation' : 'conversations'}
        </button>
      )}
      {shownThreads.length > 0 && (
        <CommentThreads post={p} threads={shownThreads} focus={focusComment} actions={commentActions} />
      )}

      <div className="flex flex-col gap-2">
        {(replyTo || editingComment) && (
          <span className="flex min-h-9 items-center gap-2 rounded-full bg-(--bg-inset) py-1 pl-3.5 pr-1 text-meta text-(--text-secondary)">
            {editingComment ? <Pencil className="size-4" aria-hidden /> : <Reply className="size-4" aria-hidden />}
            <span className="min-w-0 flex-1 truncate">
              {editingComment ? 'Editing your comment' : <>Replying to <b className="font-semibold text-(--text)">{replyTo!.mine ? 'yourself' : replyTo!.by.name}</b></>}
            </span>
            <button type="button" className="flex size-9 items-center justify-center rounded-full active:bg-(--bg-surface)"
              aria-label={editingComment ? 'Stop editing' : 'Cancel reply'} onClick={cancelCompose}>
              <X className="size-5" aria-hidden />
            </button>
          </span>
        )}
        <div className="relative flex items-center gap-2">
          {mention.list}
          <input ref={input} aria-label={editingComment ? 'Edit comment' : replyTo ? 'Reply' : 'Add a comment'}
            className={cn(inputCls, 'h-12 rounded-full px-4 text-body')} maxLength={COMMENT_LEN}
            placeholder={editingComment ? 'Edit your comment' : replyTo ? 'Write a reply' : 'Add a comment'} enterKeyHint="send"
            value={comment} onChange={(e) => setComment(e.target.value)} onSelect={mention.onSelect}
            onKeyDown={(e) => { if (!mention.onKeyDown(e) && e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); void send() } }} />
          <Button variant="primary" className="h-12 w-12 shrink-0 rounded-full p-0" aria-label={editingComment ? 'Save comment' : 'Send comment'}
            loading={busy} disabled={!comment.trim()} onClick={() => void send()}>
            {editingComment ? <Check className="size-5" /> : <Send className="size-5" />}
          </Button>
        </div>
        {!replyTo && !editingComment && !comment && (
          <span className="px-4 text-caption text-(--text-muted)">Type @ to mention someone</span>
        )}
      </div>
      </div>
      )}
      {commentQueued && <SaveStatus state="queued" />}
      {err && <p className="m-0 text-body text-(--danger)" role="alert">{err}</p>}
    </article>
  )
}

function MenuItem({ icon, label, danger, onClick }: { icon: React.ReactNode; label: string; danger?: boolean; onClick: () => void }) {
  return (
    <button type="button" role="menuitem" onClick={onClick}
      className={cn('flex min-h-12 items-center gap-3 px-4 text-left text-body', danger && 'text-(--danger)')}>
      {icon}<span className="truncate">{label}</span>
    </button>
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
              <span className="absolute inset-0 flex items-center justify-center bg-black/45 text-title-lg font-semibold text-white" aria-hidden>+{n - 4}</span>
            )}
          </button>
        ))}
      </div>
      {open != null && <PhotoViewer urls={urls} start={open} who={who} onClose={() => setOpen(null)} />}
    </>
  )
}

const SOURCE_LABEL: Record<string, string> = {
  garmin: 'Garmin', oura: 'Oura', whoop: 'WHOOP', apple: 'Apple Watch', coros: 'COROS', strava: 'Strava', polar: 'Polar', suunto: 'Suunto', wahoo: 'Wahoo',
}

type CardWorkout = NonNullable<Post['workout']>
const famOf = (w: CardWorkout) => sportFamily(w.family || w.sport, w.family ? null : w.kind)

/** The numbers that fit the sport (lib/sportstats): pace for a run, speed for a ride, per 100
 * for a swim, per 500 m for a row, vertical for a ski day, time (and sets) for the gym. */
function StatGrid({ w, imperial, big }: { w: CardWorkout; imperial: boolean; big?: boolean }) {
  const stats = statsFor(w, imperial)
  if (!stats.length) return null
  return (
    <dl className={cn('grid grid-cols-2 gap-x-3', big ? 'gap-y-3' : 'gap-y-2 min-[400px]:grid-cols-3')}>
      {stats.map((s) => (
        <div key={s.label} className="min-w-0">
          <dt className="text-caption font-semibold text-(--text-muted)">{s.label}</dt>
          <dd className={cn('font-semibold leading-tight tabular-nums text-(--text) [overflow-wrap:anywhere]', big ? 'text-title-sm' : 'text-body-lg')}>{s.value}</dd>
        </div>
      ))}
    </dl>
  )
}

function Legs({ w, imperial }: { w: CardWorkout; imperial: boolean }) {
  if (!w.legs?.length) return null
  return (
    <ul className="flex flex-col gap-2" aria-label="Legs">
      {w.legs.map((lg, i) => {
        const l = legLine({ ...lg, sport: lg.family ?? 'other' }, imperial)
        return (
          <li key={i} className="flex items-center gap-2.5">
            <SportTile family={lg.family} size={32} />
            <span className="min-w-0 flex-1">
              <span className="block text-body font-semibold text-(--text)">{l.label}</span>
              {l.value && <span className="block text-meta text-(--text-secondary)">{l.value}</span>}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

function WorkoutCard({ w, imperial, onOpen, who }: { w: CardWorkout; imperial: boolean; onOpen?: () => void; who?: string | null }) {
  const fam = famOf(w)
  const headline = w.headline || w.highlight
  const via = SOURCE_LABEL[w.source ?? 'garmin'] ?? 'Garmin'
  return (
    <div className="mt-2.5 flex flex-col gap-3 rounded-xl border border-(--border) bg-(--bg-inset) px-3.5 py-3">
      <div className="flex items-center gap-3">
        <SportTile sport={w.sport} family={fam} size={44} />
        <span className="min-w-0 flex-1">
          <span className="block text-lead font-semibold leading-snug text-(--text)">{w.title}</span>
          <span className="block text-caption text-(--text-muted)">
            {w.title.trim().toLowerCase() === FAMILY_NAME[fam].toLowerCase() ? (w.auto ? 'Synced' : 'Shared') : `${FAMILY_NAME[fam]}, ${w.auto ? 'synced' : 'shared'}`} via {via}
          </span>
        </span>
      </div>
      {headline && <p className="m-0 text-small font-medium text-(--accent)">{headline}</p>}
      {w.route && w.route.length > 1 && (
        onOpen ? (
          <button type="button" onClick={onOpen} aria-label={`Open the ${w.title.toLowerCase()} and its map`} className="block w-full rounded-xl text-left active:opacity-90">
            <RouteMini line={w.route} label={who ? `${who}'s route` : 'Your route'} />
          </button>
        ) : <RouteMini line={w.route} label={who ? `${who}'s route` : 'Your route'} />
      )}
      <StatGrid w={w} imperial={imperial} />
      <Legs w={w} imperial={imperial} />
      {splitsOk(fam) && w.splits && w.splits.length >= 2 && <SplitBars splits={w.splits} swim={fam === 'swim'} />}
      {onOpen && (
        <button type="button" onClick={onOpen} className="flex min-h-11 w-full items-center justify-between border-t border-(--border) pt-1 text-small font-medium text-(--accent)">
          See all the details <ChevronRight className="size-5" aria-hidden />
        </button>
      )}
    </div>
  )
}

/** A friend's shared workout, read-only: exactly what they share (sport, distance, time, the
 *  rate that fits the sport, climb, lap shape). Never heart rate, health data or where they went. */
function FriendWorkoutSheet({ w, who, imperial, onClose, onMessage }: {
  w: CardWorkout; who: string; imperial: boolean; onClose: () => void; onMessage?: () => void
}) {
  const fam = famOf(w)
  const laps = splitsOk(fam) ? (w.splits ?? []).filter((x) => x.km > 0 && x.s > 0) : []
  const swim = fam === 'swim'
  return (
    <Sheet title={w.title} onClose={onClose} portal label={`${who}'s workout`}
      bodyClassName="settings flex flex-col gap-4 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
      <div className="flex items-center gap-3">
        <SportTile sport={w.sport} family={fam} size={44} />
        <p className="m-0 text-small text-(--text-secondary)">
          <span className="block font-semibold text-(--text)">{who}, {FAMILY_NAME[fam].toLowerCase()}</span>
          {w.date ? new Date(`${w.date.slice(0, 10)}T12:00:00`).toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' }) : ''}
        </p>
      </div>
      <div className="rounded-xl border border-(--border) bg-(--bg-surface) p-4"><StatGrid w={w} imperial={imperial} big /></div>
      {w.legs?.length ? <div className="rounded-xl border border-(--border) bg-(--bg-surface) p-4"><Legs w={w} imperial={imperial} /></div> : null}
      {laps.length >= 2 && (
        <section aria-label="Laps" className="rounded-xl border border-(--border) bg-(--bg-surface) p-4">
          <h3 className="section-label mb-2">{swim ? 'Laps' : 'Splits'}</h3>
          <table className="w-full text-left text-small tabular-nums">
            <thead><tr className="text-(--text-muted)"><th className="py-1 font-medium">Lap</th><th className="font-medium">Distance</th><th className="font-medium">Time</th><th className="font-medium">{swim ? (imperial ? 'Per 100 yd' : 'Per 100 m') : 'Pace'}</th></tr></thead>
            <tbody>
              {laps.map((x, i) => (
                <tr key={i} className="border-t border-(--border)">
                  <td className="py-1.5">{i + 1}</td>
                  <td>{swim ? famDist(x.km, 'swim', imperial) : fmtDist(x.km, imperial, null, { decimals: 2 })}</td>
                  <td>{`${Math.floor(x.s / 60)}:${String(Math.round(x.s % 60)).padStart(2, '0')}`}</td>
                  <td>{swim ? fmtSwim100(x.s / (x.km * 10), imperial).split(' ')[0] : fmtPaceKm(x.s / x.km, imperial)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      <p className="text-meta text-(--text-muted)">What {who} shares with friends. Heart rate, health data and where they went stay private.</p>
      {onMessage && (
        <Button variant="primary" className="h-11 gap-1.5 text-body" onClick={onMessage}>
          <Send className="size-5" aria-hidden /> Message {who}
        </Button>
      )}
    </Sheet>
  )
}

/** A route-less shape of a run or swim: one bar per lap, taller = faster (pace per distance, so a
 * short last lap still compares). Rides and gym sessions don't get one. No map, no heart rate. */
function SplitBars({ splits, swim }: { splits: { km: number; s: number }[]; swim?: boolean }) {
  const speed = splits.map((x) => (x.km > 0 && x.s > 0 ? x.km / x.s : 0))
  const max = Math.max(...speed), min = Math.min(...speed.filter((v) => v > 0))
  const fastest = speed.indexOf(max)
  return (
    <div role="img" aria-label={`${splits.length} laps, fastest is lap ${fastest + 1}`}>
      <div className="flex h-10 items-end gap-[2px]" aria-hidden>
        {speed.map((v, i) => (
          <span key={i} className={cn('min-w-[3px] flex-1 rounded-t-sm', i === fastest ? 'bg-(--accent)' : 'bg-(--accent)/40')}
            style={{ height: `${max > min ? 30 + 70 * ((v - min) / (max - min)) : 70}%` }} />
        ))}
      </div>
      <p className="mt-1 text-caption text-(--text-muted)">{splits.length} {swim ? 'laps' : 'splits'}, taller bars are faster</p>
    </div>
  )
}

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
        <textarea ref={mention.ref} aria-label="Caption" className={cn(areaCls, 'min-h-[90px] text-lead')} autoFocus maxLength={TEXT_LEN} value={text}
          placeholder="How did it feel?" onChange={(e) => setText(e.target.value)} onSelect={mention.onSelect}
          onKeyDown={(e) => { mention.onKeyDown(e) }} />
      </div>
      <PhotoPicker picker={photos} />
      {err && <p className="text-meta text-(--danger)" role="alert">{err}</p>}
      <Button variant="primary" className="h-11 text-body" loading={busy}
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
            onClick={(e) => { e.stopPropagation(); go(-1) }}><ChevronRight className="size-6 rotate-180" /></button>
          <button type="button" aria-label="Next photo" disabled={i === n - 1} className={cn(navCls, 'right-2')}
            onClick={(e) => { e.stopPropagation(); go(1) }}><ChevronRight className="size-6" /></button>
          <span className="absolute bottom-[max(16px,env(safe-area-inset-bottom))] left-1/2 -translate-x-1/2 rounded-full bg-black/55 px-3 py-1 text-meta font-medium text-white tabular-nums" aria-hidden>
            {i + 1} / {n}
          </span>
        </>
      )}
      <button type="button" aria-label="Close" className="hit-44 absolute right-3 top-[max(12px,env(safe-area-inset-top))] flex size-10 items-center justify-center rounded-full bg-black/60 text-white"
        onClick={onClose}><X className="size-6" /></button>
    </div>
  )
}
