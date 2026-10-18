// Connected screens (server: people.py / people_web.py): person profiles, the notifications
// inbox, Home's "Friends today", "Who else is doing this?" and club group chats. Plus the
// app-wide "open X" events that Chat.tsx listens for, so any screen can open any other.
import { getJSON, sendJSON } from '@/lib/api'
import { NEW_DM_EVENT, type DMShare } from '@/lib/dm'

export type PersonRef = { id: string; name: string; photo?: number | null; picture?: string }
export type FeedWorkout = {
  id: string; date: string; time: string | null; sport: string; title: string
  minutes: number | null; km: number | null; climb_m?: number | null; race?: boolean
}
export type Profile = {
  person: PersonRef; me: boolean; city: string; following: boolean; follows_you: boolean; pending: boolean
  can_message: 'direct' | 'request' | null
  workouts: FeedWorkout[]; workouts_hidden: boolean
  stats: { workouts_4w: number; km_4w: number | null; minutes_4w: number | null } | null
  clubs: { id: string; name: string; emoji: string; sport: string; members: number | null; shared: boolean }[]
  races: { key: string; name: string; date: string; type: string; activity: string; neighborhood: string }[]
  in_common: { clubs: string[] }
}
export type NotifOpen =
  | { k: 'dm'; id: string } | { k: 'people' } | { k: 'person'; id: string } | { k: 'activity'; id: string }
  | { k: 'feed' } | { k: 'club'; id: string } | { k: 'checklist'; id: string }
  | { k: 'post'; id: string; comment?: string }
export type Notif = {
  key: string; kind: string; title: string; body: string; ts: number; unread: boolean
  person: PersonRef | null; open: NotifOpen
}
export type FriendsToday = {
  today: string
  trained: { person: PersonRef; workout: FeedWorkout; count: number; kudos: number; you_cheered: boolean }[]
  racing: { person: PersonRef; key: string; name: string; date: string; activity: string }[]
}
export type AlsoDoing = {
  same_sport: { person: PersonRef; workout: FeedWorkout; count: number }[]
  same_event: { person: PersonRef; key: string }[]
}

const enc = encodeURIComponent
export const getProfile = (uid: string) => getJSON<Profile>(`/api/people/${enc(uid)}`)
export const followPerson = (uid: string, on: boolean) =>
  sendJSON<Profile | { ok: true; gone: true }>(on ? 'POST' : 'DELETE', `/api/people/${enc(uid)}/follow`, {})
export const blockPerson = (uid: string) => sendJSON<{ ok: true }>('POST', `/api/people/${enc(uid)}/block`, {})
export const reportPerson = (uid: string, reason: string) => sendJSON<{ ok: true }>('POST', `/api/people/${enc(uid)}/report`, { reason })
export const getNotifications = () => getJSON<{ items: Notif[]; unread: number }>('/api/notifications')
export const markNotificationsRead = (keys?: string[]) =>
  sendJSON<{ items: Notif[]; unread: number }>('POST', '/api/notifications/read', keys ? { keys } : {})
export const getFriendsToday = () => getJSON<FriendsToday>('/api/friends/today')
export const getAlsoDoing = (q: { sport?: string; date?: string; event_name?: string; event_date?: string }) => {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(q)) if (v) p.set(k, v)
  return getJSON<AlsoDoing>(`/api/people/also?${p.toString()}`)
}
export const openClubChat = (clubId: string) =>
  sendJSON<{ conv: { id: string } }>('POST', `/api/clubs/${enc(clubId)}/chat`, {})

/** Profile photo through the community route (only people you may already see). */
export function personPhoto(p: PersonRef | null | undefined): string | null {
  return p?.photo ? `/app/api/community/people/${enc(p.id)}/photo?v=${p.photo}` : null
}

// ------------------------------------------------------------ open anything --
// Chat.tsx listens and opens the page (the page stack: back returns where you were).
export const OPEN_PERSON_EVENT = 'rabbit:open-person'      // detail: uid
export const OPEN_TARGET_EVENT = 'rabbit:open-target'      // detail: a NotifOpen target
export const NOTIFS_CHANGED_EVENT = 'rabbit:notifs-changed'

const fire = (name: string, detail?: unknown) => { try { window.dispatchEvent(new CustomEvent(name, { detail })) } catch { /* old browsers */ } }
export const openPerson = (uid: string) => fire(OPEN_PERSON_EVENT, uid)
export const openTarget = (t: NotifOpen) => fire(OPEN_TARGET_EVENT, t)
export const notifsChanged = () => fire(NOTIFS_CHANGED_EVENT)

// ---------------------------------------------------------------- deep links --
// In-app links any screen can copy or share: /app/?open=<kind>&id=<id>[&date=]. Chat.tsx reads
// them on load (also from push taps) and opens the page.
export type DeepKind = 'workout' | 'activity' | 'event' | 'club' | 'person' | 'checklist' | 'post'
export function deepLink(kind: DeepKind, id: string, date?: string): string {
  const p = new URLSearchParams({ open: kind, id })
  if (date) p.set('date', date)
  return `${window.location.origin}/app/?${p.toString()}`
}
export async function copyDeepLink(kind: DeepKind, id: string, date?: string): Promise<boolean> {
  try { await navigator.clipboard.writeText(deepLink(kind, id, date)); return true } catch { return false }
}

export function sportWord(sport: string): string {
  const s = sport.toLowerCase()
  return s.includes('run') ? 'Run' : s.includes('cycl') || s.includes('bik') || s.includes('ride') ? 'Ride'
    : s.includes('swim') ? 'Swim' : s.includes('walk') ? 'Walk' : s.includes('hik') ? 'Hike'
      : s.includes('strength') ? 'Strength' : s ? s[0]!.toUpperCase() + s.slice(1) : 'Workout'
}

/** "Invite to join": the New message sheet with this workout / event as a card (and, when
 *  given, these people already picked). */
export function inviteToJoin(share: DMShare, to?: string[]) {
  fire(NEW_DM_EVENT, to?.length ? { to, share } : { share })
}
