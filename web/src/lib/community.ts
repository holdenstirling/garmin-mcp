// Community: a calm feed of life events and accomplishments, clubs (meetups, challenges)
// and people (community.py, clubs.py, routes in community_web.py).
import { AuthError, getJSON, postJSON, sendJSON } from '@/lib/api'
import type { Metric } from '@/lib/challenges'
import type { SocialUser } from '@/lib/social'
import { counted } from '@/lib/usage'
import { milestone } from '@/lib/traction'

export type Category = 'race' | 'pb' | 'milestone' | 'life' | 'comeback' | 'gratitude' | 'other'
export type ReactionKind = 'party' | 'strong' | 'heart' | 'rabbit'
export type MilestoneType = 'race' | 'pb' | 'streak' | 'level' | 'badge' | 'challenge' | 'first'
/** "friends" | "public" | "private" | "club:<id>" | "grp:<gid>[,<gid>]" (feed groups) */
export type Audience = string

export const CATEGORIES: [Category, string][] = [
  ['race', 'Race'], ['pb', 'Personal best'], ['milestone', 'Milestone'], ['life', 'Life event'],
  ['comeback', 'Comeback'], ['gratitude', 'Gratitude'], ['other', 'Other'],
]
export const CATEGORY_LABEL = Object.fromEntries(CATEGORIES) as Record<Category, string>
export const FEELINGS = ['😀', '🥳', '💪', '😅', '🥹', '🙏', '😤', '😴', '❤️', '🔥'] as const
export const REACTIONS: [ReactionKind, string, string][] = [
  ['party', '🎉', 'Celebrate'], ['strong', '💪', 'Strong'], ['heart', '❤️', 'Love'], ['rabbit', '🐇', 'Hop on'],
]
/** Quick starts for the composer: a category and a first line to edit. */
export const TEMPLATES: { emoji: string; label: string; category: Category; text: string }[] = [
  { emoji: '🏅', label: 'First marathon', category: 'race', text: 'I ran my first marathon! ' },
  { emoji: '⏱️', label: 'New PR', category: 'pb', text: 'New personal record: ' },
  { emoji: '✅', label: 'Finished my plan', category: 'milestone', text: 'Finished my training plan, every week of it. ' },
  { emoji: '🚲', label: 'New bike', category: 'life', text: 'Meet my new bike: ' },
  { emoji: '💚', label: 'Comeback', category: 'comeback', text: 'Back running after my injury. ' },
  { emoji: '🎂', label: 'Birthday run', category: 'life', text: 'Birthday run! ' },
  { emoji: '👶', label: 'New baby', category: 'life', text: 'Our family just got bigger! ' },
  { emoji: '💼', label: 'New job', category: 'life', text: 'Big news: I started a new job. ' },
  { emoji: '📦', label: 'Moved', category: 'life', text: 'New city, new running routes. ' },
  { emoji: '🙏', label: 'Thank you', category: 'gratitude', text: 'Thank you to ' },
]
export const MILESTONE_LABEL: Record<MilestoneType, string> = {
  race: 'Race finished', pb: 'Personal bests', streak: 'Streak milestones', level: 'Level ups',
  badge: 'Badges earned', challenge: 'Challenges completed', first: 'Firsts (first ultra, 70.3…)',
}
export const TEXT_LEN = 500
export const COMMENT_LEN = 280
export const MAX_PHOTOS = 10

export function audienceLabel(a: Audience, club?: { name: string } | null): string {
  if (a === 'public') return 'Everyone on rabbt'
  if (a === 'private') return 'Only me'
  if (a.startsWith('club:')) return club?.name ?? 'Club'
  if (a.startsWith('grp:')) return 'Group'
  return 'Friends'
}

export type PostEvent = { id: string; name: string; date: string; type?: string | null; distance?: string | null }
export type PostWorkout = {
  activity_id: number | string; sport: string; title: string; date: string
  /** where it came from: garmin (default), oura, whoop, apple, coros, strava… */
  source?: string
  km: number | null; minutes: number | null; climb_m: number | null; highlight: string
  /** which numbers fit (lib/sportstats): run, walk, hike, ride, indoor_ride, swim, row, paddle, ski,
   *  strength, mind, hiit, climb, brick, other; ``kind`` is Garmin's type (indoor_cycling, yoga) */
  family?: string; kind?: string
  /** an outdoor GPS workout's route: [lat, lon] points, both ends already trimmed (routes.py).
   *  Only when the viewer may see it (mine with my maps on; a friend's only once they share maps). */
  route?: [number, number][]
  /** mine only: there is a map but I turned "Show my route maps" off */
  route_hidden?: boolean
  /** a friend's workout that has a map they keep private ("Share my maps with friends" off) */
  map_private?: boolean
  /** the one rate that fits the family: s/km (runs, walks, hikes), km/h (rides), s/100 m (swims),
   *  s/500 m (rows, paddles) */
  pace_s_km?: number; speed_kmh?: number; pace_s_100m?: number; pace_s_500m?: number
  /** a ski day's vertical (m), a gym session's sets and reps */
  vertical_m?: number; sets?: number; reps?: number
  /** a multisport's legs, each with its own rate */
  legs?: { family?: string; km?: number | null; minutes?: number | null; pace_s_km?: number; speed_kmh?: number; pace_s_100m?: number; pace_s_500m?: number }[]
  /** lap shape: distance + time per lap (no HR, no GPS) */
  splits?: { km: number; s: number }[]
  /** the workout reward's headline */
  headline?: string
  /** auto-shared after sync */
  auto?: boolean
}
export type PostComment = {
  id: string; by: { id: string; name: string; photo?: number | null; picture?: string; handle?: string }; text: string; ts: number; parent: string | null; mine: boolean; can_delete: boolean
  /** only the author can edit; ``edited`` is when they last did */
  can_edit?: boolean; edited?: number | null
  /** likes, without anyone blocked either way */
  like_count?: number; liked?: boolean
  /** the feed preview: how many replies this comment has (they show on the post's page) */
  reply_count?: number
  /** people @mentioned (links in the text, current names) */
  mentions?: { id: string; name: string }[]
}
export type Post = {
  id: string; author: string; user: SocialUser | null; kind: 'moment' | 'milestone' | 'workout'
  category: Category; text: string; feeling: string | null; event: PostEvent | null; workout?: PostWorkout | null
  milestone?: { type: MilestoneType; key: string } | null; created: number; edited: number | null
  audience: Audience; club: { id: string; name: string } | null; mine: boolean; photos: number[]
  /** Mine only: the photo ids, so an edit can keep some and add more. */
  photo_ids?: string[]
  groups?: { id: string; name: string; emoji: string }[]
  /** the pinned post on my own feed: "Add a photo or caption" while it has neither */
  prompt?: string | null; pinned_until?: number
  reactions: Record<ReactionKind, number>; reaction_total: number; my_reaction: ReactionKind | null
  comment_count: number; comments: PostComment[]
  /** people @mentioned in the text */
  mentions?: { id: string; name: string }[]
}
export type Draft = {
  id: string; type: MilestoneType; key: string; text: string; category: Category; event: PostEvent | null
  created: number; day: string
}
export type CommunitySettings = {
  milestones: Record<MilestoneType, boolean>; auto_share: Record<MilestoneType, boolean>
  audience: 'friends' | 'public' | 'private'
  /** "Share my workouts with friends": null = not answered (on once the one-time prompt was shown) */
  share_workouts?: boolean | null
  share_prompted?: boolean
  share_since?: string | null
  /** where auto-shared workouts go: "friends" or "grp:<gid>[,...]" */
  share_audience?: string
  default_view?: 'feed' | 'clubs'
  /** when my newest workout post went out (unix seconds), or null */
  last_shared_at?: number | null
  /** Do friends see my workouts (Feed and friends' lists), community.py `sharing_consent`:
   *  a yes here, or "share my workouts" saved earlier in friends settings when this was never answered */
  sharing_effective?: boolean
  /** why: yes (said yes here), earlier (friends settings, before this setting), off (said no), unanswered */
  sharing_source?: 'yes' | 'earlier' | 'off' | 'unanswered'
  /** who'd see my shared workouts (count, up to 2 first names), for the share ask */
  followers?: { count: number; names: string[] }
  /** route maps: show my own (default on); share with friends (null = not answered = off) */
  routes_own?: boolean
  routes_share?: boolean | null
  /** metres cut off the start and finish of every map: 200, 400 or 800 */
  routes_trim_m?: 200 | 400 | 800
  /** routes that start inside this area never show to others; set from one of my maps */
  routes_home?: { radius_m: number } | null
}
/** Effective "Share my workouts with friends" (community.py `sharing_consent`): only after a yes. */
export const sharingWorkouts = (s: CommunitySettings) => s.sharing_effective ?? s.share_workouts === true
export const TRIM_CHOICES = [200, 400, 800] as const
export const HOME_RADIUS_CHOICES = [200, 400, 800, 1600] as const
export type Usage = { photos: number; bytes: number; max_photos: number; max_bytes: number }
export type Sport = 'running' | 'trail' | 'cycling' | 'triathlon' | 'swimming' | 'walking' | 'multisport' | 'other'
export const SPORTS: [Sport, string][] = [
  ['running', 'Running'], ['trail', 'Trail'], ['cycling', 'Cycling'], ['triathlon', 'Triathlon'],
  ['swimming', 'Swimming'], ['walking', 'Walking'], ['multisport', 'Multisport'], ['other', 'Other'],
]
export type Level = 'all' | 'easy' | 'moderate' | 'fast'
export const LEVELS: [Level, string][] = [['all', 'All paces'], ['easy', 'Easy'], ['moderate', 'Moderate'], ['fast', 'Fast']]
export type ClubSummary = {
  id: string; kind: 'club' | 'race'; name: string; sport: Sport; city: string; state: string; description: string
  emoji: string; privacy: 'open' | 'approval'; visibility?: 'public' | 'private'; role: 'owner' | 'admin' | 'member' | null; members: number
  requested: boolean; code?: string | null; requests?: number; event_id?: string; date?: string
  invited_by?: SocialUser | null; near?: 'city' | 'state' | null
}
export type Meetup = {
  id: string; title: string; start: string; repeat: 'none' | 'weekly'; where: string; pace: string; level: Level
  notes: string; by: string; next: string | null; going: (SocialUser | null)[]; maybe: number
  my_rsvp: 'going' | 'maybe' | 'waitlist' | null; mine: boolean; club?: { id: string; name: string; emoji: string; member?: boolean }
  groups?: PaceGroup[]; walk?: boolean; beginner?: boolean; women?: boolean
  capacity?: number | null; count?: number; guests?: number; spots_left?: number | null; waitlist?: number; wait_pos?: number | null
  see?: RunSee; waiver?: string; paid?: string; lat?: number | null; lng?: number | null; skips?: string[]
  waiver_signed?: boolean; checked_in?: boolean; token?: string | null
}
export type PaceGroup = { label: string; pace: string }
export type RunSee = 'public' | 'club' | 'private'
export const RUN_SEE: [RunSee, string][] = [['public', 'Anyone'], ['club', 'Club members'], ['private', 'Only people I invite']]
export type RosterRow = {
  id: string; kind: 'user' | 'guest'; status: 'going' | 'maybe' | 'waitlist'; name?: string; email?: string
  checked_in: boolean; waiver: boolean; waiver_at?: number | null; user?: SocialUser | null
}
export type Roster = { date: string | null; next: string | null; rows: RosterRow[]; going: number; checked_in: number; waitlist: number }
export type ClubDashboard = {
  members: number; requests: number; link: string | null
  runs: { id: string; title: string; next: string; count: number; capacity: number | null; waitlist: number; see: RunSee }[]
  attendance: { date: string; going: number; checkins: number }[]
}
export type ClubChallenge = {
  id: string; name: string; period: 'week' | 'month'; period_end: string; metric: Metric; sport: string | null
  target: number; participants: number; joined: boolean; xp: number
  leaders: { user_id: string; name: string; pct: number | null; me: boolean }[]
}
export type ClubDetail = ClubSummary & {
  people: { user_id: string; role: 'owner' | 'admin' | 'member'; user: SocialUser | null }[]
  pending: (SocialUser | null)[]
  invited?: (SocialUser | null)[]
  meetups?: Meetup[]
  challenges: ClubChallenge[]
  can_challenge?: boolean
  upcoming: { name: string; date: string; type?: string | null; distance?: string | null; event_id: string | null; people: (SocialUser | null)[] }[]
}
export type LocalGroup = { id: string; name: string; category: string; organizer: string; when: string; where: string; url: string }
export type ClubsView = {
  clubs: ClubSummary[]; invites: ClubSummary[]; discover: ClubSummary[]; max: number
  home: { city: string; state: string }; local: LocalGroup[]
}
export type PostInput = {
  text?: string; category?: Category; feeling?: string | null; photo_ids?: string[]
  event_id?: string | null; audience?: Audience
}
export type ClubInput = {
  name?: string; sport?: Sport; city?: string; state?: string; description?: string; emoji?: string; privacy?: 'open' | 'approval'; visibility?: 'public' | 'private'
}
export type MeetupInput = {
  title: string; start: string; repeat: 'none' | 'weekly'; where: string; pace?: string; level?: Level; notes?: string
  groups?: PaceGroup[]; walk?: boolean; beginner?: boolean; women?: boolean; capacity?: number | null; see?: RunSee
  waiver?: string; paid?: string; lat?: number | null; lng?: number | null
}

const P = '/api/community'
const pp = (id: string) => `${P}/posts/${encodeURIComponent(id)}`
const cp = (id: string) => `${P}/clubs/${encodeURIComponent(id)}`

export const getCommunityFeed = (cursor?: string | null, club?: string, scope: 'all' | 'friends' | 'clubs' = 'all', group?: string) => {
  const q = new URLSearchParams()
  if (cursor) q.set('cursor', cursor)
  if (club) q.set('club', club)
  if (group) q.set('group', group)
  if (scope !== 'all') q.set('scope', scope)
  const s = q.toString()
  return getJSON<{ items: Post[]; next: string | null; drafts: number | null; following: number; pinned?: Post | null; extras?: FeedExtras | null }>(`${P}/feed${s ? `?${s}` : ''}`)
}
export const getPost = (id: string) => getJSON<{ post: Post }>(pp(id))
export const createPost = (b: PostInput) => counted(postJSON<{ post: Post }>(`${P}/posts`, b), 'share', { what: 'post' })
export const shareWorkout = (activityId: number, b: PostInput = {}) =>
  counted(postJSON<{ post: Post }>(`${P}/posts`, { ...b, workout_id: activityId }), 'share', { what: 'workout' })
export const updatePost = (id: string, b: PostInput) => sendJSON<{ post: Post }>('PATCH', pp(id), b)
export const deletePost = (id: string) => sendJSON<{ ok: boolean }>('DELETE', pp(id))
export const react = (id: string, kind: ReactionKind) => postJSON<{ post: Post }>(`${pp(id)}/reactions`, { kind })
export const unreact = (id: string) => sendJSON<{ post: Post }>('DELETE', `${pp(id)}/reactions`)
export const addComment = (id: string, text: string, replyTo?: string | null) =>
  postJSON<{ comment: PostComment }>(`${pp(id)}/comments`, { text, reply_to: replyTo ?? null })
export const deleteComment = (id: string, cid: string) =>
  sendJSON<{ ok: boolean }>('DELETE', `${pp(id)}/comments/${encodeURIComponent(cid)}`)
export const editComment = (id: string, cid: string, text: string) =>
  sendJSON<{ comment: PostComment }>('PATCH', `${pp(id)}/comments/${encodeURIComponent(cid)}`, { text })
/** Like (``on``) or unlike a comment; idempotent. */
export const likeComment = (id: string, cid: string, on: boolean) =>
  sendJSON<{ comment: PostComment }>(on ? 'POST' : 'DELETE', `${pp(id)}/comments/${encodeURIComponent(cid)}/like`)
export const commentLikers = (id: string, cid: string) =>
  getJSON<{ people: SocialUser[] }>(`${pp(id)}/comments/${encodeURIComponent(cid)}/likes`)
export const hidePost = (id: string) => postJSON<{ ok: boolean; message: string }>(`${pp(id)}/hide`)
export const reportPost = (id: string, reason?: string) => postJSON<{ ok: boolean; message: string }>(`${pp(id)}/report`, { reason })
export const postPhotoUrls = (p: Post) => p.photos.map((v, i) => `/app${pp(p.id)}/photos/${i}?v=${v}`)

export const getDrafts = () => getJSON<{ drafts: Draft[] }>(`${P}/drafts`)
export const shareDraft = (id: string, b: PostInput = {}) =>
  counted(postJSON<{ post: Post; message: string }>(`${P}/drafts/${encodeURIComponent(id)}/share`, b), 'share', { what: 'post' })
export const dismissDraft = (id: string) => sendJSON<{ ok: boolean }>('DELETE', `${P}/drafts/${encodeURIComponent(id)}`)
/** Is this workout of mine already on the feed? (auto-shared or shared by hand) */
export const getWorkoutPost = (id: number | string) =>
  getJSON<{ post_id: string | null }>(`${P}/workouts/${encodeURIComponent(String(id))}/post`)
export const getCommunitySettings = () => getJSON<{ settings: CommunitySettings; usage: Usage }>(`${P}/settings`)
export const putCommunitySettings = (patch: Partial<CommunitySettings>) =>
  sendJSON<{ settings: CommunitySettings; usage: Usage }>('PUT', `${P}/settings`, patch)

export const getSuggested = () => getJSON<{ people: { user: SocialUser | null; reason: string }[] }>(`${P}/people/suggested`)
/** Avatars of people met through Community (followers, following, a shared club, public posters). */
export function communityPhotoUrl(u: SocialUser): string | null {
  return u.photo ? `/app${P}/people/${encodeURIComponent(u.id)}/photo?v=${u.photo}` : null
}

export const getMyMeetups = () => getJSON<{ meetups: Meetup[] }>(`${P}/meetups`)
export const getClubs = (q?: string) => getJSON<ClubsView>(`${P}/clubs${q ? `?q=${encodeURIComponent(q)}` : ''}`)
export const createClub = (b: ClubInput) => postJSON<{ club: ClubSummary }>(`${P}/clubs`, b)
export const getClub = (id: string) => getJSON<{ club: ClubDetail }>(cp(id))
export const updateClub = (id: string, b: ClubInput) => sendJSON<{ club: ClubSummary }>('PATCH', cp(id), b)
export const deleteClub = (id: string) => sendJSON<{ ok: boolean }>('DELETE', cp(id))
export const joinClub = (id: string) => postJSON<{ club: ClubSummary; message: string }>(`${cp(id)}/join`)
export const cancelJoinRequest = (id: string) => sendJSON<{ ok: boolean }>('DELETE', `${cp(id)}/join`)
export const joinClubByCode = (code: string) => postJSON<{ club: ClubSummary }>(`${P}/clubs/join`, { code })
export const leaveClub = (id: string) => postJSON<{ ok: boolean }>(`${cp(id)}/leave`)
export const inviteToClub = (id: string, userId: string) => postJSON<{ ok: boolean; message: string }>(`${cp(id)}/invite`, { user_id: userId })
export const answerClubInvite = (id: string, accept: boolean) =>
  postJSON<{ club: ClubSummary | null }>(`${cp(id)}/invite/${accept ? 'accept' : 'decline'}`)
export const decideRequest = (id: string, uid: string, approve: boolean) =>
  postJSON<{ club: ClubDetail }>(`${cp(id)}/requests/${encodeURIComponent(uid)}/${approve ? 'approve' : 'decline'}`)
export const newClubCode = (id: string) => postJSON<{ code: string }>(`${cp(id)}/code`)
export const setMemberRole = (id: string, uid: string, role: 'admin' | 'member') =>
  sendJSON<{ club: ClubDetail }>('PUT', `${cp(id)}/members/${encodeURIComponent(uid)}`, { role })
export const removeMember = (id: string, uid: string) =>
  sendJSON<{ club: ClubDetail }>('DELETE', `${cp(id)}/members/${encodeURIComponent(uid)}`)
export const addMeetup = (id: string, b: MeetupInput) =>
  postJSON<{ meetup: Meetup }>(`${cp(id)}/meetups`, b).then((r) => { milestone('run_posted'); return r })
export const deleteMeetup = (id: string, mid: string) => sendJSON<{ ok: boolean }>('DELETE', `${cp(id)}/meetups/${encodeURIComponent(mid)}`)
export const rsvpMeetup = (id: string, mid: string, status: 'going' | 'maybe' | 'none', acceptWaiver = false) =>
  status === 'none' ? postJSON<{ meetup: Meetup }>(`${cp(id)}/meetups/${encodeURIComponent(mid)}/rsvp`, { status })
    : counted(postJSON<{ meetup: Meetup }>(`${cp(id)}/meetups/${encodeURIComponent(mid)}/rsvp`,
      { status, ...(acceptWaiver ? { accept_waiver: true } : {}) }), 'rsvp', { kind: 'meetup' })
const mp = (id: string, mid: string) => `${cp(id)}/meetups/${encodeURIComponent(mid)}`
export const updateMeetup = (id: string, mid: string, b: Partial<MeetupInput>) => sendJSON<{ meetup: Meetup }>('PATCH', mp(id, mid), b)
export const getRoster = (id: string, mid: string) => getJSON<{ roster: Roster }>(`${mp(id, mid)}/roster`)
export const checkIn = (id: string, mid: string, who: string, on: boolean) =>
  postJSON<{ roster: Roster }>(`${mp(id, mid)}/checkin`, { who, on })
export const skipWeek = (id: string, mid: string, date: string, skip: boolean) =>
  postJSON<{ meetup: Meetup }>(`${mp(id, mid)}/skip`, { date, skip })
export const duplicateRun = (id: string, mid: string) => postJSON<{ meetup: Meetup }>(`${mp(id, mid)}/duplicate`)
export const messageRunners = (id: string, mid: string, text: string) =>
  postJSON<{ ok: boolean; sent: number }>(`${mp(id, mid)}/message`, { text })
export const waiverCsvUrl = (id: string, mid: string) => `/app${mp(id, mid)}/waivers?format=csv`
export const reportRun = (id: string, mid: string, reason?: string) => postJSON<{ ok: boolean }>(`${mp(id, mid)}/report`, { reason })
export const getClubDashboard = (id: string) => getJSON<{ dashboard: ClubDashboard }>(`${cp(id)}/dashboard`)
export const getClubLink = (id: string) => postJSON<{ path: string; url: string }>(`${cp(id)}/link`)
export const getNearbyRuns = (hours = 36) => getJSON<{ runs: Meetup[]; city: string }>(`${P}/runs/nearby?hours=${hours}`)
/** Short tags for a run: beginner, walkers, women-only. */
export function runTags(m: Pick<Meetup, 'beginner' | 'walk' | 'women'>): string[] {
  return [m.beginner && 'No one left behind', m.walk && 'Walkers welcome', m.women && 'Women only'].filter(Boolean) as string[]
}
export const startClubChallenge = (id: string, template: string, period: 'week' | 'month') =>
  postJSON<{ club: ClubDetail }>(`${cp(id)}/challenges`, { template, period })
export const joinClubChallenge = (id: string, gid: string) =>
  postJSON<{ club: ClubDetail }>(`${cp(id)}/challenges/${encodeURIComponent(gid)}/join`)

/** "Sat 7:00 AM" (this week), "Tomorrow 6:30 PM", "Oct 24 7:00 AM". ``iso`` is club-local. */
export function meetupWhen(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const days = Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
    - new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()) / 86400000)
  const t = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  if (days === 0) return `Today ${t}`
  if (days === 1) return `Tomorrow ${t}`
  if (days > 1 && days < 7) return `${d.toLocaleDateString([], { weekday: 'short' })} ${t}`
  return `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${t}`
}

// --------------------------------------------------------------- photos ---
const MAX_SIDE = 1600
const MAX_BYTES = 800 * 1024

function toBlob(canvas: HTMLCanvasElement, type: string, quality: number): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, type, quality))
}

/** Scale to <= 1600 px on the long side and re-encode (JPEG) until it fits 800 KB. */
export async function resizeForPost(file: File): Promise<Blob> {
  if (typeof createImageBitmap !== 'function') throw new Error("This browser can't resize photos.")
  let bmp: ImageBitmap
  try { bmp = await createImageBitmap(file) } catch {
    // iPhone Safari hands HEIC photos over as JPEG; other browsers may not read HEIC at all.
    const heic = /hei[cf]/i.test(file.type) || /\.hei[cf]$/i.test(file.name)
    throw new Error(heic ? "This browser can't read HEIC photos. Pick it from your phone, or save it as a JPEG first."
      : "That file isn't a photo we can read.")
  }
  let side = MAX_SIDE
  for (let attempt = 0; attempt < 3; attempt++) {
    const scale = Math.min(1, side / Math.max(bmp.width, bmp.height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(bmp.width * scale))
    canvas.height = Math.max(1, Math.round(bmp.height * scale))
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error("This browser can't resize photos.")
    ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height)
    for (const q of [0.85, 0.72, 0.6]) {
      const blob = await toBlob(canvas, 'image/jpeg', q)
      if (blob && blob.size <= MAX_BYTES) { bmp.close?.(); return blob }
    }
    side = Math.round(side * 0.75)
  }
  bmp.close?.()
  throw new Error('That photo is too large even after resizing.')
}

export async function uploadPostPhoto(blob: Blob): Promise<string> {
  const r = await fetch(`/app${P}/photos`, {
    method: 'POST', credentials: 'same-origin', headers: { 'content-type': blob.type || 'image/jpeg' }, body: blob,
  })
  if (r.status === 401) throw new AuthError('not signed in')
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.error ?? `HTTP ${r.status}`)
  return data.photo_id as string
}

/** "2h", "3d", or a short date. */
export function ago(ts: number): string {
  const s = Math.max(0, Date.now() / 1000 - ts)
  if (s < 60) return 'now'
  if (s < 3600) return `${Math.floor(s / 60)}m`
  if (s < 86400) return `${Math.floor(s / 3600)}h`
  if (s < 7 * 86400) return `${Math.floor(s / 86400)}d`
  return new Date(ts * 1000).toLocaleDateString([], { month: 'short', day: 'numeric' })
}
export const followSuggested = (userId: string) =>
  postJSON<{ ok: boolean; status: 'active' | 'pending'; message: string }>(`${P}/people/${encodeURIComponent(userId)}/follow`)
    .then((r) => { milestone('follow'); return r })

// Feed extras (server: feedlife.py): no health data from anyone who didn't share it.
export type LifePerson = { id: string; name: string }
export type LifeUpcoming =
  | { kind: 'meetup'; when: string; title: string; where: string; club: { id: string; name: string; emoji: string }
      meetup_id: string; count: number; my_rsvp: 'going' | 'maybe' | null; people: LifePerson[] }
  | { kind: 'race'; when: string; title: string; distance: string | null; people: LifePerson[] }
export type LifeJoined = { kind: 'joined'; club: { id: string; name: string; emoji: string }; ts: number; count: number; people: LifePerson[] }
export type LifeShout =
  | { kind: 'most'; person: LifePerson; workouts: number }
  | { kind: 'longest'; person: LifePerson; minutes: number; title: string }
  | { kind: 'farthest'; person: LifePerson; km: number; title: string }
export type LifeRecap = { kind: 'recap'; week: string; km: number; workouts: number; people: number; shoutouts: LifeShout[] }
export type FeedExtras = { recap: LifeRecap | null; upcoming: LifeUpcoming[]; joined: LifeJoined[] }
