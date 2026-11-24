#!/usr/bin/env python3
"""
MemeBot - Paper trading (DEMO) l meme coins f Solana.
MA KAYSTA3MELCH FLOUS 7A9I9IYA. Ma kaytlab 7ta private key.

Kayqra data men DexScreener (API fabor, bla key) w kaydir "fri9" dyal 12 agent:
 1. Scout          - kayjib les tokens jdad f Solana
 2. Data Feed      - kayjib taman, liquidity, volume, buys/sells
 3. Age Filter     - token machi jdid bzaf w machi 9dim bzaf
 4. Liquidity Guard- liquidity kafya (bach t9der tbi3)
 5. Volume Flow    - wach kayn volume 7a9i9i
 6. Buy Pressure   - wach chrayin ktar men bay3in
 7. Momentum       - wach taman tal3 (bla ma ykon tla3 bzaf)
 8. Rug Check      - FDV/liquidity ma ykonch m7m9
 9. Risk Gate      - max positions, ma t3awedch nfs token
10. Sizer          - ch7al t7et f kol trade
11. Exit Manager   - Take profit / Stop loss / trailing / wa9t
12. Head Trader    - kayjma3 l'avis w kay9arrer

Kaykhddem: python3 memebot.py
Kaykteb: trades.csv (kol trade) w state.json (balance w positions)
Ma kay7tajch 7ta library: ghir Python 3.8+
"""

import csv
import json
import os
import time
import urllib.request
from datetime import datetime, timezone

# ====================== SETTINGS (bddel hna) ======================
START_BALANCE = 150.0        # flous wahmiya ($)
SCAN_EVERY_SEC = 60          # kol ch7al d tanya kaychof
POSITION_PCT = 0.10          # 10% men balance f kol trade
MAX_OPEN = 3                 # max dyal trades m7loulin f nfs l wa9t
FEE_SLIPPAGE = 0.01          # 1% f dkhla w 1% f khrja (simulation)

MIN_LIQ_USD = 15_000         # Liquidity Guard
MIN_AGE_MIN = 10             # Age Filter (d9ay9)
MAX_AGE_MIN = 24 * 60
MIN_VOL_5M = 3_000           # Volume Flow ($ f 5 d9ay9)
MIN_BUY_RATIO = 1.3          # Buy Pressure: buys/sells
MAX_FDV_TO_LIQ = 40          # Rug Check
MIN_SCORE = 7                # Head Trader: score min (men 10)

TAKE_PROFIT = 0.30           # +30%
STOP_LOSS = -0.15            # -15%
TRAIL_FROM = 0.15            # trailing kaybda men +15%
TRAIL_GAP = 0.10             # kaybi3 ila tay7 10% men a3la point
MAX_HOLD_MIN = 60            # max wa9t f trade
# =================================================================

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "state.json")
TRADES_FILE = os.path.join(HERE, "trades.csv")
API = "https://api.dexscreener.com"


def now():
    return time.time()


def ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def log(agent, msg):
    print(f"[{ts()}] {agent:<15} | {msg}", flush=True)


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "memebot-paper/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


# ---------------------- STATE ----------------------
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"balance": START_BALANCE, "positions": {}, "seen": [],
            "wins": 0, "losses": 0}


def save_state(s):
    s["seen"] = s["seen"][-500:]
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=2)


def record_trade(row):
    new = not os.path.exists(TRADES_FILE)
    with open(TRADES_FILE, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "symbol", "address", "entry", "exit",
                        "pnl_pct", "pnl_usd", "reason", "balance_after"])
        w.writerow(row)


# ---------------------- AGENTS ----------------------
def agent_scout():
    """1. Scout: tokens jdad f Solana."""
    addrs = []
    for path in ("/token-profiles/latest/v1", "/token-boosts/latest/v1"):
        try:
            data = get_json(API + path)
            for t in data if isinstance(data, list) else []:
                if t.get("chainId") == "solana" and t.get("tokenAddress"):
                    addrs.append(t["tokenAddress"])
        except Exception as e:
            log("Scout", f"error {path}: {e}")
    addrs = list(dict.fromkeys(addrs))
    log("Scout", f"l9it {len(addrs)} token f Solana")
    return addrs


def agent_data_feed(addresses):
    """2. Data Feed: a7san pair (a3la liquidity) l kol token."""
    best = {}
    for i in range(0, len(addresses), 30):
        chunk = ",".join(addresses[i:i + 30])
        try:
            pairs = get_json(f"{API}/tokens/v1/solana/{chunk}")
        except Exception as e:
            log("Data Feed", f"error: {e}")
            continue
        for p in pairs if isinstance(pairs, list) else []:
            a = (p.get("baseToken") or {}).get("address")
            liq = (p.get("liquidity") or {}).get("usd") or 0
            if a and (a not in best or liq > best[a]["liq"]):
                best[a] = parse_pair(p)
    return best


def parse_pair(p):
    tx5 = (p.get("txns") or {}).get("m5") or {}
    created = p.get("pairCreatedAt") or 0
    return {
        "address": p["baseToken"]["address"],
        "symbol": p["baseToken"].get("symbol", "?"),
        "price": float(p.get("priceUsd") or 0),
        "liq": float((p.get("liquidity") or {}).get("usd") or 0),
        "fdv": float(p.get("fdv") or p.get("marketCap") or 0),
        "vol5m": float((p.get("volume") or {}).get("m5") or 0),
        "chg5m": float((p.get("priceChange") or {}).get("m5") or 0),
        "chg1h": float((p.get("priceChange") or {}).get("h1") or 0),
        "buys5m": int(tx5.get("buys") or 0),
        "sells5m": int(tx5.get("sells") or 0),
        "age_min": (now() * 1000 - created) / 60000 if created else -1,
    }


def agent_age(t):          # 3
    return MIN_AGE_MIN <= t["age_min"] <= MAX_AGE_MIN


def agent_liquidity(t):    # 4
    return t["liq"] >= MIN_LIQ_USD


def agent_volume(t):       # 5
    return t["vol5m"] >= MIN_VOL_5M


def agent_buy_pressure(t):  # 6
    return t["buys5m"] / max(t["sells5m"], 1) >= MIN_BUY_RATIO


def agent_momentum(t):     # 7 - tal3 walakin machi f qmma
    return t["chg5m"] > 0 and 0 < t["chg1h"] < 200


def agent_rug_check(t):    # 8
    return t["liq"] > 0 and t["fdv"] / t["liq"] <= MAX_FDV_TO_LIQ


def agent_risk_gate(t, s):  # 9
    return (len(s["positions"]) < MAX_OPEN
            and t["address"] not in s["positions"]
            and t["address"] not in s["seen"])


def agent_sizer(s):        # 10
    return round(s["balance"] * POSITION_PCT, 2)


def agent_exit_manager(s, prices):  # 11
    for addr, pos in list(s["positions"].items()):
        price = prices.get(addr)
        if not price:
            if (now() - pos["opened"]) / 60 > MAX_HOLD_MIN * 2:
                close(s, addr, pos["entry"] * 0.5, "no data (-50%)")
            continue
        pos["peak"] = max(pos["peak"], price)
        chg = price / pos["entry"] - 1
        from_peak = price / pos["peak"] - 1
        held = (now() - pos["opened"]) / 60
        reason = None
        if chg >= TAKE_PROFIT:
            reason = "take profit"
        elif chg <= STOP_LOSS:
            reason = "stop loss"
        elif pos["peak"] / pos["entry"] - 1 >= TRAIL_FROM and from_peak <= -TRAIL_GAP:
            reason = "trailing stop"
        elif held >= MAX_HOLD_MIN:
            reason = "time exit"
        if reason:
            close(s, addr, price, reason)


def close(s, addr, price, reason):
    pos = s["positions"].pop(addr)
    gross = pos["size"] * price / pos["entry"]
    net = gross * (1 - FEE_SLIPPAGE)
    pnl = net - pos["size"]
    s["balance"] += net
    s["wins" if pnl > 0 else "losses"] += 1
    pct = pnl / pos["size"] * 100
    log("Exit Manager", f"BI3 {pos['symbol']} | {reason} | {pct:+.1f}% "
        f"({pnl:+.2f}$) | balance {s['balance']:.2f}$")
    record_trade([ts(), pos["symbol"], addr, pos["entry"], price,
                  round(pct, 2), round(pnl, 2), reason, round(s["balance"], 2)])


def agent_head_trader(t, s):  # 12
    checks = {
        "Age": agent_age(t), "Liquidity": agent_liquidity(t),
        "Volume": agent_volume(t), "BuyPressure": agent_buy_pressure(t),
        "Momentum": agent_momentum(t), "RugCheck": agent_rug_check(t),
    }
    score = sum(checks.values()) / len(checks) * 10
    must = checks["Liquidity"] and checks["RugCheck"] and checks["Age"]
    if must and score >= MIN_SCORE and agent_risk_gate(t, s):
        size = agent_sizer(s)
        if size < 1:
            return
        s["balance"] -= size
        entry = t["price"] * (1 + FEE_SLIPPAGE)  # dkhla ghalya chwiya
        s["positions"][t["address"]] = {
            "symbol": t["symbol"], "entry": entry, "peak": entry,
            "size": size, "opened": now()}
        s["seen"].append(t["address"])
        log("Head Trader", f"CHRI {t['symbol']} b {size}$ | score {score:.1f}/10 "
            f"| liq {t['liq']:,.0f}$ | vol5m {t['vol5m']:,.0f}$")


# ---------------------- LOOP ----------------------
def summary(s):
    open_val = sum(p["size"] for p in s["positions"].values())
    total = s["balance"] + open_val
    n = s["wins"] + s["losses"]
    wr = s["wins"] / n * 100 if n else 0
    log("Summary", f"total ~{total:.2f}$ (bda b {START_BALANCE}$) | "
        f"{s['wins']}W/{s['losses']}L ({wr:.0f}%) | open {len(s['positions'])}")


def main():
    # RUN_MINUTES=13 -> kaykhdem 13 d9i9a w kaytfa (l GitHub Actions)
    # bla RUN_MINUTES -> kaykhdem dima (l serveur/VPS)
    run_min = float(os.environ.get("RUN_MINUTES", "0"))
    stop_at = now() + run_min * 60 if run_min > 0 else None
    log("Bot", "DEMO / PAPER TRADING - ma kayn 7ta flous 7a9i9iya")
    s = load_state()
    while stop_at is None or now() < stop_at:
        try:
            addrs = agent_scout()
            watch = list(set(addrs) | set(s["positions"].keys()))
            data = agent_data_feed(watch)
            agent_exit_manager(s, {a: d["price"] for a, d in data.items()})
            for a in addrs:
                if a in data:
                    agent_head_trader(data[a], s)
            summary(s)
            save_state(s)
        except KeyboardInterrupt:
            save_state(s)
            break
        except Exception as e:
            log("Bot", f"error: {e}")
        time.sleep(SCAN_EVERY_SEC)


if __name__ == "__main__":
    main()
