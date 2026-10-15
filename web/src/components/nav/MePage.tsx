// "Me" (from the avatar in every tab header): who you are and everything around your
// training that isn't the plan, progress or events, plus Settings. Friends live in Community.
import { useState } from 'react'
import { Brain, ClipboardList, KeyRound, Mail, Search, Settings, User, UserCheck, Users, Wrench } from 'lucide-react'
import { AccessScreen } from '@/components/settings/AccessScreen'
import { Avatar } from '@/components/Avatar'
import { Screen } from '@/components/plan/ui'
import { Group, Icon, Row } from '@/components/settings/Grouped'
import { LevelBadge } from '@/components/progress/Progress'
import { photoUrl } from '@/lib/photo'
import { goalCountdown, type Goal, type Me } from '@/lib/api'
import type { Progress } from '@/lib/progress'

export type MeRow = 'profile' | 'memory' | 'gear' | 'friends' | 'coaches' | 'inbox' | 'athletes' | 'settings' | 'findcoach' | 'coachstatus'

const Count = ({ n, label }: { n: number; label: string }) => (
  <span className="flex items-center gap-1.5">
    <span className="min-w-5 rounded-full bg-(--accent) px-1.5 text-center text-[0.7059rem] font-semibold leading-5 text-white" aria-label={label}>{n}</span>
  </span>
)

export function MePage({ me, goal, progress, onOpen, onClose }: {
  me: Me; goal: Goal | null; progress: Progress | null; onOpen: (r: MeRow) => void; onClose: () => void
}) {
  const name = me.profile.name || me.user_id
  const countdown = goalCountdown(goal)
  const coachStatus = me.athlete.coach_status ?? null
  const [access, setAccess] = useState(false)
  return (
    <Screen title="Me" onClose={onClose}>
      <button type="button" onClick={() => onOpen('profile')}
        className="flex items-center gap-3.5 rounded-2xl border border-(--border) bg-(--bg-surface) p-4 text-left active:bg-(--bg-inset)">
        <Avatar name={name} picture={me.profile.picture} photo={photoUrl(me.photo)} size={56} />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-display text-[1.2941rem] leading-tight text-(--brand)">{name}</span>
          <span className="block truncate text-[0.7647rem] text-(--text-muted)">
            {goal ? `${goal.title}${countdown ? ` · ${countdown}` : ''}` : 'No goal set yet'}
          </span>
        </span>
        {progress && (
          <span className="flex shrink-0 flex-col items-center gap-0.5">
            <LevelBadge level={progress.level} size="md" />
            <span className="max-w-20 truncate text-[0.6471rem] text-(--text-muted)">{progress.name}</span>
          </span>
        )}
      </button>

      <Group label="You">
        <Row icon={<Icon><User /></Icon>} title="Training profile" subtitle="You, goals, zones and your week" onClick={() => onOpen('profile')} />
        <Row icon={<Icon><Brain /></Icon>} title="What Rabbit knows" subtitle="Your goal, notes and plan files" onClick={() => onOpen('memory')} />
        <Row icon={<Icon><Wrench /></Icon>} title="Gear garage" subtitle="Shoes, bikes and the rest" onClick={() => onOpen('gear')} />
        <Row icon={<Icon><Users /></Icon>} title="Friends" subtitle="In Community, with your clubs" onClick={() => onOpen('friends')} />
      </Group>

      {coachStatus === 'looking' && me.coaches === 0 && (
        <Group>
          <Row icon={<Icon><Search /></Icon>} title="Find a coach" subtitle="Coaches who fit your race, contact them directly"
            onClick={() => onOpen('findcoach')} />
        </Group>
      )}

      <Group label="Coaching">
        {me.coaches > 0 && (
          <Row icon={<Icon><Mail /></Icon>} title="Coach messages" subtitle="Chat with your coach"
            trailing={me.coach_unread ? <Count n={me.coach_unread} label={`${me.coach_unread} unread`} /> : undefined}
            onClick={() => onOpen('inbox')} />
        )}
        <Row icon={<Icon><UserCheck /></Icon>} title="Coaches"
          subtitle={me.coaches ? `${me.coaches} coach${me.coaches === 1 ? '' : 'es'}` : 'Invite a coach by email'}
          onClick={() => onOpen('coaches')} />
        {me.coaches === 0 && coachStatus === null && (
          <Row icon={<Icon tone="muted"><Search /></Icon>} title="Looking for a coach?" subtitle="Find one or go solo"
            onClick={() => onOpen('coachstatus')} />
        )}
        {me.coaches === 0 && coachStatus === 'self_coached' && (
          <Row icon={<Icon tone="muted"><Search /></Icon>} title="Find a coach" subtitle="If you change your mind"
            onClick={() => onOpen('findcoach')} />
        )}
        {me.coaching > 0 && (
          <Row icon={<Icon><ClipboardList /></Icon>} title="Athletes you coach"
            subtitle={`${me.coaching} athlete${me.coaching === 1 ? '' : 's'}`} onClick={() => onOpen('athletes')} />
        )}
      </Group>

      <Group>
        <Row icon={<Icon tone="muted"><Settings /></Icon>} title="Settings" subtitle="Garmin, calendar, Oura, notifications, account"
          onClick={() => onOpen('settings')} />
        <Row icon={<Icon tone="muted"><KeyRound /></Icon>} title={me.can_invite ? 'Sign-in and invites' : 'Sign-in'}
          subtitle={me.can_invite ? 'Passkeys, invite links, members' : 'Passkeys on your devices'} onClick={() => setAccess(true)} />
      </Group>
      {access && <AccessScreen onClose={() => setAccess(false)} />}
    </Screen>
  )
}
