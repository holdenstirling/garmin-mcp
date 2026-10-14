// Oura Ring recovery data (shown in the app only; never sent to the coach model).
import { getJSON, sendJSON } from '@/lib/api'

export type OuraDay = {
  date: string; readiness?: number; sleep_score?: number; hrv?: number; resting_hr?: number
  sleep_hours?: number; activity_score?: number; steps?: number; temp_deviation?: number
}
export type OuraRecovery = {
  available: boolean; connected: boolean; error?: string
  window?: number; days?: OuraDay[]; latest?: OuraDay | null
  baseline?: { hrv: number | null; resting_hr: number | null; readiness: number | null; sleep_hours: number | null }
}
export const getOura = (days = 28) => getJSON<OuraRecovery>(`/api/oura?days=${days}`)
export const disconnectOura = () => sendJSON<{ connected: false }>('DELETE', '/api/oura')
export const OURA_CONNECT_URL = '/app/auth/oura/start'
