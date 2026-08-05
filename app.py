# Basit Trendyol/Hepsiburada/Amazon/n11 fiyat takipçi (Flask)
import os
import re
import sqlite3
import threading
import time
from datetime import datetime
from urllib.parse import urlparse, quote_plus

import requests
from bs4 import BeautifulSoup
from flask import Flask, g, jsonify, redirect, render_template, request, url_for

from rapidfuzz import fuzz

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")  # Telegram bot token
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")  # chat id to send messages
CHECK_INTERVAL_SECONDS = int(os.environ.get("CHECK_INTERVAL_SECONDS", 3600))  # default 3600 = 1 saat
SCRAPINGBEE_KEY = os.environ.get("SCRAPINGBEE_KEY")  # optional scraping API key

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/115.0 Safari/537.36"
}

app = Flask(__name__, static_folder="static", template_folder="templates")
DB_PATH = "data.db"


# --- DB helpers ---
def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db


def init_db():
    db = sqlite3.connect(DB_PATH)
    c = db.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS products (
           id INTEGER PRIMARY KEY,
           url TEXT NOT NULL,
           site TEXT,
           title TEXT,
           last_price REAL,
           desired_price REAL,
           last_checked TEXT
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS listings (
           id INTEGER PRIMARY KEY,
           url TEXT NOT NULL UNIQUE,
           site TEXT,
           name TEXT,
           last_scanned TEXT
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS deals (
           id INTEGER PRIMARY KEY,
           listing_id INTEGER,
           product_url TEXT,
           title TEXT,
           old_price REAL,
           new_price REAL,
           discount_pct REAL,
           first_seen TEXT,
           last_seen TEXT,
           UNIQUE(listing_id, product_url),
           FOREIGN KEY(listing_id) REFERENCES listings(id)
        )"""
    )
    # table for scraped offers from aggregator sites / telegram
    c.execute(
        """CREATE TABLE IF NOT EXISTS scraped_offers (
           id INTEGER PRIMARY KEY,
           site TEXT,
           url TEXT,
           title TEXT,
           price REAL,
           first_seen TEXT,
           last_seen TEXT,
           notified INTEGER DEFAULT 0,
           UNIQUE(site, url)
        )"""
    )
    db.commit()
    db.close()


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


# --- Fetching (ScrapingBee optional) ---
def get_page(url): # If SCRAPINGBEE_KEY present, use it to render JS and avoid blocks key = os.getenv("SCRAPINGBEE_KEY") if key: api_url = f"https://app.scrapingbee.com/api/v1?api_key={key}&url={quote_plus(url)}&render_js=true&premium_proxy=true" try: r = requests.get(api_url, headers={"Accept": "text/html"}, timeout=30) print("ScrapingBee status:", r.status_code) if r.status_code == 200 and r.text: return r.text else: print("ScrapingBee returned non-200 or empty body; falling back to direct fetch") except Exception as e: print("ScrapingBee fetch failed:", e) # fallthrough to direct # Direct fetch fallback try: r = requests.get(url, headers=HEADERS, timeout=15) print("Direct fetch status:", r.status_code) r.raise_for_status() return r.text except Exception as e: print("Direct fetch failed:", e) return None


# --- Generic price parsing helpers ---
def parse_price_from_text(text):
    if not text:
        return None
    # Find first price-looking number like 1.234,56 or 1234.56 or 1.234
    m = re.search(r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)", text.replace("\xa0", " "))
    if not m:
        return None
    s = m.group(1)
    s = s.replace(".", "").replace(",", ".")  # turn "1.234,56" -> "1234.56"
    try:
        return float(s)
    except:
        return None


# --- Site parsers (examples) ---
def price_trendyol(html):
    soup = BeautifulSoup(html, "html.parser")
    selectors = [
        ".prc-slg .prc-slg-w",
        ".prc-dsc",
        ".price",
        "span[data-test=price]",
        ".prc-slg"
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            p = parse_price_from_text(el.get_text())
            if p:
                return p
    return parse_price_from_text(soup.get_text())


def price_amazon(html):
    soup = BeautifulSoup(html, "html.parser")
    selectors = [
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        ".a-price .a-offscreen",
        "span[data-a-color='price'] .a-offscreen",
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            p = parse_price_from_text(el.get_text())
            if p:
                return p
    # fallback: look for TL symbol near numbers
    txt = soup.get_text()
    m = re.search(r"([0-9\.,]+)\s*(?:₺|TL|tl)", txt)
    if m:
        s = m.group(1).replace('.', '').replace(',', '.')
        try:
            return float(s)
        except:
            pass
    return parse_price_from_text(txt)


SITE_PARSERS = {
    "trendyol": price_trendyol,
    "hepsiburada": price_trendyol,  # reuse generic for now
    "n11": price_trendyol,
    "amazon": price_amazon
}


def detect_site(url):
    host = urlparse(url).netloc.lower()
    if "trendyol" in host:
        return "trendyol"
    if "hepsiburada" in host:
        return "hepsiburada"
    if "n11" in host:
        return "n11"
    if "amazon" in host:
        return "amazon"
    if "akakce" in host:
        return "akakce"
    if "cimri" in host:
        return "cimri"
    return None


# --- Telegram ---
def send_telegram(text):
    token = TELEGRAM_TOKEN
    chat_id = TELEGRAM_CHAT_ID
    if not token or not chat_id:
        print("Telegram token/chat id missing, skip send")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        print("Telegram send failed:", e)


# --- Check logic (products) ---
def check_product(row):
    url = row["url"]
    site = row["site"] or detect_site(url)
    html = get_page(url)
    if not html:
        return None, "404"
    parser = SITE_PARSERS.get(site)
    if not parser:
        price = parse_price_from_text(BeautifulSoup(html, "html.parser").get_text())
    else:
        price = parser(html)
    title = None
    try:
        soup = BeautifulSoup(html, "html.parser")
        if soup.title:
            title = soup.title.get_text().strip()
    except:
        pass
    return price, title


def check_all():
    print("Starting check_all:", datetime.utcnow().isoformat())
    db = sqlite3.connect(DB_PATH)
    c = db.cursor()
    c.execute("SELECT * FROM products")
    rows = c.fetchall()
    col_names = [d[0] for d in c.description] if c.description else []
    for r in rows:
        prod = dict(zip(col_names, r))
        price, title = check_product(prod)
        now = datetime.utcnow().isoformat()
        if price is not None:
            prev = prod.get("last_price")
            desired = prod.get("desired_price")
            c.execute(
                "UPDATE products SET last_price = ?, title = ?, last_checked = ? WHERE id = ?",
                (price, title or prod.get("title"), now, prod["id"])
            )
            db.commit()
            if prev is None or price != prev:
                msg = f"Fiyat güncellendi:\n{prod['url']}\n{title or ''}\nYeni fiyat: {price} TL\nÖnceki: {prev}"
                print(msg)
                send_telegram(msg)
            if desired and price <= desired:
                msg = f"Fiyat hedefe ulaştı! ({price} ≤ {desired})\n{prod['url']}\n{title or ''}"
                send_telegram(msg)
        else:
            print("Fiyat alınamadı:", prod["url"])
    db.close()


def scheduler_thread():
    while True:
        try:
            check_all()
        except Exception as e:
            print("Hata during check_all:", e)
        time.sleep(CHECK_INTERVAL_SECONDS)


# --- Aggregator scrapers: akakce & cimri (basic implementations) ---

def extract_price_from_element(el):
    try:
        return parse_price_from_text(el.get_text())
    except:
        return None


def get_akakce_deals(listing_url="https://www.akakce.com/indirim/"):
    html = get_page(listing_url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    offers = []
    # Generic approach: find links that contain product keywords and nearby price-like text
    for a in soup.select("a[href]"):
        href = a.get("href")
        text = a.get_text(" ", strip=True)
        if not text or len(text) < 5:
            continue
        # try to find price in parent or sibling
        parent = a.parent
        price = None
        for candidate in [a, parent] + parent.find_all(recursive=False):
            if candidate and candidate.get_text():
                p = parse_price_from_text(candidate.get_text())
                if p:
                    price = p
                    break
        url = href
        if url and url.startswith("/"):
            url = "https://www.akakce.com" + url
        if price and url:
            offers.append({"site": "akakce", "url": url, "title": text[:180], "price": price})
    # dedupe by url
    seen = set()
    dedup = []
    for o in offers:
        if o["url"] in seen:
            continue
        seen.add(o["url"])
        dedup.append(o)
    return dedup


def get_cimri_deals(listing_url="https://www.cimri.com/indirimler/"):
    html = get_page(listing_url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    offers = []
    for a in soup.select("a[href]"):
        href = a.get("href")
        text = a.get_text(" ", strip=True)
        if not text or len(text) < 5:
            continue
        parent = a.parent
        price = None
        for candidate in [a, parent] + parent.find_all(recursive=False):
            if candidate and candidate.get_text():
                p = parse_price_from_text(candidate.get_text())
                if p:
                    price = p
                    break
        url = href
        if url and url.startswith("/"):
            url = "https://www.cimri.com" + url
        if price and url:
            offers.append({"site": "cimri", "url": url, "title": text[:180], "price": price})
    seen = set()
    dedup = []
    for o in offers:
        if o["url"] in seen:
            continue
        seen.add(o["url"])
        dedup.append(o)
    return dedup


# --- New robust akakce parser for fark-atan-fiyatlar ---
_product_href_keywords = ["/urun", "/product", "-p-", "/fiyat", "/kampanya", "/kategori"]


def _looks_like_product_href(href):
    if not href:
        return False
    lower = href.lower()
    for k in _product_href_keywords:
        if k in lower:
            return True
    # if it's an absolute akakce link or relative link, accept as possible product
    if "akakce.com" in lower or href.startswith("/"):
        return True
    return False


def _extract_price_from_text(text):
    if not text:
        return None
    m = re.search(r"([0-9\.,]+)\s*(?:₺|TL|tl)", text)
    if not m:
        m = re.search(r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)", text)
    if not m:
        return None
    s = m.group(1).replace('.', '').replace(',', '.')
    try:
        return float(s)
    except:
        return None


def get_akakce_deals_farkatan(listing_url="https://www.akakce.com/fark-atan-fiyatlar/"):
    html = get_page(listing_url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    offers = []
    seen = set()

    # find price-like text nodes
    price_nodes = soup.find_all(text=re.compile(r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)"))
    for txt_node in price_nodes:
        text = txt_node.strip()
        price = _extract_price_from_text(text)
        if price is None:
            continue
        parent = txt_node.parent
        # prefer anchors in parent subtree
        a = None
        if parent.name == "a" and parent.get("href"):
            a = parent
        else:
            cur = parent
            for _ in range(6):
                if cur is None:
                    break
                a = cur.select_one("a[href]")
                if a:
                    break
                cur = cur.parent
        if not a:
            for sib in parent.find_next_siblings(limit=4):
                a = sib.select_one("a[href]")
                if a:
                    break
        if not a:
            continue
        href = a.get("href")
        if not href:
            continue
        if href.startswith("/"):
            parsed = urlparse(listing_url)
            href = f"{parsed.scheme}://{parsed.netloc}{href}"
        if not _looks_like_product_href(href):
            txt_anchor = a.get_text(" ", strip=True)
            if len(txt_anchor) < 4 or not re.search(r"[A-Za-z0-9İĞÜŞÖÇığüşöç]", txt_anchor):
                continue
        title = a.get_text(" ", strip=True) or parent.get_text(" ", strip=True)
        if href in seen:
            continue
        seen.add(href)
        offers.append({"site": "akakce", "url": href, "title": title[:240], "price": price})
    return offers


# --- Process scraped offers: store and notify if new/cheap ---

def store_or_update_offer(o):
    db = sqlite3.connect(DB_PATH)
    c = db.cursor()
    now = datetime.utcnow().isoformat()
    try:
        c.execute("INSERT INTO scraped_offers (site, url, title, price, first_seen, last_seen, notified) VALUES (?, ?, ?, ?, ?, ?, 0)",
                  (o["site"], o["url"], o.get("title"), o["price"], now, now))
        db.commit()
        inserted = True
    except sqlite3.IntegrityError:
        # update last_seen and price if changed
        c.execute("SELECT price, notified FROM scraped_offers WHERE site = ? AND url = ?", (o["site"], o["url"]))
        row = c.fetchone()
        prev_price = row[0] if row else None
        notified = row[1] if row else 0
        if prev_price != o["price"]:
            c.execute("UPDATE scraped_offers SET price = ?, last_seen = ?, notified = 0 WHERE site = ? AND url = ?",
                      (o["price"], now, o["site"], o["url"]))
            db.commit()
        inserted = False
    db.close()
    return inserted


def find_similar_product_prices(title):
    # simple title normalization + fuzzy matching against products table
    db = sqlite3.connect(DB_PATH)
    c = db.cursor()
    c.execute("SELECT id, title, last_price, url, site FROM products WHERE last_price IS NOT NULL AND title IS NOT NULL")
    rows = c.fetchall()
    db.close()
    norm = normalize_title(title)
    matches = []
    for r in rows:
        pid, ptitle, pprice, purl, psite = r
        score = fuzz.token_sort_ratio(norm, normalize_title(ptitle)) if ptitle else 0
        if score >= 75:
            matches.append({"id": pid, "title": ptitle, "price": pprice, "url": purl, "site": psite, "score": score})
    return matches


def process_scraped_offers(offers, pct_threshold=100.0, absolute_threshold=50.0):
    # Store offers and notify if they seem like big bargains compared to known product prices
    notified = []
    for o in offers:
        inserted = store_or_update_offer(o)
        # check against known products
        sims = find_similar_product_prices(o.get("title") or "")
        other_prices = [s["price"] for s in sims if s.get("price")]
        is_bargain = False
        reason = None
        if other_prices:
            min_other = min(other_prices)
            if min_other and min_other > 0:
                pct = (min_other - o["price"]) / min_other * 100.0
                if pct >= pct_threshold:
                    is_bargain = True
                    reason = f"%{round(pct,1)} daha ucuz (ortalama benzeri: {min_other} TL)"
        else:
            # if no comparable product known, consider absolute price threshold
            if o["price"] <= absolute_threshold:
                is_bargain = True
                reason = f"Fiyat ≤ {absolute_threshold} TL"
        if is_bargain:
            msg = f"Fırsat: {o.get('title')}\n{o.get('url')}\nFiyat: {o.get('price')} TL\n{reason}"
            send_telegram(msg)
            notified.append(o)
            # mark notified
            db = sqlite3.connect(DB_PATH)
            c = db.cursor()
            c.execute("UPDATE scraped_offers SET notified = 1 WHERE site = ? AND url = ?", (o["site"], o["url"]))
            db.commit()
            db.close()
    return notified


# --- Combined scan function ---
def scan_aggregators_and_process():
    offers = []
    try:
        offers.extend(get_akakce_deals())
    except Exception as e:
        print("akakce scan error:", e)
    try:
        offers.extend(get_cimri_deals())
    except Exception as e:
        print("cimri scan error:", e)
    print(f"Found {len(offers)} offers from aggregators")
    return process_scraped_offers(offers)


# --- Price discrepancy detection (cross-site) ---
def normalize_title(t):
    if not t:
        return ""
    s = t.lower()
    s = re.sub(r"[^0-9a-zığüşöçİĞÜŞÖÇ\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def load_products_with_prices():
    db = sqlite3.connect(DB_PATH)
    c = db.cursor()
    c.execute("SELECT id, url, site, title, last_price FROM products WHERE last_price IS NOT NULL AND title IS NOT NULL")
    rows = [dict(zip([d[0] for d in c.description], r)) for r in c.fetchall()]
    db.close()
    for r in rows:
        r["norm_title"] = normalize_title(r.get("title") or "")
    return rows


def find_discrepancies(pct_threshold=100.0, sim_threshold=80):
    prods = load_products_with_prices()
    n = len(prods)
    results = []
    for i in range(n):
        a = prods[i]
        for j in range(i + 1, n):
            b = prods[j]
            if a["site"] == b["site"]:
                continue
            sim = fuzz.token_sort_ratio(a["norm_title"], b["norm_title"]) if a["norm_title"] and b["norm_title"] else 0
            if sim < sim_threshold:
                continue
            pa = a["last_price"]
            pb = b["last_price"]
            if pa is None or pb is None or pa <= 0 or pb <= 0:
                continue
            bigger = max(pa, pb)
            smaller = min(pa, pb)
            pct_diff = (bigger - smaller) / smaller * 100.0
            if pct_diff >= pct_threshold:
                cheaper = a if a["last_price"] < b["last_price"] else b
                expensive = b if cheaper is a else a
                results.append({
                    "a_id": a["id"], "a_url": a["url"], "a_site": a["site"], "a_title": a["title"], "a_price": pa,
                    "b_id": b["id"], "b_url": b["url"], "b_site": b["site"], "b_title": b["title"], "b_price": pb,
                    "similarity": sim,
                    "pct_diff": round(pct_diff, 2),
                    "cheaper_site": cheaper["site"],
                    "cheaper_price": cheaper["last_price"],
                })
    results.sort(key=lambda x: x["pct_diff"], reverse=True)
    return results


# --- Routes ---
@app.route("/admin/discrepancies", methods=["GET"])
def admin_discrepancies():
    pct = float(request.args.get("pct", 100.0))
    sim = int(request.args.get("sim", 80))
    res = find_discrepancies(pct_threshold=pct, sim_threshold=sim)
    return jsonify({"count": len(res), "results": res})


@app.route("/admin/scan_sources", methods=["POST", "GET"])
def admin_scan_sources():
    # run scan in background thread to avoid blocking
    t = threading.Thread(target=scan_aggregators_and_process, daemon=True)
    t.start()
    return jsonify({"status": "started"})


@app.route("/webhook/telegram", methods=["POST"])
def webhook_telegram():
    # Accept POST from Telethon listener (or other) with JSON {"text": "...", "channel": "..."}
    data = request.get_json() or {}
    text = data.get("text") or ""
    channel = data.get("channel")
    urls = re.findall(r'https?://\S+', text)
    offers = []
    # try to extract price in message text
    price = parse_price_from_text(text)
    title = text[:200]
    for u in urls:
        offers.append({"site": channel or "telegram", "url": u, "title": title, "price": price})
    if offers:
        notified = process_scraped_offers(offers)
        return jsonify({"notified": len(notified)})
    return jsonify({"processed_urls": len(urls)})


@app.route("/", methods=["GET"])
def index():
    db = get_db()
    c = db.cursor()
    c.execute("SELECT * FROM products")
    rows = c.fetchall()
    return render_template("index.html", products=rows)


@app.route("/add", methods=["POST"])
def add():
    url = request.form.get("url", "").strip()
    desired = request.form.get("desired")
    try:
        desired_price = float(desired) if desired else None
    except:
        desired_price = None
    if not url:
        return redirect(url_for("index"))
    site = detect_site(url)
    db = get_db()
    c = db.cursor()
    c.execute("INSERT INTO products (url, site, desired_price) VALUES (?, ?, ?)", (url, site, desired_price))
    db.commit()
    return redirect(url_for("index"))


@app.route("/delete/<int:id>", methods=["POST"])
def delete(id):
    db = get_db()
    c = db.cursor()
    c.execute("DELETE FROM products WHERE id = ?", (id,))
    db.commit()
    return redirect(url_for("index"))


if __name__ == "__main__":
    init_db()
    # start scheduler
    t = threading.Thread(target=scheduler_thread, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
