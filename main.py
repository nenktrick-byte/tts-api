import os
import json
import re
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import edge_tts
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

app = FastAPI()

# Format data yang akan dikirim dari Google Sheet
class Artikel(BaseModel):
    id_baris: str
    tanggal: str
    judul: str
    teks_fatwa: str
    folder_id: str

@app.post("/generate")
async def generate_audio(artikel: Artikel):
    try:
        # 1. Autentikasi Google Drive (Menggunakan Service Account dari Environment Variable)
        creds_json = os.environ.get("GOOGLE_CREDENTIALS")
        creds_dict = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(creds_dict)
        drive_service = build('drive', 'v3', credentials=creds)

        # 2. Bersihkan Teks & Rangkai Nama File
        teks_bersih = re.sub(r'[\(\)\[\]/]', ' ', artikel.teks_fatwa)
        teks_bersih = re.sub(r'\s+', ' ', teks_bersih).strip()

        judul_bersih = re.sub(r'[\\/*?:"<>|]', '', artikel.judul).strip()
        if len(judul_bersih) > 60: judul_bersih = judul_bersih[:60] + "..."

        nama_file = f"{artikel.id_baris}-{artikel.tanggal}-{judul_bersih}.mp3"
        local_path = f"/tmp/{nama_file}" # Disimpan sementara di server Render

        # 3. Generate Audio ke MP3
        communicate = edge_tts.Communicate(teks_bersih, "id-ID-ArdiNeural")
        await communicate.save(local_path)

        # 4. Upload ke Google Drive & Set Publik
        file_metadata = {'name': nama_file, 'parents': [artikel.folder_id]}
        media = MediaFileUpload(local_path, mimetype='audio/mp3')
        file_drive = drive_service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        drive_service.permissions().create(fileId=file_drive.get('id'), body={'type': 'anyone', 'role': 'reader'}).execute()

        # 5. Hapus file MP3 di Render agar memori tidak penuh
        os.remove(local_path) 

        return {"status": "success", "link": file_drive.get('webViewLink')}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
