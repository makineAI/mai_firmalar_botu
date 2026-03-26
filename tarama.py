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
MODEL_NAME = 'gemini-1.5-flash' # Kota dostu model

def log(msg):
    print(f">>> {msg}", flush=True)

def temiz_metin_al(html, limit=1000): # KRİTİK: Limit 1000'e indi
    soup = BeautifulSoup(html, 'html.parser')
    for tags in soup(["nav", "footer", "header", "script", "style", "aside", "iframe", "noscript"]):
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
    
    # Çok kısa ve net prompt
    prompt = f"JSON format: {target_url}. Content: {str(ham_veriler)}"
    
    for deneme in range(2):
        try:
            response = client_ai.models.generate_content(model=MODEL_NAME, contents=prompt)
            text = response.text.strip()
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception as e:
            if "429" in str(e):
                log(f"⚠️ KOTA: 90sn bekleniyor... (Deneme {deneme+1}/2)")
                time.sleep(90)
            else:
                log(f"❌ Hata: {e}")
                break
    return None

def airtable_kaydet(data, web_url):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_TOKEN}", "Content-Type": "application/json"}
    
    fields = {
        "firma_unvan": str(data.get("firma_unvan", "TSM Global")),
        "web_site": web_url,
        "kurumsal_hakkinda": str(data.get("kurumsal_hakkinda", "Analiz Başarılı")),
        "firma_turu": "İş Makineleri",
        "ai_firma_analizi": "BAĞLANTI TAMAMLANDI"
    }

    params = {"filterByFormula": f"{{web_site}} = '{web_url}'"}
    search = requests.get(url, headers=headers, params=params).json()

    if search.get("records"):
        rid = search["records"][0]["id"]
        requests.patch(f"{url}/{rid}", json={"fields": fields}, headers=headers)
        log(f"🔄 GÜNCELLENDİ: {web_url}")
    else:
        requests.post(url, json={"fields": fields}, headers=headers)
        log(f"✅ KAYIT EDİLDİ: {web_url}")

def siteyi_tara(target_url):
    log(f"🚀 Deneme Başlıyor: {target_url}")
    ham_veriler = {}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            soup = BeautifulSoup(page.content(), 'html.parser')
            
            # Sadece Hakkımızda sayfasına bakalım (Kota yememek için)
            hakkinda_url = link_bul(soup, ['hakkimizda', 'kurumsal'], target_url)
            if hakkinda_url:
                log(f"📄 Sadece Hakkında okunuyor: {hakkinda_url}")
                page.goto(hakkinda_url, timeout=30000)
                ham_veriler['hakkinda'] = temiz_metin_al(page.content())
            
            log("🧠 AI Test Ediliyor...")
            analiz = uzman_analizi(ham_veriler, target_url)
            if analiz:
                airtable_kaydet(analiz, target_url)
            else:
                log("❌ Kota hala izin vermiyor.")
        finally:
            browser.close()

if __name__ == "__main__":
    siteyi_tara("https://tsmglobal.com.tr/")
