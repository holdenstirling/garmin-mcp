// Agree before using rabbt: on first sign-in or join, and again when the terms change
// (server consent.py, legal.VERSION). Four boxes are required; the documents open in-app.
// Sharing workouts with friends is a separate, optional box (opt-in consent to share health
// data, as Washington's My Health My Data Act asks); it sets "Share my workouts with friends".
import { useEffect, useState } from 'react'
import { DataPromise } from '@/components/legal/DataPromise'
import { getCommunitySettings } from '@/lib/community'
import { Button } from '@/components/ui/button'
import { DocScreen } from '@/components/legal/PrivacyLegalScreen'
import { acceptConsent, type ConsentView, type LegalSlug } from '@/lib/legal'
import { RabbitNap } from '@/components/anim'

type Box = 'terms' | 'privacy' | 'age16' | 'health'

export function ConsentScreen({ consent, onDone, onSignOut }: {
  consent: ConsentView; onDone: () => void; onSignOut: () => void
}) {
  const [on, setOn] = useState<Record<Box, boolean>>({ terms: false, privacy: false, age16: false, health: false })
  const [doc, setDoc] = useState<LegalSlug | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  // Ticked only when the person already said yes (here or in the app); never pre-ticked otherwise.
  const [share, setShare] = useState(consent.share === true)
  useEffect(() => {
    if (consent.share != null) return
    let live = true
    getCommunitySettings().then((r) => { if (live && r.settings.share_workouts === true) setShare(true) }, () => {})
    return () => { live = false }
  }, [consent.share])
  if (doc) return <DocScreen slug={doc} onClose={() => setDoc(null)} />
  const all = Object.values(on).every(Boolean)
  const link = (slug: LegalSlug, label: string) => (
    <button type="button" className="underline text-(--accent)" onClick={(e) => { e.preventDefault(); setDoc(slug) }}>{label}</button>
  )
  const boxes: { id: Box; label: React.ReactNode }[] = [
    { id: 'terms', label: <>I agree to the {link('terms', 'Terms of service')} and {link('guidelines', 'Community guidelines')}.</> },
    { id: 'privacy', label: <>I've read the {link('privacy', 'Privacy policy')}.</> },
    { id: 'age16', label: <>I'm 16 or older.</> },
    { id: 'health', label: <>I agree to rabbt processing my health and fitness data (heart rate, sleep, recovery, how workouts felt, niggles) to coach me, as the {link('health-data', 'consumer health data policy')} explains.</> },
  ]
  async function agree() {
    setBusy(true); setErr(null)
    try { await acceptConsent({ ...on, version: consent.version, share }); onDone() }
    catch (e) { setErr((e as Error).message || "Couldn't save just now."); setBusy(false) }
  }
  return (
    <main className="flex flex-1 flex-col overflow-y-auto px-5 pb-[max(24px,env(safe-area-inset-bottom))] pt-[max(28px,env(safe-area-inset-top))]">
      <div className="mx-auto flex w-full max-w-md flex-col gap-5">
        <RabbitNap size={44} mode={consent.first ? 'wave' : 'peek'} className="self-start" />
        <h1 className="font-display text-display leading-tight text-(--brand)">
          {consent.first ? 'Before you start' : 'Our terms changed'}
        </h1>
        <p className="text-lead leading-snug text-(--text-secondary)">
          {consent.first
            ? 'rabbt uses your training and health data to coach you.'
            : 'Please review the updated terms and privacy policy to keep using rabbt.'}
        </p>
        <fieldset className="flex flex-col gap-2.5">
          <legend className="sr-only">Agreements</legend>
          {boxes.map((b) => (
            <label key={b.id} className="flex min-h-14 items-start gap-3.5 rounded-xl border border-(--border) bg-(--bg-surface) p-4 text-body-lg leading-snug text-(--text)">
              <input type="checkbox" className="mt-0.5 size-6 shrink-0 accent-(--accent)" checked={on[b.id]}
                onChange={(e) => setOn((s) => ({ ...s, [b.id]: e.target.checked }))} />
              <span>{b.label}</span>
            </label>
          ))}
        </fieldset>
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 text-body font-semibold text-(--text)">Optional</legend>
          <label className="flex min-h-14 items-start gap-3.5 rounded-xl border border-(--border) bg-(--bg-surface) p-4 text-body-lg leading-snug text-(--text)">
            <input type="checkbox" className="mt-0.5 size-6 shrink-0 accent-(--accent)" checked={share}
              onChange={(e) => setShare(e.target.checked)} />
            <span>
              Share my workouts with friends I choose.
              <span className="mt-1 block text-small text-(--text-secondary)">Sport, time and distance for people who follow you. Never heart rate or maps. Change it any time in Me.</span>
            </span>
          </label>
        </fieldset>
        <DataPromise />
        <p className="text-small leading-snug text-(--text-muted)">
          You can download your data or delete your account any time in Me, Privacy &amp; legal. {link('security', 'How your data is kept safe')}.
        </p>
        {err && <p role="alert" className="text-body text-(--danger)">{err}</p>}
        <Button variant="primary" className="w-full text-body-lg" disabled={!all || busy} onClick={() => void agree()}>{busy ? 'Saving…' : 'Agree and continue'}</Button>
        <button type="button" className="hit-44 self-center text-body text-(--text-muted) underline" onClick={onSignOut}>Sign out</button>
      </div>
    </main>
  )
}
