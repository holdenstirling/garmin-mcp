// Where to look: a zip field and "Use my location". The browser is only asked after a tap
// on our own friendly pre-prompt (why we ask, what we keep), never on page load. The server
// rounds the coordinates (~1 km) and keeps only a coarse spot plus town/zip/state; a typed zip
// is saved the same way ("manual"). Never shared with friends, never sent to the AI.
import { useState } from 'react'
import { LocateFixed, MapPin, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { inputCls } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import { forgetLocation, saveZipLocation, shareDeviceLocation, type ResolvedLocation } from '@/lib/explore2'

/** The "Allow location" pre-prompt + the actual browser ask. */
function AllowLocation({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function allow() {
    setBusy(true); setError(null)
    try { await shareDeviceLocation(); onDone() } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <div className="flex flex-col gap-2 rounded-xl bg-(--bg-elevated) px-3 py-3">
      <p className="text-[0.8235rem] font-medium leading-snug text-(--text)">Allow location so Rabbit can find races, courts, tracks and group runs near you</p>
      <p className="text-[0.7059rem] leading-snug text-(--text-muted)">
        We keep only a rough spot (about a kilometer) and your town, state and zip, never your exact location.
        Rabbit's AI only ever sees your city and state, and friends never see it. Forget it any time.
      </p>
      <div className="flex gap-2">
        <Button variant="primary" className="h-11 flex-1 gap-1.5 text-[0.8235rem]" loading={busy} onClick={() => void allow()}>
          <LocateFixed className="size-4" /> Allow location
        </Button>
        <Button variant="ghost" className="h-11 px-4 text-[0.8235rem]" disabled={busy} onClick={onCancel}>Not now</Button>
      </div>
      {error && <p className="text-[0.7059rem] leading-snug text-(--danger)" role="alert">{error}</p>}
    </div>
  )
}

/** Inline ask when we don't know where the athlete is. */
export function LocationPrompt({ title = 'Where should Rabbit look?', onSaveZip, onChanged, className }: {
  title?: string
  onSaveZip?: (zip: string) => Promise<void>
  onChanged: () => void
  className?: string
}) {
  const [zip, setZip] = useState('')
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const valid = /^\d{5}$/.test(zip)
  const saveZip = onSaveZip ?? (async (z: string) => { await saveZipLocation(z) })
  async function save() {
    if (!valid) return
    setBusy(true); setError(null)
    try { await saveZip(zip); onChanged() } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <section className={cn('flex flex-col gap-2.5 rounded-2xl border border-dashed border-(--accent) bg-(--accent-subtle) px-3.5 py-3.5', className)}>
      <p className="flex items-center gap-1.5 text-[0.8824rem] font-medium text-(--text)"><MapPin className="size-4 text-(--accent)" />{title}</p>
      {asking ? <AllowLocation onDone={() => { setAsking(false); onChanged() }} onCancel={() => setAsking(false)} /> : (
        <>
          <Button variant="primary" className="h-11 gap-1.5 text-[0.8235rem]" onClick={() => setAsking(true)}>
            <LocateFixed className="size-4" /> Use my location
          </Button>
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void save() }}>
            <input className={cn(inputCls, 'h-11 min-w-0 flex-1')} value={zip} inputMode="numeric" autoComplete="postal-code"
              maxLength={5} placeholder="Or enter a zip code" aria-label="Zip code"
              onChange={(e) => setZip(e.target.value.replace(/\D/g, '').slice(0, 5))} />
            <Button type="submit" variant="default" className="h-11 px-4 text-[0.8235rem]" loading={busy} disabled={!valid}>Save</Button>
          </form>
        </>
      )}
      {error && <p className="text-[0.7059rem] text-(--danger)" role="alert">{error}</p>}
    </section>
  )
}

const SOURCE_LABEL: Record<string, string> = {
  device: 'from your location', manual: 'your zip', home_zip: 'your home zip', profile_zip: 'your profile', profile_city: 'your profile',
}

/** "Near Denver, CO · from your location" with Change / Forget my location. */
export function LocationLine({ loc, onChanged }: { loc: ResolvedLocation; onChanged: () => void }) {
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  if (!loc.label) return null
  async function forget() {
    setBusy(true)
    try { await forgetLocation(); onChanged() } catch { /* stays as is */ } finally { setBusy(false) }
  }
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1.5 px-1 text-[0.7059rem] text-(--text-muted)">
        <MapPin className="size-3.5 shrink-0" />
        <span className="min-w-0 flex-1 truncate">Near <span className="font-medium text-(--text-secondary)">{loc.label}</span>
          {loc.source && SOURCE_LABEL[loc.source] ? ` · ${SOURCE_LABEL[loc.source]}` : ''}</span>
        {loc.source === 'device' || loc.source === 'manual' ? (
          <button type="button" className="hit-44 inline-flex items-center gap-1 font-medium text-(--text-secondary)" disabled={busy}
            onClick={() => void forget()}><X className="size-3.5" /> Forget my location</button>
        ) : !asking && (
          <button type="button" className="hit-44 inline-flex items-center gap-1 font-medium text-(--accent)" onClick={() => setAsking(true)}>
            <LocateFixed className="size-3.5" /> Use my location
          </button>
        )}
      </div>
      {asking && <AllowLocation onDone={() => { setAsking(false); onChanged() }} onCancel={() => setAsking(false)} />}
    </div>
  )
}
