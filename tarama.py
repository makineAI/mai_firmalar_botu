import os, sys, time, json, requests, re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from google import genai

# --- YAPILANDIRMA ---
AIRTABLE_TOKEN = os.environ.get('AIRTABLE_TOKEN')
AIRTABLE_BASE_ID = os.environ.get('AIRTABLE_BASE_ID', "appC4JNkqLfVCEcna")
AIRTABLE_TABLE_NAME = os.environ.get('AIRTABLE_TABLE_NAME', "tbldmaqYiPXpH7IZ2")
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

client_ai = genai.Client(api_key=GEMINI_API_KEY)
# Ücretsiz tier için en yüksek kotaya sahip ve en stabil model
MODEL_NAME = 'gemini-1.5-flash' 

def log(msg):
    print(f">>> {msg}", flush=True)

def temiz_metin_al(html, limit=4000):
    """HTML'i temizler ve AI'yı boğmamak için karakter sınırı koyar."""
    soup = BeautifulSoup(html, 'html.parser')
    for tags in soup(["nav", "footer", "header", "script", "style", "aside", "iframe", "noscript"]):
        tags.extract()
    text = soup.get_text(separator=' ', strip=True)
    # Birden fazla boşluğu tek boşluğa indirge (Token tasarrufu)
    text = re.sub(r'\s+', ' ', text)
    return text[:limit] # AI kotasını patlatmamak için kesiyoruz

def link_bul(soup, keywords, base_url):
    for a in soup.find_all('a', href=True):
        text = a.get_text().lower()
        href = a['href'].lower()
        if any(kw in text for kw in keywords) or any(kw in href for kw in keywords):
            return urljoin(base_url, a['href'])
    return None

def uzman_analizi(ham_veriler, target_url):
    if not any(ham_veriler.values()):
        log("⚠️ AI Analizi için metin bulunamadı.")
        return None

    prompt = f"""
    Sektör: İş Makineleri, Endüstriyel Ekipman ve Ticari Araçlar.
    Görevin: Aşağıdaki metinlerden firma profilini çıkar. 
    Kural: SADECE metindeki gerçekleri kullan. Bilgi yoksa "Bilinmiyor" yaz.

    SİTE: {target_url}
    İÇERİK (Hakkında): {ham_veriler.get('hakkinda', '')}
    İÇERİK (İletişim): {ham_veriler.get('iletisim', '')}
    İÇERİK (Ürünler): {ham_veriler.get('urunler', '')}

    SADECE AŞAĞIDAKİ JSON FORMATINDA YANIT VER:
    {{
      "firma_unvan": "Şirket Adı",
      "kurumsal_hakkinda": "Profesyonel Özet",
      "firma_turu": "Tür",
      "iletisim": "Adres/Tel",
      "makine_markalari": "Markalar (Virgülle ayrılmış liste)",
      "makineler": "Ürün Grupları (Virgülle ayrılmış liste)",
      "ai_firma_analizi": "Kısa Analiz"
    }}
    """
    
    # 429 Kota Hatasına Karşı Hata Yakalama ve Yeniden Deneme (Retry)
    try:
        response = client_ai.models.generate_content(model=MODEL_NAME, contents=prompt)
        res_text = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(res_text)
    except Exception as e:
        hata_mesaji = str(e)
        if "429" in hata_mesaji or "RESOURCE_EXHAUSTED" in hata_mesaji:
            log("⏳ API Limiti doldu (429)! 25 saniye beklenip tekrar deneniyor...")
            time.sleep(25)
            try:
                # İkinci deneme
                response = client_ai.models.generate_content(model=MODEL_NAME, contents=prompt)
                res_text = response.text.replace('```json', '').replace('```', '').strip()
                return json.loads(res_text)
            except Exception as e2:
                log(f"❌ İkinci denemede de hata alındı: {e2}")
                return None
        else:
            log(f"❌ Beklenmeyen AI Hatası: {e}")
            return None

def airtable_kaydet(data, web_url):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_TOKEN}", "Content-Type": "application/json"}
    
    fields = {
        "firma_unvan": str(data.get("firma_unvan")),
        "web_site": web_url,
        "kurumsal_hakkinda": str(data.get("kurumsal_hakkinda")),
        "firma_turu": str(data.get("firma_turu")),
        "iletisim": str(data.get("iletisim")),
        "makine_markalari": str(data.get("makine_markalari")),
        "makineler": str(data.get("makineler")),
        "ai_firma_analizi": str(data.get("ai_firma_analizi"))
    }

    params = {"filterByFormula": f"{{web_site}} = '{web_url}'"}
    search = requests.get(url, headers=headers, params=params).json()

    if search.get("records"):
        rid = search["records"][0]["id"]
        requests.patch(f"{url}/{rid}", json={"fields": fields}, headers=headers)
        log(f"🔄 Airtable Güncellendi: {web_url}")
    else:
        requests.post(url, json={"fields": fields}, headers=headers)
        log(f"✅ Airtable'a Yeni Kayıt: {web_url}")

def siteyi_tara(target_url):
    log(f"🚀 Başlatılıyor: {target_url}")
    ham_veriler = {}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()
        
        try:
            log("📡 Ana sayfaya bağlanılıyor...")
            page.goto(target_url, wait_until="commit", timeout=60000)
            page.wait_for_timeout(5000) 
            
            html = page.content()
            soup_main = BeautifulSoup(html, 'html.parser')
            
            links = {
                'hakkinda': link_bul(soup_main, ['kurumsal', 'hakkimizda', 'hakkinda'], target_url),
                'iletisim': link_bul(soup_main, ['iletisim', 'contact'], target_url),
                'urunler': link_bul(soup_main, ['urunler', 'markalarimiz', 'markalar'], target_url)
            }
            
            log(f"🔗 Bulunan Linkler: {links}")

            # Her sayfanın verisini karakter limitli olarak çekiyoruz
            for key, lurl in links.items():
                if lurl:
                    log(f"📄 {key} sayfası okunuyor: {lurl}")
                    try:
                        page.goto(lurl, wait_until="commit", timeout=30000)
                        page.wait_for_timeout(3000)
                        # Her sayfa için maksimum 4000 karakter (yaklaşık 800 token) alıyoruz.
                        ham_veriler[key] = temiz_metin_al(page.content(), limit=4000)
                    except:
                        log(f"❌ {key} sayfası okunamadı.")
            
            log("🧠 Veriler AI Analizine gönderiliyor...")
            analiz = uzman_analizi(ham_veriler, target_url)
            
            if analiz:
                airtable_kaydet(analiz, target_url)
            else:
                log("❌ Analiz sonucu boş döndü.")
                
        except Exception as e:
            log(f"⚠️ Kritik Hata: {e}")
        finally:
            browser.close()
            log("🏁 Tarayıcı kapatıldı.")

if __name__ == "__main__":
    siteler = ["https://tsmglobal.com.tr/"]
    for site in siteler:
        siteyi_tara(site)
        time.sleep(5) # İki site arası API'yi dinlendirmek için 5 sn bekleme
