// Open a place in the app from any component without prop drilling (screens/Chat.tsx listens).
// e.g. a group sheet with no friends yet -> Clubs > People to find some.
export const OPEN_PLACE_EVENT = 'rabbit:open-place'
export type Place = 'people' | 'clubs' | 'feed' | 'events' | 'plan' | 'progress' | 'connections'

export function openPlace(place: Place) {
  try { window.dispatchEvent(new CustomEvent<Place>(OPEN_PLACE_EVENT, { detail: place })) } catch { /* old browsers */ }
}

/** Fired (detail: tab id) whenever a bottom tab is shown; kept-mounted tabs refresh stale bits. */
export const TAB_SHOWN_EVENT = 'rabbit:tab-shown'
