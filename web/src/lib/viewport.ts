// Keep the app inside the *visual* viewport. iOS doesn't resize the page when the
// keyboard opens; it shrinks and shifts the visual viewport instead. The app shell is a
// fixed frame sized and offset to match (--vv-h, --vv-top), so the header stays visible
// and the composer sits right on the keyboard. We only follow iOS here, never scroll
// the page ourselves (fighting its keyboard scrolling breaks the layout).
//
// Keyboard detection compares the visual viewport with the tallest it has been (the
// full screen), not window.innerHeight: iOS Home Screen apps shrink innerHeight with the
// keyboard too (observed: innerHeight 481 = visual height, full 894).
// Sets html.kb-open so the composer drops its home-indicator padding.
export function trackKeyboard(): void {
  const vv = window.visualViewport
  if (!vv) return
  const root = document.documentElement
  let full = Math.max(vv.height, window.innerHeight)
  let frame = 0
  const update = () => {
    cancelAnimationFrame(frame)
    frame = requestAnimationFrame(() => {
      if (vv.height > full) full = vv.height
      const keyboard = full - vv.height > 120
      root.style.setProperty('--vv-h', `${vv.height}px`)
      root.style.setProperty('--vv-top', `${vv.offsetTop}px`)
      root.classList.toggle('kb-open', keyboard)
      if (keyboard) requestAnimationFrame(revealFocused)  // after the tab bar steps aside
      else if (padded.size) unpad()
    })
  }
  // A field focused while the keyboard is already up (moving between fields).
  document.addEventListener('focusin', () => { if (root.classList.contains('kb-open')) window.setTimeout(revealFocused, 60) })
  vv.addEventListener('resize', update)
  vv.addEventListener('scroll', update)
  window.addEventListener('orientationchange', () => { full = 0; update() })
  update()
}

const padded = new Set<HTMLElement>()
function unpad(): void { for (const a of padded) a.style.paddingBottom = ''; padded.clear() }

const editable = (el: Element | null): el is HTMLElement =>
  !!el && (el instanceof HTMLTextAreaElement || (el instanceof HTMLInputElement && !['checkbox', 'radio', 'range', 'button', 'submit', 'file'].includes(el.type))
    || (el as HTMLElement).isContentEditable)

/** Keep the focused text field above the keyboard: scroll its own scrolling container (never the
 *  page, which iOS manages) just enough that the field, and a send button beside it, show. */
function revealFocused(): void {
  const el = document.activeElement
  if (!editable(el)) return
  const vv = window.visualViewport
  const bottomLimit = (vv ? vv.height : window.innerHeight) - 12
  // The field, or its row when the row is just the field plus a send button beside it.
  const own = el.getBoundingClientRect()
  const row = el.parentElement?.getBoundingClientRect()
  const box = row && row.height <= own.height + 16 ? row : own
  for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
    const st = getComputedStyle(a)
    if (!/(auto|scroll)/.test(st.overflowY) || a.scrollHeight <= a.clientHeight) continue
    const top = a.getBoundingClientRect().top + 8
    // A tall field (a post's text box) keeps its top in view rather than its bottom.
    const over = Math.min(box.bottom - Math.min(bottomLimit, a.getBoundingClientRect().bottom - 8), box.top - top)
    const under = top - box.top
    if (over > 0) {
      // Near the end of a short list there may be nothing left to scroll: add room below
      // until the keyboard closes.
      const room = a.scrollHeight - a.clientHeight - a.scrollTop
      if (room < over) { a.style.paddingBottom = `${parseFloat(getComputedStyle(a).paddingBottom) + over - room}px`; padded.add(a) }
      a.scrollTop += over
    } else if (under > 0) a.scrollTop -= under
    return
  }
}
