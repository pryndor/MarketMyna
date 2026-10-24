/** Which market a typed symbol belongs to, so the market picker follows the
 * symbol instead of the user switching it by hand.
 *
 * - A Yahoo-style suffix decides first: RELIANCE.NS / .BO -> India,
 *   BTC-USD -> Crypto, 0700.HK -> Hong Kong, 600519.SS / .SZ -> China A.
 * - Otherwise an exact symbol match in the listings decides (leading zeros
 *   ignored, so 0700 finds 00700). When the symbol is listed in more than
 *   one market (INFY in India and as a US ADR), the market already picked
 *   wins if it is one of them, else the best-ranked listing.
 * - Then the full name of one listing ("360 ONE Balanced Hybrid Fund -
 *   Direct Plan - Growth Option" -> its scheme code in India), so a pasted
 *   fund or company name opens the right market.
 * - A partial name or symbol decides nothing: the suggestions are there to
 *   pick from. */

interface SymbolRow {
  symbol: string
  market: string
  name?: string | null
}

const SUFFIXES: Array<[RegExp, string]> = [
  [/\.(NS|BO)$/i, 'india'],
  [/\.HK$/i, 'hong_kong'],
  [/\.(SS|SZ)$/i, 'china_a'],
  [/-USD$/i, 'crypto'],
]

/** The symbol as the listing knows it (no exchange suffix; crypto keeps -USD) and its market. */
export function marketFromSuffix(text: string): SymbolRow | null {
  const s = text.trim().toUpperCase()
  for (const [re, market] of SUFFIXES) {
    if (re.test(s)) return { symbol: market === 'crypto' ? s : s.replace(re, ''), market }
  }
  return null
}

function same(a: string, b: string): boolean {
  const x = a.trim().toUpperCase()
  const y = b.trim().toUpperCase()
  if (x === y) return true
  // Numeric codes: 0700 and 00700 are the same Hong Kong listing.
  return /^\d+$/.test(x) && /^\d+$/.test(y) && Number(x) === Number(y)
}

/** The listing an exact symbol match points at, or undefined. `rows` are in search-rank order. */
export function exactMatch<T extends SymbolRow>(text: string, rows: T[], current?: string): T | undefined {
  const hits = rows.filter((r) => same(r.symbol, text))
  if (!hits.length) return undefined
  return hits.find((r) => r.market === current) ?? hits[0]
}

const squash = (text: string) => text.trim().replace(/\s+/g, ' ').toUpperCase()

/** The one listing whose full name is what was typed, or undefined. */
function nameMatch<T extends SymbolRow>(text: string, rows: T[]): T | undefined {
  const typed = squash(text)
  const hits = rows.filter((r) => r.name && squash(r.name) === typed)
  return hits.length === 1 ? hits[0] : undefined
}

/** The symbol and market to open for what was typed: suffix, then exact match, else the current market. */
export async function resolveSymbol(
  text: string,
  current: string,
  search: (q: string) => Promise<SymbolRow[]>,
): Promise<SymbolRow> {
  const typed = text.trim().toUpperCase()
  const suffixed = marketFromSuffix(typed)
  if (suffixed) return suffixed
  try {
    const rows = await search(typed)
    const hit = exactMatch(typed, rows, current) ?? nameMatch(typed, rows)
    if (hit) return { symbol: hit.symbol, market: hit.market }
  } catch {
    // Listing search down: open what was typed in the picked market.
  }
  return { symbol: typed, market: current }
}
