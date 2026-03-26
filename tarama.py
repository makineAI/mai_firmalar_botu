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
# Not: Gemini 3 Flash için model ismini güncel tutuyoruz.
MODEL_NAME = 'gemini-2.0-flash' 

def log(msg):
    print(f">>> {msg}", flush=True)

def temiz_metin_al(html):
    soup = BeautifulSoup(html, 'html.parser')
    for tags in soup(["nav", "footer", "header", "script", "style", "aside", "iframe"]):
        tags.extract()
    return soup.get_text(separator=' ', strip=True)

def link_bul(soup, keywords, base_url):
    for a in soup.find_all('a', href=True):
        text = a.get_text().lower()
        href = a['href'].lower()
        if any(kw in text for kw in keywords) or any(kw in href for kw in keywords):
            found_url = urljoin(base_url, a['href'])
            return found_url
    return None

def uzman_analizi(ham_veriler, target_url):
    # Eğer ham veriler boşsa AI'yı hiç yormayalım
    if not any(ham_veriler.values()):
        log("⚠️ AI Analizi için yeterli metin toplanamadı!")
        return None

    prompt = f"""
    Sektör: İş Makineleri ve Endüstriyel Ekipman.
    Görevin: Aşağıdaki metinlerden firma profilini çıkar. 
    Kural: SADECE metindeki gerçekleri kullan. Bilgi yoksa "Bilinmiyor" yaz.

    SİTE: {target_url}
    İÇERİK: {str(ham_veriler)}

    JSON YANIT:
    {{
      "firma_unvan": "Şirket Adı",
      "kurumsal_hakkinda": "Profesyonel Özet",
      "firma_turu": "Tür",
      "iletisim": "Adres/Tel",
      "makine_markalari": "Markalar (Liste)",
      "makineler": "Ürün Grupları (Liste)",
      "ai_firma_analizi": "Kısa Analiz"
    }}
    """
    try:
        response = client_ai.models.generate_content(model=MODEL_NAME, contents=prompt)
        res_text = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(res_text)
    except Exception as e:
        log(f"❌ AI Hatası: {e}")
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
        "makine_markalari": ", ".join(data.get("makine_markalari", [])) if isinstance(data.get("makine_markalari"), list) else str(data.get("makine_markalari")),
        "makineler": ", ".join(data.get("makineler", [])) if isinstance(data.get("makineler"), list) else str(data.get("makineler")),
        "ai_firma_analizi": str(data.get("ai_firma_analizi"))
    }

    # Upsert (Güncelle veya Ekle)
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
        # Daha az dikkat çeken ayarlar
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0",
            viewport={'width': 1280, 'height': 720}
        )
        page = context.new_page()
        
        try:
            log("📡 Ana sayfaya bağlanılıyor...")
            # 'commit' kullanarak sayfa yanıt verdiği an içeriği yakalamaya çalışıyoruz
            page.goto(target_url, wait_until="commit", timeout=60000)
            page.wait_for_timeout(7000) # İçeriğin yüklenmesi için 7 saniye net bekleme
            
            html = page.content()
            if "verify you are human" in html.lower() or "cloudflare" in html.lower():
                log("⚠️ Güvenlik duvarına (Cloudflare) takıldık. İçerik sınırlı olabilir.")

            soup_main = BeautifulSoup(html, 'html.parser')
            
            # Linkleri tek tek loglayalım
            links = {
                'hakkinda': link_bul(soup_main, ['kurumsal', 'hakkimizda', 'hakkinda'], target_url),
                'iletisim': link_bul(soup_main, ['iletisim', 'contact'], target_url),
                'urunler': link_bul(soup_main, ['urunler', 'markalarimiz', 'markalar'], target_url)
            }
            
            log(f"🔗 Bulunan Linkler: {links}")

            for key, lurl in links.items():
                if lurl:
                    log(f"📄 {key} sayfası taranıyor: {lurl}")
                    try:
                        page.goto(lurl, wait_until="commit", timeout=30000)
                        page.wait_for_timeout(3000)
                        ham_veriler[key] = temiz_metin_al(page.content())
                    except:
                        log(f"❌ {key} sayfası açılırken hata oluştu.")
            
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
    # Test siteleri
    siteler = ["https://tsmglobal.com.tr/"]
    for site in siteler:
        siteyi_tara(site)
