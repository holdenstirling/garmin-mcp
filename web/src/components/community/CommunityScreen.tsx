// Two tabs share this screen (section): Friends ("Updates | People"), and Near me (runs, clubs, meetups). The feed is calm on purpose: what people choose
// to share (life events, races, PRs) and milestones as drafts until you tap Share, never
// every workout. Clubs: local run clubs and crews with meetups and challenges. Featured clubs
// (owner-promoted) lead Feed and Clubs; feed groups open as their own page.
import { useEffect, useState } from 'react'
import { RabbitLoader } from '@/components/RabbitLoader'
import { ErrorState } from '@/components/ui/ErrorState'
import { Row, Switch } from '@/components/settings/Grouped'
import { RowGroup } from './RowGroup'
import { Choice } from './Choice'
import { Screen } from '@/components/plan/ui'
import { Segmented } from '@/components/nav/Segmented'
import {
  MILESTONE_LABEL, getCommunitySettings, putCommunitySettings,
  type CommunitySettings, type MilestoneType, type Usage,
} from '@/lib/community'
import { ClubsTab } from './Clubs'
import { NearbyRuns, PostRunButton } from './LocalRuns'
import { CommunityFeed } from './Feed'
import { PeopleSection } from './People'
import { BuddiesSection } from './Buddies'
import { BuddyCheckCard } from './BuddyCheck'
import { BlocksEntry } from '@/components/blocks/BlocksEntry'
import { markSeen } from '@/lib/unread'
import { Sheet } from '@/components/ui/Sheet'
import { getCommunityHome, listGroups, type Featured, type FeedGroup } from '@/lib/community2'
import { FeaturedStrip } from './Featured'
import { GroupPage, GroupSheet } from './Groups'
import { openFindFriends } from '@/lib/friends'
import { NewEventSheet } from '@/components/events/EventsScreen'
import { MEETUP_KINDS } from '@/lib/events'
import { Button } from '@/components/ui/button'
import { CalendarPlus } from 'lucide-react'
import { OneTip } from '@/components/home/OneTip'
import { milestone } from '@/lib/traction'

export type CommunityView = 'feed' | 'clubs' | 'people'

export function CommunityScreen({ section = 'feed', imperial, view, onView, onChanged, club, onClub, onOpenPlan, onBuildPlan }: {
  /** which tab: Feed (the feed and feed groups) or Clubs (clubs and people) */
  section?: 'feed' | 'clubs'
  imperial: boolean; view: CommunityView; onView: (v: CommunityView) => void; onChanged?: () => void
  /** an open club page (from a meetup reminder or the "You're going" strip) */
  club: string | null; onClub: (id: string | null) => void
  /** for the meetup form's plan links */
  onOpenPlan?: () => void; onBuildPlan?: () => void
}) {
  const [newMeetup, setNewMeetup] = useState(false)
  const [settings, setSettings] = useState(false)
  const [featured, setFeatured] = useState<Featured[] | undefined>(undefined)
  const [group, setGroup] = useState<string | null>(null)
  const [newGroup, setNewGroup] = useState(false)
  const [groupsKey, setGroupsKey] = useState(0)
  const [runsKey, setRunsKey] = useState(0)
  const openClub = (id: string) => { onClub(id); onView('clubs') }
  useEffect(() => {
    let live = true
    getCommunityHome().then((r) => { if (live) setFeatured(r.featured) }, () => { if (live) setFeatured([]) })
    return () => { live = false }
  }, [])
  // Viewing clears that part of the app icon badge (cheers/comments, friend requests, club invites).
  useEffect(() => { void markSeen(view === 'feed' ? 'cheers' : view === 'people' ? 'requests' : 'invites') }, [view])
  return (
    <Screen title={section === 'feed' ? 'Friends' : 'Near me'}
      subtitle={section === 'feed' ? (view === 'people' ? 'Find friends and running buddies' : 'What your friends and groups are up to') : 'Runs, clubs and meetups near you'}
      headerExtra={section === 'feed' ? <Segmented label="Friends" value={view === 'people' ? 'people' : 'feed'} onChange={onView}
        options={[['feed', 'Updates'], ['people', 'People']] as const} /> : undefined}>
      {view === 'clubs' && <OneTip id="near_me" text="Tap a club or a pin to see when they meet. Tap Going and rabbt reminds you the night before." />}
      {view === 'feed' && <OneTip id="friends" text="Your workouts post here after each sync, for friends only. Turn sharing off in Me, under Sharing." />}
      {view === 'clubs' && (
        <div className="flex flex-col gap-2">
          <PostRunButton onPosted={() => setRunsKey((k) => k + 1)} />
          <Button variant="ghost" className="h-11 w-full gap-1.5 text-body" onClick={() => setNewMeetup(true)}>
            <CalendarPlus className="size-5" aria-hidden /> Post another kind of meetup
          </Button>
        </div>
      )}
      {view === 'clubs' && <NearbyRuns refreshKey={runsKey} />}
      {view === 'clubs' && featured && featured.length > 0 && (
        <FeaturedStrip items={featured} onOpenClub={openClub} />
      )}
      {view === 'feed' && <CommunityFeed imperial={imperial} onInvite={() => openFindFriends()} onSettings={() => setSettings(true)} onOpenClub={openClub}
        onOpenGroup={setGroup} onNewGroup={() => setNewGroup(true)} groupsKey={groupsKey} />}
      {view === 'clubs' && <ClubsTab imperial={imperial} openId={club} onOpen={onClub} />}
      {newGroup && <GroupSheet onClose={() => setNewGroup(false)}
        onSaved={(g) => { setNewGroup(false); setGroupsKey((k) => k + 1); setGroup(g.id) }} />}
      {group && <GroupPage id={group} imperial={imperial} onClose={() => setGroup(null)} onChanged={() => setGroupsKey((k) => k + 1)} />}
      {view === 'people' && <BuddyCheckCard />}
      {view === 'people' && <BuddiesSection imperial={imperial} />}
      {view === 'people' && <PeopleSection imperial={imperial} onChanged={onChanged} />}
      {view === 'people' && <BlocksEntry compact />}
      {settings && <SharingSheet onClose={() => setSettings(false)} />}
    {newMeetup && (
        <NewEventSheet only={MEETUP_KINDS} title="Post a meetup" imperial={imperial} onClose={() => setNewMeetup(false)}
          onSaved={() => { milestone('run_posted'); setRunsKey((k) => k + 1); onChanged?.() }} onOpenPlan={() => onOpenPlan?.()} onBuildPlan={() => onBuildPlan?.()} />
      )}
      </Screen>
  )
}

const TYPES = Object.keys(MILESTONE_LABEL) as MilestoneType[]

function SharingSheet({ onClose }: { onClose: () => void }) {
  const [s, setS] = useState<CommunitySettings | null>(null)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [groups, setGroups] = useState<FeedGroup[]>([])
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    getCommunitySettings().then((r) => { setS(r.settings); setUsage(r.usage) }, (e) => setError((e as Error).message))
    listGroups().then((r) => setGroups(r.groups), () => { /* friends still works */ })
  }, [])
  async function put(patch: Partial<CommunitySettings>, optimistic: CommunitySettings) {
    const prev = s
    setS(optimistic)
    try { const r = await putCommunitySettings(patch); setS(r.settings) } catch (e) { setS(prev); setError((e as Error).message) }
  }
  return (
    <Sheet title="Sharing" onClose={onClose} bodyClassName="flex flex-col gap-4 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
          {error && <ErrorState compact message={error} />}
          {!s && !error && <RabbitLoader className="py-6" label="Loading" />}
          {s && (
            <>
              <RowGroup as="h3" title="Milestones rabbt spots" footer="rabbt offers these as drafts. Nothing is shared until you tap Share.">
                {TYPES.map((t) => (
                  <Row key={t} title={MILESTONE_LABEL[t]}
                    trailing={<Switch label={MILESTONE_LABEL[t]} checked={s.milestones[t]}
                      onChange={(v) => void put({ milestones: { ...s.milestones, [t]: v } }, { ...s, milestones: { ...s.milestones, [t]: v } })} />} />
                ))}
              </RowGroup>
              <RowGroup as="h3" title="Share automatically" footer="Skip the draft for these and post to your default audience right away.">
                {TYPES.filter((t) => s.milestones[t]).map((t) => (
                  <Row key={t} title={MILESTONE_LABEL[t]}
                    trailing={<Switch label={`Auto-share ${MILESTONE_LABEL[t]}`} checked={s.auto_share[t]}
                      onChange={(v) => void put({ auto_share: { ...s.auto_share, [t]: v } }, { ...s, auto_share: { ...s.auto_share, [t]: v } })} />} />
                ))}
              </RowGroup>
              {groups.length > 0 && (
                <RowGroup as="h3" title="Auto-shared workouts go to" footer="Right after your watch syncs. Group posts are only seen by the group.">
                  <div className="px-3 py-2.5">
                    <Choice label="Auto-shared workouts audience" value={s.share_audience ?? 'friends'}
                      options={[['friends', 'Friends'], ...groups.map((g) => [`grp:${g.id}`, `${g.emoji} ${g.name}`] as const)]}
                      onChange={(v) => void put({ share_audience: v }, { ...s, share_audience: v })} />
                  </div>
                </RowGroup>
              )}
              <RowGroup as="h3" title="Shared milestones go to" footer="Never your heart rate, health data or where you trained.">
                <div className="px-3 py-2.5">
                  <Choice label="Default audience" value={s.audience}
                    options={[['friends', 'Friends'], ['public', 'Everyone on rabbt'], ['private', 'Only me']]}
                    onChange={(v) => void put({ audience: v }, { ...s, audience: v })} />
                </div>
              </RowGroup>
              {usage && (
                <p className="px-1 text-caption text-(--text-muted)">
                  Photos: {usage.photos} of {usage.max_photos} · {Math.round(usage.bytes / 1024 / 1024)} of {Math.round(usage.max_bytes / 1024 / 1024)} MB
                </p>
              )}
            </>
          )}
    </Sheet>
  )
}
