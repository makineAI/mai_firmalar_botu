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
    soup = BeautifulSoup(html, 'html.parser')
    for img in soup.find_all('img'):
        siniflar = " ".join(img.get('class', [])).lower()
        id_adi = img.get('id', '').lower()
        if 'navbar-brand' in siniflar or 'header-logo' in siniflar or 'site-logo' in siniflar or 'main-logo' in id_adi:
            return urljoin(base_url, img.get('src'))
    for container in soup.find_all(['header', 'nav', 'div'], limit=10):
        for img in container.find_all('img'):
            src = img.get('src', '').lower()
            alt = img.get('alt', '').lower()
            if 'logo' in src or 'logo' in alt:
                return urljoin(base_url, img.get('src'))
    return ""

def temiz_metin_al(html, limit=150000): 
    soup = BeautifulSoup(html, 'html.parser')
    for tags in soup(["script", "style", "noscript", "iframe", "svg"]):
        tags.extract()
    text = soup.get_text(separator='\n', strip=True)
    return re.sub(r'\n+', '\n', text)[:limit]

def kritik_linkleri_bul(soup, base_url):
    linkler = {'hakkimizda': None, 'iletisim': None, 'urunler': None}
    for a in soup.find_all('a', href=True):
        text = a.get_text().strip().lower()
        href = a['href'].lower()
        full_url = urljoin(base_url, a['href'])
        
        if not linkler['hakkimizda'] and any(k in text for k in ['hakkımızda', 'hakkimizda', 'hakkinda', 'kurumsal kimlik', 'tarihçe']):
            linkler['hakkimizda'] = full_url
        elif not linkler['hakkimizda'] and any(k in href for k in ['hakkimizda', 'kurumsal-kimlik']):
            linkler['hakkimizda'] = full_url
            
        if not linkler['iletisim'] and any(k in text for k in ['iletişim', 'iletisim', 'bize ulaşın', 'iletisim-bilgileri']):
            linkler['iletisim'] = full_url
        elif not linkler['iletisim'] and 'iletisim' in href:
            linkler['iletisim'] = full_url
            
        if not linkler['urunler'] and any(k in text for k in ['ürünler', 'urunler', 'markalarımız']):
            linkler['urunler'] = full_url
        elif not linkler['urunler'] and any(k in href for k in ['urunler', 'markalar']):
            linkler['urunler'] = full_url
            
    return linkler

def uzman_analizi(ham_veriler, target_url):
    if not any(ham_veriler.values()): return None
    
    prompt = f"""
    Sen kıdemli bir İş Makinesi Sektör Analisti ve Veri Madencisisin.

    KESİN VE KIRILAMAZ KURALLARIN:
    1. firma_unvan: Firmanın resmi ticari ünvanını bul (Örn: TSM GLOBAL TURKEY MAKİNA SANAYİ VE TİCARET A.Ş.). Mutlaka A.Ş. veya Ltd. gibi ekleri içermelidir.
    2. kurumsal_hakkinda: Sitenin 'Hakkımızda' veya 'Kurumsal' bölümünde yer alan hikaye, vizyon, tarihçe ve şirket profili bilgilerini ÇOK DETAYLI, UZUN ve KAPSAMLI bir metin olarak tek parça halinde yaz. Kesinlikle boş bırakma.
    3. iletisim: "Adres: [Açık Adres] | Tel: [Telefonlar] | Fax: [Faks] | E-posta: [Mail]" formatında yaz. (Firma adını buraya ekleme).
    4. makine_markalari: Sadece markanın adını ve Türkiye'deki konumunu kısa bir cümleyle yaz.
    5. makineler: SADECE KATEGORİ VE MARKA EŞLEŞTİRMESİ YAP. (Örn: "Yükleyiciler: LOVOL Lastik Tekerlekli Yükleyiciler"). Model numaralarını (Örn: SH500LHD-7) ve pazarlama cümlelerini KESİNLİKLE SİL.

    Hedef Site: {target_url}
    Veriler: {str(ham_veriler)}

    AŞAĞIDAKİ JSON FORMATINDA YANIT VER (Markdown kullanma):
    {{
        "firma_unvan": "...",
        "kurumsal_hakkinda": "...",
        "firma_turu": "...",
        "iletisim": "...",
        "makine_markalari": [
            {{"marka": "...", "detay": "..."}}
        ],
        "makineler": [
            {{"kategori": "...", "detay": "..."}}
        ]
    }}
    """
    
    try:
        response = client_ai.models.generate_content(model=MODEL_NAME, contents=prompt)
        match = re.search(r'\{.*\}', response.text.strip(), re.DOTALL)
        if match: return json.loads(match.group())
        return None
    except Exception as e:
        log(f"❌ AI Hatası: {e}")
        return None

def airtable_kaydet(data, web_url, logo_url):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_TOKEN}", "Content-Type": "application/json"}
    
    logo_data = [{"url": logo_url}] if logo_url else []

    markalar_metni = "\n\n".join([f"🔹 {m.get('marka', '')}:\n{m.get('detay', '')}" for m in data.get("makine_markalari", []) if isinstance(m, dict)])
    makineler_metni = "\n\n".join([f"🚜 {m.get('kategori', '')}:\n{m.get('detay', '')}" for m in data.get("makineler", []) if isinstance(m, dict)])

    fields = {
        "firma_unvan": data.get("firma_unvan", "Bilinmiyor"),
        "logo": logo_data,
        "web_site": web_url,
        "kurumsal_hakkinda": data.get("kurumsal_hakkinda", "Bilgi bulunamadı."),
        "firma_turu": data.get("firma_turu", "Bilinmiyor"),
        "iletisim": data.get("iletisim", ""),
        "makine_markalari": markalar_metni if markalar_metni else str(data.get("makine_markalari", "")),
        "makineler": makineler_metni if makineler_metni else str(data.get("makineler", "")),
        "ai_firma_analizi": "✅ Son Aşama: Kurumsal metin düzeltildi, iletişim formatı temizlendi."
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
    log(f"🚀 FINAL TARAMA Başlıyor: {target_url}")
    ham_veriler = {}
    logo_url = ""
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        page = context.new_page()
        
        try:
            page.goto(target_url, wait_until="networkidle", timeout=60000)
            anasayfa_html = page.content()
            logo_url = logo_bul(anasayfa_html, target_url)
            log(f"🖼️ Ana Logo Bulundu: {logo_url}")
            
            soup = BeautifulSoup(anasayfa_html, 'html.parser')
            ham_veriler['anasayfa'] = temiz_metin_al(anasayfa_html, 40000)
            
            linkler = kritik_linkleri_bul(soup, target_url)
            
            for sayfa_turu, link in linkler.items():
                if link:
                    log(f"📄 Okunuyor [{sayfa_turu}]: {link}")
                    try:
                        page.goto(link, wait_until="domcontentloaded", timeout=45000)
                        ham_veriler[sayfa_turu] = temiz_metin_al(page.content(), 50000)
                    except Exception as e:
                        log(f"⚠️ {sayfa_turu} sayfasında zaman aşımı: {e}")
            
            log("🧠 Veriler Gemini'ye iletiliyor...")
            analiz = uzman_analizi(ham_veriler, target_url)
            
            if analiz:
                log(f"📊 Analiz Tamamlandı.")
                airtable_kaydet(analiz, target_url, logo_url)
            else:
                log("❌ Analiz başarısız oldu.")
                
        except Exception as e:
            log(f"❌ Tarama sırasında hata: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    siteyi_tara("https://www.tsmglobal.com.tr")
