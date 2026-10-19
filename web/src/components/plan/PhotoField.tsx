// Profile photo picker: resized to 256x256 in the browser, then uploaded. Your coaches see
// it too; otherwise your Google photo (or initial) is used.
import { useRef, useState } from 'react'
import { Trash2, Upload } from 'lucide-react'
import { Avatar } from '@/components/Avatar'
import { Button } from '@/components/ui/button'
import type { Me } from '@/lib/api'
import { deletePhoto, photoUrl, resizePhoto, uploadPhoto } from '@/lib/photo'
import { Card } from './ui'

export function PhotoField({ me, onChanged }: { me: Me; onChanged: () => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [version, setVersion] = useState<number | null>(me.photo ?? null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function pick(file: File | undefined) {
    if (!file) return
    setBusy(true); setError(null)
    try {
      setVersion(await uploadPhoto(await resizePhoto(file)))
      onChanged()
    } catch (e) { setError((e as Error).message) }
    finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  async function remove() {
    setBusy(true); setError(null)
    try { await deletePhoto(); setVersion(null); onChanged() }
    catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }

  return (
    <Card className="flex items-center gap-4 px-4 py-3.5">
      <Avatar name={me.profile.name || me.user_id} picture={me.profile.picture} photo={photoUrl(version)} size={64} />
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <span className="text-caption font-semibold text-(--text-muted)">Profile photo</span>
        <div className="flex flex-wrap gap-2">
          <Button variant="default" className="h-9 gap-1.5 px-3 text-small" loading={busy} onClick={() => input.current?.click()}>
            <Upload className="size-5" /> {version ? 'Change' : 'Upload'}
          </Button>
          {version != null && (
            <Button variant="ghost" className="h-9 gap-1.5 px-3 text-small text-(--danger)" disabled={busy} onClick={() => void remove()}>
              <Trash2 className="size-5" /> Remove
            </Button>
          )}
        </div>
        {error && <span className="text-meta text-(--danger)" role="alert">{error}</span>}
        <input ref={input} type="file" accept="image/*" className="hidden"
          onChange={(e) => void pick(e.target.files?.[0])} />
      </div>
    </Card>
  )
}
