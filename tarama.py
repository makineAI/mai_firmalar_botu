from curl_cffi import requests # En güçlü bypass kütüphanesi
from bs4 import BeautifulSoup
import os, sys, time, json
from google import genai

# --- 1. YAPILANDIRMA ---
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
    # Gereksiz kısımları temizle
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
    headers = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json"
    }
    
    fields = {
        "firma_adi": data.get("firma_adi"),
        "web_site": data.get("web_site"),
        "kurumsal_hakkinda": data.get("kurumsal_hakkinda"),
        "firma_turu": data.get("firma_turu"),
        "iletisim": data.get("iletisim"),
        "makine_markaları": data.get("makine_markaları"),
        "makineler": data.get("makineler"),
        "ai_firma_analizi": data.get("ai_firma_analizi")
    }
    
    # Airtable kaydı için standart requests kullanabiliriz
    import requests as air_req
    res = air_req.post(url, json={"fields": fields}, headers=headers)
    return f"✅ Kaydedildi." if res.status_code in [200, 201] else f"❌ Airtable Hatası: {res.text}"

def firma_tara(target_url):
    log(f"🚀 Tarama Başlıyor (Chrome Impersonate Modu): {target_url}")
    
    try:
        # curl_cffi ile kendimizi GERÇEK BİR CHROME gibi tanıtıyoruz
        # Bu işlem SSL hatalarını ve 403 engellerini otomatik aşar.
        r = requests.get(
            target_url, 
            impersonate="chrome", # Kritik nokta: Chrome gibi davran!
            timeout=30,
            verify=False
        )
        r.raise_for_status()
        
        log("🔓 Site güvenliği aşıldı, AI analizine geçiliyor...")
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
