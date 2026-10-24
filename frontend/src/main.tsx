import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './i18n'
import App from './App.tsx'

// A tab opened before a deploy asks for page chunks that no longer exist:
// reload once to pick up the new build instead of showing a blank page.
window.addEventListener('vite:preloadError', (event) => {
  try {
    const last = Number(sessionStorage.getItem('chunk-reload') || 0)
    if (Date.now() - last < 60_000) return
    sessionStorage.setItem('chunk-reload', String(Date.now()))
  } catch {
    return
  }
  event.preventDefault()
  window.location.reload()
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
