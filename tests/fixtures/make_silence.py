"""Generate silence_30s.wav test fixture. Run once; wav is committed to repo."""
import subprocess
from pathlib import Path

def make_wav(path: Path, seconds: int, freq: int = 440) -> None:
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i",
        f"sine=frequency={freq}:duration={seconds}",
        "-ar", "16000", "-ac", "1", str(path),
    ], check=True, capture_output=True)
    print(f"created {path} ({path.stat().st_size} bytes)")

if __name__ == "__main__":
    here = Path(__file__).parent
    make_wav(here / "silence_30s.wav", 30)
