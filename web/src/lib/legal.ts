// Privacy & legal (server: legal.py, consent.py, account.py). Documents are rendered by the
// server (trusted static HTML) and shown in-app; consent gates the app on first sign-in and
// whenever the terms version changes; export / delete are the account controls in Me.
import { getJSON, postJSON } from '@/lib/api'

export type LegalSlug = 'privacy' | 'terms' | 'security' | 'guidelines'
export const LEGAL_DOCS: { slug: LegalSlug; title: string; help: string }[] = [
  { slug: 'privacy', title: 'Privacy policy', help: 'What rabbt collects, why, and your rights' },
  { slug: 'terms', title: 'Terms of service', help: 'The rules for using rabbt' },
  { slug: 'security', title: 'Data & security', help: 'How your data is protected' },
  { slug: 'guidelines', title: 'Community guidelines', help: 'Keeping rabbt kind and safe' },
]
export type LegalDoc = { slug: LegalSlug; title: string; version: string; updated: string; operator: string; html: string }
export type ConsentView = {
  needed: boolean; version: string; accepted_version: string | null; accepted_at: number | null; first: boolean; contact?: string
}
export type ConsentBody = { terms: boolean; privacy: boolean; age16: boolean; health: boolean; version: string }

export const getLegalDoc = (slug: LegalSlug) => getJSON<LegalDoc>(`/api/legal/${slug}`)
export const getConsent = () => getJSON<ConsentView>('/api/consent')
export const acceptConsent = (b: ConsentBody) => postJSON<ConsentView>('/api/consent', b)
export const deleteAccount = () => postJSON<{ ok: boolean; failed: string[] }>('/api/account/delete', { confirm: 'DELETE' })

/** /me.consent (older servers: treat as agreed so the app never locks). */
export function consentOf(me: unknown): ConsentView | null {
  const c = (me as { consent?: ConsentView }).consent
  return c && typeof c.needed === 'boolean' ? c : null
}

/** Download my data: fetch the zip and hand it to the browser. */
export async function downloadMyData(): Promise<void> {
  const r = await fetch('/app/api/account/export', { credentials: 'same-origin' })
  if (!r.ok) {
    let msg = `HTTP ${r.status}`
    try { msg = (await r.json()).error ?? msg } catch { /* not JSON */ }
    throw new Error(msg)
  }
  const name = /filename="([^"]+)"/.exec(r.headers.get('content-disposition') ?? '')?.[1] ?? 'rabbt-data.zip'
  const url = URL.createObjectURL(await r.blob())
  const a = document.createElement('a')
  a.href = url; a.download = name
  document.body.appendChild(a); a.click(); a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

export const PRIVACY_CONTACT = 'holdenstirling@gmail.com'
