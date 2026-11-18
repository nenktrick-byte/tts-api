#!/usr/bin/env python3
"""
RENDER.COM FREE-TIER (512MB RAM) PROPERTY VIDEO WORKER & DRIVE UPLOADER
Siap ditempel ke repo Python (FastAPI atau Flask) seperti nenktrick-byte/tts-api.

Cara pasang di app.py / main.py Anda:
  from render_worker import register_render_routes
  register_render_routes(app)
"""

import os
import re
import gc
import json
import math
import uuid
import shutil
import tempfile
import threading
import subprocess
import requests
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1080, 1920, 30

GOLD_MAIN = (224, 189, 110)
GOLD_BRIGHT = (248, 224, 150)
WARM_WHITE = (248, 246, 240)
NAVY_PILL = (21, 50, 87)
MAROON_TOP = (142, 10, 10)
MAROON_BOT = (72, 2, 2)


def get_ffmpeg_bin():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def extract_drive_id(url):
    m = re.search(r"[-\w]{25,}", str(url or ""))
    return m.group(0) if m else None


_LAST_JOB = {"status": "idle"}


def _get_drive_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    sa_raw = (os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") or os.environ.get("GOOGLE_CREDENTIALS") or "").strip()
    if not sa_raw:
        raise RuntimeError("Env var GOOGLE_SERVICE_ACCOUNT_JSON / GOOGLE_CREDENTIALS belum diatur di Render.")
    creds = service_account.Credentials.from_service_account_info(
        json.loads(sa_raw),
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _download_via_drive_api(fid, out_path):
    from googleapiclient.http import MediaIoBaseDownload

    service = _get_drive_service()
    request = service.files().get_media(fileId=fid, supportsAllDrives=True)
    with open(out_path, "wb") as f:
        downloader = MediaIoBaseDownload(f, request, chunksize=1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    return out_path


def download_drive_or_http(url, out_path):
    fid = extract_drive_id(url)
    url_str = str(url or "")
    is_drive = bool(fid and ("drive.google.com" in url_str or "drive.usercontent.google.com" in url_str))
    dl_url = f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t" if is_drive else url
    try:
        with requests.get(dl_url, stream=True, timeout=60, allow_redirects=True) as r:
            r.raise_for_status()
            ctype = str(r.headers.get("Content-Type", "")).lower()
            if is_drive and "text/html" in ctype:
                raise RuntimeError("Drive returned HTML confirmation/login page")
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
        return out_path
    except Exception:
        if is_drive:
            return _download_via_drive_api(fid, out_path)
        raise


def load_render_fonts():
    """Memuat font dari folder ./fonts/ di repo (jika diunggah) atau font sistem Linux."""
    base = os.path.dirname(os.path.abspath(__file__))
    candidates_serif = [
        os.path.join(base, "fonts", "NotoSerifDisplay-Bold.ttf"),
        "/usr/share/fonts/truetype/noto/NotoSerifDisplay-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    ]
    candidates_sans = [
        os.path.join(base, "fonts", "Baloo2-Variable.ttf"),
        os.path.join(base, "fonts", "NotoSans-Bold.ttf"),
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    serif = next((p for p in candidates_serif if os.path.exists(p)), None)
    sans = next((p for p in candidates_sans if os.path.exists(p)), serif)

    def _f(path, size):
        if path:
            return ImageFont.truetype(path, size)
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()

    return {
        "hero": _f(serif, 88),
        "title": _f(serif, 74),
        "sub": _f(serif, 38),
        "kicker": _f(sans, 28),
        "pill": _f(sans, 28),
        "spec_num": _f(serif, 92),
        "price_rp": _f(serif, 32),
        "price_num": _f(serif, 98),
        "price_unit": _f(serif, 40),
        "cta": _f(serif, 36),
    }


def ease_out_cubic(x):
    x = max(0.0, min(1.0, x))
    return 1.0 - pow(1.0 - x, 3)


def ease_in_out_sine(x):
    x = max(0.0, min(1.0, x))
    return -(math.cos(math.pi * x) - 1.0) / 2.0


def sanitize_text(s):
    if not s:
        return ""
    s = re.sub(r"(\+?62|0)8[0-9\s.\-]{7,14}", "", str(s))
    s = re.sub(r"https?://\S+", "", s)
    s = re.sub(r"\b(lukman|properland)\b", "", s, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", s).strip(" •|-")


def draw_shadow_text(draw, xy, text, font, rgb, alpha=255, stroke=2):
    a = max(0, min(255, int(alpha)))
    if a <= 1 or not text:
        return
    x, y = int(xy[0]), int(xy[1])
    draw.text((x + 3, y + 4), text, font=font, fill=(6, 9, 14, int(a * 0.70)))
    draw.text(
        (x, y),
        text,
        font=font,
        fill=(rgb[0], rgb[1], rgb[2], a),
        stroke_width=stroke,
        stroke_fill=(8, 12, 18, int(a * 0.65)),
    )


def transform_fullbleed(cv_img, scale, tx_n, ty_n):
    ih, iw = cv_img.shape[:2]
    s = max(W / iw, H / ih) * scale
    max_dx = max(0.0, (iw * s - W) / 2.0)
    max_dy = max(0.0, (ih * s - H) / 2.0)
    tx = (W / 2.0) - s * (iw / 2.0) - max(-1.0, min(1.0, tx_n)) * max_dx
    ty = (H / 2.0) - s * (ih / 2.0) - max(-1.0, min(1.0, ty_n)) * max_dy
    M = np.float32([[s, 0, tx], [0, s, ty]])
    warped = cv2.warpAffine(cv_img, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
    return Image.fromarray(cv2.cvtColor(warped, cv2.COLOR_BGR2RGB))


def draw_scene_overlay(overlay, sc, t_sec, dur, fonts):
    layout = sc.get("layout_mode", "FULL_BLEED_TYPO")
    if layout == "PURE_PHOTO":
        return
    ov = sc.get("text_overlay", {})
    title = sanitize_text(ov.get("title", ""))
    subtitle = sanitize_text(ov.get("subtitle", ""))
    kicker = sanitize_text(ov.get("kicker", ""))
    price = sanitize_text(ov.get("price", ""))
    pos = str(ov.get("position", "lower_left")).lower()

    enter_p = ease_out_cubic(min(1.0, t_sec / 0.50))
    exit_p = max(0.0, min(1.0, (dur - t_sec) / 0.28))
    a = enter_p * exit_p
    if a <= 0.01:
        return

    draw = ImageDraw.Draw(overlay)

    if layout in ("CINEMATIC_END", "CINEMATIC_CLOSING"):
        dy = int((1.0 - enter_p) * 28)
        draw_shadow_text(draw, (110, 1260 + dy), title or "KEMANG", fonts["hero"], GOLD_MAIN, 255 * a)
        if subtitle:
            draw_shadow_text(draw, (110, 1365 + dy), subtitle, fonts["cta"], WARM_WHITE, 255 * a)
        if price:
            draw_shadow_text(draw, (110, 1435 + dy), price, fonts["spec_num"], GOLD_BRIGHT, 255 * a)
        return

    y_base = 230 if "top" in pos else 1320
    dy = int((1.0 - enter_p) * 30)
    if kicker:
        draw_shadow_text(draw, (96, y_base - 44 + dy), kicker, fonts["kicker"], WARM_WHITE, 240 * a)
    if title:
        draw_shadow_text(draw, (96, y_base + dy), title[:34], fonts["title"], GOLD_MAIN, 255 * a)
    if subtitle:
        draw_shadow_text(draw, (96, y_base + 92 + dy), subtitle[:48], fonts["sub"], GOLD_BRIGHT, 250 * a)


def render_job_to_mp4_low_ram(payload, work_dir):
    sb = payload.get("storyboard", {})
    scenes = sb.get("scenes", [])
    if not scenes:
        raise ValueError("Storyboard tidak memiliki scenes.")

    vo_url = payload.get("audio_url") or sb.get("audio_url")
    vo_path = os.path.join(work_dir, "vo.wav")
    has_audio = False
    if vo_url:
        download_drive_or_http(vo_url, vo_path)
        has_audio = os.path.exists(vo_path) and os.path.getsize(vo_path) > 1000

    out_name = payload.get("output_filename") or f"VIDEO_PROPERTY_{uuid.uuid4().hex[:8]}.mp4"
    out_mp4 = os.path.join(work_dir, out_name)
    ffmpeg_bin = get_ffmpeg_bin()
    fonts = load_render_fonts()

    cmd = [
        ffmpeg_bin, "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{W}x{H}", "-pix_fmt", "rgb24", "-r", str(FPS), "-i", "-",
    ]
    if has_audio:
        cmd += ["-i", vo_path, "-c:a", "aac", "-b:a", "128k"]
    cmd += [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-threads", "1", "-pix_fmt", "yuv420p", "-shortest", "-movflags", "+faststart",
        out_mp4,
    ]

    ffmpeg_log_path = os.path.join(work_dir, "ffmpeg.log")
    with open(ffmpeg_log_path, "wb") as log_f:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log_f)
        for idx, sc in enumerate(scenes):
            img_url = sc.get("image_url")
            if not img_url:
                continue
            img_local = os.path.join(work_dir, f"sc_{idx:02d}.jpg")
            download_drive_or_http(img_url, img_local)
            cv_im = cv2.imread(img_local)
            if cv_im is None:
                continue

            dur = float(sc.get("duration_seconds", 4.0))
            n_frames = max(1, int(round(dur * FPS)))
            for f_idx in range(n_frames):
                t_sec = f_idx / float(FPS)
                p = ease_in_out_sine(f_idx / max(1, n_frames - 1))
                scale = 1.02 + 0.06 * p
                canvas = transform_fullbleed(cv_im, scale, 0.0, 0.0).convert("RGBA")
                overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                draw_scene_overlay(overlay, sc, t_sec, dur, fonts)
                frame_rgb = np.array(Image.alpha_composite(canvas, overlay).convert("RGB"))
                proc.stdin.write(frame_rgb.tobytes())

            del cv_im
            gc.collect()

        proc.stdin.close()
        ret = proc.wait()

    if ret != 0:
        err_tail = ""
        if os.path.exists(ffmpeg_log_path):
            with open(ffmpeg_log_path, "r", encoding="utf-8", errors="ignore") as f:
                err_tail = f.read()[-400:]
        raise RuntimeError(f"FFmpeg error (code {ret}): {err_tail}")
    return out_mp4, out_name


def upload_to_drive_service_account(local_path, file_name, folder_id):
    from googleapiclient.http import MediaFileUpload

    service = _get_drive_service()
    meta = {"name": file_name, "parents": [folder_id]} if folder_id else {"name": file_name}
    media = MediaFileUpload(local_path, mimetype="video/mp4", resumable=True)
    created = service.files().create(
        body=meta,
        media_body=media,
        fields="id,webViewLink",
        supportsAllDrives=True,
    ).execute()
    try:
        service.permissions().create(
            fileId=created["id"],
            body={"type": "anyone", "role": "reader"},
            supportsAllDrives=True,
        ).execute()
    except Exception:
        pass
    return created.get("webViewLink") or f"https://drive.google.com/file/d/{created['id']}/view?usp=drivesdk"


def _set_last_job(**fields):
    _LAST_JOB.clear()
    _LAST_JOB.update(fields)
    print(f"[JOB] {json.dumps(_LAST_JOB, ensure_ascii=False)}", flush=True)


def _post_callback(callback_url, status, row_num, timeout=30, **extra):
    if not callback_url:
        print("[CALLBACK] skipped (callback_url empty)", flush=True)
        return
    body = {
        "status": status,
        "row_num": row_num,
        "secret": os.environ.get("RENDERER_API_KEY", ""),
        **extra,
    }
    resp = requests.post(callback_url, json=body, timeout=timeout)
    print(f"[CALLBACK] HTTP {resp.status_code}: {resp.text[:200]}", flush=True)


def _background_render_pipeline(payload):
    work_dir = tempfile.mkdtemp(prefix="prop_render_")
    callback_url = payload.get("callback_url")
    row_num = payload.get("row_num")
    _set_last_job(type="render", status="running", row_num=row_num)
    try:
        out_mp4, out_name = render_job_to_mp4_low_ram(payload, work_dir)
        video_url = upload_to_drive_service_account(out_mp4, out_name, payload.get("drive_folder_id"))
        _set_last_job(type="render", status="VIDEO_READY", row_num=row_num, video_url=video_url)
        _post_callback(callback_url, "VIDEO_READY", row_num, timeout=30, video_url=video_url)
    except Exception as e:
        _set_last_job(type="render", status="ERROR", row_num=row_num, error=str(e))
        try:
            _post_callback(callback_url, "ERROR", row_num, timeout=20, error=str(e))
        except Exception as cb_err:
            print(f"[CALLBACK_ERR] {cb_err}", flush=True)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        gc.collect()


def _merge_drive_parts_job(part_ids, output_filename, target_folder_id, callback_url, row_num):
    work_dir = tempfile.mkdtemp(prefix="merge_mp4_")
    safe_name = os.path.basename(output_filename or "VIDEO_PROPERTY_1947_V4_HYBRID_LUXURY_HD.mp4")
    out_path = os.path.join(work_dir, safe_name)
    _set_last_job(type="merge", status="running", row_num=row_num, output_filename=safe_name, total_parts=len(part_ids))
    try:
        with open(out_path, "wb") as out_f:
            for idx, fid in enumerate(part_ids):
                part_path = os.path.join(work_dir, f"part_{idx:02d}.bin")
                print(f"[MERGE] downloading part {idx + 1}/{len(part_ids)} ({fid})", flush=True)
                download_drive_or_http(f"https://drive.google.com/uc?export=download&id={fid}", part_path)
                with open(part_path, "rb") as pf:
                    shutil.copyfileobj(pf, out_f, length=1024 * 1024)
                os.remove(part_path)

        size_mb = round(os.path.getsize(out_path) / (1024 * 1024), 2)
        print(f"[MERGE] uploading {safe_name} ({size_mb} MB) to folder {target_folder_id}", flush=True)
        video_url = upload_to_drive_service_account(out_path, safe_name, target_folder_id)
        _set_last_job(type="merge", status="VIDEO_READY", row_num=row_num, output_filename=safe_name, size_mb=size_mb, video_url=video_url)
        _post_callback(callback_url, "VIDEO_READY", row_num, timeout=30, video_url=video_url)
    except Exception as e:
        _set_last_job(type="merge", status="ERROR", row_num=row_num, output_filename=safe_name, error=str(e))
        try:
            _post_callback(callback_url, "ERROR", row_num, timeout=20, error=str(e))
        except Exception as cb_err:
            print(f"[CALLBACK_ERR] {cb_err}", flush=True)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        gc.collect()


def _is_authorized(auth_header):
    expected = os.environ.get("RENDERER_API_KEY", "").strip()
    if not expected:
        return True
    token = str(auth_header or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token == expected


def register_render_routes(app):
    """Otomatis mendeteksi FastAPI atau Flask dan mendaftarkan route render & merge."""
    app_type = type(app).__name__.lower()
    if "fastapi" in app_type:
        from fastapi import Request
        from fastapi.responses import JSONResponse

        @app.get("/last-job")
        async def last_job_endpoint():
            return JSONResponse(status_code=200, content=_LAST_JOB)

        @app.post("/render-property-video")
        async def render_property_endpoint(request: Request):
            if not _is_authorized(request.headers.get("authorization")):
                return JSONResponse(status_code=401, content={"status": "error", "message": "Unauthorized"})
            payload = await request.json()
            job_id = uuid.uuid4().hex[:10]
            threading.Thread(target=_background_render_pipeline, args=(payload,), daemon=True).start()
            return JSONResponse(status_code=202, content={"status": "accepted", "job_id": job_id})

        @app.post("/merge-drive-parts")
        async def merge_drive_parts_endpoint(request: Request):
            if not _is_authorized(request.headers.get("authorization")):
                return JSONResponse(status_code=401, content={"status": "error", "message": "Unauthorized"})
            payload = await request.json()
            part_ids = payload.get("part_ids", [])
            output_filename = payload.get("output_filename", "VIDEO_PROPERTY_1947_V4_HYBRID_LUXURY_HD.mp4")
            target_folder_id = payload.get("target_folder_id", "13dsLrLyOhC3pw0YXHbIMxgdBL5Y6-4lM")
            callback_url = payload.get("callback_url")
            row_num = payload.get("row_num")

            if not part_ids:
                return JSONResponse(status_code=400, content={"status": "error", "message": "part_ids kosong"})

            threading.Thread(
                target=_merge_drive_parts_job,
                args=(part_ids, output_filename, target_folder_id, callback_url, row_num),
                daemon=True,
            ).start()
            return JSONResponse(status_code=202, content={"status": "accepted", "output_filename": output_filename})
    else:
        from flask import request, jsonify

        @app.route("/render-property-video", methods=["POST"])
        def render_property_endpoint():
            if not _is_authorized(request.headers.get("Authorization")):
                return jsonify({"status": "error", "message": "Unauthorized"}), 401
            payload = request.get_json(force=True) or {}
            job_id = uuid.uuid4().hex[:10]
            threading.Thread(target=_background_render_pipeline, args=(payload,), daemon=True).start()
            return jsonify({"status": "accepted", "job_id": job_id}), 202
