import httpx # Cloudscraper yerine httpx kullanıyoruz
from bs4 import BeautifulSoup
import os, sys, time, json, ssl
from urllib.parse import urljoin
from google import genai

# --- 1. SSL BYPASS (Kritik Çözüm) ---
def create_unsafe_client():
    # SSL ve Hostname kontrolünü tamamen devre dışı bırakan özel bir client
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    return httpx.Client(verify=False, follow_redirects=True, timeout=30.0)

# --- 2. YAPILANDIRMA ---
try:
    AIRTABLE_TOKEN = os.environ['AIRTABLE_TOKEN']
    AIRTABLE_BASE_ID = "appC4JNkqLfVCEcna" 
    AIRTABLE_TABLE_NAME = "tblC5TPs01HhtO9MA" 
    GEMINI_API_KEY = os.environ['GEMINI_API_KEY']
except KeyError as e:
    print(f"❌ HATA: GitHub Secrets eksik: {e}")
    sys.exit(1)

client_ai = genai.Client(api_key=GEMINI_API_KEY)
MODEL_NAME = 'gemini-2.5-flash'

def log(msg):
    print(f">>> {msg}")
    sys.stdout.flush()

def ai_ile_analiz(html_content, web_url):
    soup = BeautifulSoup(html_content, 'html.parser')
    for element in soup(["script", "style", "nav", "footer", "header"]): 
        element.extract()
    text = soup.get_text(separator=' ', strip=True)[:12000]

    prompt = f"Analiz et: {web_url}\nİçerik: {text}\nJSON formatında (firma_adi, web_site, kurumsal_hakkinda, firma_turu, iletisim, makine_markaları, makineler, ai_firma_analizi) sonuç döndür."
    
    try:
        response = client_ai.models.generate_content(model=MODEL_NAME, contents=prompt)
        clean_json = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_json)
    except Exception as e:
        log(f"❌ AI Hatası: {e}")
        return None

def airtable_kaydet(data):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_TOKEN}", "Content-Type": "application/json"}
    
    # Airtable'daki sütun isimlerinin tam olarak bunlar olduğundan emin ol!
    fields = {
        "firma_adi": data.get("firma_adi"),
        "web_site": data.get("web_site") or data.get("web_url"),
        "kurumsal_hakkinda": data.get("kurumsal_hakkinda"),
        "firma_turu": data.get("firma_turu"),
        "iletisim": data.get("iletisim"),
        "makine_markaları": data.get("makine_markaları"),
        "makineler": data.get("makineler"),
        "ai_firma_analizi": data.get("ai_firma_analizi")
    }
    
    with httpx.Client() as c:
        res = c.post(url, json={"fields": fields}, headers=headers)
        return f"✅ Kaydedildi." if res.status_code in [200, 201] else f"❌ Airtable Hatası: {res.text}"

def firma_tara(target_url):
    log(f"🚀 Tarama Başlıyor (HTTPX SSL-Bypass): {target_url}")
    
    try:
        with create_unsafe_client() as scraper:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
            r = scraper.get(target_url, headers=headers)
            r.raise_for_status()
            
            ai_sonuc = ai_ile_analiz(r.text, target_url)
            if ai_sonuc:
                ai_sonuc["web_site"] = target_url
                log(airtable_kaydet(ai_sonuc))
            else:
                log("❌ AI analiz yapamadı.")
    except Exception as e:
        log(f"⚠️ Kritik Hata: {e}")

if __name__ == "__main__":
    firma_tara("https://tsmglobal.com.tr/")
