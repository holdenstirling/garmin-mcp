// TrainingPeaks two-way (server: tpsync.py, routes tp_web.py). The athlete pastes their
// TrainingPeaks session value once (stored encrypted, never sent back); planned workouts show on
// the plan calendar tagged "From TrainingPeaks"; a setting picks which plan is the source.
import { getJSON, postJSON, sendJSON } from '@/lib/api'

export type TPSource = 'trainingpeaks' | 'rabbit'
export type TPItem = {
  id: number
  date: string
  /** Rabbit sport key (swim/bike/run/brick/strength/race/other) */
  sport: string
  tp_sport: string
  title: string
  minutes: number | null
  distance_km: number | null
  tss: number | null
  description: string | null
  coach_notes: string | null
  /** readable structure lines ("3x: On 10' 88-93%") */
  structure: string[]
  completed: boolean
  /** a workout Rabbit created (Rabbit was the source) */
  ours: boolean
  /** the Rabbit session it duplicates, if any */
  session_id: string | null
  garmin_activity_id: number | null
  /** shown on the calendar (false = its Rabbit twin shows instead) */
  show: boolean
  can_move: boolean
}
export type TPView = {
  connected: boolean
  source: TPSource
  last_sync: number | null
  state: 'connected' | 'attention' | 'not_connected'
  error: string | null
  items: TPItem[]
  /** Rabbit sessions hidden because TrainingPeaks is the source and has the same workout */
  hide_sessions: string[]
  linked_sessions: Record<string, number>
}

export const getTP = () => getJSON<TPView>('/api/trainingpeaks')
export const connectTP = (cookie: string) =>
  postJSON<{ connected: boolean; name: string | null; view: TPView }>('/api/trainingpeaks/connect', { cookie })
export const disconnectTP = () => postJSON<{ connected: boolean }>('/api/trainingpeaks/disconnect')
export const setTPSource = (source: TPSource) => sendJSON<TPView>('PUT', '/api/trainingpeaks/settings', { source })
export const syncTP = () => postJSON<{ result: { ok: boolean; error?: string }; view: TPView }>('/api/trainingpeaks/sync')
export const moveTP = (id: number, date: string) => postJSON<TPView>(`/api/trainingpeaks/workouts/${id}/move`, { date })

export const TP_SOURCE_LABEL: Record<TPSource, string> = {
  trainingpeaks: 'TrainingPeaks plan (coach)',
  rabbit: 'rabbt plan',
}
export const TP_SOURCE_HINT: Record<TPSource, string> = {
  trainingpeaks: 'Your TrainingPeaks workouts show in rabbt. rabbt doesn’t write to TrainingPeaks, except when you move a workout here.',
  rabbit: 'rabbt adds your next 14 days to TrainingPeaks and keeps them updated when you edit, move or delete a session. It never touches workouts it didn’t create.',
}

// Plan screens re-read when something synced or the source changed.
export const TP_CHANGED = 'rabbit:tp-changed'
export function tpChanged(): void {
  window.dispatchEvent(new CustomEvent(TP_CHANGED))
}
