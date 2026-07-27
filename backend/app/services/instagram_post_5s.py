import logging
import os
import subprocess


def normalize_multiline_text(value: str | None, *, max_length: int | None = None) -> str | None:
    text = "\n".join(
        line
        for line in (
            " ".join(raw_line.split())
            for raw_line in (value or "").replace("\r\n", "\n").split("\n")
        )
        if line
    ).strip()
    if max_length is not None:
        text = text[:max_length].strip()
    return text or None


def build_integrated_card_prompt(
    *,
    title: str,
    description: str | None,
    cta_text: str | None,
    user_direction: str | None,
) -> str:
    cta_block = cta_text or "У меня про тендеры и бизнес\nПОДПИШИСЬ ↓"
    prompt = (
        "Create a final ready-to-publish vertical Instagram card image, 9:16. "
        "Do not create a background for later overlays. Do not add a red title plate. "
        "All text must be naturally designed inside the generated image itself.\n\n"
        "Use the provided Instagram post as content/style reference and use the provided author face reference for the person. "
        "Build a new clean Russian infographic card "
        "similar to the reference format: warm yellow/gold background, a large rounded off-white content panel, "
        "bold black Russian typography, bullet/list structure when useful, a short conclusion, and a realistic cutout "
        "of the same author from the face reference, pointing toward the CTA or content. The person must not cover important text.\n\n"
        "Exact Russian headline to include prominently near the top:\n"
        f"{title}\n\n"
        "Use this rewritten context to create concise bullet points and/or a conclusion on the card, without copying ads, "
        "links, mentions, watermarks or foreign CTA from the source:\n"
        f"{(description or title)[:900]}\n\n"
        "Exact CTA text to include as a natural lower CTA box inside the generated card:\n"
        f"{cta_block}\n\n"
        "Layout rules: no red rectangles, no separate overlay plate, no app UI, no logos, no watermarks, no random extra CTA. "
        "The card must look like a complete designed social post screenshot, with readable Russian text and enough spacing."
    )
    if user_direction:
        prompt += (
            "\n\nMandatory user creative direction. Follow this unless it conflicts with readable Russian text, "
            "the exact CTA/headline, or safety rules:\n"
            f"{user_direction[:1200]}"
        )
    return prompt


def render_static_card_video(
    *,
    image_path: str,
    output_path: str,
    audio_path: str | None = None,
    duration_seconds: float = 5.0,
    timeout_seconds: int = 900,
) -> tuple[str | None, dict]:
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    temp_path = f"{output_path}.tmp.mp4"
    use_audio_path = audio_path if audio_path and os.path.isfile(audio_path) else None
    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-t",
        f"{duration_seconds:.3f}",
        "-i",
        image_path,
    ]
    if use_audio_path:
        cmd.extend(["-stream_loop", "-1", "-i", use_audio_path])
    else:
        cmd.extend([
            "-f",
            "lavfi",
            "-t",
            f"{duration_seconds:.3f}",
            "-i",
            "anullsrc=r=48000:cl=stereo",
        ])
    cmd.extend([
        "-t",
        f"{duration_seconds:.3f}",
        "-vf",
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-r",
        "30",
        "-c:v",
        "libx264",
        "-preset",
        os.getenv("FFMPEG_X264_PRESET", "veryfast"),
        "-crf",
        os.getenv("FFMPEG_X264_CRF", "18"),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-shortest",
        "-movflags",
        "+faststart",
        temp_path,
    ])
    meta = {
        "status": "skipped",
        "image_path": image_path,
        "audio_path": use_audio_path,
        "output_path": output_path,
        "duration_seconds": duration_seconds,
        "reason": None,
    }
    logging.info("Rendering integrated Instagram post 5s video: %s", " ".join(cmd))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds)
    except Exception as exc:
        meta["status"] = "failed"
        meta["reason"] = str(exc)
        return None, meta
    if result.returncode != 0:
        meta["status"] = "failed"
        meta["reason"] = (result.stderr or result.stdout or "ffmpeg failed")[-1200:]
        return None, meta
    os.replace(temp_path, output_path)
    meta["status"] = "ready"
    return output_path, meta
