// A person's round photo on community surfaces (Feed cards, the waiting row, DMs). Its own
// module so small pieces (WaitingRow, FriendsScreen's ask button) don't import the whole Feed
// and Feed <-> WaitingRow isn't an import cycle.
import { Avatar } from '@/components/Avatar'
import { communityPhotoUrl } from '@/lib/community'
import type { SocialUser } from '@/lib/social'

export function PersonAvatar({ u, size = 36 }: { u: SocialUser | null; size?: number }) {
  return <Avatar name={u?.name ?? '?'} picture={u?.picture ?? ''} photo={u ? communityPhotoUrl(u) : null} size={size} />
}
