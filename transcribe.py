import os
import shutil
import imageio_ffmpeg

ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
ffmpeg_dir = os.path.dirname(ffmpeg_exe)
target_ffmpeg = os.path.join(ffmpeg_dir, "ffmpeg.exe")
if not os.path.exists(target_ffmpeg):
    shutil.copyfile(ffmpeg_exe, target_ffmpeg)
    print("Copied", ffmpeg_exe, "to", target_ffmpeg)

os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

print("Testing ffmpeg...")
import subprocess
subprocess.run(["ffmpeg", "-version"], check=True)

import whisper

print("Loading Whisper model (tiny)...")
model = whisper.load_model("tiny")

audio_file = r"c:/Users/karti/OneDrive/Desktop/sewasetu-ai-handout/DIRECTOR-NOTE.mp3"
print(f"Transcribing {audio_file}...")
result = model.transcribe(audio_file, fp16=False)

print("\n--- TRANSCRIPTION COMPLETE ---\n")
print(result["text"])

with open(r"c:/Users/karti/OneDrive/Desktop/sewasetu-ai-handout/DIRECTOR-NOTE.txt", "w", encoding="utf-8") as f:
    f.write(result["text"])

print("\nSaved transcription to DIRECTOR-NOTE.txt")
