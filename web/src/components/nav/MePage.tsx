// The "Me" tab: who you are and everything around your training that isn't the plan,
// progress or races. Rows open the existing screens and the Settings sheet.
import { Brain, ClipboardList, Mail, Settings, User, UserCheck, Users, Wrench } from 'lucide-react'
import { Avatar } from '@/components/Avatar'
import { Screen } from '@/components/plan/ui'
import { Group, Icon, Row } from '@/components/settings/Grouped'
import { LevelBadge } from '@/components/progress/Progress'
import { photoUrl } from '@/lib/photo'
import { goalCountdown, type Goal, type Me } from '@/lib/api'
import type { Progress } from '@/lib/progress'

export type MeRow = 'profile' | 'memory' | 'gear' | 'friends' | 'coaches' | 'inbox' | 'athletes' | 'settings'

const Count = ({ n, label }: { n: number; label: string }) => (
  <span className="flex items-center gap-1.5">
    <span className="min-w-5 rounded-full bg-(--accent) px-1.5 text-center text-[0.7059rem] font-semibold leading-5 text-white" aria-label={label}>{n}</span>
  </span>
)
const Dot = ({ label }: { label: string }) => <span className="size-2 rounded-full bg-(--accent)" role="img" aria-label={label} />

export function MePage({ me, goal, progress, friendsDot, onOpen }: {
  me: Me; goal: Goal | null; progress: Progress | null; friendsDot: boolean; onOpen: (r: MeRow) => void
}) {
  const name = me.profile.name || me.user_id
  const countdown = goalCountdown(goal)
  return (
    <Screen title="Me" onClose={() => {}}>
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
      </Group>

      <Group label="People">
        <Row icon={<Icon><Users /></Icon>} title="Friends" subtitle="Train together, cheer each other on"
          trailing={friendsDot ? <span className="flex items-center gap-2"><Dot label="New activity" /></span> : undefined}
          onClick={() => onOpen('friends')} />
        {me.coaches > 0 && (
          <Row icon={<Icon><Mail /></Icon>} title="Coach messages" subtitle="Chat with your coach"
            trailing={me.coach_unread ? <Count n={me.coach_unread} label={`${me.coach_unread} unread`} /> : undefined}
            onClick={() => onOpen('inbox')} />
        )}
        <Row icon={<Icon><UserCheck /></Icon>} title="Coaches"
          subtitle={me.coaches ? `${me.coaches} coach${me.coaches === 1 ? '' : 'es'}` : 'Invite a coach by email'}
          onClick={() => onOpen('coaches')} />
        {me.coaching > 0 && (
          <Row icon={<Icon><ClipboardList /></Icon>} title="Athletes you coach"
            subtitle={`${me.coaching} athlete${me.coaching === 1 ? '' : 's'}`} onClick={() => onOpen('athletes')} />
        )}
      </Group>

      <Group>
        <Row icon={<Icon tone="muted"><Settings /></Icon>} title="Settings" subtitle="Garmin, calendar, Oura, notifications, account"
          onClick={() => onOpen('settings')} />
      </Group>
    </Screen>
  )
}
