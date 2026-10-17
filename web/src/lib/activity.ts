// What a local club, league, meetup or event is for (server: activity.py). One id per listing
// drives its icon (components/local/ActivityIcon) and the activity filter chips everywhere in
// Local and Schedule > Discover. Listings arrive classified; events are classified here from
// their own words with the same keywords (kept in step with activity.py).

export type ActivityId =
  | 'run' | 'trail' | 'ride' | 'swim' | 'tri' | 'volleyball' | 'pickleball' | 'soccer'
  | 'basketball' | 'climbing' | 'yoga' | 'other'

export const ACTIVITIES: readonly (readonly [ActivityId, string])[] = [
  ['run', 'Run'], ['trail', 'Trail'], ['ride', 'Ride'], ['swim', 'Swim'], ['tri', 'Tri'],
  ['volleyball', 'Volleyball'], ['pickleball', 'Pickleball'], ['soccer', 'Soccer'],
  ['basketball', 'Basketball'], ['climbing', 'Climbing'], ['yoga', 'Yoga'], ['other', 'Other'],
]
export const ACTIVITY_LABEL = Object.fromEntries(ACTIVITIES) as Record<ActivityId, string>
export const isActivity = (v: unknown): v is ActivityId => typeof v === 'string' && v in ACTIVITY_LABEL

/** Club | League | Meetup (server: activity.group_type). */
export type GroupType = 'club' | 'league' | 'meetup'

const WORDS: [ActivityId, RegExp][] = [
  ['tri', /triathlon|triathlete|\btri club|\btri team|\bduathlon|\baquathlon|\bbrick/i],
  ['volleyball', /volleyball|\bvolley\b/i],
  ['pickleball', /pickleball|pickle ball/i],
  ['soccer', /soccer|futsal|\bfootball club\b/i],
  ['basketball', /basketball|\bhoops\b/i],
  ['climbing', /\bclimbing\b|\bclimbers?\b|bouldering|boulder gym|\bcrag/i],
  ['yoga', /\byoga\b|pilates/i],
  ['swim', /\bswim|masters swim|open water|\bpool\b|aquatic/i],
  ['trail', /\btrail|ultra|mountain run|sky ?run|fell run|hik(?:e|ing)/i],
  ['ride', /cycl|\bbike|\bbicycl|\bride\b|\brides\b|gravel|\bmtb\b|velo|peloton|criterium|\bspin\b/i],
  ['run', /\brun|runner|running|jog|striders|harriers|\b5k\b|\b10k\b|marathon|track night|track club/i],
]
/** Event types (lib/events EventType) that already say the activity. */
const BY_TYPE: Record<string, ActivityId> = {
  running: 'run', trail: 'trail', cycling: 'ride', swimming: 'swim', triathlon: 'tri', duathlon: 'tri',
  mountaineering: 'climbing',
}

/** The activity of an event or anything with a name: its words first, then its type. */
export function classifyActivity(texts: (string | null | undefined)[], type?: string | null): ActivityId {
  for (const t of texts) {
    if (!t) continue
    for (const [id, rx] of WORDS) if (rx.test(t)) return id
  }
  return (type && BY_TYPE[type]) || 'other'
}

/** Miles -> the athlete's units for the radius label ("10 mi" / "16 km"). */
export function radiusLabel(mi: number, imperial: boolean): string {
  return imperial ? `${mi} mi` : `${Math.round(mi * 1.609344)} km`
}

/** "0.4 mi" / "1 km" / "in your city" (no mapped spot). */
export function distanceLabel(km: number | null | undefined, imperial: boolean): string {
  if (km == null) return 'In your city'
  const v = imperial ? km / 1.609344 : km
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${imperial ? 'mi' : 'km'} away`
}
