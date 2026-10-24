import { useEffect, useState } from 'react'

type Theme = 'dark' | 'light'

const KEY = 'marketmyna.theme'
const THEME_COLORS: Record<Theme, string> = { dark: '#002b36', light: '#f2f4f7' }

function currentTheme(): Theme {
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'
}

export function setTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLORS[theme])
  try {
    localStorage.setItem(KEY, theme)
  } catch {
    // storage unavailable - the choice lasts for this page only
  }
}

/** The active theme, updating when the header toggle changes it (charts
 * that read colors once, like the candlestick chart, re-render on it). */
export function useTheme(): Theme {
  const [theme, setState] = useState<Theme>(currentTheme)
  useEffect(() => {
    const observer = new MutationObserver(() => setState(currentTheme()))
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])
  return theme
}
