// Me -> Connected apps: every integration on one page with its status (Connected / Not
// connected / Needs attention + last sync), then the coming-soon apps (SoonSheet: "I want this"). Tapping one opens its connect popup
// (ConnectSheet, owned by screens/Chat.tsx so there is only ever one, via requestConnect).
import { useCallback, useEffect, useState } from 'react'
import { BellRing, Check, ChevronRight, Lock } from 'lucide-react'
import { Screen } from '@/components/plan/ui'
import { Group } from '@/components/settings/Grouped'
import { RabbitLoader } from '@/components/RabbitLoader'
import { ErrorState } from '@/components/ui/ErrorState'
import { AppTile, PURPOSE } from '@/components/connect/ConnectSheet'
import { SoonSheet, SoonTile } from '@/components/connect/SoonSheet'
import { cn } from '@/lib/utils'
import { sourcesSummary } from '@/lib/sources'
import { CONNECTIONS_CHANGED, getConnections, requestConnect, syncedAgo, type Connection, type Connections, type SoonApp, type SoonId } from '@/lib/connections'

/** "Connected · Synced 5 min ago" / "Needs attention" / "Not connected" / "Coming soon". */
function statusLine(a: Connection): string {
  if (a.state === 'connected') return `Connected · ${syncedAgo(a.last_sync)}`
  if (a.state === 'attention') return 'Needs attention · tap to reconnect'
  if (a.state === 'unavailable') return 'Coming soon'
  return 'Not connected'
}

export function ConnectionsScreen({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<Connections | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [soon, setSoon] = useState<SoonId | null>(null)
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
        rabbt reads from these so you never log anything by hand. Tap one to connect, sync or disconnect.
      </p>
      <p className="flex items-start gap-2 rounded-xl bg-(--bg-inset) px-3.5 py-2.5 text-[0.7059rem] leading-snug text-(--text-secondary)">
        <Lock className="mt-0.5 size-3.5 shrink-0 text-(--accent)" aria-hidden />
        rabbt only uses what each app lists, changes nothing there unless you ask (like sending a workout to your watch), and stores sign-ins encrypted. Disconnect anytime and rabbt deletes its access.
      </p>
      {err && !data ? <ErrorState message={err} onRetry={load} />
        : !data ? <div className="flex justify-center py-8"><RabbitLoader label="Checking your apps…" /></div>
        : (
          <>
          <Group footer={data.sources ? `${sourcesSummary(data.sources)}. A workout recorded by two apps counts once (Garmin's is used).` : undefined}>
            {data.apps.map((a) => (
              <button key={a.id} type="button" onClick={() => requestConnect(a.id)}
                className="settings-row flex min-h-14 w-full items-center gap-3 px-4 py-3 text-left active:bg-(--bg-inset)">
                <AppTile app={a.id} size={40} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[0.9412rem] text-(--text)">{a.name}</span>
                  <span className="block truncate text-[0.7059rem] text-(--text-muted)">{PURPOSE[a.id]}</span>
                  <span className={cn('mt-0.5 flex items-center gap-1.5 text-[0.7059rem] font-medium',
                    a.state === 'connected' ? 'text-(--accent)' : a.state === 'attention' ? 'text-(--warning-text)' : 'text-(--text-muted)')}>
                    <span aria-hidden className={cn('size-1.5 shrink-0 rounded-full',
                      a.state === 'connected' ? 'bg-(--accent)' : a.state === 'attention' ? 'bg-(--warning-text)' : 'bg-(--text-muted)')} />
                    {statusLine(a)}
                  </span>
                </span>
                <ChevronRight className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
              </button>
            ))}
          </Group>
          {data.soon && data.soon.length > 0 && (
            <Group label="Coming soon" footer="Tap one and say “I want this”: it tells us what to build next.">
              {data.soon.map((a) => (
                <button key={a.id} type="button" onClick={() => setSoon(a.id)}
                  className="settings-row flex min-h-14 w-full items-center gap-3 px-4 py-3 text-left active:bg-(--bg-inset)">
                  <SoonTile app={a.id} size={40} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[0.9412rem] text-(--text)">{a.name}</span>
                    <span className={cn('mt-0.5 flex items-center gap-1.5 text-[0.7059rem] font-medium', a.wanted ? 'text-(--accent)' : 'text-(--text-muted)')}>
                      {a.wanted ? <Check className="size-3 shrink-0" aria-hidden /> : <BellRing className="size-3 shrink-0" aria-hidden />}
                      <span className="min-w-0 truncate">
                        {a.wanted ? 'You asked for this' : 'Coming soon · tap to ask'}
                        {a.wanted_by != null && <span className="text-(--text-muted)"> · {a.wanted_by} want{a.wanted_by === 1 ? 's' : ''} it</span>}
                      </span>
                    </span>
                  </span>
                  <ChevronRight className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
                </button>
              ))}
            </Group>
          )}
          </>
        )}
      {soon && data?.soon?.find((a) => a.id === soon) && (
        <SoonSheet app={data.soon.find((a) => a.id === soon)!} onClose={() => setSoon(null)}
          onChanged={(next: SoonApp) => setData((d) => d && { ...d, soon: (d.soon ?? []).map((a) => (a.id === next.id ? next : a)) })} />
      )}
    </Screen>
  )
}
