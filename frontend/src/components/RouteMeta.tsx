import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { titleFor } from '../seo/meta'

// The browser tab title per page. A private, self-hosted app: no search tags
// (index.html says noindex).
export default function RouteMeta() {
  const { pathname } = useLocation()
  useEffect(() => {
    document.title = titleFor(pathname)
  }, [pathname])
  return null
}
