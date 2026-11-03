// Home's one prompt slot: of everything that might want attention (a sync error, sick mode, race
// week, the setup checklist, connect your watch, rabbt's notes, the share question, a calendar or
// niggle nudge, the pulse survey, a tip) exactly one shows, the first that applies in priority
// order. The rest wait their turn, never a pile.
//
// A candidate is either known right away (`show: true | false`) or finds out for itself (`show`
// left undefined): it is mounted and reports back with `report(shown)`. Lower candidates are only
// mounted once every higher one has said no, so nothing below does its "seen it" side effects
// (a tip counted as seen, a question marked as asked) while it is hidden.
import { Fragment, useCallback, useState, type ReactNode } from 'react'

export type PromptCandidate = {
  id: string
  /** known now: true shows it (and stops), false skips it; undefined: it reports itself */
  show?: boolean
  render: (report: (shown: boolean) => void) => ReactNode
}

export function PromptSlot({ items }: { items: PromptCandidate[] }) {
  const [shown, setShown] = useState<Record<string, boolean>>({})
  const report = useCallback((id: string, v: boolean) => {
    setShown((s) => (s[id] === v ? s : { ...s, [id]: v }))
  }, [])
  const out: ReactNode[] = []
  for (const c of items) {
    if (c.show === false) continue
    const node = c.render((v) => report(c.id, v))
    if (c.show === true) { out.push(<Fragment key={c.id}>{node}</Fragment>); break }
    // Self-reporting: stays mounted (it may still come up later); the next one waits until it says no.
    out.push(<Fragment key={c.id}>{node}</Fragment>)
    if (shown[c.id] !== false) break
  }
  return <div className="flex flex-col gap-3 empty:hidden">{out}</div>
}
