"""
P2: aiohttp → httpx migration. Exercise the converted tools against an
in-process ``httpx.MockTransport`` (no network) — success, status-code and
timeout paths.
"""

from __future__ import annotations

import httpx
import pytest


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


def _timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("slow", request=request)


# =============================================================================
# finance_tools
# =============================================================================


@pytest.fixture
def finance(monkeypatch):
    from src.infra.tools import finance_tools

    def use(handler):
        monkeypatch.setattr(finance_tools, "_http_session", _client(handler))
        return finance_tools

    return use


@pytest.mark.asyncio
async def test_stock_price_parses_quote(finance):
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "regularMarketPrice": 110.0,
                                "chartPreviousClose": 100.0,
                                "currency": "USD",
                                "shortName": "Apple",
                            }
                        }
                    ]
                }
            },
        )

    out = await finance(handler).get_stock_price("aapl")
    assert out.startswith("Apple (AAPL): 110.00 USD ▲ +10.00 (+10.00%)")
    assert seen[0].url.path.endswith("/AAPL")
    assert seen[0].url.params["range"] == "1d"


@pytest.mark.asyncio
async def test_stock_price_404_and_timeout(finance):
    out = await finance(lambda r: httpx.Response(404)).get_stock_price("NOPE")
    assert "No stock found" in out
    out = await finance(_timeout).get_stock_price("AAPL")
    assert out == "Stock request timed out. Please try again."


@pytest.mark.asyncio
async def test_crypto_price_and_rate_limit(finance):
    def handler(request):
        assert request.url.params["ids"] == "bitcoin"
        return httpx.Response(200, json={"bitcoin": {"usd": 50000.0, "usd_24h_change": -1.5}})

    out = await finance(handler).get_crypto_price("btc")
    assert out == "Bitcoin: 50,000.00 USD ▼ -1.50% (24h)"
    out = await finance(lambda r: httpx.Response(429)).get_crypto_price("btc")
    assert "rate-limited" in out


@pytest.mark.asyncio
async def test_crypto_connect_error_is_reported(finance):
    def handler(request):
        raise httpx.ConnectError("down", request=request)

    out = await finance(handler).get_crypto_price("eth")
    assert out.startswith("Network error fetching crypto data")


# =============================================================================
# info_tools
# =============================================================================


@pytest.fixture
def info(monkeypatch):
    from src.infra.tools import info_tools

    monkeypatch.setattr(info_tools.settings, "WEATHER_API_KEY", "k")
    monkeypatch.setattr(info_tools.settings, "NEWS_API_KEY", "k")

    def use(handler):
        monkeypatch.setattr(info_tools, "_http_session", _client(handler))
        return info_tools

    return use


@pytest.mark.asyncio
async def test_weather_parses_response(info):
    payload = {
        "main": {"temp": 21.0, "feels_like": 20.0, "humidity": 50},
        "weather": [{"description": "clear sky"}],
        "name": "Pune",
        "sys": {"country": "IN"},
        "wind": {"speed": 10},
    }
    out = await info(lambda r: httpx.Response(200, json=payload)).get_weather_async("Pune")
    assert out.startswith("Weather in Pune, IN: Clear sky. Temperature is 21.0°C")
    assert "36.0 km/h" in out
    out = await info(_timeout).get_weather_async("Pune")
    assert out == "Weather request timed out. Please try again."


@pytest.mark.asyncio
async def test_news_headlines(info):
    payload = {
        "status": "ok",
        "articles": [
            {"title": "A", "source": {"name": "S1"}},
            {"title": "B", "source": {"name": "S2"}},
        ],
    }
    out = await info(lambda r: httpx.Response(200, json=payload)).get_news_async(count="2")
    assert out == "Top 2 general headlines:\n1. A (S1)\n2. B (S2)"


@pytest.mark.asyncio
async def test_wikipedia_summary_and_404_fallback(info):
    def handler(request):
        if "rest_v1" in request.url.path:
            if "Missing" in request.url.path:
                return httpx.Response(404)
            return httpx.Response(200, json={"title": "Pune", "extract": "One. Two. Three. Four."})
        return httpx.Response(
            200,
            json={
                "query": {
                    "search": [
                        {"title": "Found", "snippet": '<span class="searchmatch">x</span> y'},
                    ]
                }
            },
        )

    tools = info(handler)
    out = await tools.wikipedia_search_async("Pune", sentences=2)
    assert out == "From Wikipedia - Pune:\nOne. Two."
    fallback = await tools.wikipedia_search_async("Missing")
    assert "Found" in fallback


# =============================================================================
# search_router
# =============================================================================


@pytest.mark.asyncio
async def test_search_router_wikipedia_and_tavily(monkeypatch):
    from src.infra.search import search_router as sr

    def handler(request):
        if request.url.host == "en.wikipedia.org":
            return httpx.Response(
                200,
                json={
                    "title": "Python",
                    "extract": "P" * 200,
                    "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Python"}},
                },
            )
        assert request.url.host == "api.tavily.com"
        assert request.method == "POST"
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "T", "content": "C", "url": "https://t.example"},
                ]
            },
        )

    router = sr.SearchRouter(tavily_api_key="key")
    router._session = _client(handler)

    async def no_ddg(self, query, max_results):
        return []

    monkeypatch.setattr(sr.SearchRouter, "_ddg_results", no_ddg)
    results = await router.search_results("what is python")
    assert [r["provider"] for r in results] == ["wikipedia", "tavily"]
    assert results[0]["url"] == "https://en.wikipedia.org/wiki/Python"

    assert (await router.search("what is python")).startswith("P")
    await router.close()
    assert router._session is None
