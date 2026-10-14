// StreakFlame: the streak's flame icon. When the streak went up since it was last shown, it
// does one "carrot-flame" flicker (a carrot-orange flame flares over it and a tiny carrot pops
// up). At risk today: a slow, gentle pulse. Nothing with reduced motion.
import { useState } from 'react'
import { Flame } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Carrot } from './shapes'
import { reducedMotion, swapNumber } from './motion'

// Several flames can show the same streak (home strip, Progress): the first one to notice the
// rise lets the others mounting soon after flicker too.
let flicker: { streak: number; at: number } | null = null

function shouldFlicker(streak: number): boolean {
  if (streak <= 0 || reducedMotion()) return false
  if (flicker && flicker.streak === streak && Date.now() - flicker.at < 15_000) return true
  const prev = swapNumber('streak', streak)
  if (prev != null && streak > prev) { flicker = { streak, at: Date.now() }; return true }
  return false
}

/** ``replay`` changes (dev Motion lab) force one flicker. */
export function StreakFlame({ streak, atRisk, className, replay }: {
  streak: number; atRisk?: boolean; className?: string; replay?: number
}) {
  const [on] = useState(() => shouldFlicker(streak))
  const play = on || !!replay
  return (
    <span key={replay} className={cn('fx-flame', atRisk && 'fx-flame--risk', play && 'fx-flame--flicker')}>
      <Flame className={className} />
      {play && <>
        <Flame className={cn(className, 'fx-flame__hot')} aria-hidden />
        <Carrot size={10} className="fx-flame__carrot" />
      </>}
    </span>
  )
}
