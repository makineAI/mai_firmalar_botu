import os, sys, time, json, requests, re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from google import genai

# --- YAPILANDIRMA ---
AIRTABLE_TOKEN = os.environ.get('AIRTABLE_TOKEN')
AIRTABLE_BASE_ID = os.environ.get('AIRTABLE_BASE_ID', "appC4JNkqLfVCEcna")
AIRTABLE_TABLE_NAME = os.environ.get('AIRTABLE_TABLE_NAME', "tbldmaqYiPXpH7IZ2")
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

client_ai = genai.Client(api_key=GEMINI_API_KEY)
MODEL_NAME = 'gemini-2.0-flash' # En hızlı ve güncel model

def log(msg):
    print(f">>> {msg}")
    sys.stdout.flush()

# --- YARDIMCI FONKSİYONLAR ---
def temiz_metin_al(html):
    soup = BeautifulSoup(html, 'html.parser')
    for tags in soup(["nav", "footer", "header", "script", "style", "aside", "iframe"]):
        tags.extract()
    return soup.get_text(separator=' ', strip=True)

def link_bul(soup, keywords, base_url):
    for a in soup.find_all('a', href=True):
        text = a.get_text().lower()
        href = a['href'].lower()
        if any(kw in text for kw in keywords) or any(kw in href for kw in keywords):
            return urljoin(base_url, a['href'])
    return None

def logo_bul(soup, base_url):
    img = soup.find('img', {'src': re.compile(r'logo', re.I)}) or \
          soup.find('img', {'class': re.compile(r'logo', re.I)})
    if img and img.get('src'):
        return urljoin(base_url, img['src'])
    return ""

# --- SEKTÖR UZMANI ANALİZİ ---
def uzman_analizi(ham_veriler, target_url):
    prompt = f"""
    Sektör: İş Makineleri, Endüstriyel Ekipman ve Ticari Araçlar.
    Rolün: Kıdemli Sektör Analisti.
    Görev: Aşağıdaki ham metinlerden firma profilini çıkar. 
    Kural: SADECE metinde yazan gerçekleri kullan. Bilgi yoksa "Yok" yaz.

    SİTE: {target_url}
    HAKKIMIZDA: {ham_veriler.get('hakkinda', '')[:10000]}
    ÜRÜNLER: {ham_veriler.get('urunler', '')[:10000]}
    İLETİŞİM: {ham_veriler.get('iletisim', '')[:3000]}

    JSON YANIT:
    {{
      "firma_unvan": "Şirket Tam Adı",
      "kurumsal_hakkinda": "Tüm kurumsal yazının profesyonel özeti",
      "firma_turu": "Distribütör, Üretici veya Servis mi?",
      "iletisim": "Adres, Tel ve Email",
      "makine_markalari": "Temsil edilen markalar (Liste)",
      "makineler": "Sattığı ana makine grupları",
      "ai_firma_analizi": "Kısa analist notu"
    }}
    """
    try:
        response = client_ai.models.generate_content(model=MODEL_NAME, contents=prompt)
        res_text = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(res_text)
    except: return None

# --- GÜNCELLEME VEYA EKLEME (UPSERT) ---
def airtable_kaydet(data, web_url, logo_url):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_TOKEN}", "Content-Type": "application/json"}
    
    fields = {
        "firma_unvan": str(data.get("firma_unvan")),
        "web_site": web_url,
        "kurumsal_hakkinda": str(data.get("kurumsal_hakkinda")),
        "firma_turu": str(data.get("firma_turu")),
        "iletisim": str(data.get("iletisim")),
        "makine_markalari": ", ".join(data.get("makine_markalari", [])) if isinstance(data.get("makine_markalari"), list) else str(data.get("makine_markalari")),
        "makineler": ", ".join(data.get("makineler", [])) if isinstance(data.get("makineler"), list) else str(data.get("makineler")),
        "ai_firma_analizi": str(data.get("ai_firma_analizi"))
    }
    if logo_url: fields["logo"] = [{"url": logo_url}]

    # Zaten var mı?
    params = {"filterByFormula": f"{{web_site}} = '{web_url}'"}
    search = requests.get(url, headers=headers, params=params).json()

    if search.get("records"):
        rid = search["records"][0]["id"]
        requests.patch(f"{url}/{rid}", json={"fields": fields}, headers=headers)
        log(f"🔄 Güncellendi: {web_url}")
    else:
        requests.post(url, json={"fields": fields}, headers=headers)
        log(f"✅ Yeni Eklendi: {web_url}")

# --- TARAMA MOTORU ---
def siteyi_tara(target_url):
    log(f"🚀 Hayalet Modu: {target_url}")
    ham_veriler = {}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Gerçek bir Windows/Chrome simülasyonu
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            extra_http_headers={"Referer": "https://www.google.com/"}
        )
        page = context.new_page()
        page.route("**/*.{png,jpg,jpeg,gif,css,woff}", lambda route: route.abort()) # Hızlandırıcı
        
        try:
            page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000) # JS içeriği için bekle
            
            soup_main = BeautifulSoup(page.content(), 'html.parser')
            logo_url = logo_bul(soup_main, target_url)
            
            # Alt sayfaları keşfet
            links = {
                'hakkinda': link_bul(soup_main, ['kurumsal', 'hakkimizda', 'about'], target_url),
                'iletisim': link_bul(soup_main, ['iletisim', 'contact'], target_url),
                'urunler': link_bul(soup_main, ['urunler', 'makineler', 'markalarimiz'], target_url)
            }
            
            for key, lurl in links.items():
                if lurl:
                    page.goto(lurl, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(2000)
                    ham_veriler[key] = temiz_metin_al(page.content())
            
            analiz = uzman_analizi(ham_veriler, target_url)
            if analiz:
                airtable_kaydet(analiz, target_url, logo_url)
                
        except Exception as e: log(f"⚠️ Hata: {e}")
        finally: browser.close()

if __name__ == "__main__":
    siteler = ["https://tsmglobal.com.tr/"]
    for site in siteler:
        siteyi_tara(site)
