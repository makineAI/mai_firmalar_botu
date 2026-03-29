import os, sys, json, requests, re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from google import genai

# --- GÜVENLİ YAPILANDIRMA (GitHub Secrets'tan Çekilir) ---
AIRTABLE_TOKEN = os.environ.get('AIRTABLE_TOKEN')
AIRTABLE_BASE_ID = os.environ.get('AIRTABLE_BASE_ID', "appC4JNkqLfVCEcna")
AIRTABLE_TABLE_NAME = os.environ.get('AIRTABLE_TABLE_NAME', "tbldmaqYiPXpH7IZ2")
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

# Yeni SDK ve Ücretli Pro Model Tanımlaması
client_ai = genai.Client(api_key=GEMINI_API_KEY)
MODEL_NAME = 'gemini-2.5-pro' # Hız sınırları kalktı, en zeki modeli kullanıyoruz

def log(msg):
    print(f">>> {msg}", flush=True)

def temiz_metin_al(html, limit=50000): 
    """Gereksiz kodları temizler, sadece saf metni alır. Limit 50 bin karaktere çıkarıldı."""
    soup = BeautifulSoup(html, 'html.parser')
    for tags in soup(["nav", "footer", "header", "script", "style", "aside", "iframe", "noscript"]):
        tags.extract()
    text = soup.get_text(separator=' ', strip=True)
    text = re.sub(r'\s+', ' ', text)
    return text[:limit]

def link_bul(soup, keywords, base_url):
    """Site içindeki hedef sayfaları (Hakkımızda, Markalar vb.) bulur."""
    for a in soup.find_all('a', href=True):
        text = a.get_text().lower()
        href = a['href'].lower()
        if any(kw in text for kw in keywords) or any(kw in href for kw in keywords):
            return urljoin(base_url, a['href'])
    return None

def uzman_analizi(ham_veriler, target_url):
    """Gemini Pro'ya devasa veriyi gönderir ve JSON formatında yanıt alır."""
    if not any(ham_veriler.values()): 
        return None
    
    prompt = f"""
    Sen bir İş Makinesi Sektör Analistisin. Aşağıdaki web sitesi verilerini analiz et ve SADECE geçerli bir JSON formatında yanıt ver. 
    Açıklama veya markdown (```json) kullanma, doğrudan süslü parantez ile başla.
    
    Hedef Site: {target_url}
    Veriler: {str(ham_veriler)}

    İstenen Format:
    {{
        "firma_unvan": "Tam Ticari Ünvan (Örn: TSM Global Turkey Makine A.Ş.)",
        "kurumsal_hakkinda": "Firma hakkında 2 cümlelik sektörel özet",
        "markalar": ["Marka1", "Marka2"],
        "firma_turu": "Distribütör, Servis veya Kiralama"
    }}
    """
    
    try:
        # Kota bekleme süreleri (sleep) tamamen kaldırıldı!
        response = client_ai.models.generate_content(model=MODEL_NAME, contents=prompt)
        text = response.text.strip()
        
        # Sadece JSON kısmını güvenli bir şekilde çek
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        else:
            log("❌ AI yanıtı JSON formatında değildi.")
            return None
            
    except Exception as e:
        log(f"❌ AI Analiz Hatası: {e}")
        return None

def airtable_kaydet(data, web_url):
    """Veriyi Airtable'a 'Upsert' (Varsa güncelle, yoksa ekle) mantığıyla yazar."""
    url = f"[https://api.airtable.com/v0/](https://api.airtable.com/v0/){AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_TOKEN}", "Content-Type": "application/json"}
    
    fields = {
        "firma_unvan": data.get("firma_unvan", "Bilinmiyor"),
        "web_site": web_url,
        "kurumsal_hakkinda": data.get("kurumsal_hakkinda", ""),
        "firma_turu": data.get("firma_turu", "İş Makineleri"),
        "ai_markalar": ", ".join(data.get("markalar", [])) if data.get("markalar") else ""
    }

    try:
        # Site daha önce eklenmiş mi kontrol et
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
    """Sitenin kritik sayfalarını gezip veriyi toplar ve analiz zincirini başlatır."""
    log(f"🚀 PRO Analiz Başlıyor: {target_url}")
    ham_veriler = {}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Gerçek bir tarayıcı gibi davranması için User-Agent eklendi
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        page = context.new_page()
        
        try:
            # 1. Ana Sayfa Taraması
            page.goto(target_url, wait_until="networkidle", timeout=60000)
            soup = BeautifulSoup(page.content(), 'html.parser')
            ham_veriler['anasayfa'] = temiz_metin_al(page.content(), 20000) # Büyük veri havuzu
            
            # 2. Hakkımızda veya Markalar Sayfası Taraması
            hakkinda_url = link_bul(soup, ['hakkimizda', 'kurumsal', 'markalar', 'temsilcilik'], target_url)
            
            if hakkinda_url:
                log(f"📄 Alt sayfa taranıyor: {hakkinda_url}")
                page.goto(hakkinda_url, wait_until="domcontentloaded", timeout=30000)
                ham_veriler['detay'] = temiz_metin_al(page.content(), 30000) # Toplam 50k karakter
            
            log("🧠 Veriler Gemini Pro'ya gönderiliyor...")
            analiz = uzman_analizi(ham_veriler, target_url)
            
            if analiz:
                log(f"📊 Analiz Başarılı: {analiz.get('firma_unvan')}")
                airtable_kaydet(analiz, target_url)
            else:
                log("❌ Analiz başarısız oldu (Geçerli veri dönmedi).")
                
        except Exception as e:
            log(f"❌ Tarama sırasında hata oluştu: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    # Test için TSM Global
    siteyi_tara("[https://www.tsmglobal.com.tr](https://www.tsmglobal.com.tr)")
