// Me -> Partners (owners only; server partners.py). Add, edit or remove the local clubs and shops
// Rabbit promotes to people in their cities. Partners always show labelled "Partner": at the top of
// Clubs near you, pinned in club search and in Search everywhere. Each row shows whether it's live
// and its anonymous counts for the last 30 days (views, link taps, "I'm interested").
import { useCallback, useEffect, useState } from 'react'
import { ChevronRight, Plus, Trash2 } from 'lucide-react'
import { Field, Screen, areaCls, inputCls } from '@/components/plan/ui'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { RowsSkeleton } from '@/components/ui/Skeleton'
import { Monogram, PartnerBadge } from '@/components/community/Partners'
import {
  addPartner, editPartner, listPartnersAdmin, removePartner,
  type PartnerAdmin, type PartnerAdminList, type PartnerDraft, type PartnerKind,
} from '@/lib/clubdir'
import { cn } from '@/lib/utils'

const PLACE_LABEL: Record<string, string> = {
  local: 'Local', home: 'Home', discover: 'Discover', explore: 'Explore', directory_empty: 'Empty club list', search: 'Search',
}

const EMPTY: PartnerDraft = {
  name: '', kind: 'run_club', tagline: '', description: '', schedule: '', website: '', instagram: '', signup: '',
  metros: [], starts: null, ends: null, active: true, sponsored: true,
}

function draftOf(p: PartnerAdmin): PartnerDraft {
  return {
    name: p.name, kind: p.kind, tagline: p.tagline, description: p.description, schedule: p.schedule,
    website: p.website, instagram: p.instagram, signup: p.signup,
    metros: p.metros.map((m) => `${m.city}, ${m.state}`), starts: p.starts, ends: p.ends, active: p.active,
    sponsored: p.sponsored !== false,
  }
}

function PartnerForm({ p, kinds, onSaved, onClose }: {
  p: PartnerAdmin | null; kinds: PartnerAdminList['kinds']; onSaved: (l: PartnerAdminList) => void; onClose: () => void
}) {
  const [d, setD] = useState<PartnerDraft>(p ? draftOf(p) : EMPTY)
  const [cities, setCities] = useState((p ? draftOf(p).metros : ['Denver, CO']).join('\n'))
  const [busy, setBusy] = useState<'save' | 'delete' | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const set = <K extends keyof PartnerDraft>(k: K, v: PartnerDraft[K]) => setD((x) => ({ ...x, [k]: v }))
  async function save() {
    setBusy('save'); setErr(null)
    const body = { ...d, metros: cities.split('\n').map((c) => c.trim()).filter(Boolean) }
    try { onSaved(p ? await editPartner(p.id, body) : await addPartner(body)); onClose() }
    catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }
  async function remove() {
    if (!p) return
    setBusy('delete'); setErr(null)
    try { onSaved(await removePartner(p.id)); onClose() } catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }
  return (
    <Sheet title={p ? `Edit ${p.name}` : 'Add a partner'} onClose={onClose} portal
      footer={
        <div className="flex gap-2 border-t border-(--border) bg-(--bg) px-4 pt-3 pb-[max(12px,env(safe-area-inset-bottom))]">
          {p && (
            <Button variant="reject" className="h-11 gap-1.5 px-4 text-body" loading={busy === 'delete'} onClick={() => void remove()}>
              <Trash2 className="size-5" aria-hidden /> Remove
            </Button>
          )}
          <Button variant="primary" className="h-11 flex-1 text-body" loading={busy === 'save'} disabled={!d.name.trim()} onClick={() => void save()}>
            {p ? 'Save' : 'Add partner'}
          </Button>
        </div>
      }>
      <Field label="Name"><input className={inputCls} maxLength={60} value={d.name} onChange={(e) => set('name', e.target.value)} placeholder="5280 Runners" /></Field>
      <Field label="Kind">
        <select className={inputCls} value={d.kind} onChange={(e) => set('kind', e.target.value as PartnerKind)}>
          {kinds.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
        </select>
      </Field>
      <Field label="Tagline" hint="One short line, like their own slogan."><input className={inputCls} maxLength={80} value={d.tagline} onChange={(e) => set('tagline', e.target.value)} /></Field>
      <Field label="Description" hint="Only facts the partner gave you or that are on their site.">
        <textarea className={areaCls} maxLength={280} value={d.description} onChange={(e) => set('description', e.target.value)} />
      </Field>
      <Field label="When they meet" hint="Optional, e.g. “Saturdays 7:30 am from Wash Park”. Leave empty if it changes.">
        <input className={inputCls} maxLength={160} value={d.schedule} onChange={(e) => set('schedule', e.target.value)} />
      </Field>
      <Field label="Website"><input className={inputCls} inputMode="url" autoCapitalize="none" value={d.website} onChange={(e) => set('website', e.target.value)} placeholder="https://…" /></Field>
      <Field label="Sign-up page"><input className={inputCls} inputMode="url" autoCapitalize="none" value={d.signup} onChange={(e) => set('signup', e.target.value)} placeholder="https://…" /></Field>
      <Field label="Instagram"><input className={inputCls} autoCapitalize="none" value={d.instagram} onChange={(e) => set('instagram', e.target.value)} placeholder="@handle or link" /></Field>
      <Field label="Cities" hint="One per line as City, ST. People whose home city is listed see this partner.">
        <textarea className={areaCls} value={cities} onChange={(e) => setCities(e.target.value)} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Starts"><input type="date" className={inputCls} value={d.starts ?? ''} onChange={(e) => set('starts', e.target.value || null)} /></Field>
        <Field label="Ends"><input type="date" className={inputCls} value={d.ends ?? ''} onChange={(e) => set('ends', e.target.value || null)} /></Field>
      </div>
      <label className="flex min-h-11 items-center gap-3 text-body text-(--text)">
        <input type="checkbox" className="size-5 accent-(--accent)" checked={d.active} onChange={(e) => set('active', e.target.checked)} />
        Show this partner
      </label>
      <label className="flex min-h-11 items-start gap-3 text-body text-(--text)">
        <input type="checkbox" className="mt-0.5 size-5 accent-(--accent)" checked={d.sponsored} onChange={(e) => set('sponsored', e.target.checked)} />
        <span>Sponsored placement
          <span className="block text-small text-(--text-secondary)">Also shown as one “Sponsored partner” card in the find-clubs screens (Local, Discover, Explore, search) for people in these cities or who search one of their zip codes. Always labelled sponsored.</span>
        </span>
      </label>
      {err && <p className="text-small text-(--danger)" role="alert">{err}</p>}
    </Sheet>
  )
}

export function PartnersScreen({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<PartnerAdminList | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<PartnerAdmin | 'new' | null>(null)
  const load = useCallback(() => listPartnersAdmin().then((d) => { setData(d); setError(null) }, (e) => setError((e as Error).message)), [])
  useEffect(() => { void load() }, [load])
  return (
    <Screen title="Partners" subtitle="Promoted to people in their cities, always labelled" onClose={onClose}>
      {error && !data ? <ErrorState compact message={error} onRetry={() => void load()} />
        : !data ? <RowsSkeleton label="Loading partners" count={3} />
        : (
          <>
            <Button variant="primary" className="h-11 gap-1.5 text-body" onClick={() => setEditing('new')}>
              <Plus className="size-5" aria-hidden /> Add a partner
            </Button>
            {data.partners.length === 0 && <p className="px-1 text-small text-(--text-muted)">No partners yet.</p>}
            <ul className="flex flex-col gap-2">
              {data.partners.map((p) => (
                <li key={p.id}>
                  <button type="button" onClick={() => setEditing(p)}
                    className="flex w-full items-center gap-3 rounded-2xl border border-(--border) bg-(--bg-surface) p-3.5 text-left active:bg-(--bg-inset)">
                    <Monogram p={p} />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="truncate text-body-lg font-semibold text-(--text)">{p.name}</span>
                        <PartnerBadge />
                        {p.sponsored !== false && <span className="text-meta font-semibold text-(--text-secondary)">Sponsored</span>}
                      </span>
                      <span className={cn('block text-meta', p.live ? 'text-(--accent)' : 'text-(--text-muted)')}>
                        {p.live ? 'Live' : p.active ? 'Scheduled or ended' : 'Hidden'} · {p.metros.length === 1 ? `${p.metros[0]!.city}, ${p.metros[0]!.state}` : `${p.metros.length} cities`}
                      </span>
                      <span className="block font-mono text-meta tabular-nums text-(--text-secondary)">
                        {p.stats.view} views · {p.stats.website + p.stats.signup + p.stats.instagram} link taps · {p.stats.interested} interested
                      </span>
                      {Object.entries(p.placements ?? {}).map(([pl, c]) => (
                        <span key={pl} className="block font-mono text-meta tabular-nums text-(--text-secondary)">
                          {PLACE_LABEL[pl] ?? pl}: {c?.impression ?? 0} seen · {c?.tap ?? 0} taps · {c?.hide ?? 0} hides
                        </span>
                      ))}
                    </span>
                    <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
            <p className="px-1 text-small leading-snug text-(--text-secondary)">
              Counts are anonymous, last {data.stats_days} days, each person once per day. People who turned off usage counting aren't counted.
            </p>
          </>
        )}
      {editing && data && (
        <PartnerForm p={editing === 'new' ? null : editing} kinds={data.kinds} onSaved={setData} onClose={() => setEditing(null)} />
      )}
    </Screen>
  )
}
