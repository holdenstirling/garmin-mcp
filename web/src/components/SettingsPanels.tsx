import { useEffect, useState } from 'react'
import { Bell, CalendarClock, CircleDot, Layers, LogOut, Watch } from 'lucide-react'
import { Avatar } from '@/components/Avatar'
import { photoUrl } from '@/lib/photo'
import { Group, Icon, Row, Switch } from '@/components/settings/Grouped'
import { ShareRow } from '@/components/settings/ShareRow'
import { DataSourcesSheet } from '@/components/settings/DataSourcesSheet'
import { defaultSources, sourcesSummary } from '@/lib/sources'
import { CoachingSettings } from '@/components/CoachingSettings'
import { ConnectGarmin } from '@/components/ConnectGarmin'
import { postJSON, signOut, type Me } from '@/lib/api'
import { CALENDAR_CONNECT_URL, disconnectCalendar } from '@/lib/calendar'
import { OURA_CONNECT_URL, disconnectOura } from '@/lib/oura'
import { disablePush, enablePush, isStandalone, pushSupported, sendTestPush, thisDeviceSubscribed } from '@/lib/push'

// Settings sheet content: Garmin connection, notifications, device checks, account.
// Profile, plan, events, gear and people live in their tabs (Me, Plan, Races).
export function SettingsPanels({ me, onChange, onDevDone, onToast }: {
  me: Me
  onChange: () => void
  onDevDone: () => void
  onToast?: (msg: string) => void
}) {
  const [sourcesOpen, setSourcesOpen] = useState(false)
  const [pushMsg, setPushMsg] = useState<string | null>(null)
  const [here, setHere] = useState<boolean | null>(null) // this device subscribed?
  useEffect(() => { void thisDeviceSubscribed().then(setHere) }, [me.push.subscriptions])

  async function onDisablePush() {
    setBusy(true)
    try { await disablePush(); setHere(false); setPushMsg(null); onChange() }
    catch (e) { setPushMsg((e as Error).message) } finally { setBusy(false) }
  }
  const [busy, setBusy] = useState(false)

  async function onDisconnect() {
    if (!window.confirm('Disconnect Garmin? Rabbit will stop seeing your training data until you connect again.')) return
    setBusy(true)
    try { await postJSON('/api/garmin/disconnect') } finally { setBusy(false); onChange() }
  }

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
      <Group label="Garmin"
        footer={me.garmin.connected ? 'Rabbit can read your activities, sleep and training data. It only adds workouts to your Garmin calendar when you sync a plan you built in Rabbit.' : undefined}>
        {me.garmin.connected ? (
          <>
            <Row icon={<Icon><Watch /></Icon>} title="Garmin Connect"
              trailing={<span className="flex items-center gap-1.5 text-[0.7647rem] text-(--accent)">
                <span className="size-2 rounded-full bg-(--accent)" />Connected</span>} />
            <Row title="Disconnect Garmin" danger disabled={busy} center onClick={() => void onDisconnect()} />
          </>
        ) : me.garmin.can_connect ? (
          <div className="p-4">
            <p className="mb-3 text-[0.8235rem] text-(--text-secondary)">Connect your Garmin account so Rabbit can see your training.</p>
            <ConnectGarmin cooldownUntil={me.garmin.cooldown_until} onConnected={onChange} />
          </div>
        ) : (
          <Row icon={<Icon tone="muted"><Watch /></Icon>} title="Garmin" subtitle="Connecting isn't available on this server." />
        )}
        {me.garmin.fake && (
          <Row title="Fake Garmin (dev)" subtitle="Try mfa@, wrong@, 429@ or cf@ emails; MFA code 123456" />
        )}
      </Group>

      {me.calendar.available && (
        <Group label="Calendar" footer="Read-only. Rabbit spots trips and busy days so your plan can work around them.">
          {me.calendar.connected ? (
            <>
              <Row icon={<Icon><CalendarClock /></Icon>} title="Google Calendar"
                trailing={<span className="flex items-center gap-1.5 text-[0.7647rem] text-(--accent)"><span className="size-2 rounded-full bg-(--accent)" />Connected</span>} />
              <Row title="Disconnect Google Calendar" danger disabled={busy} center
                onClick={() => { setBusy(true); void disconnectCalendar().finally(() => { setBusy(false); onChange() }) }} />
            </>
          ) : (
            <a href={CALENDAR_CONNECT_URL} className="settings-row flex w-full items-center gap-3 px-4 py-3 text-left active:bg-(--bg-inset)">
              <Icon><CalendarClock /></Icon>
              <span className="min-w-0 flex-1">
                <span className="block text-[0.9412rem] text-(--text)">Connect Google Calendar</span>
                <span className="block text-[0.7647rem] text-(--text-muted)">See travel and busy days in your plan</span>
              </span>
            </a>
          )}
        </Group>
      )}

      <Group label="Oura" footer={me.oura.available
        ? 'Readiness, sleep and HRV appear in Progress and help Rabbit adjust your week. Oura data stays in the app: it is never sent to Rabbit\'s AI (Oura\'s API terms).'
        : 'Oura needs a one-time server setup: create an app at developer.ouraring.com, then run 8-oura.sh in Cloud Shell.'}>
        {me.oura.connected ? (
          <>
            <Row icon={<Icon><CircleDot /></Icon>} title="Oura Ring"
              trailing={<span className="flex items-center gap-1.5 text-[0.7647rem] text-(--accent)"><span className="size-2 rounded-full bg-(--accent)" />Connected</span>} />
            <Row title="Disconnect Oura" danger disabled={busy} center
              onClick={() => { setBusy(true); void disconnectOura().finally(() => { setBusy(false); onChange() }) }} />
          </>
        ) : me.oura.available ? (
          <a href={OURA_CONNECT_URL} className="settings-row flex w-full items-center gap-3 px-4 py-3 text-left active:bg-(--bg-inset)">
            <Icon><CircleDot /></Icon>
            <span className="min-w-0 flex-1">
              <span className="block text-[0.9412rem] text-(--text)">Connect Oura</span>
              <span className="block text-[0.7647rem] text-(--text-muted)">Readiness, sleep and HRV</span>
            </span>
          </a>
        ) : (
          <Row icon={<Icon tone="muted"><CircleDot /></Icon>} title="Oura Ring" subtitle="Not set up on this server yet" />
        )}
      </Group>

      <Group label="Data sources" footer="Workouts come from Garmin only, so nothing is counted twice.">
        <Row icon={<Icon><Layers /></Icon>} title="Data sources"
          subtitle={sourcesSummary(me.settings.data_sources ?? defaultSources(me.oura.connected))}
          onClick={() => setSourcesOpen(true)} />
      </Group>
      {sourcesOpen && (
        <DataSourcesSheet me={me} onClose={() => setSourcesOpen(false)}
          onSaved={(msg) => { setSourcesOpen(false); onToast?.(msg); onChange() }} />
      )}

      {me.garmin.connected && me.chat.available && (
        <CoachingSettings me={me} onChange={onChange} onDevDone={onDevDone} />
      )}

      <Group label="Share your plan" footer="Coaches see your plan, events and stats; your Rabbit chats stay private. Manage coaches under Me.">
        <ShareRow />
      </Group>

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

      <Group label="Account">
        <Row icon={<Avatar name={me.profile.name || me.user_id} picture={me.profile.picture} photo={photoUrl(me.photo)} />}
          title={me.profile.name || me.user_id} subtitle="Signed in with Google" />
        <Row title={<span className="inline-flex items-center gap-1.5"><LogOut className="size-4" /> Sign out</span>}
          danger center onClick={() => void signOut().finally(onChange)} />
      </Group>
    </div>
  )
}
