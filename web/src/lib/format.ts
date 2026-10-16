// One place for units and number formatting, so every screen says the same thing the same way.

export const KM_PER_MI = 1.609344
export const FT_PER_M = 3.28084
export const YD_PER_M = 1.0936133

type DistOpts = { decimals?: number }

/** Distance from km in the athlete's units. Swims read in m/yd. Default: 1 decimal under 100, whole above. */
export function fmtDist(km: number, imperial: boolean, sport?: string | null, opts: DistOpts = {}): string {
  if (sport === 'swim') {
    const v = imperial ? km * 1000 * YD_PER_M : km * 1000
    return `${Math.round(v).toLocaleString()} ${imperial ? 'yd' : 'm'}`
  }
  const v = imperial ? km / KM_PER_MI : km
  const d = opts.decimals ?? (v >= 100 ? 0 : 1)
  const s = d === 0 ? Math.round(v).toLocaleString() : v.toFixed(d)
  return `${s} ${imperial ? 'mi' : 'km'}`
}

/** Meters (e.g. a planned swim) shown in the athlete's units. */
export function fmtMeters(m: number, imperial: boolean): string {
  return imperial ? `${Math.round(m * YD_PER_M).toLocaleString()} yd` : `${Math.round(m).toLocaleString()} m`
}

/** Climb in m or ft. */
export function fmtClimb(m: number, imperial: boolean): string {
  return imperial ? `${Math.round(m * FT_PER_M).toLocaleString()} ft` : `${Math.round(m).toLocaleString()} m`
}

/** "45 min" under an hour, "1h 05m" above, "2h" on the hour. */
export function fmtDuration(minutes: number | null | undefined): string {
  if (minutes == null || !Number.isFinite(minutes)) return ''
  const t = Math.round(minutes)
  if (t < 60) return `${t} min`
  const h = Math.floor(t / 60), m = t % 60
  return m ? `${h}h ${String(m).padStart(2, '0')}m` : `${h}h`
}

/** Wind speed from km/h. */
export function fmtSpeed(kmh: number, imperial: boolean): string {
  return imperial ? `${Math.round(kmh / KM_PER_MI)} mph` : `${Math.round(kmh)} km/h`
}

/** A pace from seconds per km in the athlete's units: "7:04/mi" | "4:23/km" (`unit: false` drops the unit). */
export function fmtPaceKm(secPerKm: number, imperial: boolean, unit = true): string {
  const s = Math.round(secPerKm * (imperial ? KM_PER_MI : 1))
  const t = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
  return unit ? `${t}/${imperial ? 'mi' : 'km'}` : t
}

/** Swim pace from seconds per 100 m: "1:45/100m". */
export function fmtSwimPace(secPer100m: number, unit = true): string {
  const s = Math.round(secPer100m)
  const t = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
  return unit ? `${t}/100m` : t
}
