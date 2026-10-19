// "Add by QR": my code to show a friend in person (it's my follow link), and a scanner for
// theirs where the browser can read QR codes (BarcodeDetector: Chrome on Android). On iPhone
// the friend just points their Camera app at the code, which opens Rabbit on "Add friend".
import { useEffect, useRef, useState } from 'react'
import { Check, Copy, ScanLine, Share2 } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/button'
import { QrCode } from './QrCode'
import { getFindMe, type FindMe } from '@/lib/friends'
import { canNativeShare, nativeShare } from '@/lib/sharelinks'

type Detector = { detect: (src: CanvasImageSource) => Promise<{ rawValue: string }[]> }
type DetectorCtor = new (opts: { formats: string[] }) => Detector
const detectorCtor = (): DetectorCtor | null =>
  (typeof window !== 'undefined' && (window as unknown as { BarcodeDetector?: DetectorCtor }).BarcodeDetector) || null

/** The follow code in a Rabbit QR link (``/app/?add=CODE``), or null. */
export function addCodeFrom(text: string): string | null {
  try {
    const u = new URL(text, window.location.origin)
    const c = u.searchParams.get('add') ?? ''
    return u.origin === window.location.origin && /^[A-Z2-9]{8}$/.test(c) ? c : null
  } catch { return null }
}

export function QrSheet({ onClose, onScanned }: { onClose: () => void; onScanned: (code: string) => void }) {
  const [me, setMe] = useState<FindMe | null>(null)
  const [scan, setScan] = useState(false)
  const [copied, setCopied] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { getFindMe().then(setMe, (e) => setErr((e as Error).message)) }, [])
  const canScan = !!detectorCtor() && !!navigator.mediaDevices?.getUserMedia

  async function copy() {
    if (!me) return
    try { await navigator.clipboard.writeText(me.invite_link); setCopied(true); window.setTimeout(() => setCopied(false), 1500) }
    catch { setErr(me.invite_link) }
  }
  return (
    <Sheet title={scan ? 'Scan a friend’s code' : 'My QR code'} onClose={onClose} portal>
      <div className="flex flex-col items-center gap-4 p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
        {scan ? <Scanner onCode={(c) => { setScan(false); onScanned(c) }} onError={(m) => { setScan(false); setErr(m) }} /> : (
          <>
            {me ? <QrCode text={me.invite_link} size={232} label={`QR code to follow @${me.handle} on rabbt`} />
              : <div className="size-[232px] animate-pulse rounded-xl bg-(--bg-inset)" />}
            {me && <p className="font-mono text-[0.9412rem] font-semibold text-(--brand)">@{me.handle}</p>}
            <p className="max-w-xs text-center text-[0.7647rem] leading-snug text-(--text-secondary)">
              A friend points their phone camera at this to follow you. It works for people already on rabbt.
            </p>
            <div className="flex w-full gap-2">
              <Button variant="default" className="h-11 flex-1 gap-1.5" disabled={!me} onClick={() => void copy()}>
                {copied ? <Check className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />} {copied ? 'Copied' : 'Copy link'}
              </Button>
              {canNativeShare() && (
                <Button variant="default" className="h-11 flex-1 gap-1.5" disabled={!me}
                  onClick={() => me && void nativeShare('Follow me on rabbt', `Follow me on rabbt: @${me.handle}`, me.invite_link)}>
                  <Share2 className="size-4" aria-hidden /> Share
                </Button>
              )}
            </div>
            {canScan && (
              <Button variant="primary" className="h-12 w-full gap-2" onClick={() => { setErr(null); setScan(true) }}>
                <ScanLine className="size-5" aria-hidden /> Scan a friend&rsquo;s code
              </Button>
            )}
          </>
        )}
        {err && <p role="alert" className="text-center text-[0.7647rem] text-(--danger)">{err}</p>}
      </div>
    </Sheet>
  )
}

function Scanner({ onCode, onError }: { onCode: (code: string) => void; onError: (msg: string) => void }) {
  const video = useRef<HTMLVideoElement>(null)
  useEffect(() => {
    const Ctor = detectorCtor()
    if (!Ctor) { onError("This browser can't scan codes. Use your phone's Camera app instead."); return }
    const det = new Ctor({ formats: ['qr_code'] })
    let stream: MediaStream | null = null
    let alive = true
    let timer = 0
    const tick = async () => {
      if (!alive || !video.current) return
      try {
        const found = await det.detect(video.current)
        for (const f of found) {
          const code = addCodeFrom(f.rawValue)
          if (code) { alive = false; onCode(code); return }
        }
      } catch { /* frame not ready */ }
      timer = window.setTimeout(() => void tick(), 250)
    }
    navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false }).then((s) => {
      if (!alive) { s.getTracks().forEach((t) => t.stop()); return }
      stream = s
      if (video.current) { video.current.srcObject = s; void video.current.play().catch(() => {}) }
      void tick()
    }, () => onError('rabbt needs the camera to scan. You can allow it in your browser settings.'))
    return () => { alive = false; window.clearTimeout(timer); stream?.getTracks().forEach((t) => t.stop()) }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="relative w-full overflow-hidden rounded-2xl bg-black" style={{ aspectRatio: '1 / 1' }}>
      <video ref={video} muted playsInline className="size-full object-cover" aria-label="Camera" />
      <span aria-hidden className="pointer-events-none absolute inset-[18%] rounded-2xl border-2 border-white/80" />
      <p className="absolute inset-x-0 bottom-3 text-center text-[0.7647rem] font-medium text-white">Point at a rabbt QR code</p>
    </div>
  )
}
