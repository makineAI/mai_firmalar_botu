import os
import json
import requests
import sys
import urllib.parse
import time
from bs4 import BeautifulSoup

# ÇEVRESEL DEĞİŞKENLER
AIRTABLE_API_KEY = os.environ.get("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")
AIRTABLE_TABLE_NAME = "mai_firmalar" 
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# SADECE ASCENDUM AKTİF
FIRMA_LISTESI = [
    {"unvan": "ASCENDUM MAKİNA TİC. A.Ş.", "url": "https://www.ascendum.com.tr"}
]

def alt_sayfa_metni_cek(alt_url):
    """Bulunan iletişim veya kurumsal alt sayfalarının metnini çeker."""
    proxy_url = f"http://api.scraperapi.com/?api_key={SCRAPER_API_KEY}&url={urllib.parse.quote(alt_url)}&render=true"
    try:
        res = requests.get(proxy_url, timeout=40)
        if res.status_code == 200:
            soup = BeautifulSoup(res.content, 'html.parser')
            for element in soup(["script", "style", "iframe", "nav", "footer"]):
                element.extract()
            return ' '.join(soup.get_text(separator=' ', strip=True).split())
    except Exception:
        pass
    return ""

def scraperapi_ile_metin_cek(hedef_url):
    """Ana sayfayı ve önemli alt sayfaları (İletişim, Kurumsal) derinlemesine tarar."""
    proxy_url = f"http://api.scraperapi.com/?api_key={SCRAPER_API_KEY}&url={urllib.parse.quote(hedef_url)}&render=true"
    try:
        response = requests.get(proxy_url, timeout=60) 
        
        if response.status_code != 200:
            print(f"❌ ScraperAPI Bağlantı Hatası! Durum Kodu: {response.status_code}")
            return "", ""
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Logo tespiti
        logo_url = ""
        img_tags = soup.find_all('img')
        for img in img_tags:
            src = img.get('src', '').lower()
            if 'logo' in src and (src.endswith('.png') or src.endswith('.jpg') or src.endswith('.jpeg') or src.endswith('.svg') or src.endswith('.webp')):
                logo_url = img.get('src')
                if logo_url and not logo_url.startswith('http'):
                    logo_url = urllib.parse.urljoin(hedef_url, logo_url)
                break

        # Alt sayfaları (linkleri) arama
        iletisim_url = None
        kurumsal_url = None
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            tam_link = urllib.parse.urljoin(hedef_url, a['href'])
            
            if not iletisim_url and any(k in href for k in ['iletisim', 'contact', 'ulasin', 'bize-ulasin']):
                iletisim_url = tam_link
            if not kurumsal_url and any(k in href for k in ['hakkimizda', 'kurumsal', 'about', 'hakkinda']):
                kurumsal_url = tam_link

        # Ana sayfa temizliği
        for element in soup(["script", "style", "iframe", "nav", "footer"]):
            element.extract()
            
        ham_metin = soup.get_text(separator=' ', strip=True)
        temiz_metin = ' '.join(ham_metin.split())
        
        # Derin Tarama: Bulunan alt sayfaları da kazı ve ana metne ekle
        ek_metin = ""
        if kurumsal_url:
            print(f"   [+] Kurumsal sayfa bulundu ve taranıyor: {kurumsal_url}")
            ek_metin += " [KURUMSAL SAYFA VERİSİ]: " + alt_sayfa_metni_cek(kurumsal_url)
            
        if iletisim_url:
            print(f"   [+] İletişim sayfası bulundu ve taranıyor: {iletisim_url}")
            ek_metin += " [İLETİŞİM SAYFASI VERİSİ]: " + alt_sayfa_metni_cek(iletisim_url)

        toplam_metin = temiz_metin + " " + ek_metin
        # Limit 15000 karaktere çıkarıldı ki alt sayfalar sığsın
        return toplam_metin[:15000], logo_url 
        
    except Exception as e:
        print(f"⚠️ {hedef_url} sitesine bağlanırken sistem hatası oluştu: {e}")
        return "", ""

def gemini_ile_analiz_et(site_metni, firma_unvan, ana_url):
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""
    Aşağıda, Türkiye'deki bir iş/istif makinesi firmasının ana sayfasından, kurumsal sayfasından ve iletişim sayfasından derlenmiş devasa bir ham metin bulunmaktadır. 
    Bu metni bir sektör uzmanı gibi incele ve senden istenen bilgileri kesinlikle belirtilen JSON formatında çıktı olarak ver. Başka açıklama ekleme.

    Firma Resmi Ünvanı: {firma_unvan}
    Firma Web Sitesi: {ana_url}
    Siteden Çekilen Ham Metin:
    \"\"\"{site_metni}\"\"\"

    Senden İstenen JSON Formatı ve Kuralları:
    {{
        "Kurumsal_Hakkinda": "Firmanın tarihçesi, vizyonu ve sektördeki konumunu anlatan, metindeki tüm detayların harmanlandığı, detaylı ve uzun bir Türkçe kurumsal tanıtım yazısı (en az 3-4 paragraf yaz).",
        "Marka_ve_Urun_Portfoyu": "Firmanın distribütörü olduğu tüm markaları tespit et. Her bir markanın altına hangi tip makineleri sattığını detaylıca açıkla. Markdown kullan.",
        "Iletisim_Merkez": "Metin içerisinde geçen telefon numaralarını, e-posta adreslerini (info@... vs) ve genel müdürlük açık adresini KESİNLİKLE atlamadan, eksiksiz bir metin bloku halinde yaz.",
        "Bayiler_Subeler": "Metin içerisinde firmanın sahip olduğu bölge müdürlükleri, servis noktaları veya bayiler geçiyorsa şehir şehir ayırarak Markdown formatında detaylıca yaz."
    }}
    """
    
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }
    
    bekleme_suresi = 10
    for deneme in range(4): 
        try:
            res = requests.post(api_url, headers=headers, json=payload, timeout=40) 
            if res.status_code == 200:
                res_json = res.json()
                if 'candidates' in res_json and len(res_json['candidates']) > 0:
                    raw_response = res_json['candidates'][0]['content']['parts'][0]['text']
                    clean_response = raw_response.replace('```json', '').replace('```', '').strip()
                    return json.loads(clean_response)
            elif res.status_code in [503, 500, 429]:
                print(f"⏳ Google sunucuları anlık yoğun. {deneme + 1}. deneme... {bekleme_suresi} sn bekleniyor...")
                time.sleep(bekleme_suresi)
            else:
                return None
        except Exception:
            pass
    return None

def airtable_tablosuna_yaz(fields):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }
    
    logo_url = fields.get("Logo_Temp")
    gorsel_payload = [{"url": logo_url}] if logo_url and logo_url.startswith("http") else []
    
    payload = {"fields": {
        "Firma_Unvan": fields.get("Firma_Unvan"),
        "Firma_Turu": "Ana Distribütör",
        "Web_Sitesi": fields.get("Web_Sitesi"),
        "Logo": gorsel_payload,
        "Kurumsal_Hakkinda": fields.get("Kurumsal_Hakkinda"),
        "Marka_ve_Urun_Portfoyu": fields.get("Marka_ve_Urun_Portfoyu"),
        "Iletisim_Merkez": fields.get("Iletisim_Merkez"),
        "Bayiler_Subeler": fields.get("Bayiler_Subeler")
    }}
    
    res = requests.post(url, headers=headers, json=payload)
    if res.status_code == 200:
        print(f"✅ BAŞARI: {fields.get('Firma_Unvan')} daha zengin detaylarla Airtable'a işlendi!")
    else:
        print(f"❌ Airtable Hatası: {res.text}")

def main():
    print(f"🚀 MAI Yapay Zeka Destekli Derin Firma Taraması Başlatıldı...")
    print("-" * 50)
    
    for firma in FIRMA_LISTESI:
        print(f"🔍 Taranıyor: {firma['unvan']} ({firma['url']})")
        
        site_metni, bulunan_logo = scraperapi_ile_metin_cek(firma['url'])
        if not site_metni: continue
            
        print("🧠 Yapay zeka tüm verileri harmanlıyor...")
        ai_raporu = gemini_ile_analiz_et(site_metni, firma_unvan=firma['unvan'], ana_url=firma['url'])
        if not ai_raporu: continue
            
        final_fields = {
            "Firma_Unvan": firma['unvan'],
            "Web_Sitesi": firma['url'],
            "Logo_Temp": bulunan_logo,
            "Kurumsal_Hakkinda": ai_raporu.get("Kurumsal_Hakkinda", ""),
            "Marka_ve_Urun_Portfoyu": ai_raporu.get("Marka_ve_Urun_Portfoyu", ""),
            "Iletisim_Merkez": ai_raporu.get("Iletisim_Merkez", ""),
            "Bayiler_Subeler": ai_raporu.get("Bayiler_Subeler", "")
        }
        airtable_tablosuna_yaz(final_fields)
        print("-" * 50)

if __name__ == "__main__":
    main()
