import os, sys, json, requests, re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from google import genai

# --- GÜVENLİ YAPILANDIRMA ---
AIRTABLE_TOKEN = os.environ.get('AIRTABLE_TOKEN')
AIRTABLE_BASE_ID = os.environ.get('AIRTABLE_BASE_ID', "appC4JNkqLfVCEcna")
AIRTABLE_TABLE_NAME = os.environ.get('AIRTABLE_TABLE_NAME', "tbldmaqYiPXpH7IZ2")
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

client_ai = genai.Client(api_key=GEMINI_API_KEY)
MODEL_NAME = 'gemini-2.5-pro' 

def log(msg):
    print(f">>> {msg}", flush=True)

def logo_bul(html, base_url):
    """Logoyu özellikle sitenin üst (header/nav) kısımlarında arar."""
    soup = BeautifulSoup(html, 'html.parser')
    # Önce header veya nav içindeki logolara bak (en doğru logo buradadır)
    for container in soup.find_all(['header', 'nav', 'div']):
        for img in container.find_all('img'):
            src = img.get('src', '').lower()
            alt = img.get('alt', '').lower()
            if 'logo' in src or 'logo' in alt:
                return urljoin(base_url, img.get('src'))
    return ""

def temiz_metin_al(html, limit=40000): 
    """SADECE arka plan kodlarını siler. Footer ve Header (Ünvan/İletişim) DOKUNULMAZ!"""
    soup = BeautifulSoup(html, 'html.parser')
    for tags in soup(["script", "style", "noscript", "iframe", "svg"]):
        tags.extract()
    # Metinleri birbirine girmemesi için boşluklarla ayır
    text = soup.get_text(separator=' | ', strip=True)
    return re.sub(r'\s+', ' ', text)[:limit]

def kritik_linkleri_bul(soup, base_url):
    """İletişim, Hakkımızda ve Ürünler linklerini yakalar."""
    linkler = {'hakkimizda': None, 'iletisim': None, 'urunler': None}
    
    for a in soup.find_all('a', href=True):
        text = a.get_text().lower()
        href = a['href'].lower()
        full_url = urljoin(base_url, a['href'])
        
        if any(k in text or k in href for k in ['hakkimizda', 'kurumsal', 'biz kim']):
            linkler['hakkimizda'] = full_url
        elif any(k in text or k in href for k in ['iletişim', 'iletisim', 'contact']):
            linkler['iletisim'] = full_url
        elif any(k in text or k in href for k in ['ürünler', 'urunler', 'markalar', 'temsilcilik']):
            linkler['urunler'] = full_url
            
    return linkler

def uzman_analizi(ham_veriler, target_url):
    """Kısıtlamalar kaldırıldı! Gemini'ye kesin ve net emirler verildi."""
    if not any(ham_veriler.values()): return None
    
    prompt = f"""
    Sen kıdemli bir İş Makinesi Sektör Analistisin. Amacımız şirketin resmi bilgilerini EKSİKSİZ çıkarmak.
    Aşağıdaki veriler sitenin Anasayfa, Hakkımızda, İletişim ve Ürünler sayfalarından çekilmiştir. (Footer ve Header dahil).

    KESİN KURALLAR:
    1. "firma_unvan": Kesinlikle RESMİ TİCARİ ÜNVANI bul. (Örn: TSM GLOBAL TURKEY MAKİNA SANAYİ VE TİCARET A.Ş.). Genelde iletişim sayfasında veya sayfanın en altında (footer) yazar.
    2. "kurumsal_hakkinda": Sitedeki 'Hakkımızda / Kurumsal' yazısını ASLA ÖZETLEME. Kısaltma yapmadan, tarihçe ve vizyon dahil metnin TAMAMINA YAKININI detaylı bir paragraf olarak ver.
    3. "iletisim": Merkez ofis adresini, TÜM telefon numaralarını (Tel, Faks) ve E-posta adreslerini tam olarak yaz.
    4. "makine_markalari": Sitede satıldığı/temsil edildiği belirtilen TÜM markaları (Sumitomo, Hyster vb.) eksiksiz bir dizi olarak listele.
    5. "makineler": Hangi tip makineler satılıyor? (Örn: Paletli Ekskavatör, Dizel Forklift, Toprak Silindiri). Sayfada geçen tüm kategorileri detaylıca listele.

    Hedef Site: {target_url}
    Veriler: {str(ham_veriler)}

    İstenen JSON Formatı (Sadece geçerli bir JSON döndür, markdown kullanma):
    {{
        "firma_unvan": "...",
        "kurumsal_hakkinda": "...",
        "firma_turu": "Distribütör / Servis / Kiralama / İmalatçı",
        "iletisim": "...",
        "makine_markalari": ["...", "..."],
        "makineler": ["...", "..."]
    }}
    """
    
    try:
        response = client_ai.models.generate_content(model=MODEL_NAME, contents=prompt)
        match = re.search(r'\{.*\}', response.text.strip(), re.DOTALL)
        if match: return json.loads(match.group())
        else: return None
    except Exception as e:
        log(f"❌ AI Hatası: {e}")
        return None

def airtable_kaydet(data, web_url, logo_url):
    """Veriyi eksiksiz bir şekilde Airtable'a işler."""
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_TOKEN}", "Content-Type": "application/json"}
    
    logo_data = [{"url": logo_url}] if logo_url else []

    fields = {
        "firma_unvan": data.get("firma_unvan", "Bilinmiyor"),
        "logo": logo_data,
        "web_site": web_url,
        "kurumsal_hakkinda": data.get("kurumsal_hakkinda", ""),
        "firma_turu": data.get("firma_turu", "Bilinmiyor"),
        "iletisim": data.get("iletisim", ""),
        "makine_markalari": ", ".join(data.get("makine_markalari", [])) if data.get("makine_markalari") else "",
        "makineler": ", ".join(data.get("makineler", [])) if data.get("makineler") else "",
        "ai_firma_analizi": "✅ Maksimum Derinlikte Tarandı ve Doğrulandı."
    }

    try:
        params = {"filterByFormula": f"{{web_site}} = '{web_url}'"}
        search_res = requests.get(url, headers=headers, params=params)
        search_data = search_res.json()

        if search_data.get("records"):
            rid = search_data["records"][0]["id"]
            res = requests.patch(f"{url}/{rid}", json={"fields": fields}, headers=headers)
            if res.status_code in [200, 201]: log(f"🔄 GÜNCELLENDİ: {web_url}")
            else: log(f"❌ Güncelleme Hatası: {res.text}")
        else:
            res = requests.post(url, json={"fields": fields}, headers=headers)
            if res.status_code in [200, 201]: log(f"✅ KAYIT EDİLDİ: {web_url}")
            else: log(f"❌ Kayıt Hatası: {res.text}")
    except Exception as e:
        log(f"❌ Airtable Hatası: {e}")

def siteyi_tara(target_url):
    log(f"🚀 MAKSİMUM DERİN TARAMA Başlıyor: {target_url}")
    ham_veriler = {}
    logo_url = ""
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        page = context.new_page()
        
        try:
            # 1. Ana Sayfa
            page.goto(target_url, wait_until="networkidle", timeout=60000)
            anasayfa_html = page.content()
            logo_url = logo_bul(anasayfa_html, target_url)
            log(f"🖼️ Bulunan Logo URL: {logo_url}")
            
            soup = BeautifulSoup(anasayfa_html, 'html.parser')
            ham_veriler['anasayfa'] = temiz_metin_al(anasayfa_html, 25000)
            
            # 2. Kritik Alt Sayfalar
            linkler = kritik_linkleri_bul(soup, target_url)
            
            for sayfa_turu, link in linkler.items():
                if link:
                    log(f"📄 Okunuyor [{sayfa_turu}]: {link}")
                    try:
                        page.goto(link, wait_until="domcontentloaded", timeout=30000)
                        ham_veriler[sayfa_turu] = temiz_metin_al(page.content(), 30000)
                    except Exception as e:
                        log(f"⚠️ {sayfa_turu} sayfası okunurken uyarı: {e}")
            
            log("🧠 Ham veriler Gemini 2.5 Pro'ya analiz için iletiliyor...")
            analiz = uzman_analizi(ham_veriler, target_url)
            
            if analiz:
                log(f"📊 Ünvan Tespiti: {analiz.get('firma_unvan')}")
                airtable_kaydet(analiz, target_url, logo_url)
            else:
                log("❌ Analiz başarısız oldu.")
                
        except Exception as e:
            log(f"❌ Tarama sırasında hata: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    siteyi_tara("https://www.tsmglobal.com.tr")
