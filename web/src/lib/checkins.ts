// Voice check-ins (server: checkins.py). The athlete's words become a structured entry
// (feel, RPE, sleep, soreness, pain flag...) that Rabbit's Today card and plan adjustments use.
import { getJSON, sendJSON } from '@/lib/api'

export const AREAS = ['calf', 'shin', 'achilles', 'knee', 'hamstring', 'quad', 'hip', 'glute', 'lower_back', 'upper_back',
  'shoulder', 'neck', 'foot', 'ankle', 'it_band', 'groin', 'other'] as const
export type Area = (typeof AREAS)[number]
export type Side = 'left' | 'right' | 'both'
export type Level = 1 | 2 | 3
export type Soreness = { area: Area; side: Side | null; level: Level }
export type Energy = 'low' | 'ok' | 'high'
export type Sleep = 'poor' | 'ok' | 'good'
export type Mood = 'great' | 'good' | 'meh' | 'low'

export type Checkin = {
  id: string; date: string; ts: number
  session_id: string | null; activity_id: string | null
  text: string; feel: number | null; rpe: number | null
  energy: Energy | null; sleep: Sleep | null; soreness: Soreness[]
  pain_flag: boolean; mood: Mood | null; tags: string[]; summary: string
  edited?: boolean
}
export type CheckinEdit = Partial<Pick<Checkin, 'feel' | 'rpe' | 'energy' | 'sleep' | 'soreness' | 'pain_flag' | 'mood' | 'summary' | 'text'>>
export type NewCheckin = { text: string; session_id?: string; activity_id?: string | number; date?: string; feel?: number
  /** tapped answers (the workout page): they win over what's parsed from the words */
  rpe?: number; pain?: boolean }

export const AREA_LABEL: Record<Area, string> = {
  calf: 'Calf', shin: 'Shin', achilles: 'Achilles', knee: 'Knee', hamstring: 'Hamstring', quad: 'Quad', hip: 'Hip',
  glute: 'Glute', lower_back: 'Lower back', upper_back: 'Upper back', shoulder: 'Shoulder', neck: 'Neck', foot: 'Foot',
  ankle: 'Ankle', it_band: 'IT band', groin: 'Groin', other: 'Somewhere else',
}
const LEVEL_WORD: Record<Level, string> = { 1: 'a bit tight', 2: 'sore', 3: 'really sore' }

export function sorenessLabel(s: Soreness): string {
  const area = AREA_LABEL[s.area] ?? s.area
  const where = s.side === 'both' ? `Both ${area.toLowerCase()}s` : s.side ? `${s.side[0]!.toUpperCase()}${s.side.slice(1)} ${area.toLowerCase()}` : area
  return `${where} · ${LEVEL_WORD[s.level] ?? 'sore'}`
}

/** Short chips for a saved check-in: "Feel 2/5", "RPE 6", "Left calf · a bit tight", "Sleep poor". */
export function checkinChips(c: Checkin): { label: string; warn?: boolean }[] {
  const out: { label: string; warn?: boolean }[] = []
  if (c.feel != null) out.push({ label: `Feel ${c.feel}/5`, warn: c.feel <= 2 })
  if (c.rpe != null) out.push({ label: `RPE ${c.rpe}` })
  for (const s of c.soreness) out.push({ label: sorenessLabel(s), warn: s.level >= 3 })
  if (c.sleep) out.push({ label: `Sleep ${c.sleep}`, warn: c.sleep === 'poor' })
  if (c.energy) out.push({ label: `Energy ${c.energy}`, warn: c.energy === 'low' })
  if (c.mood) out.push({ label: `Mood ${c.mood}` })
  if (c.pain_flag) out.push({ label: 'Pain flagged', warn: true })
  return out
}

export const listCheckins = (days = 30, sessionId?: string) =>
  getJSON<{ checkins: Checkin[] }>(`/api/checkins?days=${days}${sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : ''}`)
export const createCheckin = (body: NewCheckin) =>
  sendJSON<{ checkin: Checkin; source: 'model' | 'fallback'; xp: number }>('POST', '/api/checkins', body)
export const updateCheckin = (id: string, patch: CheckinEdit) =>
  sendJSON<{ checkin: Checkin }>('PATCH', `/api/checkins/${encodeURIComponent(id)}`, patch)
export const deleteCheckin = (id: string) =>
  sendJSON<{ ok: boolean }>('DELETE', `/api/checkins/${encodeURIComponent(id)}`)
