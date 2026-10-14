// PullToRefresh: touch only. Put it first inside a scrolling container's content. Pulling down
// at the top reveals the rabbit crouching; let go past the line and it leaps and onRefresh()
// runs. Listeners are passive (scrolling is never blocked); the pull is drawn with transforms
// set directly on the element, so dragging never re-renders React. The rabbit is drawn in a
// fixed window over the top of the scroller (portaled to <body>), so it takes no layout space.
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { RabbitLogo } from '@/components/RabbitLogo'
import { cn } from '@/lib/utils'
import { Puff } from './shapes'

const READY = 64 // px of (damped) pull that triggers a refresh
const MAX = 96

function scrollParent(el: HTMLElement | null): HTMLElement | null {
  for (let p = el?.parentElement ?? null; p; p = p.parentElement) {
    const o = getComputedStyle(p).overflowY
    if (o === 'auto' || o === 'scroll') return p
  }
  return null
}

export function PullToRefresh({ onRefresh, disabled }: { onRefresh: () => void; disabled?: boolean }) {
  const anchor = useRef<HTMLSpanElement>(null)
  const bunny = useRef<HTMLSpanElement>(null)
  const win = useRef<HTMLSpanElement>(null)
  const [phase, setPhase] = useState<'idle' | 'pull' | 'ready' | 'leap'>('idle')
  const phaseRef = useRef(phase)
  phaseRef.current = phase
  const cb = useRef(onRefresh)
  cb.current = onRefresh

  useEffect(() => {
    if (disabled) return
    const sc = scrollParent(anchor.current)
    if (!sc) return
    let startY: number | null = null
    let pull = 0
    const draw = (px: number) => {
      const b = bunny.current
      if (!b) return
      b.style.transition = 'none'
      b.style.opacity = String(Math.min(1, px / 28))
      b.style.transform = `translate3d(-50%, ${Math.round(px - 40)}px, 0)`
    }
    const reset = () => {
      const b = bunny.current
      if (b) { b.style.transition = ''; b.style.opacity = '0'; b.style.transform = 'translate3d(-50%, -40px, 0)' }
    }
    const start = (e: TouchEvent) => {
      if (phaseRef.current === 'leap' || e.touches.length !== 1 || sc.scrollTop > 0) { startY = null; return }
      startY = e.touches[0]!.clientY; pull = 0
      const r = sc.getBoundingClientRect(), w = win.current
      if (w) { w.style.top = `${r.top}px`; w.style.left = `${r.left}px`; w.style.width = `${r.width}px` }
    }
    const move = (e: TouchEvent) => {
      if (startY == null) return
      const dy = e.touches[0]!.clientY - startY
      if (dy <= 0 || sc.scrollTop > 0) { if (pull) { pull = 0; reset(); setPhase('idle') } return }
      pull = Math.min(MAX, dy * 0.5)
      draw(pull)
      const next = pull >= READY ? 'ready' : 'pull'
      if (next !== phaseRef.current) setPhase(next)
    }
    const end = () => {
      if (startY == null) return
      startY = null
      if (pull >= READY) {
        setPhase('leap')
        const b = bunny.current
        if (b) { b.style.transition = ''; b.style.transform = '' } // the leap keyframes take over
        try { cb.current() } catch { /* the screen shows its own errors */ }
        window.setTimeout(() => { setPhase('idle'); reset() }, 750)
      } else { reset(); if (pull) setPhase('idle') }
      pull = 0
    }
    sc.addEventListener('touchstart', start, { passive: true })
    sc.addEventListener('touchmove', move, { passive: true })
    sc.addEventListener('touchend', end, { passive: true })
    sc.addEventListener('touchcancel', end, { passive: true })
    return () => {
      sc.removeEventListener('touchstart', start)
      sc.removeEventListener('touchmove', move)
      sc.removeEventListener('touchend', end)
      sc.removeEventListener('touchcancel', end)
    }
  }, [disabled])

  const layer = (
    <span ref={win} className={cn('fx-ptr', phase !== 'idle' && 'is-on')} aria-hidden="true">
      <span ref={bunny} className={cn('fx-ptr__bunny', phase === 'ready' && 'is-ready', phase === 'leap' && 'is-leap')}>
        <span className="fx-ptr__crouch"><RabbitLogo size={30} /></span>
        {phase === 'leap' && <Puff size={16} className="fx-ptr__puff" />}
      </span>
    </span>
  )
  return (
    <>
      <span ref={anchor} hidden />
      {typeof document !== 'undefined' && createPortal(layer, document.body)}
    </>
  )
}
