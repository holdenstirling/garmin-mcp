// "New version of Rabbit · Update": shown when lib/appUpdate finds a newer deploy while the app
// is open. One tap reloads (drafts and unsent saves stay on the device).
import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { UPDATE_READY_EVENT, isUpdateReady, reloadNow, startUpdateChecks } from '@/lib/appUpdate'

export function UpdatePill() {
  const [show, setShow] = useState(isUpdateReady)
  useEffect(() => {
    startUpdateChecks()
    const on = () => setShow(true)
    window.addEventListener(UPDATE_READY_EVENT, on)
    return () => window.removeEventListener(UPDATE_READY_EVENT, on)
  }, [])
  if (!show) return null
  return (
    <div role="status" className="pointer-events-none fixed inset-x-0 top-[max(8px,env(safe-area-inset-top))] z-[90] flex justify-center px-4">
      <button type="button" onClick={reloadNow}
        className="pointer-events-auto flex min-h-11 items-center gap-2 rounded-full bg-(--accent) px-4 text-[0.8235rem] font-semibold text-(--on-fill) shadow-lg active:opacity-80">
        <RefreshCw className="size-4" aria-hidden /> New version of rabbt · Update
      </button>
    </div>
  )
}
