"""Application constants and enums."""

from enum import Enum


class Markets(Enum):
    """Supported markets."""
    US = "us"
    INDIA = "india"
    GLOBAL = "global"
    CRYPTO = "crypto"
    CHINA_A = "china_a"
    HONG_KONG = "hong_kong"


class TimeFrame(Enum):
    """Chart timeframes."""
    MINUTE_1 = "1m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    MINUTE_30 = "30m"
    HOUR_1 = "1h"
    HOUR_4 = "4h"
    DAY_1 = "1d"
    WEEK_1 = "1wk"
    MONTH_1 = "1mo"




# Popular indices by market
MARKET_INDICES = {
    Markets.US: [
        ("^GSPC", "S&P 500"),
        ("^DJI", "Dow Jones"),
        ("^IXIC", "NASDAQ"),
        ("^RUT", "Russell 2000"),
    ],
    Markets.INDIA: [
        ("^NSEI", "NIFTY 50"),
        ("^BSESN", "SENSEX"),
        ("^NSEBANK", "NIFTY Bank"),
        ("RELIANCE.NS", "Reliance"),
    ],
    Markets.CRYPTO: [
        ("BTC-USD", "Bitcoin"),
        ("ETH-USD", "Ethereum"),
        ("BNB-USD", "Binance Coin"),
    ],
    Markets.CHINA_A: [
        ("000001", "上证指数 (Shanghai Composite)"),
        ("399001", "深证成指 (Shenzhen Component)"),
        ("399006", "创业板指 (ChiNext)"),
    ],
    Markets.HONG_KONG: [
        ("HSI", "恒生指数 (Hang Seng Index)"),
        ("00700", "腾讯控股 (Tencent)"),
        ("09988", "阿里巴巴 (Alibaba)"),
    ],
}

# Default watchlist symbols
DEFAULT_WATCHLIST = {
    Markets.US: ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"],
    Markets.INDIA: ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS"],
    Markets.CRYPTO: ["BTC-USD", "ETH-USD", "SOL-USD", "ADA-USD"],
    Markets.CHINA_A: ["600519", "000001", "000002", "601318"],
    Markets.HONG_KONG: ["00700", "00005", "09988", "03690"],
}
