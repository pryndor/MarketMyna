import { useEffect, useRef, useState, type MouseEvent } from 'react'
import { useTranslation } from 'react-i18next'
import type { NewItem } from '../api/watchlists'
import { cx } from '../lib/cx'
import { itemKey, useWatchlists } from '../lib/watchlists'
import { Icon } from './ui'

/** Star toggle for any instrument. With one watchlist it toggles
 * directly; with several it opens a small menu to pick lists. */
export default function WatchButton({
  item,
  showLabel = false,
}: {
  item: NewItem
  showLabel?: boolean
}) {
  const { t } = useTranslation('app')
  const { lists, members, loaded, load, add, remove } = useWatchlists()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!loaded) load()
  }, [loaded, load])

  useEffect(() => {
    if (!open) return
    const close = (e: globalThis.MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  const key = itemKey(item)
  const inLists = new Set(members.filter((m) => itemKey(m) === key).map((m) => m.watchlist_id))
  const watched = inLists.size > 0

  async function toggle(listId: number) {
    setBusy(true)
    try {
      if (inLists.has(listId)) await remove(listId, item)
      else await add(listId, item)
    } finally {
      setBusy(false)
    }
  }

  function onClick(e: MouseEvent) {
    // Buttons sit inside clickable table rows - don't open the row.
    e.stopPropagation()
    if (!lists.length) return
    if (lists.length === 1) toggle(lists[0].id)
    else setOpen((v) => !v)
  }

  const label = watched ? t('watch.watching') : t('watch.watch')
  return (
    <div ref={ref} className="relative inline-block" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        onClick={onClick}
        disabled={busy || !loaded}
        aria-pressed={watched}
        aria-haspopup={lists.length > 1 ? 'menu' : undefined}
        title={watched ? t('watch.inList') : t('watch.add')}
        className={cx(
          'inline-flex items-center gap-1.5 rounded-md transition-colors disabled:opacity-50',
          showLabel ? 'border border-line-strong bg-raised px-3 py-1.5 text-xs font-medium hover:border-faint' : 'p-1',
          watched ? 'text-warn' : 'text-faint hover:text-fg',
        )}
      >
        <Icon name="star" className={cx('h-4 w-4', watched && 'fill-current')} />
        {showLabel && <span className={watched ? 'text-fg' : undefined}>{label}</span>}
      </button>
      {open && (
        <div
          role="menu"
          className="absolute end-0 z-30 mt-1 w-56 rounded-lg border border-line-strong bg-raised py-1 text-start shadow-xl"
        >
          <div className="px-3 py-1.5 text-xs text-muted">{t('watch.addTo', { symbol: item.symbol })}</div>
          {lists.map((l) => (
            <button
              key={l.id}
              type="button"
              role="menuitemcheckbox"
              aria-checked={inLists.has(l.id)}
              onClick={() => toggle(l.id)}
              disabled={busy}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-sm hover:bg-line"
            >
              <span
                className={cx(
                  'grid h-4 w-4 place-items-center rounded border',
                  inLists.has(l.id) ? 'border-accent bg-accent text-white' : 'border-line-strong',
                )}
              >
                {inLists.has(l.id) && <Icon name="check" className="h-3 w-3" />}
              </span>
              <span className="truncate">{l.name}</span>
              <span className="ms-auto text-xs text-faint">{l.count}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
