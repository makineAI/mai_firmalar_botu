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
    """HTML içinden sitenin logosunu bulmaya çalışır."""
    soup = BeautifulSoup(html, 'html.parser')
    for img in soup.find_all('img'):
        src = img.get('src', '').lower()
        alt = img.get('alt', '').lower()
        class_name = " ".join(img.get('class', [])).lower()
        id_name = img.get('id', '').lower()
        
        if 'logo' in src or 'logo' in alt or 'logo' in class_name or 'logo' in id_name:
            return urljoin(base_url, img.get('src'))
    return ""

def temiz_metin_al(html, limit=25000): 
    """Gereksiz kodları temizler, sadece saf metni alır."""
    soup = BeautifulSoup(html, 'html.parser')
    for tags in soup(["nav", "footer", "header", "script", "style", "aside", "iframe", "noscript"]):
        tags.extract()
    text = soup.get_text(separator=' ', strip=True)
    return re.sub(r'\s+', ' ', text)[:limit]

def kritik_linkleri_bul(soup, base_url):
    """Sitedeki iletişim, hakkımızda ve ürünler sayfalarını bulur."""
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
    """Gemini Pro'ya tüm toplanan veriyi gönderip detaylı JSON alır."""
    if not any(ham_veriler.values()): 
        return None
    
    prompt = f"""
    Sen kıdemli bir İş Makinesi Sektör Analistisin. Aşağıdaki şirket web sitesinden toplanan ham verileri derinlemesine analiz et.
    Hiçbir veriyi eksik bırakma, özetleme, detaylıca çıkar. Yanıtın SADECE geçerli bir JSON olmalıdır. Markdown kullanma.
    
    Hedef Site: {target_url}
    Toplanan Veriler: {str(ham_veriler)}

    İstenen JSON Formatı ve Kuralları:
    {{
        "firma_unvan": "Firmanın tam resmi ticari ünvanı (A.Ş., Ltd. Şti. dahil, bulamazsan markayı yaz)",
        "kurumsal_hakkinda": "Firmanın tarihçesi, misyonu ve ne iş yaptığına dair DETAYLI ve uzun kurumsal açıklama metni.",
        "firma_turu": "Sadece şunlardan biri: Distribütör / Servis / Kiralama / Yedek Parça / İmalatçı",
        "iletisim": "Açık adres, Telefon numaraları ve Email adresi (Tamamını yaz)",
        "makine_markalari": ["Marka1", "Marka2"],
        "makineler": ["Ekskavatör", "Loder", "Forklift", "Silindir"] 
    }}
    Not: 'makine_markalari' ve 'makineler' dizilerini (array) bulabildiğin tüm modellerle doldur.
    """
    
    try:
        response = client_ai.models.generate_content(model=MODEL_NAME, contents=prompt)
        # HATALI KISIM DÜZELTİLDİ:
        match = re.search(r'\{.*\}', response.text.strip(), re.DOTALL)
        if match:
            return json.loads(match.group())
        else:
            log("❌ AI yanıtı JSON değildi.")
            return None
    except Exception as e:
        log(f"❌ AI Hatası: {e}")
        return None

def airtable_kaydet(data, web_url, logo_url):
    """Veriyi Airtable'a yazar, logoyu ek (attachment) formatına çevirir."""
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_TOKEN}", "Content-Type": "application/json"}
    
    # Airtable 'Attachment' (Dosya Eki) alanı için özel logo formatı:
    logo_data = [{"url": logo_url}] if logo_url else []

    fields = {
        "firma_unvan": data.get("firma_unvan", "Bilinmiyor"),
        "logo": logo_data,  # Artık Airtable'ın tam istediği formatta gidiyor!
        "web_site": web_url,
        "kurumsal_hakkinda": data.get("kurumsal_hakkinda", ""),
        "firma_turu": data.get("firma_turu", "Bilinmiyor"),
        "iletisim": data.get("iletisim", ""),
        "makine_markalari": ", ".join(data.get("makine_markalari", [])) if data.get("makine_markalari") else "",
        "makineler": ", ".join(data.get("makineler", [])) if data.get("makineler") else "",
        "ai_firma_analizi": "✅ Detaylı Tarama Yapıldı."
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
    log(f"🚀 DERİN TARAMA Başlıyor: {target_url}")
    ham_veriler = {}
    logo_url = ""
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        page = context.new_page()
        
        try:
            # 1. Ana Sayfa ve Logo
            page.goto(target_url, wait_until="networkidle", timeout=60000)
            anasayfa_html = page.content()
            logo_url = logo_bul(anasayfa_html, target_url)
            log(f"🖼️ Bulunan Logo URL: {logo_url}")
            
            soup = BeautifulSoup(anasayfa_html, 'html.parser')
            ham_veriler['anasayfa'] = temiz_metin_al(anasayfa_html, 15000)
            
            # 2. Kritik Sayfa Linklerini Çıkar
            linkler = kritik_linkleri_bul(soup, target_url)
            
            # 3. Alt Sayfaları Ziyaret Et (Hakkımızda, İletişim, Ürünler)
            for sayfa_turu, link in linkler.items():
                if link:
                    log(f"📄 Geziliyor [{sayfa_turu}]: {link}")
                    page.goto(link, wait_until="domcontentloaded", timeout=30000)
                    ham_veriler[sayfa_turu] = temiz_metin_al(page.content(), 20000)
            
            log("🧠 Kapsamlı Veriler Gemini Pro'ya gönderiliyor...")
            analiz = uzman_analizi(ham_veriler, target_url)
            
            if analiz:
                log(f"📊 Analiz Başarılı: {analiz.get('firma_unvan')}")
                airtable_kaydet(analiz, target_url, logo_url)
            else:
                log("❌ Analiz başarısız oldu.")
                
        except Exception as e:
            log(f"❌ Tarama sırasında hata: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    siteyi_tara("https://www.tsmglobal.com.tr")
