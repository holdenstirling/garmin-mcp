// Community v2 (featured.py, feedgroups.py, routes in feed2_web.py): featured clubs, friends'
// latest for the Rabbit home, feed groups.
import { getJSON, postJSON, sendJSON } from '@/lib/api'
import type { Post } from '@/lib/community'
import type { SocialUser } from '@/lib/social'

const P = '/api/community'

export type FeaturedNext = { id: string; title: string; next: string; going: number; my_rsvp: 'going' | 'maybe' | 'waitlist' | null; where: string }
export type Featured = {
  id: string; kind: 'club' | 'listing'; label: 'Featured'; tagline: string; until: string | null; online: boolean; local: boolean
  name: string; city: string; state: string; description: string; members: number | null
  // Rabbit clubs
  club_id?: string; emoji?: string; sport?: string; privacy?: 'open' | 'approval'
  role?: 'owner' | 'admin' | 'member' | null; requested?: boolean; next_meetup?: FeaturedNext | null; full?: boolean
  // directory listings
  listing_id?: string; kind_label?: string; join_url?: string; link_only?: string | null
  next?: { weekday: string; time: string | null; in_days: number; date?: string | null } | null
  going?: { date: string; count: number; me: boolean } | null; same_metro?: boolean
}
export type FeatureState = { owner: boolean; featured?: boolean; until?: string | null; tagline?: string; online?: boolean; slots_left?: number }
export type GroupBrief = { id: string; name: string; emoji: string; count: number; owner: boolean }
export type FeedGroup = GroupBrief & { owner_id: string; members: (SocialUser | null)[]; max: number }

export const getCommunityHome = () =>
  getJSON<{ view: 'feed' | 'clubs'; featured: Featured[]; groups: GroupBrief[] }>(`${P}/home`)
export const getFriendsLatest = () => getJSON<{ items: Post[] }>(`${P}/latest`)
export const getFeatured = (where: 'community' | 'explore' = 'community') =>
  getJSON<{ items: Featured[] }>(`${P}/featured?where=${where}`)
export const getFeatureState = (ref: { club?: string; listing?: string }) =>
  getJSON<FeatureState>(`${P}/featured/manage?${ref.club ? `club=${encodeURIComponent(ref.club)}` : `listing=${encodeURIComponent(ref.listing ?? '')}`}`)
export const setFeature = (ref: { club_id?: string; listing_id?: string }, b: { on: boolean; until?: string | null; tagline?: string; online?: boolean }) =>
  sendJSON<FeatureState>('PUT', `${P}/featured`, { ...ref, ...b })

const gp = (id: string) => `${P}/groups/${encodeURIComponent(id)}`
export const listGroups = () => getJSON<{ groups: FeedGroup[]; max: number }>(`${P}/groups`)
export const groupFriends = () => getJSON<{ people: (SocialUser | null)[] }>(`${P}/groups/friends`)
export const createGroup = (b: { name: string; emoji: string; members: string[] }) =>
  postJSON<{ group: FeedGroup }>(`${P}/groups`, b)
export const getGroup = (id: string) => getJSON<{ group: FeedGroup }>(gp(id))
export const updateGroup = (id: string, b: { name?: string; emoji?: string }) => sendJSON<{ group: FeedGroup }>('PATCH', gp(id), b)
export const deleteGroup = (id: string) => sendJSON<{ ok: boolean }>('DELETE', gp(id))
export const addToGroup = (id: string, userIds: string[]) => postJSON<{ group: FeedGroup; added: number }>(`${gp(id)}/members`, { user_ids: userIds })
export const removeFromGroup = (id: string, uid: string) => sendJSON<{ group: FeedGroup }>('DELETE', `${gp(id)}/members/${encodeURIComponent(uid)}`)
export const leaveGroup = (id: string) => postJSON<{ ok: boolean }>(`${gp(id)}/leave`)

/** "grp:a,b" -> ["a", "b"] */
export const groupIds = (a: string) => (a.startsWith('grp:') ? a.slice(4).split(',').filter(Boolean) : [])
