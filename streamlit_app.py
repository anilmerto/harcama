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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(page_title="Genveon Masraf Portalı", layout="wide", page_icon="🧾")

# --- GELİŞMİŞ MOBİL UYUM & GENEL TASARIM CSS ---
st.markdown("""
    <style>
        .block-container { max-width: 1100px !important; padding-top: 2rem !important; }
        .stTabs [data-baseweb="tab-list"] { justify-content: center; gap: 15px; border-bottom: 2px solid #f0f2f6; }
        .stTabs [data-baseweb="tab"] { font-size: 1.1rem; padding: 12px 20px; font-weight: 500; }
        @media (max-width: 768px) {
            [data-testid="stImage"] { display: flex; justify-content: center; align-items: center; }
            [data-testid="stImage"] img { max-width: 160px !important; height: auto; }
            .kurumsal-baslik { font-size: 18px !important; margin-bottom: 20px !important; text-align: center; }
            h1, h2, h3 { text-align: center; }
        }
        .kurumsal-baslik { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #2c3e50; font-weight: 300; text-align: center; font-size: 24px; margin-top: -10px; margin-bottom: 30px; letter-spacing: 1px; }
        .budget-card { background-color: #f8f9fa; border: 1px solid #e0e6ed; border-radius: 8px; padding: 15px; margin-bottom: 10px; }
        .budget-title { color: #2c3e50; font-weight: bold; font-size: 1.1rem; margin-bottom: 10px; border-bottom: 1px solid #dcdde1; padding-bottom: 5px; }
        .budget-row { display: flex; justify-content: space-between; margin-bottom: 4px; font-size: 0.95rem; }
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
        data = doc.to_dict()
        if 'butceler' not in data:
            data['butceler'] = {}
        return data
    else:
        default_settings = {
            "kategoriler": {
                "Temsil": {"limit": 7000.0, "dapgeon_oran": 60, "liniga_oran": 40},
                "Audiovisual": {"limit": 7000.0, "dapgeon_oran": 60, "liniga_oran": 40},
                "Bölgesel": {"limit": 3000.0, "dapgeon_oran": 60, "liniga_oran": 40}
            },
            "markalar": ["Dapgeon", "Liniga"],
            "butceler": {}
        }
        doc_ref.set(default_settings)
        return default_settings

def save_system_settings(settings_dict):
    db.collection('ayarlar').document('sistem').set(settings_dict)

if 'sistem_ayarlari' not in st.session_state:
    st.session_state['sistem_ayarlari'] = get_system_settings()

ayarlar = st.session_state['sistem_ayarlari']
genel_kategoriler = ayarlar.get('kategoriler', {})
if not genel_kategoriler:  # Güvenlik önlemi
    genel_kategoriler = {"Temsil": {"limit": 7000.0, "dapgeon_oran": 60, "liniga_oran": 40}}
    
markalar = ayarlar.get('markalar', ["Dapgeon", "Liniga"])
butceler = ayarlar.get('butceler', {})

def get_budget_for_period(donem_str):
    if donem_str in butceler and butceler[donem_str]:
        return butceler[donem_str]
    return genel_kategoriler

# --- KESİN DÖNEM LİSTESİ OLUŞTURUCU (2024-2027) ---
@st.cache_data
def get_all_periods():
    aylar = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    periods = []
    for year in range(2024, 2028):
        for month in range(1, 13):
            next_month = month + 1 if month < 12 else 1
            next_year = year if month < 12 else year + 1
            periods.append(f"15 {aylar[month]} {year} - 15 {aylar[next_month]} {next_year}")
    return periods

TUM_DONEMLER = get_all_periods()

def get_current_period_string():
    now = datetime.now()
    day, month, year = now.day, now.month, now.year
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

def calculate_period_from_date(tarih_str):
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
                donem_str = f"15 {aylar[bas_ay]} {bas_yil} - 15 {aylar[bit_ay]} {bit_yil}"
                if donem_str in TUM_DONEMLER:
                    return donem_str
    except:
        pass
    return get_current_period_string()

# --- KİMLİK DOĞRULAMA (SAYFA YENİLEME HATASI ÇÖZÜLDÜ) ---
# Cache'i geri ekledik ki sayfayı yenileyince şifreler uçmasın ve sistemden atılmayın!
@st.cache_data(show_spinner=False)
def get_hashed_credentials():
    credentials_dict = {"usernames": {}}
    users = dict(st.secrets["credentials"]["usernames"])
    for u_name, u_info in users.items():
        credentials_dict["usernames"][u_name] = {
            "email": u_info.get("email", ""),
            "name": u_info.get("name", u_name),
            "password": str(u_info["password"]).strip()
        }
    stauth.Hasher.hash_passwords(credentials_dict)
    return credentials_dict

try:
    credentials_dict = get_hashed_credentials()
    authenticator = stauth.Authenticate(
        credentials_dict, st.secrets["cookie"]["name"], st.secrets["cookie"]["key"], st.secrets["cookie"]["expiry_days"]
    )
except Exception as e:
    st.error("Giriş sistemi yapılandırılamadı. Yöneticinize başvurun.")
    st.stop()

auth_status = st.session_state.get("authentication_status")

# GİRİŞ EKRANI
if not auth_status:
    st.markdown("""
        <style>
            [data-testid="stFormSubmitButton"] button p { font-size: 0px !important; }
            [data-testid="stFormSubmitButton"] button p::before { content: "Sisteme Giriş Yap"; font-size: 16px !important; visibility: visible; }
        </style>
    """, unsafe_allow_html=True)
    st.markdown("<div style='display:flex; justify-content:center; margin-bottom: 20px;'>", unsafe_allow_html=True)
    try:
        if os.path.exists("logo.png"): st.image("logo.png", width=250)
        else: st.markdown("<h1 style='color: #3498db; text-align: center;'>GENVEON</h1>", unsafe_allow_html=True)
    except:
        st.markdown("<h1 style='color: #3498db; text-align: center;'>GENVEON</h1>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("<div class='kurumsal-baslik'>Masraf Takip Uygulaması</div>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        authenticator.login()
    
    if st.session_state.get("authentication_status") is False:
        st.error("Kullanıcı adı veya şifre hatalı!")
    st.stop()

# --- GİRİŞ BAŞARILI SONRASI ---
name = st.session_state.get("name")
username = st.session_state.get("username")
is_admin = (username == 'admin')

col_logo, col_space, col_user = st.columns([2, 1, 2])
with col_logo:
    try:
        if os.path.exists("logo.png"): st.image("logo.png", width=180)
        else: st.markdown("<h3 style='color: #3498db; margin:0;'>GENVEON</h3>", unsafe_allow_html=True)
    except: pass
with col_user:
    st.markdown(f"<div style='text-align: right; padding-top:10px;'>Hoş geldin, <b>{name}</b></div>", unsafe_allow_html=True)
    authenticator.logout('Çıkış', 'main')
st.divider()

# --- GEMINI YZ YAPILANDIRMASI ---
try: genai.configure(api_key=st.secrets["gemini"]["api_key"])
except: st.error("Gemini API bağlantı hatası!")

# --- YARDIMCI FONKSİYONLAR ---
def compress_and_encode_image(image):
    img = image.copy()
    img.thumbnail((800, 800))
    buffered = io.BytesIO()
    img.save(buffered, format="JPEG", quality=70)
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

def parse_amount(val):
    if isinstance(val, (int, float)): return float(val)
    val = str(val).strip()
    if not val: return 0.0
    separators = re.findall(r'[^\d]', val)
    if not separators: return float(val)
    if separators[-1] == ',': val = val.replace('.', '').replace(',', '.')
    elif separators[-1] == '.': val = val.replace(',', '')
    else:
        if val.count(',') == 1 and val.count('.') == 0: val = val.replace(',', '.')
        elif val.count('.') > 1 and val.count(',') == 0: val = val.replace('.', '')
        elif val.count('.') == 1 and val.count(',') == 0:
            if len(val.split('.')[1]) == 3: val = val.replace('.', '')
    val = re.sub(r'[^\d\.]', '', val)
    try: return float(val)
    except: return 0.0

def normalize_str(s): return re.sub(r'[\s\W_]+', '', str(s)).lower()

def safe_text(text):
    text = str(text)
    donusum = {"ı":"i", "İ":"I", "ş":"s", "Ş":"S", "ğ":"g", "Ğ":"G", "ü":"u", "Ü":"U", "ö":"o", "Ö":"O", "ç":"c", "Ç":"C"}
    for tr, en in donusum.items(): text = text.replace(tr, en)
    return text

def get_expenses(fetch_all=False, user_id=None):
    expenses_ref = db.collection('masraflar')
    query = expenses_ref.stream() if fetch_all else expenses_ref.where('username', '==', user_id).stream()
    data = []
    mevcut_kategoriler = list(genel_kategoriler.keys())
    
    for doc in query:
        item = doc.to_dict()
        item['id'] = doc.id
        
        ham_kat =
