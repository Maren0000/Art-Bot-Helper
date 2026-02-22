import hashlib
import io

from PIL import Image
import imagehash


def image_id(img: io.BytesIO) -> str:
    img = Image.open(img)
    img = img.convert("RGB")
    img = img.resize((1024, 1024), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return hashlib.sha256(buf.getvalue()).hexdigest()


def compute_hashes(img: io.BytesIO) -> dict:
    image = Image.open(img)
    return {
        "phash": imagehash.phash(image),
        "dhash": imagehash.dhash(image),
    }


def is_similar(h1: dict, h2: dict) -> bool:
    return (h1["phash"] - h2["phash"] <= 8) and (h1["dhash"] - h2["dhash"] <= 10)


def hamming(a, b):
    return a - b
