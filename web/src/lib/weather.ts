// Weather-aware workouts (server: weather.py rules, weather_web.py routes). Display only: the
// stored plan never changes. Temperatures come in °C and wind in km/h; format with fmtTemp /
// fmtWind (miles and °F unless the athlete chose metric).
import { getJSON } from '@/lib/api'
import { CloudDrizzle, CloudFog, CloudLightning, CloudRain, CloudSnow, CloudSun, Cloud, Haze, Mountain, Snowflake, Sun, ThermometerSun, Umbrella, Wind } from 'lucide-react'

export type WxHour = {
  t: string; temp_c: number | null; dew_c: number | null; feels_c: number | null; rain_pct: number | null
  code: number | null; summary: string; wind_kmh: number | null; gust_kmh: number | null; aqi: number | null; day: boolean
}
export type WxDay = { date: string; hi_c: number | null; lo_c: number | null; rain_pct: number | null; code: number | null; summary: string; sunrise: string | null; sunset: string | null }
export type WxBadge = 'heat' | 'cold' | 'wind' | 'altitude' | 'storm' | 'ice' | 'rain' | 'air'
export type WxAdjust = { pct: number; badges: WxBadge[]; reasons: string[]; safety: string[]; pace: [number, number] | null; note: string }
export type NextDays = {
  units: 'imperial' | 'metric'; place: string | null; available: boolean; today: string; has_plan: boolean
  days: { date: string; weather: WxDay | null; sessions: { id: string; title: string; sport: string; minutes: number | null; time: string | null; badges: WxBadge[]; pct: number }[] }[]
}
export type SessionWeather =
  | { available: false; reason: 'range' | 'unreachable'; date: string; units: string }
  | {
    available: true; date: string; units: string; place: string | null; elevation_m: number | null; planned_time: string | null
    strip: WxHour[]; day: WxDay | null; adjust: WxAdjust; planned_pace: { fast: number; slow: number } | null
    best: { start: string; end: string; why: string; better: boolean } | null
  }

const TTL = 15 * 60_000
let nextCache: { at: number; p: Promise<NextDays> } | null = null
/** Today + 2 days with weather and planned sessions; cached 15 min (call fresh after plan edits). */
export function getNextDays(fresh = false): Promise<NextDays> {
  if (!fresh && nextCache && Date.now() - nextCache.at < TTL) return nextCache.p
  const p = getJSON<NextDays>('/api/weather/next')
  nextCache = { at: Date.now(), p }
  p.catch(() => { nextCache = null })
  return p
}
export const getSessionWeather = (sessionId: string) =>
  getJSON<SessionWeather>(`/api/weather/session?session_id=${encodeURIComponent(sessionId)}`)

export const fmtTemp = (c: number | null | undefined, imperial: boolean) =>
  c == null ? '' : imperial ? `${Math.round(c * 9 / 5 + 32)}°` : `${Math.round(c)}°`
export const fmtWind = (kmh: number | null | undefined, imperial: boolean) =>
  kmh == null ? '' : imperial ? `${Math.round(kmh / 1.609344)} mph` : `${Math.round(kmh)} km/h`
/** "6 AM", "13:00" by locale-ish preference: imperial users get 12-hour time. */
export function fmtHour(hhmm: string, imperial: boolean) {
  const h = Number(hhmm.slice(0, 2)), m = hhmm.slice(3, 5)
  if (!imperial) return hhmm.slice(0, 5)
  const h12 = h % 12 === 0 ? 12 : h % 12
  return `${h12}${m && m !== '00' ? `:${m}` : ''} ${h < 12 ? 'AM' : 'PM'}`
}

export function wxIcon(code: number | null | undefined): typeof Sun {
  if (code == null) return CloudSun
  if (code === 0 || code === 1) return Sun
  if (code === 2) return CloudSun
  if (code === 3) return Cloud
  if (code === 45 || code === 48) return CloudFog
  if (code >= 51 && code <= 57) return CloudDrizzle
  if ((code >= 61 && code <= 67) || (code >= 80 && code <= 82)) return CloudRain
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) return CloudSnow
  if (code >= 95) return CloudLightning
  return CloudSun
}

export const BADGE: Record<WxBadge, { label: string; icon: typeof Sun; warn: boolean }> = {
  heat: { label: 'Heat', icon: ThermometerSun, warn: true },
  cold: { label: 'Cold', icon: Snowflake, warn: false },
  wind: { label: 'Windy', icon: Wind, warn: false },
  altitude: { label: 'Altitude', icon: Mountain, warn: false },
  storm: { label: 'Storms', icon: CloudLightning, warn: true },
  ice: { label: 'Icy', icon: Snowflake, warn: true },
  rain: { label: 'Rain', icon: Umbrella, warn: false },
  air: { label: 'Air quality', icon: Haze, warn: true },
}
