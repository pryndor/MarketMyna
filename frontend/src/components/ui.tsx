import { createContext, useCallback, useContext, useEffect, useId, useState } from 'react'
import type {
  ButtonHTMLAttributes,
  ComponentProps,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from 'react'
import { cx } from '../lib/cx'
import type { Option } from '../lib/options'
import { tileHelp } from '../lib/tileHelp'


/* ------------------------------------------------------------------ icons */

const ICON_PATHS = {
  analyze: 'M3 17l6-6 4 4 8-8M15 7h6v6',
  candles: 'M7 4v3M7 17v3M5 7h4v10H5zM17 3v5M17 15v4M15 8h4v7h-4z',
  portfolio: 'M4 7h16v12H4zM9 7V5h6v2',
  clock: 'M12 7v5l3 2M12 21a9 9 0 110-18 9 9 0 010 18z',
  chat: 'M4 5h16v11H8l-4 4z',
  settings:
    'M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z',
  plus: 'M12 5v14M5 12h14',
  check: 'M5 12l5 5L20 7',
  x: 'M6 6l12 12M18 6L6 18',
  play: 'M7 5l12 7-12 7z',
  stop: 'M7 7h10v10H7z',
  send: 'M4 12l16-8-6 16-2-6z',
  refresh: 'M20 11a8 8 0 10-2.3 5.7M20 5v6h-6',
  bell: 'M6 16V11a6 6 0 1112 0v5l2 2H4zM10 20h4',
  cpu: 'M7 7h10v10H7zM9 3v4M15 3v4M9 17v4M15 17v4M3 9h4M3 15h4M17 9h4M17 15h4',
  lock: 'M6 11h12v9H6zM8 11V8a4 4 0 118 0v3',
  alert: 'M12 8v5M12 16.5v.5M10.3 3.9L2.4 18a2 2 0 001.7 3h15.8a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z',
  chevron: 'M9 6l6 6-6 6',
  trash: 'M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13',
  download: 'M12 3v12M7 10l5 5 5-5M5 21h14',
  search: 'M11 18a7 7 0 110-14 7 7 0 010 14zM20 20l-4-4',
  globe: 'M12 21a9 9 0 100-18 9 9 0 000 18zM3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.7-3.8-9s1.3-6.3 3.8-9z',
  sort: 'M8 9l4-4 4 4M8 15l4 4 4-4',
  filter: 'M4 5h16l-6 8v5l-4 2v-7z',
  sun: 'M12 16a4 4 0 100-8 4 4 0 000 8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4',
  moon: 'M20 14.5A8 8 0 019.5 4a8 8 0 1010.5 10.5z',
  star: 'M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z',
  pencil: 'M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4',
  compare: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  home: 'M3 11l9-7 9 7M5 10v10h5v-6h4v6h5V10',
  grid: 'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z',
  logout: 'M14 4h5v16h-5M10 8l-4 4 4 4M6 12h10',
  user: 'M12 12a4 4 0 100-8 4 4 0 000 8zM4 21a8 8 0 0116 0',
  shield: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z',
  radar: 'M12 21a9 9 0 110-18 9 9 0 010 18zM12 16a4 4 0 110-8M12 12l6-6',
} as const

export type IconName = keyof typeof ICON_PATHS

export function Icon({ name, className = 'h-4 w-4' }: { name: IconName; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cx('shrink-0', className)}
      aria-hidden
    >
      <path d={ICON_PATHS[name]} />
    </svg>
  )
}

export function Spinner({ className = 'h-4 w-4' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={cx('animate-spin', className)} aria-hidden>
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 00-9-9" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

/* ----------------------------------------------------------------- layout */

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string
  description?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

/** `section` names the card in the page's jump index (see SectionIndex);
 * it needs an `id` to scroll to. */
/** The card's help topic (lib/tileHelp.ts), read by CardHeader for its ⓘ button. */
const CardTopic = createContext<string | undefined>(undefined)

export function Card({
  children,
  className,
  id,
  section,
  help,
}: {
  children: ReactNode
  className?: string
  id?: string
  section?: string
  /** Help topic when it differs from `section` (or the card has none). */
  help?: string
}) {
  return (
    <section
      id={id}
      data-section={section}
      className={cx('rounded-xl border border-line bg-surface shadow-card', id && 'scroll-mt-6', className)}
    >
      <CardTopic.Provider value={help ?? section}>{children}</CardTopic.Provider>
    </section>
  )
}

/** The ⓘ button: opens a short explanation of the card (see InfoPanel). */
export function InfoButton({
  topic,
  open,
  onToggle,
  panelId,
}: {
  topic: string
  open: boolean
  onToggle: () => void
  panelId: string
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      aria-controls={panelId}
      aria-label={`What is ${topic}?`}
      title={`What is ${topic}?`}
      className={cx(
        'grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full border font-serif text-[11px] font-semibold italic leading-none transition-colors',
        open ? 'border-accent bg-accent text-white' : 'border-line-strong text-muted hover:border-accent hover:text-accent-fg',
      )}
    >
      i
    </button>
  )
}

/** The explanation the ⓘ button opens, in the card's flow (so it never runs
 * off a phone screen). Esc closes it. */
export function InfoPanel({ topic, open, onClose, id }: { topic: string; open: boolean; onClose: () => void; id: string }) {
  const help = tileHelp(topic)
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!help || !open) return null
  return (
    <div id={id} role="region" aria-label={`About ${topic}`} className="mt-3 rounded-lg border border-line bg-canvas p-3 text-xs leading-relaxed">
      <p className="text-fg">{help.about}</p>
      <p className="mt-1.5 text-muted">
        <span className="font-medium text-fg">How to read it: </span>
        {help.read}
      </p>
      {help.note && <p className="mt-1.5 text-warn">{help.note}</p>}
    </div>
  )
}

/** Open / closed state and ids for one card's help. */
export function useCardHelp(topic: string | undefined) {
  const [open, setOpen] = useState(false)
  const panelId = useId()
  const has = !!tileHelp(topic)
  const toggle = useCallback(() => setOpen((o) => !o), [])
  const close = useCallback(() => setOpen(false), [])
  return { has, open, toggle, close, panelId }
}

export function CardHeader({
  title,
  description,
  actions,
  icon,
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  icon?: IconName
}) {
  const topic = useContext(CardTopic)
  const help = useCardHelp(topic)
  return (
    <header className="border-b border-line px-5 py-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          {icon && (
            <span className="mt-0.5 rounded-md bg-raised p-1.5 text-muted">
              <Icon name={icon} />
            </span>
          )}
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold">{title}</h2>
              {help.has && topic && (
                <InfoButton topic={topic} open={help.open} onToggle={help.toggle} panelId={help.panelId} />
              )}
            </div>
            {description && <p className="mt-0.5 text-xs text-muted">{description}</p>}
          </div>
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      {topic && <InfoPanel topic={topic} open={help.open} onClose={help.close} id={help.panelId} />}
    </header>
  )
}

export function CardBody({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx('p-5', className)}>{children}</div>
}

/* ---------------------------------------------------------------- buttons */

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'custom'

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-cta text-on-cta hover:bg-cta-hover',
  secondary: 'border border-line-strong bg-raised text-fg hover:border-faint',
  ghost: 'text-muted hover:bg-raised hover:text-fg',
  danger: 'border border-down/40 bg-down-soft text-down hover:bg-down/20',
  /** Colours come from className. */
  custom: '',
}

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  icon,
  children,
  className,
  disabled,
  type = 'button',
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant
  size?: 'sm' | 'md'
  loading?: boolean
  icon?: IconName
}) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      className={cx(
        'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg font-medium transition-colors',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
        'disabled:cursor-not-allowed disabled:opacity-50',
        size === 'sm' ? 'h-8 px-3 text-xs' : 'h-9 px-4 text-sm',
        BUTTON_VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {loading ? <Spinner /> : icon ? <Icon name={icon} /> : null}
      {children}
    </button>
  )
}

/* ----------------------------------------------------------------- inputs */

const CONTROL =
  'rounded-lg border border-line bg-canvas px-3 text-sm text-fg placeholder:text-faint ' +
  'focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent-soft disabled:opacity-50'

/** Full width unless the caller passes its own width (w-36, sm:w-48, ...) -
 * both utilities in one class list would leave the winner to CSS order. */
function controlWidth(className?: string) {
  return /(^|\s)(\w+:)?w-/.test(className ?? '') ? null : 'w-full'
}

export function Input({ className, ...rest }: ComponentProps<'input'>) {
  return <input className={cx(CONTROL, controlWidth(className), 'h-9', className)} {...rest} />
}

/** A key / token field. Not type="password": Chrome treats two password
 * fields next to each other as "new + confirm password", fills them with a
 * saved or generated password and then copies every edit of one into the
 * other. A text field masked with CSS gets none of that; the opt-out hints
 * keep 1Password, LastPass and Bitwarden away too. */
export function SecretInput({ className, ...rest }: ComponentProps<'input'>) {
  return (
    <Input
      type="text"
      autoComplete="off"
      autoCorrect="off"
      autoCapitalize="off"
      spellCheck={false}
      data-1p-ignore=""
      data-lpignore="true"
      data-bwignore="true"
      data-form-type="other"
      className={cx('[-webkit-text-security:disc]', className)}
      {...rest}
    />
  )
}

export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cx(CONTROL, controlWidth(className), 'py-2 font-mono text-xs', className)} {...rest} />
}

export function Select({
  options,
  className,
  ...rest
}: SelectHTMLAttributes<HTMLSelectElement> & { options: Option[] }) {
  return (
    <select className={cx(CONTROL, controlWidth(className), 'h-9 pe-8', className)} {...rest}>
      {options.map((o) => (
        <option key={o.value} value={o.value} disabled={o.disabled}>
          {o.label}
        </option>
      ))}
    </select>
  )
}

export function Field({
  label,
  hint,
  children,
  className,
}: {
  label: ReactNode
  hint?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <label className={cx('block', className)}>
      <span className="mb-1.5 block text-xs font-medium text-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-faint">{hint}</span>}
    </label>
  )
}

export function Switch({
  checked,
  onChange,
  label,
  description,
}: {
  checked: boolean
  onChange: (next: boolean) => void
  label: ReactNode
  description?: ReactNode
}) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-4">
      <span>
        <span className="block text-sm font-medium">{label}</span>
        {description && <span className="mt-0.5 block text-xs text-muted">{description}</span>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cx(
          'relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors',
          checked ? 'bg-accent' : 'bg-line-strong',
        )}
      >
        <span
          className={cx(
            'absolute top-0.5 start-0 h-4 w-4 rounded-full bg-white transition-transform',
            checked ? 'translate-x-4.5' : 'translate-x-0.5',
          )}
        />
      </button>
    </label>
  )
}

/** Pill-style single choice. Shows the active option's hint underneath
 * so users see exactly what a choice does without a tooltip hunt. */
export function Segmented({
  options,
  value,
  onChange,
  size = 'md',
  showHint = false,
}: {
  options: Option[]
  value: string
  onChange: (value: string) => void
  size?: 'sm' | 'md'
  showHint?: boolean
}) {
  const active = options.find((o) => o.value === value)
  return (
    <div>
      <div className="inline-flex flex-wrap gap-1 rounded-lg border border-line bg-canvas p-1">
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            title={o.hint}
            aria-pressed={o.value === value}
            disabled={o.disabled}
            onClick={() => onChange(o.value)}
            className={cx(
              'inline-flex items-center gap-1.5 rounded-md font-medium transition-colors',
              size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3 py-1.5 text-sm',
              // The current option keeps the arrow; the others show the hand.
              o.disabled
                ? 'cursor-not-allowed text-faint'
                : o.value === value
                  ? 'cursor-default bg-raised text-fg shadow-sm ring-1 ring-line-strong'
                  : 'cursor-pointer text-muted hover:text-fg',
            )}
          >
            {o.label}
            {o.badge && (
              <span className="rounded bg-accent-soft px-1.5 py-0.5 text-[10px] font-semibold leading-none text-accent-fg">
                {o.badge}
              </span>
            )}
          </button>
        ))}
      </div>
      {showHint && active?.hint && <p className="mt-1.5 text-xs text-faint">{active.hint}</p>}
    </div>
  )
}

/* --------------------------------------------------------------- feedback */

type Tone = 'neutral' | 'up' | 'down' | 'warn' | 'accent'

const TONES: Record<Tone, string> = {
  neutral: 'bg-raised text-muted ring-line-strong',
  up: 'bg-up-soft text-up ring-up/30',
  down: 'bg-down-soft text-down ring-down/30',
  warn: 'bg-warn-soft text-warn ring-warn/30',
  accent: 'bg-accent-soft text-accent-fg ring-accent/30',
}

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ring-1 ring-inset',
        TONES[tone],
      )}
    >
      {children}
    </span>
  )
}

const SIGNAL_TONES: Record<string, Tone> = {
  buy: 'up',
  strong_buy: 'up',
  bullish: 'up',
  low: 'up',
  hold: 'warn',
  neutral: 'warn',
  medium: 'warn',
  sell: 'down',
  strong_sell: 'down',
  bearish: 'down',
  high: 'down',
  low_risk: 'up',
  medium_risk: 'warn',
  high_risk: 'down',
  positive: 'up',
  negative: 'down',
}

export function SignalBadge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-faint">—</span>
  return <Badge tone={SIGNAL_TONES[value.toLowerCase()] ?? 'neutral'}>{value.replace(/_/g, ' ')}</Badge>
}

export function StatusDot({ tone }: { tone: Tone }) {
  const color = { neutral: 'bg-faint', up: 'bg-up', down: 'bg-down', warn: 'bg-warn', accent: 'bg-accent' }[tone]
  return <span className={cx('inline-block h-2 w-2 shrink-0 rounded-full', color)} />
}

export function Alert({
  tone = 'down',
  title,
  children,
  onDismiss,
}: {
  tone?: 'down' | 'warn' | 'accent'
  title?: ReactNode
  children?: ReactNode
  onDismiss?: () => void
}) {
  return (
    <div className={cx('flex items-start gap-3 rounded-lg px-4 py-3 text-sm ring-1 ring-inset', TONES[tone])}>
      <Icon name="alert" className="mt-0.5 h-4 w-4" />
      <div className="min-w-0 flex-1 normal-case">
        {title && <div className="font-semibold">{title}</div>}
        {children && <div className="break-words text-fg/80">{children}</div>}
      </div>
      {onDismiss && (
        <button type="button" onClick={onDismiss} className="opacity-70 hover:opacity-100" aria-label="Dismiss">
          <Icon name="x" />
        </button>
      )}
    </div>
  )
}

export function Stat({
  label,
  value,
  sub,
  subClassName,
}: {
  label: ReactNode
  value: ReactNode
  sub?: ReactNode
  subClassName?: string
}) {
  return (
    <div className="min-w-0">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className="tabular mt-1 truncate text-lg font-semibold">{value}</div>
      {sub != null && <div className={cx('tabular mt-0.5 text-xs', subClassName ?? 'text-muted')}>{sub}</div>}
    </div>
  )
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon: IconName
  title: ReactNode
  description?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      <span className="rounded-full bg-raised p-3 text-muted">
        <Icon name={icon} className="h-5 w-5" />
      </span>
      <h3 className="mt-3 text-sm font-semibold">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-xs text-muted">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

/** A list or table that scrolls inside its own box once it outgrows
 * `maxHeight` (default about ten rows), so the card around it keeps its
 * height; table headers stay visible while scrolling. */
export function ScrollBox({ children, className, maxHeight = '27rem' }: { children: ReactNode; className?: string; maxHeight?: string }) {
  return (
    <div
      data-scrollbox
      style={{ maxHeight }}
      className={cx('overflow-y-auto overscroll-contain [&_thead]:sticky [&_thead]:top-0 [&_thead]:z-[1] [&_thead]:bg-surface', className)}
    >
      {children}
    </div>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx('animate-pulse rounded-md bg-raised', className)} />
}

/** Token-list input: type, press Enter or comma to add, click × to drop. */
export function TagInput({
  values,
  onChange,
  placeholder,
}: {
  values: string[]
  onChange: (next: string[]) => void
  placeholder?: string
}) {
  function commit(raw: string) {
    const parts = raw
      .split(/[,\s]+/)
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean)
    const next = [...values]
    for (const p of parts) if (!next.includes(p)) next.push(p)
    onChange(next)
  }

  return (
    <div className="flex min-h-9 flex-wrap items-center gap-1.5 rounded-lg border border-line bg-canvas px-2 py-1.5 focus-within:border-accent focus-within:ring-2 focus-within:ring-accent-soft">
      {values.map((v) => (
        <span key={v} className="inline-flex items-center gap-1 rounded-md bg-raised px-2 py-0.5 font-mono text-xs">
          {v}
          <button
            type="button"
            onClick={() => onChange(values.filter((x) => x !== v))}
            className="text-faint hover:text-down"
            aria-label={`Remove ${v}`}
          >
            <Icon name="x" className="h-3 w-3" />
          </button>
        </span>
      ))}
      <input
        className="min-w-24 flex-1 bg-transparent px-1 text-sm outline-none placeholder:text-faint"
        placeholder={values.length ? '' : placeholder}
        onKeyDown={(e) => {
          const input = e.currentTarget
          if ((e.key === 'Enter' || e.key === ',') && input.value.trim()) {
            e.preventDefault()
            commit(input.value)
            input.value = ''
          } else if (e.key === 'Backspace' && !input.value && values.length) {
            onChange(values.slice(0, -1))
          }
        }}
        onBlur={(e) => {
          if (e.currentTarget.value.trim()) {
            commit(e.currentTarget.value)
            e.currentTarget.value = ''
          }
        }}
      />
    </div>
  )
}
