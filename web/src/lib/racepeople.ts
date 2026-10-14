// Race people: who's racing, crewing, pacing or cheering at your races (racepeople.py).
import { getJSON, postJSON, sendJSON } from '@/lib/api'
import type { SocialUser } from '@/lib/social'

export type RaceRole = 'racing' | 'crew' | 'pacer' | 'spectator' | 'coach'
export const ROLE_OPTIONS: [Exclude<RaceRole, 'coach'>, string, string][] = [
  ['racing', 'Racing', 'Racing it too: adds it to their races'],
  ['crew', 'Crew', 'Helps at aid stations'],
  ['pacer', 'Pacer', 'Runs a stretch with you'],
  ['spectator', 'Cheering', 'Family and fans'],
]
export const ROLE_LABEL: Record<RaceRole, string> = {
  racing: 'Racing', crew: 'Crew', pacer: 'Pacer', spectator: 'Cheering', coach: 'Coach',
}
const ROLE_VERB: Record<RaceRole, string> = { racing: 'race', crew: 'crew', pacer: 'pace', spectator: 'cheer', coach: 'coach' }
export const inviteLine = (name: string, role: RaceRole, race: string) => `${name} invited you to ${ROLE_VERB[role]} at ${race}`

export type CrewSettings = {
  show_finish: boolean; show_grade: boolean; show_week: boolean
  team_grade: boolean; team_finish: boolean; crew_notes: string; tracking_url: string
}
export type RacePerson = {
  id: string; role: RaceRole; status: 'invited' | 'accepted'; user_id: string | null; user: SocialUser | null
  email: string | null; coach_email: string | null; ts: number
}
export type RacePeopleView = {
  event_id: string; people: RacePerson[]; settings: CrewSettings; share_url: string | null
  group: string | null; coaches: string[]; racing_together: number; message?: string
}
export type PeopleSummary = { people: SocialUser[]; count: number; pending: number; racing: number; link: boolean }
export type RaceBrief = { name: string; type: string; distance: string; date: string; location: string; url: string; start_time?: string }
export type RaceInvite = { id: string; role: RaceRole; from: SocialUser | null; ts: number; event: RaceBrief }
export type FollowedRace = {
  id: string; role: RaceRole; athlete: SocialUser | null; event: RaceBrief; crew_notes: string; tracking_url: string
}
export type Teammate = { user: SocialUser | null; date: string; grade: string | null; finish: string | null }
export type Together = { members: Teammate[]; me: { team_grade: boolean; team_finish: boolean } }
export type RaceMsg = { id: string; by: { id: string; name: string }; text: string; kind: 'msg' | 'cheer'; ts: number; mine: boolean }

const ev = (id: string) => `/api/events/${encodeURIComponent(id)}`

export const getRacePeople = (eventId: string) => getJSON<RacePeopleView>(`${ev(eventId)}/people`)
export type InviteBody = { role: RaceRole; user_id?: string; email?: string; code?: string; coach_email?: string }
export const inviteToRace = (eventId: string, b: InviteBody) => postJSON<RacePeopleView>(`${ev(eventId)}/people`, b)
export const removeRacePerson = (eventId: string, pid: string) =>
  sendJSON<RacePeopleView>('DELETE', `${ev(eventId)}/people/${encodeURIComponent(pid)}`)
export const putCrew = (eventId: string, patch: Partial<CrewSettings>) =>
  sendJSON<{ settings: CrewSettings }>('PUT', `${ev(eventId)}/crew`, patch)
export const makeCrewLink = (eventId: string) => postJSON<{ url: string }>(`${ev(eventId)}/crew/link`)
export const stopCrewLink = (eventId: string) => sendJSON<{ url: null }>('DELETE', `${ev(eventId)}/crew/link`)
export const getTogether = (eventId: string) => getJSON<Together>(`${ev(eventId)}/together`)
export const getRaceMessages = (eventId: string) => getJSON<{ messages: RaceMsg[] }>(`${ev(eventId)}/together/messages`)
export const postRaceMessage = (eventId: string, text: string) =>
  postJSON<{ message: RaceMsg }>(`${ev(eventId)}/together/messages`, { text })
export const cheerTeam = (eventId: string) => postJSON<{ message: RaceMsg }>(`${ev(eventId)}/together/cheer`, {})

export const getPeopleSummary = () => getJSON<{ events: Record<string, PeopleSummary> }>('/api/races/people')
export const getRaceInvites = () => getJSON<{ invites: RaceInvite[] }>('/api/races/invites')
export const answerRaceInvite = (pid: string, accept: boolean) =>
  postJSON<{ ok: boolean; role: RaceRole; event_id: string | null }>(`/api/races/invites/${encodeURIComponent(pid)}/${accept ? 'accept' : 'decline'}`)
export const getFollowedRaces = () => getJSON<{ races: FollowedRace[] }>('/api/races/following')
export const leaveRace = (pid: string) => sendJSON<{ ok: boolean }>('DELETE', `/api/races/following/${encodeURIComponent(pid)}`)

/** A race contact's uploaded photo (null: none, fall back to their Google picture). */
export function racePhotoUrl(u: SocialUser): string | null {
  return u.photo ? `/app/api/races/people/${encodeURIComponent(u.id)}/photo?v=${u.photo}` : null
}
