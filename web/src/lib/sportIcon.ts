// One icon per sport, everywhere in the app. Every screen that shows a workout, activity, plan
// day or feed post picks its icon here (usually through <SportTile>), so a run is always the
// same footprints and a hike is always the same mountain. Accepts plan sports ("run"),
// Garmin/Strava-style names ("Ride", "trail_running", "Open Water Swim"), sport families
// (lib/sportstats) and free text, case-insensitive.
import {
  Activity, Bike, Dumbbell, Flag, Flame, Flower2, Footprints, Layers, Moon, Mountain, MountainSnow,
  PersonStanding, Ship, Waves, type LucideIcon,
} from 'lucide-react'
import { sportFamily, type SportFamily } from './sportstats'

const BY_FAMILY: Record<SportFamily, LucideIcon> = {
  run: Footprints, walk: PersonStanding, hike: Mountain, ride: Bike, indoor_ride: Bike, swim: Waves,
  row: Ship, paddle: Ship, ski: MountainSnow, strength: Dumbbell, mind: Flower2, hiit: Flame,
  climb: Mountain, brick: Layers, other: Activity,
}

/** The tint a family's tile uses (``--sport-<tone>`` / ``--sport-<tone>-bg`` in globals.css). */
export type SportTone = 'run' | 'ride' | 'swim' | 'strength' | 'outdoor' | 'winter' | 'water' | 'other'
const TONE: Record<SportFamily, SportTone> = {
  run: 'run', walk: 'outdoor', hike: 'outdoor', climb: 'outdoor', ride: 'ride', indoor_ride: 'ride',
  swim: 'swim', row: 'water', paddle: 'water', ski: 'winter', strength: 'strength', mind: 'strength',
  hiit: 'strength', brick: 'run', other: 'other',
}

export function familyIcon(fam: SportFamily): LucideIcon { return BY_FAMILY[fam] ?? Activity }
export function familyTone(fam: SportFamily): SportTone { return TONE[fam] ?? 'other' }

/** The icon for a sport, a plan session, a Garmin type or free text (``kind``: Garmin's type,
 * when known, e.g. "indoor_cycling" or "yoga"). Rest days get the moon, races the flag. */
export function sportIcon(sport: string | null | undefined, kind?: string | null): LucideIcon {
  const s = (sport ?? '').trim().toLowerCase()
  if (s === 'rest' || /\boff\b|recovery day/.test(s)) return Moon
  if (s === 'race') return Flag
  return familyIcon(sportFamily(sport, kind))
}
