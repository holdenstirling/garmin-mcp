// Find a coach: a short, curated list of human coaches, ranked for the athlete's main race
// and sports. "Near you | Anywhere (remote)": near you filters by distance (city centroids,
// from a location saved in Explore) and in-person/remote; "Find coaches near me on the web"
// runs one web search (sport + city only), labelled as not verified. The athlete contacts
// coaches directly (email, phone, website); Rabbit takes no cut. "Invite as my coach" only
// for coaches who already use Rabbit.
import type React from 'react'
import { useCallback, useEffect, useState } from 'react'
import { Sheet } from '@/components/ui/Sheet'
import { BadgeCheck, ExternalLink, Globe, Mail, MapPin, MessageCircle, Phone, Quote, Target, UserPlus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { RabbitLoader } from '@/components/RabbitLoader'
import { Chip, Screen, inputCls } from '@/components/plan/ui'
import { Switch } from '@/components/settings/Grouped'
import { cn } from '@/lib/utils'
import {
  DIRECTORY_SPORTS, DISTANCES_MI, findWebCoaches, getDirectory, initials, inviteDirectoryCoach, mailtoHref,
  type CoachScope, type DirectoryCoach, type DirectoryResp, type WebCoachResp,
} from '@/lib/coachdir'

const FILTERS_FROM = 5 // text search only helps once there are 5+ coaches
const WEB_STATE: Record<Exclude<WebCoachResp['state'], 'ok'>, string> = {
  needs_location: 'Add your location in Explore first, so Rabbit knows which city to search.',
  limit: "That's today's web searches used up. Try again tomorrow.",
  unavailable: "Web search isn't available right now.",
  failed: "The web search didn't work just now. Try again in a minute.",
}

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
  const [scope, setScope] = useState<CoachScope>('local')
  const [within, setWithin] = useState<number>(50)
  const [inPerson, setInPerson] = useState(true)
  const [remoteOk, setRemoteOk] = useState(true)
  const [web, setWeb] = useState<WebCoachResp | null>(null)
  const [webBusy, setWebBusy] = useState(false)
  const [webError, setWebError] = useState<string | null>(null)
  const [open, setOpen] = useState<DirectoryCoach | null>(null)
  const [closing, setClosing] = useState(false)
  const [total, setTotal] = useState(0)
  // In person only -> everyone near you; remote only -> coaches Rabbit knows coach remotely.
  const format = scope === 'local' && !inPerson && remoteOk ? 'remote' : 'any'

  const load = useCallback(() => {
    setError(null)
    getDirectory({ sport, q, scope, format, within: scope === 'local' ? within : undefined })
      .then((r) => { setData(r); setTotal((t) => Math.max(t, r.coaches.length)) }, (e) => setError((e as Error).message))
  }, [sport, q, scope, format, within])
  async function searchWeb() {
    setWebBusy(true); setWebError(null)
    try { setWeb(await findWebCoaches(sport || undefined)) }
    catch (e) { setWebError((e as Error).message) } finally { setWebBusy(false) }
  }
  useEffect(() => { setWeb(null) }, [sport])
  useEffect(() => { const id = window.setTimeout(load, q ? 250 : 0); return () => window.clearTimeout(id) }, [load, q])
  const close = () => { setClosing(true); setTimeout(onBack ?? onClose, 200) }

  return (
    <Screen title="Find a coach" subtitle="Human coaches who can work alongside Rabbit" closing={closing}
      onClose={close} onBack={onBack ? close : undefined}>
      <div role="tablist" aria-label="Where" className="seg flex rounded-full bg-(--bg-inset) p-0.5" style={{ '--seg-i': Math.max(0, scope === 'remote' ? 1 : 0), '--seg-n': 2 } as React.CSSProperties}>
      <span className="seg__pill" aria-hidden />
        {([['local', 'Near you'], ['remote', 'Anywhere (remote)']] as const).map(([v, l]) => (
          <button key={v} type="button" role="tab" aria-selected={scope === v} onClick={() => setScope(v)}
            className={cn('min-h-11 flex-1 rounded-full text-[0.7647rem] font-medium transition-colors',
              scope === v ? 'text-(--text)' : 'text-(--text-muted)')}>{l}</button>
        ))}
      </div>
      <p className="px-1 text-[0.7647rem] leading-snug text-(--text-secondary)">
        Rabbit doesn't take a cut; you contact coaches directly. Ranked for {data?.race?.name ? <b className="text-(--text)">{data.race.name}</b> : 'your sports'}.
      </p>
      <div className="flex flex-col gap-2">
        {total >= FILTERS_FROM && (
          <input className={inputCls} type="search" placeholder="Search coaches" aria-label="Search coaches"
            value={q} onChange={(e) => setQ(e.target.value)} />
        )}
        <div className="flex flex-wrap gap-1.5" aria-label="Sport">
          <Chip selected={!sport} onClick={() => setSport('')}>All</Chip>
          {DIRECTORY_SPORTS.map(([id, label]) => (
            <Chip key={id} selected={sport === id} onClick={() => setSport(sport === id ? '' : id)}>{label}</Chip>
          ))}
        </div>
        {scope === 'local' && (
          <>
            {data?.has_location ? (
              <div className="flex flex-wrap gap-1.5" aria-label="Distance">
                {DISTANCES_MI.map((mi) => <Chip key={mi} selected={within === mi} onClick={() => setWithin(mi)}>{mi} mi</Chip>)}
              </div>
            ) : data && (
              <p className="flex items-start gap-1.5 px-1 text-[0.7059rem] text-(--text-muted)">
                <MapPin className="mt-0.5 size-3.5 shrink-0" />
                {data.area ? `Showing coaches in ${data.area.split(', ').pop()}. ` : ''}Save your location in Explore to see distances.
              </p>
            )}
            <div className="flex flex-wrap gap-1.5" aria-label="Coaching format">
              <Chip selected={inPerson} onClick={() => { if (inPerson && !remoteOk) setRemoteOk(true); setInPerson(!inPerson) }}>In person</Chip>
              <Chip selected={remoteOk} onClick={() => { if (remoteOk && !inPerson) setInPerson(true); setRemoteOk(!remoteOk) }}>Remote</Chip>
            </div>
          </>
        )}
      </div>
      {!data && !error && <RabbitLoader className="py-16" label="Finding coaches" cycle={['Finding coaches…', 'Matching your race…', 'Checking who fits…']} />}
      {error && <ErrorState message={error} onRetry={load} />}
      {data && data.coaches.length === 0 && (
        <p className="px-1 py-6 text-center text-[0.8235rem] text-(--text-muted)">
          {scope === 'local' ? 'No coaches in Rabbit’s list near you yet. Try Anywhere, or search the web below.' : 'No coaches match that yet.'}
        </p>
      )}
      {data?.coaches.map((c) => <CoachCard key={c.id} c={c} onOpen={() => setOpen(c)} />)}
      {data && scope === 'local' && (
        <section className="flex flex-col gap-2 border-t border-(--border) pt-3">
          {!web && (
            <Button variant="default" className="h-11 gap-1.5 text-[0.7647rem]" loading={webBusy} onClick={() => void searchWeb()}>
              <Globe className="size-4" /> Find coaches near me on the web
            </Button>
          )}
          {!web && !webBusy && <p className="px-1 text-[0.6471rem] text-(--text-muted)">Searches by your sport and city only. Uses 1 of your daily web searches.</p>}
          {webBusy && <RabbitLoader className="py-6" label="Searching the web" cycle={['Searching the web…', 'Checking coaching sites…', 'Keeping only real links…']} />}
          {webError && <ErrorState compact message={webError} onRetry={() => void searchWeb()} />}
          {web && web.state !== 'ok' && <p className="px-1 text-[0.7647rem] text-(--text-muted)">{WEB_STATE[web.state]}</p>}
          {web && web.state === 'ok' && (
            <>
              <p className="flex items-center gap-1.5 px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">
                <Globe className="size-3.5" /> {web.label}
              </p>
              {web.coaches.length === 0 && <p className="px-1 text-[0.7647rem] text-(--text-muted)">Nothing with a website turned up around {web.area}.</p>}
              {web.coaches.map((w) => (
                <a key={w.id} href={w.url} target="_blank" rel="noopener noreferrer"
                  className="flex min-h-11 items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-2.5 active:bg-(--bg-inset)">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[0.8235rem] font-medium text-(--text)">{w.name}</span>
                    <span className="block truncate text-[0.7059rem] text-(--text-muted)">{[w.specialty, w.area || web.area].filter(Boolean).join(' · ')}</span>
                  </span>
                  <span className="flex shrink-0 items-center gap-1 text-[0.7059rem] text-(--accent)">{hostOf(w.url)} <ExternalLink className="size-3" /></span>
                </a>
              ))}
            </>
          )}
        </section>
      )}
      {open && data && (
        <CoachDetail c={open} race={data.race} athleteName={athleteName} onClose={() => setOpen(null)}
          onAsk={onAsk} onInvited={() => { setOpen(null); onInvited?.() }} />
      )}
    </Screen>
  )
}

function hostOf(u: string): string {
  try { return new URL(u).hostname.replace(/^www\./, '') } catch { return u }
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
          <span className="block truncate text-[0.7647rem] text-(--text-muted)">{c.business} · {c.distance_label ?? c.location}</span>
        </span>
      </span>
      <span className="flex items-start gap-1.5 text-[0.7647rem] leading-snug text-(--accent)">
        <Target className="mt-0.5 size-3.5 shrink-0" aria-hidden /> {c.match.why}
      </span>
      <span className="flex flex-wrap gap-1.5">
        {c.specialties.map((s) => (
          <span key={s} className="rounded-full bg-(--bg-elevated) px-2 py-0.5 text-[0.6471rem] text-(--text-secondary)">{s}</span>
        ))}
        {c.remote === true && <span className="rounded-full bg-(--accent-subtle) px-2 py-0.5 text-[0.6471rem] text-(--accent)">Coaches remotely</span>}
        {!c.accepting && <span className="rounded-full bg-(--warning-subtle) px-2 py-0.5 text-[0.6471rem] text-(--warning-text)">Not taking athletes</span>}
      </span>
    </button>
  )
}

const H = ({ children }: { children: React.ReactNode }) => (
  <h2 className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">{children}</h2>
)

function CoachDetail({ c, race, athleteName, onClose, onAsk, onInvited }: {
  c: DirectoryCoach; race: DirectoryResp['race']; athleteName: string; onClose: () => void
  onAsk?: (text: string) => void; onInvited: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null)
  // Invite confirmation: view-only unless the athlete turns these on.
  const [confirm, setConfirm] = useState(false)
  const [canEdit, setCanEdit] = useState(false)
  const [canSee, setCanSee] = useState(false)
  const first = c.name.split(' ')[0] ?? c.name
  async function invite() {
    setBusy(true); setMsg(null)
    try { await inviteDirectoryCoach(c.id, { can_edit_plan: canEdit, can_see_rabbit_chats: canSee }); setConfirm(false); setMsg({ text: `Invited ${first}. They'll see your plan once they sign in.`, ok: true }); setTimeout(onInvited, 1200) }
    catch (e) { setMsg({ text: (e as Error).message, ok: false }) } finally { setBusy(false) }
  }
  const askText = `Would ${c.name} (${c.business}, ${c.location}; ${c.specialties.join(', ')}) be a good coach for me${race?.name ? ` for ${race.name}` : ''}? `
  const contactCls = 'h-11 flex-1 gap-1.5 text-[0.7647rem]'
  return (
    <Sheet title={c.name} onClose={onClose} bodyClassName="gap-4">
          <div className="flex items-center gap-3">
            <Initials name={c.name} size={56} />
            <div className="min-w-0">
              <p className="text-[0.8824rem] font-medium text-(--text)">{c.business}</p>
              <p className="text-[0.7647rem] text-(--text-muted)">{c.location}</p>
              <p className="mt-0.5 flex items-start gap-1 text-[0.7059rem] text-(--accent)"><Target className="mt-0.5 size-3 shrink-0" aria-hidden /> {c.match.why}</p>
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
              {c.can_invite && !confirm && (
                <Button variant="default" className="h-11 gap-1.5 text-[0.7647rem]" onClick={() => setConfirm(true)}>
                  <UserPlus className="size-4" /> Invite as my coach
                </Button>
              )}
              {c.can_invite && confirm && (
                <div className="flex flex-col gap-2 rounded-xl border border-(--border) bg-(--bg-surface) p-3">
                  <p className="text-[0.7647rem] font-medium text-(--text)">What can {first} do?</p>
                  <p className="text-[0.7059rem] text-(--text-muted)">{first} can always see your plan, races and workouts. Turn on more only if you want to.</p>
                  <div className="flex min-h-11 items-center justify-between gap-3">
                    <span className="text-[0.7647rem] text-(--text)">Edit my plan</span>
                    <Switch label="Coach can edit my plan" checked={canEdit} disabled={busy} onChange={setCanEdit} />
                  </div>
                  <div className="flex min-h-11 items-center justify-between gap-3">
                    <span className="text-[0.7647rem] text-(--text)">See my Rabbit chats</span>
                    <Switch label="Coach can see my Rabbit chats" checked={canSee} disabled={busy} onChange={setCanSee} />
                  </div>
                  <div className="flex gap-2">
                    <Button variant="ghost" className="h-11 flex-1 text-[0.7647rem]" disabled={busy} onClick={() => setConfirm(false)}>Cancel</Button>
                    <Button variant="primary" className="h-11 flex-1 gap-1.5 text-[0.7647rem]" loading={busy} onClick={() => void invite()}>
                      <UserPlus className="size-4" /> Send invite
                    </Button>
                  </div>
                  <p className="text-[0.6471rem] text-(--text-muted)">You can change these any time in Me → Coaches.</p>
                </div>
              )}
              {onAsk && (
                <Button variant="ghost" className="h-11 gap-1.5 text-[0.7647rem]" onClick={() => onAsk(askText)}>
                  <MessageCircle className="size-4" /> Ask Rabbit if this coach fits me
                </Button>
              )}
            </div>
          )}
          {msg && <p className={`text-[0.7647rem] ${msg.ok ? 'text-(--accent)' : 'text-(--danger)'}`} role="status">{msg.text}</p>}
    </Sheet>
  )
}
