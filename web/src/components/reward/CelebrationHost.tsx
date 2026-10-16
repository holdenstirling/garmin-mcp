// Mounted once on Rabbit home: shows unseen race / block celebrations (server: celebrate.py)
// one after another when nothing else is open (``ready``). Checks once per app open; the
// full-screen moment's code loads only when there is something to celebrate.
import { Suspense, lazy, useEffect, useRef, useState } from 'react'
import { getCelebrations, type Celebration } from '@/lib/trends'

const CelebrationScreen = lazy(() => import('./CelebrationScreen').then((m) => ({ default: m.CelebrationScreen })))

export function CelebrationHost({ ready }: { ready: boolean }) {
  const [queue, setQueue] = useState<Celebration[]>([])
  const [open, setOpen] = useState(false)
  const asked = useRef(false)
  useEffect(() => {
    if (!ready || asked.current) return
    asked.current = true
    getCelebrations().then((r) => setQueue(r.items), () => { /* offline or a coach account */ })
  }, [ready])
  useEffect(() => { if (ready && queue.length) setOpen(true) }, [ready, queue.length])
  const c = queue[0]
  if (!c || !open) return null
  return (
    <Suspense fallback={null}>
      <CelebrationScreen key={c.id} c={c} onClose={() => { setOpen(false); setQueue((q) => q.slice(1)) }} />
    </Suspense>
  )
}
