import os
import re
import uuid
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
import edge_tts

app = FastAPI()

class Artikel(BaseModel):
    teks_fatwa: str

def hapus_file(path: str):
    if os.path.exists(path):
        os.remove(path)

@app.post("/generate")
async def generate_audio(artikel: Artikel, background_tasks: BackgroundTasks):
    try:
        # Bersihkan teks
        teks_bersih = re.sub(r'[\(\)\[\]/]', ' ', artikel.teks_fatwa)
        teks_bersih = re.sub(r'\s+', ' ', teks_bersih).strip()
        
        # Buat file audio sementara
        nama_file = f"audio_{uuid.uuid4().hex}.mp3"
        local_path = f"/tmp/{nama_file}" if os.name != 'nt' else nama_file

        communicate = edge_tts.Communicate(teks_bersih, "id-ID-ArdiNeural")
        await communicate.save(local_path)

        # Hapus file otomatis setelah berhasil dikirim
        background_tasks.add_task(hapus_file, local_path)

        # Kembalikan file MP3 secara langsung!
        return FileResponse(local_path, media_type="audio/mpeg", filename=nama_file)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
