# Panduan Integrasi Render Video ke Server Render.com (`api-tts-otomatis`)

Panduan singkat ini menghubungkan service Python Anda di Render (`https://api-tts-otomatis.onrender.com`, repo `nenktrick-byte/tts-api`) agar bisa merender video MP4 Full HD di latar belakang, langsung mengunggah ke Google Drive, lalu mengisi kolom `VIDEO_URL` di Google Sheets via `doPost()`.

## 1. File di Repo GitHub `nenktrick-byte/tts-api`
- `render_worker.py` sudah ditempatkan di root folder repo.
- `requirements.txt` sudah digabungkan dengan dependensi render (`imageio-ffmpeg`, `pillow`, `opencv-python-headless`, `numpy`, `requests`, `google-api-python-client`, `google-auth`).
- `main.py` sudah mendaftarkan route dengan `register_render_routes(app)`.
- *(Opsional)* Salin folder `fonts/` (berisi `NotoSerifDisplay-Bold.ttf` atau `Baloo2-Variable.ttf`) ke dalam repo agar font tampil persis sama.
- Commit & push ke branch `main` agar Render otomatis men-deploy ulang.

## 2. Atur Service Account Google Drive (Agar Bisa Upload > 10 MB)
1. Buka [Google Cloud Console](https://console.cloud.google.com/) → **IAM & Admin** → **Service Accounts** → buat Service Account baru → **Keys** → **Add Key** → **JSON**.
2. Buka isi file JSON tersebut, lalu di Dashboard Render (`api-tts-otomatis` → **Environment**), tambahkan Environment Variable:
   - Key: `GOOGLE_SERVICE_ACCOUNT_JSON`
   - Value: *(tempel seluruh isi JSON satu baris)*
   - *(Opsional, disarankan)* Tambahkan juga `RENDERER_API_KEY` yang nilainya sama dengan `RENDERER_API_KEY` di Script Properties GAS.
3. Buka folder Google Drive `EXTRACT VIDEO` (`13dsLrLyOhC3pw0YXHbIMxgdBL5Y6-4lM`), klik **Share**, dan tambahkan alamat email `client_email` dari Service Account tersebut sebagai **Editor**.

## 3. Hubungkan Google Apps Script (`Code.gs`)
1. Di Google Apps Script, klik **Deploy** → **New deployment** → **Web app** (*Execute as: Me*, *Who has access: Anyone*), lalu salin URL Web App-nya.
2. Di Google Sheets menu **🎬 PROPERLAND AI VIDEO** → **14. Pengaturan Renderer & BGM**, masukkan URL endpoint:
   `https://api-tts-otomatis.onrender.com/render-property-video`
3. Saat Anda memanggil fungsi render di GAS, GAS mengirim job ke Render (langsung dijawab `202 Accepted` dalam < 1 detik), Render merender MP4 di background, mengunggahnya ke Google Drive tanpa batas 10 MB, dan otomatis memanggil `doPost()` GAS untuk mengisi kolom `VIDEO_URL`.
