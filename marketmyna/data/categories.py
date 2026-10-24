"""One broad category list shared by every market, so a single filter
("Technology", "Agriculture", "Natural Resources", ...) works whether the
row came from NSE, NASDAQ or anywhere else.

Resolution order for a row:
1. industry keywords (the most specific signal, e.g. US "Farming/Seeds/Milling"),
2. the source's own sector label (NSE industry / US sector),
3. keywords in the company name - the only signal for most small NSE/SME
   stocks, which no free bulk source classifies. Those rows are flagged
   ``category_inferred`` so the UI can say so.
"""

from __future__ import annotations

import re
from typing import Optional

TECHNOLOGY = "Technology"
FINANCIALS = "Financials"
HEALTHCARE = "Healthcare"
CONSUMER = "Consumer"
AUTOMOBILE = "Automobile"
INDUSTRIALS = "Industrials"
ENERGY = "Energy"
NATURAL_RESOURCES = "Natural Resources"
AGRICULTURE = "Agriculture"
MATERIALS = "Chemicals & Materials"
REAL_ESTATE = "Real Estate & Construction"
TRUSTS = "REITs & InvITs"
TELECOM_MEDIA = "Telecom & Media"
UTILITIES = "Utilities"
TEXTILES = "Textiles"
SERVICES = "Services"
OTHER = "Other"

# Extra groups used only for ETFs (and index funds).
BROAD_MARKET = "Broad Market"
BONDS = "Bonds"
COMMODITIES = "Commodities"
LEVERAGED = "Leveraged & Inverse"
INTERNATIONAL = "International"

CATEGORIES = [
    TECHNOLOGY, FINANCIALS, HEALTHCARE, CONSUMER, AUTOMOBILE, INDUSTRIALS, ENERGY,
    NATURAL_RESOURCES, AGRICULTURE, MATERIALS, REAL_ESTATE, TRUSTS, TELECOM_MEDIA,
    UTILITIES, TEXTILES, SERVICES, BROAD_MARKET, BONDS, COMMODITIES, INTERNATIONAL, LEVERAGED, OTHER,
]

_ETF_RULES: list[tuple[str, re.Pattern]] = [
    (LEVERAGED, re.compile(r"\b[23]x\b|ultra ?pro|ultrashort|inverse|\bbull\b|\bbear\b|daily .*(long|short)|leveraged", re.I)),
    (COMMODITIES, re.compile(r"gold|silver|commodit|platinum|copper|oil fund|natural gas|crude", re.I)),
    (BONDS, re.compile(
        r"bond|treasury|gilt|t-bill|income|credit|debt|fixed|municipal|muni|aggregate|"
        r"liquid|money market|floating rate|high yield|duration|mortgage|sdl|g-sec|bharat bond", re.I)),
    (INTERNATIONAL, re.compile(
        r"international|emerging|ex[- ]u\.?s|global|world|europe|japan|china|india|brazil|"
        r"korea|taiwan|germany|canada|mexico|spain|kuwait|saudi|asia|pacific|latin|frontier|"
        r"developed markets|hang seng|msci [a-z]+ (etf|index)", re.I)),
    (BROAD_MARKET, re.compile(
        r"s&p 500|s&p500|total (stock )?market|total world|nifty 50\b|nifty next|sensex|"
        r"russell|nasdaq[- ]100|dow jones industrial|msci (world|acwi|eafe|emerging)|all[- ]world|"
        r"large[- ]?cap|mid[- ]?cap|small[- ]?cap|micro[- ]?cap|nifty 100|nifty 200|nifty 500|"
        r"broad|total market|equal weight|dividend|value|growth|momentum|quality|low vol", re.I)),
]

# Source sector labels (NSE industries + NASDAQ sectors), lower-cased.
_SECTOR_MAP = {
    # Listed trusts (NSE series RR / IV, see listings.TRUST_SERIES)
    "reit": TRUSTS,
    "invit": TRUSTS,
    # NSE
    "information technology": TECHNOLOGY,
    "financial services": FINANCIALS,
    "healthcare": HEALTHCARE,
    "fast moving consumer goods": CONSUMER,
    "consumer durables": CONSUMER,
    "consumer services": SERVICES,
    "automobile and auto components": AUTOMOBILE,
    "capital goods": INDUSTRIALS,
    "oil gas & consumable fuels": ENERGY,
    "power": ENERGY,
    "metals & mining": NATURAL_RESOURCES,
    "forest materials": NATURAL_RESOURCES,
    "chemicals": MATERIALS,
    "construction materials": MATERIALS,
    "construction": REAL_ESTATE,
    "realty": REAL_ESTATE,
    "telecommunication": TELECOM_MEDIA,
    "media entertainment & publication": TELECOM_MEDIA,
    "utilities": UTILITIES,
    "textiles": TEXTILES,
    "services": SERVICES,
    "diversified": OTHER,
    # NASDAQ
    "technology": TECHNOLOGY,
    "finance": FINANCIALS,
    "health care": HEALTHCARE,
    "consumer discretionary": CONSUMER,
    "consumer staples": CONSUMER,
    "industrials": INDUSTRIALS,
    "energy": ENERGY,
    "basic materials": MATERIALS,
    "real estate": REAL_ESTATE,
    "telecommunications": TELECOM_MEDIA,
}

# Checked against industry first, then the company name. Order matters:
# the first matching rule wins, so specific themes sit above generic ones.
_KEYWORD_RULES: list[tuple[str, re.Pattern]] = [
    (AGRICULTURE, re.compile(
        r"\b(agri\w*|agro\w*|farm\w*|seeds?|fertili[sz]\w*|crop\w*|sugars?|tea|teas|coffee|"
        r"plantation\w*|dairy|poultry|rice|flour|milling|feeds?|fisher\w*|aqua\w*|"
        r"edible oils?|solvent|cattle|kisan|krishi|grains?)\b", re.I)),
    (NATURAL_RESOURCES, re.compile(
        r"\b(mining|mines?|minerals?|metals?|steel|iron|ore|alloys?|copper|zinc|"
        r"alumin\w*|gold|silver|precious|coal|granite|marble|forest\w*|timber|"
        r"paper|pulp|quarry\w*|ferro\w*|sponge)\b", re.I)),
    (ENERGY, re.compile(
        r"\b(oil|gas|petro\w*|refin\w*|energ\w*|power\w*|solar|wind|renewable\w*|"
        r"hydro\w*|fuels?|lng|drilling)\b", re.I)),
    (HEALTHCARE, re.compile(
        r"\b(pharma\w*|health\w*|hospitals?|medic\w*|drugs?|bio\w*|labs?|"
        r"laborator\w*|diagnostic\w*|life ?sciences?|remedies|clinic\w*|surgical|"
        r"therapeutic\w*|formulations?)\b", re.I)),
    (TECHNOLOGY, re.compile(
        r"\b(software|tech\w*|infotech|info ?systems?|computer\w*|digital|data|"
        r"cyber\w*|semiconductor\w*|electronics?|it services|infoway|internet|"
        r"cloud|ai|analytics|netsol)\b", re.I)),
    (FINANCIALS, re.compile(
        r"\b(bank\w*|financ\w*|fincorp|fincap|capital|invest\w*|credit|leasing|"
        r"securities|insurance|assurance|asset management|holdings?|fintech|"
        r"money|broking|stock ?brokers?|nbfc)\b", re.I)),
    (TEXTILES, re.compile(
        r"\b(tex\w*|textiles?|spinning|spinners|cotton|yarns?|fabrics?|garments?|apparel|"
        r"weav\w*|knit\w*|denim|silk|jute|mills?)\b", re.I)),
    (AUTOMOBILE, re.compile(r"\b(auto\w*|motors?|tyres?|tires?|vehicles?|forg\w*|mobility|ev|wheels?)\b", re.I)),
    (MATERIALS, re.compile(
        r"\b(chemicals?|chem\w*|paints?|plastics?|polymers?|pipes?|cement|glass|"
        r"ceramics?|packaging|rubber|dyes?|pigments?|fertichem|laminates?)\b", re.I)),
    (REAL_ESTATE, re.compile(
        r"\b(realty|real estate|estates?|housing|homes|builders?|construct\w*|"
        r"infra\w*|developers?|properties|projects)\b", re.I)),
    (TELECOM_MEDIA, re.compile(
        r"\b(telecom\w*|communications?|media|entertainment|broadcast\w*|films?|"
        r"studios?|publish\w*|news\w*|cable|networks?)\b", re.I)),
    (UTILITIES, re.compile(r"\b(water|sewer|utilit\w*|electric utilit\w*)\b", re.I)),
    (CONSUMER, re.compile(
        r"\b(foods?|beverages?|consumer|retail\w*|jewel\w*|fashion|footwear|"
        r"cosmetics?|brands?|appliances?|furniture|breweries|distiller\w*|"
        r"spirits|tobacco|restaurants?)\b", re.I)),
    (SERVICES, re.compile(
        r"\b(hotels?|resorts?|travels?|tours?|logistics|shipping|transport\w*|"
        r"airlines?|aviation|education\w*|services|hospitality|courier|trading|traders|"
        r"impex|exports?|overseas|ventures)\b", re.I)),
    (INDUSTRIALS, re.compile(
        r"\b(engineer\w*|machin\w*|equipments?|electricals?|cables?|industrial\w*|"
        r"tools?|pumps?|valves?|bearings?|defen[cs]e|aerospace|castings?|"
        r"fabricat\w*|compressors?|transformers?|turbines?)\b", re.I)),
]


# Eastmoney's (Chinese) industry names for China A / Hong Kong. Substring
# match, first hit wins, so e.g. 电力设备 (Industrials) precedes 电力 (Energy).
_ZH_RULES: list[tuple[str, tuple[str, ...]]] = [
    # Financials first: 农业银行 / 农商行 are banks, not farms.
    (FINANCIALS, ("银行", "证券", "保险", "金融", "信托", "期货", "农商行")),
    (AGRICULTURE, ("农", "种植", "养殖", "饲料", "渔业", "林业", "动物保健", "畜")),
    (NATURAL_RESOURCES, ("煤炭", "有色", "金属", "钢", "贵金属", "黄金", "冶", "焦炭", "矿", "造纸", "非金属材料")),
    (INDUSTRIALS, ("电力设备", "电网设备", "光伏设备", "风电设备", "电源设备", "电池", "电机", "机械", "专用设备",
                   "通用设备", "自动化设备", "工程机械", "轨交", "航空装备", "航天", "航海装备", "地面兵装",
                   "军工", "环保设备", "照明设备", "工业")),
    (ENERGY, ("石油", "油气", "油服", "炼化", "电力", "燃气", "能源", "光伏", "风电", "新能源")),
    (TECHNOLOGY, ("半导体", "软件", "IT服务", "计算机", "电子", "元件", "光学", "通信设备", "互联网", "科技", "数字")),
    (HEALTHCARE, ("医", "药", "生物", "医疗")),
    (AUTOMOBILE, ("汽车", "乘用车", "商用车", "摩托车")),
    (MATERIALS, ("化学", "化工", "塑料", "橡胶", "玻璃", "水泥", "建材", "化纤", "农化", "包装")),
    (REAL_ESTATE, ("房地产", "地产", "建筑", "基础建设", "工程", "装修", "房屋")),
    (TELECOM_MEDIA, ("通信服务", "电信", "传媒", "广告", "游戏", "影视", "出版", "电视", "媒体")),
    (UTILITIES, ("水务", "公用", "环境治理")),
    (TEXTILES, ("纺织", "服装", "家纺")),
    (CONSUMER, ("食品", "饮料", "乳", "酒", "家电", "家居", "零售", "化妆品", "个护", "饰品", "文娱", "调味",
                "休闲", "电商", "连锁", "美容")),
    (SERVICES, ("物流", "航运", "港口", "机场", "铁路", "公路", "旅游", "酒店", "餐饮", "教育", "贸易", "服务", "体育")),
]


def _match_zh(text: str) -> Optional[str]:
    for category, words in _ZH_RULES:
        if any(w in text for w in words):
            return category
    return None


def _match(text: str) -> Optional[str]:
    for category, pattern in _KEYWORD_RULES:
        if pattern.search(text):
            return category
    return None


def classify(row: dict) -> tuple[str, bool]:
    """(category, inferred) for a stock/ETF row."""
    industry = row.get("industry") or ""
    sector = (row.get("sector") or "").strip()

    # US industries carry themes their broad sector hides (Farming sits
    # under Consumer Staples, Steel under Industrials, ...).
    if industry:
        hit = _match(industry)
        if hit in (AGRICULTURE, NATURAL_RESOURCES, ENERGY, UTILITIES, TECHNOLOGY):
            return hit, False

    mapped = _SECTOR_MAP.get(sector.lower())
    if mapped:
        return mapped, False
    if sector and row.get("market") in ("china_a", "hong_kong"):
        zh = _match_zh(sector)
        if zh:
            return zh, False

    if row.get("type") == "etf":
        text = f"{row.get('symbol', '')} {row.get('name', '')} {row.get('underlying') or ''}"
        # Sector themes first ("Technology Select Sector"), then asset class.
        themed = _match(text)
        if themed and themed not in (FINANCIALS, SERVICES):
            return themed, True
        for category, pattern in _ETF_RULES:
            if pattern.search(text):
                return category, True
        return themed or OTHER, True

    name = row.get("name") or ""
    return _match(name) or _match_zh(row.get("name_local") or name) or OTHER, True


def fund_category(row: dict) -> str:
    """Mutual funds: AMFI scheme group, cleaned into a short label."""
    group = (row.get("fund_group") or "").lower()
    sub = (row.get("sector") or "").lower()
    if "index" in sub or "etf" in sub:
        return "Index / ETF"
    if "fund of funds" in sub or "fof" in sub:
        return "Fund of Funds"
    if "elss" in sub or "elss" in group:
        return "ELSS (Tax Saving)"
    for key, label in (
        ("equity", "Equity"),
        ("debt", "Debt"),
        ("income", "Debt"),
        ("hybrid", "Hybrid"),
        ("solution", "Solution Oriented"),
        ("children", "Solution Oriented"),
        ("retirement", "Solution Oriented"),
        ("growth", "Equity"),
    ):
        if key in group:
            return label
    return "Other"


def enrich(rows: list[dict]) -> list[dict]:
    """Stamp ``category`` (+ ``category_inferred``) on every row in place."""
    for row in rows:
        if row.get("type") == "mf":
            row["category"] = fund_category(row)
            row["category_inferred"] = False
        elif row.get("type") == "crypto":
            row["category"] = "Crypto"
            row["category_inferred"] = False
        else:
            row["category"], row["category_inferred"] = classify(row)
    return rows
