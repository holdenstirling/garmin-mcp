// Race-week pack: pacing by leg, fueling, gear, weather and the final-week timeline.
import { getJSON } from '@/lib/api'
import type { EventInfo } from '@/lib/events'

export type RacePack = {
  event: { id: string; name: string; type: string; distance: string; date: string; location: string; url: string; priority: string }
  days_out: number; info: EventInfo
  pacing: { leg: string; target: string; detail: string }[]
  fueling: { carbs_g_per_h: number; expected_hours: number; total_carbs_g: number; fluid_ml_per_h: string; sodium_mg_per_h: string; steps: string[] }
  gear: string[]
  weather: { place: string; high_c: number | null; low_c: number | null; rain_pct: number | null; wind_kmh: number | null } | null
  weather_tips: string[]
  week: { date: string; title: string; minutes: number | null }[]
  timeline: { when: string; what: string }[]
}
export const getRacePack = (eventId?: string) => getJSON<RacePack>(`/api/racepack${eventId ? `?event_id=${encodeURIComponent(eventId)}` : ''}`)
