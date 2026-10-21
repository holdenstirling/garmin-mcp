// The gentle nudge on the Feed when friends' workouts show up but mine don't reach them:
// "Your friends can't see your workouts. Share them?" Share turns on "Share my workouts with
// friends" (an explicit yes, community.py `share_workouts`); Not now hides it on this device for
// two weeks. Only for people who haven't said no: an explicit "off" is respected, no nagging.
import { useEffect, useState } from 'react'
import { Share2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { MapShareAsk } from '@/components/community/MapShareAsk'
import { getCommunitySettings, putCommunitySettings, SHARE_CONSENT_LINE } from '@/lib/community'

const KEY = 'rabbt:share-nudge-dismissed'
const QUIET_MS = 14 * 86_400_000

function dismissedRecently(): boolean {
  try { const t = Number(localStorage.getItem(KEY) || 0); return t > 0 && Date.now() - t < QUIET_MS } catch { return false }
}

/** "Jesse wants to see your workouts" / "Jesse and 2 others..." / "Your friends can't see..." */
export function askLine(f?: { count: number; names: string[] }): string {
  if (!f || f.count < 1 || !f.names.length) return "Your friends can't see your workouts. Share them?"
  if (f.count === 1) return `${f.names[0]} wants to see your workouts. Share them?`
  const rest = f.count - 1
  return `${f.names[0]} and ${rest} other${rest > 1 ? 's' : ''} want to see your workouts. Share them?`
}

export function ShareNudge({ onShared, home = false }: { onShared?: () => void; home?: boolean }) {
  const [show, setShow] = useState(false)
  const [line, setLine] = useState(askLine())
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)
  useEffect(() => {
    if (dismissedRecently()) return
    let live = true
    getCommunitySettings().then((r) => {
      const s = r.settings
      // On Home, only when someone actually follows you (the Feed shows it either way).
      if (live && s.sharing_effective === false && s.sharing_source !== 'off' && (!home || (s.followers?.count ?? 0) > 0)) {
        setLine(askLine(s.followers)); setShow(true)
      }
    }, () => {})
    return () => { live = false }
  }, [])
  if (!show) return null

  function later() {
    try { localStorage.setItem(KEY, String(Date.now())) } catch { /* private mode: hides for this visit */ }
    setShow(false)
  }
  async function share() {
    setBusy(true)
    try { await putCommunitySettings({ share_workouts: true, share_prompted: true }); setDone(true); onShared?.() }
    catch { /* Me -> Share my workouts still works */ } finally { setBusy(false) }
  }
  if (done) {
    return (
      <div className="flex flex-col gap-2">
        <p role="status" className="m-0 rounded-xl border border-(--border) bg-(--accent-subtle) px-3.5 py-3 text-small font-medium text-(--text)">
          You're sharing. Your last few days are on the Feed, and new workouts follow after each sync.
        </p>
        <MapShareAsk />
      </div>
    )
  }
  return (
    <div role="note" className="flex items-start gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-3">
      <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-(--accent-subtle) text-(--accent)" aria-hidden>
        <Share2 className="size-5" />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <p className="m-0 text-body font-semibold leading-snug text-(--text)">{line}</p>
        <p className="m-0 text-small leading-snug text-(--text-secondary)">{SHARE_CONSENT_LINE}</p>
        <div className="flex gap-2">
          <Button variant="primary" className="h-11 px-4 text-body" loading={busy} onClick={() => void share()}>Share</Button>
          <Button variant="ghost" className="h-11 px-3 text-body" disabled={busy} onClick={later}>Not now</Button>
        </div>
      </div>
      <button type="button" aria-label="Dismiss" onClick={later} className="-mr-1.5 -mt-1 flex size-11 shrink-0 items-center justify-center text-(--text-muted)">
        <X className="size-5" aria-hidden />
      </button>
    </div>
  )
}
