// The plan, opened from the coach log's pinned plan bar: where you are in it, Rabbit's
// summary, the original files, and a way to ask about it. Edits live in "What Rabbit knows".
import { RabbitMarkdown } from '@/components/chat/RabbitText'
import { FileText, MessageCircle, Pencil } from 'lucide-react'
import { RabbitLogo } from '@/components/RabbitLogo'
import { Button } from '@/components/ui/button'
import { Group, Icon, Row } from '@/components/settings/Grouped'
import { ATTACH_INPUT_ID } from '@/components/chat/Composer'
import { planLine } from '@/components/chat/PlanPins'
import { attachmentUrl, formatFileSize } from '@/lib/attachments'
import type { Goal, PlanWeek } from '@/lib/api'
import { Sheet } from '@/components/ui/Sheet'

export function PlanSheet({ goal, week, onAsk, onUploadPlan, onEdit, onBuild, onClose, onDismissed, closing }: {
  goal: Goal; week: PlanWeek | null
  onAsk: () => void; onUploadPlan: () => void; onEdit: () => void; onBuild: () => void
  onClose: () => void; onDismissed: () => void; closing: boolean
}) {
  const files = goal.plan_files ?? []
  const raceDay = goal.date
    ? new Date(`${goal.date}T12:00:00`).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
    : null

  return (
    <Sheet title="Your plan" onClose={onClose} closing={closing} onDismissed={onDismissed} bodyClassName="settings flex flex-col gap-5 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
          <div className="px-1">
            <p className="font-display text-[1.2941rem] leading-tight text-(--brand)">{goal.title}</p>
            <p className="mt-1 text-[0.7647rem] text-(--text-muted)">
              {[raceDay, planLine(week, goal)].filter(Boolean).join(' · ')}
            </p>
          </div>

          <div className="flex gap-2">
            <Button variant="primary" className="h-10 flex-1 gap-1.5" onClick={onAsk}>
              <MessageCircle className="size-4" /> Ask about my plan
            </Button>
            {goal.plan && (
              <Button variant="outline" size="icon" className="size-10" aria-label="Edit plan" onClick={onEdit}>
                <Pencil className="size-4" />
              </Button>
            )}
          </div>

          <Group footer={goal.plan ? 'Replaces this plan with one built from your answers. You can sync it to Garmin.' : 'Answer a few questions and get a week-by-week plan you can sync to Garmin.'}>
            <Row icon={<Icon><RabbitLogo current /></Icon>} title="Build a plan in Rabbit" subtitle="Race, goals, you and your week" onClick={onBuild} />
          </Group>

          {files.length > 0 && (
            <Group label="Plan files">
              {files.map((f) => (
                <a key={f.id} href={attachmentUrl(f.id)} target="_blank" rel="noopener"
                  className="flex items-center gap-3 px-4 py-2.5 active:bg-(--bg-inset)">
                  <Icon><FileText /></Icon>
                  <span className="min-w-0 flex-1 truncate text-[0.8824rem] text-(--text)">{f.name}</span>
                  <span className="shrink-0 text-[0.7059rem] text-(--text-muted)">{formatFileSize(f.size)}</span>
                </a>
              ))}
            </Group>
          )}

          <Group label="Rabbit's summary"
            footer={<label htmlFor={ATTACH_INPUT_ID} onClick={onUploadPlan} className="cursor-pointer text-(--accent)">
              {goal.plan ? 'Send an updated plan' : 'Upload my plan'}</label>}>
            {goal.plan ? (
              <div className="chat-text px-4 py-3 text-[0.9412rem]">
                <RabbitMarkdown text={goal.plan} className="rabbit-md--doc" />
              </div>
            ) : (
              <p className="px-4 py-3 text-[0.8235rem] text-(--text-muted)">
                No plan yet. Upload it (a PDF or screenshots) or describe it to Rabbit, and this week's sessions will show up on your Schedule.
              </p>
            )}
          </Group>
    </Sheet>
  )
}
