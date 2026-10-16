// Apply the saved Light / Dark choice before first paint (no flash). Classic script: the CSP
// allows only same-origin scripts. lib/theme.ts owns the setting; keep the key in sync.
(function () {
  try {
    var t = localStorage.getItem('rabbit.theme')
    if (t === 'light' || t === 'dark') {
      document.documentElement.classList.add(t)
      var c = t === 'dark' ? '#121413' : '#f5f0e8'
      var m = document.querySelectorAll('meta[name="theme-color"]')
      for (var i = 0; i < m.length; i++) { m[i].setAttribute('content', c); m[i].removeAttribute('media') }
    }
  } catch (e) { /* storage blocked: follow the system */ }
})()
