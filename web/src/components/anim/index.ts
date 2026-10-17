// Rabbit's animation kit: the one import for motion. Styles: styles/rabbit.css (.rb-*) and
// styles/fx.css (.fx-*, the burst/flame/pull-to-refresh layer in components/fx).
// Rules: transform/opacity only; one-shots <= 600 ms (bursts and celebrations up to 1.2 s);
// never blocks taps; idle loops pause offscreen/hidden (useIdleLoop); everything is still or
// off under prefers-reduced-motion. Only the app's RabbitLogo artwork is used as a character.
export { HopIn, hopIn } from './HopIn'
export { CarrotBurst, burst } from './CarrotBurst'
export { RabbitHop } from './RabbitHop'
export { EmptyRabbit, RabbitNap, type RabbitPose } from './EmptyRabbit'
export { Shake } from './Shake'
export { CountUp, useCountUp } from './CountUp'
export { useIdleLoop } from './useIdleLoop'
export { PullToRefresh } from '@/components/fx/PullToRefresh'
export { StreakFlame } from '@/components/fx/StreakFlame'
export { celebrate, reducedMotion, type BurstKind } from '@/components/fx/motion'
export { hapticTap } from '@/lib/haptics'
