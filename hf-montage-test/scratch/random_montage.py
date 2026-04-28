import os
import random
import subprocess
from pathlib import Path

def get_clips(directory):
    path = Path(directory)
    clips = list(path.glob("*.mp4"))
    clips.sort()
    return [str(c) for c in clips]

def create_random_montage(clips, output_path):
    # Shuffle clips
    random_clips = clips[:]
    random.shuffle(random_clips)
    
    print(f"Creating montage: {output_path}")
    print("Clip order:")
    for i, clip in enumerate(random_clips):
        print(f"  {i+1}: {os.path.basename(clip)}")

    # Create a concat list file for FFmpeg
    concat_file = Path("concat_list.txt")
    with open(concat_file, "w") as f:
        for clip in random_clips:
            # Escape single quotes in filenames for FFmpeg concat file
            safe_path = clip.replace("'", "'\\''")
            f.write(f"file '{safe_path}'\n")

    try:
        # Use concat demuxer (faster, no re-encoding)
        # Note: This assumes all clips have identical parameters
        ffmpeg_bin = "/opt/homebrew/bin/ffmpeg"
        cmd = [
            ffmpeg_bin,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            output_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print("Direct copy failed, trying with re-encoding...")
            # Fallback to re-encoding if copy fails due to incompatible clips
            # This is slower but more robust
            cmd_reencode = [
                ffmpeg_bin,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c:v", "libx264",
                "-preset", "fast",
                "-c:a", "aac",
                output_path
            ]
            subprocess.run(cmd_reencode, check=True)
        
        print(f"Successfully created: {output_path}")
    finally:
        if concat_file.exists():
            concat_file.unlink()

if __name__ == "__main__":
    clips_dir = "/Users/nadaraya/Desktop/clips_1776827185311"
    renders_dir = Path("/Users/nadaraya/Desktop/Turan/hf-montage-test/renders")
    renders_dir.mkdir(parents=True, exist_ok=True)
    
    all_clips = get_clips(clips_dir)
    if not all_clips:
        print(f"No clips found in {clips_dir}")
        exit(1)
        
    create_random_montage(all_clips, str(renders_dir / "test_montage_1.mp4"))
    create_random_montage(all_clips, str(renders_dir / "test_montage_2.mp4"))
