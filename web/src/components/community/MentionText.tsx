// Post and comment text with @mentions as bold links to the person's profile (current name).
// Tokens that aren't in the item's own `mentions` list read as plain "@Name".
import { openPerson } from '@/lib/people'
import { segments, type Mention } from '@/lib/mentions'

export function MentionText({ text, mentions, className }: { text: string; mentions?: Mention[]; className?: string }) {
  const parts = segments(text, mentions)
  return (
    <span className={className}>
      {parts.map((s, i) => 'mention' in s ? (
        <button key={i} type="button" onClick={(e) => { e.stopPropagation(); openPerson(s.mention.id) }}
          aria-label={`Open ${s.mention.name}'s profile`}
          className="inline cursor-pointer p-0 font-semibold text-(--accent) underline-offset-2 hover:underline">{s.label}</button>
      ) : <span key={i}>{s.text}</span>)}
    </span>
  )
}
