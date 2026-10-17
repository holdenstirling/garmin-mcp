// Renders lib/confirm's in-app confirm dialogs (one at a time). Mounted once in App.tsx.
import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { CONFIRM_EVENT, type ConfirmReq } from '@/lib/confirm'

export function ConfirmHost() {
  const [req, setReq] = useState<ConfirmReq | null>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const back = useRef<HTMLElement | null>(null)

  useEffect(() => {
    const on = (e: Event) => {
      e.preventDefault()  // tells confirmAsk a host took it
      back.current = document.activeElement as HTMLElement | null
      setReq((e as CustomEvent<ConfirmReq>).detail)
    }
    window.addEventListener(CONFIRM_EVENT, on)
    return () => window.removeEventListener(CONFIRM_EVENT, on)
  }, [])
  useEffect(() => { if (req) setTimeout(() => cancelRef.current?.focus(), 0) }, [req])

  if (!req) return null
  const done = (ok: boolean) => {
    req.resolve(ok)
    setReq(null)
    try { back.current?.focus() } catch { /* gone */ }
  }
  return (
    <div className="fixed inset-0 z-[95] flex items-end justify-center bg-black/40 p-4 pb-[max(16px,env(safe-area-inset-bottom))] sm:items-center"
      onClick={(e) => { if (e.target === e.currentTarget) done(false) }}>
      <div role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby={req.detail ? 'confirm-detail' : undefined}
        className="w-full max-w-sm rounded-2xl border border-(--border) bg-(--bg-surface) p-4 shadow-xl"
        onKeyDown={(e) => {
          if (e.key === 'Escape') { e.stopPropagation(); done(false) }
          if (e.key === 'Tab') {  // keep focus on the two buttons
            const btns = Array.from(e.currentTarget.querySelectorAll('button'))
            const i = btns.indexOf(document.activeElement as HTMLButtonElement)
            e.preventDefault()
            btns[(i + (e.shiftKey ? btns.length - 1 : 1)) % btns.length]?.focus()
          }
        }}>
        <p id="confirm-title" className="text-[0.9412rem] font-semibold leading-snug text-(--text)">{req.message}</p>
        {req.detail && <p id="confirm-detail" className="mt-1 text-[0.8235rem] leading-snug text-(--text-secondary)">{req.detail}</p>}
        <div className="mt-4 flex gap-2">
          <Button ref={cancelRef} variant="default" className="h-11 flex-1" onClick={() => done(false)}>{req.cancel ?? 'Cancel'}</Button>
          <Button variant={req.danger ? 'destructive' : 'primary'} className="h-11 flex-1" onClick={() => done(true)}>{req.confirm ?? 'OK'}</Button>
        </div>
      </div>
    </div>
  )
}
