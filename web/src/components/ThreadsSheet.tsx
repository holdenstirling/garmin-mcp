// Ported from Dolly's ConversationList (web-mcp): same rows, relative times and delete
// confirmation; the pinned Rabbit thread (briefs, workout notes) sits on top. No virtualization needed at this size.
import { useDialog } from '@/hooks/useDialog'
import { useRef, useState } from 'react'
import { MessageSquarePlus, Pin, Trash2 } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/button'
import type { Goal, Thread } from '@/lib/api'
import { Segmented } from '@/components/nav/Segmented'
import { DmList } from '@/components/dm/DmList'

function formatRelativeTime(ts: number): string {
  const diffMs = Date.now() - ts * 1000
  const min = Math.floor(diffMs / 60_000)
  const hr = Math.floor(diffMs / 3_600_000)
  const days = Math.floor(diffMs / 86_400_000)
  if (min < 1) return 'Just now'
  if (min < 60) return `${min}m ago`
  if (hr < 24) return `${hr}h ago`
  if (days < 7) return `${days}d ago`
  return new Date(ts * 1000).toLocaleDateString()
}

export function ThreadsSheet({ goal, threads, activeId, onSelect, onNew, onDelete, onEditGoal, onClose, onDismissed, closing,
  view = 'rabbit', onView, onOpenDm, onNewDm, dmUnread = 0 }: {
  goal: Goal | null; threads: Thread[]; activeId: string | null
  onSelect: (id: string) => void; onNew: () => void; onDelete: (id: string) => void
  onEditGoal: () => void; onClose: () => void; onDismissed: () => void; closing: boolean
  /** Rabbit chats or direct messages with people (athletes only: no onView = Rabbit only) */
  view?: 'rabbit' | 'people'; onView?: (v: 'rabbit' | 'people') => void
  onOpenDm?: (id: string) => void; onNewDm?: () => void; dmUnread?: number
}) {
  const [deleteTarget, setDeleteTarget] = useState<Thread | null>(null)
  const people = view === 'people' && !!onView
  return (
    <Sheet closing={closing} onClose={onClose} onDismissed={onDismissed}
      bodyClassName="min-h-0 flex-1 gap-0 p-0 pb-[max(12px,env(safe-area-inset-bottom))]"
      header={
        <div className="min-w-0">
          <h2 className="modal-title truncate">{people ? 'Messages' : 'Chats with rabbt'}</h2>
          <button type="button" className="hit-44 max-w-full text-left text-small leading-snug text-muted-foreground underline-offset-2 hover:underline" onClick={onEditGoal}>
            {goal ? `Training for ${goal.title}` : 'Set what you’re training for'}
          </button>
        </div>
      }
      actions={
        <button className="modal-close" aria-label={people ? 'New message' : 'New chat with rabbt'} title={people ? 'New message' : 'New chat'}
          onClick={people ? onNewDm : onNew}>
          <MessageSquarePlus className="size-5" />
        </button>
      }
      below={onView && (
        <div className="px-5 pb-2">
          <Segmented label="Messages" value={view} onChange={onView}
            options={[['people', dmUnread > 0 ? `Friends · ${dmUnread}` : 'Friends'], ['rabbit', 'rabbt chats']] as const} />
        </div>
      )}
      extra={deleteTarget && (
        <ConfirmDelete title={deleteTarget.title || 'New chat'} onCancel={() => setDeleteTarget(null)}
          onConfirm={() => { onDelete(deleteTarget.id); setDeleteTarget(null) }} />
      )}>
          {people && onOpenDm && onNewDm ? <DmList onOpen={onOpenDm} onNew={onNewDm} /> : threads.map((t) => (
            <div key={t.id} role="button" tabIndex={0} onClick={() => onSelect(t.id)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(t.id) } }}
              className={`group flex min-h-16 w-full cursor-pointer items-center gap-3 border-b border-(--border) px-5 py-3.5 text-left transition-colors hover:bg-muted/50 active:bg-(--bg-inset) ${activeId === t.id ? 'bg-muted' : ''}`}>
              {t.kind === 'coach' && <Pin className="size-5 shrink-0 text-(--accent)" />}
              <div className="min-w-0 flex-1">
                <p className="line-clamp-2 text-body-lg font-medium leading-snug">
                  {t.kind === 'coach' ? 'rabbt' : t.title || 'New chat'}
                </p>
                <p className="mt-0.5 text-small text-muted-foreground">
                  {t.kind === 'coach' ? 'Briefs, workout notes and chats you started' : formatRelativeTime(t.updated)}
                </p>
              </div>
              {t.kind === 'topic' && (
                <button onClick={(e) => { e.stopPropagation(); setDeleteTarget(t) }}
                  className="flex size-11 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted"
                  title="Delete" aria-label="Delete chat">
                  <Trash2 className="size-5" />
                </button>
              )}
            </div>
          ))}
    </Sheet>
  )
}

/** "Delete chat?" A small alert dialog: focus in, Escape cancels, focus returns. */
function ConfirmDelete({ title, onCancel, onConfirm }: { title: string; onCancel: () => void; onConfirm: () => void }) {
  const box = useRef<HTMLDivElement>(null)
  useDialog(box, onCancel)
  return (
    <div className="fixed inset-0 z-(--z-dialog) flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onCancel} />
      <div ref={box} role="alertdialog" aria-modal="true" aria-labelledby="del-chat-title" aria-describedby="del-chat-desc"
        className="relative z-10 mx-4 w-full max-w-sm rounded-lg border bg-background p-5 shadow-lg">
        <h3 id="del-chat-title" className="text-body font-semibold text-foreground">Delete chat?</h3>
        <p id="del-chat-desc" className="mt-1.5 text-body text-muted-foreground">
          <span className="font-medium text-foreground">{title}</span> will be permanently deleted.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" className="h-11" onClick={onCancel}>Cancel</Button>
          <Button variant="destructive" className="h-11" onClick={onConfirm}>Delete</Button>
        </div>
      </div>
    </div>
  )
}
