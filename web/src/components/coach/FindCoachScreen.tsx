// Find a coach: a short, curated list of human coaches, ranked for the athlete's main race
// and sports. The athlete contacts coaches directly (email, phone, website); Rabbit takes
// no cut. "Invite as my coach" only for coaches who already use Rabbit.
import { useCallback, useEffect, useState } from 'react'
import { BadgeCheck, ExternalLink, Mail, MessageCircle, Phone, Quote, Sparkles, UserPlus, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { RabbitLoader } from '@/components/RabbitLoader'
import { Chip, Screen, inputCls } from '@/components/plan/ui'
import {
  DIRECTORY_SPORTS, getDirectory, initials, inviteDirectoryCoach, mailtoHref,
  type DirectoryCoach, type DirectoryResp,
} from '@/lib/coachdir'

const FILTERS_FROM = 4 // filters only help once the list is longer than a screen

export function FindCoachScreen({ athleteName, onClose, onBack, onAsk, onInvited }: {
  athleteName: string
  onClose: () => void
  /** opened from another screen: back instead of X */
  onBack?: () => void
  /** "Ask Rabbit if this coach fits me" (prefills Rabbit's composer); hidden when absent */
  onAsk?: (text: string) => void
  onInvited?: () => void
}) {
  const [data, setData] = useState<DirectoryResp | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sport, setSport] = useState('')
  const [q, setQ] = useState('')
  const [open, setOpen] = useState<DirectoryCoach | null>(null)
  const [closing, setClosing] = useState(false)
  const [total, setTotal] = useState(0)

  const load = useCallback(() => {
    setError(null)
    getDirectory({ sport, q }).then((r) => { setData(r); setTotal((t) => Math.max(t, r.coaches.length)) },
      (e) => setError((e as Error).message))
  }, [sport, q])
  useEffect(() => { const id = window.setTimeout(load, q ? 250 : 0); return () => window.clearTimeout(id) }, [load, q])
  const close = () => { setClosing(true); setTimeout(onBack ?? onClose, 200) }

  return (
    <Screen title="Find a coach" subtitle="Human coaches who can work alongside Rabbit" closing={closing}
      onClose={close} onBack={onBack ? close : undefined}>
      <p className="px-1 text-[0.7647rem] leading-snug text-(--text-secondary)">
        Rabbit doesn't take a cut; you contact coaches directly. Ranked for {data?.race?.name ? <b className="text-(--text)">{data.race.name}</b> : 'your sports'}.
      </p>
      {total >= FILTERS_FROM && (
        <div className="flex flex-col gap-2">
          <input className={inputCls} type="search" placeholder="Search coaches" aria-label="Search coaches"
            value={q} onChange={(e) => setQ(e.target.value)} />
          <div className="flex flex-wrap gap-1.5">
            <Chip selected={!sport} onClick={() => setSport('')}>All</Chip>
            {DIRECTORY_SPORTS.map(([id, label]) => (
              <Chip key={id} selected={sport === id} onClick={() => setSport(sport === id ? '' : id)}>{label}</Chip>
            ))}
          </div>
        </div>
      )}
      {!data && !error && <RabbitLoader className="py-16" label="Finding coaches" cycle={['Finding coaches…', 'Matching your race…', 'Checking who fits…']} />}
      {error && <ErrorState message={error} onRetry={load} />}
      {data && data.coaches.length === 0 && (
        <p className="px-1 py-6 text-center text-[0.8235rem] text-(--text-muted)">No coaches match that yet.</p>
      )}
      {data?.coaches.map((c) => <CoachCard key={c.id} c={c} onOpen={() => setOpen(c)} />)}
      {open && data && (
        <CoachDetail c={open} race={data.race} athleteName={athleteName} onClose={() => setOpen(null)}
          onAsk={onAsk} onInvited={() => { setOpen(null); onInvited?.() }} />
      )}
    </Screen>
  )
}

function Initials({ name, size = 48 }: { name: string; size?: number }) {
  return (
    <span aria-hidden="true" style={{ width: size, height: size }}
      className="flex shrink-0 items-center justify-center rounded-full bg-(--accent-subtle) font-display text-[1.0588rem] text-(--accent)">
      {initials(name)}
    </span>
  )
}

function CoachCard({ c, onOpen }: { c: DirectoryCoach; onOpen: () => void }) {
  return (
    <button type="button" onClick={onOpen}
      className="flex w-full flex-col gap-2.5 rounded-2xl border border-(--border) bg-(--bg-surface) p-4 text-left active:bg-(--bg-inset)">
      <span className="flex items-center gap-3">
        <Initials name={c.name} />
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1 text-[0.9412rem] font-medium text-(--text)">
            <span className="truncate">{c.name}</span>
            {c.verified_by_operator && <BadgeCheck className="size-4 shrink-0 text-(--accent)" aria-label="Checked by Rabbit" />}
          </span>
          <span className="block truncate text-[0.7647rem] text-(--text-muted)">{c.business} · {c.location}</span>
        </span>
      </span>
      <span className="flex items-start gap-1.5 text-[0.7647rem] leading-snug text-(--accent)">
        <Sparkles className="mt-0.5 size-3.5 shrink-0" /> {c.match.why}
      </span>
      <span className="flex flex-wrap gap-1.5">
        {c.specialties.map((s) => (
          <span key={s} className="rounded-full bg-(--bg-elevated) px-2 py-0.5 text-[0.6471rem] text-(--text-secondary)">{s}</span>
        ))}
        {!c.accepting && <span className="rounded-full bg-(--warning-subtle) px-2 py-0.5 text-[0.6471rem] text-(--warning-text)">Not taking athletes</span>}
      </span>
    </button>
  )
}

const H = ({ children }: { children: React.ReactNode }) => (
  <h3 className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">{children}</h3>
)

function CoachDetail({ c, race, athleteName, onClose, onAsk, onInvited }: {
  c: DirectoryCoach; race: DirectoryResp['race']; athleteName: string; onClose: () => void
  onAsk?: (text: string) => void; onInvited: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null)
  const first = c.name.split(' ')[0] ?? c.name
  async function invite() {
    setBusy(true); setMsg(null)
    try { await inviteDirectoryCoach(c.id); setMsg({ text: `Invited ${first}. They'll see your plan once they sign in.`, ok: true }); setTimeout(onInvited, 1200) }
    catch (e) { setMsg({ text: (e as Error).message, ok: false }) } finally { setBusy(false) }
  }
  const askText = `Would ${c.name} (${c.business}, ${c.location}; ${c.specialties.join(', ')}) be a good coach for me${race?.name ? ` for ${race.name}` : ''}? `
  const contactCls = 'h-11 flex-1 gap-1.5 text-[0.7647rem]'
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="coach-title" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-handle" />
        <div className="modal-header">
          <h2 id="coach-title" className="modal-title">{c.name}</h2>
          <button type="button" className="modal-close" aria-label="Close" onClick={onClose}><X className="size-4" /></button>
        </div>
        <div className="modal-body flex flex-col gap-4 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
          <div className="flex items-center gap-3">
            <Initials name={c.name} size={56} />
            <div className="min-w-0">
              <p className="text-[0.8824rem] font-medium text-(--text)">{c.business}</p>
              <p className="text-[0.7647rem] text-(--text-muted)">{c.location}</p>
              <p className="mt-0.5 flex items-start gap-1 text-[0.7059rem] text-(--accent)"><Sparkles className="mt-0.5 size-3 shrink-0" /> {c.match.why}</p>
            </div>
          </div>
          <p className="text-[0.8235rem] leading-snug text-(--text)">{c.bio}</p>

          <div className="flex flex-wrap gap-2">
            {c.contact.email && (
              <Button asChild variant="primary" className={contactCls}>
                <a href={mailtoHref(c, race, athleteName)}><Mail className="size-4" /> Email</a>
              </Button>
            )}
            {c.contact.phone && (
              <Button asChild variant="default" className={contactCls}>
                <a href={`tel:${c.contact.phone.replace(/[^\d+]/g, '')}`}><Phone className="size-4" /> Call</a>
              </Button>
            )}
            {c.contact.website && (
              <Button asChild variant="default" className={contactCls}>
                <a href={c.contact.website} target="_blank" rel="noopener noreferrer"><ExternalLink className="size-4" /> Website</a>
              </Button>
            )}
          </div>
          <p className="-mt-2 text-[0.6471rem] text-(--text-muted)">
            Email opens a draft{race?.name ? ` mentioning ${race.name}` : ''} for you to edit and send yourself.
          </p>

          {c.credentials.length > 0 && (
            <section className="flex flex-col gap-1"><H>Credentials</H>
              <ul className="flex flex-col gap-0.5 text-[0.7647rem] text-(--text-secondary)">{c.credentials.map((x) => <li key={x}>• {x}</li>)}</ul>
            </section>
          )}
          {c.highlights.length > 0 && (
            <section className="flex flex-col gap-1"><H>Athlete results</H>
              <ul className="flex flex-col gap-0.5 text-[0.7647rem] text-(--text-secondary)">{c.highlights.map((x) => <li key={x}>• {x}</li>)}</ul>
            </section>
          )}
          {c.testimonial && (
            <figure className="flex gap-2 rounded-xl bg-(--bg-inset) p-3">
              <Quote className="mt-0.5 size-4 shrink-0 text-(--accent)" />
              <div>
                <blockquote className="text-[0.8235rem] italic leading-snug text-(--text)">{c.testimonial.quote}</blockquote>
                <figcaption className="mt-1 text-[0.6471rem] text-(--text-muted)">{c.testimonial.by}</figcaption>
              </div>
            </figure>
          )}
          {(c.services.length > 0 || c.pricing_note) && (
            <section className="flex flex-col gap-1"><H>Services</H>
              {c.services.map((x) => <p key={x} className="text-[0.7647rem] text-(--text-secondary)">{x}</p>)}
              {c.pricing_note && <p className="text-[0.7647rem] text-(--text-muted)">{c.pricing_note}</p>}
            </section>
          )}

          {(c.can_invite || onAsk) && (
            <div className="flex flex-col gap-2 border-t border-(--border) pt-3">
              {c.can_invite && (
                <Button variant="default" className="h-11 gap-1.5 text-[0.7647rem]" loading={busy} onClick={() => void invite()}>
                  <UserPlus className="size-4" /> Invite as my coach
                </Button>
              )}
              {onAsk && (
                <Button variant="ghost" className="h-11 gap-1.5 text-[0.7647rem]" onClick={() => onAsk(askText)}>
                  <MessageCircle className="size-4" /> Ask Rabbit if this coach fits me
                </Button>
              )}
            </div>
          )}
          {msg && <p className={`text-[0.7647rem] ${msg.ok ? 'text-(--accent)' : 'text-(--danger)'}`} role="status">{msg.text}</p>}
        </div>
      </div>
    </div>
  )
}
