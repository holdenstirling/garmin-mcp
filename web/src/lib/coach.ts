// Human coaches: the athlete's side (invite, permissions, messages, shared notes) and the
// coach's side (athletes, plan, messages, notes, Rabbit chats when allowed).
import { getJSON, sendJSON, type Athlete, type Goal } from '@/lib/api'
import type { RaceEvent } from '@/lib/events'
import type { Stats } from '@/lib/stats'

export type CoachLink = {
  email: string; status: 'invited' | 'active'; can_edit_plan: boolean; can_see_rabbit_chats: boolean
  invited_at: number; accepted_at: number | null
}
export type Message = { id: string; from: 'athlete' | 'coach'; text: string; ts: number }
export type ThreadSummary = {
  id: string; coach: string; title: string; session_id: string | null; session_date: string | null
  created: number; updated: number; last: Message | null; count: number
  /** last message id each side has seen */
  read?: { athlete: string | null; coach: string | null }
}
export type Thread = ThreadSummary & { messages: Message[] }
export type Note = { id: string; coach: string; text: string; shared: boolean; pinned: boolean; ts: number; event_id?: string | null }
export type AthleteCard = CoachLink & {
  athlete_id: string; profile: { name: string; picture: string }; photo?: number | null
  goal: { title: string; date: string | null; distance: string } | null; unread: number
}
export type AthleteOverview = {
  athlete_id: string; profile: { name: string; picture: string }; photo?: number | null; link: CoachLink
  athlete: Athlete & Record<string, unknown>; goal: Goal | null; events: RaceEvent[]; notes: Note[]; unread: number
}

// ---------------------------------------------------------------- athlete --
export const getCoaches = () => getJSON<{ coaches: CoachLink[]; unread: number }>('/api/coaches')
export const inviteCoach = (b: { email: string; can_edit_plan: boolean; can_see_rabbit_chats: boolean }) =>
  sendJSON<{ coaches: CoachLink[] }>('POST', '/api/coaches', b)
export const updateCoach = (email: string, b: Partial<Pick<CoachLink, 'can_edit_plan' | 'can_see_rabbit_chats'>>) =>
  sendJSON<{ coaches: CoachLink[] }>('PATCH', `/api/coaches/${encodeURIComponent(email)}`, b)
export const removeCoach = (email: string) => sendJSON<{ coaches: CoachLink[] }>('DELETE', `/api/coaches/${encodeURIComponent(email)}`)
export const getCoachNotes = () => getJSON<{ notes: Note[] }>('/api/coachnotes')

/** Messages API for either side: '/api/coachchat' (athlete) or '/api/coach/athletes/{id}/chat' (coach). */
export function chatApi(base: string) {
  return {
    list: () => getJSON<{ threads: ThreadSummary[]; coaches?: CoachLink[] }>(base),
    open: (b: { coach?: string; session_id?: string }) => sendJSON<{ thread: Thread }>('POST', base, b),
    get: (id: string) => getJSON<{ thread: Thread }>(`${base}/${id}`),
    post: (id: string, text: string) => sendJSON<{ message: Message }>('POST', `${base}/${id}/messages`, { text }),
  }
}
export type ChatApi = ReturnType<typeof chatApi>
export const athleteChat = chatApi('/api/coachchat')

// ------------------------------------------------------------------ coach --
export const coachBase = (aid: string) => `/api/coach/athletes/${encodeURIComponent(aid)}`
export const getAthletes = () => getJSON<{ athletes: AthleteCard[] }>('/api/coach/athletes')
export const getAthlete = (aid: string) => getJSON<AthleteOverview>(coachBase(aid))
export const getAthleteStats = (aid: string) => getJSON<Stats>(`${coachBase(aid)}/stats`)
export const addNote = (aid: string, b: { text: string; shared: boolean; pinned?: boolean; event_id?: string }) =>
  sendJSON<{ note: Note }>('POST', `${coachBase(aid)}/notes`, b)
export const updateNote = (aid: string, id: string, b: Partial<Pick<Note, 'text' | 'shared' | 'pinned'>>) =>
  sendJSON<{ note: Note }>('PATCH', `${coachBase(aid)}/notes/${id}`, b)
export const deleteNote = (aid: string, id: string) => sendJSON<{ ok: boolean }>('DELETE', `${coachBase(aid)}/notes/${id}`)
export const getRabbitThreads = (aid: string) =>
  getJSON<{ threads: { id: string; kind: string; title: string; updated: number }[] }>(`${coachBase(aid)}/rabbit`)
export const getRabbitThread = (aid: string, tid: string) =>
  getJSON<{ thread: { id: string; title: string }; turns: { id: string; ts: number; kind: string; label?: string; user?: string; parts?: { type: string; text?: string }[] }[] }>(`${coachBase(aid)}/rabbit/${tid}`)

export function timeAgo(ts: number): string {
  const s = Math.max(0, Date.now() / 1000 - ts)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  if (s < 7 * 86400) return `${Math.floor(s / 86400)}d ago`
  return new Date(ts * 1000).toLocaleDateString([], { month: 'short', day: 'numeric' })
}
