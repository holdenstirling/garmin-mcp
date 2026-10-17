// Direct messages between athletes (server: messages.py / messages_web.py). Mutual friends and
// club / group mates chat freely; anyone else gets a request they accept or decline. Shared
// workouts and events are snapshots (sport, title, date, distance, time, pace; never heart
// rate or location). screens/Chat.tsx listens for the events below and opens the right place.
import { getJSON, sendJSON } from '@/lib/api'

export type DMPerson = { id: string; name: string; photo?: number | null; picture?: string }
export type DMConv = {
  id: string; kind: 'direct' | 'group'; name: string; members: DMPerson[]; owner: boolean
  status: 'active' | 'request'; muted: boolean; unread: boolean; waiting_on: DMPerson[]
  last: { ts: number | null; mine: boolean; preview: string } | null; created: number
}
export type DMWorkoutCard = {
  type: 'workout'; title: string; sport: string | null; date: string; minutes: number | null
  km: number | null; pace: number | null; planned: boolean; mine: boolean
  ref?: { kind: 'session' | 'activity'; id: string; date?: string }
}
export type DMEventCard = {
  type: 'event'; name: string; date: string; time?: string | null; neighborhood: string
  event_type?: string; activity?: string | null; repeat_text?: string; mine: boolean; ref?: { id: string }
}
export type DMMessage = {
  id: string; by: string; mine: boolean; ts: number; text: string
  att: DMWorkoutCard | DMEventCard | null
  reactions: Record<string, { n: number; mine: boolean }>
}
/** What "Send to a friend" attaches. */
export type DMShare =
  | { type: 'workout'; ref: { kind: 'session' | 'activity'; id: string; date?: string }; label: string }
  | { type: 'event'; ref: { id: string }; label: string }

export const REACTIONS = ['👍', '❤️', '🔥', '😂', '👏', '💪'] as const

export const listConvs = () => getJSON<{ convs: DMConv[]; requests: DMConv[]; unread: number }>('/api/dm')
export const dmUnread = () => getJSON<{ unread: number }>('/api/dm/unread')
export const dmPeople = (q = '') => getJSON<{ people: DMPerson[] }>(`/api/dm/people${q ? `?q=${encodeURIComponent(q)}` : ''}`)
export const startConv = (to: string[], opts: { name?: string; text?: string; att?: { type: string; ref: unknown } } = {}) =>
  sendJSON<{ conv: DMConv; msg: DMMessage | null }>('POST', '/api/dm', { to, ...opts })
export const getConv = (id: string, before?: number) =>
  getJSON<{ conv: DMConv; msgs: DMMessage[]; more: boolean }>(`/api/dm/${id}${before != null ? `?before=${before}` : ''}`)
export const sendMsg = (id: string, text: string, att?: { type: string; ref: unknown }) =>
  sendJSON<{ msg: DMMessage }>('POST', `/api/dm/${id}/messages`, { text, ...(att ? { att } : {}) })
export const reactMsg = (id: string, msgId: string, emoji: string) =>
  sendJSON<{ msg: DMMessage }>('POST', `/api/dm/${id}/react`, { msg_id: msgId, emoji })
export const convAction = (id: string, action: 'accept' | 'decline' | 'leave' | 'read') =>
  sendJSON<{ conv?: DMConv; ok?: boolean }>('POST', `/api/dm/${id}/${action}`, {})
export const muteConv = (id: string, muted: boolean) => sendJSON<{ conv: DMConv }>('POST', `/api/dm/${id}/mute`, { muted })
export const renameConv = (id: string, name: string) => sendJSON<{ conv: DMConv }>('PATCH', `/api/dm/${id}`, { name })
export const reportConv = (id: string, msgId: string | null, reason: string) =>
  sendJSON<{ ok: boolean }>('POST', `/api/dm/${id}/report`, { msg_id: msgId, reason })

// ------------------------------------------------------------- navigation --
export const OPEN_DM_EVENT = 'rabbit:open-dm'          // detail: { id }
export const NEW_DM_EVENT = 'rabbit:new-dm'            // detail: { to?: string[]; share?: DMShare }
export const DM_CHANGED_EVENT = 'rabbit:dm-changed'    // unread count may have changed

const fire = (name: string, detail?: unknown) => { try { window.dispatchEvent(new CustomEvent(name, { detail })) } catch { /* old browsers */ } }
/** Open one conversation (page). */
export const openConversation = (id: string) => fire(OPEN_DM_EVENT, { id })
/** Message these people (reuses a 1:1 that already exists). */
export const messagePeople = (to: string[]) => fire(NEW_DM_EVENT, { to })
/** "Send to a friend": pick a chat or people, then the workout / event goes in as a card. */
export const shareToFriends = (share: DMShare) => fire(NEW_DM_EVENT, { share })
export const dmChanged = () => fire(DM_CHANGED_EVENT)

export function convTitle(c: DMConv): string {
  if (c.kind === 'group' && c.name) return c.name
  const names = c.members.map((m) => m.name)
  if (!names.length) return 'Just you'
  return names.length <= 3 ? names.join(', ') : `${names.slice(0, 2).join(', ')} +${names.length - 2}`
}

export function timeAgo(ts: number | null | undefined): string {
  if (!ts) return ''
  const s = Date.now() / 1000 - ts
  if (s < 60) return 'now'
  if (s < 3600) return `${Math.floor(s / 60)}m`
  if (s < 86400) return `${Math.floor(s / 3600)}h`
  if (s < 7 * 86400) return `${Math.floor(s / 86400)}d`
  return new Date(ts * 1000).toLocaleDateString([], { month: 'short', day: 'numeric' })
}
