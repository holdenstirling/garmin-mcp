// Progress "Refresh" / pull-to-refresh: every card re-reads when ``loadKey`` bumps and hands its
// request to ``useTrackRefresh()``, so the pull rabbit keeps hopping until all of them land.
import { createContext, useCallback, useContext, useEffect, useRef } from 'react'

type Track = (p: Promise<unknown>) => void
const Ctx = createContext<Track | null>(null)

/** Cards call the returned function with each load they start. */
export function useTrackRefresh(): Track {
  const t = useContext(Ctx)
  return useCallback((p: Promise<unknown>) => { t?.(p) }, [t])
}

/** Owner side: ``refresh(bump)`` bumps the key and resolves when every card that reloaded
 *  for it (children's effects run before the owner's) has settled. */
export function useRefreshGroup(loadKey: number) {
  const pending = useRef<Promise<unknown>[]>([])
  const waiting = useRef<((p: Promise<unknown>) => void) | null>(null)
  const track = useCallback<Track>((p) => { pending.current.push(p.catch(() => {})) }, [])
  useEffect(() => {
    const done = waiting.current
    if (!done) return
    waiting.current = null
    done(Promise.all(pending.current))
  }, [loadKey])
  const refresh = useCallback((bump: () => void, own?: Promise<unknown>): Promise<unknown> => {
    pending.current = own ? [own.catch(() => {})] : []
    return new Promise<Promise<unknown>>((resolve) => { waiting.current = resolve; bump() }).then((all) => all)
  }, [])
  return { track, refresh, Provider: Ctx.Provider }
}
