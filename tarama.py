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
MODEL_NAME = 'gemini-1.5-flash'

def log(msg):
    print(f">>> {msg}", flush=True)

def temiz_metin_al(html, limit=5000):
    soup = BeautifulSoup(html, 'html.parser')
    for tags in soup(["nav", "footer", "header", "script", "style", "aside", "iframe", "noscript"]):
        tags.extract()
    text = soup.get_text(separator=' ', strip=True)
    text = re.sub(r'\s+', ' ', text)
    return text[:limit]

def link_bul(soup, keywords, base_url):
    for a in soup.find_all('a', href=True):
        text = a.get_text().lower()
        href = a['href'].lower()
        if any(kw in text for kw in keywords) or any(kw in href for kw in keywords):
            return urljoin(base_url, a['href'])
    return None

def uzman_analizi(ham_veriler, target_url):
    if not any(ham_veriler.values()): 
        return None
    
    prompt = f"Sen iş makineleri uzmanısın. Şu verilerden JSON formatında firma profili çıkar: {target_url}. Veriler: {str(ham_veriler)}"
    
    try:
        response = client_ai.models.generate_content(model=MODEL_NAME, contents=prompt)
        text = response.text.strip()
        # JSON temizleme işlemi (Hata riski en düşük yöntem)
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return None
    except Exception as e:
        log(f"❌ AI Hatası: {e}")
        return None

def airtable_kaydet(data, web_url):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_TOKEN}", "Content-Type": "application/json"}
    
    fields = {
        "firma_unvan": str(data.get("firma_unvan", "Bilinmiyor")),
        "web_site": web_url,
        "kurumsal_hakkinda": str(data.get("kurumsal_hakkinda", "Yok")),
        "firma_turu": str(data.get("firma_turu", "Yok")),
        "iletisim": str(data.get("iletisim", "Yok")),
        "makine_markalari": str(data.get("makine_markalari", "Yok")),
        "makineler": str(data.get("makineler", "Yok")),
        "ai_firma_analizi": str(data.get("ai_firma_analizi", "Analiz Yapılamadı"))
    }

    params = {"filterByFormula": f"{{web_site}} = '{web_url}'"}
    search = requests.get(url, headers=headers, params=params).json()

    if search.get("records"):
        rid = search["records"][0]["id"]
        requests.patch(f"{url}/{rid}", json={"fields": fields}, headers=headers)
        log(f"🔄 Güncellendi: {web_url}")
    else:
        requests.post(url, json={"fields": fields}, headers=headers)
        log(f"✅ Yeni Eklendi: {web_url}")

def siteyi_tara(target_url):
    log(f"🚀 İşlem Başlıyor: {target_url}")
    ham_veriler = {}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36")
        page = context.new_page()
        
        try:
            page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            soup_main = BeautifulSoup(page.content(), 'html.parser')
            
            links = {
                'hakkinda': link_bul(soup_main, ['kurumsal', 'hakkimizda', 'hakkinda'], target_url),
                'iletisim': link_bul(soup_main, ['iletisim', 'contact'], target_url),
                'urunler': link_bul(soup_main, ['urunler', 'markalarimiz', 'markalar'], target_url)
            }
            log(f"🔗 Linkler: {links}")

            for key, lurl in links.items():
                if lurl:
                    log(f"📄 {key} okunuyor...")
                    page.goto(lurl, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(3000)
                    ham_veriler[key] = temiz_metin_al(page.content())
            
            log("🧠 AI Analizine Geçiliyor...")
            analiz = uzman_analizi(ham_veriler, target_url)
            if analiz:
                airtable_kaydet(analiz, target_url)
            else:
                log("❌ Veri analiz edilemedi.")
                
        except Exception as e:
            log(f"⚠️ Hata: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    siteler = ["https://tsmglobal.com.tr/"]
    for site in siteler:
        siteyi_tara(site)
