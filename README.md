Indirim Bulucu
===============

Kısa açıklama
- URL bazlı fiyat takipçisi: Trendyol / Hepsiburada / Amazon / n11
- Flask backend, SQLite veri tabanı, Telegram bildirimleri
- Saatlik tarama (varsayılan). Hedef fiyata ulaştığında Telegram bildirimi gönderir.

Hızlı başlatma (yerel)
1. Python 3.10+ kurulu olsun.
2. Sanal ortam oluştur ve aktifleştir:
   python -m venv venv
   source venv/bin/activate   (Windows PowerShell: venv\\Scripts\\Activate.ps1)
3. Gerekli paketleri yükle:
   pip install -r requirements.txt
4. Ortam değişkenlerini ayarla:
   export TELEGRAM_TOKEN="bot_token"
   export TELEGRAM_CHAT_ID="chat_id"
   (Windows: set veya PowerShell uygun komutları kullan)
5. Uygulamayı çalıştır:
   python app.py
6. Tarayıcıda http://localhost:5000 aç.

Replit üzerinde çalıştırma
- Replit hesabı oluştur, repo dosyalarını ekle veya import et.
- Replit Secrets / Environment bölümüne TELEGRAM_TOKEN ve TELEGRAM_CHAT_ID ekle.
- Run tuşuna bas.

Telegram token ve chat_id alma
1. Telegram'da @BotFather ile /newbot komutu ile bot oluşturup token al.
2. Botu başlatıp (kendine /start gönder) şu URL ile getUpdates çağır:
   https://api.telegram.org/bot<TOKEN>/getUpdates
   Dönen JSON içinde chat.id değerini alıp TELEGRAM_CHAT_ID olarak kullan.

Uyarılar
- Amazon ve bazı sayfalar dinamik/korumalı olabilir; fiyat çekilemeyebilir. Gerekirse headless browser (Playwright) eklenebilir.
- Çok sık tarama (dakika bazlı) IP engellemelere yol açabilir. Saatlik tarama makul bir varsayılandır.
- Kişisel/deneme amaçlı kullanım genelde sorun olmaz; ticari/yoğun kullanımda sitelerin kullanım koşullarını kontrol edin.

İleri adımlar (isteğe bağlı)
- Playwright destekli scraper (Amazon için)
- Dockerfile veya Railway/Heroku deployment örneği
- GitHub Actions ile otomatik deploy


Trigger: workflow dispatch test — update by Copilot on 2026-08-04
