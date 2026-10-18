// Me -> Privacy & legal: read every policy in the app, download your data, delete your account,
// and see where each privacy control lives. Server: legal.py (documents), account.py (export /
// delete), consent.py (what you agreed to and when).
import { useEffect, useState } from 'react'
import { AtSign, BookOpen, Download, FileText, HeartHandshake, Mail, Plug, Settings, ShieldCheck, Trash2 } from 'lucide-react'
import { Screen } from '@/components/plan/ui'
import { Group, Icon, Row } from '@/components/settings/Grouped'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { RowsSkeleton } from '@/components/ui/Skeleton'
import { LegalDocBody } from '@/components/legal/LegalDoc'
import {
  LEGAL_DOCS, PRIVACY_CONTACT, consentOf, deleteAccount, downloadMyData, getLegalDoc,
  type LegalDoc, type LegalSlug,
} from '@/lib/legal'
import type { Me } from '@/lib/api'
import { openFindFriends } from '@/lib/friends'

const ICONS: Record<LegalSlug, React.ReactNode> = {
  privacy: <ShieldCheck />, terms: <FileText />, security: <BookOpen />, guidelines: <HeartHandshake />,
}

export function DocScreen({ slug, onBack, onClose }: { slug: LegalSlug; onBack?: () => void; onClose: () => void }) {
  const [doc, setDoc] = useState<LegalDoc | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let live = true
    setErr(null)
    getLegalDoc(slug).then((d) => { if (live) setDoc(d) }).catch((e: Error) => { if (live) setErr(e.message) })
    return () => { live = false }
  }, [slug, tick])
  const meta = LEGAL_DOCS.find((d) => d.slug === slug)!
  return (
    <Screen title={meta.title} onBack={onBack} onClose={onClose}>
      {err ? <ErrorState message="Couldn't load this page." onRetry={() => setTick((t) => t + 1)} />
        : !doc ? <RowsSkeleton label="Loading" count={6} />
        : (
          <article className="rounded-2xl border border-(--border) bg-(--bg-surface) p-4">
            <p className="mb-3 text-[0.7647rem] text-(--text-muted)">
              Operated by {doc.operator} · updated {doc.updated} · version {doc.version}
            </p>
            <LegalDocBody html={doc.html} />
            <p className="mt-4 text-[0.7647rem]">
              <a className="underline" href={`/app/${slug}`} target="_blank" rel="noopener">Open the printable page</a>
            </p>
          </article>
        )}
    </Screen>
  )
}

function DeleteAccount({ onCancel }: { onCancel: () => void }) {
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  async function go() {
    setBusy(true); setErr(null)
    try {
      await deleteAccount()
      window.location.assign('/app/')
    } catch (e) { setErr((e as Error).message || "Couldn't delete just now."); setBusy(false) }
  }
  return (
    <section className="flex flex-col gap-3 rounded-2xl border border-(--danger) bg-(--bg-surface) p-4" aria-labelledby="del-h">
      <h2 id="del-h" className="text-[1rem] font-semibold text-(--danger)">Delete your account</h2>
      <ul className="list-disc pl-5 text-[0.8235rem] leading-snug text-(--text-secondary)">
        <li>Everything in your account is deleted: profile, plan, events, chats, workouts feedback, posts, photos and settings.</li>
        <li>Garmin, Oura, Google Calendar and TrainingPeaks are disconnected (their own copies stay with them).</li>
        <li>Follows, clubs, buddy profile and share links are removed. Messages you sent stay in other people's chats, without your name or photo.</li>
        <li>Encrypted backups expire on their own within 12 months. This can't be undone.</li>
      </ul>
      <label className="flex flex-col gap-1 text-[0.8235rem] text-(--text)">
        Type DELETE to confirm
        <input value={typed} onChange={(e) => setTyped(e.target.value)} autoCapitalize="characters" autoComplete="off"
          spellCheck={false} aria-describedby={err ? 'del-err' : undefined}
          className="min-h-11 rounded-lg border border-(--border) bg-(--bg) px-3 text-[1rem]" />
      </label>
      {err && <p id="del-err" role="alert" className="text-[0.8235rem] text-(--danger)">{err}</p>}
      <div className="flex gap-2">
        <Button variant="outline" className="flex-1" onClick={onCancel} disabled={busy}>Cancel</Button>
        <Button variant="destructive" className="flex-1" disabled={typed.trim() !== 'DELETE' || busy} onClick={() => void go()}>
          {busy ? 'Deleting…' : 'Delete forever'}
        </Button>
      </div>
    </section>
  )
}

export function PrivacyLegalScreen({ me, onClose, onOpenSettings, onOpenConnections }: {
  me: Me; onClose: () => void; onOpenSettings: () => void; onOpenConnections: () => void
}) {
  const [doc, setDoc] = useState<LegalSlug | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const consent = consentOf(me)
  if (doc) return <DocScreen slug={doc} onBack={() => setDoc(null)} onClose={onClose} />

  async function exportData() {
    setExporting(true); setNote(null)
    try { await downloadMyData(); setNote('Your download has started.') }
    catch (e) { setNote((e as Error).message || "Couldn't prepare your download.") }
    finally { setExporting(false) }
  }
  const agreed = consent?.accepted_at
    ? `You agreed to version ${consent.accepted_version} on ${new Date(consent.accepted_at * 1000).toLocaleDateString()}.`
    : undefined

  return (
    <Screen title="Privacy & legal" onClose={onClose}>
      <Group label="Policies" footer={agreed}>
        {LEGAL_DOCS.map((d) => (
          <Row key={d.slug} icon={<Icon>{ICONS[d.slug]}</Icon>} title={d.title} subtitle={d.help} onClick={() => setDoc(d.slug)} />
        ))}
      </Group>

      <Group label="Your data" footer={note ? <span role="status">{note}</span> : 'A zip of everything in your account, without passwords or sign-in tokens.'}>
        <Row icon={<Icon><Download /></Icon>} title={exporting ? 'Preparing…' : 'Download my data'}
          subtitle="Profile, plan, events, chats, posts and more" disabled={exporting} onClick={() => void exportData()} />
        {!me.owner && (
          <Row icon={<Icon tone="danger"><Trash2 /></Icon>} title="Delete my account" danger
            subtitle="Removes your data and disconnects every app" onClick={() => setDeleting(true)} />
        )}
      </Group>
      {deleting && <DeleteAccount onCancel={() => setDeleting(false)} />}

      <Group label="Privacy controls">
        {me.role === 'athlete' && (<>
        <Row icon={<Icon tone="muted"><Settings /></Icon>} title="Sharing, location and usage counts"
          subtitle="What friends see, your area, Don't count my usage" onClick={onOpenSettings} />
        <Row icon={<Icon tone="muted"><Plug /></Icon>} title="Connected apps"
          subtitle="What each app shares; disconnect any time" onClick={onOpenConnections} />
        <Row icon={<Icon tone="muted"><AtSign /></Icon>} title="How friends find you"
          subtitle="Your @handle; find me by name, email or phone" onClick={() => openFindFriends({ section: 'me' })} />
        </>)}
        <Row icon={<Icon tone="muted"><Mail /></Icon>} title="Contact about privacy" subtitle={PRIVACY_CONTACT}
          onClick={() => { window.location.href = `mailto:${PRIVACY_CONTACT}?subject=${encodeURIComponent('Rabbit privacy request')}` }} />
      </Group>

      {me.owner && (
        <p className="px-4 text-[0.7647rem] leading-snug text-(--text-muted)">
          Owner only: these pages were written from what the code does. Have a lawyer review them before a public launch.
          The owner account can't be deleted from the app.
        </p>
      )}
    </Screen>
  )
}
