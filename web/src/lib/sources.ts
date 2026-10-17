// Data sources: workouts that count come from Garmin (Oura workouts Garmin missed are display-only, so
// nothing is counted twice); recovery and sleep come from Garmin or Oura, the athlete's call.
import { useSyncExternalStore } from 'react'
import { getJSON, type DataSource, type DataSources } from '@/lib/api'
import type { OuraRecovery } from '@/lib/oura'

export type { DataSource, DataSources }

export const SOURCE_NAME: Record<DataSource, string> = { garmin: 'Garmin', oura: 'Oura' }

export const defaultSources = (ouraConnected: boolean): DataSources => {
  const s: DataSource = ouraConnected ? 'oura' : 'garmin'
  return { workouts: 'garmin', recovery: s, sleep: s, show_both: false }
}

/** "Workouts: Garmin · Recovery: Oura" (plus sleep when it differs). */
export function sourcesSummary(s: DataSources): string {
  const parts = [`Workouts: Garmin`, `Recovery: ${SOURCE_NAME[s.recovery]}`]
  if (s.sleep !== s.recovery) parts.push(`Sleep: ${SOURCE_NAME[s.sleep]}`)
  return parts.join(' · ')
}

/** Recovery rows from either source share Oura's shape (Garmin adds hrv_week). */
export type RecoveryData = OuraRecovery & { source?: DataSource }
export type RecoveryBoth = {
  sources: DataSources; oura_connected: boolean
  oura: RecoveryData | null; garmin: RecoveryData | null
}
export const getRecovery = () => getJSON<RecoveryBoth>('/api/recovery')

// The signed-in athlete's current choice, set from /me by the app shell so screens can read
// it without another request or extra props.
let current: DataSources | null = null
const listeners = new Set<() => void>()
export function setCurrentSources(s: DataSources | null | undefined) {
  const next = s ?? null
  if (JSON.stringify(next) === JSON.stringify(current)) return
  current = next
  listeners.forEach((l) => l())
}
export function useDataSources(): DataSources | null {
  return useSyncExternalStore((l) => { listeners.add(l); return () => { listeners.delete(l) } }, () => current, () => current)
}
