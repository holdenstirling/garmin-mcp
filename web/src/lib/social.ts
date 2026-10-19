// Following friends: people you follow, their recent workouts, kudos and short cheers.
import { getJSON, postJSON, sendJSON } from '@/lib/api'
import { fmtClimb, fmtDuration } from '@/lib/format'
import { counted } from '@/lib/usage'
import { famDist, noDistance, sportFamily } from '@/lib/sportstats'

export type SocialUser = { id: string; name: string; photo: number | null; picture: string; handle?: string }
export type FeedUser = SocialUser & { level: number | null; streak: number | null }
export type SocialSettings = {
  workouts: boolean; distance: boolean; times: boolean; streak: boolean; races: boolean; auto_accept: boolean
}
export type PersonEdge = { edge_id: string; user_id: string | null; user: SocialUser | null; since?: number; ts?: number; email?: string | null }
export type People = {
  following: PersonEdge[]; followers: PersonEdge[]; pending_in: PersonEdge[]; pending_out: PersonEdge[]
  blocked: (SocialUser | null)[]; invite_code: string; settings: SocialSettings
}
export type Cheer = { id: string; by: { id: string; name: string }; text: string; ts: number; mine: boolean; can_delete: boolean }
export type FeedItem = {
  id: string; date: string; time: string | null; sport: string; title: string
  minutes: number | null; km: number | null; climb_m: number | null; xp: number | null; race: boolean
  user: FeedUser; mine: boolean; kudos: number; you_kudoed: boolean; cheers: Cheer[]
}
export type FriendCard = {
  user: FeedUser; week: { workouts: number; hours: number | null } | null; recent: FeedItem[]
  shares: { workouts: boolean; distance: boolean; times: boolean; streak: boolean; races: boolean }
}
export type SocialBadge = { pending: number; new_kudos: number }

export const getPeople = () => getJSON<People>('/api/social')
export const getFeed = () => getJSON<{ items: FeedItem[]; following: number }>('/api/social/feed')
export const getBadge = () => getJSON<SocialBadge>('/api/social/badge')
export const markSocialSeen = () => postJSON<{ ok: boolean }>('/api/social/seen')
export const getFriend = (id: string) => getJSON<FriendCard>(`/api/social/people/${encodeURIComponent(id)}`)

/** ``value`` is an email (has "@") or an invite code. */
export const follow = (value: string) =>
  postJSON<{ ok: boolean; message: string }>('/api/social/follow', value.includes('@') ? { email: value } : { code: value })
export const acceptRequest = (edge: string) => postJSON<{ ok: boolean }>(`/api/social/requests/${edge}/accept`)
export const declineRequest = (edge: string) => postJSON<{ ok: boolean }>(`/api/social/requests/${edge}/decline`)
export const unfollow = (edge: string) => sendJSON<{ ok: boolean }>('DELETE', `/api/social/following/${edge}`)
export const removeFollower = (edge: string) => sendJSON<{ ok: boolean }>('DELETE', `/api/social/followers/${edge}`)
export const blockUser = (userId: string) => postJSON<{ ok: boolean }>('/api/social/block', { user_id: userId })
export const unblockUser = (userId: string) => sendJSON<{ ok: boolean }>('DELETE', `/api/social/block/${encodeURIComponent(userId)}`)
export const putSocialSettings = (patch: Partial<SocialSettings>) =>
  sendJSON<{ settings: SocialSettings }>('PUT', '/api/social/settings', patch)
export const newInviteCode = () => postJSON<{ invite_code: string }>('/api/social/code')

const actPath = (owner: string, id: string) => `/api/social/kudos/${encodeURIComponent(owner)}/${encodeURIComponent(id)}`
export const giveKudos = (owner: string, id: string) => counted(postJSON<{ count: number; you_kudoed: boolean }>(actPath(owner, id)), 'cheer')
export const takeKudos = (owner: string, id: string) => sendJSON<{ count: number; you_kudoed: boolean }>('DELETE', actPath(owner, id))
export const addCheer = (owner: string, id: string, text: string) =>
  counted(postJSON<{ cheer: Cheer }>(`/api/social/cheers/${encodeURIComponent(owner)}/${encodeURIComponent(id)}`, { text }), 'cheer')
export const deleteCheer = (owner: string, id: string, cheer: string) =>
  sendJSON<{ ok: boolean }>('DELETE', `/api/social/cheers/${encodeURIComponent(owner)}/${encodeURIComponent(id)}/${encodeURIComponent(cheer)}`)

/** A followed person's uploaded photo (null: none, fall back to their Google picture). */
export function friendPhotoUrl(u: SocialUser): string | null {
  return u.photo ? `/app/api/social/people/${encodeURIComponent(u.id)}/photo?v=${u.photo}` : null
}

/** "45 min · 8.2 km" from whatever the person shares. */
export function workoutLine(it: Pick<FeedItem, 'minutes' | 'km' | 'climb_m'> & { sport?: string }, imperial = true): string {
  const parts: string[] = []
  const fam = sportFamily(it.sport)
  if (it.minutes != null) parts.push(fmtDuration(it.minutes))
  // No distance for a gym, yoga or climbing session; swims in yards or meters.
  if (it.km && !noDistance(fam)) parts.push(famDist(it.km, fam, imperial))
  if (it.climb_m && it.climb_m >= 100) parts.push(`${fmtClimb(it.climb_m, imperial)} up`)
  return parts.join(' · ')
}

/** "Today", "Yesterday", "3 days ago", or a short date. */
export function relativeDay(date: string, time?: string | null): string {
  const d = new Date(`${date}T${time ?? '12:00'}:00`)
  const today = new Date(); today.setHours(0, 0, 0, 0)
  const day = new Date(d); day.setHours(0, 0, 0, 0)
  const diff = Math.round((today.getTime() - day.getTime()) / 86_400_000)
  if (diff <= 0) {
    const mins = Math.round((Date.now() - d.getTime()) / 60_000)
    if (time && mins >= 0 && mins < 60) return mins < 2 ? 'Just now' : `${mins} min ago`
    if (time && mins >= 60 && mins < 12 * 60) return `${Math.floor(mins / 60)} h ago`
    return 'Today'
  }
  if (diff === 1) return 'Yesterday'
  if (diff < 7) return `${diff} days ago`
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}
