// PullToRefresh: the rabbit loader for hooks/usePullToRefresh (gesture rules live there). Touch only. Put it first inside a scrolling container's content. Pulling down
// at the top reveals the rabbit crouching; let go past the line and it leaps and onRefresh()
// runs. If onRefresh returns a promise, the rabbit hops in place until it settles (max 10 s),
// then leaps away. Listeners are passive (scrolling is never blocked); the pull is drawn with transforms
// set directly on the element, so dragging never re-renders React. The rabbit is drawn in a
// fixed window over the top of the scroller (portaled to <body>), so it takes no layout space.
import { createPortal } from 'react-dom'
import { RabbitLogo } from '@/components/RabbitLogo'
import { cn } from '@/lib/utils'
import { usePullToRefresh } from '@/hooks/usePullToRefresh'
import { Puff } from './shapes'

export function PullToRefresh({ onRefresh, disabled }: { onRefresh: () => unknown; disabled?: boolean }) {
  const { anchor, bunny, win, phase } = usePullToRefresh(onRefresh, { disabled })
  const layer = (
    <span ref={win} className={cn('fx-ptr', phase !== 'idle' && 'is-on')} aria-hidden="true">
      <span ref={bunny} className={cn('fx-ptr__bunny', phase === 'ready' && 'is-ready', phase === 'busy' && 'is-busy', phase === 'leap' && 'is-leap')}>
        <span className="fx-ptr__crouch"><RabbitLogo size={30} /></span>
        {phase === 'leap' && <Puff size={16} className="fx-ptr__puff" />}
      </span>
    </span>
  )
  return (
    <>
      <span ref={anchor} hidden />
      {phase === 'busy' && <span className="sr-only" role="status">Refreshing</span>}
      {typeof document !== 'undefined' && createPortal(layer, document.body)}
    </>
  )
}
