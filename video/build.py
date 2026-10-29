"""Assemble the demo video from motion scenes, app takes and voice-over.

Each scene lasts its voice-over plus a little padding. Take segments are
sped up to fit: every segment gets speed k * weight, with k solved so the
segments add up to the scene length.

Usage: python build.py   ->  out/asli_demo.mp4 and thumbnails
"""
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
B = HERE / "build"
OUT = HERE / "out"
LEAD, TAIL = 0.25, 0.45   # silence before and after each voice-over
FPS = 30

# (source start, source end, relative speed weight)
CUTS = {
    "04_amazon_run": [(3.6, 6.9, 1.3), (6.9, 24.6, 1.0)],
    "05_amazon_verdict": [(24.6, 50.0, 1.0)],
    "06_flipkart": [(8.0, 19.5, 1.0), (19.5, 33.0, 4.0), (33.0, 40.5, 0.8)],
    "07_watch": [(5.3, 21.6, 1.0)],
    "09_hood": [(5.6, 16.2, 1.0)],
}
EXTRA = {"10_outro": 1.6}  # hold the end card a bit longer


def run(*args):
    subprocess.run(args, check=True)


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(r.stdout)


def video_filter(scene, total):
    """Filter graph that produces [v] of exactly `total` seconds from input 0."""
    if scene["kind"] == "motion":
        start = float((B / "motion" / f"{scene['id'][3:]}.start").read_text())
        return (f"[0:v]trim=start={start:.3f}:duration={total:.3f},setpts=PTS-STARTPTS,"
                f"fps={FPS},format=yuv420p[v]")
    segs = CUTS[scene["id"]]
    k = sum((e - s) / w for s, e, w in segs) / total
    parts, labels = [], []
    for i, (s, e, w) in enumerate(segs):
        speed = k * w
        parts.append(f"[0:v]trim=start={s}:end={e},setpts=(PTS-STARTPTS)/{speed:.4f},fps={FPS}[s{i}]")
        labels.append(f"[s{i}]")
    parts.append(f"{''.join(labels)}concat=n={len(segs)}:v=1:a=0,"
                 f"trim=duration={total:.3f},format=yuv420p[v]")
    print(f"  {scene['id']}: speeds " + ", ".join(f"{k * w:.2f}x" for _, _, w in segs))
    return ";".join(parts)


def build_scene(scene):
    vo = B / "vo" / f"{scene['id']}.mp3"
    total = LEAD + duration(vo) + TAIL + EXTRA.get(scene["id"], 0)
    src = (B / "motion" / f"{scene['id'][3:]}.webm" if scene["kind"] == "motion"
           else B / "takes2" / f"{scene['take']}.webm")
    out = B / "scenes" / f"{scene['id']}.mp4"
    delay = int(LEAD * 1000)
    graph = (video_filter(scene, total) +
             f";[1:a]adelay={delay}|{delay},apad,atrim=duration={total:.3f},"
             f"aformat=sample_rates=48000:channel_layouts=stereo[a]")
    run("ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-i", str(vo),
        "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out))
    return out, total


def main():
    script = json.loads((HERE / "script.json").read_text())
    (B / "scenes").mkdir(parents=True, exist_ok=True)
    OUT.mkdir(exist_ok=True)
    parts, total = [], 0.0
    for scene in script:
        path, secs = build_scene(scene)
        parts.append(path)
        total += secs
        print(f"{scene['id']}: {secs:.2f}s")
    listing = B / "scenes" / "list.txt"
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    joined = B / "scenes" / "joined.mp4"
    run("ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
        "-c", "copy", str(joined))
    # Fade in from black and out to black, loudness normalised for YouTube.
    final = OUT / "asli_demo.mp4"
    run("ffmpeg", "-loglevel", "error", "-y", "-i", str(joined),
        "-vf", f"fade=t=in:st=0:d=0.5,fade=t=out:st={total - 0.8:.2f}:d=0.8",
        "-af", f"loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=out:st={total - 0.8:.2f}:d=0.8",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k",
        "-ar", "48000", "-movflags", "+faststart", str(final))
    print(f"total {total:.1f}s -> {final}")


if __name__ == "__main__":
    main()
