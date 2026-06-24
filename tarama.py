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
# KENDİ TABLE ID'Nİ BURAYA YAZDIĞINDAN EMİN OL (Örn: tblDEF456QWE)
AIRTABLE_TABLE_NAME = "mai_firmalar" 
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# ANA DİSTRİBÜTÖR LİSTESİ (TSM kapalı, Ascendum ve Borusan aktif)
FIRMA_LISTESI = [
    # {"unvan": "TSM GLOBAL TURKEY Makina Sanayi ve Ticaret A.Ş.", "url": "https://tsmglobal.com.tr/"}, # ScraperAPI Ücretli Plan İstiyor
    {"unvan": "ASCENDUM MAKİNA TİC. A.Ş.", "url": "https://www.ascendum.com.tr"},
    {"unvan": "BORUSAN MAKİNA VE GÜÇ SİSTEMLERİ SAN. VE TİC. A.Ş.", "url": "https://www.borusanmakina.com"}
]

def scraperapi_ile_metin_cek(hedef_url):
    """Standart render ayarlarıyla koruması normal düzeydeki siteleri tarar."""
    # Premium parametreleri kaldırıldı, standart ücretsiz sürüme dönüldü
    proxy_url = f"http://api.scraperapi.com/?api_key={SCRAPER_API_KEY}&url={urllib.parse.quote(hedef_url)}&render=true"
    try:
        response = requests.get(proxy_url, timeout=60) 
        
        if response.status_code != 200:
            print(f"❌ ScraperAPI Bağlantı Hatası! Durum Kodu: {response.status_code}")
            print(f"Hata Detayı: {response.text}")
            return "", ""
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        logo_url = ""
        img_tags = soup.find_all('img')
        for img in img_tags:
            src = img.get('src', '').lower()
            if 'logo' in src and (src.endswith('.png') or src.endswith('.jpg') or src.endswith('.jpeg') or src.endswith('.svg') or src.endswith('.webp')):
                logo_url = img.get('src')
                if logo_url and not logo_url.startswith('http'):
                    logo_url = urllib.parse.urljoin(hedef_url, logo_url)
                break

        for element in soup(["script", "style", "iframe", "nav", "footer"]):
            element.extract()
            
        ham_metin = soup.get_text(separator=' ', strip=True)
        temiz_metin = ' '.join(ham_metin.split())
        return temiz_metin[:8000], logo_url 
    except Exception as e:
        print(f"⚠️ {hedef_url} sitesine bağlanırken sistem hatası oluştu: {e}")
        return "", ""

def gemini_ile_analiz_et(site_metni, firma_unvan, ana_url):
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""
    Aşağıda, Türkiye'deki bir iş/istif makinesi firmasının web sitesinden kazınmış ham bir metin bulunmaktadır. 
    Bu metni bir sektör uzmanı gibi incele ve senden istenen bilgileri kesinlikle belirtilen JSON formatında çıktı olarak ver. 
    Başka hiçbir açıklama yazısı ekleme, sadece saf JSON döndür.

    Firma Resmi Ünvanı: {firma_unvan}
    Firma Web Sitesi: {ana_url}
    Siteden Çekilen Ham Metin:
    \"\"\"{site_metni}\"\"\"

    Senden İstenen JSON Formatı ve Kuralları:
    {{
        "Kurumsal_Hakkinda": "Firmanın tarihçesi, vizyonu ve sektördeki konumunu anlatan akıcı bir Türkçe kurumsal tanıtım yazısı.",
        "Marka_ve_Urun_Portfoyu": "Firmanın distribütörü olduğu veya sattığı tüm markaları tespit et. Her bir markanın altına hangi tip makineleri sattığını detaylıca açıkla. Markdown kullan (Örn: **Volvo İş Makinaları:** Türkiye resmi distribütörü olarak paletli ekskavatörler... şeklinde).",
        "Iletisim_Merkez": "Firmanın genel müdürlük telefon, e-posta ve açık adres bilgilerini içeren temiz bir metin bloku.",
        "Bayiler_Subeler": "Metin içerisinde geçiyorsa firmanın sahip olduğu bölge müdürlükleri, servis noktaları veya bayi listesini içeren Markdown formatında liste. Yoksa boş bırak."
    }}
    """
    
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }
    
    bekleme_suresi = 15
    for deneme in range(5): 
        try:
            res = requests.post(api_url, headers=headers, json=payload, timeout=60) 
            
            if res.status_code == 200:
                res_json = res.json()
                if 'candidates' in res_json and len(res_json['candidates']) > 0:
                    try:
                        raw_response = res_json['candidates'][0]['content']['parts'][0]['text']
                        clean_response = raw_response.replace('```json', '').replace('```', '').strip()
                        return json.loads(clean_response)
                    except KeyError:
                        print(f"❌ Gemini JSON yapısı okunamadı: {res_json}")
                        return None
                else:
                    print(f"❌ Gemini boş veya hatalı yanıt döndürdü: {res_json}")
                    return None
                    
            elif res.status_code in [503, 500, 429]:
                print(f"⏳ Google sunucuları meşgul (Kod: {res.status_code}). {deneme + 1}. deneme başarısız... {bekleme_suresi} saniye bekleniyor...")
                time.sleep(bekleme_suresi)
                bekleme_suresi += 15 
            else:
                print(f"❌ Gemini API Hatası (Kod: {res.status_code}): {res.text}")
                return None
        except Exception as e:
            print(f"❌ Yapay zeka analizi sırasında hata: {e}")
            return None
            
    print("⚠️ 5 deneme de başarısız oldu. Google sunucuları cevap vermiyor, atlanıyor...")
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
        print(f"✅ BAŞARI: {fields.get('Firma_Unvan')} Airtable'a kusursuz işlendi.")
    else:
        print(f"❌ Airtable Hatası ({fields.get('Firma_Unvan')}): {res.text}")

def main():
    anahtarlar = {
        "AIRTABLE_API_KEY": AIRTABLE_API_KEY,
        "AIRTABLE_BASE_ID": AIRTABLE_BASE_ID,
        "SCRAPER_API_KEY": SCRAPER_API_KEY,
        "GEMINI_API_KEY": GEMINI_API_KEY
    }
    
    eksik_anahtarlar = [isim for isim, deger in anahtarlar.items() if not deger]
    
    if eksik_anahtarlar:
        print(f"❌ EKSİK ŞİFRE TESPİT EDİLDİ!")
        print(f"GitHub Secrets içinde şu anahtarlar bulunamadı veya boş: {', '.join(eksik_anahtarlar)}")
        sys.exit(1)
        
    print(f"🚀 MAI Yapay Zeka Destekli Firma Veri Madenciliği Başlatıldı...")
    print(f"📋 İşlemdeki firma sayısı: {len(FIRMA_LISTESI)}\n" + "-"*50)
    
    for firma in FIRMA_LISTESI:
        print(f"🔍 Taranıyor: {firma['unvan']} ({firma['url']})")
        
        site_metni, bulunan_logo = scraperapi_ile_metin_cek(firma['url'])
        
        if not site_metni:
            print(f"⚠️ Siteden metin içeriği sökülemedi, atlanıyor...")
            continue
            
        print("🧠 Yapay zeka marka portföyünü detaylandırıyor (PRO Model)...")
        ai_raporu = gemini_ile_analiz_et(site_metni, firma_unvan=firma['unvan'], ana_url=firma['url'])
        
        if not ai_raporu:
            print("⚠️ Yapay zeka analizi başarısız oldu, atlanıyor...")
            continue
            
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
