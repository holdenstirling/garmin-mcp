// Race-week pack: pacing by leg, fueling, gear, weather and the final-week timeline.
import { getJSON } from '@/lib/api'
import type { EventInfo } from '@/lib/events'
import type { GearKind, GearStatus } from '@/lib/gear'

/** One of the athlete's own items relevant to the race, from the gear garage. */
export type RaceGear = {
  id: string; kind: GearKind; name: string; nickname: string; total_km: number
  pct_of_alert: number | null; status: GearStatus; is_default: boolean; warning: string | null
}

export type RacePack = {
  event: { id: string; name: string; type: string; distance: string; date: string; location: string; url: string; priority: string; kind?: string }
  days_out: number; info: EventInfo
  pacing: { leg: string; target: string; detail: string }[]
  fueling: { carbs_g_per_h: number; expected_hours: number; total_carbs_g: number; fluid_ml_per_h: string; sodium_mg_per_h: string; steps: string[] }
  your_gear?: RaceGear[]
  gear: string[]
  weather: { place: string; high_c: number | null; low_c: number | null; rain_pct: number | null; wind_kmh: number | null } | null
  weather_tips: string[]
  week: { date: string; title: string; minutes: number | null }[]
  timeline: { when: string; what: string }[]
}
export const getRacePack = (eventId?: string) => getJSON<RacePack>(`/api/racepack${eventId ? `?event_id=${encodeURIComponent(eventId)}` : ''}`)
