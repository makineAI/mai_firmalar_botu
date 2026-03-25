import requests
from bs4 import BeautifulSoup
import os, sys, time, urllib3, json
from urllib.parse import urljoin
import google.generativeai as genai

# SSL uyarılarını kapat
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- YAPILANDIRMA (GitHub Secrets'tan Alınır) ---
try:
    AIRTABLE_TOKEN = os.environ['AIRTABLE_TOKEN']
    AIRTABLE_BASE_ID = os.environ['AIRTABLE_BASE_ID']
    GEMINI_API_KEY = os.environ['GEMINI_API_KEY']
    AIRTABLE_TABLE_NAME = "mai_firmalar" # Sabit tablo adı
except KeyError as e:
    print(f"❌ HATA: GitHub Secrets eksik tanımlanmış: {e}")
    sys.exit(1)

# Gemini Kurulumu
genai.configure(api_key=GEMINI_API_KEY)
ai_model = genai.GenerativeModel('gemini-1.5-flash')

def log(msg):
    print(f">>> {msg}")
    sys.stdout.flush()

def logo_bul(soup, base_url):
    """Sitenin içinden logo URL'sini avlar."""
    # 1. Klasik img tagı taraması
    for img in soup.find_all('img', src=True):
        src = img['src'].lower()
        alt = img.get('alt', '').lower()
        if any(x in src or x in alt for x in ['logo', 'brand', 'header']):
            return urljoin(base_url, img['src'])
    # 2. Meta etiketi (Sosyal Medya görseli)
    og_image = soup.find("meta", property="og:image")
    if og_image:
        return urljoin(base_url, og_image["content"])
    return ""

def ai_ile_analiz(html_content, web_url):
    """Sitenin metnini Gemini'ye gönderir ve tam JSON olarak döner."""
    soup = BeautifulSoup(html_content, 'html.parser')
    # Gereksiz kısımları (script, style, menü) temizle
    for element in soup(["script", "style", "nav", "footer", "header"]): 
        element.extract()
    text = soup.get_text(separator=' ', strip=True)[:15000] # Daha geniş metin alanı

    prompt = f"""
    Sen iş makineleri ve istifleme sektörü uzmanı bir yapay zekasın.
    Aşağıdaki web sitesini analiz et: {web_url}
    Sitenin ham metni: {text}
    
    Analiz sonuçlarını, Airtable sütun isimlerimle birebir uyumlu, aşağıdaki JSON formatında döndür.
    JSON dışında HİÇBİR açıklama yazma, sadece JSON'ı döndür.
    Eğer bir bilgiyi bulamazsan, karşılığını boş bırak (Örn: "").
    
    JSON Formatı:
    {{
      "firma_adi": "Firmanın tam resmi adı",
      "kurumsal_hakkinda": "Firma hakkında sektörel derinliği olan 2-3 cümlelik özet",
      "firma_turu": "Distribütör, Bayi, Servis, Kiralama seçeneklerinden hangileri uygunsa, virgülle ayırarak yaz",
      "iletisim": "Bulabildiğin adres, telefon ve e-posta",
      "makine_markaları": "Temsil edilen veya satılan tüm markalar (Yanmar, Sumitomo vb.), virgülle ayır",
      "makineler": "Hangi tip makineler var? (Forklift, Ekskavatör, Platform vb.), virgülle ayır",
      "ai_firma_analizi": "Firmanın piyasadaki gücü ve uzmanlık alanları hakkında profesyonel yorum"
    }}
    """
    try:
        response = ai_model.generate_content(prompt)
        # JSON'ı temizle (Bazen AI ```json ... ``` içinde döndürebiliyor)
        clean_json = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_json)
    except Exception as e:
        log(f"❌ AI Analiz Hatası: {e}")
        return None

def airtable_kaydet(data):
    """Veriyi Airtable'a gönderir."""
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json"
    }
    
    # Airtable sütun isimlerinle (Senin verdiğin gibi) birebir eşleşen alanlar
    fields = {
        "firma_adi": data.get("firma_adi"),
        "web_site": data.get("web_url"),
        "kurumsal_hakkinda": data.get("kurumsal_hakkinda"),
        "firma_turu": data.get("firma_turu"),
        "iletisim": data.get("iletisim"),
        "makine_markaları": data.get("makine_markaları"), # 'ı' harfine dikkat!
        "makineler": data.get("makineler"),
        "ai_firma_analizi": data.get("ai_firma_analizi")
    }
    
    # Logo varsa ekle (Airtable Attachment formatı)
    if data.get("logo"):
        fields["logo"] = [{"url": data.get("logo")}]
        
    try:
        res = requests.post(url, json={"fields": fields}, headers=headers, timeout=20)
        if res.status_code in [200, 201]:
            return f"✅ {data.get('firma_adi')} başarıyla kaydedildi."
        else:
            return f"❌ Airtable Hatası ({res.status_code}): {res.text}"
    except Exception as e:
        return f"⚠️ Airtable Bağlantı Hatası: {e}"

def firma_tara(target_url):
    log(f"🔎 Tarama Başlıyor: {target_url}")
    session = requests.Session()
    
    # --- GELİŞMİŞ GÜVENLİK DUVARI AŞICI HEADERS ---
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer': 'https://www.google.com/',
        'Upgrade-Insecure-Requests': '1',
        'DNT': '1'
    })
    
    try:
        # Siteyi çekerken biraz daha gerçekçi davranalım
        time.sleep(2) # Siteye girmeden önce 2 saniye bekle (insan hızı)
        r = session.get(target_url, timeout=40, verify=False)
        
        # Eğer hala 403 verirse alternatif bir yol deneyelim
        if r.status_code == 403:
            log("⚠️ 403 Hatası alındı, alternatif kimlik deneniyor...")
            session.headers.update({'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'})
            r = session.get(target_url, timeout=40, verify=False)

        r.raise_for_status() 
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # --- (Kodun geri kalanı aynı kalacak: Logo ve AI Analizi) ---
        log("🖼️ Logo aranıyor...")
        logo_url = logo_bul(soup, target_url)
        
        log("🧠 AI analizi başlatılıyor...")
        ai_sonuc = ai_ile_analiz(r.text, target_url)
        
        if ai_sonuc:
            ai_sonuc["web_url"] = target_url
            ai_sonuc["logo"] = logo_url
            log("💾 Airtable'a kaydediliyor...")
            sonuc = airtable_kaydet(ai_sonuc)
            log(sonuc)
        else:
            log("❌ AI veri üretemedi.")
            
    except Exception as e:
        log(f"⚠️ Kritik Hata ({target_url}): {e}")

if __name__ == "__main__":
    # --- İLK ÖRNEK SİTE ---
    # Bu sistem tamam olduktan sonra burayı toplu tarama için değiştireceğiz.
    hedef_site = "https://tsmglobal.com.tr/"
    
    firma_tara(hedef_site)
