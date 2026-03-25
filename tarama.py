from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import os, sys, time, json
import requests
from google import genai

# --- 1. YAPILANDIRMA ---
try:
    AIRTABLE_TOKEN = os.environ['AIRTABLE_TOKEN']
    AIRTABLE_BASE_ID = os.environ.get('AIRTABLE_BASE_ID', "appC4JNkqLfVCEcna")
    AIRTABLE_TABLE_NAME = os.environ.get('AIRTABLE_TABLE_NAME', "tblC5TPs01HhtO9MA")
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

    # AI'ya veriyi hazırlatırken anahtarları sabit tutuyoruz, 
    # Airtable'a gönderirken senin sütun isimlerine eşleyeceğiz.
    prompt = f"""
    Aşağıdaki web sitesini analiz et: {web_url}
    İçerik: {text}
    
    Analizi SADECE aşağıdaki JSON formatında döndür (Ek açıklama yapma):
    {{
      "unvan": "Firma Tam Adı",
      "web": "{web_url}",
      "ozet": "Kurumsal özet bilgi",
      "tur": "Firma türü (Üretici/Bayi vb.)",
      "iletisim": "Telefon, e-posta ve adres",
      "marka": "Temsil edilen markalar",
      "urun": "Ürün grupları ve makineler",
      "analiz": "AI tarafından yapılan sektör analizi"
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
    
    # --- BURASI KRİTİK: Sol taraftaki isimleri Airtable'daki sütun başlıklarınla BİREBİR AYNI yap ---
    # Eğer Airtable'da "Firma Ünvanı" yazıyorsa burayı da öyle değiştir.
    fields = {
        "firma_unvan": data.get("unvan"),
        "web_site": data.get("web"),
        "kurumsal_hakkinda": data.get("ozet"),
        "firma_turu": data.get("tur"),
        "iletisim": data.get("iletisim"),
        "makine_markalari": data.get("marka"),
        "makineler": data.get("urun"),
        "ai_firma_analizi": data.get("analiz")
    }
    
    res = requests.post(url, json={"fields": fields}, headers=headers)
    
    if res.status_code in [200, 201]:
        return f"✅ {data.get('unvan')} başarıyla Airtable'a kaydedildi!"
    else:
        # Hata durumunda hangi sütunun sorunlu olduğunu anlamak için tam mesajı basıyoruz
        return f"❌ Airtable Hatası: {res.text}"

def firma_tara(target_url):
    log(f"🚀 Tarama Başlıyor: {target_url}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        try:
            page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3) # JS içeriklerin yüklenmesi için biraz bekle
            
            log("🔓 Site içeriği alındı, AI analizine başlanıyor...")
            html_content = page.content()
            
            ai_sonuc = ai_ile_analiz(html_content, target_url)
            
            if ai_sonuc:
                log(airtable_kaydet(ai_sonuc))
            else:
                log("❌ AI veri işleyemedi.")
                
        except Exception as e:
            log(f"⚠️ Hata: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    # Test için TSM Global
    firma_tara("https://tsmglobal.com.tr/")
