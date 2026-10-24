import { useEffect, useState, type RefObject } from 'react'
import { cx } from '../lib/cx'
import { Card, CardHeader } from './ui'

interface Entry {
  id: string
  label: string
}

/** A section counts as current once its top passes this line (px from the viewport top). */
const ACTIVE_LINE = 120

function collect(root: HTMLElement): Entry[] {
  return Array.from(root.querySelectorAll<HTMLElement>('[data-section][id]')).map((el) => ({
    id: el.id,
    label: el.dataset.section ?? el.id,
  }))
}

function sameEntries(a: Entry[], b: Entry[]) {
  return a.length === b.length && a.every((e, i) => e.id === b[i].id && e.label === b[i].label)
}

/** "On this page" jump list for every card under `root` tagged with
 * `id` + `data-section` (Card's `id`/`section` props). Picks up cards that
 * load later (AI decision, financials) and highlights the one in view.
 * `fill`: shrink to the height its (flex) parent leaves and scroll the list,
 * so it can share a sticky column with another card. */
export default function SectionIndex({ root, fill = false }: { root: RefObject<HTMLElement | null>; fill?: boolean }) {
  const [entries, setEntries] = useState<Entry[]>([])
  const [active, setActive] = useState<string | null>(null)

  useEffect(() => {
    const el = root.current
    if (!el) return
    const refresh = () => setEntries((prev) => {
      const next = collect(el)
      return sameEntries(prev, next) ? prev : next
    })
    refresh()
    const observer = new MutationObserver(refresh)
    observer.observe(el, { childList: true, subtree: true })
    return () => observer.disconnect()
  }, [root])

  useEffect(() => {
    if (!entries.length) return
    let frame = 0
    const update = () => {
      frame = 0
      let current = entries[0].id
      for (const e of entries) {
        const node = document.getElementById(e.id)
        if (node && node.getBoundingClientRect().top <= ACTIVE_LINE) current = e.id
      }
      // At the very bottom the last short cards can never reach the line.
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) {
        current = entries[entries.length - 1].id
      }
      setActive(current)
    }
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update)
    }
    update()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
      if (frame) cancelAnimationFrame(frame)
    }
  }, [entries])

  if (!entries.length) return null

  return (
    <Card className={fill ? 'hidden max-h-full min-h-0 flex-col lg:flex' : 'hidden lg:block'}>
      <CardHeader title="On this page" description={`${entries.length} sections`} />
      <nav aria-label="Sections on this page" className={cx('px-3 py-3', fill && 'min-h-0 flex-1 overflow-y-auto')}>
        <ol className="space-y-0.5">
          {entries.map((e) => {
            const isActive = e.id === active
            return (
              <li key={e.id}>
                <button
                  type="button"
                  onClick={() => {
                    document.getElementById(e.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                    setActive(e.id)
                  }}
                  aria-current={isActive ? 'location' : undefined}
                  className={cx(
                    'relative flex w-full items-center rounded-md py-1.5 pe-2 ps-4 text-start text-sm transition-colors',
                    isActive ? 'bg-accent-soft font-medium text-accent-fg' : 'text-muted hover:bg-raised hover:text-fg',
                  )}
                >
                  <span
                    className={cx(
                      'absolute top-1.5 bottom-1.5 start-1.5 w-0.5 rounded-full transition-colors',
                      isActive ? 'bg-accent' : 'bg-transparent',
                    )}
                  />
                  <span className="truncate">{e.label}</span>
                </button>
              </li>
            )
          })}
        </ol>
      </nav>
    </Card>
  )
}
