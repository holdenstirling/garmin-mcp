// Appearance: System (follow the phone), Light or Dark. Stored on this device; public/theme.js
// applies it before first paint. Sets html.light / html.dark (globals.css, rabbit.css and the
// Tailwind `dark:` variant all honor both) and the browser chrome color.
import { useSyncExternalStore } from 'react'

export type Theme = 'system' | 'light' | 'dark'
const KEY = 'rabbit.theme'
const COLOR = { light: '#f5f0e8', dark: '#121413' } as const
const listeners = new Set<() => void>()

export function getTheme(): Theme {
  try {
    const t = localStorage.getItem(KEY)
    return t === 'light' || t === 'dark' ? t : 'system'
  } catch { return 'system' }
}

function apply(t: Theme) {
  const root = document.documentElement
  root.classList.remove('light', 'dark')
  if (t !== 'system') root.classList.add(t)
  const metas = Array.from(document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]'))
  metas.forEach((m, i) => {
    if (t === 'system') {
      // back to one color per scheme (index.html order: light, dark)
      const scheme = i === 0 ? 'light' : 'dark'
      m.setAttribute('media', `(prefers-color-scheme: ${scheme})`)
      m.setAttribute('content', COLOR[scheme])
    } else {
      m.removeAttribute('media')
      m.setAttribute('content', COLOR[t])
    }
  })
}

export function setTheme(t: Theme) {
  try { if (t === 'system') localStorage.removeItem(KEY); else localStorage.setItem(KEY, t) } catch { /* ignore */ }
  apply(t)
  listeners.forEach((l) => l())
}

export function useTheme(): Theme {
  return useSyncExternalStore((cb) => { listeners.add(cb); return () => { listeners.delete(cb) } }, getTheme, () => 'system')
}

export const THEME_LABEL: Record<Theme, string> = { system: 'Match phone', light: 'Light', dark: 'Dark' }
