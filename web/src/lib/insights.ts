// "What your data says": deterministic insights (server: insights.py). Oura-based ones are
// shown to the athlete only (marked uses_oura); coaches and Rabbit never get them.
import { useEffect, useState } from 'react'
import { getJSON, sendJSON } from '@/lib/api'
import { coachBase } from '@/lib/coach'

export type Impact = 'positive' | 'watch' | 'action'
export type InsightActionKind = 'apply_adjust' | 'open_plan' | 'open_session' | 'ask_rabbit' | 'ask_coach' | 'open_gear' | 'none'
export type InsightAction = {
  kind: InsightActionKind; label: string
  payload: { id?: string; session_id?: string; date?: string; text?: string; gear_id?: string }
}
export type Evidence = { kind: 'line' | 'bars' | 'meter'; values: number[]; labels: string[]; unit: string; target?: number }
export type Insight = {
  id: string; title: string; explanation: string; why: string; impact: Impact
  confidence: 'low' | 'medium' | 'high'; evidence: Evidence | null; action: InsightAction
  sources: string[]; uses_oura: boolean; fresh: boolean
}
export type Insights = { today: string; insights: Insight[]; total?: number }

export const getInsights = (fresh = false) => getJSON<Insights>(`/api/insights${fresh ? '?fresh=1' : ''}`)
export const getAthleteInsights = (aid: string) => getJSON<Insights>(`${coachBase(aid)}/insights`)
export const dismissInsight = (id: string, days?: number) =>
  sendJSON<{ ok: boolean; until: string }>('POST', `/api/insights/${encodeURIComponent(id)}/dismiss`, days ? { days } : {})

/** One line for the Today card: the top fresh "action" insight, if any (refetched per day). */
export function useTopInsight(day: string | null | undefined): string | null {
  const [line, setLine] = useState<string | null>(null)
  useEffect(() => {
    if (!day) return
    let live = true
    getInsights().then((r) => {
      const top = r.insights.find((i) => i.impact === 'action' && i.fresh)
      if (live) setLine(top ? top.title : null)
    }, () => { if (live) setLine(null) })
    return () => { live = false }
  }, [day])
  return line
}
