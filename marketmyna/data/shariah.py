"""Shariah (halal) screening for listings.

Two layers:

1. ``screen_row`` - a fast, per-listing check run on every row when the
   listing cache loads. Stocks get a *business-activity* screen (what the
   company does) from its sector / industry / name; funds get a *mandate*
   screen (is it a Shariah-screened fund at all). This is what the Markets
   "Shariah" filter uses.
2. ``marketmyna/services/shariah.py`` - the full per-stock profile (business
   screen + balance-sheet ratios + purification), computed on demand.

Statuses:
    halal     - passes the screen (for stocks: business activity only -
                the financial ratios are checked on the stock page)
    doubtful  - mixed or unclear activity (hotels, media, REITs, ...)
    haram     - prohibited activity (interest-based finance, alcohol,
                tobacco, gambling, pork, weapons, adult content, ...) or an
                interest-bearing / conventional fund
    unknown   - not enough information to say

This is a screening aid, not a fatwa - scholars and index providers
(AAOIFI, S&P / Dow Jones Islamic, MSCI, FTSE) differ at the edges.
"""

from __future__ import annotations

import re
from typing import Optional

HALAL = "halal"
DOUBTFUL = "doubtful"
HARAM = "haram"
UNKNOWN = "unknown"

STATUSES = (HALAL, DOUBTFUL, HARAM, UNKNOWN)

# ---------------------------------------------------------------- funds

# Known Shariah-screened funds/ETFs whose names don't say so.
SHARIAH_TICKERS = {
    # SP Funds (all Shariah-screened by S&P / Dow Jones)
    "SPUS", "SPSK", "SPRE", "SPTE", "SPWO",
    # Wahed, Manzil
    "HLAL", "UMMA", "MNZL", "KWIN",
    # Amana, Iman, Azzad (US mutual funds)
    "AMAGX", "AMANX", "AMAPX", "AMIGX", "AMINX", "AMIDX", "IMANX", "ADJEX", "WISEX",
    # India
    "SHARIABEES",
}

_SHARIAH_NAME = re.compile(
    r"shari'?a[h]?|islamic|\bhalal\b|\bsukuk\b|\bamana\b|\bwahed\b|\bmanzil\b|\biman fund\b|\bazzad\b|"
    r"\bsp funds\b|\bfalah\b",
    re.I,
)
# In India every "Ethical" fund (Tata, Taurus, Quantum, The Wealth Company)
# benchmarks a Shariah index and follows Shariah screening. Elsewhere
# "ethical" usually means ESG, which still allows banks and interest.
_INDIA_ETHICAL = re.compile(r"\bethical\b", re.I)

_INTEREST_FUND = re.compile(
    r"\b(liquid|money market|overnight|gilt|g-?sec|treasury|t-?bill|bonds?|debt|income|credit|"
    r"corporate bond|banking (and|&) psu|floater|floating rate|duration|fixed (maturity|income)|"
    r"fmp|arbitrage|sdl|bharat bond|aggregate|municipal|muni|high yield|mortgage)\b",
    re.I,
)


def _fund(row: dict) -> tuple[str, str]:
    name = row.get("name") or ""
    symbol = (row.get("symbol") or "").upper()
    if symbol in SHARIAH_TICKERS or _SHARIAH_NAME.search(name):
        if re.search(r"\bsukuk\b", name, re.I) or symbol in ("SPSK", "KWIN"):
            return HALAL, "Ethical bond fund - asset-backed, no interest"
        return HALAL, "Ethically screened fund - excludes interest-based finance and excluded businesses"
    if row.get("market") == "india" and _INDIA_ETHICAL.search(name):
        return HALAL, "Indian 'Ethical' fund - screened against an ethical index"

    category = row.get("category") or ""
    text = f"{name} {row.get('fund_group') or ''} {row.get('sector') or ''}"
    if category in ("Debt", "Bonds") or _INTEREST_FUND.search(text):
        return HARAM, "Holds interest-bearing debt"
    if category == "Leveraged & Inverse":
        return HARAM, "Uses leverage / derivatives"
    if category == "Hybrid" or re.search(r"\bhybrid|balanced|asset allocat|multi asset|equity savings\b", text, re.I):
        return HARAM, "Hybrid fund - part of the money sits in interest-bearing debt"
    if re.search(r"\b(gold|silver)\b", text, re.I) and not re.search(r"miners?|mining|futures|equity|stocks", text, re.I):
        return DOUBTFUL, "Precious-metal fund - passes some screens only if physically backed"
    if category == "Commodities":
        return HARAM, "Commodity futures (speculation and interest on collateral)"
    return HARAM, "No ethical mandate - a conventional fund holds banks, insurers and interest-bearing assets"


# --------------------------------------------------------------- stocks

# Prohibited core business. Checked against the company name and industry.
_HARAM_WORDS = re.compile(
    r"\b(banks?|banking|bancorp\w*|bancshares|bankshares|banc|financ(e|ial|iers?|ing)|fincorp|finserv|fincap|"
    r"finvest|credit|lending|loans?|insurance|insurers?|assurance|reinsurance|nbfc|micro ?finance|"
    r"mortgage|securities|broking|stock ?brokers?|"
    r"brew(ery|eries|ers|ing)|distiller(y|ies|s)?|wines?|winery|wineries|spirits|liquors?|beers?|"
    r"whisk(e)?y|vodka|alcohol\w*|"
    r"tobacco|cigarettes?|cigars?|vap(e|ing)|"
    r"casinos?|gambling|betting|lotter(y|ies)|wagering|bookmakers?|sportsbook|"
    r"pork|swine|hogs?|"
    r"adult entertainment|pornograph\w*|"
    r"firearms?|ammunition|munitions?|ordnance|guns?)\b",
    re.I,
)
# Gambling, alcohol and tobacco companies whose names don't say so.
_HARAM_BRANDS = re.compile(
    r"\b(las vegas sands|sands china|wynn|melco|sjm holdings|galaxy ent\w*|mgm (resorts|china)|caesars|"
    r"draftkings|flutter|churchill downs|penn entertainment|boyd gaming|red rock resorts|monarch casino|"
    r"delta corp|"
    r"itc limited|godfrey phillips|vst industries|altria|philip morris|british american tobacco|turning point brands|"
    r"radico khaitan|tilaknagar|sula vineyards|constellation brands|molson coors|boston beer|brown-forman|"
    r"diageo|anheuser|heineken|pernod|carlsberg|ambev|tsingtao|budweiser|"
    r"hsbc|stanchart|standard chartered|boc hong kong|ping an|china life|prudential|berkshire hathaway|"
    r"allianz|manulife|sun life)\b",
    re.I,
)
_ISLAMIC_FINANCE = re.compile(r"islamic|shari'?a|takaful|sukuk", re.I)
# Chinese names (China A / Hong Kong): banks, brokers, insurers, trusts,
# futures, finance, alcohol, tobacco, lottery / gaming.
_HARAM_ZH = ("银行", "证券", "保险", "信托", "期货", "金融", "租赁", "酒业", "酒厂", "啤酒", "白酒", "葡萄酒", "烟草", "彩票", "博彩",
             "人寿", "中国平安", "茅台", "五粮液", "老窖", "汾酒", "洋河", "古井贡", "酒鬼")
_DOUBTFUL_ZH = ("酒店", "影视", "传媒", "娱乐", "游戏", "军工", "兵装")

# Mixed or unclear activity.
_DOUBTFUL_WORDS = re.compile(
    r"\b(hotels?|resorts?|hospitality|restaurants?|bars?|pubs?|night ?clubs?|cinemas?|multiplex|films?|"
    r"studios?|movies?|music|entertainment|broadcast\w*|media|television|advertising|"
    r"defen[cs]e|military|weapons?|explosives?|aerospace (and|&) defen[cs]e|"
    r"leasing|reit|meat|poultry|beverages?)\b",
    re.I,
)
# Name words that often mean a finance / holding company, but only matter
# when nothing else classifies the business ("XYZ Holdings", "ABC Capital").
_VAGUE_FINANCE_WORDS = re.compile(r"\b(capital|holdings?|invest\w*|trusts?|ventures)\b", re.I)

# Exact US (NASDAQ screener) industries.
_US_HARAM_INDUSTRY = {
    "major banks", "commercial banks", "savings institutions", "banks", "finance: consumer services",
    "finance companies", "investment bankers/brokers/service", "investment managers",
    "finance/investors services", "property-casualty insurers", "life insurance", "specialty insurers",
    "accident &health insurance", "diversified financial services", "blank checks", "tobacco",
    "ordnance and accessories",
}
_US_DOUBTFUL_INDUSTRY = {
    "services-misc. amusement & recreation", "hotels/resorts", "restaurants", "movies/entertainment",
    "broadcasting", "cable & other pay television services", "advertising", "military/government/technical",
    "real estate investment trusts", "trusts except educational religious and charitable",
    "meat/poultry/fish", "rental/leasing companies", "misc corporate leasing services",
    "beverages (production/distribution)", "managed health care", "real estate",
}
_INDIA_SECTOR = {
    "financial services": (HARAM, "Conventional financial services - interest-based"),
    "media entertainment & publication": (DOUBTFUL, "Media & entertainment - content may include prohibited material"),
}


def _stock(row: dict) -> tuple[str, str]:
    name = row.get("name") or ""
    local = row.get("name_local") or ""
    sector = (row.get("sector") or "").strip()
    industry = (row.get("industry") or "").strip()
    text = f"{name} {industry}"

    if _ISLAMIC_FINANCE.search(name):
        return DOUBTFUL, "Ethical-finance company - verify its ethics board certification"
    if _HARAM_BRANDS.search(name):
        return HARAM, "Excluded core business (interest-based finance, gambling, alcohol or tobacco)"
    hit = _HARAM_WORDS.search(text)
    if hit:
        return HARAM, f"Excluded business activity ({hit.group(0).lower()})"
    if sector == "REIT" or re.search(r"\breit\b", name, re.I):
        return DOUBTFUL, "REIT - passes only if its tenants and financing pass the ethical screen"
    if sector == "InvIT":
        return DOUBTFUL, "InvIT - roads and power assets pass the screen, but these trusts usually carry interest-bearing debt"
    zh = next((w for w in _HARAM_ZH if w in local or w in name or w in sector), None)
    if zh:
        return HARAM, f"Excluded business activity ({zh})"

    ind = industry.lower()
    if ind in _US_HARAM_INDUSTRY:
        return HARAM, f"Excluded business activity ({industry})"
    if sector.lower() == "finance" and ind not in _US_DOUBTFUL_INDUSTRY:
        return HARAM, "Conventional financial services - interest-based"
    if ind in _US_DOUBTFUL_INDUSTRY:
        return DOUBTFUL, f"Mixed activity ({industry}) - check revenue sources"
    mapped = _INDIA_SECTOR.get(sector.lower())
    if mapped:
        return mapped

    doubt = _DOUBTFUL_WORDS.search(text)
    if doubt:
        return DOUBTFUL, f"Mixed or unclear activity ({doubt.group(0).lower()}) - check revenue sources"
    zh = next((w for w in _DOUBTFUL_ZH if w in local or w in name or w in sector), None)
    if zh:
        return DOUBTFUL, f"Mixed or unclear activity ({zh}) - check revenue sources"

    category = row.get("category")
    unclassified = not sector and not industry
    vague = _VAGUE_FINANCE_WORDS.search(name)
    if unclassified and vague:
        return DOUBTFUL, f"Name suggests a finance or holding company ({vague.group(0).lower()}) - verify"
    if category == "Financials":
        return DOUBTFUL, "Looks like a financial company - verify"
    if not category or category == "Other":
        return UNKNOWN, "Business not classified - open the stock for a full screen"
    how = "guessed from the company name" if row.get("category_inferred") else "sector"
    return HALAL, f"Business activity passes the ethical screen ({category}, {how}) - financial ratios checked on the stock page"


def screen_row(row: dict) -> tuple[str, str]:
    """(status, reason) for one listing row."""
    type_ = row.get("type")
    # Some exchanges list ETFs alongside stocks.
    if type_ in ("mf", "etf") or re.search(r"\b(etf|bees)\b", row.get("name") or "", re.I):
        return _fund(row)
    if type_ == "crypto":
        return UNKNOWN, "Crypto - not covered by the ethical screen"
    return _stock(row)


def stamp(rows: list[dict]) -> list[dict]:
    """Stamp ``shariah`` + ``shariah_reason`` on every row in place."""
    for row in rows:
        row["shariah"], row["shariah_reason"] = screen_row(row)
    return rows


def business_status(name: str, sector: Optional[str], industry: Optional[str], summary: str = "") -> tuple[str, str, list[str]]:
    """Business screen for the full profile, from Yahoo sector/industry.

    Returns (status, reason, flags) where flags are prohibited activities
    mentioned in the business description."""
    ind = (industry or "").lower()
    yahoo_haram = (
        "banks", "credit services", "capital markets", "mortgage finance", "insurance", "asset management",
        "financial conglomerates", "brewers", "wineries", "distilleries", "tobacco", "gambling",
        "resorts & casinos", "shell companies",
    )
    yahoo_doubtful = (
        "aerospace & defense", "entertainment", "lodging", "restaurants", "broadcasting", "advertising",
        "reit", "leisure", "financial data & stock exchanges", "beverages", "farm products", "packaged foods",
    )

    flags = sorted({m.group(0).lower() for m in _SUMMARY_FLAGS.finditer(summary or "")})

    if _ISLAMIC_FINANCE.search(name):
        return DOUBTFUL, "Ethical-finance company - verify its ethics board certification", flags
    if _HARAM_BRANDS.search(name):
        return HARAM, "Excluded core business (interest-based finance, gambling, alcohol or tobacco)", flags
    hit = next((k for k in yahoo_haram if k in ind), None)
    if hit and not (hit == "beverages" and "non-alcoholic" in ind):
        return HARAM, f"Excluded core business ({industry})", flags
    if (sector or "").lower() == "financial services":
        return HARAM, f"Conventional financial services ({industry or sector})", flags
    doubt = next((k for k in yahoo_doubtful if k in ind), None)
    if doubt and not ("non-alcoholic" in ind and doubt == "beverages"):
        # Packaged food / farm products only matter if pork or alcohol shows up.
        if doubt in ("farm products", "packaged foods", "beverages") and not flags:
            pass
        else:
            return DOUBTFUL, f"Mixed activity ({industry}) - check revenue sources", flags
    if not industry and not sector:
        status, reason = _stock({"name": name, "type": "stock"})
        return status, reason, flags
    if flags:
        return DOUBTFUL, "Business description mentions: " + ", ".join(flags), flags
    return HALAL, f"Core business passes the ethical screen ({industry or sector})", flags


# Prohibited activities worth flagging when they appear in the business
# description (e.g. a hotel chain that sells alcohol, a food group with pork).
_SUMMARY_FLAGS = re.compile(
    r"\b(casinos?|gambling|betting|lotter(y|ies)|wagering|alcoholic|beer|wines?|spirits|liquor|brewing|"
    r"distill\w*|pork|tobacco|cigarettes?|adult entertainment|pornograph\w*|firearms|ammunition|"
    r"weapons|idols?|astrology|conventional (banking|insurance))\b",
    re.I,
)
