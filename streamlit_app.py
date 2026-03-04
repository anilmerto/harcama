import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
from PIL import Image

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(page_title="Akıllı Masraf Asistanı", layout="wide", page_icon="🧾")

# --- VERİ VE AYAR YÖNETİMİ (SESSION STATE) ---
# Uygulama yenilendiğinde verilerin kaybolmaması için
if 'masraflar' not in st.session_state:
    st.session_state['masraflar'] = pd.DataFrame(columns=[
        "Tarih", "İşletme", "Fiş No", "Harcama Türü", "Kategori", 
        "Toplam Tutar", "KDV Oranı", "KDV Tutarı", "Dapgeon Payı", "Liniga Payı"
    ])

# Dinamik Kategori Ayarları (Varsayılanlar)
if 'kategoriler' not in st.session_state:
    st.session_state['kategoriler'] = {
        "Temsil": {"limit": 7000.0, "dapgeon_oran": 60, "liniga_oran": 40},
        "Audiovisual": {"limit": 7000.0, "dapgeon_oran": 60, "liniga_oran": 40},
        "Bölgesel": {"limit": 3000.0, "dapgeon_oran": 60, "liniga_oran": 40}
    }

# --- YAN PANEL: AYARLAR VE YENİ KATEGORİ EKLEME ---
with st.sidebar:
    st.header("⚙️ Sistem Ayarları")
    
    # API Anahtarı (Kullanıcının kendi Gemini API anahtarını girmesi için)
    api_key = st.text_input("Google Gemini API Anahtarı", type="password", help="Yapay zekanın fişleri okuyabilmesi için gereklidir.")
    if api_key:
        genai.configure(api_key=api_key)
    else:
        st.warning("Fiş okuma özelliği için API anahtarınızı girin.")

    st.divider()
    st.header("📌 Limit ve Oran Ayarları")
    
    # Mevcut Kategorileri Düzenleme
    for kat_adi in list(st.session_state['kategoriler'].keys()):
        with st.expander(f"{kat_adi} Ayarları", expanded=False):
            yeni_limit = st.number_input(f"Limit (TL) - {kat_adi}", value=float(st.session_state['kategoriler'][kat_adi]['limit']))
            dap_oran = st.slider(f"Dapgeon Oranı (%) - {kat_adi}", 0, 100, int(st.session_state['kategoriler'][kat_adi]['dapgeon_oran']))
            lin_oran = 100 - dap_oran
            st.info(f"Liniga Oranı: %{lin_oran}")
            
            # Ayarları Güncelle
            st.session_state['kategoriler'][kat_adi]['limit'] = yeni_limit
            st.session_state['kategoriler'][kat_adi]['dapgeon_oran'] = dap_oran
            st.session_state['kategoriler'][kat_adi]['liniga_oran'] = lin_oran

    st.divider()
    # Yeni Kategori Ekleme (Örn: İlaç Kalemi)
    st.subheader("➕ Yeni Kalem Ekle")
    yeni_kat_adi = st.text_input("Kategori Adı (Örn: İlaç)")
    if st.button("Kategoriyi Ekle") and yeni_kat_adi:
        if yeni_kat_adi not in st.session_state['kategoriler']:
            st.session_state['kategoriler'][yeni_kat_adi] = {"limit": 5000.0, "dapgeon_oran": 60, "liniga_oran": 40}
            st.success(f"'{yeni_kat_adi}' başarıyla eklendi! Sayfayı yenileyin.")
            st.rerun()

# --- ANA EKRAN ---
st.title("🧾 Akıllı Fiş Analiz ve Dağıtım Portalı")
st.markdown("Fiş fotoğrafını yükleyin, yapay zeka detayları okusun ve belirlediğiniz oranlara göre dağıtsın.")

# 1. Fiş Yükleme
uploaded_file = st.file_uploader("Fiş veya Fatura Fotoğrafı Yükle", type=['png', 'jpg', 'jpeg'])

if uploaded_file is not None:
    col_img, col_form = st.columns([1, 2])
    
    with col_img:
        image = Image.open(uploaded_file)
        st.image(image, caption="Yüklenen Fiş", use_column_width=True)
    
    with col_form:
        st.subheader("🤖 Yapay Zeka Analizi")
        
        # Yapay Zeka ile Veri Çekme Butonu
        if st.button("Fişi Okut ve Analiz Et", type="primary"):
            if not api_key:
                st.error("Lütfen sol menüden API anahtarınızı giriniz!")
            else:
                with st.spinner("Yapay zeka fişi inceliyor, lütfen bekleyin..."):
                    try:
                        # Gemini Modeli Çağrısı
                        model = genai.GenerativeModel('gemini-2.5-flash')
                        prompt = """
                        Bu fiş/fatura görüntüsünü analiz et ve aşağıdaki bilgileri çıkar. Sadece geçerli bir JSON formatında yanıt ver. Markdown veya fazladan metin kullanma.
                        Format:
                        {
                          "isletme": "Dükkan veya Firma adı",
                          "fis_no": "Fiş veya Fatura numarası (yoksa boş bırak)",
                          "tarih": "Tarih (GG.AA.YYYY)",
                          "harcama_turu": "Harcamanın tahmini türü (Gıda, Restoran, Kırtasiye vb.)",
                          "toplam_tutar": 150.50,
                          "kdv_orani": 10,
                          "kdv_tutari": 15.05
                        }
                        Tutar ve KDV kısımları kesinlikle sayı (float) olmalıdır.
                        """
                        response = model.generate_content([prompt, image])
                        
                        # Yanıttan JSON formatını temizleyip ayıklama
                        json_str = response.text.replace("```json", "").replace("```", "").strip()
                        ai_data = json.loads(json_str)
                        
                        # Geçici olarak session_state'e kaydet (düzenlenebilir olması için)
                        st.session_state['ai_data'] = ai_data
                        st.success("Analiz başarılı! Lütfen bilgileri kontrol edin.")
                    except Exception as e:
                        st.error(f"Okuma sırasında bir hata oluştu: {e}")
                        st.session_state['ai_data'] = {}

        # Düzenlenebilir Form (AI yanlış okursa düzeltmek için)
        ai_data = st.session_state.get('ai_data', {})
        
        with st.form("masraf_formu"):
            f_col1, f_col2 = st.columns(2)
            with f_col1:
                isletme = st.text_input("İşletme Adı", value=ai_data.get("isletme", ""))
                fis_no = st.text_input("Fiş/Fatura No", value=ai_data.get("fis_no", ""))
                tarih = st.text_input("Tarih", value=ai_data.get("tarih", ""))
                harcama_turu = st.text_input("Harcama Türü", value=ai_data.get("harcama_turu", ""))
            with f_col2:
                toplam_tutar = st.number_input("Toplam Tutar (TL)", value=float(ai_data.get("toplam_tutar", 0.0)), step=10.0)
                kdv_orani = st.number_input("KDV Oranı (%)", value=float(ai_data.get("kdv_orani", 0.0)), step=1.0)
                kdv_tutari = st.number_input("KDV Tutarı (TL)", value=float(ai_data.get("kdv_tutari", 0.0)), step=1.0)
                secilen_kategori = st.selectbox("Harcama Kategorisi (Limit Kalemi)", list(st.session_state['kategoriler'].keys()))

            submit_button = st.form_submit_button("Sisteme Kaydet ve Paylaştır")
            
            if submit_button and toplam_tutar > 0:
                # Dağıtım Hesaplaması
                oranlar = st.session_state['kategoriler'][secilen_kategori]
                dapgeon_payi = round(toplam_tutar * (oranlar['dapgeon_oran'] / 100), 2)
                liniga_payi = round(toplam_tutar * (oranlar['liniga_oran'] / 100), 2)
                
                # DataFrame'e Ekleme
                yeni_kayit = {
                    "Tarih": tarih,
                    "İşletme": isletme,
                    "Fiş No": fis_no,
                    "Harcama Türü": harcama_turu,
                    "Kategori": secilen_kategori,
                    "Toplam Tutar": toplam_tutar,
                    "KDV Oranı": kdv_orani,
                    "KDV Tutarı": kdv_tutari,
                    "Dapgeon Payı": dapgeon_payi,
                    "Liniga Payı": liniga_payi
                }
                
                st.session_state['masraflar'] = pd.concat([st.session_state['masraflar'], pd.DataFrame([yeni_kayit])], ignore_index=True)
                st.success(f"{toplam_tutar} TL, {secilen_kategori} kalemine başarıyla eklendi! (Dapgeon: {dapgeon_payi} TL | Liniga: {liniga_payi} TL)")
                st.session_state['ai_data'] = {} # Formu temizle

# --- GİRİLEN MASRAFLAR VE BÜTÇE TAKİBİ ---
st.divider()
st.header("📊 Masraf Listesi ve Bütçe Durumu")

tab1, tab2 = st.tabs(["Girilen Fişler", "Bütçe ve Limit Raporu"])

with tab1:
    if not st.session_state['masraflar'].empty:
        st.dataframe(st.session_state['masraflar'], use_container_width=True)
        
        # Excel Olarak İndirme
        csv = st.session_state['masraflar'].to_csv(index=False).encode('utf-8')
        st.download_button("Excel/CSV Olarak İndir", data=csv, file_name='masraflar.csv', mime='text/csv')
    else:
        st.info("Henüz sisteme kaydedilmiş bir masraf bulunmuyor.")

with tab2:
    if not st.session_state['masraflar'].empty:
        # Kategori bazlı toplam harcamaları hesapla
        kategori_toplam = st.session_state['masraflar'].groupby('Kategori')['Toplam Tutar'].sum().reset_index()
        
        for _, row in kategori_toplam.iterrows():
            kat = row['Kategori']
            harcanan = row['Toplam Tutar']
            limit = st.session_state['kategoriler'][kat]['limit']
            kalan = limit - harcanan
            yuzde = min((harcanan / limit) * 100, 100) if limit > 0 else 100
            
            st.markdown(f"**{kat} Kalemi:** {harcanan:,.2f} TL / {limit:,.2f} TL (Kalan: {kalan:,.2f} TL)")
            st.progress(yuzde / 100)
            
            if kalan < 0:
                st.error(f"⚠️ DİKKAT: {kat} kaleminde limit {abs(kalan):,.2f} TL aşıldı!")
    else:
         st.info("Bütçe durumu hesaplanması için veri bekleniyor.")
