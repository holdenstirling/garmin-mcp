// The one photo picker for posts: the composer, "Add photos or a caption" on an auto-shared
// workout, and editing a post. A big "Add photos" tile when there are none; after that a row of
// thumbnails (each uploads on its own, with a spinner, a Retry on failure and an X to remove)
// and a small tile to add more. Photos are resized on the phone (lib/community resizeForPost)
// and uploaded as soon as they're picked, so posting is instant. Gallery and camera both work:
// the gallery input's system menu offers the camera too, and on phones a separate camera
// button opens it straight away.
import { useEffect, useRef, useState } from 'react'
import { Camera, ImagePlus, LoaderCircle, RotateCw, X } from 'lucide-react'
import { MAX_PHOTOS, resizeForPost, uploadPostPhoto } from '@/lib/community'
import { cn } from '@/lib/utils'

export type PickedPhoto = {
  key: string
  /** server photo id once uploaded */
  id: string | null
  url: string
  state: 'uploading' | 'done' | 'error'
  error?: string
  file?: File
}

let seq = 0
const nextKey = () => `ph${Date.now().toString(36)}${(seq++).toString(36)}`

/** Photos already on a post (an edit): ids + their URLs, already uploaded. */
export function existingPhotos(ids: string[] | undefined, urls: string[]): PickedPhoto[] {
  if (!ids || ids.length !== urls.length) return []
  return ids.map((id, i) => ({ key: `old-${id}`, id, url: urls[i]!, state: 'done' as const }))
}

export function usePhotoPicker(initial: PickedPhoto[] = [], max = MAX_PHOTOS) {
  const [items, setItems] = useState<PickedPhoto[]>(initial)
  const made = useRef<string[]>([])
  useEffect(() => () => made.current.forEach((u) => URL.revokeObjectURL(u)), [])

  const patch = (key: string, p: Partial<PickedPhoto>) => setItems((xs) => xs.map((x) => (x.key === key ? { ...x, ...p } : x)))

  async function upload(key: string, file: File) {
    patch(key, { state: 'uploading', error: undefined })
    try {
      const blob = await resizeForPost(file)
      const url = URL.createObjectURL(blob)
      made.current.push(url)
      patch(key, { url })
      const id = await uploadPostPhoto(blob)
      patch(key, { id, state: 'done' })
    } catch (e) {
      patch(key, { state: 'error', error: (e as Error).message || "Couldn't upload" })
    }
  }

  async function add(files: FileList | File[] | null) {
    if (!files) return
    const room = Math.max(0, max - items.length)
    const list = Array.from(files).filter((f) => f.type.startsWith('image/') || /\.(hei[cf]|jpe?g|png|webp)$/i.test(f.name)).slice(0, room)
    if (!list.length) return
    const fresh = list.map((file) => {
      let url = ''
      try { url = URL.createObjectURL(file); made.current.push(url) } catch { /* preview comes after resize */ }
      return { key: nextKey(), id: null, url, state: 'uploading' as const, file }
    })
    setItems((xs) => [...xs, ...fresh])
    // One at a time keeps the order and is kind to a phone's connection.
    for (const f of fresh) await upload(f.key, f.file)
  }

  return {
    items,
    ids: items.filter((x) => x.state === 'done' && x.id).map((x) => x.id!),
    busy: items.some((x) => x.state === 'uploading'),
    failed: items.some((x) => x.state === 'error'),
    full: items.length >= max,
    max,
    add,
    remove: (key: string) => setItems((xs) => xs.filter((x) => x.key !== key)),
    retry: (key: string) => { const it = items.find((x) => x.key === key); if (it?.file) void upload(key, it.file) },
    clear: () => setItems([]),
  }
}

export type PhotoPickerState = ReturnType<typeof usePhotoPicker>

const touch = () => { try { return window.matchMedia('(pointer: coarse)').matches } catch { return false } }

export function PhotoPicker({ picker, className }: { picker: PhotoPickerState; className?: string }) {
  const gallery = useRef<HTMLInputElement>(null)
  const camera = useRef<HTMLInputElement>(null)
  const [phone] = useState(touch)
  const { items, full, max } = picker
  const onPick = (e: React.ChangeEvent<HTMLInputElement>) => { void picker.add(e.target.files); e.target.value = '' }
  const inputs = (
    <>
      <input ref={gallery} type="file" accept="image/*" multiple className="hidden" onChange={onPick} aria-hidden tabIndex={-1} />
      <input ref={camera} type="file" accept="image/*" capture="environment" className="hidden" onChange={onPick} aria-hidden tabIndex={-1} />
    </>
  )

  if (!items.length) {
    return (
      <div className={cn('flex gap-2', className)}>
        {inputs}
        <button type="button" onClick={() => gallery.current?.click()}
          className="flex min-h-[88px] flex-1 flex-col items-center justify-center gap-1 rounded-2xl border border-dashed border-(--border) bg-(--bg-surface) px-3 text-(--accent) active:bg-(--bg-inset)">
          <ImagePlus className="size-6" aria-hidden />
          <span className="text-[0.8235rem] font-semibold">Add photos</span>
          <span className="text-[0.6471rem] text-(--text-muted)">Up to {max}</span>
        </button>
        {phone && (
          <button type="button" onClick={() => camera.current?.click()} aria-label="Take a photo"
            className="flex min-h-[88px] w-[88px] shrink-0 flex-col items-center justify-center gap-1 rounded-2xl border border-dashed border-(--border) bg-(--bg-surface) text-(--accent) active:bg-(--bg-inset)">
            <Camera className="size-6" aria-hidden />
            <span className="text-[0.6471rem] font-medium">Camera</span>
          </button>
        )}
      </div>
    )
  }

  return (
    <div className={cn('flex flex-col gap-1', className)}>
      {inputs}
      <ul className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 pt-1" aria-label={`${items.length} of ${max} photos`}>
        {items.map((p, i) => (
          <li key={p.key} className="relative size-[88px] shrink-0">
            {p.url
              ? <img src={p.url} alt={`Photo ${i + 1}`} className={cn('size-full rounded-xl object-cover', p.state !== 'done' && 'opacity-60')} />
              : <span className="block size-full rounded-xl bg-(--bg-inset)" />}
            {p.state === 'uploading' && (
              <span className="absolute inset-0 flex items-center justify-center" role="status" aria-label={`Uploading photo ${i + 1}`}>
                <LoaderCircle className="size-6 animate-spin text-white drop-shadow" aria-hidden />
              </span>
            )}
            {p.state === 'error' && (
              <button type="button" onClick={() => picker.retry(p.key)} title={p.error}
                aria-label={`Photo ${i + 1} didn't upload: ${p.error ?? ''}. Retry`}
                className="absolute inset-0 flex flex-col items-center justify-center gap-0.5 rounded-xl bg-black/55 text-[0.6471rem] font-semibold text-white">
                <RotateCw className="size-5" aria-hidden /> Retry
              </button>
            )}
            <button type="button" aria-label={`Remove photo ${i + 1}`} onClick={() => picker.remove(p.key)}
              className="absolute -right-1.5 -top-1.5 flex size-7 items-center justify-center rounded-full bg-(--text) text-(--bg) shadow-sm">
              <X className="size-3.5" aria-hidden />
            </button>
          </li>
        ))}
        {!full && (
          <li className="flex shrink-0 flex-col gap-2">
            <button type="button" onClick={() => gallery.current?.click()} aria-label="Add more photos"
              className="flex size-[88px] flex-col items-center justify-center gap-0.5 rounded-xl border border-dashed border-(--border) text-(--accent) active:bg-(--bg-inset)">
              <ImagePlus className="size-5" aria-hidden />
              <span className="text-[0.6471rem] font-medium">{items.length}/{max}</span>
            </button>
          </li>
        )}
      </ul>
      {picker.failed && (
        <p className="text-[0.6471rem] text-(--danger)" role="alert">
          {items.find((x) => x.state === 'error')?.error ?? "A photo didn't upload."} Tap it to retry, or remove it.
        </p>
      )}
    </div>
  )
}
