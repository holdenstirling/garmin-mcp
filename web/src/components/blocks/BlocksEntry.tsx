// "Train together" on the Plan tab and in Community: my shared training blocks (week N of M,
// my sessions this week), invites waiting for me, blocks open to my clubs, and the one way to
// start a new block with friends. Each opens the block page (lib/blocks openBlock).
import { useEffect, useState } from 'react'
import { ChevronRight, Users } from 'lucide-react'
import { Group, Icon, Row } from '@/components/settings/Grouped'
import { WeekRing } from '@/components/progress/Progress'
import { getBlocks, openBlock, weekLine, type BlockSummary, type BlocksOverview } from '@/lib/blocks'

export function BlocksEntry({ compact = false }: {
  /** no explainer footer (Community, a built plan's page) */
  compact?: boolean
}) {
  const [o, setO] = useState<BlocksOverview | null>(null)
  useEffect(() => {
    let live = true
    getBlocks().then((r) => { if (live) setO(r) }, () => { /* a bonus row: hide on error */ })
    return () => { live = false }
  }, [])
  const live = (o?.blocks ?? []).filter((b) => b.status === 'active' && b.week.state !== 'done')
  const waiting = [...(o?.invites ?? []), ...(o?.clubs ?? [])]
  const full = !!o && o.active >= o.max_active
  return (
    <Group label="Train together"
      footer={!compact && live.length === 0 ? 'Same weeks, your own plan. Check in on Sundays and cheer each other on.' : undefined}>
      {live.map((b) => <BlockRow key={b.id} b={b} />)}
      {waiting.map((b) => (
        <Row key={b.id} icon={<Icon><Users /></Icon>}
          title={b.name}
          subtitle={b.invited_by ? `${b.invited_by.name} invited you · ${weekLine(b.week)}` : `${b.club?.name ?? 'Your club'} · ${weekLine(b.week)}`}
          onClick={() => openBlock(b.id)} />
      ))}
      <Row icon={<Icon><Users /></Icon>} title="Start a block with friends"
        subtitle={full ? `You're in ${o?.max_active} blocks. Finish or leave one first.` : 'Pick a block, a start Monday and your crew'}
        disabled={full} onClick={() => openBlock('new')} />
    </Group>
  )
}

function BlockRow({ b }: { b: BlockSummary }) {
  return (
    <button type="button" onClick={() => openBlock(b.id)}
      className="settings-row flex w-full items-center gap-3 px-4 py-3 text-left transition-colors active:bg-(--bg-inset)">
      {b.me ? <WeekRing done={b.me.done} target={b.me.target} size={36} />
        : <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-(--accent-subtle) text-(--accent)"><Users className="size-4" /></span>}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[0.9412rem] leading-snug text-(--text)">{b.name}</span>
        <span className="mt-0.5 block text-[0.7647rem] leading-snug text-(--text-muted)">
          {weekLine(b.week)} · {b.members} {b.members === 1 ? 'person' : 'people'}
          {b.week.state === 'active' && b.members > 1 ? ` · ${b.closed} closed` : ''}
        </span>
      </span>
      <ChevronRight className="size-4 shrink-0 text-(--text-muted)" />
    </button>
  )
}
