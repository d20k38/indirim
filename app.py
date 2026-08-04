# Basit Trendyol/Hepsiburada/Amazon/n11 fiyat takipçi (Flask)
import os
import re
import sqlite3
import threading
import time
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from flask import Flask, g, jsonify, redirect, render_template, request, url_for

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")  # Telegram bot token
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")  # chat id to send messages
CHECK_INTERVAL_SECONDS = int(os.environ.get("CHECK_INTERVAL_SECONDS", 3600))  # default 3600 = 1 saat

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
    db.commit()
    db.close()


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


# --- Site parsers (simple, may need tweaks over time) ---
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


def get_page(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.text
    except Exception:
        return None


def price_trendyol(html):
    soup = BeautifulSoup(html, "html.parser")
    # Trendyol değişken ama bu denemeler iş görürse...
    selectors = [
        ".prc-slg .prc-slg-w",  # önceki / yeni sınıflar
        ".prc-dsc",  # fallback
        ".price"
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            p = parse_price_from_text(el.get_text())
            if p:
                return p
    # fallback: search whole page
    return parse_price_from_text(soup.get_text())


def price_hepsiburada(html):
    soup = BeautifulSoup(html, "html.parser")
    selectors = [
        ".price-container .current-price",
        ".product-price",
        "#offering-price"
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            p = parse_price_from_text(el.get_text())
            if p:
                return p
    return parse_price_from_text(soup.get_text())


def price_n11(html):
    soup = BeautifulSoup(html, "html.parser")
    selectors = [
        ".proDetail .newPrice",
        ".newPrice",
        ".price"
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
        ".a-price .a-offscreen"
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            p = parse_price_from_text(el.get_text())
            if p:
                return p
    return parse_price_from_text(soup.get_text())


SITE_PARSERS = {
    "trendyol": price_trendyol,
    "hepsiburada": price_hepsiburada,
    "n11": price_n11,
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


# --- Check logic ---
def check_product(row):
    url = row["url"]
    site = row["site"] or detect_site(url)
    html = get_page(url)
    if not html:
        return None, "404"
    parser = SITE_PARSERS.get(site)
    if not parser:
        # fallback generic parse
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
    for r in rows:
        prod = dict(zip([d[0] for d in c.description], r))
        price, title = check_product(prod)
        now = datetime.utcnow().isoformat()
        if price is not None:
            # compare and update
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


# --- Routes ---
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
    # insert
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
