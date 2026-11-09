"""Shared helpers: public unauthenticated HTTP only, polite rate limiting."""
import time, json, requests

HL = "https://api.hyperliquid.xyz/info"
BIN_F = "https://fapi.binance.com"
BIN_S = "https://api.binance.com"
BYB = "https://api.bybit.com"
COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "SUI", "LINK", "AVAX"]
S = requests.Session()
S.headers["User-Agent"] = "perps-arb-research/0.1"


def _req(method, url, sleep=0.25, **kw):
    for attempt in range(6):
        try:
            r = S.request(method, url, timeout=30, **kw)
        except requests.RequestException as e:
            time.sleep(2 ** attempt); continue
        if r.status_code in (429, 418) or r.status_code >= 500:
            time.sleep(2 ** attempt + 1); continue
        if r.status_code in (403, 451):
            raise RuntimeError(f"GEO-BLOCKED {r.status_code} {url}")
        r.raise_for_status()
        time.sleep(sleep)
        return r.json()
    raise RuntimeError(f"failed after retries: {url}")


def hl(body, sleep=0.4):
    return _req("POST", HL, sleep=sleep, json=body)


def get(url, params=None, sleep=0.25):
    return _req("GET", url, sleep=sleep, params=params)
