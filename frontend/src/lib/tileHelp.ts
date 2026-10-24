/** Plain-language help for each card on the Analyze page, shown by the ⓘ
 * button in the card's header (components/ui.tsx InfoButton). Keyed by the
 * card's `section` name, or its title when it has none.
 *
 * Each entry: what the card is, how to read it, and a caution when one
 * matters. Keep them short: a sentence or two each, no jargon left
 * unexplained. */
interface TileHelp {
  about: string
  read: string
  note?: string
}

const TILE_HELP: Record<string, TileHelp> = {
  'Quote & chart': {
    about: "The latest price, today's move and the price history for the period you pick.",
    read: 'Line shows the closing price; Candles show each day’s open, high, low and close. "Period change" is the move over the chosen period. For Indian shares you can switch between the NSE and BSE listing.',
    note: 'Prices can be a few minutes delayed.',
  },
  'Trade setup': {
    about: 'Where the price sits for the next days to weeks, computed from daily prices (no AI).',
    read: 'The bar shows today’s price inside its normal range (the 20-day Bollinger band) and the expected 1-week range. ATR is the average daily move; RSI and volume show momentum and interest.',
    note: 'Ranges are estimates from past prices, not buy or sell levels.',
  },
  'AI analysis': {
    about: 'An AI explanation of what the figures on this page show, with the outlook they point to.',
    read: 'The badge is the outlook: bullish, neutral or bearish. The paragraph describes the data (trend, valuation, risks, upcoming events) and the questions worth checking next.',
    note: 'A direction from the data, not a recommendation to buy, sell or hold. AI can be wrong.',
  },
  'Agent opinions': {
    about: 'What each step of the AI analysis reported, one by one.',
    read: 'Open a step to read its full note. Technical reads the chart, Risk the volatility, News the headlines, Sentiment the online chatter, Fundamentals the filings; at Full depth a bull and a bear argue, and a risk team and a portfolio manager review the plan.',
  },
  'Agent pipeline': {
    about: 'The AI analysis steps, shown live while Analyze runs.',
    read: 'Each step turns green when done. A skipped step (e.g. a data source was down) does not stop the others; the final decision uses whatever finished.',
  },
  'Valuation meter': {
    about: "How expensive today's price is compared with similar companies in the same sector.",
    read: 'It compares P/E (price to earnings), P/B (price to book value) and P/S (price to sales) with the sector median. Below the median is cheaper than peers, above is dearer.',
    note: 'Cheaper than peers can be deserved (slower growth, more debt). It is a comparison, not a verdict.',
  },
  'DCF & Graham': {
    about: "Two classic ways to estimate a company's value from its cash flows and earnings.",
    read: 'DCF adds up future cash flows (under the growth and discount rates you set) in today’s money. It also shows what growth today’s price already assumes. Graham’s formula is a quick check from earnings and growth.',
    note: 'Small changes in the assumptions move the result a lot.',
  },
  'Investor checklists': {
    about: 'The company’s filings run through the published rules of five investing styles: Graham, Buffett-style quality, Lynch, Greenblatt and a Howard Marks-style risk check.',
    read: 'Each rule passes or fails with its number, so you can see which styles the company fits.',
    note: 'These are public rules applied to published figures. They do not say what these investors would do.',
  },
  'Social sentiment': {
    about: 'What people are saying about the stock on Reddit, StockTwits, ValuePickr and Hacker News over the last 7 days.',
    read: 'The score runs from -100 (very negative) to +100 (very positive), from words and tags in the posts. Look at the themes and the top posts for why. Buzz compares the last 24 hours with a normal day.',
    note: 'Chatter is noisy, easy to manipulate and often just follows the price. Long-term investors should use it mainly to spot red flags (fraud, lawsuits, dilution).',
  },
  'My thesis': {
    about: 'Your own written reason for owning or watching this stock.',
    read: 'Write what has to go right, what would prove you wrong and the price that breaks it. MarketMyna checks it against live prices and results, and reminds you to review it every quarter.',
  },
  Earnings: {
    about: 'The next results date, what to watch in this kind of company’s results, and how past results compared with forecasts.',
    read: '"Beat" or "missed" compares reported earnings per share (EPS) with the analysts’ estimate. Stock move shows how the price reacted.',
    note: 'Past reactions do not predict the next one.',
  },
  'ETF holdings': {
    about: 'What this exchange-traded fund owns.',
    read: 'The biggest holdings and their weights show where your money actually goes.',
  },
  Estimates: {
    about: 'Analysts’ forecasts for revenue and earnings, and how those forecasts have changed.',
    read: 'Rising estimates mean analysts expect more than before; a record of beats means the company has tended to report above forecasts.',
  },
  Dividends: {
    about: 'The company’s dividend payments over the years.',
    read: 'Yield is the yearly dividend as a % of today’s price. Growth shows whether the payout has been rising.',
    note: 'A very high yield can mean the price has fallen because the dividend is at risk.',
  },
  Peers: {
    about: 'Companies in the same industry and of similar size.',
    read: 'Compare growth, margins and valuation side by side; one click opens a full comparison.',
  },
  'Mutual funds holding this': {
    about: 'Indian mutual fund schemes that hold this stock, from their monthly portfolio disclosures.',
    read: 'More schemes and a bigger total amount mean more professional money in the stock.',
    note: 'Disclosures are monthly, so holdings can be weeks old.',
  },
  'Ethical screen': {
    about: 'An ethical check: whether the business and the balance sheet meet common ethical-investing rules.',
    read: 'The business must not be on the excluded list (e.g. interest-based banking, alcohol, gambling). Debt, cash and interest income must stay under the limits shown (the standard index limit, with a stricter line where standards differ).',
    note: 'A screening aid, not a final ruling. Standards differ at the edges.',
  },
  'Financial statements': {
    about: 'The income statement, balance sheet and cash flow, yearly or quarterly.',
    read: 'Each statement gets a verdict with the findings behind it: growth, margins, debt, and whether profit turns into cash.',
  },
  Fundamentals: {
    about: 'A quick score of the business from its key ratios.',
    read: 'The score out of 100 combines valuation, profitability (e.g. return on equity), financial health (debt) and growth. 60+ is strong, under 40 weak.',
  },
  Technical: {
    about: 'Chart indicators computed from daily prices.',
    read: 'Each row explains its indicator; "neutral" means it gives no clear signal. The moving-average chips show how far the price is above or below its 20-, 50-, 100- and 200-day averages.',
    note: 'Indicators describe the past and often disagree.',
  },
  Risk: {
    about: 'How much the price swings and how far it has fallen before.',
    read: 'Volatility is the typical yearly swing; max drawdown the deepest fall from a high in the last year. Beta of 1 moves with the market, above 1 moves more. The forecast shows whether swings are expected to grow or calm.',
  },
  'Analysts & events': {
    about: 'What brokers think and the dates coming up.',
    read: 'Broker consensus and average target summarise third-party analysts. Next earnings and ex-dividend dates often move the price.',
    note: 'Broker views are third-party opinions, not MarketMyna’s.',
  },
  'Company profile': {
    about: 'What the company does, its sector and size.',
    read: 'A summary of the business: what it sells, where, and how big it is.',
  },
  'Latest news': {
    about: 'Recent headlines about the company from news sites.',
    read: 'Click a headline to read the full story at its source. The time shows how old it is.',
  },
}

export function tileHelp(key: string | undefined): TileHelp | undefined {
  return key ? TILE_HELP[key] : undefined
}
