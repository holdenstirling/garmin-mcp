// Schedule's "+ Add": the one place to add anything to your schedule, plan or not.
//   A workout -> the session editor on a day (with a start time), on the plan calendar;
//   An event -> the event editor (races, group sessions, trips; can repeat), linked to the plan;
//   Travel / days away -> travel mode (lib/plantools openTravel);
//   I'm sick -> sick mode (lib/sick openSick);
//   A plan -> build one in Rabbit, or import a plan you already have.
import { CalendarPlus, ChevronRight, Dumbbell, FileUp, Plane, Thermometer, UserPlus } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { RabbitLogo } from '@/components/RabbitLogo'
import { openFindFriends } from '@/lib/friends'

function Option({ icon, title, sub, onClick }: { icon: React.ReactNode; title: string; sub: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick}
      className="flex min-h-16 w-full items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-3 text-left active:bg-(--bg-inset)">
      <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-(--accent-subtle) text-(--accent)" aria-hidden>{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-body-lg font-semibold text-(--text)">{title}</span>
        <span className="block text-meta leading-snug text-(--text-muted)">{sub}</span>
      </span>
      <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
    </button>
  )
}

export function AddSheet({ hasPlan, onWorkout, onEvent, onTravel, onSick, onBuildPlan, onImportPlan, onClose }: {
  /** a Rabbit-built plan exists (workouts are added to it) */
  hasPlan: boolean
  onWorkout: () => void
  onEvent: () => void
  /** travel mode: days away (a built plan only) */
  onTravel?: () => void
  /** sick mode (a built plan only) */
  onSick?: () => void
  onBuildPlan: () => void
  onImportPlan: () => void
  onClose: () => void
}) {
  const pick = (f: () => void) => () => { onClose(); f() }
  return (
    <Sheet title="Add" onClose={onClose}
      bodyClassName="settings flex flex-col gap-2.5 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
      {hasPlan ? (
        <Option icon={<Dumbbell className="size-6" />} title="A workout"
          sub="Pick the day and a start time; rabbt balances the rest of the week" onClick={pick(onWorkout)} />
      ) : (
        <Option icon={<Dumbbell className="size-6" />} title="A workout"
          sub="Workouts live in a plan: get one first (about 3 minutes)" onClick={pick(onBuildPlan)} />
      )}
      <Option icon={<CalendarPlus className="size-6" />} title="Add to my calendar"
        sub="A race, a trip or a big day; your plan works around it" onClick={pick(onEvent)} />
      {hasPlan && onTravel && (
        <Option icon={<Plane className="size-6" />} title="Travel / days away"
          sub="Hotel gym, treadmill or runs only: rabbt swaps those days' sessions" onClick={pick(onTravel)} />
      )}
      {hasPlan && onSick && (
        <Option icon={<Thermometer className="size-6" />} title="I'm sick"
          sub="Rest or short easy days until you're better, then an easy return" onClick={pick(onSick)} />
      )}
      <p className="mt-3 px-1 text-body font-semibold text-(--text)">People</p>
      <Option icon={<UserPlus className="size-6" />} title="Friends"
        sub="Search, check your contacts, invite by text or share your QR code" onClick={pick(() => openFindFriends())} />
      <p className="mt-3 px-1 text-body font-semibold text-(--text)">A plan</p>
      <Option icon={<RabbitLogo size={20} current />} title={hasPlan ? 'Rebuild my plan' : 'Get a plan'}
        sub={hasPlan ? 'New race or new answers; your events stay' : 'Race, goals, your week: about 3 minutes'} onClick={pick(onBuildPlan)} />
      <Option icon={<FileUp className="size-6" />} title="Import a plan"
        sub="From a coach or app: a file, screenshots, pasted text or a template" onClick={pick(onImportPlan)} />
    </Sheet>
  )
}
