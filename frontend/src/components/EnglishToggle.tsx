import { setEnglish, useEnglish } from '../lib/english'
import { cx } from '../lib/cx'
import { Spinner } from './ui'

/** "中 / EN" pill that switches Chinese names to English app-wide. */
export default function EnglishToggle({ loading = false, className }: { loading?: boolean; className?: string }) {
  const on = useEnglish()
  return (
    <button
      type="button"
      onClick={() => setEnglish(!on)}
      title={on ? 'Showing English names - click for the original Chinese' : 'Show Chinese names in English'}
      className={cx(
        'inline-flex shrink-0 items-center gap-1.5 rounded-md border px-2 py-1 text-xs whitespace-nowrap',
        on ? 'border-accent bg-accent/10 text-fg' : 'border-line text-muted hover:border-line-strong hover:text-fg',
        className,
      )}
    >
      {loading && on ? <Spinner className="h-3 w-3 text-accent" /> : <span aria-hidden>{on ? 'EN' : '中'}</span>}
      English names
    </button>
  )
}
