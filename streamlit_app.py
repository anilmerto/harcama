import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import io
import base64
from PIL import Image
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
import streamlit_authenticator as stauth
import plotly.express as px
from fpdf import FPDF
import re

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(page_title="Akıllı Masraf Portalı", layout="wide", page_icon="🧾")

# --- KİMLİK DOĞRULAMA (LOGIN) SİSTEMİ ---
try:
    credentials_dict = {"usernames": {}}
    users = dict(st.secrets["credentials"]["usernames"])
    
    for u_name, u_info in users.items():
        plain_pass = str(u_info["password"]).strip()
        credentials_dict["usernames"][u_name] = {
            "email": u_info.get("email", ""),
            "name": u_info.get("name", u_name),
            "password": plain_pass
        }

    stauth.Hasher.hash_passwords(credentials_dict)

    authenticator = stauth.Authenticate(
        credentials_dict,
        st.secrets["cookie"]["name"],
        st.secrets["cookie"]["key"],
        st.secrets["cookie"]["expiry_days"]
    )
    
    authenticator.login()
except Exception as e:
    st.error(f"Giriş sistemi yapılandırılamadı. Hata detayı: {e}")
    st.stop()

auth_status = st.session_state.get("authentication_status")

if auth_status is False:
    st.error("Kullanıcı adı veya şifre hatalı!")
    st.stop()
elif auth_status is None:
    st.info("Lütfen işlem yapabilmek için giriş yapın.")
    st.stop()

name = st.session_state.get("name")
username = st.session_state.get("username")
is_admin = (username == 'admin')

# --- ÇIKIŞ BUTONU VE KARŞILAMA ---
authenticator.logout('Çıkış Yap', 'sidebar')
st.sidebar.write(f"Hoş geldin, *{name}* 👋")

# --- FIREBASE VERİTABANI BAĞLANTISI ---
@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        cred_dict = dict(st.secrets["firebase"])
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
    return firestore.client()

try:
    db = init_firebase()
except Exception as e:
    st.error("Veritabanı bağlantısı kurulamadı. Firebase Secrets ayarlarını kontrol edin.")
    st.stop()

# --- GEMINI YZ YAPILANDIRMASI ---
try:
    genai.configure(api_key=st.secrets["gemini"]["api_key"])
except:
    st.sidebar.error("Gemini API Anahtarı 'Secrets' içinde bulunamadı!")

# --- YARDIMCI FONKSİYONLAR ---
def compress_and_encode_image(image):
    img = image.copy()
    img.thumbnail((800, 800))
    buffered = io.BytesIO()
    img.save(buffered, format="JPEG", quality=70)
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

# 15'inden 15'ine Dönem Hesaplama Fonksiyonu
def get_donem(tarih_str):
    try:
        t_str = str(tarih_str).replace('/', '.').replace('-', '.')
        parts = t_str.split('.')
        if len(parts) >= 3:
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            if year < 100: year += 2000
            
            aylar = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
            
            if day >= 15:
                bas_ay, bas_yil = month, year
                bit_ay = month + 1 if month < 12 else 1
                bit_yil = year if month < 12 else year + 1
            else:
                bas_ay = month - 1 if month > 1 else 12
                bas_yil = year if month > 1 else year - 1
                bit_ay, bit_yil = month, year
                
            return f"15 {aylar[bas_ay]} {bas_yil} - 15 {aylar[bit_ay]} {bit_yil}"
    except:
        pass
    return "Bilinmeyen Dönem"

def get_expenses(fetch_all=False, user_id=None):
    expenses_ref = db.collection('masraflar')
    if not fetch_all:
        query = expenses_ref.where('username', '==', user_id).stream()
    else:
        query = expenses_ref.stream()
    
    data = []
    for doc in query:
        item = doc.to_dict()
        item['id'] = doc.id
        
        item['kategori'] = item.get('kategori', item.get('Kategori', 'Bilinmeyen'))
        item['İlaç'] = item.get('marka', item.get('İlaç', 'Bilinmeyen'))
        item['toplam_tutar'] = float(item.get('toplam_tutar', item.get('Toplam Tutar', 0.0)))
        item['isletme'] = item.get('isletme', item.get('İşletme', 'Bilinmeyen'))
        item['fis_no'] = item.get('fis_no', item.get('Fiş No', ''))
        item['tarih'] = item.get('tarih', item.get('Tarih', ''))
        item['kullanici_adi'] = item.get('kullanici_adi', item.get('username', 'Bilinmeyen'))
        item['Dönem'] = get_donem(item['tarih'])
        
        data.append(item)
    return data

# Türkçe karakterleri İngilizce'ye çevirerek PDF font çökmesini önleme
def safe_text(text):
    text = str(text)
    donusum = {"ı": "i", "İ": "I", "ş": "s", "Ş": "S", "ğ": "g", "Ğ": "G", "ü": "u", "Ü": "U", "ö": "o", "Ö": "O", "ç": "c", "Ç": "C"}
    for tr, en in donusum.items():
        text = text.replace(tr, en)
    return text

def create_pdf_report(df, donem, isim):
    pdf = FPDF()
    pdf.add_page()
    
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, safe_text(f"Harcama Raporu - {isim}"), ln=True, align='C')
    pdf.set_font("Arial", '', 12)
    pdf.cell(0, 10, safe_text(f"Donem: {donem}"), ln=True, align='C')
    pdf.ln(10)
    
    toplam = df['toplam_tutar'].sum()
    pdf.cell(0, 10, safe_text(f"Toplam Harcama: {toplam:,.2f} TL"), ln=True)
    pdf.ln(5)
    
    pdf.set_font("Arial", 'B', 10)
    col_widths = [25, 35, 35, 65, 30]
    headers = ["Tarih", "Kategori", "Ilac", "Isletme", "Tutar(TL)"]
    for w, h in zip(col_widths, headers):
        pdf.cell(w, 10, h, border=1, align='C')
    pdf.ln()
    
    pdf.set_font("Arial", '', 9)
    for _, row in df.iterrows():
        pdf.cell(col_widths[0], 10, safe_text(row['tarih']), border=1)
        pdf.cell(col_widths[1], 10, safe_text(row['kategori'])[:18], border=1)
        pdf.cell(col_widths[2], 10, safe_text(row['İlaç'])[:18], border=1)
        pdf.cell(col_widths[3], 10, safe_text(row['isletme'])[:35], border=1)
        pdf.cell(col_widths[4], 10, f"{row['toplam_tutar']:,.2f}", border=1, align='R')
        pdf.ln()
        
    # PDF'yi güvenli bytes formatına çevir (Telefonda indirme hatasını engeller)
    return bytes(pdf.output(dest='S').encode('latin-1', 'ignore'))

# --- VERİ VE AYAR YÖNETİMİ ---
if 'kategoriler' not in st.session_state:
    st.session_state['kategoriler'] = {
        "Temsil": {"limit": 7000.0, "dapgeon_oran": 60, "liniga_oran": 40},
        "Audiovisual": {"limit": 7000.0, "dapgeon_oran": 60, "liniga_oran": 40},
        "Bölgesel": {"limit": 3000.0, "dapgeon_oran": 60, "liniga_oran": 40}
    }

if 'markalar' not in st.session_state:
    st.session_state['markalar'] = ["Dapgeon", "Liniga"]

# --- YAN PANEL: AYARLAR (SADECE ADMİN) ---
if is_admin:
    st.sidebar.divider()
    st.sidebar.header("⚙️ Sistem Ayarları")
    
    st.sidebar.subheader("1. Kategori & Bütçe Ayarları")
    for kat_adi in list(st.session_state['kategoriler'].keys()):
        with st.sidebar.expander(f"📂 {kat_adi} Bütçesi", expanded=False):
            yeni_limit = st.number_input(f"Toplam Limit (TL)", value=float(st.session_state['kategoriler'][kat_adi]['limit']), key=f"lim_{kat_adi}")
            
            dap_oran = st.slider(f"Dapgeon Payı (%)", 0, 100, int(st.session_state['kategoriler'][kat_adi]['dapgeon_oran']), key=f"oran_{kat_adi}")
            lin_oran = 100 - dap_oran 
            st.info(f"Liniga Payı: %{lin_oran}")
            
            st.session_state['kategoriler'][kat_adi]['limit'] = yeni_limit
            st.session_state['kategoriler'][kat_adi]['dapgeon_oran'] = dap_oran
            st.session_state['kategoriler'][kat_adi]['liniga_oran'] = lin_oran

    st.sidebar.divider()
    st.sidebar.subheader("2. Yeni İlaç Ekle")
    yeni_marka = st.sidebar.text_input("İlaç Adı (Örn: X-İlacı)")
    if st.sidebar.button("İlacı Ekle") and yeni_marka:
        if yeni_marka not in st.session_state['markalar']:
            st.session_state['markalar'].append(yeni_marka)
            st.sidebar.success(f"'{yeni_marka}' seçeneklere eklendi!")
            st.rerun()

    st.sidebar.divider()
    st.sidebar.subheader("3. Yeni Ana Kategori Ekle")
    yeni_kat_adi = st.sidebar.text_input("Kategori Adı (Örn: Konaklama)")
    if st.sidebar.button("Kategoriyi Ekle") and yeni_kat_adi:
        if yeni_kat_adi not in st.session_state['kategoriler']:
            st.session_state['kategoriler'][yeni_kat_adi] = {"limit": 5000.0, "dapgeon_oran": 60, "liniga_oran": 40}
            st.sidebar.success(f"'{yeni_kat_adi}' eklendi!")
            st.rerun()

# --- DASHBOARD ÇİZİM FONKSİYONU ---
def draw_dashboard(df_harcamalar, baslik_metni):
    st.header(baslik_metni)
    
    if df_harcamalar.empty:
        st.info("Sistemde henüz harcama verisi bulunmuyor.")
        return

    # Dönem Seçimi
    donemler = sorted(df_harcamalar['Dönem'].unique(), reverse=True)
    secilen_donem = st.selectbox(f"📅 İncelenecek Dönemi Seçin", donemler, key=f"donem_secici_{baslik_metni}")
    
    df_secili = df_harcamalar[df_harcamalar['Dönem'] == secilen_donem]
    
    if df_secili.empty:
        st.warning("Bu dönemde hiç harcama bulunamadı.")
        return

    # PDF Rapor İndirme Butonu (Dosya ismi temizlenmiş haliyle)
    isim_temiz = baslik_metni.replace("👤 ", "").replace("👑 ", "")
    safe_isim = re.sub(r'[^A-Za-z0-9_]', '', isim_temiz.replace(' ', '_'))
    safe_donem = re.sub(r'[^A-Za-z0-9_]', '', secilen_donem.replace(' ', '_'))
    dosya_adi = f"Harcama_Raporu_{safe_isim}_{safe_donem}.pdf"
    
    pdf_bytes = create_pdf_report(df_secili, secilen_donem, isim_temiz)
    st.download_button(
        label="📄 Bu Dönemin Raporunu İndir (PDF)",
        data=pdf_bytes,
        file_name=dosya_adi,
        mime="application/pdf"
    )
    st.divider()

    harcama_ozeti = df_secili.groupby(['kategori', 'İlaç'])['toplam_tutar'].sum().reset_index()
    st.subheader(f"📊 {secilen_donem} - Bütçe Durumu")
    
    for kat_adi, ayarlar in st.session_state['kategoriler'].items():
        st.markdown(f"#### 📁 {kat_adi} Kategorisi (Dönemsel Bütçe: {ayarlar['limit']:,.2f} TL)")
        
        dapgeon_limit = ayarlar['limit'] * (ayarlar['dapgeon_oran'] / 100)
        liniga_limit = ayarlar['limit'] * (ayarlar['liniga_oran'] / 100)
        
        kat_harcamalari = harcama_ozeti[harcama_ozeti['kategori'] == kat_adi]
        
        dap_harcanan = kat_harcamalari[kat_harcamalari['İlaç'] == 'Dapgeon']['toplam_tutar'].sum() if not kat_harcamalari.empty else 0
        lin_harcanan = kat_harcamalari[kat_harcamalari['İlaç'] == 'Liniga']['toplam_tutar'].sum() if not kat_harcamalari.empty else 0
        
        dap_kalan = dapgeon_limit - dap_harcanan
        lin_kalan = liniga_limit - lin_harcanan
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric(label=f"Dapgeon (Bütçe: {dapgeon_limit:,.0f} TL)", value=f"{dap_kalan:,.2f} TL", delta=f"-{dap_harcanan:,.2f} TL (Harcanan)", delta_color="inverse")
            yuzde_dap = min((dap_harcanan / dapgeon_limit) * 100, 100) if dapgeon_limit > 0 else 0
            st.progress(yuzde_dap / 100, text=f"%{yuzde_dap:.1f} Kullanıldı")
            
        with col2:
            st.metric(label=f"Liniga (Bütçe: {liniga_limit:,.0f} TL)", value=f"{lin_kalan:,.2f} TL", delta=f"-{lin_harcanan:,.2f} TL (Harcanan)", delta_color="inverse")
            yuzde_lin = min((lin_harcanan / liniga_limit) * 100, 100) if liniga_limit > 0 else 0
            st.progress(yuzde_lin / 100, text=f"%{yuzde_lin:.1f} Kullanıldı")
        
        diger_ilaclar = kat_harcamalari[~kat_harcamalari['İlaç'].isin(['Dapgeon', 'Liniga', 'Bilinmeyen'])]
        if not diger_ilaclar.empty:
            for _, row in diger_ilaclar.iterrows():
                st.warning(f"💊 **{row['İlaç']}** ilacı için bu kategoride {row['toplam_tutar']:,.2f} TL ekstra harcama girildi.")
        
        st.divider()
        
    # Yeni Pasta Grafiği (Donut Chart)
    st.subheader("📈 Harcama Dağılımı (İlaç Bazlı)")
    grafik_df = df_secili.groupby('İlaç')['toplam_tutar'].sum().reset_index()
    
    if not grafik_df.empty:
        fig = px.pie(grafik_df, values='toplam_tutar', names='İlaç', hole=0.4, 
                     title=f"{secilen_donem} İlaç Harcama Oranları")
        fig.update_traces(textposition='inside', textinfo='percent+label')
        st.plotly_chart(fig, use_container_width=True, key=f"pie_chart_{baslik_metni}")

# --- ANA EKRAN SEKMELERİ (SIRALAMA DEĞİŞTİ: ÖNCE DASHBOARD) ---
if is_admin:
    tabs = st.tabs(["👤 Kendi Harcamalarım", "➕ Yeni Fiş Yükle", "👑 Tüm Ekip (Admin Paneli)"])
    tab_kisisel, tab_yeni, tab_ekip = tabs
else:
    tabs = st.tabs(["👤 Kendi Harcamalarım", "➕ Yeni Fiş Yükle"])
    tab_kisisel, tab_yeni = tabs[0], tabs[1]

# --- 1. SEKME: KİŞİSEL PANEL (VARSAYILAN AÇILAN EKRAN) ---
with tab_kisisel:
    kisisel_masraflar = get_expenses(fetch_all=False, user_id=username)
    df_kisisel = pd.DataFrame(kisisel_masraflar) if kisisel_masraflar else pd.DataFrame()
    
    draw_dashboard(df_kisisel, f"👤 {name} - Kişisel Bütçe Durumu")
    
    st.divider()
    st.subheader("📋 Geçmiş Harcamalarınız")
    if not df_kisisel.empty:
        gosterilecek_sutunlar = ["Dönem", "tarih", "kategori", "İlaç", "isletme", "toplam_tutar", "fis_no"]
        st.dataframe(df_kisisel[gosterilecek_sutunlar], use_container_width=True)
        
        secilen_isletme_kisisel = st.selectbox("Görselini görmek istediğiniz fişi seçin:", df_kisisel['isletme'].tolist() + ["Seçiniz..."], index=len(df_kisisel))
        if secilen_isletme_kisisel != "Seçiniz...":
            kayit = df_kisisel[df_kisisel['isletme'] == secilen_isletme_kisisel].iloc[0]
            if pd.notna(kayit.get('gorsel_b64')):
                st.image(base64.b64decode(kayit['gorsel_b64']), caption=f"{kayit['isletme']} - {kayit['toplam_tutar']} TL", width=400)
    else:
        st.info("Henüz kaydettiğiniz bir fiş bulunmuyor.")

# --- 2. SEKME: YENİ FİŞ YÜKLEME ---
with tab_yeni:
    st.markdown("Fiş fotoğrafını yüklediğiniz an yapay zeka otomatik olarak okuyacak, uygun ilaç ve kategoriyi kendi atayacaktır.")
    uploaded_file = st.file_uploader("Fiş veya Fatura Fotoğrafı Yükle", type=['png', 'jpg', 'jpeg'])

    if uploaded_file is not None:
        col_img, col_form = st.columns([1, 2])
        
        image = Image.open(uploaded_file)
        with col_img:
            st.image(image, caption="Yüklenen Fiş", use_column_width=True)
        
        with col_form:
            st.subheader("🤖 Yapay Zeka Analizi ve Giriş Formu")
            
            file_bytes = uploaded_file.getvalue()
            mevcut_kategoriler = list(st.session_state['kategoriler'].keys())
            mevcut_markalar = st.session_state['markalar']
            
            if st.session_state.get('last_uploaded') != file_bytes:
                st.session_state['last_uploaded'] = file_bytes
                st.session_state['ai_data'] = {} 
                
                with st.spinner("Yapay zeka fişi inceliyor, lütfen bekleyin..."):
                    try:
                        model = genai.GenerativeModel('gemini-2.5-flash')
                        prompt = f"""
                        Bu fiş/fatura görüntüsünü analiz et ve bilgileri çıkar. Geçerli bir JSON formatında yanıt ver. 
                        Format: {{"isletme": "Ad", "fis_no": "No", "tarih": "GG.AA.YYYY", "harcama_turu": "Tür", "toplam_tutar": 150.50, "kdv_orani": 10, "kdv_tutari": 15.05, "kategori": "...", "marka": "..."}}
                        
                        ÖNEMLİ KURALLAR:
                        1. Fişin içeriğine (yiyecek, otel, market vs.) bakarak en uygun Ana Kategoriyi seç. Şunlardan biri OLMALI: {mevcut_kategoriler}
                        2. Fişin kime/neye ait olduğuna karar vererek en uygun İlacı/Markayı seç. Şunlardan biri OLMALI: {mevcut_markalar}
                        (Eğer fiş bir yemek veya konaklama ise 'Temsil' veya 'Bölgesel' gibi kategoriler seçip, ilacı da en mantıklı olana atayabilirsin).
                        """
                        response = model.generate_content([prompt, image])
                        json_str = response.text.replace("```json", "").replace("```", "").strip()
                        st.session_state['ai_data'] = json.loads(json_str)
                        st.success("Analiz başarılı! Lütfen bilgileri kontrol edip 'Sisteme Kaydet' butonuna basın.")
                    except Exception as e:
                        st.error("Okuma sırasında hata oluştu. Lütfen bilgileri manuel giriniz.")
            
            ai_data = st.session_state.get('ai_data', {})
            
            # YZ'nin seçtiği kategori ve markayı form için bul
            ai_kat = ai_data.get("kategori", mevcut_kategoriler[0])
            ai_mar = ai_data.get("marka", mevcut_markalar[0])
            idx_kat = mevcut_kategoriler.index(ai_kat) if ai_kat in mevcut_kategoriler else 0
            idx_mar = mevcut_markalar.index(ai_mar) if ai_mar in mevcut_markalar else 0
            
            with st.form("masraf_formu"):
                f_col1, f_col2 = st.columns(2)
                with f_col1:
                    isletme = st.text_input("İşletme Adı", value=ai_data.get("isletme", ""))
                    fis_no = st.text_input("Fiş/Fatura No", value=ai_data.get("fis_no", ""))
                    tarih = st.text_input("Tarih (GG.AA.YYYY)", value=ai_data.get("tarih", ""))
                    harcama_turu = st.text_input("Harcama Türü", value=ai_data.get("harcama_turu", ""))
                with f_col2:
                    toplam_tutar = st.number_input("Toplam Tutar (TL)", value=float(ai_data.get("toplam_tutar", 0.0)), step=10.0)
                    kdv_orani = st.number_input("KDV Oranı (%)", value=float(ai_data.get("kdv_orani", 0.0)), step=1.0)
                    kdv_tutari = st.number_input("KDV Tutarı (TL)", value=float(ai_data.get("kdv_tutari", 0.0)), step=1.0)
                    
                    secilen_kategori = st.selectbox("📌 Ana Kategori", mevcut_kategoriler, index=idx_kat)
                    secilen_marka = st.selectbox("💊 İlaç Seçimi", mevcut_markalar, index=idx_mar)

                submit_button = st.form_submit_button("Sisteme Kaydet")
                
                if submit_button and toplam_tutar > 0:
                    # 200 TL LİMİT AŞIMI KONTROLÜ
                    aktif_donem = get_donem(tarih)
                    
                    # Kullanıcının bu dönem, bu kategori ve ilaçtaki harcamasını hesapla
                    df_kontrol = pd.DataFrame(kisisel_masraflar) if kisisel_masraflar else pd.DataFrame()
                    if not df_kontrol.empty:
                        df_donem = df_kontrol[df_kontrol['Dönem'] == aktif_donem]
                        mevcut_harcanan = df_donem[(df_donem['kategori'] == secilen_kategori) & (df_donem['İlaç'] == secilen_marka)]['toplam_tutar'].sum()
                    else:
                        mevcut_harcanan = 0.0
                        
                    kategori_ayari = st.session_state['kategoriler'][secilen_kategori]
                    
                    if secilen_marka == 'Dapgeon':
                        butce_limiti = kategori_ayari['limit'] * (kategori_ayari['dapgeon_oran'] / 100)
                    elif secilen_marka == 'Liniga':
                        butce_limiti = kategori_ayari['limit'] * (kategori_ayari['liniga_oran'] / 100)
                    else:
                        butce_limiti = 0 # Diğer ilaçların standart bir limiti yok
                        
                    kalan_butce = butce_limiti - mevcut_harcanan
                    
                    # Eğer kalan bütçe + 200 TL'yi de aşıyorsa KABUL ETME
                    if secilen_marka in ['Dapgeon', 'Liniga'] and (toplam_tutar > kalan_butce + 200):
                        st.error(f"❌ LİMİT AŞIMI! {secilen_marka} için kalan bütçeniz {kalan_butce:,.2f} TL. En fazla 200 TL esneme payı (aşım) yapabilirsiniz. Fiş tutarı çok yüksek!")
                    else:
                        with st.spinner("Veritabanına kaydediliyor..."):
                            img_base64 = compress_and_encode_image(image)
                            
                            yeni_kayit = {
                                "username": username,
                                "kullanici_adi": name,
                                "tarih": tarih,
                                "isletme": isletme,
                                "fis_no": fis_no,
                                "harcama_turu": harcama_turu,
                                "kategori": secilen_kategori,
                                "marka": secilen_marka, 
                                "toplam_tutar": toplam_tutar,
                                "kdv_orani": kdv_orani,
                                "kdv_tutari": kdv_tutari,
                                "gorsel_b64": img_base64,
                                "timestamp": firestore.SERVER_TIMESTAMP
                            }
                            
                            db.collection('masraflar').add(yeni_kayit)
                            st.success(f"✅ Başarıyla Kaydedildi! Dönem: {aktif_donem}")
                            st.session_state['last_uploaded'] = None 

# --- 3. SEKME: EKİP PANELİ (SADECE ADMİN) ---
if is_admin:
    with tab_ekip:
        tum_masraflar = get_expenses(fetch_all=True)
        df_tum = pd.DataFrame(tum_masraflar) if tum_masraflar else pd.DataFrame()
        
        draw_dashboard(df_tum, "👑 Tüm Ekip Bütçe Kullanımı")
        
        st.divider()
        st.subheader("📋 Tüm Ekibin Harcama Listesi")
        if not df_tum.empty:
            gosterilecek_sutunlar_admin = ["Dönem", "kullanici_adi", "tarih", "kategori", "İlaç", "isletme", "toplam_tutar", "fis_no"]
            st.dataframe(df_tum[gosterilecek_sutunlar_admin], use_container_width=True)
            
            df_tum['secim_metni'] = df_tum['kullanici_adi'] + " - " + df_tum['isletme'] + " (" + df_tum['toplam_tutar'].astype(str) + " TL)"
            secim_listesi = df_tum['secim_metni'].tolist() + ["Seçiniz..."]
            
            secilen_isletme_admin = st.selectbox("Görselini görmek istediğiniz fişi seçin (Ekip):", secim_listesi, index=len(secim_listesi)-1)
            if secilen_isletme_admin != "Seçiniz...":
                kayit = df_tum[df_tum['secim_metni'] == secilen_isletme_admin].iloc[0]
                if pd.notna(kayit.get('gorsel_b64')):
                    st.image(base64.b64decode(kayit['gorsel_b64']), caption=secilen_isletme_admin, width=400)
        else:
            st.info("Sistemde kayıtlı fiş bulunmuyor.")
