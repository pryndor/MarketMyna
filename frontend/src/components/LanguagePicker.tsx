import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'
import gb from 'flag-icons/flags/4x3/gb.svg'
import es from 'flag-icons/flags/4x3/es.svg'
import br from 'flag-icons/flags/4x3/br.svg'
import ru from 'flag-icons/flags/4x3/ru.svg'
import cn from 'flag-icons/flags/4x3/cn.svg'
import sa from 'flag-icons/flags/4x3/sa.svg'
import ir from 'flag-icons/flags/4x3/ir.svg'
import { Icon } from './ui'
import { cx } from '../lib/cx'
import { setLanguage } from '../i18n'
import { LANGUAGES, type Language } from '../i18n/languages'

// One flag per language, for the country most of its readers here come from.
const FLAGS: Record<Language, string> = { en: gb, es, pt: br, ru, zh: cn, ar: sa, fa: ir }

function Flag({ code }: { code: Language }) {
  return <img src={FLAGS[code]} alt="" width={20} height={15} className="h-[15px] w-5 shrink-0 rounded-[2px] object-cover shadow-sm ring-1 ring-black/10" />
}

/** Flag and language name, opening a list of every language with its flag, each in its own script.
 *  On phones (and always when `compact`) the button shows just the flag and the language code.
 *  The list opens up when the button sits low on the screen (sidebar footer), down otherwise. */
export default function LanguagePicker({ className, compact = false }: { className?: string; compact?: boolean }) {
  const { t, i18n } = useTranslation()
  const current = LANGUAGES.find((l) => l.code === i18n.resolvedLanguage) ?? LANGUAGES[0]
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const [place, setPlace] = useState({ up: false, end: false })
  const root = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const list = useRef<HTMLUListElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (e: PointerEvent) => !root.current?.contains(e.target as Node) && setOpen(false)
    document.addEventListener('pointerdown', close)
    list.current?.focus()
    return () => document.removeEventListener('pointerdown', close)
  }, [open])

  const show = () => {
    const r = button.current!.getBoundingClientRect()
    setPlace({ up: r.bottom > window.innerHeight * 0.6, end: r.left + r.width / 2 > window.innerWidth / 2 })
    setActive(Math.max(0, LANGUAGES.indexOf(current)))
    setOpen(true)
  }
  const choose = (code: Language) => {
    setLanguage(code)
    setOpen(false)
    button.current?.focus()
  }
  const onListKey = (e: KeyboardEvent) => {
    if (e.key === 'ArrowDown') setActive((i) => (i + 1) % LANGUAGES.length)
    else if (e.key === 'ArrowUp') setActive((i) => (i - 1 + LANGUAGES.length) % LANGUAGES.length)
    else if (e.key === 'Home') setActive(0)
    else if (e.key === 'End') setActive(LANGUAGES.length - 1)
    else if (e.key === 'Enter' || e.key === ' ') choose(LANGUAGES[active].code)
    else if (e.key === 'Escape' || e.key === 'Tab') {
      setOpen(false)
      if (e.key === 'Escape') button.current?.focus()
      return
    } else return
    e.preventDefault()
  }

  return (
    <div ref={root} className={cx('relative', className)}>
      <button
        ref={button}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`${t('language')}: ${current.name}`}
        title={t('language')}
        onClick={() => (open ? setOpen(false) : show())}
        onKeyDown={(e) => e.key === 'ArrowDown' && !open && (e.preventDefault(), show())}
        className={cx(
          'flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-muted hover:bg-raised hover:text-fg',
          !compact && 'sm:min-w-[9.5rem]',
        )}
      >
        <Flag code={current.code} />
        <span className={cx('text-xs font-semibold uppercase', !compact && 'sm:hidden')}>{current.code}</span>
        {!compact && (
          <span lang={current.tag} className="hidden flex-1 text-start sm:inline">
            {current.name}
          </span>
        )}
        <Icon name="chevron" className={cx('h-3.5 w-3.5 shrink-0 opacity-70 transition-transform', open ? '-rotate-90' : 'rotate-90', !compact && 'hidden sm:block')} />
      </button>
      {open && (
        <ul
          ref={list}
          role="listbox"
          tabIndex={-1}
          aria-label={t('language')}
          aria-activedescendant={`lang-${LANGUAGES[active].code}`}
          onKeyDown={onListKey}
          className={cx(
            'absolute z-50 w-52 overflow-hidden rounded-xl border border-line-strong bg-surface p-1 text-sm text-fg shadow-card outline-none',
            place.up ? 'bottom-full mb-1.5' : 'top-full mt-1.5',
            place.end ? 'right-0' : 'left-0',
          )}
        >
          {LANGUAGES.map((l, i) => (
            <li
              key={l.code}
              id={`lang-${l.code}`}
              role="option"
              aria-selected={l.code === current.code}
              onPointerEnter={() => setActive(i)}
              onClick={() => choose(l.code)}
              className={cx('flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2', i === active && 'bg-raised')}
            >
              <Flag code={l.code} />
              <span lang={l.tag} className="flex-1">
                <bdi>{l.name}</bdi>
              </span>
              {l.code === current.code && <Icon name="check" className="h-4 w-4 text-accent-fg" />}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
