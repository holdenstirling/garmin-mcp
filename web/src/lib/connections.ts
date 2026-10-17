// Connected apps (server: connections.py): Garmin, Oura, Google Calendar, TrainingPeaks and Apple Watch, one status row
// each for the Me -> Connected apps hub and the connect popup (components/connect/), plus the
// coming-soon apps (Whoop, Coros; demand.py) with "I want this".
// Any screen opens an app's popup with requestConnect(app); screens/Chat.tsx listens.
import { getJSON, sendJSON, type DataSources } from '@/lib/api'
import { OURA_CONNECT_URL } from '@/lib/oura'
import { CALENDAR_CONNECT_URL } from '@/lib/calendar'

export type ConnApp = 'garmin' | 'oura' | 'calendar' | 'trainingpeaks' | 'apple'
export type ConnState = 'connected' | 'attention' | 'not_connected' | 'unavailable'
export type Connection = {
  id: ConnApp; name: string; kind: 'password' | 'oauth' | 'cookie' | 'shortcut'
  available: boolean; connected: boolean; state: ConnState
  /** ISO time of the last successful read, or null */
  last_sync: string | null
  error: string | null
  import_weeks: number; import_label: string
  /** what Rabbit reads / what it never does (connections.APPS, matches the privacy policy) */
  reads: string[]; never: string[]
  /** a gentle note on a connected app (e.g. "Connect Oura again to import its workouts.") */
  note?: string
}
/** Apps that can't connect yet (server: demand.py). `wanted_by` only for the app's owners. */
export type SoonId = 'whoop' | 'apple' | 'coros'
export type SoonApp = { id: SoonId; name: string; state: 'soon'; why: string; would_use: string[]; wanted: boolean; wanted_by?: number }
export type Connections = { apps: Connection[]; sources: DataSources | null; soon?: SoonApp[] }

export const getConnections = () => getJSON<Connections>('/api/connections')
export const syncConnection = (app: 'oura' | 'calendar' | 'trainingpeaks') =>
  sendJSON<{ app: Connection }>('POST', `/api/connections/${app}/sync`, {})
/** "I want this" on a coming-soon app; counts once per person. */
export const wantApp = (app: SoonId, want: boolean) =>
  sendJSON<{ app: SoonId; wanted: boolean; wanted_by?: number }>('POST', `/api/connections/${app}/want`, { want })
export const OAUTH_URL: Record<'oura' | 'calendar', string> = { oura: OURA_CONNECT_URL, calendar: CALENDAR_CONNECT_URL }

/** Back from a provider: `?oura=connected|failed`, `?calendar=connected|...`. */
export type ConnResult = 'connected' | 'failed'
export type ConnectRequest = { app: ConnApp; result?: ConnResult; ask?: boolean }

export const CONNECT_EVENT = 'rabbit:connect-garmin'
export function requestConnect(app: ConnApp = 'garmin'): void {
  window.dispatchEvent(new CustomEvent<ConnApp>(CONNECT_EVENT, { detail: app }))
}

// Something connected, synced or disconnected: the hub (if open) re-reads.
export const CONNECTIONS_CHANGED = 'rabbit:connections-changed'
export function connectionsChanged(): void {
  window.dispatchEvent(new CustomEvent(CONNECTIONS_CHANGED))
}

/** "Synced 5 min ago" / "Synced yesterday" / "Not synced yet". */
export function syncedAgo(iso: string | null, now = Date.now()): string {
  if (!iso) return 'Not synced yet'
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return 'Not synced yet'
  const min = Math.max(0, Math.round((now - t) / 60000))
  if (min < 1) return 'Synced just now'
  if (min < 60) return `Synced ${min} min ago`
  const h = Math.round(min / 60)
  if (h < 24) return `Synced ${h} h ago`
  const d = Math.round(h / 24)
  return d === 1 ? 'Synced yesterday' : `Synced ${d} days ago`
}

export const STATE_LABEL: Record<ConnState, string> = {
  connected: 'Connected', attention: 'Needs attention', not_connected: 'Not connected', unavailable: 'Coming soon',
}
