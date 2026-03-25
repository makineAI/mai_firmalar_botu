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

# --- 2. HTML TEMİZLEME (Kritik: Hatalı veriyi engeller) ---
def temiz_metin_al(html):
    soup = BeautifulSoup(html, 'html.parser')
    # Menü, footer, script gibi kalabalıkları sil
    for tags in soup(["nav", "footer", "header", "script", "style", "aside", "form"]):
        tags.extract()
    return soup.get_text(separator=' ', strip=True)[:8000]

def logo_bul(soup, base_url):
    # En olası logo desenlerini tara
    img = soup.find('img', {'src': re.compile(r'logo', re.I)}) or \
          soup.find('img', {'class': re.compile(r'logo', re.I)}) or \
          soup.find('a', {'class': re.compile(r'logo', re.I)}).find('img')
    
    if img and img.get('src'):
        src = img['src']
        return src if src.startswith('http') else base_url.rstrip('/') + '/' + src.lstrip('/')
    return ""

# --- 3. AI ANALİZ (Sıkılaştırılmış Talimatlar) ---
def rafine_analiz(context_data, target_url):
    prompt = f"""
    GÖREV: Aşağıdaki ham metinlerden sadece gerçek bilgileri ayıkla. 
    KURAL: Sitede yazmayan hiçbir şeyi uydurma. Bilgi yoksa "Bulunamadı" yaz.
    
    SİTE: {target_url}
    HAM VERİ: {context_data}

    JSON FORMATI (SADECE JSON DÖNDÜR):
    {{
      "unvan": "Şirketin resmi ve tam adı",
      "hakkinda": "Kurumsal kimlik özeti (max 2 cümle)",
      "iletisim": "Sadece telefon ve adres",
      "markalar": "Temsil edilen markalar (Örn: Sumitomo, Yanmar)",
      "urunler": "Ana ürün kategorileri (Örn: Ekskavatörler, Forkliftler)",
      "tur": "Distribütör mü, Üretici mi yoksa Servis mi?"
    }}
    """
    try:
        response = client_ai.models.generate_content(model=MODEL_NAME, contents=prompt)
        res_text = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(res_text)
    except Exception as e:
        log(f"❌ AI Analiz Hatası: {e}")
        return None

# --- 4. ANA SÜREÇ ---
def firma_tara(target_url):
    log(f"🚀 {target_url} taranıyor...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            # 1. Ana Sayfadan Logo ve Temel Bilgi Çek
            page.goto(target_url, wait_until="networkidle", timeout=60000)
            main_html = page.content()
            soup = BeautifulSoup(main_html, 'html.parser')
            
            logo_url = logo_bul(soup, target_url)
            raw_content = temiz_metin_al(main_html)
            
            # 2. Varsa "Hakkımızda" sayfasına git (Ekstra doğruluk için)
            about_link = soup.find('a', string=re.compile(r'Hakkımızda|Kurumsal', re.I))
            if about_link and about_link.get('href'):
                about_url = about_link['href'] if about_link['href'].startswith('http') else target_url.rstrip('/') + '/' + about_link['href'].lstrip('/')
                page.goto(about_url, wait_until="domcontentloaded")
                raw_content += " " + temiz_metin_al(page.content())

            # 3. AI ile Veriyi Yapılandır
            data = rafine_analiz(raw_content, target_url)
            
            if data:
                airtable_kaydet(data, target_url, logo_url)
            else:
                log("❌ Veri rafine edilemedi.")

        except Exception as e:
            log(f"⚠️ Hata: {e}")
        finally:
            browser.close()

def airtable_kaydet(data, web_url, logo_url):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_TOKEN}", "Content-Type": "application/json"}
    
    # Airtable sütun isimlerini buradakilerle birebir aynı (küçük harf, alt tire) yapmalısın.
    fields = {
        "firma_unvan": data.get("unvan", "Bilinmiyor"),
        "web_site": web_url,
        "kurumsal_hakkinda": data.get("hakkinda"),
        "firma_turu": data.get("tur"),
        "iletisim": data.get("iletisim"),
        "makine_markalari": data.get("markalar"),
        "makineler": data.get("urunler"),
        "ai_firma_analizi": f"Logo URL: {logo_url}" # Logo sütunun yoksa buraya ekledik
    }
    
    # Eğer Airtable'da 'logo' isminde bir Attachment sütunun varsa:
    if logo_url:
        fields["logo"] = [{"url": logo_url}]
    
    res = requests.post(url, json={"fields": fields}, headers=headers)
    if res.status_code in [200, 201]:
        log(f"✅ Başarıyla kaydedildi: {data.get('unvan')}")
    else:
        log(f"❌ Airtable Hatası: {res.text}")

if __name__ == "__main__":
    firma_tara("https://tsmglobal.com.tr/")
