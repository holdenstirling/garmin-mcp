// The Community tab: "Feed | Clubs | People". The feed is calm on purpose: what people choose
// to share (life events, races, PRs) and milestones as drafts until you tap Share, never
// every workout. Clubs: local run clubs and crews with meetups and challenges.
import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { RabbitLoader } from '@/components/RabbitLoader'
import { ErrorState } from '@/components/ui/ErrorState'
import { Group, Row, Switch } from '@/components/settings/Grouped'
import { Choice } from './Choice'
import { Screen } from '@/components/plan/ui'
import { Segmented } from '@/components/nav/Segmented'
import { useSheetDrag } from '@/hooks/useSheetDrag'
import {
  MILESTONE_LABEL, getCommunitySettings, putCommunitySettings,
  type CommunitySettings, type MilestoneType, type Usage,
} from '@/lib/community'
import { ClubsTab } from './Clubs'
import { CommunityFeed } from './Feed'
import { PeopleSection } from './People'
import { markSeen } from '@/lib/unread'

export type CommunityView = 'feed' | 'clubs' | 'people'

export function CommunityScreen({ imperial, view, onView, onChanged, club, onClub }: {
  imperial: boolean; view: CommunityView; onView: (v: CommunityView) => void; onChanged?: () => void
  /** an open club page (from a meetup reminder or the "You're going" strip) */
  club: string | null; onClub: (id: string | null) => void
}) {
  const [settings, setSettings] = useState(false)
  const openClub = (id: string) => { onClub(id); onView('clubs') }
  // Viewing clears that part of the app icon badge (cheers/comments, friend requests, club invites).
  useEffect(() => { void markSeen(view === 'feed' ? 'cheers' : view === 'people' ? 'requests' : 'invites') }, [view])
  return (
    <Screen title="Community" onClose={() => {}}
      headerExtra={<Segmented label="Community" value={view} onChange={onView}
        options={[['feed', 'Feed'], ['clubs', 'Clubs'], ['people', 'People']] as const} />}>
      {view === 'feed' && <CommunityFeed imperial={imperial} onInvite={() => onView('people')} onSettings={() => setSettings(true)} onOpenClub={openClub} />}
      {view === 'clubs' && <ClubsTab imperial={imperial} openId={club} onOpen={onClub} />}
      {view === 'people' && <PeopleSection imperial={imperial} onChanged={onChanged} />}
      {settings && <SharingSheet onClose={() => setSettings(false)} />}
    </Screen>
  )
}

const TYPES = Object.keys(MILESTONE_LABEL) as MilestoneType[]

function SharingSheet({ onClose }: { onClose: () => void }) {
  const [s, setS] = useState<CommunitySettings | null>(null)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const drag = useSheetDrag(onClose)
  useEffect(() => { getCommunitySettings().then((r) => { setS(r.settings); setUsage(r.usage) }, (e) => setError((e as Error).message)) }, [])
  async function put(patch: Partial<CommunitySettings>, optimistic: CommunitySettings) {
    const prev = s
    setS(optimistic)
    try { const r = await putCommunitySettings(patch); setS(r.settings) } catch (e) { setS(prev); setError((e as Error).message) }
  }
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} {...drag}>
        <div className="sheet-handle" />
        <div className="modal-header">
          <h2 className="modal-title">Sharing</h2>
          <button className="modal-close" aria-label="Close" onClick={onClose}><X className="size-4" /></button>
        </div>
        <div className="modal-body flex flex-col gap-4 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
          {error && <ErrorState compact message={error} />}
          {!s && !error && <RabbitLoader className="py-6" label="Loading" />}
          {s && (
            <>
              <Group label="Milestones Rabbit spots" footer="Rabbit offers these as drafts. Nothing is shared until you tap Share.">
                {TYPES.map((t) => (
                  <Row key={t} title={MILESTONE_LABEL[t]}
                    trailing={<Switch label={MILESTONE_LABEL[t]} checked={s.milestones[t]}
                      onChange={(v) => void put({ milestones: { ...s.milestones, [t]: v } }, { ...s, milestones: { ...s.milestones, [t]: v } })} />} />
                ))}
              </Group>
              <Group label="Share automatically" footer="Skip the draft for these and post to your default audience right away.">
                {TYPES.filter((t) => s.milestones[t]).map((t) => (
                  <Row key={t} title={MILESTONE_LABEL[t]}
                    trailing={<Switch label={`Auto-share ${MILESTONE_LABEL[t]}`} checked={s.auto_share[t]}
                      onChange={(v) => void put({ auto_share: { ...s.auto_share, [t]: v } }, { ...s, auto_share: { ...s.auto_share, [t]: v } })} />} />
                ))}
              </Group>
              <Group label="Shared milestones go to" footer="Never your heart rate, health data or where you trained.">
                <div className="px-3 py-2.5">
                  <Choice label="Default audience" value={s.audience}
                    options={[['friends', 'Friends'], ['public', 'Everyone on Rabbit'], ['private', 'Only me']]}
                    onChange={(v) => void put({ audience: v }, { ...s, audience: v })} />
                </div>
              </Group>
              {usage && (
                <p className="px-1 text-[0.6471rem] text-(--text-muted)">
                  Photos: {usage.photos} of {usage.max_photos} · {Math.round(usage.bytes / 1024 / 1024)} of {Math.round(usage.max_bytes / 1024 / 1024)} MB
                </p>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
