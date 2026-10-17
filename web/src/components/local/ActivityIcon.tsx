// One icon per activity (lib/activity), used for every club, league, meetup, partner, event,
// search result and map pin in Local and Schedule, so a volleyball league always shows a
// volleyball and a group ride always shows a bike.
import { Bike, CircleDot, Dribbble, Flower2, Footprints, Goal, Layers, Mountain, MountainSnow, Users, Volleyball, Waves } from 'lucide-react'
import type { ActivityId } from '@/lib/activity'
import { cn } from '@/lib/utils'

export const ACTIVITY_ICON: Record<ActivityId, typeof Bike> = {
  run: Footprints, trail: Mountain, ride: Bike, swim: Waves, tri: Layers, volleyball: Volleyball,
  pickleball: CircleDot, soccer: Goal, basketball: Dribbble, climbing: MountainSnow, yoga: Flower2, other: Users,
}

/** The activity's icon in the app's rounded tile (decorative: the name says what it is). */
export function ActivityTile({ activity, size = 40, className }: { activity: ActivityId | null | undefined; size?: number; className?: string }) {
  const Icon = ACTIVITY_ICON[activity ?? 'other'] ?? Users
  return (
    <span aria-hidden style={{ width: size, height: size }}
      className={cn('flex shrink-0 items-center justify-center rounded-xl bg-(--accent-subtle) text-(--accent)', className)}>
      <Icon style={{ width: size / 2, height: size / 2 }} />
    </span>
  )
}
