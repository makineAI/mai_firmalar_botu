import os, sys, time, json, requests, re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from google import genai

# --- YAPILANDIRMA (Environment Variables'dan çekilir) ---
AIRTABLE_TOKEN = os.environ.get('AIRTABLE_TOKEN')
AIRTABLE_BASE_ID = os.environ.get('AIRTABLE_BASE_ID', "appC4JNkqLfVCEcna")
AIRTABLE_TABLE_NAME = os.environ.get('AIRTABLE_TABLE_NAME', "tbldmaqYiPXpH7IZ2")
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

# Yeni Google GenAI SDK Kullanımı
client_ai = genai.Client(api_key=GEMINI_API_KEY)
MODEL_NAME = 'gemini-2.0-flash' 

def log(msg):
    print(f">>> {msg}", flush=True)

def temiz_metin_al(html, limit=5000): # Limit 5000'e çıkarıldı (Analiz kalitesi için)
    soup = BeautifulSoup(html, 'html.parser')
    for tags in soup(["nav", "footer", "header", "script", "style", "aside", "iframe"]):
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
    if not any(ham_veriler.values()): return None
    
    # Modelin ne döndüreceğini netleştiren güçlü prompt
    prompt = f"""
    Sen bir İş Makinesi Sektör Analistisin. Aşağıdaki verileri analiz et ve SADECE JSON formatında yanıt ver.
    Hedef Site: {target_url}
    Veriler: {str(ham_veriler)}

    İstenen JSON Yapısı:
    {{
        "firma_unvan": "Tam Ticari Ünvan",
        "kurumsal_hakkinda": "Firma hakkında 2 cümlelik teknik özet",
        "markalar": ["Marka1", "Marka2"],
        "firma_turu": "Distribütör/Servis/Kiralama"
    }}
    """
    
    for deneme in range(3):
        try:
            # Ücretsiz sürüm için her istekten önce kısa bir nefes payı
            time.sleep(2) 
            response = client_ai.models.generate_content(model=MODEL_NAME, contents=prompt)
            text = response.text.strip()
            
            # JSON'u ayıkla
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception as e:
            if "429" in str(e):
                log(f"⚠️ KOTA DOLU: 60sn bekleniyor... (Deneme {deneme+1}/3)")
                time.sleep(60)
            else:
                log(f"❌ AI Analiz Hatası: {e}")
                break
    return None

def airtable_kaydet(data, web_url):
    # Airtable API URL'i (Tablo ID veya Adı kullanılabilir)
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_TOKEN}", "Content-Type": "application/json"}
    
    # Gelen veriyi Airtable sütun isimlerine eşle (Sütun adlarının Airtable ile aynı olduğundan emin ol)
    fields = {
        "firma_unvan": data.get("firma_unvan", "Bilinmiyor"),
        "web_site": web_url,
        "kurumsal_hakkinda": data.get("kurumsal_hakkinda", ""),
        "firma_turu": data.get("firma_turu", "İş Makineleri"),
        "ai_markalar": ", ".join(data.get("markalar", [])) if data.get("markalar") else ""
    }

    # Upsert mantığı: Önce kaydı ara
    try:
        # URL içinde özel karakterler olabileceği için basit filtreleme
        params = {"filterByFormula": f"{{web_site}} = '{web_url}'"}
        search_res = requests.get(url, headers=headers, params=params)
        search_data = search_res.json()

        if search_data.get("records"):
            rid = search_data["records"][0]["id"]
            requests.patch(f"{url}/{rid}", json={"fields": fields}, headers=headers)
            log(f"🔄 GÜNCELLENDİ: {web_url}")
        else:
            requests.post(url, json={"fields": fields}, headers=headers)
            log(f"✅ KAYIT EDİLDİ: {web_url}")
    except Exception as e:
        log(f"❌ Airtable Hatası: {e}")

def siteyi_tara(target_url):
    log(f"🚀 TSM Global Analizi Başlıyor: {target_url}")
    ham_veriler = {}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) MAI-Project/2026")
        page = context.new_page()
        
        try:
            # 1. Sayfa: Ana Sayfa
            page.goto(target_url, wait_until="networkidle", timeout=60000)
            soup = BeautifulSoup(page.content(), 'html.parser')
            ham_veriler['anasayfa'] = temiz_metin_al(page.content(), 2000)
            
            # 2. Sayfa: Hakkımızda veya Markalarımız (Hangisi bulunursa)
            hakkinda_url = link_bul(soup, ['hakkimizda', 'kurumsal', 'markalar', 'temsilcilik'], target_url)
            
            if hakkinda_url:
                log(f"📄 Alt sayfa bulundu ve taranıyor: {hakkinda_url}")
                page.goto(hakkinda_url, wait_until="domcontentloaded", timeout=30000)
                ham_veriler['detay'] = temiz_metin_al(page.content(), 4000)
            
            # Analiz Aşaması
            log("🧠 Veriler Gemini AI'ya gönderiliyor...")
            analiz = uzman_analizi(ham_veriler, target_url)
            
            if analiz:
                log(f"📊 Analiz Başarılı: {analiz.get('firma_unvan')}")
                airtable_kaydet(analiz, target_url)
            else:
                log("❌ Analiz başarısız oldu (AI yanıt vermedi).")
                
        except Exception as e:
            log(f"❌ Tarama sırasında hata oluştu: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    # TSM Global için test (Sondaki slash'a dikkat)
    siteyi_tara("https://www.tsmglobal.com.tr")
