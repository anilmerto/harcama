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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(page_title="Genveon Masraf Portalı", layout="wide", page_icon="🧾")

# --- GELİŞMİŞ MOBİL UYUM & GENEL TASARIM CSS ---
st.markdown("""
    <style>
        .block-container {
            max-width: 1050px !important;
            padding-top: 2rem !important;
        }
        
        .stTabs [data-baseweb="tab-list"] {
            justify-content: center;
            gap: 15px;
            border-bottom: 2px solid #f0f2f6;
        }
        .stTabs [data-baseweb="tab"] {
            font-size: 1.1rem;
            padding: 12px 20px;
            font-weight: 500;
        }
        
        @media (max-width: 768px) {
            [data-testid="stImage"] {
                display: flex;
                justify-content: center;
                align-items: center;
            }
            [data-testid="stImage"] img {
                max-width: 160px !important; 
                height: auto;
            }
            .kurumsal-baslik {
                font-size: 18px !important;
                margin-bottom: 20px !important;
                text-align: center;
            }
            h1, h2, h3 { text-align: center; }
        }

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

# --- OTOMATİK E-POSTA FONKSİYONU ---
def send_email_to_admin(konu, mesaj):
    try:
        sender_email = st.secrets["email"]["address"]
        sender_pass = st.secrets["email"]["password"]
        receiver_email = "anilmertocak@gmail.com"
        
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = receiver_email
        msg['Subject'] = f"Genveon Portal: {konu}"
        msg.attach(MIMEText(mesaj, 'plain', 'utf-8'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_pass)
        server.send_message(msg)
        server.quit()
    except Exception:
        pass

# --- FIREBASE VERİTABANI BAĞLANTISI ---
@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        try:
            cred_dict = dict(st.secrets["firebase"])
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
        except Exception as e:
            send_email_to_admin("KRİTİK HATA: Veritabanı Çöktü", f"Sistem veritabanına bağlanamadı.\nHata detayı: {str(e)}")
            st.error("Sistem bağlantı hatası. Yöneticiye bilgi verildi.")
            st.stop()
    return firestore.client()

db = init_firebase()

# --- SİSTEM AYARLARI ---
def get_system_settings():
    doc_ref = db.collection('ayarlar').document('sistem')
    doc = doc_ref.get()
    if doc.exists:
        return doc.to_dict()
    else:
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

if 'sistem_ayarlari' not in st.session_state:
    st.session_state['sistem_ayarlari'] = get_system_settings()

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
    send_email_to_admin("KRİTİK HATA: Login Sistemi Çöktü", f"Giriş sistemi başlatılamadı.\nHata: {str(e)}")
    st.error("Giriş sistemi yapılandırılamadı.")
    st.stop()

auth_status = st.session_state.get("authentication_status")

# --- GİRİŞ EKRANI TASARIMI (GÜNCELLENDİ) ---
if auth_status is not True:
    
    st.markdown("""
        <style>
            [data-testid="stFormSubmitButton"] button p { font-size: 0px !important; }
            [data-testid="stFormSubmitButton"] button p::before {
                content: "Sisteme Giriş Yap";
                font-size: 16px !important;
                visibility: visible;
            }
        </style>
    """, unsafe_allow_html=True)
    
    st.markdown("<div style='display:flex; justify-content:center; margin-bottom: 20px;'>", unsafe_allow_html=True)
    try:
        st.image("logo.png", width=250)
    except:
        st.markdown("<h1 style='color: #3498db; text-align: center;'>GENVEON</h1>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    
    st.markdown("<div class='kurumsal-baslik'>Masraf Takip Uygulaması</div>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        authenticator.login()
    st.stop()

# --- GİRİŞ BAŞARILI SONRASI (ÜST NAVİGASYON / LOGO) ---
name = st.session_state.get("name")
username = st.session_state.get("username")
is_admin = (username == 'admin')

col_logo, col_space, col_user = st.columns([2, 1, 2])
with col_logo:
    try:
        st.image("logo.png", width=180)
    except:
        st.markdown("<h3 style='color: #3498db; margin:0;'>GENVEON</h3>", unsafe_allow_html=True)

with col_user:
    st.markdown(f"<div style='text-align: right; padding-top:10px;'>Hoş geldin, <b>{name}</b></div>", unsafe_allow_html=True)
    authenticator.logout('Çıkış', 'main')

st.divider()

# --- GEMINI YZ YAPILANDIRMASI ---
try:
    genai.configure(api_key=st.secrets["gemini"]["api_key"])
except:
    st.error("Gemini API bağlantı hatası!")

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
    if isinstance(val, (int, float)): return float(val)
    val = str(val).strip()
    if not val: return 0.0
    separators = re.findall(r'[^\d]', val)
    if not separators: return float(val)
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
            if len(val.split('.')[1]) == 3: val = val.replace('.', '')
    val = re.sub(r'[^\d\.]', '', val)
    try: return float(val)
    except: return 0.0

def normalize_str(s):
    return re.sub(r'[\s\W_]+', '', str(s)).lower()

def safe_text(text):
    text = str(text)
    donusum = {"ı": "i", "İ": "I", "ş": "s", "Ş": "S", "ğ": "g", "Ğ": "G", "ü": "u", "Ü": "U", "ö": "o", "Ö": "O", "ç": "c", "Ç": "C"}
    for tr, en in donusum.items():
        text = text.replace(tr, en)
    return text

def get_expenses(fetch_all=False, user_id=None):
    expenses_ref = db.collection('masraflar')
    query = expenses_ref.stream() if fetch_all else expenses_ref.where('username', '==', user_id).stream()
    
    data = []
    mevcut_kategoriler = list(kategoriler.keys())
    
    for doc in query:
        item = doc.to_dict()
        item['id'] = doc.id
        
        ham_kat = str(item.get('kategori', item.get('Kategori', 'Bilinmeyen'))).strip()
        eslesen_kat = ham_kat
        for mk in mevcut_kategoriler:
            if normalize_str(mk) == normalize_str(ham_kat): eslesen_kat = mk; break
        item['kategori'] = eslesen_kat
        
        ham_ilac = str(item.get('marka', item.get('İlaç', 'Bilinmeyen'))).strip()
        eslesen_ilac = ham_ilac
        for mi in markalar:
            if normalize_str(mi) == normalize_str(ham_ilac): eslesen_ilac = mi; break
        item['İlaç'] = eslesen_ilac
        
        item['toplam_tutar'] = parse_amount(item.get('toplam_tutar', 0.0))
        item['kdv_orani'] = float(item.get('kdv_orani', 0.0))
        item['kdv_tutari'] = float(item.get('kdv_tutari', 0.0))
        item['harcama_turu'] = safe_text(item.get('harcama_turu', ''))
        
        item['isletme'] = safe_text(item.get('isletme', 'Bilinmeyen'))
        item['fis_no'] = safe_text(item.get('fis_no', ''))
        item['tarih'] = str(item.get('tarih', ''))
        item['kullanici_adi'] = str(item.get('kullanici_adi', 'Bilinmeyen'))
        item['Dönem'] = get_donem(item['tarih'])
        
        data.append(item)
    return data

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
    for w, h in zip(col_widths, headers): pdf.cell(w, 10, h, border=1, align='C')
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

# --- FİŞ DÜZENLEME ARAYÜZÜ (GELİŞMİŞ EKSİKSİZ) ---
def render_edit_interface(df, prefix_key):
    st.markdown("#### ✏️ Fiş Düzenle veya Sil")
    df['secim_metni'] = df['isletme'] + " - " + df['toplam_tutar'].astype(str) + " TL (" + df['tarih'] + ")"
    secim_listesi = ["Bir fiş seçin..."] + df['secim_metni'].tolist()
    
    secilen_metin = st.selectbox("İşlem yapılacak fişi seçin:", secim_listesi, key=f"edit_select_{prefix_key}")
    
    if secilen_metin != "Bir fiş seçin...":
        secilen_kayit = df[df['secim_metni'] == secilen_metin].iloc[0]
        doc_id = secilen_kayit['id']
        
        with st.form(key=f"edit_form_{prefix_key}"):
            c1, c2 = st.columns(2)
            
            y_isletme = c1.text_input("İşletme Adı", secilen_kayit['isletme'])
            y_fis = c1.text_input("Fiş No", secilen_kayit.get('fis_no', ''))
            y_tarih = c1.text_input("Tarih (GG.AA.YYYY)", secilen_kayit['tarih'])
            y_harcama_turu = c1.text_input("Harcama Türü", secilen_kayit.get('harcama_turu', ''))
            
            mevcut_kats = list(kategoriler.keys())
            idx_k = mevcut_kats.index(secilen_kayit['kategori']) if secilen_kayit['kategori'] in mevcut_kats else 0
            y_kategori = c1.selectbox("Kategori", mevcut_kats, index=idx_k)
            
            y_tutar = c2.number_input("Tutar (TL)", float(secilen_kayit['toplam_tutar']), step=10.0)
            y_kdv_oran = c2.number_input("KDV Oranı (%)", float(secilen_kayit.get('kdv_orani', 0.0)), step=1.0)
            y_kdv_tutar = c2.number_input("KDV Tutarı (TL)", float(secilen_kayit.get('kdv_tutari', 0.0)), step=1.0)
            
            idx_m = markalar.index(secilen_kayit['İlaç']) if secilen_kayit['İlaç'] in markalar else 0
            y_ilac = c2.selectbox("İlaç", markalar, index=idx_m)
            
            st.write("") # Boşluk
            
            col_b1, col_b2 = st.columns(2)
            btn_guncelle = col_b1.form_submit_button("💾 Güncelle", use_container_width=True, type="primary")
            btn_sil = col_b2.form_submit_button("🗑️ Sil", use_container_width=True)
            
            if btn_guncelle:
                db.collection('masraflar').document(doc_id).update({
                    "isletme": y_isletme, "tarih": y_tarih, "kategori": y_kategori,
                    "marka": y_ilac, "toplam_tutar": float(y_tutar), "fis_no": y_fis,
                    "kdv_orani": float(y_kdv_oran), "kdv_tutari": float(y_kdv_tutar), "harcama_turu": y_harcama_turu
                })
                st.success("Fiş başarıyla güncellendi!")
                st.rerun()
            if btn_sil:
                db.collection('masraflar').document(doc_id).delete()
                st.success("Fiş tamamen silindi!")
                st.rerun()
                
        if pd.notna(secilen_kayit.get('gorsel_b64')):
            st.image(base64.b64decode(secilen_kayit['gorsel_b64']), caption="Seçili Fiş Görseli", width=300)

# --- DASHBOARD ÇİZİM FONKSİYONU ---
def draw_dashboard(df_harcamalar, baslik_metni):
    st.markdown(f"<h2 style='text-align: center;'>{baslik_metni}</h2>", unsafe_allow_html=True)
    
    if df_harcamalar.empty:
        st.info("Sistemde henüz harcama verisi bulunmuyor.")
        return

    donemler = sorted(df_harcamalar['Dönem'].unique(), reverse=True)
    secilen_donem = st.selectbox(f"📅 İncelenecek Dönemi Seçin", donemler, key=f"donem_secici_{baslik_metni}")
    df_secili = df_harcamalar[df_harcamalar['Dönem'] == secilen_donem].copy() 
    
    if df_secili.empty:
        st.warning("Bu dönemde hiç harcama bulunamadı.")
        return

    mevcut_kat_listesi = list(kategoriler.keys())
    unmapped_df = df_secili[~df_secili['kategori'].isin(mevcut_kat_listesi)]
    if not unmapped_df.empty:
        st.error("⚠️ DİKKAT: Aşağıdaki harcamaların kategorisi sistemdeki bütçelerle uyuşmuyor. Lütfen 'Fiş Düzenle' kısmından güncelleyin.")
        st.dataframe(unmapped_df[['tarih', 'kategori', 'İlaç', 'isletme', 'toplam_tutar']], use_container_width=True)

    st.markdown("### ⏱️ Hızlı Dönem Özeti")
    rapor_kolonlari = st.columns(len(kategoriler))
    
    for idx, (kat_adi, ayar) in enumerate(kategoriler.items()):
        with rapor_kolonlari[idx]:
            with st.container(border=True): 
                limit = ayar['limit']
                harcanan = df_secili[df_secili['kategori'] == kat_adi]['toplam_tutar'].sum() if not df_secili.empty else 0.0
                kalan = limit - harcanan
                st.markdown(f"<div style='text-align:center;'><b>📂 {kat_adi}</b></div>", unsafe_allow_html=True)
                st.metric(label="Kalan Bütçe", value=f"{kalan:,.2f} TL", delta=f"-{harcanan:,.2f} TL", delta_color="inverse")
    
    st.divider()
    
    safe_isim = re.sub(r'[^A-Za-z0-9_]', '', baslik_metni.replace("👤 ", "").replace("👑 ", "").replace(' ', '_'))
    safe_donem = re.sub(r'[^A-Za-z0-9_]', '', secilen_donem.replace(' ', '_'))
    
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.download_button("📄 Dönem Raporunu İndir (PDF)", create_pdf_report(df_secili, secilen_donem, safe_isim), file_name=f"Rapor_{safe_isim}_{safe_donem}.pdf", mime="application/pdf", use_container_width=True)
    st.divider()

    harcama_ozeti = df_secili.groupby(['kategori', 'İlaç'])['toplam_tutar'].sum().reset_index()
    
    for kat_adi, ayar in kategoriler.items():
        with st.expander(f"📊 {kat_adi} Kategorisi Detayları (Ayrılan: {ayar['limit']:,.0f} TL)", expanded=True):
            dapgeon_limit = ayar['limit'] * (ayar['dapgeon_oran'] / 100)
            liniga_limit = ayar['limit'] * (ayar['liniga_oran'] / 100)
            kat_harcamalari = harcama_ozeti[harcama_ozeti['kategori'] == kat_adi]
            dap_harcanan = kat_harcamalari[kat_harcamalari['İlaç'] == 'Dapgeon']['toplam_tutar'].sum() if not kat_harcamalari.empty else 0
            lin_harcanan = kat_harcamalari[kat_harcamalari['İlaç'] == 'Liniga']['toplam_tutar'].sum() if not kat_harcamalari.empty else 0
            
            c1, c2 = st.columns(2)
            with c1:
                st.metric("Dapgeon Limit", f"{(dapgeon_limit - dap_harcanan):,.2f} TL", delta=f"-{dap_harcanan:,.2f} TL", delta_color="inverse")
                st.progress(min((dap_harcanan / dapgeon_limit) * 100, 100) / 100 if dapgeon_limit > 0 else 0)
            with c2:
                st.metric("Liniga Limit", f"{(liniga_limit - lin_harcanan):,.2f} TL", delta=f"-{lin_harcanan:,.2f} TL", delta_color="inverse")
                st.progress(min((lin_harcanan / liniga_limit) * 100, 100) / 100 if liniga_limit > 0 else 0)
        
    grafik_df = df_secili[df_secili['kategori'].isin(mevcut_kat_listesi)].groupby('İlaç')['toplam_tutar'].sum().reset_index()
    if not grafik_df.empty:
        fig = px.pie(grafik_df, values='toplam_tutar', names='İlaç', hole=0.4, title="İlaç Dağılımı")
        st.plotly_chart(fig, use_container_width=True, key=f"pie_{baslik_metni}")

# --- ANA SEKMELER ---
if is_admin:
    tabs = st.tabs(["👤 Kendi Harcamalarım", "➕ Yeni Fiş Yükle", "👑 Tüm Ekip", "⚙️ Ayarlar", "🚨 Destek"])
    tab_kisisel, tab_yeni, tab_ekip, tab_ayarlar, tab_destek = tabs
else:
    tabs = st.tabs(["👤 Kendi Harcamalarım", "➕ Yeni Fiş Yükle", "🚨 Destek"])
    tab_kisisel, tab_yeni, tab_destek = tabs[0], tabs[1], tabs[2]

# --- 1. SEKME: KİŞİSEL PANEL ---
with tab_kisisel:
    kisisel_masraflar = get_expenses(fetch_all=False, user_id=username)
    df_kisisel = pd.DataFrame(kisisel_masraflar) if kisisel_masraflar else pd.DataFrame()
    draw_dashboard(df_kisisel, f"👤 Kendi Bütçem")
    
    if not df_kisisel.empty:
        with st.expander("📋 Geçmiş Harcamalar & Fiş Düzenleme Listesi", expanded=False):
            st.dataframe(df_kisisel[["Dönem", "tarih", "kategori", "İlaç", "isletme", "toplam_tutar"]], use_container_width=True)
            st.divider()
            render_edit_interface(df_kisisel, prefix_key="kisisel")

# --- 2. SEKME: YENİ FİŞ YÜKLEME (GÜNCELLENDİ) ---
with tab_yeni:
    st.markdown("<h3 style='text-align:center;'>🤖 Yapay Zeka Destekli Fiş Okuyucu</h3>", unsafe_allow_html=True)
    uploaded_file = st.file_uploader("Fotoğraf Yükle", type=['png', 'jpg', 'jpeg'])

    if uploaded_file is not None:
        image = Image.open(uploaded_file)
        st.image(image, use_container_width=True)
        
        file_bytes = uploaded_file.getvalue()
        if st.session_state.get('last_uploaded') != file_bytes:
            st.session_state['last_uploaded'] = file_bytes
            with st.spinner("Yapay Zeka Analiz Ediyor..."):
                try:
                    model = genai.GenerativeModel('gemini-2.5-flash')
                    current_date = datetime.now().strftime("%d.%m.%Y")
                    current_year = datetime.now().year
                    
                    prompt = f"""
                    Bu fiş görüntüsünü analiz et ve JSON ver. 
                    Format: {{"isletme": "Ad", "fis_no": "No", "tarih": "GG.AA.YYYY", "harcama_turu": "Tür", "toplam_tutar": 150.50, "kdv_orani": 10, "kdv_tutari": 15.05, "kategori": "...", "marka": "..."}}
                    
                    KRİTİK KURALLAR:
                    1. Kategori şunlardan biri OLMALI: {list(kategoriler.keys())}
                    2. İlaç şunlardan biri OLMALI: {markalar}
                    3. ZAMAN BİLİNCİ: Bugünün tarihi {current_date}. Fişteki tarihi okurken yılı karıştırırsan veya eski okursan (örn: 2024), mantıken içinde bulunduğumuz {current_year} yılı olarak DÜZELT!
                    """
                    response = model.generate_content([prompt, image])
                    json_str = response.text.replace("```json", "").replace("```", "").strip()
                    st.session_state['ai_data'] = json.loads(json_str)
                    st.success("Analiz tamam! Lütfen bilgileri kontrol edip kaydedin.")
                except Exception as e:
                    send_email_to_admin("Yapay Zeka Okuma Hatası", f"Kullanıcı: {name}\nHata: {str(e)}")
                    st.error("Okuma hatası oluştu, lütfen manuel giriniz.")
        
        ai_data = st.session_state.get('ai_data', {})
        ai_kat = ai_data.get("kategori", list(kategoriler.keys())[0])
        ai_mar = ai_data.get("marka", markalar[0])
        
        with st.form("masraf_formu"):
            c1, c2 = st.columns(2)
            
            # Eksik alanlar formlara geri eklendi
            isletme = c1.text_input("İşletme Adı", safe_text(ai_data.get("isletme", "")))
            fis_no = c1.text_input("Fiş No", safe_text(ai_data.get("fis_no", "")))
            tarih = c1.text_input("Tarih (GG.AA.YYYY)", safe_text(ai_data.get("tarih", "")))
            harcama_turu = c1.text_input("Harcama Türü", safe_text(ai_data.get("harcama_turu", "")))
            
            sec_kat = c1.selectbox("Kategori", list(kategoriler.keys()), index=list(kategoriler.keys()).index(ai_kat) if ai_kat in kategoriler else 0)
            
            toplam_tutar = c2.number_input("Tutar (TL)", float(ai_data.get("toplam_tutar", 0.0)), step=10.0)
            kdv_orani = c2.number_input("KDV Oranı (%)", float(ai_data.get("kdv_orani", 0.0)), step=1.0)
            kdv_tutari = c2.number_input("KDV Tutarı (TL)", float(ai_data.get("kdv_tutari", 0.0)), step=1.0)
            
            sec_mar = c2.selectbox("İlaç", markalar, index=markalar.index(ai_mar) if ai_mar in markalar else 0)

            if st.form_submit_button("💾 Sisteme Kaydet", use_container_width=True) and toplam_tutar > 0:
                aktif_donem = get_donem(tarih)
                df_k = pd.DataFrame(kisisel_masraflar) if kisisel_masraflar else pd.DataFrame()
                
                # YENİ ESNEME MANTIĞI: Toplam Kategori Bütçesine Göre Kontrol (İlaç Farketmez)
                kategori_harcanan = df_k[(df_k['Dönem'] == aktif_donem) & (df_k['kategori'] == sec_kat)]['toplam_tutar'].sum() if not df_k.empty else 0
                kategori_limit = kategoriler[sec_kat]['limit']
                
                # Sadece Kategori Genel Limiti + 200 TL Aşılırsa Hata Verir
                if (kategori_harcanan + toplam_tutar) > (kategori_limit + 200):
                    st.error(f"❌ KATEGORİ LİMİT AŞIMI! {sec_kat} kategorisi için kalan toplam bütçeniz {(kategori_limit - kategori_harcanan):,.2f} TL. Genel kategoride en fazla 200 TL esneme payı (aşım) yapabilirsiniz.")
                else:
                    db.collection('masraflar').add({
                        "username": username, "kullanici_adi": name, "tarih": tarih,
                        "isletme": isletme, "kategori": sec_kat, "marka": sec_mar, 
                        "toplam_tutar": float(toplam_tutar), "kdv_orani": float(kdv_orani),
                        "kdv_tutari": float(kdv_tutari), "fis_no": fis_no, "harcama_turu": harcama_turu,
                        "gorsel_b64": compress_and_encode_image(image),
                        "timestamp": firestore.SERVER_TIMESTAMP
                    })
                    st.success("✅ Kaydedildi!")
                    st.rerun()

# --- 3. SEKME: DESTEK & SORUN BİLDİR ---
with tab_destek:
    st.markdown("<h3 style='text-align:center;'>🚨 Sistem Destek & Sorun Bildirimi</h3>", unsafe_allow_html=True)
    st.info("Sistemde bir hata, yanlış bir kayıt veya ekleyemediğiniz bir fiş mi var? Buradan yazın, yapay zeka analiz edip yöneticiye iletecektir.")
    
    with st.form("sorun_formu"):
        sorun_metni = st.text_area("Karşılaştığınız sorunu detaylıca açıklayın:")
        if st.form_submit_button("Yöneticiye İlet", use_container_width=True):
            if sorun_metni:
                with st.spinner("Yapay zeka sorununuzu analiz ediyor..."):
                    try:
                        model = genai.GenerativeModel('gemini-2.5-flash')
                        prompt = f"Bir kullanıcı şu sorunu yaşadı: '{sorun_metni}'. Uygulama yetkilisi için kısa bir teşhis ve çözüm önerisi yaz."
                        ai_analiz = model.generate_content(prompt).text
                        
                        bildirim = {
                            "kullanici": name,
                            "sorun": sorun_metni,
                            "ai_analizi": ai_analiz,
                            "zaman": datetime.now().strftime("%d.%m.%Y %H:%M")
                        }
                        db.collection('sorun_bildirimleri').add(bildirim)
                        
                        mail_icerik = f"Kullanıcı: {name}\nSorun: {sorun_metni}\n\nAI Analizi:\n{ai_analiz}"
                        send_email_to_admin("Yeni Sorun Bildirimi", mail_icerik)
                        
                        st.success("Sorununuz analiz edildi ve yöneticiye güvenli bir şekilde iletildi.")
                    except:
                        db.collection('sorun_bildirimleri').add({"kullanici": name, "sorun": sorun_metni})
                        st.success("Mesajınız başarıyla iletildi.")

# --- ADMIN SEKMELERİ ---
if is_admin:
    with tab_ekip:
        tm = get_expenses(True)
        draw_dashboard(pd.DataFrame(tm), "👑 Tüm Ekip Harcamaları")
        
        df_tum = pd.DataFrame(tm)
        if not df_tum.empty:
            with st.expander("📋 Tüm Ekibin Geçmiş Harcamaları & Fiş Düzenleme", expanded=False):
                st.dataframe(df_tum[["Dönem", "kullanici_adi", "tarih", "kategori", "İlaç", "isletme", "toplam_tutar"]], use_container_width=True)
                st.divider()
                render_edit_interface(df_tum, prefix_key="admin")
        
    with tab_ayarlar:
        st.markdown("<h3 style='text-align:center;'>⚙️ Sistem ve Bütçe Ayarları</h3>", unsafe_allow_html=True)
        with st.form("ayar_form"):
            yk = {}
            for k, a in kategoriler.items():
                lim = st.number_input(f"{k} Limit", float(a['limit']), key=f"l_{k}")
                dap = st.slider(f"{k} Dapgeon %", 0, 100, int(a['dapgeon_oran']), key=f"o_{k}")
                yk[k] = {"limit": lim, "dapgeon_oran": dap, "liniga_oran": 100-dap}
            if st.form_submit_button("Ayarları Kalıcı Olarak Kaydet", type="primary", use_container_width=True):
                save_system_settings({"kategoriler": yk, "markalar": markalar})
                st.rerun()
                
        st.divider()
        st.subheader("🚨 Gelen Sorun Bildirimleri")
        docs = db.collection('sorun_bildirimleri').order_by('zaman', direction=firestore.Query.DESCENDING).limit(10).stream()
        for d in docs:
            b = d.to_dict()
            with st.expander(f"{b.get('zaman', '')} - {b.get('kullanici', '')}"):
                st.write(f"**Kullanıcının Sorunu:** {b.get('sorun', '')}")
                st.write(f"**Yapay Zeka Teşhisi:** {b.get('ai_analizi', 'Analiz yapılamadı.')}")


