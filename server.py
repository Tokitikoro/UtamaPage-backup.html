from flask import Flask, request, send_file, jsonify
from pathlib import Path
import subprocess
import tempfile
import uuid
import zipfile

app = Flask(__name__, static_folder=".", static_url_path="")

MAX_FILE_SIZE = 25 * 1024 * 1024


@app.get("/")
def home():
    return app.send_static_file("index.html")


@app.post("/api/process")
def process_media():
    video = request.files.get("video")
    audio = request.files.get("audio")

    if not video or not video.filename:
        return jsonify({"error": "Video belum dipilih."}), 400

    video.seek(0, 2)
    video_size = video.tell()
    video.seek(0)

    if video_size > MAX_FILE_SIZE:
        return jsonify({"error": "Ukuran video maksimal 25 MB."}), 400

    work_dir = Path(tempfile.mkdtemp(prefix="soundstik_"))

    job_id = uuid.uuid4().hex
    video_ext = Path(video.filename).suffix.lower()

    if video_ext not in [".mp4", ".webm", ".mov"]:
        video_ext = ".mp4"

    video_path = work_dir / f"video{video_ext}"
    output_path = work_dir / f"soundstik-{job_id}.mp4"

    video.save(video_path)

    try:
        if audio and audio.filename:
            audio_ext = Path(audio.filename).suffix.lower()

            if not audio_ext:
                audio_ext = ".mp3"

            audio_path = work_dir / f"audio{audio_ext}"
            audio.save(audio_path)

            command = [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-i",
                str(audio_path),
                "-t",
                "6",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-vf",
                (
                    "scale=512:512:"
                    "force_original_aspect_ratio=decrease,"
                    "pad=512:512:"
                    "(ow-iw)/2:(oh-ih)/2:color=black"
                ),
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "28",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                "-shortest",
                "-movflags",
                "+faststart",
                str(output_path),
            ]

        else:
            command = [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-t",
                "6",
                "-vf",
                (
                    "scale=512:512:"
                    "force_original_aspect_ratio=decrease,"
                    "pad=512:512:"
                    "(ow-iw)/2:(oh-ih)/2:color=black"
                ),
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "28",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                "-movflags",
                "+faststart",
                str(output_path),
            ]

        result = subprocess.run(command, capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            print(result.stderr)

            return jsonify({"error": "FFmpeg gagal memproses media."}), 500

        return send_file(
            output_path,
            as_attachment=True,
            download_name="soundstik.mp4",
            mimetype="video/mp4",
        )

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Pemrosesan melebihi batas waktu 120 detik."}), 504

    except Exception as error:
        print(error)

        return jsonify({"error": "Terjadi kesalahan pada server."}), 500


@app.post("/api/create-assets")
def create_assets():
    video = request.files.get("video")
    audio = request.files.get("audio")

    if not video or not video.filename:
        return jsonify({"error": "Video belum dipilih."}), 400

    work_dir = Path(tempfile.mkdtemp(prefix="soundstik_assets_"))

    video_ext = Path(video.filename).suffix.lower()

    if video_ext not in [".mp4", ".webm", ".mov"]:
        video_ext = ".mp4"

    video_path = work_dir / f"video{video_ext}"
    sticker_path = work_dir / "sticker.webp"
    audio_path = work_dir / "audio.ogg"
    zip_path = work_dir / "soundstik-assets.zip"

    video.save(video_path)

    try:
        sticker_command = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-t",
            "6",
            "-an",
            "-vf",
            (
                "fps=15,"
                "scale=512:512:"
                "force_original_aspect_ratio=decrease,"
                "pad=512:512:"
                "(ow-iw)/2:(oh-ih)/2:"
                "color=0x00000000"
            ),
            "-c:v",
            "libwebp_anim",
            "-lossless",
            "0",
            "-quality",
            "70",
            "-loop",
            "0",
            "-preset",
            "picture",
            str(sticker_path),
        ]

        sticker_result = subprocess.run(
            sticker_command, capture_output=True, text=True, timeout=120
        )

        if sticker_result.returncode != 0:
            print(sticker_result.stderr)

            return jsonify({"error": "Gagal membuat stiker WebP."}), 500

        if audio and audio.filename:
            input_audio_ext = Path(audio.filename).suffix.lower() or ".mp3"

            input_audio_path = work_dir / f"audio-input{input_audio_ext}"

            audio.save(input_audio_path)
            audio_input = input_audio_path
        else:
            audio_input = video_path

        audio_command = [
            "ffmpeg",
            "-y",
            "-i",
            str(audio_input),
            "-t",
            "6",
            "-vn",
            "-c:a",
            "libopus",
            "-ac",
            "1",
            "-b:a",
            "64k",
            "-avoid_negative_ts",
            "make_zero",
            str(audio_path),
        ]

        audio_result = subprocess.run(
            audio_command, capture_output=True, text=True, timeout=120
        )

        if audio_result.returncode != 0:
            print(audio_result.stderr)

            return jsonify({"error": "Gagal membuat audio Opus."}), 500

        with zipfile.ZipFile(
            zip_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as zip_file:
            zip_file.write(sticker_path, arcname="sticker.webp")

            zip_file.write(audio_path, arcname="audio.ogg")

        return send_file(
            zip_path,
            as_attachment=True,
            download_name="soundstik-assets.zip",
            mimetype="application/zip",
        )

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Pemrosesan melebihi 120 detik."}), 504

    except Exception as error:
        print(error)

        return jsonify({"error": "Gagal membuat aset stiker."}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
