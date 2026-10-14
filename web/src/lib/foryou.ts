// Explore "For you": personal race picks from the athlete's interests ("What are you into?").
// Interests live on the athlete profile (PUT /api/athlete {interests}); the feed is
// GET /api/explore/foryou and the weekly bucket-list web search is POST /api/explore/foryou/bucket.
import { getJSON, sendJSON } from '@/lib/api'
import type { ExploreRace, HintTone } from '@/lib/explore'
import type { Estimate, ResolvedLocation } from '@/lib/explore2'

export type RaceType =
  | 'road' | 'trail' | 'ultra' | 'triathlon' | 'duathlon' | 'gravel' | 'road_cycling' | 'mtb' | 'swim'
  | 'hike' | 'obstacle' | 'adventure'
export type InterestDistance =
  | '5k' | '10k' | 'half' | 'marathon' | 'ultra_50k' | 'ultra_100k_plus' | 'sprint' | 'olympic' | '70.3' | '140.6' | 'century'
export type Vibe = 'competitive' | 'scenic' | 'fun_social' | 'charity' | 'bucket_list' | 'low_key'
export type Goal12 = 'first_race' | 'pr' | 'first_ultra' | 'qualify' | 'stay_fit' | 'try_new_sport' | 'travel_race'
export type Travel = 'local' | 'regional' | 'anywhere'

export type Interests = {
  race_types?: RaceType[]; distances?: InterestDistance[]; travel?: Travel
  race_vibe?: Vibe[]; goals_next_12mo?: Goal12[]; months_avoid?: number[]; home_zip?: string
}

export const RACE_TYPES: [RaceType, string, string][] = [
  ['road', 'Road running', '🏃'], ['trail', 'Trail running', '⛰️'], ['ultra', 'Ultras', '🦄'],
  ['triathlon', 'Triathlon', '🏊'], ['duathlon', 'Duathlon', '🔁'], ['gravel', 'Gravel', '🪨'],
  ['road_cycling', 'Road cycling', '🚴'], ['mtb', 'Mountain bike', '🚵'], ['swim', 'Open water', '🌊'],
  ['hike', 'Hiking', '🥾'], ['obstacle', 'Obstacle', '🧗'], ['adventure', 'Adventure', '🧭'],
]
export const DISTANCES: [InterestDistance, string][] = [
  ['5k', '5K'], ['10k', '10K'], ['half', 'Half marathon'], ['marathon', 'Marathon'], ['ultra_50k', '50K-ish ultra'],
  ['ultra_100k_plus', '100K+'], ['sprint', 'Sprint tri'], ['olympic', 'Olympic tri'], ['70.3', '70.3'],
  ['140.6', '140.6'], ['century', 'Century ride'],
]
export const VIBES: [Vibe, string, string][] = [
  ['competitive', 'Competitive', '🏆'], ['scenic', 'Scenic', '🏔️'], ['fun_social', 'Fun & social', '🎉'],
  ['charity', 'Charity', '💚'], ['bucket_list', 'Bucket list', '✨'], ['low_key', 'Low-key', '🌿'],
]
export const GOALS: [Goal12, string][] = [
  ['first_race', 'First race'], ['pr', 'Set a PR'], ['first_ultra', 'First ultra'], ['qualify', 'Qualify'],
  ['stay_fit', 'Stay fit'], ['try_new_sport', 'Try a new sport'], ['travel_race', 'Race somewhere new'],
]
export const TRAVEL: [Travel, string, string][] = [
  ['local', 'Close to home', 'Within about 50 miles'],
  ['regional', 'Road trip', 'Within about 250 miles'],
  ['anywhere', 'Anywhere', "I'll travel for the right race"],
]
export const MONTH_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export const hasInterests = (i: Interests | null | undefined) => !!i && Object.keys(i).length > 0

/** "Trail · Ultras · Half marathon · Road trip" (first few picks) */
export function interestsSummary(i: Interests | null | undefined, max = 4): string[] {
  if (!i) return []
  const lbl = <T extends string>(list: [T, string, ...string[]][], v: T) => list.find((x) => x[0] === v)?.[1] ?? v
  const out = [
    ...(i.race_types ?? []).map((t) => lbl(RACE_TYPES, t)),
    ...(i.distances ?? []).map((d) => lbl(DISTANCES, d)),
    ...(i.race_vibe ?? []).map((v) => lbl(VIBES, v)),
    ...(i.travel ? [lbl(TRAVEL, i.travel)] : []),
  ]
  return out.length > max ? [...out.slice(0, max), `+${out.length - max}`] : out
}

export type ForYouRace = ExploreRace & {
  why?: string; fit?: { label: string; tone: HintTone }; score?: number; reasons?: string[]; friends?: string[]
  estimate?: Estimate; check_dates?: boolean; usual_month?: number; popular?: boolean
}
export type ForYouSection = {
  id: 'picks' | 'tuneups' | 'near' | 'friends' | 'bucket' | 'popular'; title: string; note?: string; source?: 'web' | 'curated'
  races: ForYouRace[]
}
export type ForYouFeed = {
  interests: Interests; has_interests: boolean; sections: ForYouSection[]
  partial: boolean; failed: boolean; zip: string; radius: number
  /** Explore v2: interests were guessed from training (none set), the ones used, and where we searched. */
  inferred?: boolean; effective?: Interests; location?: ResolvedLocation
  bucket: { eligible: boolean; due: boolean }
}

export const getForYou = (fresh = false) => getJSON<ForYouFeed>(`/api/explore/foryou${fresh ? '?fresh=1' : ''}`)
export const fetchBucket = () => sendJSON<{ section: ForYouSection }>('POST', '/api/explore/foryou/bucket')
export const saveInterests = (interests: Interests) =>
  sendJSON<{ interests?: Interests }>('PUT', '/api/athlete', { interests })
