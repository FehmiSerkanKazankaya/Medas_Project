import streamlit as st
import sqlite3
import pandas as pd
import os
from PyPDF2 import PdfReader
import google.generativeai as genai
import datetime
import time

# Veritabanına bağlan
conn = sqlite3.connect("duyurular.db")
cursor = conn.cursor()

# Tabloları oluştur

cursor.execute("""
    CREATE TABLE IF NOT EXISTS chat_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dosya_adi TEXT,
        soru TEXT,
        cevap TEXT,
        tarih TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")
conn.commit()

# Gemini API'yi başlat
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('models/gemini-1.5-flash-latest')

# --- ÖZETLER BÖLÜMÜ ---
st.title("CHATBOT " \
"Özet Arayüzü")

# Veritabanından duyuru özetlerini çek
cursor.execute("SELECT dosya_adi, tarih, ozet FROM ozetler ORDER BY tarih DESC")
rows = cursor.fetchall()

if not rows:
    st.warning("Henüz özetlenmiş dosya bulunmuyor.")
else:
    search_term = st.text_input("🔍 Dosya adı veya özet içinde ara:")
    df = pd.DataFrame(rows, columns=["Dosya Adı", "Tarih", "Özet"])

    if search_term:
        df = df[df.apply(lambda row: search_term.lower() in row["Dosya Adı"].lower() or search_term.lower() in row["Özet"].lower(), axis=1)]

    for index, row in df.iterrows():
        with st.expander(f"📌 {row['Dosya Adı']} - {row['Tarih']}"):
            st.write(row['Özet'])

st.markdown("---")

# --- CHATBOT BÖLÜMÜ ---
st.header("Chatbot - PDF içeriğine dayalı yanıtlar")

# 📂 Klasörden PDF seçimi
pdf_folder = "indirilenler"
pdf_files = [f for f in os.listdir(pdf_folder) if f.endswith(".pdf")]

# 📥 Kullanıcıdan PDF yükleme
uploaded_file = st.file_uploader("İstersen buradan bir PDF yükle:", type="pdf")

selected_option = st.radio(
    "PDF kaynağını seç:",
    ("Klasörden Seç", "Yüklenen PDF'yi Kullan"),
    horizontal=True
)

selected_pdf = None
pdf_bytes = None

if selected_option == "Klasörden Seç":
    if pdf_files:
        selected_pdf = st.selectbox("Bir PDF seçin:", pdf_files)
    else:
        st.error("Klasörde hiç PDF bulunamadı.")
elif selected_option == "Yüklenen PDF'yi Kullan":
    if uploaded_file is not None:
        pdf_bytes = uploaded_file.read()
    else:
        st.info("Lütfen bir PDF yükleyin.")

# Kullanıcıdan soru al
user_question = st.text_input("Sorunuzu yazın:")

use_summary = st.checkbox("Yanıtları birleştirerek özetle", value=True)

# PDF'ten metin çıkarma fonksiyonu
def extract_text_from_pdf(file_path=None, file_bytes=None):
    text = ""
    try:
        if file_path:
            with open(file_path, "rb") as file:
                reader = PdfReader(file)
                for page in reader.pages:
                    text += page.extract_text() or ""
        elif file_bytes:
            from io import BytesIO
            reader = PdfReader(BytesIO(file_bytes))
            for page in reader.pages:
                text += page.extract_text() or ""
    except Exception as e:
        st.error(f"PDF okunamadı: {e}")
    return text

def safe_generate(prompt, max_retries=3, wait_time=15):
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            time.sleep(3)
            return response.text.strip()
        except Exception as e:
            if "429" in str(e):
                st.warning(f"⚠️ Kota sınırı aşıldı (deneme {attempt+1}). {wait_time} saniye bekleniyor...")
                time.sleep(wait_time)
            else:
                raise e
    raise Exception("🚫 3 denemede de yanıt alınamadı. Lütfen daha sonra tekrar deneyin.")

# Eğer soru sorulduysa
if user_question:
    if (selected_option == "Klasörden Seç" and selected_pdf) or (selected_option == "Yüklenen PDF'yi Kullan" and uploaded_file):
        if selected_option == "Klasörden Seç":
            pdf_path = os.path.join(pdf_folder, selected_pdf)
            full_text = extract_text_from_pdf(file_path=pdf_path)
            pdf_name = selected_pdf
        else:
            full_text = extract_text_from_pdf(file_bytes=pdf_bytes)
            pdf_name = uploaded_file.name

        try:
            with st.spinner("🤖 Yanıt oluşturuluyor..."):
                chunk_size = 12000  # Her seferde 12000 karakter gönder
                chunks = [full_text[i:i+chunk_size] for i in range(0, len(full_text), chunk_size)]

                full_response = ""
                for i, chunk in enumerate(chunks):
                    prompt = f"""
                    Aşağıdaki mevzuat duyurusuna ait parça içeriğine göre şu soruya teknik ve detaylı yanıt ver: "{user_question}"

                    --- Parça {i+1} ---
                    {chunk}
                    """
                    partial_answer = safe_generate(prompt)
                    full_response += f"\n\n--- Parça {i+1} Cevabı ---\n{partial_answer}"

                if use_summary:
                  summary_prompt = f"""
                  Aşağıda parçalar halinde üretilmiş teknik yanıtlar bulunmaktadır. Bunları dikkate alarak bütünsel, açık ve tekrar içermeyen bir yanıt ver:

                  {full_response}
                  """
                  final_response = safe_generate(summary_prompt)
                else:
                  final_response = full_response


                st.success("✅ Yanıt:")
                st.write(final_response)

                # Chat geçmişine kaydet
                cursor.execute("INSERT INTO chat_history (dosya_adi, soru, cevap) VALUES (?, ?, ?)", (pdf_name, user_question, final_response))
                conn.commit()

        except Exception as e:
            st.error(f"❌ Hata oluştu: {e}")
    else:
        st.warning("Lütfen bir PDF seçin veya yükleyin.")

st.markdown("---")

# --- CHAT GEÇMİŞİ BÖLÜMÜ ---
st.header("Sohbet Geçmişi")

cursor.execute("SELECT id, dosya_adi, soru, cevap, tarih FROM chat_history ORDER BY tarih DESC")
chat_rows = cursor.fetchall()

if not chat_rows:
    st.info("Henüz sohbet geçmişi yok.")
else:
    for chat in chat_rows:
        chat_id, dosya_adi, soru, cevap, tarih = chat
        with st.container():
            with st.expander(f"❓ {soru} ({tarih.split(' ')[0]})", expanded=False):
                st.markdown(
                    f"""
                    <div style='
                        background-color: #1e1e1e;
                        color: #ffffff;
                        padding: 15px;
                        border-radius: 10px;
                        box-shadow: 0 2px 6px rgba(0,0,0,0.5);
                        margin-bottom: 10px;
                        font-size: 16px;
                        line-height: 1.6;
                    '>
                        <b>Yanıt:</b> {cevap}
                        <br><br>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                if st.button(f"🗑️ Bu sohbeti sil", key=f"delete_{chat_id}"):
                    cursor.execute("DELETE FROM chat_history WHERE id = ?", (chat_id,))
                    conn.commit()
                    st.success("✅ Sohbet silindi.")
                    st.rerun()

# Veritabanı bağlantısını kapat
conn.close()
    









