// Comments under a feed post: one-level threads (replies indented under the comment they
// answer, "View N replies" past two), a heart with a count on every comment (tap the count to
// see who), Reply, and Edit/Delete for your own (the post's author can delete any). Names are
// bold, the time is quiet, text is 16px, and every action is a 44px target.
import { useEffect, useState } from 'react'
import { Ellipsis, Heart, Pencil, Trash2 } from 'lucide-react'
import { Avatar } from '@/components/Avatar'
import { Sheet } from '@/components/ui/Sheet'
import { RabbitLoader } from '@/components/RabbitLoader'
import { PersonAvatar, PersonLink } from '@/components/people/PersonLink'
import { ago, commentLikers, type Post, type PostComment } from '@/lib/community'
import { openPerson, personPhoto } from '@/lib/people'
import type { SocialUser } from '@/lib/social'
import { cn } from '@/lib/utils'
import { MentionText } from './MentionText'

/** Top-level comments with their replies, oldest first. A reply whose parent isn't loaded
 * (the feed preview) shows on its own. */
export function threadsOf(comments: PostComment[]): { top: PostComment; replies: PostComment[] }[] {
  const ids = new Set(comments.map((c) => c.id))
  return comments.filter((c) => !c.parent || !ids.has(c.parent))
    .map((top) => ({ top, replies: comments.filter((c) => c.parent === top.id) }))
}

export type CommentActions = {
  onReply: (c: PostComment, thread: PostComment) => void
  onLike: (c: PostComment) => void
  onDelete: (c: PostComment) => void
  onEdit: (c: PostComment) => void
}

export function CommentThreads({ post, threads, focus, actions, className }: {
  post: Post; threads: { top: PostComment; replies: PostComment[] }[]; focus?: string; actions: CommentActions; className?: string
}) {
  const [open, setOpen] = useState<Set<string>>(() => new Set(focus ? [focus] : []))
  return (
    <ul className={cn('flex flex-col gap-4', className)} aria-label="Comments">
      {threads.map(({ top, replies }) => {
        const many = replies.length > 2
        const shown = many && !open.has(top.id) && !replies.some((r) => r.id === focus) ? replies.slice(-1) : replies
        const hidden = replies.length - shown.length
        return (
          <li key={top.id} className="flex flex-col gap-3">
            <CommentItem c={top} focused={focus === top.id} post={post} actions={actions} thread={top} />
            {replies.length > 0 && (
              <ul className="ml-[18px] flex flex-col gap-3 border-l-2 border-(--border) pl-4" aria-label={`Replies to ${top.mine ? 'your comment' : top.by.name}`}>
                {hidden > 0 && (
                  <li>
                    <button type="button" onClick={() => setOpen((s) => new Set(s).add(top.id))}
                      className="hit-44 text-meta font-semibold text-(--accent)">
                      View {hidden} more {hidden === 1 ? 'reply' : 'replies'}
                    </button>
                  </li>
                )}
                {shown.map((r) => (
                  <li key={r.id}><CommentItem c={r} focused={focus === r.id} post={post} actions={actions} thread={top} small /></li>
                ))}
              </ul>
            )}
          </li>
        )
      })}
    </ul>
  )
}

function CommentItem({ c, post, actions, thread, focused, small }: {
  c: PostComment; post: Post; actions: CommentActions; thread: PostComment; focused?: boolean; small?: boolean
}) {
  const [menu, setMenu] = useState(false)
  const [likers, setLikers] = useState(false)
  const n = c.like_count ?? 0
  const size = small ? 28 : 32
  return (
    <div id={`comment-${c.id}`} className={cn('flex scroll-mt-24 items-start gap-3 rounded-xl', focused && 'comment-focus')}>
      {c.mine ? <Avatar name="You" picture={c.by.picture ?? ''} photo={personPhoto(c.by)} size={size} />
        : <PersonAvatar p={c.by} size={size} />}
      <div className="min-w-0 flex-1">
        <p className="m-0 flex flex-wrap items-baseline gap-x-2">
          {c.mine ? <span className="text-body font-semibold text-(--text)">You</span>
            : <PersonLink id={c.by.id} name={c.by.name} className="text-body font-semibold text-(--text)" />}
          <span className="text-caption text-(--text-muted)">{ago(c.ts)}{c.edited ? ', edited' : ''}</span>
        </p>
        <p className="m-0 mt-0.5 whitespace-pre-wrap break-words text-body leading-normal text-(--text)">
          <MentionText text={c.text} mentions={c.mentions} />
        </p>
        <div className="-ml-2 mt-1 flex items-center gap-1">
          <button type="button" aria-pressed={!!c.liked} onClick={() => actions.onLike(c)}
            aria-label={c.liked ? 'Unlike comment' : 'Like comment'}
            className={cn('inline-flex min-h-11 items-center gap-1.5 rounded-full px-2 text-meta font-semibold',
              c.liked ? 'text-(--danger)' : 'text-(--text-secondary) active:bg-(--bg-inset)')}>
            <Heart className={cn('size-5', c.liked && 'fill-current')} aria-hidden />
            {c.liked ? 'Liked' : 'Like'}
          </button>
          {n > 0 && (
            <button type="button" onClick={() => setLikers(true)} aria-label={`${n} ${n === 1 ? 'like' : 'likes'}: see who`}
              className="inline-flex min-h-11 items-center rounded-full px-2 text-meta text-(--text-muted) underline-offset-2 active:bg-(--bg-inset)">
              {n} {n === 1 ? 'like' : 'likes'}
            </button>
          )}
          <button type="button" onClick={() => actions.onReply(c, thread)}
            className="inline-flex min-h-11 items-center rounded-full px-2 text-meta font-semibold text-(--text-secondary) active:bg-(--bg-inset)">
            Reply
          </button>
          {(c.can_edit || c.can_delete) && (
            <div className="relative ml-auto">
              <button type="button" aria-label="Comment options" aria-expanded={menu} onClick={() => setMenu((m) => !m)}
                className="flex size-11 items-center justify-center rounded-full text-(--text-muted) active:bg-(--bg-inset)">
                <Ellipsis className="size-5" aria-hidden />
              </button>
              {menu && (
                <div role="menu" className="absolute bottom-11 right-0 z-10 flex w-44 flex-col rounded-xl border border-(--border) bg-(--bg-surface) py-1 shadow-lg">
                  {c.can_edit && (
                    <button type="button" role="menuitem" onClick={() => { setMenu(false); actions.onEdit(c) }}
                      className="flex min-h-11 items-center gap-2.5 px-3.5 text-left text-body">
                      <Pencil className="size-5" aria-hidden /> Edit
                    </button>
                  )}
                  {c.can_delete && (
                    <button type="button" role="menuitem" onClick={() => { setMenu(false); actions.onDelete(c) }}
                      className="flex min-h-11 items-center gap-2.5 px-3.5 text-left text-body text-(--danger)">
                      <Trash2 className="size-5" aria-hidden /> Delete
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      {likers && <LikersSheet pid={post.id} cid={c.id} onClose={() => setLikers(false)} />}
    </div>
  )
}

function LikersSheet({ pid, cid, onClose }: { pid: string; cid: string; onClose: () => void }) {
  const [people, setPeople] = useState<SocialUser[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    commentLikers(pid, cid).then((r) => { if (live) setPeople(r.people) }, (e: Error) => { if (live) setErr(e.message) })
    return () => { live = false }
  }, [pid, cid])
  return (
    <Sheet title="Liked by" onClose={onClose} portal>
      {err ? <p className="text-body text-(--danger)">{err}</p>
        : !people ? <RabbitLoader className="py-8" label="Loading" />
        : people.length === 0 ? <p className="text-body text-(--text-muted)">No likes yet.</p>
        : (
          <ul className="flex flex-col">
            {people.map((u) => (
              <li key={u.id}>
                <button type="button" onClick={() => { onClose(); openPerson(u.id) }}
                  className="flex min-h-14 w-full items-center gap-3 py-2 text-left active:bg-(--bg-inset)">
                  <Avatar name={u.name} picture={u.picture ?? ''} photo={personPhoto(u)} size={40} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-body-lg font-semibold text-(--text)">{u.name}</span>
                    {u.handle && <span className="block text-meta text-(--text-muted)">@{u.handle}</span>}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
    </Sheet>
  )
}
