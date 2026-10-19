// Empty-chat hero: logo + heading, with suggestion buttons under it, all in the normal flow so
// nothing can slide up under the Home / Chat switch on a short phone. The parent scrolls when
// the group doesn't fit and centers it when it does (`my-auto` inside an overflow container).
// While typing, the suggestions step aside (html.kb-open) so the composer has the room.
export function EmptyHero({ children, suggestions, gap = 16 }: {
  children: React.ReactNode
  suggestions?: React.ReactNode
  gap?: number
}) {
  return (
    <div className="empty-hero my-auto flex w-full flex-col items-center py-6">
      {children}
      {suggestions && (
        <div style={{ marginTop: gap }} className="chat-suggestions flex w-full max-w-[340px] flex-col gap-2.5">
          {suggestions}
        </div>
      )}
    </div>
  )
}
