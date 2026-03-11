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
import os

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(page_title="Genveon Masraf Portalı", layout="wide", page_icon="🧾", initial_sidebar_state="auto")

# --- MOBİL UYUM (RESPONSIVE) CSS ---
st.markdown("""
    <style>
        /* Mobil cihazlarda tabloların ve metriklerin daha iyi görünmesi için */
        @media (max-width: 768px) {
            .css-1544g2n { padding: 1rem 1rem !important; }
            h1 { font-size: 1.8rem !important; }
            h2 { font-size: 1.5rem !important; }
            h3 { font-size: 1.2rem !important; }
        }
        /* Logonun altındaki kurumsal yazı fontu */
        .kurumsal-baslik {
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
            color: #2c3e50;
            font-weight: 300;
            text-align: center;
            font-size: 24px;
            margin-top: -10px;
            margin-bottom: 30px;
            letter-spacing: 1px;
        }
    </style>
""", unsafe_allow_html=True)

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

# --- SİSTEM AYARLARI (KALICI VERİTABANI BAĞLANTISI) ---
def get_system_settings():
    doc_ref = db.collection('ayarlar').document('sistem')
    doc = doc_ref.get()
    if doc.exists:
        return doc.to_dict()
    else:
        # Veritabanında ayar yoksa varsayılanları oluştur ve kaydet
        default_settings = {
            "kategoriler": {
                "Temsil": {"limit": 7000.0, "dapgeon_oran": 60, "liniga_oran": 40},
                "Audiovisual": {"limit": 7000.0, "dapgeon_oran": 60, "liniga_oran": 40},
                "Bölgesel": {"limit": 3000.0, "dapgeon_oran": 60, "liniga_oran": 40}
            },
            "markalar": ["Dapgeon", "Liniga"]
        }
        doc_ref.set(default_settings)
        return default_settings

def save_system_settings(settings_dict):
    db.collection('ayarlar').document('sistem').set(settings_dict)

# Ayarları Session State'e yükle (Her girişte güncel kalması için)
if 'sistem_ayarlari' not in st.session_state:
    st.session_state['sistem_ayarlari'] = get_system_settings()

# Kolay erişim değişkenleri
ayarlar = st.session_state['sistem_ayarlari']
kategoriler = ayarlar['kategoriler']
markalar = ayarlar['markalar']

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
    
except Exception as e:
    st.error(f"Giriş sistemi yapılandırılamadı. Hata detayı: {e}")
    st.stop()

auth_status = st.session_state.get("authentication_status")

# GİRİŞ EKRANI TASARIMI (Logo ve Başlık)
if auth_status is not True:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        try:
            if os.path.exists("logo.png"):
                st.image("logo.png", use_container_width=True)
            else:
                st.markdown("<h1 style='text-align: center; color: #3498db;'>GENVEON</h1>", unsafe_allow_html=True)
        except:
            st.markdown("<h1 style='text-align: center; color: #3498db;'>GENVEON</h1>", unsafe_allow_html=True)
        
        st.markdown("<div class='kurumsal-baslik'>Masraf Takip Uygulaması</div>", unsafe_allow_html=True)
        
    authenticator.login()
    st.stop()

# --- GİRİŞ BAŞARILI SONRASI ---
name = st.session_state.get("name")
username = st.session_state.get("username")
is_admin = (username == 'admin')

# YAN PANEL LOGO
st.sidebar.markdown("<div style='text-align: center;'>", unsafe_allow_html=True)
try:
    if os.path.exists("logo.png"):
        st.sidebar.image("logo.png", width=200)
    else:
        st.sidebar.markdown("<h2>GENVEON</h2>", unsafe_allow_html=True)
except:
    pass
st.sidebar.markdown("</div>", unsafe_allow_html=True)
st.sidebar.divider()

authenticator.logout('Çıkış Yap', 'sidebar')
st.sidebar.write(f"Hoş geldin, **{name}** 👋")

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

def get_donem(tarih_str):
    try:
        t_str = str(tarih_str).strip().replace('/', '.').replace('-', '.')
        parts = t_str.split('.')
        if len(parts) >= 3:
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            if year < 100: year += 2000
            
            if 1 <= month <= 12:
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

def parse_amount(val):
    if isinstance(val, (int, float)):
        return float(val)
    val = str(val).strip()
    if not val:
        return 0.0
    
    separators = re.findall(r'[^\d]', val)
    if not separators:
        return float(val)
        
    if separators[-1] == ',':
        val = val.replace('.', '').replace(',', '.')
    elif separators[-1] == '.':
        val = val.replace(',', '')
    else:
        if val.count(',') == 1 and val.count('.') == 0:
            val = val.replace(',', '.')
        elif val.count('.') > 1 and val.count(',') == 0:
            val = val.replace('.', '')
        elif val.count('.') == 1 and val.count(',') == 0:
            if len(val.split('.')[1]) == 3:
                val = val.replace('.', '')
                
    val = re.sub(r'[^\d\.]', '', val)
    try:
        return float(val)
    except:
        return 0.0

def normalize_str(s):
    return re.sub(r'[\s\W_]+', '', str(s)).lower()

def get_expenses(fetch_all=False, user_id=None):
    expenses_ref = db.collection('masraflar')
    if not fetch_all:
        query = expenses_ref.where('username', '==', user_id).stream()
    else:
        query = expenses_ref.stream()
    
    data = []
    mevcut_kategoriler = list(kategoriler.keys())
    mevcut_markalar = markalar
    
    for doc in query:
        item = doc.to_dict()
        item['id'] = doc.id
        
        ham_kat = str(item.get('kategori', item.get('Kategori', 'Bilinmeyen'))).strip()
        eslesen_kat = ham_kat
        for mk in mevcut_kategoriler:
            if normalize_str(mk) == normalize_str(ham_kat):
                eslesen_kat = mk
                break
        item['kategori'] = eslesen_kat
        
        ham_ilac = str(item.get('marka', item.get('İlaç', 'Bilinmeyen'))).strip()
        eslesen_ilac = ham_ilac
        for mi in mevcut_markalar:
            if normalize_str(mi) == normalize_str(ham_ilac):
                eslesen_ilac = mi
                break
        item['İlaç'] = eslesen_ilac
        
        item['toplam_tutar'] = parse_amount(item.get('toplam_tutar', item.get('Toplam Tutar', 0.0)))
        item['isletme'] = str(item.get('isletme', item.get('İşletme', 'Bilinmeyen')))
        item['fis_no'] = str(item.get('fis_no', item.get('Fiş No', '')))
        item['tarih'] = str(item.get('tarih', item.get('Tarih', '')))
        item['kullanici_adi'] = str(item.get('kullanici_adi', item.get('username', 'Bilinmeyen')))
        item['Dönem'] = get_donem(item['tarih'])
        
        data.append(item)
    return data

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
        
    return bytes(pdf.output(dest='S').encode('latin-1', 'ignore'))

def delete_expense(doc_id):
    try:
        db.collection('masraflar').document(doc_id).delete()
        st.success("Fiş başarıyla silindi!")
        return True
    except Exception as e:
        st.error(f"Silme hatası: {e}")
        return False

def update_expense(doc_id, yeni_veri):
    try:
        db.collection('masraflar').document(doc_id).update(yeni_veri)
        st.success("Fiş başarıyla güncellendi!")
        return True
    except Exception as e:
        st.error(f"Güncelleme hatası: {e}")
        return False

# --- YAN PANEL: AYARLAR (SADECE ADMİN) ---
if is_admin:
    st.sidebar.divider()
    st.sidebar.header("⚙️ Sistem Ayarları (Kalıcı)")
    
    with st.sidebar.form("ayarlar_formu"):
        st.subheader("Kategori & Bütçe Ayarları")
        yeni_kategoriler = {}
        for kat_adi, ayar in kategoriler.items():
            st.markdown(f"**📂 {kat_adi}**")
            y_limit = st.number_input(f"Limit (TL)", value=float(ayar['limit']), key=f"form_lim_{kat_adi}")
            y_dap_oran = st.slider(f"Dapgeon Payı (%)", 0, 100, int(ayar['dapgeon_oran']), key=f"form_oran_{kat_adi}")
            y_lin_oran = 100 - y_dap_oran
            st.caption(f"Liniga Payı: %{y_lin_oran}")
            
            yeni_kategoriler[kat_adi] = {
                "limit": y_limit,
                "dapgeon_oran": y_dap_oran,
                "liniga_oran": y_lin_oran
            }
            st.divider()
            
        kaydet_btn = st.form_submit_button("Ayarları Kalıcı Olarak Kaydet", type="primary")
        
        if kaydet_btn:
            yeni_ayarlar = {"kategoriler": yeni_kategoriler, "markalar": markalar}
            save_system_settings(yeni_ayarlar)
            st.session_state['sistem_ayarlari'] = yeni_ayarlar
            st.success("Ayarlar başarıyla veritabanına kaydedildi!")
            st.rerun()

# --- DASHBOARD ÇİZİM FONKSİYONU ---
def draw_dashboard(df_harcamalar, baslik_metni):
    st.header(baslik_metni)
    
    if df_harcamalar.empty:
        st.info("Sistemde henüz harcama verisi bulunmuyor.")
        return

    donemler = sorted(df_harcamalar['Dönem'].unique(), reverse=True)
    secilen_donem = st.selectbox(f"📅 İncelenecek Dönemi Seçin", donemler, key=f"donem_secici_{baslik_metni}")
    
    df_secili = df_harcamalar[df_harcamalar['Dönem'] == secilen_donem].copy() 
    
    if df_secili.empty:
        st.warning("Bu dönemde hiç harcama bulunamadı.")
        return

    # YENİ: KAYIP HARCAMA DEDEKTÖRÜ
    mevcut_kat_listesi = list(kategoriler.keys())
    unmapped_df = df_secili[~df_secili['kategori'].isin(mevcut_kat_listesi)]
    if not unmapped_df.empty:
        st.error("⚠️ DİKKAT: Aşağıdaki harcamaların kategorisi sistemdeki bütçelerle eşleşmiyor! Lütfen 'Fiş Düzenle' kısmından doğru kategoriyi seçip güncelleyin.")
        st.dataframe(unmapped_df[['tarih', 'kategori', 'İlaç', 'isletme', 'toplam_tutar']], use_container_width=True)

    # --- MİNİ ARA RAPOR ALANI (YENİ) ---
    st.markdown("### ⏱️ Hızlı Dönem Özeti (Ara Rapor)")
    toplam_genel_limit = sum(k['limit'] for k in kategoriler.values())
    toplam_genel_harcama = df_secili['toplam_tutar'].sum()
    toplam_genel_kalan = toplam_genel_limit - toplam_genel_harcama
    
    m_col1, m_col2, m_col3 = st.columns(3)
    m_col1.metric("Ayrılan Toplam Bütçe", f"{toplam_genel_limit:,.2f} TL")
    m_col2.metric("Güncel Toplam Harcama", f"{toplam_genel_harcama:,.2f} TL", delta=f"-{toplam_genel_harcama:,.2f} TL", delta_color="inverse")
    m_col3.metric("Toplam Kalan Bakiye", f"{max(toplam_genel_kalan, 0):,.2f} TL", delta=f"{toplam_genel_kalan:,.2f} TL" if toplam_genel_kalan >=0 else "AŞILDI", delta_color="normal")
    st.divider()

    isim_temiz = baslik_metni.replace("👤 ", "").replace("👑 ", "")
    safe_isim = re.sub(r'[^A-Za-z0-9_]', '', isim_temiz.replace(' ', '_'))
    safe_donem = re.sub(r'[^A-Za-z0-9_]', '', secilen_donem.replace(' ', '_'))
    dosya_adi = f"Harcama_Raporu_{safe_isim}_{safe_donem}.pdf"
    
    pdf_bytes = create_pdf_report(df_secili, secilen_donem, isim_temiz)
    st.download_button(
        label="📄 Detaylı Dönem Raporunu İndir (PDF)",
        data=pdf_bytes,
        file_name=dosya_adi,
        mime="application/pdf"
    )
    st.divider()

    harcama_ozeti = df_secili.groupby(['kategori', 'İlaç'])['toplam_tutar'].sum().reset_index()
    st.subheader(f"📊 {secilen_donem} - Detaylı Bütçe Durumu")
    
    for kat_adi, ayar in kategoriler.items():
        st.markdown(f"#### 📁 {kat_adi} Kategorisi (Dönemsel Bütçe: {ayar['limit']:,.2f} TL)")
        
        dapgeon_limit = ayar['limit'] * (ayar['dapgeon_oran'] / 100)
        liniga_limit = ayar['limit'] * (ayar['liniga_oran'] / 100)
        
        kat_harcamalari = harcama_ozeti[harcama_ozeti['kategori'] == kat_adi]
        
        dap_harcanan = kat_harcamalari[kat_harcamalari['İlaç'] == 'Dapgeon']['toplam_tutar'].sum() if not kat_harcamalari.empty else 0
        lin_harcanan = kat_harcamalari[kat_harcamalari['İlaç'] == 'Liniga']['toplam_tutar'].sum() if not kat_harcamalari.empty else 0
        
        dap_kalan = dapgeon_limit - dap_harcanan
        lin_kalan = liniga_limit - lin_harcanan
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric(label=f"Dapgeon (Limit: {dapgeon_limit:,.0f} TL)", value=f"{dap_kalan:,.2f} TL", delta=f"-{dap_harcanan:,.2f} TL (Harcanan)", delta_color="inverse")
            yuzde_dap = min((dap_harcanan / dapgeon_limit) * 100, 100) if dapgeon_limit > 0 else 0
            st.progress(yuzde_dap / 100)
            
        with col2:
            st.metric(label=f"Liniga (Limit: {liniga_limit:,.0f} TL)", value=f"{lin_kalan:,.2f} TL", delta=f"-{lin_harcanan:,.2f} TL (Harcanan)", delta_color="inverse")
            yuzde_lin = min((lin_harcanan / liniga_limit) * 100, 100) if liniga_limit > 0 else 0
            st.progress(yuzde_lin / 100)
        
        diger_ilaclar = kat_harcamalari[~kat_harcamalari['İlaç'].isin(['Dapgeon', 'Liniga', 'Bilinmeyen'])]
        if not diger_ilaclar.empty:
            for _, row in diger_ilaclar.iterrows():
                st.warning(f"💊 **{row['İlaç']}** ilacı için bu kategoride {row['toplam_tutar']:,.2f} TL ekstra harcama girildi.")
        
        st.divider()
        
    st.subheader("📈 Harcama Dağılımı (İlaç Bazlı)")
    grafik_df = df_secili[df_secili['kategori'].isin(mevcut_kat_listesi)].groupby('İlaç')['toplam_tutar'].sum().reset_index()
    
    if not grafik_df.empty:
        fig = px.pie(grafik_df, values='toplam_tutar', names='İlaç', hole=0.4, 
                     title=f"{secilen_donem} İlaç Harcama Oranları")
        fig.update_traces(textposition='inside', textinfo='percent+label')
        st.plotly_chart(fig, use_container_width=True, key=f"pie_chart_{baslik_metni}")

# --- FİŞ DÜZENLEME ARAYÜZÜ FONKSİYONU ---
def render_edit_interface(df, prefix_key):
    st.subheader("✏️ Fiş Düzenle veya Sil")
    
    df['secim_metni'] = df['isletme'] + " - " + df['toplam_tutar'].astype(str) + " TL (" + df['tarih'] + ")"
    secim_listesi = ["Bir fiş seçin..."] + df['secim_metni'].tolist()
    
    secilen_metin = st.selectbox("Düzenlenecek Fişi Seçin:", secim_listesi, key=f"edit_select_{prefix_key}")
    
    if secilen_metin != "Bir fiş seçin...":
        secilen_kayit = df[df['secim_metni'] == secilen_metin].iloc[0]
        doc_id = secilen_kayit['id']
        
        with st.form(key=f"edit_form_{prefix_key}"):
            st.write(f"**{secilen_kayit['isletme']}** isimli fişi düzenliyorsunuz:")
            
            c1, c2 = st.columns(2)
            with c1:
                y_isletme = st.text_input("İşletme Adı", value=secilen_kayit['isletme'])
                y_tarih = st.text_input("Tarih (GG.AA.YYYY)", value=secilen_kayit['tarih'])
                
                mevcut_kategoriler = list(kategoriler.keys())
                mevcut_markalar = markalar
                
                idx_kat = mevcut_kategoriler.index(secilen_kayit['kategori']) if secilen_kayit['kategori'] in mevcut_kategoriler else 0
                idx_mar = mevcut_markalar.index(secilen_kayit['İlaç']) if secilen_kayit['İlaç'] in mevcut_markalar else 0
                
                y_kategori = st.selectbox("Ana Kategori", mevcut_kategoriler, index=idx_kat)
            
            with c2:
                y_tutar = st.number_input("Toplam Tutar (TL)", value=float(secilen_kayit['toplam_tutar']), step=10.0)
                y_ilac = st.selectbox("İlaç Seçimi", mevcut_markalar, index=idx_mar)
                y_fis_no = st.text_input("Fiş No", value=secilen_kayit['fis_no'])
                
            c_btn1, c_btn2, c_btn3 = st.columns([1, 1, 2])
            with c_btn1:
                btn_guncelle = st.form_submit_button("💾 Güncelle", type="primary")
            with c_btn2:
                btn_sil = st.form_submit_button("🗑️ Sil")
                
            if btn_guncelle:
                yeni_veri = {
                    "isletme": y_isletme,
                    "tarih": y_tarih,
                    "kategori": y_kategori,
                    "marka": y_ilac, 
                    "toplam_tutar": float(y_tutar), 
                    "fis_no": y_fis_no
                }
                if update_expense(doc_id, yeni_veri):
                    st.rerun()
                    
            if btn_sil:
                if delete_expense(doc_id):
                    st.rerun()
                    
        if pd.notna(secilen_kayit.get('gorsel_b64')):
            st.image(base64.b64decode(secilen_kayit['gorsel_b64']), caption="Fiş Görseli", use_container_width=True)

# --- ANA EKRAN SEKMELER ---
if is_admin:
    tabs = st.tabs(["👤 Kendi Harcamalarım", "➕ Yeni Fiş Yükle", "👑 Tüm Ekip (Admin Paneli)"])
    tab_kisisel, tab_yeni, tab_ekip = tabs
else:
    tabs = st.tabs(["👤 Kendi Harcamalarım", "➕ Yeni Fiş Yükle"])
    tab_kisisel, tab_yeni = tabs[0], tabs[1]

# --- 1. SEKME: KİŞİSEL PANEL ---
with tab_kisisel:
    kisisel_masraflar = get_expenses(fetch_all=False, user_id=username)
    df_kisisel = pd.DataFrame(kisisel_masraflar) if kisisel_masraflar else pd.DataFrame()
    
    draw_dashboard(df_kisisel, f"👤 {name} - Kişisel Bütçe Durumu")
    
    st.divider()
    st.subheader("📋 Geçmiş Harcamalarınız")
    if not df_kisisel.empty:
        gosterilecek_sutunlar = ["Dönem", "tarih", "kategori", "İlaç", "isletme", "toplam_tutar", "fis_no"]
        st.dataframe(df_kisisel[gosterilecek_sutunlar], use_container_width=True)
        
        st.divider()
        render_edit_interface(df_kisisel, prefix_key="kisisel")
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
            st.image(image, caption="Yüklenen Fiş", use_container_width=True)
        
        with col_form:
            st.subheader("🤖 Yapay Zeka Analizi ve Giriş Formu")
            
            file_bytes = uploaded_file.getvalue()
            mevcut_kategoriler = list(kategoriler.keys())
            mevcut_markalar = markalar
            
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
                        1. Fişin içeriğine bakarak en uygun Ana Kategoriyi seç. Şunlardan biri OLMALI: {mevcut_kategoriler}
                        2. Fişin kime/neye ait olduğuna karar vererek en uygun İlacı/Markayı seç. Şunlardan biri OLMALI: {mevcut_markalar}
                        """
                        response = model.generate_content([prompt, image])
                        json_str = response.text.replace("```json", "").replace("```", "").strip()
                        st.session_state['ai_data'] = json.loads(json_str)
                        st.success("Analiz başarılı! Lütfen bilgileri kontrol edip 'Sisteme Kaydet' butonuna basın.")
                    except Exception as e:
                        st.error("Okuma sırasında hata oluştu. Lütfen bilgileri manuel giriniz.")
            
            ai_data = st.session_state.get('ai_data', {})
            
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
                    aktif_donem = get_donem(tarih)
                    
                    df_kontrol = pd.DataFrame(kisisel_masraflar) if kisisel_masraflar else pd.DataFrame()
                    if not df_kontrol.empty:
                        df_donem = df_kontrol[df_kontrol['Dönem'] == aktif_donem]
                        mevcut_harcanan = df_donem[(df_donem['kategori'] == secilen_kategori) & (df_donem['İlaç'] == secilen_marka)]['toplam_tutar'].sum()
                    else:
                        mevcut_harcanan = 0.0
                        
                    kategori_ayari = kategoriler[secilen_kategori]
                    
                    if secilen_marka == 'Dapgeon':
                        butce_limiti = kategori_ayari['limit'] * (kategori_ayari['dapgeon_oran'] / 100)
                    elif secilen_marka == 'Liniga':
                        butce_limiti = kategori_ayari['limit'] * (kategori_ayari['liniga_oran'] / 100)
                    else:
                        butce_limiti = 0 
                        
                    kalan_butce = butce_limiti - mevcut_harcanan
                    
                    if secilen_marka in ['Dapgeon', 'Liniga'] and (toplam_tutar > kalan_butce + 200):
                        st.error(f"❌ LİMİT AŞIMI! {secilen_marka} için kalan bütçeniz {kalan_butce:,.2f} TL. En fazla 200 TL esneme payı (aşım) yapabilirsiniz.")
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
                                "toplam_tutar": float(toplam_tutar), 
                                "kdv_orani": float(kdv_orani),
                                "kdv_tutari": float(kdv_tutari),
                                "gorsel_b64": img_base64,
                                "timestamp": firestore.SERVER_TIMESTAMP
                            }
                            
                            db.collection('masraflar').add(yeni_kayit)
                            st.success(f"✅ Başarıyla Kaydedildi! Dönem: {aktif_donem}")
                            st.session_state['last_uploaded'] = None 
                            st.rerun() 

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
            
            st.divider()
            render_edit_interface(df_tum, prefix_key="admin")
        else:
            st.info("Sistemde kayıtlı fiş bulunmuyor.")
