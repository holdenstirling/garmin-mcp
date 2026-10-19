// Rabbit home greeting (date + hello). The race countdown is in the header subtitle; streak,
// level and race grade are in Progress.
import { RabbitNap } from '@/components/anim'

function greeting(now: Date): string {
  const h = now.getHours()
  return h < 5 ? 'Up late' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

export function HomeGreeting({ name }: { name: string | null | undefined }) {
  const now = new Date()
  const first = name?.trim().split(/\s+/)[0]
  const h = now.getHours()
  const night = h >= 21 || h < 5  // Rabbit's dozing off: a sleepy rabbit next to the greeting
  return (
    <div className="flex items-end gap-3 px-0.5">
      <div className="min-w-0 flex-1">
        <p className="section-label m-0">
          {now.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' })}
        </p>
        <h2 className="font-display text-[1.1765rem] leading-tight text-(--brand)">{greeting(now)}{first ? `, ${first}` : ''}</h2>
        {night && <p className="m-0 text-[0.7059rem] text-(--text-muted)">rabbt's winding down. Sleep is training too.</p>}
      </div>
      {night && <RabbitNap size={30} mode="sleep" className="mb-1 shrink-0" />}
    </div>
  )
}
