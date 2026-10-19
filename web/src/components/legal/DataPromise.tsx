// "We never sell your data or use it for ads." The one data-stance line, shown wherever people
// decide to trust rabbt with their data (sign-in, consent, Privacy & legal, connect sheets).
import { Lock } from 'lucide-react'
import { cn } from '@/lib/utils'
import { DATA_PROMISE } from '@/lib/legal'

export function DataPromise({ className, center }: { className?: string; center?: boolean }) {
  return (
    <p className={cn('m-0 flex items-start gap-2 text-small font-medium leading-snug text-(--text-secondary)',
      center && 'justify-center text-center', className)}>
      <Lock className="mt-0.5 size-4 shrink-0 text-(--accent)" aria-hidden />
      <span>{DATA_PROMISE}</span>
    </p>
  )
}
