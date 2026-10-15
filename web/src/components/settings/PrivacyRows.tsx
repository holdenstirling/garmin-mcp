// Settings -> "Feel & privacy": vibrate on success (this device; lib/haptics) and "Don't count
// my usage" (account; usage.py drops everything, lib/usage stops sending).
import { useState } from 'react'
import { ChartColumn, Vibrate } from 'lucide-react'
import { Group, Icon, Row, Switch } from '@/components/settings/Grouped'
import { putSettings, type Me } from '@/lib/api'
import { haptic, hapticsEnabled, hapticsSupported, setHapticsEnabled } from '@/lib/haptics'
import { setUsageOff } from '@/lib/usage'

export function PrivacyRows({ me, onChange }: { me: Me; onChange: () => void }) {
  const [buzz, setBuzz] = useState(hapticsEnabled)
  const [off, setOff] = useState(me.settings.usage_off === true)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const dnt = typeof navigator !== 'undefined'
    && ((navigator as Navigator & { globalPrivacyControl?: boolean }).globalPrivacyControl === true || navigator.doNotTrack === '1')

  async function toggleUsage(v: boolean) {
    setBusy(true); setErr(null); setOff(v); setUsageOff(v)
    try { await putSettings({ usage_off: v }); onChange() }
    catch (e) { setOff(!v); setUsageOff(!v); setErr((e as Error).message) }
    finally { setBusy(false) }
  }

  return (
    <Group label="Feel & privacy" footer={err ?? (dnt
      ? 'Your browser asks sites not to track you, so nothing is counted on this device.'
      : 'Rabbit counts a few anonymous taps (never health data, text or location) to see what helps. See the privacy policy.')}>
      {hapticsSupported() && (
        <Row icon={<Icon><Vibrate /></Icon>} title="Vibrate on success" subtitle="A light tap when something saves or sends"
          trailing={<Switch label="Vibrate on success" checked={buzz}
            onChange={(v) => { setHapticsEnabled(v); setBuzz(v); if (v) haptic() }} />} />
      )}
      <Row icon={<Icon tone="muted"><ChartColumn /></Icon>} title="Don't count my usage" subtitle="Stop the anonymous usage counts"
        trailing={<Switch label="Don't count my usage" checked={off} disabled={busy} onChange={(v) => void toggleUsage(v)} />} />
    </Group>
  )
}
