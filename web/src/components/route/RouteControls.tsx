// Under my own route map (a workout's page): the one-time "Share your maps?" question (maps are
// mine only until I say yes), and "Hide routes that start near here" (a hidden area set from this
// workout's start, which the server keeps and never sends back). Settings: Feed -> Sharing.
import { useEffect, useState } from 'react'
import { EyeOff, MapPin } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { getCommunitySettings, HOME_RADIUS_CHOICES, putCommunitySettings, type CommunitySettings } from '@/lib/community'
import { cn } from '@/lib/utils'

const dist = (m: number) => (m >= 1000 ? `${(m / 1000).toLocaleString()} km` : `${m} m`)

export function RouteControls({ postId }: { postId: string | null }) {
  const [s, setS] = useState<CommunitySettings | null>(null)
  const [picking, setPicking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    getCommunitySettings().then((r) => { if (live) setS(r.settings) }, () => {})
    return () => { live = false }
  }, [])
  if (!s) return null

  async function put(patch: Partial<CommunitySettings> | Record<string, unknown>) {
    setBusy(true); setErr(null)
    try { setS((await putCommunitySettings(patch as Partial<CommunitySettings>)).settings); setPicking(false) }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  const trim = s.routes_trim_m ?? 200
  return (
    <div className="flex flex-col gap-2">
      {s.routes_share == null && (
        <div role="note" className="flex flex-col gap-2 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-3">
          <p className="m-0 text-body font-semibold text-(--text)">Show this map to friends?</p>
          <p className="m-0 text-small leading-snug text-(--text-secondary)">
            Right now only you see your maps. If you share them, friends see the line with the first and last {dist(trim)} cut off.
          </p>
          <div className="flex gap-2">
            <Button variant="primary" className="h-11 flex-1 text-body" loading={busy} onClick={() => void put({ routes_share: true })}>Share my maps</Button>
            <Button variant="ghost" className="h-11 px-3 text-body" disabled={busy} onClick={() => void put({ routes_share: false })}>Keep private</Button>
          </div>
        </div>
      )}
      {s.routes_home ? (
        <p className="m-0 flex items-start gap-2 px-1 text-small text-(--text-muted)">
          <EyeOff className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>Routes that start within {dist(s.routes_home.radius_m)} of your hidden spot are only shown to you.{' '}
            <button type="button" className="hit-44 font-medium text-(--accent)" disabled={busy} onClick={() => void put({ routes_home: null })}>Clear</button>
          </span>
        </p>
      ) : postId && !picking ? (
        <button type="button" onClick={() => setPicking(true)}
          className="flex min-h-11 items-center gap-2 self-start px-1 text-small font-medium text-(--accent)">
          <MapPin className="size-4" aria-hidden /> Hide routes that start near here
        </button>
      ) : null}
      {picking && postId && (
        <div className="flex flex-col gap-2 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-3">
          <p className="m-0 text-small text-(--text-secondary)">Routes starting within this distance of where this one started stay private to you, even when you share maps.</p>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Hidden area size">
            {HOME_RADIUS_CHOICES.map((r) => (
              <button key={r} type="button" disabled={busy} onClick={() => void put({ routes_home: { post_id: postId, radius_m: r } })}
                className={cn('plan-chip min-h-11')}>{dist(r)}</button>
            ))}
            <button type="button" className="min-h-11 px-2 text-small font-medium text-(--text-muted)" onClick={() => setPicking(false)}>Cancel</button>
          </div>
        </div>
      )}
      {err && <p className="m-0 px-1 text-meta text-(--danger)" role="alert">{err}</p>}
    </div>
  )
}
