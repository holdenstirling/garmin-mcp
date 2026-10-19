// Partners (server: partners.py): local clubs and shops the app owner promotes to people in their
// area. Always labelled "Partner" (never passed off as a normal result). PartnersNearYou is the spot
// at the top of Clubs near you; PartnerRow is the pinned row in club search and Search everywhere;
// PartnerSheet is the detail: monogram, tagline, description, schedule, and links that open the
// club's own site. SponsoredCard is the one "Sponsored partner" card in the find-clubs flows (Local,
// Discover, Explore, the directory's empty state, search), always disclosed, with Hide. Counts are anonymous (partners.py) and skipped when usage counting is off.
import { useEffect, useState } from 'react'
import { Check, ChevronDown, ChevronRight, ExternalLink, Heart, Info, X } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { countPartner, countSponsored, getSponsored, hideSponsored, type Partner, type PartnerCount, type SponsorPlacement } from '@/lib/clubdir'
import { counting } from '@/lib/usage'
import { ACTIVITY_ICON } from '@/components/local/ActivityIcon'
import type { ActivityId } from '@/lib/activity'

/** The partner's activity icon (next to its kind), matching every other club and league. */
const PARTNER_ACTIVITY: Record<string, ActivityId> = { run_club: 'run', tri_club: 'tri', ride: 'ride', swim: 'swim', trail: 'trail', store: 'run' }
function KindIcon({ p }: { p: Partner }) {
  const I = ACTIVITY_ICON[PARTNER_ACTIVITY[p.kind] ?? 'other']
  return <I className="mr-1 inline size-4 align-[-2px] text-(--accent)" aria-hidden />
}

const SAVED = 'rabbit.partners.interested'

function savedIds(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(SAVED) ?? '[]')
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []
  } catch { return [] }
}
function setSaved(id: string, on: boolean) {
  try {
    const cur = savedIds().filter((x) => x !== id)
    localStorage.setItem(SAVED, JSON.stringify(on ? [id, ...cur].slice(0, 50) : cur))
  } catch { /* this visit only */ }
}

export function track(p: Partner, what: PartnerCount) {
  if (counting()) countPartner(p.id, what).catch(() => {})
}

export function Monogram({ p, size = 44 }: { p: Partner; size?: number }) {
  return (
    <span aria-hidden style={{ width: size, height: size }}
      className="flex shrink-0 items-center justify-center rounded-xl bg-(--brand) font-display text-lead leading-none text-(--bg)">
      {p.monogram}
    </span>
  )
}

export function PartnerBadge({ className }: { className?: string }) {
  return (
    <span className={cn('inline-flex items-center rounded-full border border-(--border-strong) px-2 py-0.5 text-caption font-semibold text-(--text-secondary)', className)}>
      Partner
    </span>
  )
}

/** "Partners near you": one card per partner at the top of Clubs near you. */
export function PartnersNearYou({ partners, metro }: { partners: Partner[]; metro: string }) {
  const [open, setOpen] = useState<Partner | null>(null)
  if (!partners.length) return null
  return (
    <section aria-label="Partners near you" className="flex flex-col gap-1.5">
      <h2 className="font-sans px-1 text-caption font-semibold text-(--text-muted)">Partners near you</h2>
      {partners.map((p) => (
        <button key={p.id} type="button" onClick={() => setOpen(p)}
          aria-label={`Partner: ${p.name}${p.tagline ? `, ${p.tagline}` : ''}. Open details`}
          className="flex w-full items-center gap-3 rounded-2xl border border-(--accent)/40 bg-(--accent-subtle) p-3.5 text-left active:opacity-80">
          <Monogram p={p} />
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-2">
              <span className="truncate text-body-lg font-semibold text-(--text)">{p.name}</span>
              <PartnerBadge />
            </span>
            <span className="block truncate text-meta text-(--text-secondary)">
              <KindIcon p={p} />{[p.kind_label, p.tagline].filter(Boolean).join(' · ')}
            </span>
          </span>
          <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
        </button>
      ))}
      <p className="px-1 text-caption text-(--text-muted)">Partners are local groups rabbt works with. Shown because you're near {metro}.</p>
      {open && <PartnerSheet p={open} onClose={() => setOpen(null)} />}
    </section>
  )
}

/** A pinned, labelled row (club search, Search everywhere). */
export function PartnerRow({ p, onOpen }: { p: Partner; onOpen: () => void }) {
  return (
    <button type="button" onClick={onOpen} aria-label={`Partner: ${p.name}. Open details`}
      className="flex min-h-14 w-full items-center gap-3 rounded-xl border border-(--accent)/40 bg-(--accent-subtle) px-3 py-2 text-left active:opacity-80">
      <Monogram p={p} size={36} />
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="truncate text-body font-semibold text-(--text)">{p.name}</span>
          <PartnerBadge />
        </span>
        <span className="block truncate text-meta text-(--text-secondary)"><KindIcon p={p} />{[p.kind_label, p.tagline].filter(Boolean).join(' · ')}</span>
      </span>
      <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
    </button>
  )
}

const linkBtn = 'flex min-h-11 w-full items-center justify-between gap-2 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 text-body font-medium text-(--text) active:bg-(--bg-inset)'

export function PartnerSheet({ p, onClose }: { p: Partner; onClose: () => void }) {
  const [saved, setSavedState] = useState(() => savedIds().includes(p.id))
  useEffect(() => { track(p, 'view') }, [p])
  const host = (u: string) => { try { return new URL(u).hostname.replace(/^www\./, '') } catch { return u } }
  function toggle() {
    const on = !saved
    setSaved(p.id, on)
    setSavedState(on)
    if (on) track(p, 'interested')
  }
  return (
    <Sheet title={p.name} onClose={onClose} portal bodyClassName="gap-4">
      <>
        <div className="flex items-center gap-3">
          <Monogram p={p} size={56} />
          <div className="min-w-0">
            <div className="flex items-center gap-2"><PartnerBadge /><span className="text-meta text-(--text-muted)"><KindIcon p={p} />{p.kind_label}</span></div>
            {p.tagline && <p className="mt-1 font-display text-title-sm leading-tight text-(--brand)">{p.tagline}</p>}
          </div>
        </div>
        {p.description && <p className="text-body leading-relaxed text-(--text)">{p.description}</p>}
        {p.schedule ? (
          <p className="rounded-xl bg-(--bg-inset) px-3.5 py-2.5 text-small text-(--text)">{p.schedule}</p>
        ) : (
          <p className="text-meta text-(--text-muted)">Check their site for this week's runs and how to join.</p>
        )}
        <div className="flex flex-col gap-2">
          {p.website && (
            <a href={p.website} target="_blank" rel="noopener noreferrer" className={linkBtn} onClick={() => track(p, 'website')}>
              <span>Visit website <span className="text-(--text-muted)">· {host(p.website)}</span></span><ExternalLink className="size-5 text-(--text-muted)" aria-hidden />
            </a>
          )}
          {p.signup && (
            <a href={p.signup} target="_blank" rel="noopener noreferrer" className={linkBtn} onClick={() => track(p, 'signup')}>
              <span>Join or sign up <span className="text-(--text-muted)">· {host(p.signup)}</span></span><ExternalLink className="size-5 text-(--text-muted)" aria-hidden />
            </a>
          )}
          {p.instagram && (
            <a href={p.instagram} target="_blank" rel="noopener noreferrer" className={linkBtn} onClick={() => track(p, 'instagram')}>
              <span>Instagram</span><ExternalLink className="size-5 text-(--text-muted)" aria-hidden />
            </a>
          )}
        </div>
        <Button variant={saved ? 'default' : 'primary'} className="h-11 gap-1.5 text-body" aria-pressed={saved} onClick={toggle}>
          {saved ? <><Check className="size-5" aria-hidden /> Saved to your interests</> : <><Heart className="size-5" aria-hidden /> I'm interested</>}
        </Button>
        <p className="flex items-start gap-1.5 text-caption leading-snug text-(--text-muted)">
          <Info className="mt-px size-3.5 shrink-0" aria-hidden />
          Partners are local groups rabbt works with. Links open their own pages; rabbt doesn't share anything about you with them.
        </p>
      </>
    </Sheet>
  )
}

/** The sponsored card for one find-clubs screen: fetched for that placement (the server decides:
 *  my area or a searched zip in a partner metro, not hidden here in the last 30 days). Disclosed as
 *  "Sponsored" with "Why am I seeing this?", Hide, and an anonymous impression / tap count. */
export function SponsoredCard({ placement, zip, card: given, className }: {
  placement: SponsorPlacement; zip?: string; card?: Partner | null; className?: string
}) {
  const [card, setCard] = useState<Partner | null>(given ?? null)
  const [open, setOpen] = useState(false)
  const [why, setWhy] = useState(false)
  const [gone, setGone] = useState(false)
  useEffect(() => {
    if (given !== undefined) { setCard(given); return }
    let live = true
    getSponsored(placement, zip).then((r) => { if (live) setCard(r.card) }, () => {})
    return () => { live = false }
  }, [placement, zip, given])
  useEffect(() => {
    if (card && counting()) countSponsored(card.id, 'impression', placement).catch(() => {})
  }, [card?.id, placement]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!card || gone) return null
  const tap = () => { if (counting()) countSponsored(card.id, 'tap', placement).catch(() => {}); setOpen(true) }
  const hide = () => { setGone(true); hideSponsored(card.id, placement).catch(() => {}) }
  return (
    <section aria-label={`Sponsored partner: ${card.name}`} className={cn('flex flex-col gap-1.5', className)}>
      <div className="flex items-center gap-1 pl-1">
        <span className="text-caption font-semibold text-(--text-muted)">Sponsored partner</span>
        <span className="flex-1" />
        <button type="button" onClick={hide} aria-label={`Hide ${card.name} here`}
          className="hit-44 flex items-center gap-1 rounded-full px-2 text-caption text-(--text-muted)">
          <X className="size-4" aria-hidden /> Hide
        </button>
      </div>
      <button type="button" onClick={tap} aria-label={`Sponsored: ${card.name}${card.tagline ? `, ${card.tagline}` : ''}. Open details`}
        className="flex w-full items-center gap-3 rounded-2xl border border-(--accent)/40 bg-(--accent-subtle) p-3.5 text-left active:opacity-80">
        <Monogram p={card} />
        <span className="min-w-0 flex-1">
          <span className="mb-1 inline-flex items-center rounded-full bg-(--bg-surface) px-2.5 py-0.5 text-caption font-semibold text-(--text-secondary)">Sponsored</span>
          <span className="block text-body-lg font-semibold leading-snug text-(--text)">{card.name}</span>
          <span className="mt-0.5 block text-small leading-snug text-(--text-secondary)">
            <KindIcon p={card} />{[card.kind_label, card.tagline].filter(Boolean).join(' · ')}
          </span>
        </span>
        <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
      </button>
      <button type="button" aria-expanded={why} onClick={() => setWhy((v) => !v)}
        className="hit-44 flex items-center gap-1 self-start px-1 text-caption text-(--text-muted)">
        <Info className="size-3.5" aria-hidden /> Why am I seeing this?
        <ChevronDown className={cn('size-3.5 transition-transform', why && 'rotate-180')} aria-hidden />
      </button>
      {why && (
        <p className="px-1 text-caption leading-snug text-(--text-muted)">
          {card.why ?? `${card.name} is a rabbt partner shown to people in its area.`} rabbt doesn't share anything about you with partners.
        </p>
      )}
      {open && <PartnerSheet p={card} onClose={() => setOpen(false)} />}
    </section>
  )
}
