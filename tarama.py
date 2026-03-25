from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import os, sys, time, json, requests, re
from google import genai

# --- 1. YAPILANDIRMA ---
AIRTABLE_TOKEN = os.environ.get('AIRTABLE_TOKEN')
AIRTABLE_BASE_ID = "appC4JNkqLfVCEcna"
AIRTABLE_TABLE_NAME = "tbldmaqYiPXpH7IZ2"
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

client_ai = genai.Client(api_key=GEMINI_API_KEY)
MODEL_NAME = 'gemini-2.5-flash'

def log(msg):
    print(f">>> {msg}")
    sys.stdout.flush()

def temiz_metin_al(html):
    soup = BeautifulSoup(html, 'html.parser')
    for tags in soup(["nav", "footer", "header", "script", "style", "aside", "form", "iframe"]):
        tags.extract()
    return soup.get_text(separator=' ', strip=True)[:10000]

def rafine_analiz(context_data, target_url):
    prompt = f"""
    GÖREV: Aşağıdaki metinden firmaya ait bilgileri ayıkla. 
    KURAL: Sadece gerçek bilgileri yaz. Bilgi yoksa "Yok" yaz.
    SİTE: {target_url}
    METİN: {context_data}

    JSON (SADECE JSON):
    {{
      "unvan": "Şirket Adı",
      "hakkinda": "Özet",
      "iletisim": "Tel/Adres",
      "markalar": "Markalar",
      "urunler": "Makineler",
      "tur": "Distribütör/Üretici"
    }}
    """
    try:
        response = client_ai.models.generate_content(model=MODEL_NAME, contents=prompt)
        res_text = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(res_text)
    except: return None

def firma_tara(target_url):
    log(f"🚀 {target_url} taranıyor (Hızlı Mod)...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        page = context.new_page()

        # --- HIZLANDIRMA: Gereksiz kaynakları engelle ---
        page.route("**/*.{png,jpg,jpeg,gif,svg,css,woff,pdf}", lambda route: route.abort())
        
        try:
            # networkidle yerine domcontentloaded kullanarak timeoutu önle
            page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3000) # Sadece 3 saniye bekle
            
            main_content = temiz_metin_al(page.content())
            
            # AI Analizi
            data = rafine_analiz(main_content, target_url)
            
            if data:
                airtable_kaydet(data, target_url)
            else:
                log("❌ Veri işlenemedi.")

        except Exception as e:
            log(f"⚠️ Zaman aşımı veya Hata: {e}. Kısmi veri deneniyor...")
            # Hata olsa bile o ana kadar yüklenen içeriği almayı dene
            try:
                data = rafine_analiz(temiz_metin_al(page.content()), target_url)
                if data: airtable_kaydet(data, target_url)
            except: pass
        finally:
            browser.close()

def airtable_kaydet(data, web_url):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_TOKEN}", "Content-Type": "application/json"}
    
    fields = {
        "firma_unvan": data.get("unvan"),
        "web_site": web_url,
        "kurumsal_hakkinda": data.get("hakkinda"),
        "firma_turu": data.get("tur"),
        "iletisim": data.get("iletisim"),
        "makine_markalari": data.get("markalar"),
        "makineler": data.get("urunler")
    }
    
    res = requests.post(url, json={"fields": fields}, headers=headers)
    log(f"📡 Airtable Durumu: {res.status_code}")

if __name__ == "__main__":
    firma_tara("https://tsmglobal.com.tr/")
