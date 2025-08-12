import os
import time
import json
import random
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
from typing import List
import requests
from bs4 import BeautifulSoup

# ---------- Konfiguration über Railway Variables ----------
PRODUCT_URLS = [u.strip() for u in os.environ.get("PRODUCT_URLS","").split(",") if u.strip()] or [
    "https://www.maxgaming.gg/de/kabellos/sora-v2-superlight-kabellos-gaming-maus-schwarz",
    "https://www.maxgaming.gg/de/kabellos/sora-v2-superlight-kabellos-gaming-maus-wei",
    "https://www.maxgaming.gg/de/kabellos/ninjutso-sora-v2-rosa",
]
CHECK_EVERY_SECONDS = int(os.environ.get("CHECK_EVERY_SECONDS", "300"))

# E-Mail (optional – später per Variables setzen)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "").strip()      # z.B. smtp.mail.me.com (Apple), smtp.office365.com (Outlook), mail.gmx.net
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USER = os.environ.get("EMAIL_USER", "").strip()
EMAIL_PASS = os.environ.get("EMAIL_PASS", "").strip()
EMAIL_TO   = os.environ.get("EMAIL_TO", "").strip()

# Discord (optional – später setzen)
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

# ---------- Erkennung / HTTP ----------
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

    # 3) Fallback: Gesamttext + Lagerbestand
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

def send_email(subject: str, body: str):
    if not (EMAIL_HOST and EMAIL_PORT and EMAIL_USER and EMAIL_PASS and EMAIL_TO):
        print("[INFO] E-Mail nicht konfiguriert – nur Konsole:", subject)
        return
    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_TO
    try:
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT, timeout=15) as server:
            server.ehlo(); server.starttls(); server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, [EMAIL_TO], msg.as_string())
    except Exception as e:
        print(f"[WARN] E-Mail-Versand fehlgeschlagen: {e}")

def send_discord(msg: str):
    url = DISCORD_WEBHOOK_URL
    if not url: return
    try:
        r = requests.post(url, json={"content": msg}, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"[WARN] Discord-Webhook fehlgeschlagen: {e}")

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def main():
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
                if url in already_alerted:
                    log(f"✅ Bereits gemeldet (noch in Stock): {url}")
                else:
                    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    subject = "Sora V2 bei MaxGaming: IN STOCK ✅"
                    body = f"IN STOCK gefunden!\n{url}\nZeit: {ts}"
                    log(f"✅ IN STOCK: {url}")
                    send_email(subject, body)
                    send_discord(f"{subject}\n{body}")
                    already_alerted.add(url)
            else:
                log(f"❌ Nicht verfügbar: {url}")

        time.sleep(max(30, CHECK_EVERY_SECONDS + random.randint(-15, 15)))

if __name__ == "__main__":
    main()
