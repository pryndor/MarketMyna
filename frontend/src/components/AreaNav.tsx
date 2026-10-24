import type { ReactNode } from 'react'
import { cx } from '../lib/cx'
import { Icon, type IconName } from './ui'

/** One menu entry of an area (Markets, Analyze): the rail on wide screens or a chip in the phone row. */
export function NavItem({
  selected,
  icon,
  label,
  onClick,
  rail,
  extra,
}: {
  selected: boolean
  icon: IconName
  label: string
  onClick: () => void
  rail: boolean
  /** A status mark after the label (a spinner while the AI runs). */
  extra?: ReactNode
}) {
  return (
    <button
      type="button"
      aria-current={selected ? 'page' : undefined}
      onClick={onClick}
      className={cx(
        'flex items-center gap-2 whitespace-nowrap rounded-lg text-[13px] font-medium transition-colors',
        rail ? 'w-full px-2.5 py-1.5 text-start' : 'shrink-0 border px-2.5 py-1.5',
        selected
          ? cx('bg-accent-soft text-fg', rail ? 'ring-1 ring-accent/40' : 'border-accent/50')
          : cx('text-muted hover:bg-raised/60 hover:text-fg', !rail && 'border-line'),
      )}
    >
      <Icon name={icon} className={cx('h-3.5 w-3.5', selected ? 'text-accent' : 'text-faint')} />
      {label}
      {extra && <span className="ms-auto flex items-center ps-1">{extra}</span>}
    </button>
  )
}

/** A group of menu entries under a heading (rail) or after a divider (phone row). */
export function NavGroup({ label, rail, children }: { label: string; rail: boolean; children: ReactNode }) {
  return (
    <div className={rail ? 'pt-3' : 'flex shrink-0 items-center gap-1.5 border-s border-line ps-1.5'}>
      {rail && <div className="px-2.5 pb-1 text-[11px] font-semibold uppercase tracking-wide text-faint">{label}</div>}
      {children}
    </div>
  )
}

/** An area with its menu on the left (a scrolling row on phones) and the open part beside it. */
export function AreaLayout({ label, nav, children }: { label: string; nav: (rail: boolean) => ReactNode; children: ReactNode }) {
  return (
    <div className="lg:grid lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-6">
      <nav aria-label={label} className="hidden lg:block">
        <div className="sticky top-4 space-y-0.5">{nav(true)}</div>
      </nav>
      <nav aria-label={label} className="-mx-4 mb-4 flex gap-1.5 overflow-x-auto px-4 pb-1 sm:-mx-6 sm:px-6 lg:hidden">
        {nav(false)}
      </nav>
      <div className="min-w-0">{children}</div>
    </div>
  )
}
