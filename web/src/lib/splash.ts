// The launch screen in index.html (#splash): shown before any JS, faded out once the app has
// something real to show (App calls hideSplash when /api/me answers), with a time limit so a
// slow network never leaves it up.
let done = false

export function hideSplash() {
  if (done) return
  done = true
  const el = document.getElementById('splash')
  if (!el) return
  el.classList.add('is-gone')
  window.setTimeout(() => el.remove(), 400)
}

/** Safety net: never keep the launch screen longer than this. */
export function hideSplashLater(ms = 4000) {
  window.setTimeout(hideSplash, ms)
}
