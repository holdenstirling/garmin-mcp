// Any name or avatar that should open that person's profile (lib/people openPerson). Use
// <PersonLink> around a name, <PersonAvatar> for a tappable photo, or `personProps(id)` to make
// an existing element tappable. Never for yourself (the Me page is the avatar in the header).
import type { ReactNode } from 'react'
import { Avatar } from '@/components/Avatar'
import { openPerson, personPhoto, type PersonRef } from '@/lib/people'
import { cn } from '@/lib/utils'

export function PersonLink({ id, name, children, className }: {
  id: string | null | undefined; name: string; children?: ReactNode; className?: string
}) {
  if (!id) return <span className={className}>{children ?? name}</span>
  return (
    <button type="button" onClick={(e) => { e.stopPropagation(); openPerson(id) }} aria-label={`Open ${name}'s profile`}
      className={cn('inline cursor-pointer text-left font-[inherit] text-inherit underline-offset-2 hover:underline', className)}>
      {children ?? name}
    </button>
  )
}

export function PersonAvatar({ p, size = 32, className }: { p: PersonRef | null | undefined; size?: number; className?: string }) {
  if (!p) return null
  return (
    <button type="button" onClick={(e) => { e.stopPropagation(); openPerson(p.id) }} aria-label={`Open ${p.name}'s profile`}
      className={cn('flex shrink-0 items-center justify-center rounded-full', size < 44 && 'hit-44', className)}>
      <Avatar name={p.name} picture={p.picture ?? ''} photo={personPhoto(p)} size={size} />
    </button>
  )
}
