import hashlib
import io
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings
from app.modules.moodboards.model import new_id


class InvalidImage(ValueError):
    pass


def storage_path(key: str) -> Path:
    root = Path(settings.moodboard_storage_dir).resolve()
    path = (root / key).resolve()
    if path.parent != root:
        raise InvalidImage("Invalid storage key")
    return path


def prepare_image(data: bytes):
    if len(data) > settings.moodboard_max_file_bytes:
        raise InvalidImage("Gambar melebihi batas ukuran file")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as original:
                fmt = original.format
                if fmt not in {"JPEG", "PNG", "WEBP"}:
                    raise InvalidImage("Hanya JPEG, PNG, dan WebP didukung")
                if getattr(original, "n_frames", 1) != 1:
                    raise InvalidImage("Gambar animasi tidak didukung")
                if original.width * original.height > settings.moodboard_max_pixels:
                    raise InvalidImage("Resolusi melebihi batas megapiksel")
                original.verify()
            with Image.open(io.BytesIO(data)) as original:
                image = ImageOps.exif_transpose(original)
                image.load()
                width, height = image.size
                notes = []
                if min(width, height) < 256:
                    notes.append("Resolusi rendah; detail atau teks mungkin tidak terbaca.")
                image = image.convert("RGBA")
                if image.getextrema()[3][0] < 255:
                    notes.append("Salinan analisis memakai latar putih untuk transparansi.")
                background = Image.new("RGBA", image.size, "white")
                background.alpha_composite(image)
                preview = background.convert("RGB")
                preview.thumbnail((settings.moodboard_analysis_size, settings.moodboard_analysis_size))
                output = io.BytesIO()
                preview.save(output, "JPEG", quality=90)
    except InvalidImage:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise InvalidImage("File gambar rusak atau tidak aman untuk didekode") from exc
    return {"checksum": hashlib.sha256(data).hexdigest(), "mime_type": Image.MIME[fmt],
            "width": width, "height": height, "size_bytes": len(data), "warnings": notes}, output.getvalue()


def save_image(data: bytes, preview: bytes):
    token = new_id("img")
    original_key, analysis_key = token + ".original", token + ".jpg"
    storage_path(original_key).parent.mkdir(parents=True, exist_ok=True)
    try:
        storage_path(original_key).write_bytes(data)
        storage_path(analysis_key).write_bytes(preview)
    except OSError:
        remove_image(original_key, analysis_key)
        raise
    return original_key, analysis_key


def remove_image(*keys):
    for key in keys:
        storage_path(key).unlink(missing_ok=True)
