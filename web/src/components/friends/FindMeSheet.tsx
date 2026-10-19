// "Your @handle and who can find you": the handle (for search and @mentions), an optional
// phone number (not verified: only used so friends can find you), and three switches.
import { useEffect, useState } from 'react'
import { AtSign } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/settings/Grouped'
import { inputCls } from '@/components/plan/ui'
import { getFindMe, putFindMe, type FindMe } from '@/lib/friends'

export function FindMeSheet({ onClose, onSaved }: { onClose: () => void; onSaved?: (m: FindMe) => void }) {
  const [me, setMe] = useState<FindMe | null>(null)
  const [handle, setHandle] = useState('')
  const [phone, setPhone] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null)
  useEffect(() => {
    getFindMe().then((m) => { setMe(m); setHandle(m.handle); setPhone(m.phone ?? '') }, (e) => setMsg({ text: (e as Error).message, ok: false }))
  }, [])

  async function save(key: string, patch: Parameters<typeof putFindMe>[0], ok: string) {
    setBusy(key); setMsg(null)
    try { const m = await putFindMe(patch); setMe(m); setHandle(m.handle); setPhone(m.phone ?? ''); setMsg({ text: ok, ok: true }); onSaved?.(m) }
    catch (e) { setMsg({ text: (e as Error).message, ok: false }) }
    finally { setBusy(null) }
  }
  const toggle = (k: keyof FindMe['find'], v: boolean) => {
    if (!me) return
    setMe({ ...me, find: { ...me.find, [k]: v } })
    void save(k, { find: { [k]: v } }, 'Saved.')
  }
  const cleanHandle = handle.trim().replace(/^@/, '').toLowerCase()

  return (
    <Sheet title="How friends find you" onClose={onClose} portal>
      <div className="flex flex-col gap-5 p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
        <section className="flex flex-col gap-2">
          <label htmlFor="ff-handle" className="text-body font-semibold text-(--text)">Your @handle</label>
          <div className="flex gap-2">
            <div className="relative min-w-0 flex-1">
              <AtSign className="pointer-events-none absolute left-3 top-1/2 size-5 -translate-y-1/2 text-(--text-muted)" aria-hidden />
              <input id="ff-handle" className={`${inputCls} pl-9`} value={handle.replace(/^@/, '')} autoCapitalize="none" autoCorrect="off"
                spellCheck={false} maxLength={21} inputMode="text" onChange={(e) => setHandle(e.target.value)} />
            </div>
            <Button variant="primary" className="h-11 px-4" loading={busy === 'handle'} disabled={!me || cleanHandle === me.handle || cleanHandle.length < 3}
              onClick={() => void save('handle', { handle: cleanHandle }, 'Handle saved.')}>Save</Button>
          </div>
          <p className="text-meta leading-snug text-(--text-muted)">Friends can search for it and tag you in comments. Letters, numbers, _ and .</p>
        </section>

        <section className="flex flex-col gap-2">
          <label htmlFor="ff-phone" className="text-body font-semibold text-(--text)">Phone number <span className="font-normal text-(--text-muted)">(optional)</span></label>
          <div className="flex gap-2">
            <input id="ff-phone" className={inputCls} type="tel" inputMode="tel" autoComplete="tel" placeholder="(303) 555-1234"
              value={phone} onChange={(e) => setPhone(e.target.value)} />
            <Button variant="primary" className="h-11 px-4" loading={busy === 'phone'} disabled={!me || phone.trim() === (me.phone ?? '')}
              onClick={() => void save('phone', { phone: phone.trim() || null }, phone.trim() ? 'Number saved.' : 'Number removed.')}>Save</Button>
          </div>
          <p className="text-meta leading-snug text-(--text-muted)">Only so friends who have your number can find you. Never shown to anyone, never texted.</p>
        </section>

        <section className="flex flex-col gap-1">
          <p className="text-body font-semibold text-(--text)">Let people find me by</p>
          {me && ([
            ['name', 'My name and @handle', 'In Find friends search'],
            ['email', 'My email', 'When someone has it in their contacts or types it'],
            ['phone', 'My phone number', me.phone ? 'When someone has it in their contacts' : 'Add a number above first'],
          ] as const).map(([k, title, sub]) => (
            <div key={k} className="flex min-h-14 items-center gap-3 border-b border-(--border) py-2 last:border-0">
              <span className="min-w-0 flex-1">
                <span className="block text-lead text-(--text)">{title}</span>
                <span className="block text-meta text-(--text-muted)">{sub}</span>
              </span>
              <Switch checked={k === 'phone' && !me.phone ? false : me.find[k]} label={title} disabled={k === 'phone' && !me.phone} onChange={(v) => toggle(k, v)} />
            </div>
          ))}
          <p className="pt-1 text-meta leading-snug text-(--text-muted)">People you already follow, or who follow you, can always find you. Blocked people never can.</p>
        </section>
        {msg && <p role="status" className={msg.ok ? 'text-small text-(--accent)' : 'text-small text-(--danger)'}>{msg.text}</p>}
      </div>
    </Sheet>
  )
}
