// Keep every open copy of Rabbit on the newest version. A Home Screen app (iOS especially) can
// stay open in memory for days and never reload after a deploy. The build's entry script name
// changes with every deploy (/app/assets/index-<hash>.js), so we compare it with what /app/
// serves now:
//   * coming back to the app (it was in the background): reload straight away if it changed,
//     before anything is touched (drafts and unsent saves are kept on the device anyway);
//   * while open: check every 10 minutes and offer "Update" (components/ui/UpdatePill).
export const UPDATE_READY_EVENT = 'rabbit:update-ready'

const ENTRY = /src="(\/app\/assets\/index-[^"]+\.js)"/
let ready = false

function running(): string | null {
  const s = document.querySelector<HTMLScriptElement>('script[type="module"][src*="/app/assets/index-"]')
  return s ? new URL(s.src, location.origin).pathname : null
}

/** true when the server has a newer build than the one running. */
export async function newVersionOut(): Promise<boolean> {
  const mine = running()
  if (!mine) return false  // dev server: nothing to compare
  try {
    const r = await fetch('/app/', { cache: 'no-store', credentials: 'same-origin' })
    if (!r.ok) return false
    const live = ENTRY.exec(await r.text())?.[1]
    return !!live && live !== mine
  } catch { return false }  // offline: try again later
}

export function isUpdateReady() { return ready }

export function reloadNow() {
  try { sessionStorage.setItem('rabbit-updated', String(Date.now())) } catch { /* ignore */ }
  location.reload()
}

const typing = () => {
  const a = document.activeElement
  return !!a && (a instanceof HTMLInputElement || a instanceof HTMLTextAreaElement || (a as HTMLElement).isContentEditable)
}

let started = false
export function startUpdateChecks() {
  if (started) return
  started = true
  let hiddenAt = 0
  const flag = () => {
    if (ready) return
    ready = true
    try { window.dispatchEvent(new CustomEvent(UPDATE_READY_EVENT)) } catch { /* ignore */ }
  }
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') { hiddenAt = Date.now(); return }
    const away = hiddenAt ? Date.now() - hiddenAt : 0
    void newVersionOut().then((yes) => {
      if (!yes) return
      // Back after a while and not mid-typing: just load the new version.
      if (away > 30_000 && !typing()) reloadNow()
      else flag()
    })
  })
  window.setInterval(() => {
    if (document.visibilityState === 'visible') void newVersionOut().then((yes) => { if (yes) flag() })
  }, 10 * 60_000)
  // First check shortly after start (an app restored from memory may already be behind).
  window.setTimeout(() => { void newVersionOut().then((yes) => { if (yes) flag() }) }, 5_000)
}
