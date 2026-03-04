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
import yaml
from yaml.loader import SafeLoader

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(page_title="Akıllı Masraf Portalı", layout="wide", page_icon="🧾")

# --- KİMLİK DOĞRULAMA (LOGIN) SİSTEMİ ---
try:
    # Parolaları otomatik olarak şifrelemek (hash) için sözlüğü yeniden oluşturuyoruz
    creds = {"usernames": {}}
    for u_name, u_info in st.secrets["credentials"]["usernames"].items():
        # Gizli boşluk karakterlerini temizliyoruz
        plain_pass = str(u_info["password"]).strip()
        # streamlit-authenticator v0.4.0+ uyumlu şifreleme metodu
        hashed_pass = stauth.Hasher.hash_passwords([plain_pass])[0]
        
        creds["usernames"][u_name] = {
            "email": u_info.get("email"),
            "name": u_info.get("name"),
            "password": hashed_pass
        }

    authenticator = stauth.Authenticate(
        creds,
        st.secrets["cookie"]["name"],
        st.secrets["cookie"]["key"],
        st.secrets["cookie"]["expiry_days"],
    )
    
    # Streamlit-authenticator v0.4+ uyumlu login
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

# --- GİRİŞ BAŞARILI: ÇIKIŞ BUTONU ---
authenticator.logout('Çıkış Yap', 'sidebar')
st.sidebar.write(f"Hoş geldin, *{name}* 👋")

# --- FIREBASE VERİTABANI BAĞLANTISI ---
@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        # Streamlit Secrets üzerinden Firebase JSON anahtarını okuyoruz
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
    """Görseli veritabanına sığacak şekilde küçültür ve Base64'e çevirir"""
    img = image.copy()
    img.thumbnail((800, 800)) # Boyutu sınırla
    buffered = io.BytesIO()
    img.save(buffered, format="JPEG", quality=70)
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

def get_expenses(is_admin=False, user_id=None):
    """Veritabanından masrafları çeker"""
    expenses_ref = db.collection('masraflar')
    if not is_admin:
        # Normal kullanıcı sadece kendi fişlerini görür
        query = expenses_ref.where('username', '==', user_id).stream()
    else:
        # Admin herkesin fişini görür
        query = expenses_ref.stream()
    
    data = []
    for doc in query:
        item = doc.to_dict()
        item['id'] = doc.id
        data.append(item)
    return data

# --- VERİ VE AYAR YÖNETİMİ (SESSION STATE) ---
if 'kategoriler' not in st.session_state:
    st.session_state['kategoriler'] = {
        "Temsil": {"limit": 7000.0, "dapgeon_oran": 60, "liniga_oran": 40},
        "Audiovisual": {"limit": 7000.0, "dapgeon_oran": 60, "liniga_oran": 40},
        "Bölgesel": {"limit": 3000.0, "dapgeon_oran": 60, "liniga_oran": 40}
    }

# --- YAN PANEL: AYARLAR (SADECE ADMİN GÖREBİLİR) ---
is_admin = (username == 'admin') # Admin kontrolü

if is_admin:
    st.sidebar.divider()
    st.sidebar.header("⚙️ Sistem Ayarları (Admin)")
    
    for kat_adi in list(st.session_state['kategoriler'].keys()):
        with st.sidebar.expander(f"{kat_adi} Ayarları", expanded=False):
            yeni_limit = st.number_input(f"Limit (TL) - {kat_adi}", value=float(st.session_state['kategoriler'][kat_adi]['limit']), key=f"lim_{kat_adi}")
            
            # %100 Kuralı: Dapgeon seçilince Liniga otomatik kalan olur
            dap_oran = st.slider(f"Dapgeon Oranı (%) - {kat_adi}", 0, 100, int(st.session_state['kategoriler'][kat_adi]['dapgeon_oran']), key=f"oran_{kat_adi}")
            lin_oran = 100 - dap_oran 
            st.info(f"Liniga Oranı (Otomatik): %{lin_oran}")
            
            st.session_state['kategoriler'][kat_adi]['limit'] = yeni_limit
            st.session_state['kategoriler'][kat_adi]['dapgeon_oran'] = dap_oran
            st.session_state['kategoriler'][kat_adi]['liniga_oran'] = lin_oran

    st.sidebar.divider()
    st.sidebar.subheader("➕ Yeni Kalem Ekle")
    yeni_kat_adi = st.sidebar.text_input("Kategori Adı (Örn: İlaç)")
    if st.sidebar.button("Kategoriyi Ekle") and yeni_kat_adi:
        if yeni_kat_adi not in st.session_state['kategoriler']:
            st.session_state['kategoriler'][yeni_kat_adi] = {"limit": 5000.0, "dapgeon_oran": 60, "liniga_oran": 40}
            st.sidebar.success(f"'{yeni_kat_adi}' eklendi!")
            st.rerun()

# --- ANA EKRAN ---
st.title("🧾 Akıllı Fiş Analiz ve Dağıtım Portalı")

tab_yeni, tab_gecmis = st.tabs(["➕ Yeni Fiş Yükle", "📊 Masraf Raporları"])

with tab_yeni:
    st.markdown("Fiş fotoğrafını yüklediğiniz an yapay zeka otomatik olarak okuyacaktır.")
    uploaded_file = st.file_uploader("Fiş veya Fatura Fotoğrafı Yükle", type=['png', 'jpg', 'jpeg'])

    if uploaded_file is not None:
        col_img, col_form = st.columns([1, 2])
        
        image = Image.open(uploaded_file)
        with col_img:
            st.image(image, caption="Yüklenen Fiş", use_column_width=True)
        
        with col_form:
            st.subheader("🤖 Yapay Zeka Analizi ve Düzenleme")
            
            # YENİ ÖZELLİK: Fiş yüklenir yüklenmez otomatik okuma (Sadece 1 kez çalışır)
            file_bytes = uploaded_file.getvalue()
            if st.session_state.get('last_uploaded') != file_bytes:
                st.session_state['last_uploaded'] = file_bytes
                st.session_state['ai_data'] = {} # Eski veriyi temizle
                
                with st.spinner("Yapay zeka fişi inceliyor, lütfen bekleyin..."):
                    try:
                        model = genai.GenerativeModel('gemini-2.5-flash')
                        prompt = """
                        Bu fiş/fatura görüntüsünü analiz et ve aşağıdaki bilgileri çıkar. Sadece geçerli bir JSON formatında yanıt ver. 
                        Format: {"isletme": "Ad", "fis_no": "No", "tarih": "GG.AA.YYYY", "harcama_turu": "Tür", "toplam_tutar": 150.50, "kdv_orani": 10, "kdv_tutari": 15.05}
                        Tutar ve KDV kısımları kesinlikle sayı (float) olmalıdır.
                        """
                        response = model.generate_content([prompt, image])
                        json_str = response.text.replace("```json", "").replace("```", "").strip()
                        st.session_state['ai_data'] = json.loads(json_str)
                        st.success("Analiz başarılı! Bilgileri kontrol edip kaydedebilirsiniz.")
                    except Exception as e:
                        st.error("Okuma sırasında hata oluştu. Lütfen bilgileri manuel giriniz.")
            
            # Manuel Düzenleme Formu
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
                    with st.spinner("Veritabanına kaydediliyor..."):
                        # Dağıtım Hesaplaması
                        oranlar = st.session_state['kategoriler'][secilen_kategori]
                        dapgeon_payi = round(toplam_tutar * (oranlar['dapgeon_oran'] / 100), 2)
                        liniga_payi = round(toplam_tutar * (oranlar['liniga_oran'] / 100), 2)
                        
                        # Resmi Base64 formatına çevir
                        img_base64 = compress_and_encode_image(image)
                        
                        # Veritabanına Ekleme
                        yeni_kayit = {
                            "username": username,
                            "kullanici_adi": name,
                            "tarih": tarih,
                            "isletme": isletme,
                            "fis_no": fis_no,
                            "harcama_turu": harcama_turu,
                            "kategori": secilen_kategori,
                            "toplam_tutar": toplam_tutar,
                            "kdv_orani": kdv_orani,
                            "kdv_tutari": kdv_tutari,
                            "dapgeon_payi": dapgeon_payi,
                            "liniga_payi": liniga_payi,
                            "gorsel_b64": img_base64,
                            "timestamp": firestore.SERVER_TIMESTAMP
                        }
                        
                        db.collection('masraflar').add(yeni_kayit)
                        st.success(f"Başarıyla kaydedildi! (Dapgeon: {dapgeon_payi} TL | Liniga: {liniga_payi} TL)")
                        st.session_state['last_uploaded'] = None # Formu sıfırlamak için

with tab_gecmis:
    st.header(f"📊 {'Tüm Ekip Harcamaları (Admin Paneli)' if is_admin else 'Kendi Harcamalarınız'}")
    
    masraflar_list = get_expenses(is_admin=is_admin, user_id=username)
    
    if masraflar_list:
        df = pd.DataFrame(masraflar_list)
        # Sütunları düzenle
        gosterilecek_sutunlar = ["tarih", "kullanici_adi", "isletme", "toplam_tutar", "kategori", "dapgeon_payi", "liniga_payi"]
        df_gosterim = df[gosterilecek_sutunlar].copy()
        
        st.dataframe(df_gosterim, use_container_width=True)
        
        # Fiş Görselini Görme Alanı
        st.divider()
        st.subheader("🔍 Fiş Görseli Görüntüleme")
        secilen_isletme = st.selectbox("Görselini görmek istediğiniz fişi seçin:", df['isletme'].tolist() + ["Seçiniz..."], index=len(df))
        
        if secilen_isletme != "Seçiniz...":
            secilen_kayit = df[df['isletme'] == secilen_isletme].iloc[0]
            if pd.notna(secilen_kayit.get('gorsel_b64')):
                image_bytes = base64.b64decode(secilen_kayit['gorsel_b64'])
                st.image(image_bytes, caption=f"{secilen_kayit['isletme']} - {secilen_kayit['toplam_tutar']} TL", width=400)
            else:
                st.warning("Bu fişe ait görsel bulunamadı.")
                
        # Bütçe Özeti (Sadece Admin için tüm bütçe)
        if is_admin:
            st.divider()
            st.subheader("📈 Kategori Bazlı Bütçe Tüketimi (Tüm Ekip)")
            kategori_toplam = df.groupby('kategori')['toplam_tutar'].sum().reset_index()
            for _, row in kategori_toplam.iterrows():
                kat = row['kategori']
                harcanan = row['toplam_tutar']
                limit = st.session_state['kategoriler'].get(kat, {}).get('limit', 0)
                if limit > 0:
                    yuzde = min((harcanan / limit) * 100, 100)
                    kalan = limit - harcanan
                    st.markdown(f"**{kat}:** {harcanan:,.2f} TL / {limit:,.2f} TL (Kalan: {kalan:,.2f} TL)")
                    st.progress(yuzde / 100)
    else:
        st.info("Henüz sisteme kaydedilmiş bir fiş bulunmuyor.")
