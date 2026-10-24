/** MarketMyna mark: the myna perched on a rising market (public/brand/).
 * The favicon and app icons are the same drawing on a white tile. */
export default function Logo({ className = 'h-8 w-8' }: { className?: string }) {
  return <img src="/brand/logo-mark.webp" alt="MarketMyna" width={256} height={256} className={`${className} object-contain`} />
}

