import requests
from bs4 import BeautifulSoup
import os, sys, time, urllib3, json
from urllib.parse import urljoin
from google import genai # Yeni 2026 SDK'sı

# SSL uyarılarını kapat
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- YAPILANDIRMA ---
try:
    AIRTABLE_TOKEN = os.environ['AIRTABLE_TOKEN']
    AIRTABLE_BASE_ID = os.environ['AIRTABLE_BASE_ID']
    GEMINI_API_KEY = os.environ['GEMINI_API_KEY']
    AIRTABLE_TABLE_NAME = "mai_firmalar"
except KeyError as e:
    print(f"❌ HATA: GitHub Secrets eksik: {e}")
    sys.exit(1)

# Yeni Gemini Client Kurulumu (2026 Standartı)
client = genai.Client(api_key=GEMINI_API_KEY)
MODEL_NAME = 'gemini-2.5-flash' # Güncel ve güçlü model

def log(msg):
    print(f">>> {msg}")
    sys.stdout.flush()

def logo_bul(soup, base_url):
    for img in soup.find_all('img', src=True):
        src = img['src'].lower()
        alt = img.get('alt', '').lower()
        if any(x in src or x in alt for x in ['logo', 'brand', 'header']):
            return urljoin(base_url, img['src'])
    return ""

def ai_ile_analiz(html_content, web_url):
    soup = BeautifulSoup(html_content, 'html.parser')
    for element in soup(["script", "style", "nav", "footer", "header"]): 
        element.extract()
    text = soup.get_text(separator=' ', strip=True)[:15000]

    prompt = f"""
    Sen iş makineleri uzmanı bir yapay zekasın. Şu siteyi analiz et: {web_url}
    İçerik: {text}
    Analizi sadece aşağıdaki JSON formatında döndür, başka açıklama yazma:
    {{
      "firma_adi": "...",
      "kurumsal_hakkinda": "...",
      "firma_turu": "...",
      "iletisim": "...",
      "makine_markaları": "...",
      "makineler": "...",
      "ai_firma_analizi": "..."
    }}
    """
    try:
        # Yeni SDK'da fonksiyon çağırma şekli değişti
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt
        )
        clean_json = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_json)
    except Exception as e:
        log(f"❌ AI Analiz Hatası: {e}")
        return None

def airtable_kaydet(data):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_TOKEN}", "Content-Type": "application/json"}
    
    fields = {
        "firma_adi": data.get("firma_adi"),
        "web_site": data.get("web_url"),
        "kurumsal_hakkinda": data.get("kurumsal_hakkinda"),
        "firma_turu": data.get("firma_turu"),
        "iletisim": data.get("iletisim"),
        "makine_markaları": data.get("makine_markaları"),
        "makineler": data.get("makineler"),
        "ai_firma_analizi": data.get("ai_firma_analizi")
    }
    if data.get("logo"): fields["logo"] = [{"url": data.get("logo")}]
        
    try:
        res = requests.post(url, json={"fields": fields}, headers=headers)
        return f"✅ {data.get('firma_adi')} kaydedildi." if res.status_code in [200, 201] else f"❌ Airtable Hatası: {res.text}"
    except Exception as e:
        return f"⚠️ Airtable Bağlantı Hatası: {e}"

def firma_tara(target_url):
    log(f"🔎 Tarama Başlıyor (2026 Bypass Modu): {target_url}")
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.google.com/'
    })
    
    try:
        # Önce direkt dene, 403 alırsan Cache kullan
        r = session.get(target_url, timeout=30, verify=False)
        if r.status_code == 403:
            log("⚠️ Erişim engelli, Google Cache kullanılıyor...")
            r = session.get(f"https://webcache.googleusercontent.com/search?q=cache:{target_url}", timeout=30)
            
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        
        logo_url = logo_bul(soup, target_url)
        ai_sonuc = ai_ile_analiz(r.text, target_url)
        
        if ai_sonuc:
            ai_sonuc["web_url"] = target_url
            ai_sonuc["logo"] = logo_url
            log(airtable_kaydet(ai_sonuc))
        else:
            log("❌ AI veri üretemedi.")
            
    except Exception as e:
        log(f"⚠️ Kritik Hata: {e}")

if __name__ == "__main__":
    firma_tara("https://tsmglobal.com.tr/")
