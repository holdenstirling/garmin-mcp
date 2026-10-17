// Rabbit home greeting (date + hello). The race countdown is in the header subtitle; streak,
// level and race grade are in Progress.

function greeting(now: Date): string {
  const h = now.getHours()
  return h < 5 ? 'Up late' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

export function HomeGreeting({ name }: { name: string | null | undefined }) {
  const now = new Date()
  const first = name?.trim().split(/\s+/)[0]
  return (
    <div className="px-0.5">
      <p className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">
        {now.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' })}
      </p>
      <h2 className="font-display text-[1.1765rem] leading-tight text-(--brand)">{greeting(now)}{first ? `, ${first}` : ''}</h2>
    </div>
  )
}
