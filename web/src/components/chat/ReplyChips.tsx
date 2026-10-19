// Chat helpers that keep replies easy to answer: quick-reply chips under Rabbit's latest
// message when it ends with a question, and the composer's rotating prompt.
import { useEffect, useState } from 'react'

/** Up to 3 short replies for a message that ends with a question; [] otherwise.
 *  Simple, safe patterns only: the chip text is sent as the athlete's own message. */
export function replyChips(text: string): string[] {
  const plain = text.replace(/[*_`#>]+/g, '').trim()
  if (!plain.endsWith('?')) return []
  const cut = Math.max(plain.lastIndexOf('. '), plain.lastIndexOf('! '), plain.lastIndexOf('\n'), plain.slice(0, -1).lastIndexOf('? '))
  const last = plain.slice(cut + 1).trim().toLowerCase()
  if (/full breakdown|break it down|more detail/.test(last)) return ['Yes, break it down', 'Not now']
  if (/how (did|does|do|are|is) .*(feel|legs|going)/.test(last)) return ['Felt great', 'Tough', 'Not sure']
  if (/^(want me to|do you want me to|would you like me to|should i|shall i|can i|ready to|sound good|does that work)\b/.test(last)
    || /\b(want me to|should i|shall i|sound good|does that work)\b/.test(last)) return ['Yes, please', 'Not now']
  return []
}

export function ReplyChips({ chips, onPick, disabled }: { chips: string[]; onPick: (t: string) => void; disabled?: boolean }) {
  if (!chips.length) return null
  return (
    <div className="-mt-2 flex flex-wrap gap-1.5 pl-1" role="group" aria-label="Quick replies">
      {chips.slice(0, 3).map((c) => (
        <button key={c} type="button" disabled={disabled} onClick={() => onPick(c)}
          className="inline-flex min-h-11 items-center rounded-full disabled:opacity-50">
          <span className="rounded-full border border-(--accent)/40 bg-(--accent-subtle) px-3 py-1.5 text-[0.7647rem] font-medium text-(--accent) active:opacity-70">
            {c}
          </span>
        </button>
      ))}
    </div>
  )
}

export const COMPOSER_PROMPTS = ['Ask rabbt anything…', 'How should I fuel my long run?', 'Am I ready for intervals today?']

/** The composer's idle placeholder, gently rotating every 8 s (only while ``on``). */
export function useRotatingPrompt(on: boolean, prompts: string[] = COMPOSER_PROMPTS): string {
  const [i, setI] = useState(0)
  useEffect(() => {
    if (!on) return
    const t = window.setInterval(() => setI((n) => (n + 1) % prompts.length), 8000)
    return () => window.clearInterval(t)
  }, [on, prompts.length])
  return prompts[i % prompts.length]!
}
