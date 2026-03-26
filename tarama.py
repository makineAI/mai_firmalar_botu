from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import os, sys, time, json, requests, re
from urllib.parse import urljoin
from google import genai

# --- 1. YAPILANDIRMA ---
AIRTABLE_TOKEN = os.environ.get('AIRTABLE_TOKEN')
AIRTABLE_BASE_ID = os.environ.get('AIRTABLE_BASE_ID', "appC4JNkqLfVCEcna")
AIRTABLE_TABLE_NAME = os.environ.get('AIRTABLE_TABLE_NAME', "tbldmaqYiPXpH7IZ2")
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

client_ai = genai.Client(api_key=GEMINI_API_KEY)
MODEL_NAME = 'gemini-2.5-flash'

def log(msg):
    print(f">>> {msg}")
    sys.stdout.flush()

def list_to_string(value):
    if not value: return "Bilgi Yok"
    if isinstance(value, list): return ", ".join(map(str, value))
    return str(value)

# --- 2. SAYFA GEZİNTİ VE METİN ALMA ---
def temiz_metin_al(html):
    soup = BeautifulSoup(html, 'html.parser')
    # Sadece metne odaklanmak için menü, footer, script vb. çöpleri at
    for tags in soup(["nav", "footer", "header", "script", "style", "aside"]):
        tags.extract()
    # Sayfadaki TÜM metni eksiksiz alıyoruz
    return soup.get_text(separator='\n', strip=True)

def link_bul(soup, keywords, base_url):
    for a in soup.find_all('a', href=True):
        text = a.text.lower()
        href = a['href'].lower()
        if any(kw in text for kw in keywords) or any(kw in href for kw in keywords):
            return urljoin(base_url, a['href'])
    return None

def logo_bul(soup, base_url):
    img = soup.find('img', {'src': re.compile(r'logo', re.I)}) or soup.find('img', {'class': re.compile(r'logo', re.I)})
    if img and img.get('src'):
        return urljoin(base_url, img['src'])
    return ""

def sayfa_oku(page, url, sayfa_adi):
    if not url: return "Bulunamadı"
    log(f"📄 {sayfa_adi} sayfası okunuyor: {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        return temiz_metin_al(page.content())
    except: return "Sayfa açılamadı."

# --- 3. SEKTÖR UZMANI AI ANALİZİ ---
def uzman_analizi(ham_veriler, target_url):
    # AI'ya Sektör Temsilcisi Kimliği Veriyoruz
    prompt = f"""
    SENİN ROLÜN: Sen iş makineleri, endüstriyel ekipmanlar ve ticari araçlar sektöründe uzman kıdemli bir analistsin.
    GÖREVİN: Aşağıda farklı sayfalarından toplanmış TÜM ham metinleri incele ve firmayı analiz et.
    KURAL: Sadece bu metinlerde geçen gerçek bilgileri kullan. Yorum katma, uydurma.

    SİTE URL: {target_url}

    --- HAM SİTE VERİLERİ ---
    HAKKIMIZDA SAYFASI METNİ:
    {ham_veriler['hakkinda'][:15000]} 
    
    ÜRÜNLER SAYFASI METNİ:
    {ham_veriler['urunler'][:15000]}
    
    İLETİŞİM SAYFASI METNİ:
    {ham_veriler['iletisim'][:5000]}
    -------------------------

    SADECE AŞAĞIDAKİ JSON FORMATINDA YANIT VER:
    {{
      "firma_unvan": "Şirketin Resmi Tam Adı",
      "kurumsal_hakkinda": "Hakkımızda metninin tamamını anlamlı ve profesyonel bir şirket profili olarak toparla",
      "firma_turu": "Hakkında yazısından analiz et (Örn: Türkiye Distribütörü, Üretici, Kiralama Şirketi vs.)",
      "iletisim": "İletişim metninden çekilen açık adres, telefon ve e-posta",
      "makine_markalari": "Metinlerde geçen tüm temsil edilen/satılan markalar (Liste formatında)",
      "makineler": "Metinlerde geçen ana makine türleri ve ürün grupları (Örn: Ekskavatör, Forklift) (Liste formatında)",
      "ai_firma_analizi": "Sektör uzmanı gözüyle, bu firmanın sektördeki konumu, büyüklüğü ve odak noktası hakkında kısa bir analiz notu"
    }}
    """
    try:
        response = client_ai.models.generate_content(model=MODEL_NAME, contents=prompt)
        res_text = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(res_text)
    except Exception as e:
        log(f"❌ AI Analiz Hatası: {e}")
        return None

# --- 4. AIRTABLE GÜNCELLEME (UPSERT) MANTIĞI ---
def airtable_upsert(data, web_url, logo_url):
    base_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_TOKEN}", "Content-Type": "application/json"}
    
    fields = {
        "firma_unvan": list_to_string(data.get("firma_unvan")),
        "web_site": web_url,
        "kurumsal_hakkinda": list_to_string(data.get("kurumsal_hakkinda")),
        "firma_turu": list_to_string(data.get("firma_turu")),
        "iletisim": list_to_string(data.get("iletisim")),
        "makine_markalari": list_to_string(data.get("makine_markalari")),
        "makineler": list_to_string(data.get("makineler")),
        "ai_firma_analizi": list_to_string(data.get("ai_firma_analizi"))
    }
    if logo_url:
        fields["logo"] = [{"url": logo_url}]

    # 1. Aşama: Bu web sitesi zaten Airtable'da var mı? (Kontrol et)
    params = {"filterByFormula": f"{{web_site}} = '{web_url}'"}
    search_res = requests.get(base_url, headers=headers, params=params).json()

    if search_res.get("records"):
        # 2A. Varsa: Üzerine Yaz (PATCH)
        record_id = search_res["records"][0]["id"]
        patch_url = f"{base_url}/{record_id}"
        res = requests.patch(patch_url, json={"fields": fields}, headers=headers)
        log(f"🔄 Airtable Güncellendi: {web_url}")
    else:
        # 2B. Yoksa: Yeni Ekle (POST)
        res = requests.post(base_url, json={"fields": fields}, headers=headers)
        log(f"✅ Airtable Yeni Kayıt Eklendi: {web_url}")

# --- 5. ANA TARAMA MOTORU ---
def siteyi_tara(target_url):
    log(f"🚀 Keşif Başladı: {target_url}")
    ham_veriler = {}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0")
        page = context.new_page()
        page.route("**/*.{png,jpg,jpeg,gif,css,woff}", lambda route: route.abort()) # Hızlandırıcı
        
        try:
            # Ana Sayfa
            page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
            soup_main = BeautifulSoup(page.content(), 'html.parser')
            logo_url = logo_bul(soup_main, target_url)
            
            # Alt Sayfa Linklerini Bul
            link_hakkinda = link_bul(soup_main, ['kurumsal', 'hakkimizda', 'about'], target_url)
            link_iletisim = link_bul(soup_main, ['iletisim', 'contact', 'bize-ulasin'], target_url)
            link_urunler = link_bul(soup_main, ['urunler', 'makineler', 'products', 'markalar'], target_url)
            
            # Tüm Yazıları Çek (Eksiksiz)
            ham_veriler['hakkinda'] = sayfa_oku(page, link_hakkinda, "Kurumsal/Hakkımızda")
            ham_veriler['iletisim'] = sayfa_oku(page, link_iletisim, "İletişim")
            ham_veriler['urunler'] = sayfa_oku(page, link_urunler, "Ürünler/Markalar")
            
            # AI Uzmanına Gönder
            log("🧠 Sektör Uzmanı (AI) verileri analiz ediyor...")
            analiz_sonucu = uzman_analizi(ham_veriler, target_url)
            
            if analiz_sonucu:
                airtable_upsert(analiz_sonucu, target_url, logo_url)
            else:
                log("❌ Analiz başarısız oldu.")

        except Exception as e:
            log(f"⚠️ Ana Tarama Hatası: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    # Buraya ileride 50 sitelik bir liste (array) koyacağız. Şimdilik test için:
    siteler = [
        "https://tsmglobal.com.tr/"
        # "https://digerfirma.com.tr/",
        # "https://baska.com/"
    ]
    
    for site in siteler:
        siteyi_tara(site)
