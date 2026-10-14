// Shake: a subtle horizontal shake for errors. Plays once on mount and again whenever
// ``trigger`` changes. Reduced motion: no movement. For a plain element use className="rb-shake".
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export function Shake({ trigger, className, children }: { trigger?: unknown; className?: string; children: ReactNode }) {
  return <div key={String(trigger ?? '')} className={cn('rb-shake', className)}>{children}</div>
}
