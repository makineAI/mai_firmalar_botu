from playwright.sync_api import sync_playwright
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
    for element in soup(["script", "style", "nav", "footer", "header"]): 
        element.extract()
    text = soup.get_text(separator=' ', strip=True)[:10000]

    prompt = f"Analiz et: {web_url}\nİçerik: {text}\nSADECE JSON: (firma_adi, web_site, kurumsal_hakkinda, firma_turu, iletisim, makine_markalari, makineler, ai_firma_analizi)"
    
    try:
        response = client_ai.models.generate_content(model=MODEL_NAME, contents=prompt)
        clean_json = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_json)
    except Exception as e:
        log(f"❌ AI Analiz Hatası: {e}")
        return None

def airtable_kaydet(data):
    import requests
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_TOKEN}", "Content-Type": "application/json"}
    
    # Veriyi gönderirken isimlerin tam eşleştiğinden emin oluyoruz
    fields = {
        "firma_adi": str(data.get("firma_adi", "Bilinmiyor")),
        "web_site": str(data.get("web_site", "")),
        "kurumsal_hakkinda": str(data.get("kurumsal_hakkinda", "")),
        "firma_turu": str(data.get("firma_turu", "")),
        "iletisim": str(data.get("iletisim", "")),
        "makine_markalari": str(data.get("makine_markalari", "")), 
        "makineler": str(data.get("makineler", "")),
        "ai_firma_analizi": str(data.get("ai_firma_analizi", ""))
    }
    
    payload = {"fields": fields}
    
    res = requests.post(url, json=payload, headers=headers)
    
    if res.status_code in [200, 201]:
        return f"✅ {data.get('firma_adi')} başarıyla kaydedildi."
    else:
        # HATA AYIKLAMA: Airtable tam olarak neyi beğenmediğini burada söyleyecek
        error_msg = res.json().get('error', {}).get('message', 'Bilinmeyen Hata')
        return f"❌ Airtable Hatası: {error_msg} | Gönderilen Veri Başlıkları: {list(fields.keys())}"

def firma_tara(target_url):
    log(f"🚀 Tarama Başlıyor (Gerçek Tarayıcı Modu): {target_url}")
    
    with sync_playwright() as p:
        # Tarayıcıyı başlat (headless=True GitHub'da çalışması için şart)
        browser = p.chromium.launch(headless=True)
        # İnsan gibi davranan bir kullanıcı profili oluştur
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page = context.new_page()
        
        try:
            # Siteye git ve içeriğin tamamen yüklenmesini bekle
            page.goto(target_url, wait_until="networkidle", timeout=60000)
            log("🔓 Site başarıyla açıldı!")
            
            html_content = page.content()
            ai_sonuc = ai_ile_analiz(html_content, target_url)
            
            if ai_sonuc:
                ai_sonuc["web_site"] = target_url
                log(airtable_kaydet(ai_sonuc))
            else:
                log("❌ AI veri üretemedi.")
                
        except Exception as e:
            log(f"⚠️ Tarayıcı Hatası: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    firma_tara("https://tsmglobal.com.tr/")
