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

# --- 2. YARDIMCI FONKSİYONLAR ---
def link_bul(soup, keywords, base_url):
    """Belirli anahtar kelimelere göre sayfadaki linki bulur."""
    for link in soup.find_all('a', href=True):
        text = link.get_text().lower()
        href = link['href'].lower()
        if any(kw in text or kw in href for kw in keywords):
            full_url = href if href.startswith('http') else base_url.rstrip('/') + '/' + href.lstrip('/')
            return full_url
    return None

def logo_bul(soup, base_url):
    """Sitedeki logo URL'sini yakalamaya çalışır."""
    # 1. Klasik logo class/id'leri
    img = soup.find('img', {'class': re.compile(r'logo', re.I)}) or \
          soup.find('img', {'id': re.compile(r'logo', re.I)}) or \
          soup.find('img', {'src': re.compile(r'logo', re.I)})
    
    if img and img.get('src'):
        src = img['src']
        return src if src.startswith('http') else base_url.rstrip('/') + '/' + src.lstrip('/')
    return ""

def ai_temizlik(data_chunks):
    """Toplanan ham metinleri AI ile temiz ve yapılandırılmış hale getirir."""
    prompt = f"""
    Aşağıdaki ham verileri birleştir ve profesyonel bir şirket profili oluştur.
    HAKKIMIZDA METNİ: {data_chunks.get('hakkimizda', 'Bulunamadı')}
    İLETİŞİM METNİ: {data_chunks.get('iletisim', 'Bulunamadı')}
    ÜRÜNLER METNİ: {data_chunks.get('urunler', 'Bulunamadı')}

    JSON formatında döndür:
    {{
      "unvan": "Şirketin resmi tam adı",
      "hakkinda": "Hakkımızda kısmının temiz özeti",
      "iletisim": "Adres, Telefon, E-posta bilgileri",
      "markalar": "Ürünler içinden tespit edilen markalar (Virgülle ayır)",
      "makineler": "Sattığı ana makine grupları",
      "tur": "Üretici mi, Distribütör mü?"
    }}
    """
    try:
        response = client_ai.models.generate_content(model=MODEL_NAME, contents=prompt)
        return json.loads(response.text.replace('```json', '').replace('```', '').strip())
    except: return None

# --- 3. ANA TARAMA SÜRECİ ---
def firma_tara(target_url):
    log(f"🔎 Site Keşfi Başlıyor: {target_url}")
    data_chunks = {}
    logo_url = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            # ADIM 1: Ana Sayfa ve Linkleri Bul
            page.goto(target_url, wait_until="networkidle", timeout=60000)
            soup_main = BeautifulSoup(page.content(), 'html.parser')
            logo_url = logo_bul(soup_main, target_url)
            log(f"🖼️ Logo: {logo_url}")

            links = {
                'hakkimizda': link_bul(soup_main, ['kurumsal', 'hakkimizda', 'about'], target_url),
                'iletisim': link_bul(soup_main, ['iletisim', 'contact'], target_url),
                'urunler': link_bul(soup_main, ['urunler', 'makineler', 'products', 'makina'], target_url)
            }

            # ADIM 2: Alt Sayfaları Gez ve Ham Metni Topla
            for key, url in links.items():
                if url:
                    log(f"📄 {key.capitalize()} sayfası okunuyor: {url}")
                    page.goto(url, wait_until="domcontentloaded")
                    page.wait_for_timeout(2000)
                    data_chunks[key] = BeautifulSoup(page.content(), 'html.parser').get_text(separator=' ', strip=True)[:5000]
            
            # ADIM 3: AI ile İşle ve Airtable'a At
            final_data = ai_temizlik(data_chunks)
            if final_data:
                airtable_at(final_data, target_url, logo_url)

        except Exception as e: log(f"❌ Hata: {e}")
        finally: browser.close()

def airtable_at(data, web_url, logo_url):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_TOKEN}", "Content-Type": "application/json"}
    
    fields = {
        "firma_unvan": data.get("unvan"),
        "web_site": web_url,
        "kurumsal_hakkinda": data.get("hakkinda"),
        "firma_turu": data.get("tur"),
        "iletisim": data.get("iletisim"),
        "makine_markalari": data.get("markalar"),
        "makineler": data.get("makineler"),
        "logo": [{"url": logo_url}] if logo_url else [] # Logo için Airtable 'Attachment' tipi kullanıyorsan
    }
    
    res = requests.post(url, json={"fields": fields}, headers=headers)
    log(f"🚀 Kayıt: {res.status_code}")

if __name__ == "__main__":
    firma_tara("https://tsmglobal.com.tr/")
