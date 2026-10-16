// Me -> Connected apps: every integration on one page with its status (Connected / Not
// connected / Needs attention + last sync). Tapping one opens its connect popup
// (ConnectSheet, owned by screens/Chat.tsx so there is only ever one, via requestConnect).
import { useCallback, useEffect, useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { Screen } from '@/components/plan/ui'
import { Group } from '@/components/settings/Grouped'
import { RabbitLoader } from '@/components/RabbitLoader'
import { ErrorState } from '@/components/ui/ErrorState'
import { AppTile, StateChip } from '@/components/connect/ConnectSheet'
import { sourcesSummary } from '@/lib/sources'
import { CONNECTIONS_CHANGED, getConnections, requestConnect, syncedAgo, type Connections } from '@/lib/connections'

export function ConnectionsScreen({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<Connections | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const load = useCallback(() => {
    getConnections().then((d) => { setData(d); setErr(null) }, (e) => setErr((e as Error).message))
  }, [])
  useEffect(() => {
    load()
    window.addEventListener(CONNECTIONS_CHANGED, load)
    return () => window.removeEventListener(CONNECTIONS_CHANGED, load)
  }, [load])

  return (
    <Screen title="Connected apps" onClose={onClose}>
      <p className="px-1 text-[0.8235rem] leading-snug text-(--text-secondary)">
        Rabbit reads from these so you never log anything by hand. Tap one to connect, sync or disconnect.
      </p>
      {err && !data ? <ErrorState message={err} onRetry={load} />
        : !data ? <div className="flex justify-center py-8"><RabbitLoader label="Checking your apps…" /></div>
        : (
          <Group footer={data.sources ? `${sourcesSummary(data.sources)}. Workouts come from Garmin only, so nothing is counted twice.` : undefined}>
            {data.apps.map((a) => (
              <button key={a.id} type="button" onClick={() => requestConnect(a.id)}
                className="settings-row flex min-h-14 w-full items-center gap-3 px-4 py-3 text-left active:bg-(--bg-inset)">
                <AppTile app={a.id} size={36} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[0.9412rem] text-(--text)">{a.name}</span>
                  <span className="block truncate text-[0.7059rem] text-(--text-muted)">
                    {a.connected ? syncedAgo(a.last_sync) : a.state === 'unavailable' ? 'Not set up on this server' : 'Tap to connect'}
                  </span>
                </span>
                <StateChip state={a.state} />
                <ChevronRight className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
              </button>
            ))}
          </Group>
        )}
    </Screen>
  )
}
