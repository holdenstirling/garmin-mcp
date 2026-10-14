// TodayFx: a tone-specific flourish on the Today card, the first time it's seen each day.
// go -> the rabbit sprints across with a dash line; easy -> the tone icon sways slowly;
// rest -> a curled-up rabbit with floating "z"s. Decorative; nothing with reduced motion.
import { useEffect, useState } from 'react'
import { RabbitLogo } from '@/components/RabbitLogo'
import { firstToday, reducedMotion } from './motion'

export type TodayFxTone = 'go' | 'easy' | 'rest'

/** True once per day for this card (also with ``replay`` from the dev Motion lab). */
export function useTodayFx(day: string, replay?: number): boolean {
  const [play, setPlay] = useState(false)
  useEffect(() => {
    if (reducedMotion()) return
    if (replay || firstToday('today', day)) setPlay(true)
  }, [day, replay])
  useEffect(() => {
    if (!play) return
    const t = window.setTimeout(() => setPlay(false), 1300)
    return () => window.clearTimeout(t)
  }, [play])
  return play
}

export function fxTone(tone: string): TodayFxTone | null {
  return tone === 'go' || tone === 'plan' || tone === 'race' ? 'go' : tone === 'easy' ? 'easy' : tone === 'rest' ? 'rest' : null
}

/** The overlay layer (go, rest). ``easy`` is a class on the tone icon: ``fx-sway``. */
export function TodayFx({ tone }: { tone: TodayFxTone }) {
  if (tone === 'easy') return null
  return (
    <span className="fx-today" aria-hidden="true">
      {tone === 'go' ? (
        <span className="fx-today__sprint">
          <span className="fx-today__dash" />
          <RabbitLogo size={22} />
        </span>
      ) : (
        <span className="fx-today__nap">
          <span className="fx-today__curl"><RabbitLogo size={20} /></span>
          <span className="fx-today__z" style={{ animationDelay: '0ms' }}>z</span>
          <span className="fx-today__z fx-today__z--2" style={{ animationDelay: '220ms' }}>z</span>
          <span className="fx-today__z fx-today__z--3" style={{ animationDelay: '440ms' }}>z</span>
        </span>
      )}
    </span>
  )
}
