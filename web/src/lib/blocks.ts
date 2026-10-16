// Shared training blocks (server: blocks.py, routes blocks_web.py): friends or a club start the
// same N-week block; each member trains on their own plan from the plan builder.
import { getJSON, postJSON, sendJSON } from '@/lib/api'
import type { SocialUser } from '@/lib/social'

export type Feel = 'strong' | 'okay' | 'tough'
export const FEELS: [Feel, string][] = [['strong', '💪 Strong'], ['okay', '🙂 Okay'], ['tough', '😮‍💨 Tough']]
export const FEEL_LABEL = Object.fromEntries(FEELS) as Record<Feel, string>

export type BlockWeek = { n: number; of: number; monday: string; state: 'upcoming' | 'active' | 'done'; days_to_start?: number }
export type BlockSummary = {
  id: string; name: string; template: string; start: string; end: string; weeks: number
  week: BlockWeek; status: 'active' | 'ended'; members: number; owner: boolean
  event: { name: string; date: string; distance?: string } | null
  club: { id: string; name: string } | null
  me: { done: number; target: number } | null
  closed: number
  invited_by?: SocialUser | null
}
export type BlockPerson = {
  user_id: string; name: string; me: boolean; owner: boolean; user: SocialUser | null
  done: number | null; target: number | null; closed: boolean; behind: boolean; cheered: boolean
}
export type BlockCheckin = { user_id: string; name: string; me: boolean; user: SocialUser | null; feel: Feel; note: string; ts: number }
export type BlockDetail = BlockSummary & {
  member: boolean
  people?: BlockPerson[]
  group?: { done: number; target: number; pct: number; closed: number; count: number }
  checkins?: BlockCheckin[]; last_checkins?: BlockCheckin[]
  my_checkin?: { feel: Feel; note: string; ts: number } | null
  checkins_on?: boolean; plan?: 'new' | 'keep'
  cheers?: { name: string; day: string }[]
  invited?: (SocialUser | null)[]
  /** Community feed id for this block's posts ("b-<id>") */
  feed?: string
}
export type BlocksOverview = {
  blocks: BlockSummary[]; invites: BlockSummary[]; clubs: BlockSummary[]; active: number; max_active: number
}
export type BlockTemplate = { id: string; name: string; weeks: number; blurb: string }
export type BlockNew = {
  templates: BlockTemplate[]
  races: { id: string; name: string; date: string; distance: string; weeks: number }[]
  starts: string[]; max_members: number; max_active: number
  friends: SocialUser[]; clubs: { id: string; name: string }[]
  current: { goal: string | null; has_plan: boolean; has_goal: boolean }
}
export type PlanChoice = { plan?: 'new' | 'keep'; confirm_replace?: boolean }
export type CreateBody = PlanChoice & {
  template: string; start: string; event_id?: string; name?: string; invite?: string[]; club?: string | null
}

export const getBlocks = () => getJSON<BlocksOverview>('/api/blocks')
export const getBlockNew = () => getJSON<BlockNew>('/api/blocks/new')
export const getBlock = (id: string) => getJSON<{ block: BlockDetail }>(`/api/blocks/${id}`)
export const createBlock = (b: CreateBody) => postJSON<{ block: BlockDetail; invited: string[]; plan: string }>('/api/blocks', b)
export const joinBlock = (id: string, c: PlanChoice) => postJSON<{ block: BlockDetail; plan: string }>(`/api/blocks/${id}/join`, c)
export const declineBlock = (id: string) => postJSON(`/api/blocks/${id}/decline`)
export const inviteToBlock = (id: string, ids: string[]) => postJSON<{ block: BlockDetail }>(`/api/blocks/${id}/invite`, { user_ids: ids })
export const leaveBlock = (id: string) => postJSON(`/api/blocks/${id}/leave`)
export const endBlock = (id: string) => postJSON(`/api/blocks/${id}/end`)
export const checkinBlock = (id: string, feel: Feel, note?: string) =>
  postJSON<{ block: BlockDetail }>(`/api/blocks/${id}/checkin`, { feel, note: note ?? '' })
export const setBlockCheckins = (id: string, on: boolean) => sendJSON('PUT', `/api/blocks/${id}/checkins`, { on })
export const nudgeInBlock = (id: string, userId: string) => postJSON(`/api/blocks/${id}/nudge`, { user_id: userId })

/** 409 ``code: confirm_plan``: they already have a goal; ask keep vs replace. */
export const needsPlanChoice = (e: unknown) => (e as { code?: string })?.code === 'confirm_plan'

export const weekLine = (w: BlockWeek) =>
  w.state === 'upcoming' ? `Starts ${fmtDay(w.monday)}` : w.state === 'done' ? `Finished · ${w.of} weeks` : `Week ${w.n} of ${w.of}`

export function fmtDay(iso: string): string {
  const d = new Date(`${iso}T12:00:00`)
  return d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })
}

// Open a block page from anywhere (Plan, Community, a moment): Chat.tsx listens and shows it.
export const OPEN_BLOCK_EVENT = 'rabbit:open-block'
/** ``id``: a block, or "new" for the create flow. */
export function openBlock(id: string = 'new'): void {
  window.dispatchEvent(new CustomEvent<string>(OPEN_BLOCK_EVENT, { detail: id }))
}

/** A Rabbit moment's block chip: "View invite"/"Open block" opens the page; a feel chip
 *  answers the Sunday check-in in one tap, then opens the page (to add a note). */
export async function blockMomentAction(a: { id: string; block_id?: string; feel?: string }): Promise<string | null> {
  if (!a.block_id) return null
  if (a.id === 'block_checkin' && a.feel && a.feel in FEEL_LABEL) {
    await checkinBlock(a.block_id, a.feel as Feel)
    openBlock(a.block_id)
    return 'Shared with your crew'
  }
  openBlock(a.block_id)
  return null
}
