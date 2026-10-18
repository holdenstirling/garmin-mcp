// One feed post on its own page, comments open: where a "mentioned you" notification (bell or
// push, ?open=post&id=..&c=..) lands. Scrolls to the comment and highlights it.
import { useCallback, useEffect, useState } from 'react'
import { Screen } from '@/components/plan/ui'
import { RabbitLoader } from '@/components/RabbitLoader'
import { ErrorState } from '@/components/ui/ErrorState'
import { getPost, type Post } from '@/lib/community'
import { PostCard } from './Feed'

export function PostScreen({ id, comment, imperial, onClose }: { id: string; comment?: string; imperial: boolean; onClose: () => void }) {
  const [post, setPost] = useState<Post | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [closing, setClosing] = useState(false)
  const close = () => { setClosing(true); window.setTimeout(onClose, 200) }
  const load = useCallback(() => {
    setError(null)
    getPost(id).then((r) => setPost(r.post), (e: Error) => setError(/not found/i.test(e.message) ? "This post isn't available anymore." : e.message))
  }, [id])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    if (!post || !comment) return
    const t = window.setTimeout(() => document.getElementById(`comment-${comment}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' }), 250)
    return () => window.clearTimeout(t)
  }, [post, comment])
  const who = post?.mine ? 'Your post' : post?.user?.name ? `${post.user.name.split(' ')[0]}'s post` : 'Post'
  return (
    <Screen title={who} onClose={close} closing={closing}>
      <div className="flex flex-col gap-3 pb-[max(24px,env(safe-area-inset-bottom))]">
        {error ? <ErrorState message={error} onRetry={/not available/.test(error) ? undefined : load} />
          : !post ? <RabbitLoader className="py-16" label="Loading the post" />
          : <PostCard post={post} imperial={imperial} expanded focusComment={comment}
              onChange={setPost} onDelete={close} onBlocked={close} />}
      </div>
    </Screen>
  )
}
