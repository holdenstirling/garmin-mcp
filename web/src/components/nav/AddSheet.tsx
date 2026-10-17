// Schedule's "+ Add": the one place to add anything to your schedule, plan or not.
//   A workout -> the session editor on a day (with a start time), on the plan calendar;
//   An event -> the event editor (races, group sessions, trips; can repeat), linked to the plan;
//   Travel / days away -> travel mode (lib/plantools openTravel);
//   A plan -> build one in Rabbit, or import a plan you already have.
import { CalendarPlus, ChevronRight, Dumbbell, FileUp, Plane } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { RabbitLogo } from '@/components/RabbitLogo'

function Option({ icon, title, sub, onClick }: { icon: React.ReactNode; title: string; sub: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick}
      className="flex min-h-16 w-full items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-3 text-left active:bg-(--bg-inset)">
      <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-(--accent-subtle) text-(--accent)" aria-hidden>{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-[0.8824rem] font-semibold text-(--text)">{title}</span>
        <span className="block text-[0.7059rem] leading-snug text-(--text-muted)">{sub}</span>
      </span>
      <ChevronRight className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
    </button>
  )
}

export function AddSheet({ hasPlan, onWorkout, onEvent, onTravel, onBuildPlan, onImportPlan, onClose }: {
  /** a Rabbit-built plan exists (workouts are added to it) */
  hasPlan: boolean
  onWorkout: () => void
  onEvent: () => void
  /** travel mode: days away (a built plan only) */
  onTravel?: () => void
  onBuildPlan: () => void
  onImportPlan: () => void
  onClose: () => void
}) {
  const pick = (f: () => void) => () => { onClose(); f() }
  return (
    <Sheet title="Add to your schedule" onClose={onClose}
      bodyClassName="settings flex flex-col gap-2.5 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
      {hasPlan ? (
        <Option icon={<Dumbbell className="size-5" />} title="A workout"
          sub="Pick the day and a start time; Rabbit balances the rest of the week" onClick={pick(onWorkout)} />
      ) : (
        <Option icon={<Dumbbell className="size-5" />} title="A workout"
          sub="Workouts live in a plan: build one first (about 3 minutes)" onClick={pick(onBuildPlan)} />
      )}
      <Option icon={<CalendarPlus className="size-5" />} title="An event"
        sub="A race, group run, league night or trip; it can repeat every week and goes into your plan" onClick={pick(onEvent)} />
      {hasPlan && onTravel && (
        <Option icon={<Plane className="size-5" />} title="Travel / days away"
          sub="Hotel gym, treadmill or runs only: Rabbit swaps those days' sessions" onClick={pick(onTravel)} />
      )}
      <p className="mt-2 px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">A plan</p>
      <Option icon={<RabbitLogo size={20} current />} title={hasPlan ? 'Rebuild my plan' : 'Build my plan'}
        sub={hasPlan ? 'New race or new answers; your events stay' : 'Race, goals, your week: about 3 minutes'} onClick={pick(onBuildPlan)} />
      <Option icon={<FileUp className="size-5" />} title="Import a plan"
        sub="From a coach or app: a file, screenshots, pasted text or a template" onClick={pick(onImportPlan)} />
    </Sheet>
  )
}
