import os
import time
import json
import random
from datetime import datetime
from typing import List
import requests
from bs4 import BeautifulSoup

# ---------- Konfiguration über Umgebungsvariablen ----------
# Mehrere URLs kommasepariert in PRODUCT_URLS, sonst Standardliste:
PRODUCT_URLS = [u.strip() for u in (os.environ.get("PRODUCT_URLS") or "").split(",") if u.strip()] or [
    "https://www.maxgaming.gg/de/kabellos/sora-v2-superlight-kabellos-gaming-maus-schwarz",
    "https://www.maxgaming.gg/de/kabellos/sora-v2-superlight-kabellos-gaming-maus-wei",
    "https://www.maxgaming.gg/de/kabellos/ninjutso-sora-v2-rosa",
]
CHECK_EVERY_SECONDS = int((os.environ.get("CHECK_EVERY_SECONDS") or "300").strip())

# Discord (optional, später per Secret setzen)
DISCORD_WEBHOOK_URL = (os.environ.get("DISCORD_WEBHOOK_URL") or "").strip()

# ---------- HTTP / Heuristik ----------
TIMEOUT = 15
CONNECT_RETRIES = 2
IN_STOCK_KEYWORDS = [
    "auf lager", "in den warenkorb legen", "in stock", "add to cart", "lagerbestand", "left in stock",
]
OUT_OF_STOCK_KEYWORDS = [
    "vorübergehend aus", "ausverkauft", "sold out", "out of stock", "eingehend", "not confirmed",
]
HEADERS_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
]

def fetch(url: str) -> str:
    last_err = None
    for _ in range(CONNECT_RETRIES + 1):
        try:
            headers = {"User-Agent": random.choice(HEADERS_POOL)}
            r = requests.get(url, headers=headers, timeout=TIMEOUT)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_err = e
            time.sleep(1 + random.random() * 2)
    raise last_err

def text_contains_any(text: str, keywords: List[str]) -> bool:
    t = text.lower()
    return any(k in t for k in keywords)

def looks_in_stock(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")

    # 1) JSON-LD availability
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
            items = data if isinstance(data, list) else [data]
            for it in items:
                offers = it.get("offers")
                if isinstance(offers, dict):
                    availability = str(offers.get("availability", "")).lower()
                    if "instock" in availability: return True
                    if "outofstock" in availability: return False
                elif isinstance(offers, list):
                    for off in offers:
                        availability = str(off.get("availability", "")).lower()
                        if "instock" in availability: return True
                        if "outofstock" in availability: return False
        except Exception:
            pass

    # 2) Buttons/Labels
    texts = []
    for el in soup.find_all(["button", "a", "div", "span"], string=True):
        s = el.get_text(separator=" ", strip=True)
        if s: texts.append(s)
    joined = " ".join(texts).lower()
    if text_contains_any(joined, OUT_OF_STOCK_KEYWORDS): return False
    if text_contains_any(joined, IN_STOCK_KEYWORDS): return True

    # 3) Fallback: Gesamttext + "Lagerbestand"
    full_text = soup.get_text(separator=" ", strip=True).lower()
    if "lagerbestand" in full_text:
        try:
            window = full_text.split("lagerbestand", 1)[1][:80]
            digits = "".join(ch for ch in window if ch.isdigit())
            if digits: return int(digits) > 0
        except Exception:
            pass

    in_hits = sum(1 for k in IN_STOCK_KEYWORDS if k in full_text)
    out_hits = sum(1 for k in OUT_OF_STOCK_KEYWORDS if k in full_text)
    if out_hits > 0 and in_hits == 0: return False
    if in_hits > 0 and out_hits == 0: return True
    return False

def send_discord(msg: str):
    if not DISCORD_WEBHOOK_URL:
        # Kein Webhook gesetzt -> nur in Logs ausgeben
        print(msg, flush=True)
        return
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"[WARN] Discord-Webhook fehlgeschlagen: {e}\nNachricht wäre: {msg}", flush=True)

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# -------- zwei Modi: einmaliger Lauf (für Actions) ODER Endlosschleife --------
def run_once():
    for url in PRODUCT_URLS:
        try:
            html = fetch(url)
            in_stock = looks_in_stock(html)
        except Exception as e:
            log(f"⚠ Fehler beim Abruf {url}: {e}")
            continue

        if in_stock:
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            msg = f"✅ IN STOCK bei MaxGaming!\n{url}\nZeit: {ts}"
            log(f"✅ IN STOCK: {url}")
            send_discord(msg)
        else:
            log(f"❌ Nicht verfügbar: {url}")

def main_loop():
    already_alerted = set()
    while True:
        for url in PRODUCT_URLS:
            try:
                html = fetch(url)
                in_stock = looks_in_stock(html)
            except Exception as e:
                log(f"⚠ Fehler beim Abruf {url}: {e}")
                continue

            if in_stock:
                if url not in already_alerted:
                    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    msg = f"✅ IN STOCK bei MaxGaming!\n{url}\nZeit: {ts}"
                    log(f"✅ IN STOCK: {url}")
                    send_discord(msg)
                    already_alerted.add(url)
                else:
                    log(f"✅ Bereits gemeldet (noch in Stock): {url}")
            else:
                log(f"❌ Nicht verfügbar: {url}")

        time.sleep(max(30, CHECK_EVERY_SECONDS + random.randint(-15, 15)))

if __name__ == "__main__":
    # In GitHub Actions setzen wir RUN_ONCE=1 -> nur ein Durchlauf
    if (os.environ.get("RUN_ONCE") or "").strip() == "1":
        run_once()
    else:
        main_loop()
