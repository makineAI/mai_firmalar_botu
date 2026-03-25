from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import os, sys, time, json
import requests
from google import genai

# --- 1. YAPILANDIRMA (Doğruladığımız ID'ler) ---
AIRTABLE_TOKEN = os.environ.get('AIRTABLE_TOKEN')
AIRTABLE_BASE_ID = "appC4JNkqLfVCEcna"    
AIRTABLE_TABLE_NAME = "tbldmaqYiPXpH7IZ2" # Güncel Tablo ID'si
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

if not all([AIRTABLE_TOKEN, GEMINI_API_KEY]):
    print("❌ HATA: API Key veya Token bulunamadı!")
    sys.exit(1)

client_ai = genai.Client(api_key=GEMINI_API_KEY)
MODEL_NAME = 'gemini-2.5-flash'

def log(msg):
    print(f">>> {msg}")
    sys.stdout.flush()

# --- YARDIMCI FONKSİYON: Listeleri Metne Çevirir ---
def format_to_string(value):
    """
    AI'dan gelen veriyi kontrol eder. Eğer listeyse virgülle ayırıp metin yapar.
    Airtable'ın 'Long Text' sütunları için gereklidir.
    """
    if not value:
        return ""
    if isinstance(value, list):
        # [A, B, C] -> "A, B, C"
        return ", ".join(map(str, value))
    return str(value)

def ai_ile_analiz(html_content, web_url):
    soup = BeautifulSoup(html_content, 'html.parser')
    for element in soup(["script", "style", "nav", "footer", "header"]): 
        element.extract()
    text = soup.get_text(separator=' ', strip=True)[:10000]

    prompt = f"""
    Analiz et: {web_url}
    SADECE JSON:
    {{
      "unvan": "Firma Adı",
      "web": "{web_url}",
      "ozet": "Kurumsal özet",
      "tur": "Firma türü",
      "iletisim": "İletişim",
      "marka": "Temsil edilen markalar (Liste olarak)",
      "urun": "Ürünler (Liste olarak)",
      "analiz": "AI Analizi"
    }}
    """
    try:
        response = client_ai.models.generate_content(model=MODEL_NAME, contents=prompt)
        clean_json = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_json)
    except Exception as e:
        log(f"❌ AI Analiz Hatası: {e}")
        return None

def airtable_kaydet(data):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json"
    }
    
    # --- DÜZELTME BURADA YAPILDI ---
    # format_to_string fonksiyonunu kullanarak listeleri metne çeviriyoruz.
    fields = {
        "firma_unvan": format_to_string(data.get("unvan")),
        "web_site": format_to_string(data.get("web")),
        "kurumsal_hakkinda": format_to_string(data.get("ozet")),
        "firma_turu": format_to_string(data.get("tur")),
        "iletisim": format_to_string(data.get("iletisim")),
        "makine_markalari": format_to_string(data.get("marka")), # Kritik Düzeltme
        "makineler": format_to_string(data.get("urun")),         # Kritik Düzeltme
        "ai_firma_analizi": format_to_string(data.get("analiz"))
    }
    
    log(f"📡 Veri Airtable'a gönderiliyor...")
    res = requests.post(url, json={"fields": fields}, headers=headers)
    
    if res.status_code in [200, 201]:
        return f"✅ {data.get('unvan')} başarıyla kaydedildi!"
    else:
        # Hata mesajını daha detaylı görelim
        return f"❌ Airtable Hatası ({res.status_code}): {res.text}"

def firma_tara(target_url):
    log(f"🚀 Tarama Başlıyor: {target_url}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        page = context.new_page()
        
        try:
            # Sitenin yüklenmesi için 60 saniye süre tanı
            page.goto(target_url, wait_until="networkidle", timeout=60000)
            log("🔓 Site başarıyla açıldı!")
            
            # İçeriği AI'ya gönder
            ai_sonuc = ai_ile_analiz(page.content(), target_url)
            
            if ai_sonuc:
                log(airtable_kaydet(ai_sonuc))
            else:
                log("❌ AI analiz yapamadı.")
                
        except Exception as e:
            log(f"⚠️ Kritik Hata: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    firma_tara("https://tsmglobal.com.tr/")
