// Apply the saved theme before first paint - no flash. Dark is the default;
// light only when the user picked it with the header toggle. Loaded as a
// plain blocking script from index.html (kept out of the bundle on purpose).
document.documentElement.classList.add('js')
try {
  var t = localStorage.getItem('marketmyna.theme')
  if (t !== 'light') t = 'dark'
  document.documentElement.dataset.theme = t
} catch {
  document.documentElement.dataset.theme = 'dark'
}

// Same for the language: set lang and dir before first paint, so Arabic and
// Persian open right-to-left without a flash. Mirrors detectLanguage() in
// src/i18n/languages.ts (saved choice, else browser language, else English).
;(function () {
  var codes = { en: 'en-IN', es: 'es', pt: 'pt-BR', ru: 'ru', zh: 'zh-CN', ar: 'ar', fa: 'fa' }
  var code = null
  try {
    code = localStorage.getItem('marketmyna.lang')
  } catch {
    // storage unavailable
  }
  if (!codes[code]) {
    code = 'en'
    var tags = navigator.languages || [navigator.language]
    for (var i = 0; i < tags.length; i++) {
      var c = String(tags[i] || '').toLowerCase().split('-')[0]
      if (codes[c]) {
        code = c
        break
      }
    }
  }
  document.documentElement.lang = codes[code]
  document.documentElement.dir = code === 'ar' || code === 'fa' ? 'rtl' : 'ltr'
})()
