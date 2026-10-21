// "Where do you run?" right inside an empty Near me (no navigation, no sheet): a city or zip
// field plus "Use my location". Saving announces the new area, so the screen fills in place.
import { useState } from 'react'
import { LocateFixed } from 'lucide-react'
import { RabbitNap } from '@/components/anim'
import { Button } from '@/components/ui/button'
import { inputCls } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import { savePlaceLocation, shareDeviceLocation } from '@/lib/explore2'
import { announceArea } from './AreaBar'

export function AreaInline({ title = 'Where do you run?', line = 'Your city or zip, and rabbt shows runs, clubs and meetups around you.', className }: {
  title?: string; line?: string; className?: string
}) {
  const [place, setPlace] = useState('')
  const [busy, setBusy] = useState<'type' | 'locate' | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const typed = place.trim()
  const ok = /^\d{5}$/.test(typed) || /,\s*[a-z]{2,}/i.test(typed)
  async function go(kind: 'type' | 'locate') {
    setBusy(kind); setErr(null)
    try { announceArea(kind === 'locate' ? await shareDeviceLocation() : await savePlaceLocation(place)) }
    catch (e) { setErr((e as Error).message || "Couldn't find that. Try a zip code.") }
    finally { setBusy(null) }
  }
  return (
    <section aria-label="Set your area" className={cn('flex flex-col items-center gap-3 rounded-2xl border border-(--border) bg-(--bg-surface) px-4 py-5 text-center', className)}>
      <RabbitNap size={48} mode="peek" />
      <div>
        <h2 className="m-0 text-lead font-semibold text-(--text)">{title}</h2>
        <p className="m-0 mt-1 text-small leading-snug text-(--text-secondary)">{line}</p>
      </div>
      <form className="flex w-full flex-col gap-2" onSubmit={(e) => { e.preventDefault(); if (ok) void go('type') }}>
        <label className="sr-only" htmlFor="area-inline">City and state, or zip code</label>
        <div className="flex gap-2">
          <input id="area-inline" className={cn(inputCls, 'min-w-0 flex-1')} placeholder="Denver, CO or 80204" value={place}
            autoComplete="address-level2" enterKeyHint="go" onChange={(e) => { setPlace(e.target.value.slice(0, 60)); setErr(null) }} />
          <Button type="submit" variant="primary" className="h-12 shrink-0 px-4 text-body" disabled={!ok} loading={busy === 'type'}>Show me</Button>
        </div>
        <Button type="button" variant="default" className="h-11 w-full gap-2 text-body" loading={busy === 'locate'} onClick={() => void go('locate')}>
          <LocateFixed className="size-5 text-(--accent)" aria-hidden /> Use my location
        </Button>
      </form>
      {typed && !ok && !err && <p className="m-0 text-small text-(--text-muted)">Add the state, like Denver, CO</p>}
      {err && <p className="m-0 text-small text-(--danger)" role="alert">{err}</p>}
      <p className="m-0 text-meta text-(--text-muted)">rabbt keeps only a rough spot, never your exact location.</p>
    </section>
  )
}
