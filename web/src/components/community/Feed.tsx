// Community feed: "Share something" (life-event ideas inside the composer), the milestone drafts tray,
// meetups coming up, and calm post cards (category, text, up to 4 photos, linked event, four
// reactions with a burst, one-level comment threads). Also a club's feed (``clubId``): the
// composer posts to that club. Nothing is ever posted without a tap. Filter chips: All / Friends /
// each feed group / Clubs; a group's own feed (``groupId``) posts to that group only. My fresh
// auto-shared workout is pinned on top for an hour with "Add a photo or caption".
import { useRefreshOnShow } from '@/hooks/useRefreshOnShow'
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Ban, CalendarDays, Ellipsis, EyeOff, Flag, Globe, ImagePlus, Lock, MapPin, MessageCircle, Pencil, Pin, Plus, Reply, Send, SlidersHorizontal, SquarePen, Trash2, UserPlus, Users, UsersRound, X,
} from 'lucide-react'
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
import {
  CATEGORIES, CATEGORY_LABEL, COMMENT_LEN, FEELINGS, MAX_PHOTOS, REACTIONS, TEMPLATES, TEXT_LEN,
  ago, audienceLabel, communityPhotoUrl, deleteComment, deletePost, dismissDraft,
  getClubs, getCommunityFeed, getDrafts, getMyMeetups, getPost, hidePost, meetupWhen, postPhotoUrls, react,
  reportPost, resizeForPost, shareDraft, unreact, updatePost, uploadPostPhoto,
  type Audience, type Category, type ClubSummary, type Draft, type Meetup, type Post, type PostComment,
  type ReactionKind,
} from '@/lib/community'
import { FeedSkeleton } from '@/components/ui/Skeleton'
import { readDraft, useDraft } from '@/lib/drafts'
import { saveDurably } from '@/lib/outbox'
import { counted } from '@/lib/usage'
import { SaveStatus } from '@/components/ui/SaveStatus'
import { useUnsavedGuard } from '@/components/ui/UnsavedGuard'


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
type Pic = { id: string; url: string }

function Composer({ clubId, clubName, groupId, groupName, groups = [], template, onClose, onPosted }: {
  clubId?: string; clubName?: string; groupId?: string; groupName?: string; groups?: FeedGroup[]
  template: Template | null; onClose: () => void; onPosted: (p: Post) => void
}) {
  // Text, category, feeling, linked event and audience are kept as a draft (lib/drafts) until
  // posted or discarded. Photos can't be kept in a draft (they'd have to be picked again).
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
  const [pics, setPics] = useState<Pic[]>([])
  const [picBusy, setPicBusy] = useState(false)
  const [queued, setQueued] = useState(false)
  const guard = useUnsavedGuard(!!text.trim() || pics.length > 0, draft.discard)
  const close = guard.wrap(onClose)
  const fixed = !!clubId || !!groupId
  const [events, setEvents] = useState<RaceEvent[] | null>(null)
  const [clubs, setClubs] = useState<ClubSummary[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const file = useRef<HTMLInputElement>(null)
  const urls = useRef<string[]>([])
  const drag = useSheetDrag(close)

  useEffect(() => {
    listEvents().then((r) => setEvents(r.events), () => setEvents([]))
    if (!clubId) getClubs().then((g) => setClubs(g.clubs), () => { /* friends / everyone / only me still work */ })
  }, [clubId])
  useEffect(() => () => urls.current.forEach((u) => URL.revokeObjectURL(u)), [])

  async function pick(files: FileList | null) {
    if (!files?.length) return
    setPicBusy(true); setErr(null)
    try {
      for (const f of Array.from(files).slice(0, MAX_PHOTOS - pics.length)) {
        const blob = await resizeForPost(f)
        const id = await uploadPostPhoto(blob)
        const url = URL.createObjectURL(blob)
        urls.current.push(url)
        setPics((xs) => [...xs, { id, url }])
      }
    } catch (e) { setErr((e as Error).message) } finally { setPicBusy(false); if (file.current) file.current.value = '' }
  }
  async function post(el: HTMLElement) {
    setBusy(true); setErr(null); setQueued(false)
    try {
      // Durable + idempotent (lib/outbox): offline / 5xx keeps the text here and retries; a
      // retry can never post twice. Photos are already uploaded, so their ids go along.
      const r = await counted(saveDurably<{ post: Post }>({ method: 'POST', path: '/api/community/posts', label: 'post',
        body: { text: text.trim(), category, feeling, audience, photo_ids: pics.map((p) => p.id), event_id: eventId || null } },
      () => setQueued(true)), 'share', { what: 'post' })
      draft.clear()
      burst(el, 'kudos'); onPosted(r.post)
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false); setQueued(false) }
  }
  const canPost = (!!text.trim() || pics.length > 0) && !picBusy
  return (
    <div className="modal-overlay" onClick={close}>
      {guard.dialog}
      <div className="modal" onClick={(e) => e.stopPropagation()} {...drag}>
        <div className="sheet-handle" />
        <div className="modal-header">
          <h2 className="modal-title">{clubName ? `Share with ${clubName}` : groupName ? `Share with ${groupName}` : 'Share something'}</h2>
          <button className="modal-close" aria-label="Close" onClick={close}><X className="size-4" /></button>
        </div>
        <div className="modal-body flex flex-col gap-3 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
          {!template && !text.trim() && !fixed && (
            <div className="flex flex-wrap gap-1.5" aria-label="Ideas">
              {TEMPLATES.map((t) => (
                <button key={t.label} type="button" onClick={() => setD((x) => ({ ...x, text: t.text, category: t.category }))}
                  className="hit-44 inline-flex min-h-9 items-center gap-1 rounded-full border border-(--border) bg-(--bg-surface) px-3 text-[0.7059rem] font-medium text-(--text-secondary) active:bg-(--bg-inset)">
                  <span aria-hidden>{t.emoji}</span>{t.label}
                </button>
              ))}
            </div>
          )}
          <div className="-mx-1 flex flex-wrap gap-1" role="radiogroup" aria-label="What is it">
            {CATEGORIES.map(([id, label]) => (
              <button key={id} type="button" role="radio" aria-checked={category === id} onClick={() => setCategory(id)}
                className="hit-44 inline-flex min-h-9 items-center px-0.5">
                <span className={cn('rounded-full border px-2.5 py-1 text-[0.7059rem] font-medium',
                  category === id ? 'border-(--accent) bg-(--accent-subtle) text-(--accent)' : 'border-(--border) text-(--text-secondary)')}>{label}</span>
              </button>
            ))}
          </div>
          <div>
            <textarea aria-label="Post text" className={cn(areaCls, 'min-h-[110px]')} autoFocus maxLength={TEXT_LEN} value={text} onChange={(e) => setText(e.target.value)}
              placeholder={category === 'race' ? 'How did it go?' : category === 'gratitude' ? 'Who are you thankful for?' : 'What happened?'} />
            <p className="mt-0.5 text-right text-[0.6471rem] text-(--text-muted)">{text.length}/{TEXT_LEN}</p>
          </div>
          {pics.length > 0 && (
            <div className={cn('grid gap-1.5', pics.length > 1 ? 'grid-cols-2' : 'grid-cols-1')}>
              {pics.map((p, i) => (
                <div key={p.id} className="relative">
                  <img src={p.url} alt={`Photo ${i + 1}`} className="aspect-[4/3] w-full rounded-xl object-cover" />
                  <button type="button" aria-label={`Remove photo ${i + 1}`}
                    onClick={() => setPics((xs) => xs.filter((x) => x.id !== p.id))}
                    className="hit-44 absolute right-1.5 top-1.5 flex size-8 items-center justify-center rounded-full bg-black/60 text-white"><X className="size-4" /></button>
                </div>
              ))}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-0.5" role="radiogroup" aria-label="Feeling">
            {FEELINGS.map((f) => (
              <button key={f} type="button" role="radio" aria-checked={feeling === f} aria-label={`Feeling ${f}`}
                onClick={() => setFeeling(feeling === f ? null : f)}
                className={cn('hit-44 flex size-9 items-center justify-center rounded-full text-[1.05rem]', feeling === f ? 'bg-(--accent-subtle) ring-1 ring-(--accent)' : 'opacity-70')}>{f}</button>
            ))}
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {events && events.length > 0 && (
              <label className="flex flex-col gap-1 text-[0.6471rem] text-(--text-muted)">Link an event
                <select className={cn(inputCls, 'text-[0.8235rem]')} value={eventId} onChange={(e) => setEventId(e.target.value)}>
                  <option value="">None</option>
                  {events.map((e) => <option key={e.id} value={e.id}>{e.name} · {e.date}</option>)}
                </select>
              </label>
            )}
            {!fixed && (
              <label className="flex flex-col gap-1 text-[0.6471rem] text-(--text-muted)">Who can see it
                <select className={cn(inputCls, 'text-[0.8235rem]')} value={audience} onChange={(e) => setAudience(e.target.value)}>
                  <option value="friends">Friends (people who follow you)</option>
                  {groups.map((g) => <option key={g.id} value={`grp:${g.id}`}>Group: {g.emoji} {g.name}</option>)}
                  <option value="public">Everyone on Rabbit</option>
                  {clubs.map((g) => <option key={g.id} value={`club:${g.id}`}>Club: {g.name}</option>)}
                  <option value="private">Only me (journal)</option>
                </select>
              </label>
            )}
          </div>
          <p className="text-[0.6471rem] text-(--text-muted)">Never your heart rate, health data or where you trained.</p>
          {draft.restored && (
            <p className="flex flex-wrap items-center gap-x-2 text-[0.6471rem] text-(--text-muted)" role="status">
              <span>Restored your unsaved post. Photos aren't kept in drafts: add them again.</span>
              <button type="button" className="hit-44 underline" onClick={draft.discard}>Discard draft</button>
            </p>
          )}
          {queued && <SaveStatus state="queued" />}
          {err && <p className="text-[0.7059rem] text-(--danger)" role="alert">{err}</p>}
          <div className="flex items-center gap-2">
            <input ref={file} type="file" accept="image/*" multiple className="hidden" onChange={(e) => void pick(e.target.files)} />
            <Button variant="ghost" className="h-11 gap-1.5 px-3 text-[0.7647rem]" loading={picBusy} disabled={pics.length >= MAX_PHOTOS}
              onClick={() => file.current?.click()}>
              <ImagePlus className="size-4" /> {pics.length ? `${pics.length}/${MAX_PHOTOS}` : 'Photos'}
            </Button>
            <span className="flex-1" />
            <Button variant="primary" className="h-11 gap-1.5 px-5 text-[0.7647rem]" loading={busy} disabled={!canPost}
              onClick={(e) => void post(e.currentTarget)}>
              <Send className="size-4" /> Share
            </Button>
          </div>
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
        <span className="celebrate text-[1.1rem]" aria-hidden>🎉</span>
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
export function PostCard({ post: p, imperial, onChange, onDelete, onBlocked }: {
  post: Post; imperial: boolean; onChange: (p: Post) => void; onDelete: () => void; onBlocked?: () => void
}) {
  const [menu, setMenu] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(p.text)
  // An unsent comment is kept per post (lib/drafts); a card with one opens its comments.
  const [comment, setComment, commentDraft] = useDraft<string>(`comment.${p.id}`, '', { label: 'comment', isEmpty: (v) => !v.trim() })
  const [showComments, setShowComments] = useState(() => readDraft<string>(`comment.${p.id}`) != null)
  const [commentQueued, setCommentQueued] = useState(false)
  const [replyTo, setReplyTo] = useState<PostComment | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const reactBtns = useRef<Partial<Record<ReactionKind, HTMLButtonElement | null>>>({})
  const input = useRef<HTMLInputElement>(null)
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
    try { const r = was === kind ? await unreact(p.id) : await react(p.id, kind); onChange({ ...r.post, comments: p.comments }) }
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
    const t = comment.trim()
    if (!t) return
    setBusy(true); setErr(null); setCommentQueued(false)
    try {
      // Durable + idempotent: kept and retried when offline, never posted twice.
      const r = await saveDurably<{ comment: PostComment }>({ method: 'POST', label: 'comment',
        path: `/api/community/posts/${encodeURIComponent(p.id)}/comments`, body: { text: t, reply_to: replyTo?.id ?? null } },
      () => setCommentQueued(true))
      onChange({ ...p, comments: [...p.comments, r.comment], comment_count: p.comment_count + 1 })
      setComment(''); commentDraft.clear(); setReplyTo(null)
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false); setCommentQueued(false) }
  }
  async function removeComment(cid: string) {
    try {
      await deleteComment(p.id, cid)
      const gone = p.comments.filter((c) => c.id === cid || c.parent === cid).length
      onChange({ ...p, comments: p.comments.filter((c) => c.id !== cid && c.parent !== cid), comment_count: Math.max(0, p.comment_count - gone) })
    } catch (e) { setErr((e as Error).message) }
  }
  async function saveEdit() {
    setBusy(true); setErr(null)
    try { const r = await updatePost(p.id, { text: draft.trim() }); onChange({ ...r.post, comments: p.comments }); setEditing(false) }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  async function remove() {
    setMenu(false)
    if (!window.confirm('Delete this post?')) return
    try { await deletePost(p.id); onDelete() } catch (e) { setErr((e as Error).message) }
  }
  async function hide() {
    setMenu(false)
    try { const r = await hidePost(p.id); setNotice(r.message); window.setTimeout(onDelete, 1200) }
    catch (e) { setErr((e as Error).message) }
  }
  async function report() {
    setMenu(false)
    if (!window.confirm('Report this post? It disappears for you and the Rabbit team takes a look.')) return
    try { const r = await reportPost(p.id); setNotice(r.message); window.setTimeout(onDelete, 1500) }
    catch (e) { setErr((e as Error).message) }
  }
  async function block() {
    setMenu(false)
    if (!window.confirm(`Block ${p.user?.name ?? 'this person'}? You won't see each other's posts or comments anywhere on Rabbit.`)) return
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
        <PersonAvatar u={p.user} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[0.8235rem] font-medium text-(--text)">
            {name}{p.feeling && <span className="ml-1" aria-label={`feeling ${p.feeling}`}>{p.feeling}</span>}
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
                  <MenuItem icon={<Pencil className="size-4" />} label="Edit" onClick={() => { setMenu(false); setDraft(p.text); setEditing(true) }} />
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

      {editing ? (
        <div className="mt-2.5 flex flex-col gap-2">
          <textarea aria-label="Edit post" className={cn(areaCls, 'min-h-[80px]')} maxLength={TEXT_LEN} value={draft} onChange={(e) => setDraft(e.target.value)} autoFocus />
          <div className="flex justify-end gap-2">
            <Button variant="default" className="h-11 px-3 text-[0.7647rem]" onClick={() => setEditing(false)}>Cancel</Button>
            <Button variant="primary" className="h-11 px-3 text-[0.7647rem]" loading={busy}
              disabled={!draft.trim() && !p.photos.length && !p.workout && !p.milestone} onClick={() => void saveEdit()}>Save</Button>
          </div>
        </div>
      ) : p.text ? (
        <p className="mt-2.5 whitespace-pre-wrap break-words text-[0.9412rem] leading-snug text-(--text)">{p.text}</p>
      ) : null}
      {photos.length > 0 && <PhotoGrid urls={photos} />}
      {p.workout && <WorkoutCard w={p.workout} imperial={imperial} />}
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
              <span className={cn('text-[0.95rem]', on && 'celebrate')} aria-hidden>{emoji}</span>
              {n > 0 && <span className="tabular-nums">{n}</span>}
            </button>
          )
        })}
        <span className="flex-1" />
        <button type="button" onClick={() => void openComments()} aria-expanded={showComments}
          className="hit-44 inline-flex h-8 items-center gap-1.5 rounded-full px-2.5 text-[0.7059rem] font-medium text-(--text-secondary) active:bg-(--bg-inset)">
          <MessageCircle className="size-4" /> {p.comment_count > 0 ? p.comment_count : 'Comment'}
        </button>
      </div>

      {(showComments || (p.comments.length > 0 && p.comment_count <= 2)) && p.comments.length > 0 && (
        <ul className="mt-1.5 flex flex-col gap-1.5 border-t border-(--border) pt-2">
          {tops.map((c) => (
            <li key={c.id} className="flex flex-col gap-1">
              <CommentLine c={c} onReply={() => startReply(c)} onDelete={() => void removeComment(c.id)} />
              {replies(c.id).length > 0 && (
                <ul className="ml-4 flex flex-col gap-1 border-l border-(--border) pl-2.5">
                  {replies(c.id).map((r) => (
                    <li key={r.id}><CommentLine c={r} onReply={() => startReply(c)} onDelete={() => void removeComment(r.id)} /></li>
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
          <div className="flex items-center gap-2">
            <input ref={input} aria-label={replyTo ? 'Reply' : 'Comment'} className={cn(inputCls, 'h-11 text-[0.8235rem]')} maxLength={COMMENT_LEN}
              placeholder={replyTo ? 'Write a reply…' : 'Say something kind…'}
              value={comment} onChange={(e) => setComment(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void send() }} />
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
        <span className="font-medium text-(--text)">{c.mine ? 'You' : c.by.name}</span>{' '}
        <span className="text-(--text-secondary)">{c.text}</span>{' '}
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

function PhotoGrid({ urls }: { urls: string[] }) {
  const [open, setOpen] = useState<number | null>(null)
  return (
    <>
      <div className={cn('mt-2.5 grid gap-1', urls.length > 1 ? 'grid-cols-2' : 'grid-cols-1')}>
        {urls.map((u, i) => (
          <button key={u} type="button" aria-label={`Open photo ${i + 1}`} onClick={() => setOpen(i)}
            className={cn('overflow-hidden rounded-xl bg-(--bg-inset)', urls.length === 3 && i === 0 && 'col-span-2')}>
            <img src={u} alt="" loading="lazy" className={cn('w-full object-cover', urls.length === 1 ? 'max-h-[28rem]' : 'aspect-square')} />
          </button>
        ))}
      </div>
      {open != null && <PhotoViewer url={urls[open]!} label={`Photo ${open + 1} of ${urls.length}`} onClose={() => setOpen(null)} />}
    </>
  )
}

const SPORT_EMOJI: Record<string, string> = { run: '🏃', bike: '🚴', swim: '🏊', hike: '🥾', walk: '🚶', strength: '🏋️', ski: '⛷️', brick: '🔁', climb: '🧗', paddle: '🛶' }

const SOURCE_LABEL: Record<string, string> = {
  garmin: 'Garmin', oura: 'Oura', whoop: 'WHOOP', apple: 'Apple Watch', coros: 'COROS', strava: 'Strava', polar: 'Polar', suunto: 'Suunto', wahoo: 'Wahoo',
}

function WorkoutCard({ w, imperial }: { w: NonNullable<Post['workout']>; imperial: boolean }) {
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
        <span aria-hidden className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-(--bg-surface) text-[1.25rem]">{SPORT_EMOJI[w.sport] ?? '🐇'}</span>
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
    </div>
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

/** "Add a photo or caption" for my fresh auto-shared workout. */
function CaptionSheet({ post, onClose, onSaved }: { post: Post; onClose: () => void; onSaved: (p: Post) => void }) {
  const [text, setText] = useState(post.text)
  const [pics, setPics] = useState<Pic[]>([])
  const [busy, setBusy] = useState(false)
  const [picBusy, setPicBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const file = useRef<HTMLInputElement>(null)
  const urls = useRef<string[]>([])
  useEffect(() => () => urls.current.forEach((u) => URL.revokeObjectURL(u)), [])
  async function pick(files: FileList | null) {
    if (!files?.length) return
    setPicBusy(true); setErr(null)
    try {
      for (const f of Array.from(files).slice(0, MAX_PHOTOS - pics.length)) {
        const blob = await resizeForPost(f)
        const id = await uploadPostPhoto(blob)
        const url = URL.createObjectURL(blob)
        urls.current.push(url)
        setPics((xs) => [...xs, { id, url }])
      }
    } catch (e) { setErr((e as Error).message) } finally { setPicBusy(false); if (file.current) file.current.value = '' }
  }
  async function save(el: HTMLElement) {
    setBusy(true); setErr(null)
    try {
      const r = await updatePost(post.id, { text: text.trim(), ...(pics.length ? { photo_ids: pics.map((p) => p.id) } : {}) })
      burst(el, 'kudos'); onSaved({ ...r.post, comments: post.comments })
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <Sheet title="Add a photo or caption" onClose={onClose}
      bodyClassName="flex flex-col gap-3 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
      <textarea aria-label="Caption" className={cn(areaCls, 'min-h-[90px]')} autoFocus maxLength={TEXT_LEN} value={text}
        placeholder="How did it feel?" onChange={(e) => setText(e.target.value)} />
      {pics.length > 0 && (
        <div className="grid grid-cols-2 gap-1.5">
          {pics.map((p, i) => <img key={p.id} src={p.url} alt={`Photo ${i + 1}`} className="aspect-[4/3] w-full rounded-xl object-cover" />)}
        </div>
      )}
      {err && <p className="text-[0.7059rem] text-(--danger)" role="alert">{err}</p>}
      <div className="flex items-center gap-2">
        <input ref={file} type="file" accept="image/*" multiple className="hidden" onChange={(e) => void pick(e.target.files)} />
        <Button variant="ghost" className="h-11 gap-1.5 px-3 text-[0.7647rem]" loading={picBusy} disabled={pics.length >= MAX_PHOTOS}
          onClick={() => file.current?.click()}>
          <ImagePlus className="size-4" /> {pics.length ? `${pics.length}/${MAX_PHOTOS}` : 'Photo'}
        </Button>
        <span className="flex-1" />
        <Button variant="primary" className="h-11 px-5 text-[0.7647rem]" loading={busy} disabled={picBusy || (!text.trim() && !pics.length)}
          onClick={(e) => void save(e.currentTarget)}>Save</Button>
      </div>
    </Sheet>
  )
}

/** Full-screen photo: a keyboard dialog (focus in, Escape closes, focus returns). */
function PhotoViewer({ url, label, onClose }: { url: string; label: string; onClose: () => void }) {
  const box = useRef<HTMLDivElement>(null)
  useDialog(box, onClose)
  return (
    <div ref={box} className="modal-overlay flex items-center justify-center bg-black/85" onClick={onClose} role="dialog" aria-modal="true" aria-label={label}>
      <img src={url} alt="" className="max-h-[90vh] max-w-full object-contain" />
      <button type="button" aria-label="Close" className="hit-44 absolute right-3 top-[max(12px,env(safe-area-inset-top))] flex size-10 items-center justify-center rounded-full bg-black/60 text-white"
        onClick={onClose}><X className="size-5" /></button>
    </div>
  )
}
