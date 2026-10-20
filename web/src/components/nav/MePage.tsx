// "Me" (from the avatar in every tab header): who you are and everything around your
// training that isn't the plan, progress or events, plus Connected apps and Settings. Friends
// live in Community. Every row is opened by Chat.tsx's page stack (pushed, with a back arrow).
import { Bandage, ChartColumn, ChevronRight, ClipboardList, Compass, Handshake, KeyRound, Mail, Plug, Search, Settings, ShieldCheck, User, UserCheck, Users, Wrench } from 'lucide-react'
import { ShareWorkoutsRow } from '@/components/settings/ShareWorkoutsRow'
import { AppearanceGroup } from '@/components/settings/AppearanceRow'
import { RabbitLogo } from '@/components/RabbitLogo'
import { Avatar } from '@/components/Avatar'
import { Screen } from '@/components/plan/ui'
import { Group, Icon, LargeGroups, Row } from '@/components/settings/Grouped'
import { LevelBadge } from '@/components/progress/Progress'
import { photoUrl } from '@/lib/photo'
import { openBody } from '@/lib/body'
import { goalCountdown, type Goal, type Me } from '@/lib/api'
import type { Progress } from '@/lib/progress'
import { intentsOf, intentsSummary, openWelcome } from '@/lib/intent'
import type { LegalSlug } from '@/lib/legal'
import { openFindFriends } from '@/lib/friends'
import { openHowItWorks } from '@/components/onboarding/HowItWorks'
import { CircleQuestionMark } from 'lucide-react'

export type MeRow = 'profile' | 'memory' | 'gear' | 'friends' | 'coaches' | 'inbox' | 'athletes' | 'settings' | 'findcoach' | 'coachstatus'
  | 'connections' | 'access' | 'usage' | 'partners' | 'legal'

const Count = ({ n, label }: { n: number; label: string }) => (
  <span className="flex items-center gap-1.5">
    <span className="min-w-5 rounded-full bg-(--accent) px-1.5 text-center text-meta font-semibold leading-5 text-(--on-fill)" aria-label={label}>{n}</span>
  </span>
)

export function MePage({ me, goal, progress, onOpen, onOpenDoc, onClose }: {
  me: Me; goal: Goal | null; progress: Progress | null; onOpen: (r: MeRow) => void
  onOpenDoc: (slug: LegalSlug) => void; onClose: () => void
}) {
  const name = me.profile.name || me.user_id
  const countdown = goalCountdown(goal)
  const coachStatus = me.athlete.coach_status ?? null
  return (
    <Screen title="Me" subtitle="Your profile, coaching, connected apps and settings." onClose={onClose}>
      <LargeGroups.Provider value>
      <button type="button" onClick={() => onOpen('profile')}
        className="flex items-center gap-4 rounded-2xl border border-(--border) bg-(--bg-surface) p-5 text-left active:bg-(--bg-inset)">
        <Avatar name={name} picture={me.profile.picture} photo={photoUrl(me.photo)} size={60} />
        <span className="min-w-0 flex-1">
          <span className="block break-words font-display text-title-md leading-tight text-(--brand)">{name}</span>
          {goal ? (
            <>
              <span className="mt-1 block text-body font-medium leading-snug text-(--text)">{goal.title}</span>
              {countdown && <span className="block text-small leading-snug text-(--text-secondary)">{countdown}</span>}
            </>
          ) : <span className="mt-1 block text-body text-(--text-secondary)">No goal set yet</span>}
          {progress && (
            <span className="mt-2 flex items-center gap-2">
              <LevelBadge level={progress.level} size="sm" />
              <span className="text-small font-medium text-(--text-secondary)">{progress.name}</span>
            </span>
          )}
        </span>
        <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
      </button>

      <Group label="Your account">
        <Row icon={<Icon><CircleQuestionMark /></Icon>} title="How rabbt works" subtitle="A quick tour of what you can do" onClick={openHowItWorks} />
        {me.role === 'athlete' && (
          <Row icon={<Icon><Compass /></Icon>} title="How you use rabbt" subtitle={intentsSummary(intentsOf(me))} onClick={openWelcome} />
        )}
        <Row icon={<Icon><ShieldCheck /></Icon>} title="Privacy & legal" subtitle="Privacy policy, terms, download or delete your data"
          onClick={() => onOpen('legal')} />
      </Group>

      <Group label="You">
        <Row icon={<Icon><User /></Icon>} title="Training profile" subtitle="You, goals, zones and your week" onClick={() => onOpen('profile')} />
        <Row icon={<Icon><RabbitLogo current /></Icon>} title="What rabbt knows" subtitle="Your goal, notes and plan files" onClick={() => onOpen('memory')} />
        <Row icon={<Icon><Wrench /></Icon>} title="Gear garage" subtitle="Shoes, bikes and the rest" onClick={() => onOpen('gear')} />
        <Row icon={<Icon><Bandage /></Icon>} title="Body & niggles" subtitle="Log aches; rabbt eases the plan and suggests prehab" onClick={() => openBody({ view: 'niggles' })} />
        <Row icon={<Icon><Users /></Icon>} title="Find friends" subtitle="Search, contacts, invite by text, QR code" onClick={() => openFindFriends()} />
        {me.role === 'athlete' && <ShareWorkoutsRow />}
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

      <AppearanceGroup />

      <Group label="Apps and settings">
        <Row icon={<Icon><Plug /></Icon>} title="Connected apps" subtitle="Garmin, Oura, Apple Watch, WHOOP, Calendar"
          onClick={() => onOpen('connections')} />
        <Row icon={<Icon tone="muted"><Settings /></Icon>} title="Settings" subtitle="Notifications, privacy, account"
          onClick={() => onOpen('settings')} />
        <Row icon={<Icon tone="muted"><KeyRound /></Icon>} title={me.can_invite ? 'Sign-in and invites' : 'Sign-in'}
          subtitle={me.can_invite ? 'Passkeys, invite links, members' : 'Passkeys on your devices'} onClick={() => onOpen('access')} />
        {me.owner && <Row icon={<Icon tone="muted"><ChartColumn /></Icon>} title="Usage" subtitle="Anonymous counts, last 30 days" onClick={() => onOpen('usage')} />}
        {me.owner && <Row icon={<Icon tone="muted"><Handshake /></Icon>} title="Partners" subtitle="Clubs promoted near their cities" onClick={() => onOpen('partners')} />}
      </Group>

      <nav aria-label="Policies" className="flex flex-wrap items-center justify-center gap-x-2 pb-2 text-body text-(--text-secondary)">
        {([['privacy', 'Privacy'], ['terms', 'Terms'], ['security', 'Data & security']] as const).map(([slug, label], i) => (
          <span key={slug} className="flex items-center gap-1">
            {i > 0 && <span aria-hidden>·</span>}
            <button type="button" className="hit-44 underline" onClick={() => onOpenDoc(slug)}>{label}</button>
          </span>
        ))}
      </nav>
      </LargeGroups.Provider>
    </Screen>
  )
}
