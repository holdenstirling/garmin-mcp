// "People" in the Chats sheet: direct messages with friends and club mates, newest first, with
// message requests on top and a "New message" button.
import { useCallback, useEffect, useState } from 'react'
import { BellOff, SquarePen, Users } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { RabbitLoader } from '@/components/RabbitLoader'
import { EmptyState } from '@/components/ui/EmptyState'
import { PersonAvatar } from '@/components/community/Feed'
import { DM_CHANGED_EVENT, convTitle, listConvs, timeAgo, type DMConv } from '@/lib/dm'
import { cn } from '@/lib/utils'

function ConvAvatar({ c }: { c: DMConv }) {
  if (c.kind === 'group' || c.members.length !== 1) {
    return (
      <span className="flex size-11 shrink-0 items-center justify-center rounded-full bg-(--accent-subtle) text-(--accent)" aria-hidden>
        <Users className="size-5" />
      </span>
    )
  }
  return <PersonAvatar u={{ ...c.members[0]!, photo: c.members[0]!.photo ?? null, picture: c.members[0]!.picture ?? '' }} size={44} />
}

export function ConvRow({ c, onOpen }: { c: DMConv; onOpen: (id: string) => void }) {
  const title = convTitle(c)
  const preview = c.last?.preview ? `${c.last.mine ? 'You: ' : ''}${c.last.preview}` : c.status === 'request' ? 'Wants to message you' : 'Say hi 👋'
  return (
    <li>
      <button type="button" onClick={() => onOpen(c.id)}
        aria-label={`${title}${c.unread ? ', unread' : ''}. ${preview}`}
        className="flex min-h-16 w-full items-center gap-3 px-4 py-2.5 text-left active:bg-(--bg-inset)">
        <ConvAvatar c={c} />
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2">
            <span className={cn('min-w-0 flex-1 truncate text-[0.8824rem] text-(--text)', c.unread && 'font-semibold')}>{title}</span>
            <span className="shrink-0 text-[0.6471rem] text-(--text-muted)">{timeAgo(c.last?.ts ?? c.created)}</span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className={cn('min-w-0 flex-1 truncate text-[0.7647rem]', c.unread ? 'text-(--text)' : 'text-(--text-muted)')}>{preview}</span>
            {c.muted && <BellOff className="size-3.5 shrink-0 text-(--text-muted)" aria-label="Muted" />}
            {c.unread && <span className="size-2.5 shrink-0 rounded-full bg-(--accent)" aria-hidden />}
          </span>
        </span>
      </button>
    </li>
  )
}

export function DmList({ onOpen, onNew }: { onOpen: (id: string) => void; onNew: () => void }) {
  const [data, setData] = useState<{ convs: DMConv[]; requests: DMConv[] } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(() => { listConvs().then((d) => { setData(d); setError(null) }, (e: Error) => setError(e.message)) }, [])
  useEffect(() => {
    load()
    window.addEventListener(DM_CHANGED_EVENT, load)
    return () => window.removeEventListener(DM_CHANGED_EVENT, load)
  }, [load])

  return (
    <div className="flex flex-col">
      <div className="px-4 pb-2 pt-1">
        <Button variant="primary" className="h-11 w-full gap-1.5 text-[0.8235rem]" onClick={onNew}>
          <SquarePen className="size-4" aria-hidden /> New message
        </Button>
      </div>
      {error && !data ? (
        <p className="px-4 py-6 text-center text-[0.7647rem] text-(--text-muted)">
          Couldn't load messages. <button type="button" className="hit-44 underline" onClick={load}>Retry</button>
        </p>
      ) : !data ? (
        <RabbitLoader className="py-8" label="Loading messages" />
      ) : (
        <>
          {data.requests.length > 0 && (
            <section aria-label="Message requests">
              <h3 className="section-label px-4 pb-1 pt-3">Requests · {data.requests.length}</h3>
              <ul className="divide-y divide-(--border)">{data.requests.map((c) => <ConvRow key={c.id} c={c} onOpen={onOpen} />)}</ul>
            </section>
          )}
          {data.convs.length > 0 ? (
            <section aria-label="Conversations">
              {data.requests.length > 0 && <h3 className="section-label px-4 pb-1 pt-3">Chats</h3>}
              <ul className="divide-y divide-(--border)">{data.convs.map((c) => <ConvRow key={c.id} c={c} onOpen={onOpen} />)}</ul>
            </section>
          ) : data.requests.length === 0 && (
            <EmptyState compact title="No messages yet"
              body="Message a friend or a club mate: plan a long run, send them a workout, or just cheer them on."
              action="New message" onAction={onNew} />
          )}
        </>
      )}
    </div>
  )
}
