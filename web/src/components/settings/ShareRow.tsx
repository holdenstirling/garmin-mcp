// Settings: a read-only link to your plan (next two weeks + events). New link or off anytime.
import { useEffect, useState } from 'react'
import { Copy, Link2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { createShare, getShare, stopShare } from '@/lib/share'
import { Icon, Row } from './Grouped'

export function ShareRow() {
  const [url, setUrl] = useState<string | null | undefined>(undefined)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  useEffect(() => { getShare().then((r) => setUrl(r.url), () => setUrl(null)) }, [])
  async function run(fn: () => Promise<{ url: string | null }>, ok: string) {
    setBusy(true); setMsg(null)
    try { setUrl((await fn()).url); setMsg(ok) } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) }
  }
  if (url === undefined) return null
  return url ? (
    <div className="flex flex-col gap-2 px-4 py-3">
      <span className="flex items-center gap-3"><Icon><Link2 /></Icon><span className="text-[0.9412rem] text-(--text)">Read-only plan link</span></span>
      <div className="flex items-center gap-2">
        <code className="min-w-0 flex-1 truncate rounded-md bg-(--bg-inset) px-2 py-1.5 text-[0.7059rem]">{url}</code>
        <Button variant="default" size="icon" className="size-9" aria-label="Copy link"
          onClick={() => void navigator.clipboard?.writeText(url).then(() => setMsg('Link copied.'), () => {})}><Copy className="size-4" /></Button>
      </div>
      <div className="flex gap-2">
        <Button variant="default" className="h-8 px-3 text-[0.7059rem]" loading={busy} onClick={() => void run(createShare, 'New link made; the old one stopped working.')}>New link</Button>
        <Button variant="ghost" className="h-8 px-3 text-[0.7059rem] text-(--danger)" disabled={busy} onClick={() => void run(stopShare, 'Sharing is off.')}>Turn off</Button>
      </div>
      {msg && <p className="text-[0.7059rem] text-(--text-muted)">{msg}</p>}
    </div>
  ) : (
    <Row icon={<Icon><Link2 /></Icon>} title="Share my plan" subtitle="A read-only link: next two weeks and your events. No chats or health data."
      disabled={busy} onClick={() => void run(createShare, 'Link ready. Copy it and send it.')} />
  )
}
