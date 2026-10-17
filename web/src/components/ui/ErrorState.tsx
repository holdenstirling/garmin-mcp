// One way to say "that didn't load": a short message and a Retry button. It shakes once on
// mount (.rb-shake, anim kit; still under reduced motion).
import { RotateCw } from 'lucide-react'
import { cn } from '@/lib/utils'
import { RabbitNap } from '@/components/anim'

const offline = () => { try { return navigator.onLine === false } catch { return false } }

export function ErrorState({ message, onRetry, compact, className }: {
  message?: string | null; onRetry?: () => void; compact?: boolean; className?: string
}) {
  const text = message || "Couldn't load this."
  return (
    <div role="alert"
      className={cn('rb-shake flex items-center gap-3 rounded-xl border border-(--danger)/25 bg-(--danger-subtle)',
        compact ? 'px-3 py-2' : 'flex-col px-4 py-5 text-center', className)}>
      {!compact && <RabbitNap size={40} mode={offline() ? 'offline' : 'think'} />}
      <p className={cn('min-w-0 leading-snug text-(--danger)', compact ? 'flex-1 text-[0.7059rem]' : 'text-[0.8235rem]')}>{text}</p>
      {onRetry && (
        <button type="button" onClick={onRetry}
          className="inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-full px-3 text-[0.7647rem] font-medium text-(--text) underline-offset-2 hover:underline">
          <RotateCw className="size-3.5" aria-hidden /> Retry
        </button>
      )}
    </div>
  )
}
