// A Rabbit moment in the log (moments.py): small Rabbit avatar, one line, time, action chips.
// New ones (arrived in the last couple of minutes, first time on screen) hop in once.
import { RabbitInline } from './RabbitText'
import { memo } from 'react'
import { HopIn } from '@/components/anim'
import { RabbitLogo } from '@/components/RabbitLogo'
import type { MomentAction, MomentItem } from '@/hooks/useCoach'

const shown = new Set<string>()
const FRESH_S = 120

function fmtTime(ts: number): string {
  const d = new Date(ts * 1000)
  const today = new Date()
  const sameDay = d.toDateString() === today.toDateString()
  const time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  return sameDay ? time : `${d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })} · ${time}`
}

export const MomentCard = memo(function MomentCard({ item, onAction, disabled }: {
  item: MomentItem
  onAction: (a: MomentAction) => void
  disabled?: boolean
}) {
  const fresh = !shown.has(item.id) && Date.now() / 1000 - item.ts < FRESH_S
  shown.add(item.id)
  return (
    <HopIn play={fresh} className="flex w-full max-w-[92%] items-start gap-2.5" role="article" aria-label="Update from Rabbit">
      <span className="logo-tile mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-[8px] bg-(--brand) shadow-sm" aria-hidden>
        <RabbitLogo size={22} />
      </span>
      <div className="rabbit-voice rabbit-voice--tail min-w-0 flex-1 px-3.5 py-2.5">
        <div className="flex items-baseline gap-1.5 text-[0.6471rem]">
          <span className="rabbit-voice__label">Rabbit</span>
          <span className="text-(--text-muted)">· {fmtTime(item.ts)}</span>
        </div>
        <p className="m-0 mt-0.5 text-[1rem] leading-[1.45] text-(--text)"><RabbitInline text={item.text} /></p>
        {item.actions.length > 0 && (
          <div className="-mx-1 mt-1 flex flex-wrap gap-1.5">
            {item.actions.map((a) => (
              <button key={`${a.id}-${a.label}`} type="button" disabled={disabled} onClick={() => onAction(a)}
                className="hit-44 inline-flex min-h-11 items-center rounded-full px-1 disabled:opacity-50">
                <span className="rounded-full border border-(--accent)/40 bg-(--bg-surface) px-3 py-1.5 text-[0.7059rem] font-medium text-(--accent) active:opacity-70">
                  {a.label}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </HopIn>
  )
})
