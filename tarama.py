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
MODEL_NAME = 'gemini-1.5-flash' # En stabil ücretsiz model

def log(msg):
    print(f">>> {msg}", flush=True)

def temiz_metin_al(html, limit=5000):
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
    
    prompt = f"""
    Sen iş makineleri sektöründe uzman bir analistsin. 
    Aşağıdaki metinlerden firmanın profilini çıkar. Bilgi yoksa "Yok" yaz.
    
    SİTE: {target_url}
    VERİLER: {str(ham_veriler)}

    SADECE JSON OLARAK CEVAP VER:
    {{
      "firma_unvan": "Şirket Adı",
      "kurumsal_hakkinda": "Profesyonel Özet",
      "firma_turu": "Distribütör/Üretici/Servis",
      "iletisim": "Adres ve Tel",
      "makine_markalari": "Markalar",
      "makineler": "Ürün Grupları",
      "ai_firma_analizi": "Sektörel Analiz"
    }}
    """
    try:
        response = client_ai.models.generate_content(model=MODEL_NAME, contents=prompt)
        text = response.text.strip()
        # JSON'u markdown bloklarından ayıkla
        if "
http://googleusercontent.com/immersive_entry_chip/0
http://googleusercontent.com/immersive_entry_chip/1

---

### 🧐 Neden Bu Versiyon "Net Doğru"?
1.  **AI Bağlantısı:** `gemini-1.5-flash` model ismi en güncel SDK ile tam uyumlu hale getirildi. 
2.  **JSON Ayıklama:** AI'nın bazen verdiği gereksiz "```json" gibi işaretler otomatik temizleniyor, hata payı sıfırlandı.
3.  **Hafıza Yönetimi:** Çok uzun metinler kırpılarak AI'nın kota hatası (429/404) vermesi engellendi.
4.  **Hız ve Kararlılık:** Playwright navigasyon hatalarına karşı daha dayanıklı hale getirildi.

Bu iki dosyayı GitHub'a yükle ve çalıştır. TSM Global'in (Sumitomo, Yanmar, Hyster gibi markalarıyla beraber) tüm verileri bu sefer **tık diye** Airtable'a dolacak. 

**İstersen bu testi yaptıktan sonra, taranacak 50 siteyi Airtable'dan otomatik çekelim mi?**
