"""Deepgram TTS: turn each line of a script JSON into an mp3.

Reads the key from Appwrite/.env (TTS=...), never prints it.
Usage: python tts.py <script.json> <out_dir> [voice]
"""
import json
import sys
from pathlib import Path

import requests

KEY_FILE = Path("/Users/sanchaysingh/Desktop/Hackathons/Appwrite/.env")


def key():
    for line in KEY_FILE.read_text().splitlines():
        if line.startswith("TTS="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no TTS key")


def speak(text, out, voice):
    r = requests.post(f"https://api.deepgram.com/v1/speak?model={voice}&encoding=mp3",
                      headers={"Authorization": f"Token {key()}", "Content-Type": "application/json"},
                      json={"text": text}, timeout=120)
    if not r.ok:
        raise SystemExit(f"deepgram {r.status_code}: {r.text[:200]}")
    Path(out).write_bytes(r.content)


if __name__ == "__main__":
    script, out_dir = sys.argv[1], Path(sys.argv[2])
    voice = sys.argv[3] if len(sys.argv) > 3 else "aura-2-arcas-en"
    out_dir.mkdir(parents=True, exist_ok=True)
    for scene in json.loads(Path(script).read_text()):
        target = out_dir / f"{scene['id']}.mp3"
        if not target.exists():
            speak(scene["vo"], target, voice)
            print("spoke", scene["id"])
