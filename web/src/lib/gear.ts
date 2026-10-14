// Gear garage: shoes, bikes and the rest, with mileage and retirement alerts.
import { getJSON, sendJSON } from '@/lib/api'
import { KM_PER_MI, fmtDist as fmtDistBase } from '@/lib/format'

export type GearKind = 'shoes' | 'bike' | 'wetsuit' | 'watch' | 'power_meter' | 'helmet' | 'other'
export type BikeType = 'road' | 'tri' | 'gravel' | 'mtb' | 'indoor'
export type ShoeType = 'road' | 'trail' | 'track' | 'racing'
export type GearSport = 'run' | 'bike' | 'swim' | 'hike' | 'climb' | 'ski' | 'paddle' | 'strength' | 'other'
export type GearStatus = 'ok' | 'soon' | 'retire'

export type GearItem = {
  id: string; kind: GearKind; brand: string; model: string; nickname: string; size: string
  bike_type: BikeType | null; shoe_type: ShoeType | null
  sports: GearSport[]; default_for: GearSport[]
  start_km: number; alert_km: number | null
  added: string; retired: boolean; retired_on: string | null; notes: string
  garmin_uuid: string | null; activity_ids: number[]
  // computed by the server
  total_km: number; activities: number; last_used: string | null
  pct_of_alert: number | null; status: GearStatus; source: 'rabbit' | 'garmin'
}

export type GearFields = Partial<Pick<GearItem,
  'kind' | 'brand' | 'model' | 'nickname' | 'size' | 'bike_type' | 'shoe_type' | 'sports' | 'default_for'
  | 'start_km' | 'alert_km' | 'added' | 'retired' | 'notes' | 'activity_ids'>>

export type GearList = {
  items: GearItem[]; stats_ok: boolean; item_id?: string
  imported?: { created: number; updated: number; skipped: number }
}
export type GearCatalog = {
  kinds: GearKind[]
  brands: Partial<Record<GearKind, string[]>>
  sizes: Partial<Record<GearKind, string[]>>
  bike_types: BikeType[]; shoe_types: ShoeType[]; sports: GearSport[]
  default_alert_km: Partial<Record<GearKind, number | null>>
  max_items: number
}
export type GearResponse = GearList & GearCatalog

const path = (id: string) => `/api/gear/${encodeURIComponent(id)}`
export const getGear = () => getJSON<GearResponse>('/api/gear')
export const createGear = (f: GearFields) => sendJSON<GearList>('POST', '/api/gear', f)
export const updateGear = (id: string, f: GearFields) => sendJSON<GearList>('PATCH', path(id), f)
export const deleteGear = (id: string) => sendJSON<GearList>('DELETE', path(id))
export const retireGear = (id: string, retired = true) => sendJSON<GearList>('POST', `${path(id)}/retire`, { retired })
export const importGarminGear = () => sendJSON<GearList>('POST', '/api/gear/import-garmin', {})

export const KIND_ORDER: GearKind[] = ['shoes', 'bike', 'wetsuit', 'watch', 'power_meter', 'helmet', 'other']
export const KIND_LABEL: Record<GearKind, string> = {
  shoes: 'Shoes', bike: 'Bike', wetsuit: 'Wetsuit', watch: 'Watch', power_meter: 'Power meter', helmet: 'Helmet', other: 'Other',
}
export const KIND_GROUP: Record<GearKind, string> = {
  shoes: 'Shoes', bike: 'Bikes', wetsuit: 'Wetsuits', watch: 'Watches', power_meter: 'Power meters', helmet: 'Helmets', other: 'Other gear',
}
export const SHOE_TYPE_LABEL: Record<ShoeType, string> = { road: 'Road', trail: 'Trail', track: 'Track', racing: 'Racing' }
export const BIKE_TYPE_LABEL: Record<BikeType, string> = { road: 'Road', tri: 'Tri/TT', gravel: 'Gravel', mtb: 'MTB', indoor: 'Indoor' }
export const SPORT_LABEL: Record<GearSport, string> = {
  run: 'Run', bike: 'Ride', swim: 'Swim', hike: 'Hike', climb: 'Climb', ski: 'Ski', paddle: 'Paddle', strength: 'Strength', other: 'Other',
}
/** Sport a new item of this kind is usually the default for. */
export const DEFAULT_SPORT: Partial<Record<GearKind, GearSport>> = { shoes: 'run', bike: 'bike', wetsuit: 'swim' }

export { KM_PER_MI }

/** "Hoka Clifton 9", falling back to the nickname or the kind. */
export function gearName(g: Pick<GearItem, 'brand' | 'model' | 'nickname' | 'kind'>): string {
  return [g.brand, g.model].filter(Boolean).join(' ') || g.nickname || KIND_LABEL[g.kind]
}

/** Gear mileage reads in whole units. */
export function fmtDist(km: number, imperial: boolean): string {
  return fmtDistBase(km, imperial, null, { decimals: 0 })
}
