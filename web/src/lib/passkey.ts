// Passkeys (WebAuthn) and invite links. The server builds the options and verifies every
// response (src/garmin_mcp/passkey_web.py); this file only converts base64url <-> bytes and
// calls navigator.credentials.
import { getJSON, sendJSON } from './api'
import { track } from '@/lib/usage'

// ------------------------------------------------------------ base64url ---
export function b64uToBytes(s: string): Uint8Array<ArrayBuffer> {
  const b64 = s.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (s.length % 4)) % 4)
  const bin = atob(b64)
  const out = new Uint8Array(new ArrayBuffer(bin.length))
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

export function bytesToB64u(buf: ArrayBuffer | ArrayBufferView): string {
  const bytes = buf instanceof ArrayBuffer ? new Uint8Array(buf) : new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength)
  let bin = ''
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i])
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

// ------------------------------------------------------------- options ---
type Desc = { type: 'public-key'; id: string }
type CreationJSON = {
  challenge: string
  rp: { id: string; name: string }
  user: { id: string; name: string; displayName: string }
  pubKeyCredParams: { type: 'public-key'; alg: number }[]
  timeout: number
  attestation: AttestationConveyancePreference
  authenticatorSelection: AuthenticatorSelectionCriteria
  excludeCredentials: Desc[]
}
type RequestJSON = { challenge: string; rpId: string; timeout: number; userVerification: UserVerificationRequirement; allowCredentials: Desc[] }

const desc = (d: Desc): PublicKeyCredentialDescriptor => ({ type: 'public-key', id: b64uToBytes(d.id) })

export function supportsPasskeys(): boolean {
  return typeof window !== 'undefined' && !!window.PublicKeyCredential && !!navigator.credentials?.create
}

/** Runs the browser's "create a passkey" sheet; returns the JSON the server verifies. */
export async function createPasskey(o: CreationJSON): Promise<Record<string, unknown>> {
  const cred = await navigator.credentials.create({
    publicKey: {
      ...o, challenge: b64uToBytes(o.challenge),
      user: { ...o.user, id: b64uToBytes(o.user.id) },
      excludeCredentials: o.excludeCredentials.map(desc),
    },
  }) as PublicKeyCredential | null
  if (!cred) throw new Error('No passkey was created.')
  const r = cred.response as AuthenticatorAttestationResponse
  return {
    id: cred.id, rawId: bytesToB64u(cred.rawId), type: cred.type,
    response: {
      clientDataJSON: bytesToB64u(r.clientDataJSON), attestationObject: bytesToB64u(r.attestationObject),
      transports: typeof r.getTransports === 'function' ? r.getTransports() : [],
    },
  }
}

/** Runs the browser's "sign in with a passkey" sheet (discoverable credentials, no username). */
export async function getPasskey(o: RequestJSON): Promise<Record<string, unknown>> {
  const cred = await navigator.credentials.get({
    publicKey: { ...o, challenge: b64uToBytes(o.challenge), allowCredentials: o.allowCredentials.map(desc) },
  }) as PublicKeyCredential | null
  if (!cred) throw new Error('No passkey was chosen.')
  const r = cred.response as AuthenticatorAssertionResponse
  return {
    id: cred.id, rawId: bytesToB64u(cred.rawId), type: cred.type,
    response: {
      clientDataJSON: bytesToB64u(r.clientDataJSON), authenticatorData: bytesToB64u(r.authenticatorData),
      signature: bytesToB64u(r.signature), userHandle: r.userHandle ? bytesToB64u(r.userHandle) : null,
    },
  }
}

/** Plain-language message for a WebAuthn or server error. */
export function passkeyError(e: unknown): string {
  const name = (e as { name?: string })?.name
  if (name === 'NotAllowedError' || name === 'AbortError') return 'The passkey request was cancelled or timed out. Try again when you are ready.'
  if (name === 'InvalidStateError') return 'This device already has a Rabbit passkey for this account.'
  if (name === 'SecurityError') return "Passkeys don't work on this address. Open Rabbit from its usual link."
  if (name === 'NotSupportedError') return "This browser can't make passkeys. Try Safari, Chrome or Edge."
  return (e as Error)?.message || 'Something went wrong. Please try again.'
}

/** A short name for the passkey, so the list makes sense later ("iPhone", "Mac"). */
export function deviceLabel(): string {
  const ua = navigator.userAgent
  if (/iPhone/.test(ua)) return 'iPhone'
  if (/iPad/.test(ua)) return 'iPad'
  if (/Android/.test(ua)) return 'Android'
  if (/Macintosh/.test(ua)) return 'Mac'
  if (/Windows/.test(ua)) return 'Windows'
  if (/CrOS/.test(ua)) return 'Chromebook'
  return 'Passkey'
}

// ----------------------------------------------------------- public API ---
class ApiError extends Error {
  constructor(message: string, public status: number, public signin = false) { super(message) }
}
export { ApiError as PasskeyApiError }

async function publicPost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`/app${path}`, {
    method: 'POST', credentials: 'same-origin',
    headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new ApiError(data.error ?? `HTTP ${r.status}`, r.status, !!data.signin)
  return data as T
}

export async function joinInfo(token: string): Promise<{ inviter: string; signed_in: boolean }> {
  const r = await fetch(`/app/api/join/${encodeURIComponent(token)}`, { credentials: 'same-origin' })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new ApiError(data.error ?? `HTTP ${r.status}`, r.status)
  return data
}

export async function joinWithPasskey(token: string, name: string, email: string): Promise<void> {
  const t = encodeURIComponent(token)
  const { publicKey } = await publicPost<{ publicKey: CreationJSON }>(`/auth/join/${t}/options`, { name, email })
  const credential = await createPasskey(publicKey)
  await publicPost(`/auth/join/${t}/verify`, { credential, label: deviceLabel() })
}

export async function signInWithPasskey(): Promise<void> {
  const { publicKey } = await publicPost<{ publicKey: RequestJSON }>('/auth/passkey/options', {})
  const credential = await getPasskey(publicKey)
  await publicPost('/auth/passkey/verify', { credential })
}

// -------------------------------------------------------- signed-in API ---
export type PasskeyInfo = { id: string; name: string; created: number | null; last_used: number | null }
export type Invite = {
  id: string; created: number; expires: number; max_uses: number; uses: number
  status: 'active' | 'expired' | 'full' | 'revoked'; created_by: string
  joined: { user_id: string; name: string; at: number }[]
}
export type Member = { user_id: string; name: string; email: string; joined: number | null; passkeys: number }
export type AccessInfo = {
  owner: boolean; can_invite: boolean; google: boolean
  invites: Invite[]; members: Member[]; passkeys: PasskeyInfo[]
}

export const getAccess = () => getJSON<AccessInfo>('/api/access')

export async function addPasskey(): Promise<PasskeyInfo[]> {
  const { publicKey } = await sendJSON<{ publicKey: CreationJSON }>('POST', '/api/passkeys/options', {})
  const credential = await createPasskey(publicKey)
  return (await sendJSON<{ passkeys: PasskeyInfo[] }>('POST', '/api/passkeys', { credential, label: deviceLabel() })).passkeys
}
export const removePasskey = (id: string) =>
  sendJSON<{ passkeys: PasskeyInfo[] }>('DELETE', `/api/passkeys/${encodeURIComponent(id)}`)
export const createInvite = (max_uses: number, days: number) =>
  sendJSON<{ url: string; invite: Invite }>('POST', '/api/invites', { max_uses, days })
export const revokeInvite = (id: string) => sendJSON<{ ok: boolean }>('DELETE', `/api/invites/${encodeURIComponent(id)}`)
export const removeMember = (id: string) => sendJSON<{ ok: boolean }>('DELETE', `/api/members/${encodeURIComponent(id)}`)

/** Share sheet on phones, clipboard elsewhere. Returns what happened for the button label. */
export async function shareLink(url: string): Promise<'shared' | 'copied' | 'failed'> {
  if (navigator.share) {
    try {
      await navigator.share({ title: 'Join me on Rabbit', text: 'Join me on Rabbit, my training app:', url })
      track('share', { what: 'invite' })
      return 'shared'
    } catch (e) {
      if ((e as { name?: string }).name === 'AbortError') return 'failed'
    }
  }
  return copyLink(url)
}

export async function copyLink(url: string): Promise<'copied' | 'failed'> {
  try { await navigator.clipboard.writeText(url); return 'copied' } catch { return 'failed' }
}
