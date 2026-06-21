"""
Finance tools for Amadeus AI Assistant.

Provides stock quotes (Yahoo Finance public chart API) and cryptocurrency
prices (CoinGecko public API). Both endpoints are keyless and free, keeping
the memory and configuration footprint at zero — only aiohttp is used.

Owned by the `finance_expert` MoE profile (ToolCategory.FINANCE).
"""

import logging
from typing import Any

import aiohttp

from src.infra.tools.base import Tool, ToolCategory, tool


logger = logging.getLogger(__name__)

_http_session: aiohttp.ClientSession | None = None

_UA_HEADERS = {"User-Agent": "AmadeusAI/5.0 (https://github.com/adityatawde9699/Amadeus-AI)"}

# Common crypto ticker → CoinGecko coin id
_COINGECKO_IDS = {
    "btc": "bitcoin", "bitcoin": "bitcoin",
    "eth": "ethereum", "ethereum": "ethereum",
    "sol": "solana", "solana": "solana",
    "doge": "dogecoin", "dogecoin": "dogecoin",
    "xrp": "ripple", "ripple": "ripple",
    "ada": "cardano", "cardano": "cardano",
    "bnb": "binancecoin", "binancecoin": "binancecoin",
    "ltc": "litecoin", "litecoin": "litecoin",
    "dot": "polkadot", "polkadot": "polkadot",
    "matic": "matic-network", "polygon": "matic-network",
    "shib": "shiba-inu", "usdt": "tether", "usdc": "usd-coin",
}


async def initialize_finance_tools_http_session() -> None:
    """Create the shared HTTP session used by finance tools."""
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession()


async def close_finance_tools_http_session() -> None:
    """Close the shared HTTP session used by finance tools."""
    global _http_session
    if _http_session is not None and not _http_session.closed:
        await _http_session.close()
    _http_session = None


async def _get_http_session() -> aiohttp.ClientSession:
    if _http_session is None or _http_session.closed:
        await initialize_finance_tools_http_session()
    if _http_session is None:
        raise RuntimeError("finance tools HTTP session is unavailable")
    return _http_session


# =============================================================================
# STOCK TOOLS
# =============================================================================


@tool(
    name="get_stock_price",
    description=(
        "Fetches the latest stock quote for a ticker symbol via Yahoo Finance. "
        "Returns current price, currency, day change, and previous close. "
        "Use Yahoo symbols: 'AAPL', 'MSFT', 'TSLA'; Indian stocks need the exchange "
        "suffix, e.g. 'RELIANCE.NS', 'TCS.NS' (NSE) or 'RELIANCE.BO' (BSE). "
        "Trigger: 'stock price of Apple', 'how is TSLA doing', 'Reliance share price'"
    ),
    category=ToolCategory.FINANCE,
    parameters={
        "symbol": {
            "type": "string",
            "description": "Ticker symbol, e.g. 'AAPL', 'TSLA', 'RELIANCE.NS'",
        },
    },
)
async def get_stock_price(symbol: str | None = None, **kwargs: Any) -> str:
    """Fetch the latest quote for a stock symbol from Yahoo Finance."""
    ticker = (symbol or kwargs.get("ticker") or "").strip().upper()
    if not ticker:
        return "Error: No stock symbol provided. Example: 'AAPL' or 'RELIANCE.NS'."

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"range": "1d", "interval": "1d"}

    try:
        session = await _get_http_session()
        async with session.get(
            url, params=params, headers=_UA_HEADERS, timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            if response.status == 404:
                return f"No stock found for symbol '{ticker}'. Check the ticker (Indian stocks need '.NS' or '.BO')."
            if response.status != 200:
                return f"Stock service error (status {response.status})."

            data = await response.json()

        result = (data.get("chart", {}).get("result") or [None])[0]
        if not result:
            err = data.get("chart", {}).get("error") or {}
            return f"No data for '{ticker}': {err.get('description', 'unknown symbol')}"

        meta = result.get("meta", {})
        price = meta.get("regularMarketPrice")
        prev_close = meta.get("chartPreviousClose") or meta.get("previousClose")
        currency = meta.get("currency", "")
        name = meta.get("longName") or meta.get("shortName") or ticker

        if price is None:
            return f"Could not read a price for '{ticker}'."

        line = f"{name} ({ticker}): {price:,.2f} {currency}"
        if prev_close:
            change = price - prev_close
            pct = (change / prev_close) * 100
            arrow = "▲" if change >= 0 else "▼"
            line += f" {arrow} {change:+,.2f} ({pct:+.2f}%) vs previous close {prev_close:,.2f}"
        return line

    except TimeoutError:
        return "Stock request timed out. Please try again."
    except aiohttp.ClientError as e:
        return f"Network error fetching stock data: {e}"
    except Exception as e:
        logger.exception("get_stock_price failed for %s", ticker)
        return f"Sorry, I couldn't fetch the stock price: {e}"


# =============================================================================
# CRYPTO TOOLS
# =============================================================================


@tool(
    name="get_crypto_price",
    description=(
        "Fetches the current price of a cryptocurrency via CoinGecko (no API key). "
        "Accepts common names or tickers: 'bitcoin'/'btc', 'ethereum'/'eth', 'solana'/'sol'. "
        "Returns price in USD plus 24h change. Optionally pass vs_currency ('inr', 'eur'). "
        "Trigger: 'bitcoin price', 'how much is ETH', 'crypto prices', 'BTC in INR'"
    ),
    category=ToolCategory.FINANCE,
    parameters={
        "coin": {
            "type": "string",
            "description": "Coin name or ticker, e.g. 'bitcoin', 'btc', 'eth'",
        },
        "vs_currency": {
            "type": "string",
            "description": "Quote currency code (default: 'usd'), e.g. 'inr', 'eur'",
        },
    },
)
async def get_crypto_price(
    coin: str | None = None, vs_currency: str = "usd", **kwargs: Any
) -> str:
    """Fetch the current price and 24h change for a cryptocurrency."""
    raw = (coin or kwargs.get("symbol") or kwargs.get("name") or "").strip().lower()
    if not raw:
        return "Error: No coin provided. Example: 'bitcoin' or 'eth'."

    coin_id = _COINGECKO_IDS.get(raw, raw)
    vs = (vs_currency or "usd").strip().lower()

    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": coin_id,
        "vs_currencies": vs,
        "include_24hr_change": "true",
    }

    try:
        session = await _get_http_session()
        async with session.get(
            url, params=params, headers=_UA_HEADERS, timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            if response.status == 429:
                return "Crypto service is rate-limited right now. Try again in a minute."
            if response.status != 200:
                return f"Crypto service error (status {response.status})."

            data = await response.json()

        entry = data.get(coin_id)
        if not entry or vs not in entry:
            return (
                f"No price found for '{raw}'. Use full CoinGecko ids for less common "
                "coins (e.g. 'bitcoin', 'ethereum', 'solana')."
            )

        price = entry[vs]
        change = entry.get(f"{vs}_24h_change")
        line = f"{coin_id.replace('-', ' ').title()}: {price:,.4f} {vs.upper()}" \
            if price < 1 else f"{coin_id.replace('-', ' ').title()}: {price:,.2f} {vs.upper()}"
        if change is not None:
            arrow = "▲" if change >= 0 else "▼"
            line += f" {arrow} {change:+.2f}% (24h)"
        return line

    except TimeoutError:
        return "Crypto request timed out. Please try again."
    except aiohttp.ClientError as e:
        return f"Network error fetching crypto data: {e}"
    except Exception as e:
        logger.exception("get_crypto_price failed for %s", raw)
        return f"Sorry, I couldn't fetch the crypto price: {e}"


# =============================================================================
# TOOL COLLECTION
# =============================================================================


def get_finance_tools() -> list[Tool]:
    """Get all finance tools for manual registration."""
    return [
        get_stock_price._tool_metadata,  # type: ignore[attr-defined]
        get_crypto_price._tool_metadata,  # type: ignore[attr-defined]
    ]
