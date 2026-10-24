"""English for the Chinese names China A data comes with (opt-in on the page).

No AI needed:
- Stock names: the company's own English name from Yahoo ("宁德时代" ->
  "Contemporary Amperex Technology"), fetched only for the symbols on
  screen and saved for good in ~/.marketmyna/cache/english_names.json.
  Beijing-exchange stocks Yahoo lacks fall back to pinyin.
- Free text (block-trade broker branches, ...): a glossary of brokers and
  standard terms, the rest romanised with pypinyin ("上海浦东新区" ->
  "Shanghai Pudong Xinqu").
"""

from __future__ import annotations

import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

from src.core.home import app_home

logger = logging.getLogger(__name__)

CJK = re.compile(r"[㐀-鿿]")
MAX_LOOKUPS = 80  # per request; the rest come on the next scroll / page

# Longest first when applied. Brokers people will recognise, then the
# boilerplate every branch name carries.
GLOSSARY = {
    "机构专用": "Institutional seat",
    "沪股通专用": "Northbound (Shanghai Connect)",
    "深股通专用": "Northbound (Shenzhen Connect)",
    "中国国际金融": "CICC", "中信证券": "CITIC Securities", "中信建投": "CSC Financial", "华泰证券": "Huatai Securities",
    "国泰君安": "Guotai Junan", "国泰海通": "Guotai Haitong", "海通证券": "Haitong Securities", "招商证券": "China Merchants Securities",
    "广发证券": "GF Securities", "银河证券": "China Galaxy Securities", "中国银河": "China Galaxy", "申万宏源": "Shenwan Hongyuan",
    "东方财富": "East Money", "国信证券": "Guosen Securities", "光大证券": "Everbright Securities", "兴业证券": "Industrial Securities",
    "长江证券": "Changjiang Securities", "方正证券": "Founder Securities", "东方证券": "Orient Securities", "平安证券": "Ping An Securities",
    "安信证券": "Essence Securities", "国金证券": "Sinolink Securities", "华西证券": "Huaxi Securities", "浙商证券": "Zheshang Securities",
    "财通证券": "Caitong Securities", "长城证券": "Great Wall Securities", "中泰证券": "Zhongtai Securities", "东吴证券": "Soochow Securities",
    "华安证券": "Huaan Securities", "国元证券": "Guoyuan Securities", "西部证券": "Western Securities", "天风证券": "Tianfeng Securities",
    "开源证券": "Kaiyuan Securities", "华鑫证券": "Huaxin Securities", "中金财富": "CICC Wealth", "瑞银证券": "UBS Securities",
    "摩根大通证券": "J.P. Morgan Securities", "高盛高华": "Goldman Sachs Gao Hua", "华宝证券": "Huabao Securities",
    "股份有限公司": "", "有限责任公司": "", "有限公司": "", "分公司": " branch", "证券营业部": " branch", "营业部": " branch",
    "证券": " Securities", "总部": " HQ", "路": " Rd", "大道": " Ave", "大街": " St", "街": " St",
    "新区": " New Area", "开发区": " Dev Zone", "自贸区": " FTZ",
}
_GLOSS = sorted(GLOSSARY.items(), key=lambda kv: -len(kv[0]))
_SUFFIX = re.compile(r",?\s*(co\.?,?\s*ltd\.?|company limited|co\.?,?\s*limited|limited|corporation|corp\.?|inc\.?)\s*$", re.I)

_lock = threading.Lock()
_names: Optional[dict[str, str]] = None


def has_cjk(text: Optional[str]) -> bool:
    return bool(text and CJK.search(text))


def pinyin(text: str) -> str:
    """CJK runs -> capitalised pinyin words; everything else kept."""
    try:
        from pypinyin import lazy_pinyin
    except ImportError:
        return text

    def run(m: re.Match) -> str:
        # No word segmentation offline; most Chinese place and street names
        # are two characters, so pair the syllables: "Ningbo Tiantong Bei".
        syl = lazy_pinyin(m.group(0))
        return " " + " ".join("".join(syl[i:i + 2]).capitalize() for i in range(0, len(syl), 2)) + " "

    return re.sub(r"[㐀-鿿]+", run, text)


def english_text(text: str) -> str:
    if not has_cjk(text):
        return text
    out = text
    for zh, en in _GLOSS:
        out = out.replace(zh, f" {en} " if en and not en.startswith(" ") else en)
    out = pinyin(out)
    out = re.sub(r"\s+", " ", out).strip()
    return re.sub(r"\s+([,)])", r"\1", out)


def clean_company(name: str) -> str:
    return _SUFFIX.sub("", (name or "").strip()).strip(" ,")


# ------------------------------------------------------------ stock names


def _path() -> Path:
    path = app_home() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path / "english_names.json"


def _load() -> dict[str, str]:
    global _names
    if _names is None:
        try:
            _names = json.loads(_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _names = {}
    return _names


def _save() -> None:
    try:
        _path().write_text(json.dumps(_names, ensure_ascii=False, indent=0), encoding="utf-8")
    except OSError as exc:
        logger.warning("English names cache not saved: %s", exc)


def _yahoo_name(yahoo: str) -> Optional[str]:
    import yfinance as yf

    try:
        info = yf.Ticker(yahoo).info or {}
    except Exception:
        return None
    name = info.get("longName") or info.get("shortName")
    return clean_company(name) if name and not has_cjk(name) else None


def english_names(items: list[tuple[str, str]], market: str,
                  lookup: Callable[[str], Optional[str]] = _yahoo_name) -> dict[str, str]:
    """[(symbol, chinese name)] -> {symbol: English name}. Cached forever;
    unknown to Yahoo -> pinyin of the Chinese name (also cached)."""
    from .analysis_run import yahoo_symbol

    with _lock:
        names = _load()
        missing = [(s, n) for s, n in items if f"{market}:{s}" not in names][:MAX_LOOKUPS]
    if missing:
        with ThreadPoolExecutor(max_workers=8) as pool:
            found = list(pool.map(lambda sn: lookup(yahoo_symbol(sn[0], market)), missing))
        with _lock:
            for (sym, zh), en in zip(missing, found):
                names[f"{market}:{sym}"] = en or english_text(zh)
            _save()
    with _lock:
        return {s: names[f"{market}:{s}"] for s, _ in items if f"{market}:{s}" in names}
