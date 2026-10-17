import { useEffect, useState } from 'react'
import { UnitsGroup } from '@/components/settings/UnitsRow'
import { Bell, Compass, LogOut, Plug } from 'lucide-react'
import { Avatar } from '@/components/Avatar'
import { photoUrl } from '@/lib/photo'
import { Group, Icon, Row, Switch } from '@/components/settings/Grouped'
import { ShareRow } from '@/components/settings/ShareRow'
import { LocationRow } from '@/components/settings/LocationRow'
import { PrivacyRows } from '@/components/settings/PrivacyRows'
import { intentsOf, intentsSummary, openWelcome } from '@/lib/intent'
import { CoachingSettings } from '@/components/CoachingSettings'
import { signOut, type Me } from '@/lib/api'
import { disablePush, enablePush, isStandalone, pushSupported, sendTestPush, thisDeviceSubscribed } from '@/lib/push'

// "Garmin, Oura · 1 more to connect" for the Connected apps row.
function connectedLine(me: Me): string {
  const on = [me.garmin.connected && 'Garmin', me.oura.connected && 'Oura', me.calendar.connected && 'Google Calendar']
    .filter(Boolean) as string[]
  const avail = 1 + (me.oura.available ? 1 : 0) + (me.calendar.available ? 1 : 0)
  if (!on.length) return 'Connect Garmin, Oura or Google Calendar'
  const left = avail - on.length
  return `${on.join(', ')}${left > 0 ? ` · ${left} more to connect` : ''}`
}

// Settings sheet content: notifications, device checks, account. Integrations live on their
// own page (Me -> Connected apps); this sheet only links there (and closes first).
// Profile, plan, events, gear and people live in their tabs (Me, Plan, Events).
export function SettingsPanels({ me, onChange, onDevDone, onOpenConnections }: {
  me: Me
  onChange: () => void
  onDevDone: () => void
  onOpenConnections: () => void
}) {
  const [pushMsg, setPushMsg] = useState<string | null>(null)
  const [here, setHere] = useState<boolean | null>(null) // this device subscribed?
  useEffect(() => { void thisDeviceSubscribed().then(setHere) }, [me.push.subscriptions])

  async function onDisablePush() {
    setBusy(true)
    try { await disablePush(); setHere(false); setPushMsg(null); onChange() }
    catch (e) { setPushMsg((e as Error).message) } finally { setBusy(false) }
  }
  const [busy, setBusy] = useState(false)

  async function onEnablePush() {
    if (!me.push.public_key) return
    setBusy(true)
    try {
      const n = await enablePush(me.push.public_key)
      setHere(true)
      setPushMsg(n > 1 ? `On for ${n} devices.` : null)
      onChange()
    } catch (e) {
      setPushMsg((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function onTestPush() {
    setBusy(true)
    try {
      const r = await sendTestPush()
      setPushMsg(r.results.length
        ? (r.results.every((x) => x.status && x.status < 300) ? 'Test sent. It should arrive in a few seconds.'
          : r.results.map((x) => `${x.host}: ${x.status ?? 'error'}${x.removed ? ' (removed)' : ''}`).join(', '))
        : 'No devices subscribed.')
    } catch (e) {
      setPushMsg((e as Error).message)
    } finally {
      setBusy(false)
    }
  }


  const pushStatus = !me.push.available ? 'Not configured on the server.'
    : !pushSupported() ? (isStandalone() ? 'Not supported on this device.' : 'Open Rabbit from your Home Screen to turn these on.')
    : here ? `On for this device${me.push.subscriptions > 1 ? ` and ${me.push.subscriptions - 1} other` : ''}`
    : me.push.subscriptions ? `Off here, on for ${me.push.subscriptions} other device${me.push.subscriptions === 1 ? '' : 's'}` : 'Off'
  const canToggle = me.push.available && pushSupported() && here !== null

  return (
    <div className="settings flex flex-col gap-6">
      <Group label="Connected apps" footer="Connect, sync or disconnect your watch, ring and calendar.">
        <Row icon={<Icon><Plug /></Icon>} title="Connected apps"
          subtitle={connectedLine(me)} onClick={onOpenConnections} />
      </Group>

      {me.role === 'athlete' && (
        <Group label="Rabbit" footer="What you came for shows up first on Rabbit's home.">
          <Row icon={<Icon><Compass /></Icon>} title="How you use Rabbit" subtitle={intentsSummary(intentsOf(me))} onClick={openWelcome} />
        </Group>
      )}

      {me.garmin.connected && me.chat.available && (
        <CoachingSettings me={me} onChange={onChange} onDevDone={onDevDone} />
      )}

      <Group label="Share your plan" footer="Coaches see your plan, events and stats; your Rabbit chats stay private. Manage coaches under Me.">
        <ShareRow />
      </Group>

      {me.role === 'athlete' && <UnitsGroup me={me} onChange={onChange} />}

      <Group label="Location" footer="Used by Explore to find races and local activities near you."><LocationRow /></Group>

      <Group label="Notifications" footer={pushMsg ?? undefined}>
        <Row icon={<Icon><Bell /></Icon>} title="Notifications" subtitle={pushStatus}
          trailing={canToggle ? (
            <Switch label="Notifications on this device" checked={!!here} disabled={busy}
              onChange={(v) => void (v ? onEnablePush() : onDisablePush())} />
          ) : null} />
        {me.push.available && pushSupported() && me.push.subscriptions > 0 && (
          <Row title={<span className="text-(--accent)">Send a test notification</span>} disabled={busy}
            onClick={() => void onTestPush()} trailing={<span />} />
        )}
      </Group>

      <PrivacyRows me={me} onChange={onChange} />

      <Group label="Account">
        <Row icon={<Avatar name={me.profile.name || me.user_id} picture={me.profile.picture} photo={photoUrl(me.photo)} />}
          title={me.profile.name || me.user_id} subtitle="Signed in with Google" />
        <Row title={<span className="inline-flex items-center gap-1.5"><LogOut className="size-4" /> Sign out</span>}
          danger center onClick={() => void signOut().finally(onChange)} />
      </Group>
    </div>
  )
}
