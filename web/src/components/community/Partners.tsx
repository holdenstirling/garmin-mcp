// Partners (server: partners.py): local clubs and shops the app owner promotes to people in their
// area. Always labelled "Partner" (never passed off as a normal result). PartnersNearYou is the spot
// at the top of Clubs near you; PartnerRow is the pinned row in club search and Search everywhere;
// PartnerSheet is the detail: monogram, tagline, description, schedule, and links that open the
// club's own site. Counts are anonymous (partners.py) and skipped when usage counting is off.
import { useEffect, useState } from 'react'
import { Check, ChevronRight, ExternalLink, Heart, Info } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { countPartner, type Partner, type PartnerCount } from '@/lib/clubdir'
import { counting } from '@/lib/usage'

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
      className="flex shrink-0 items-center justify-center rounded-xl bg-(--brand) font-display text-[0.9412rem] leading-none text-(--bg)">
      {p.monogram}
    </span>
  )
}

export function PartnerBadge({ className }: { className?: string }) {
  return (
    <span className={cn('inline-flex items-center rounded-full border border-(--border-strong) px-2 py-0.5 text-[0.6471rem] font-semibold uppercase tracking-wider text-(--text-secondary)', className)}>
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
      <h2 className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Partners near you</h2>
      {partners.map((p) => (
        <button key={p.id} type="button" onClick={() => setOpen(p)}
          aria-label={`Partner: ${p.name}${p.tagline ? `, ${p.tagline}` : ''}. Open details`}
          className="flex w-full items-center gap-3 rounded-2xl border border-(--accent)/40 bg-(--accent-subtle) p-3.5 text-left active:opacity-80">
          <Monogram p={p} />
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-2">
              <span className="truncate text-[0.8824rem] font-semibold text-(--text)">{p.name}</span>
              <PartnerBadge />
            </span>
            <span className="block truncate text-[0.7059rem] text-(--text-secondary)">
              {[p.kind_label, p.tagline].filter(Boolean).join(' · ')}
            </span>
          </span>
          <ChevronRight className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
        </button>
      ))}
      <p className="px-1 text-[0.6471rem] text-(--text-muted)">Partners are local groups Rabbit works with. Shown because you're near {metro}.</p>
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
          <span className="truncate text-[0.8235rem] font-semibold text-(--text)">{p.name}</span>
          <PartnerBadge />
        </span>
        <span className="block truncate text-[0.7059rem] text-(--text-secondary)">{[p.kind_label, p.tagline].filter(Boolean).join(' · ')}</span>
      </span>
      <ChevronRight className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
    </button>
  )
}

const linkBtn = 'flex min-h-11 w-full items-center justify-between gap-2 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 text-[0.8235rem] font-medium text-(--text) active:bg-(--bg-inset)'

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
            <div className="flex items-center gap-2"><PartnerBadge /><span className="text-[0.7059rem] text-(--text-muted)">{p.kind_label}</span></div>
            {p.tagline && <p className="mt-1 font-display text-[1.0588rem] leading-tight text-(--brand)">{p.tagline}</p>}
          </div>
        </div>
        {p.description && <p className="text-[0.8235rem] leading-relaxed text-(--text)">{p.description}</p>}
        {p.schedule ? (
          <p className="rounded-xl bg-(--bg-inset) px-3.5 py-2.5 text-[0.7647rem] text-(--text)">{p.schedule}</p>
        ) : (
          <p className="text-[0.7059rem] text-(--text-muted)">Check their site for this week's runs and how to join.</p>
        )}
        <div className="flex flex-col gap-2">
          {p.website && (
            <a href={p.website} target="_blank" rel="noopener noreferrer" className={linkBtn} onClick={() => track(p, 'website')}>
              <span>Visit website <span className="text-(--text-muted)">· {host(p.website)}</span></span><ExternalLink className="size-4 text-(--text-muted)" aria-hidden />
            </a>
          )}
          {p.signup && (
            <a href={p.signup} target="_blank" rel="noopener noreferrer" className={linkBtn} onClick={() => track(p, 'signup')}>
              <span>Join or sign up <span className="text-(--text-muted)">· {host(p.signup)}</span></span><ExternalLink className="size-4 text-(--text-muted)" aria-hidden />
            </a>
          )}
          {p.instagram && (
            <a href={p.instagram} target="_blank" rel="noopener noreferrer" className={linkBtn} onClick={() => track(p, 'instagram')}>
              <span>Instagram</span><ExternalLink className="size-4 text-(--text-muted)" aria-hidden />
            </a>
          )}
        </div>
        <Button variant={saved ? 'default' : 'primary'} className="h-11 gap-1.5 text-[0.8235rem]" aria-pressed={saved} onClick={toggle}>
          {saved ? <><Check className="size-4" aria-hidden /> Saved to your interests</> : <><Heart className="size-4" aria-hidden /> I'm interested</>}
        </Button>
        <p className="flex items-start gap-1.5 text-[0.6471rem] leading-snug text-(--text-muted)">
          <Info className="mt-px size-3 shrink-0" aria-hidden />
          Partners are local groups Rabbit works with. Links open their own pages; Rabbit doesn't share anything about you with them.
        </p>
      </>
    </Sheet>
  )
}
