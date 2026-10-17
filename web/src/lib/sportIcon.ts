// One icon per sport, everywhere in the app. Every screen that shows a workout, activity, plan
// day or feed post picks its icon here, so a run is always the same footprints and a hike is
// always the same mountain. Accepts plan sports ("run"), Garmin/Strava-style names ("Ride",
// "trail_running", "Open Water Swim") and free text, case-insensitive.
import {
  Activity, Bike, Dumbbell, Flag, Footprints, Layers, Moon, Mountain, Ship, Snowflake, Waves,
  type LucideIcon,
} from 'lucide-react'

const EXACT: Record<string, LucideIcon> = {
  run: Footprints, walk: Footprints, bike: Bike, ride: Bike, swim: Waves, brick: Layers,
  strength: Dumbbell, rest: Moon, race: Flag, hike: Mountain, climb: Mountain, ski: Snowflake,
  paddle: Ship, other: Activity,
}

const RULES: [RegExp, LucideIcon][] = [
  [/brick|multisport|triathlon/, Layers],
  [/swim|pool|open.?water/, Waves],
  [/bik|cycl|ride|spin|gravel|mtb/, Bike],
  [/hik|climb|boulder|mountaineer/, Mountain],
  [/ski|snowboard|snowshoe/, Snowflake],
  [/row|paddle|kayak|canoe|sup\b/, Ship],
  [/strength|weight|gym|lift|core|pilates|yoga/, Dumbbell],
  [/run|jog|walk|track/, Footprints],
  [/rest|off\b|recovery day/, Moon],
  [/race/, Flag],
]

export function sportIcon(sport: string | null | undefined): LucideIcon {
  const s = (sport ?? '').trim().toLowerCase()
  if (!s) return Activity
  if (s in EXACT) return EXACT[s]
  for (const [re, icon] of RULES) if (re.test(s)) return icon
  return Activity
}
