from pathlib import Path
from tortoise import Tortoise
import imagehash

from db.models import Image


def _hamming_distance(h1: str, h2: str) -> int:
    """Calculate hamming distance between two hex hash strings."""
    return imagehash.hex_to_hash(h1) - imagehash.hex_to_hash(h2)


class Database:
    _hash_cache: dict[str, int] | None = None  # phash -> image_id

    def __init__(self, path: str | Path):
        self.path = str(path)

    async def connect(self):
        await Tortoise.init(
            db_url=f"sqlite://{self.path}",
            modules={"models": ["db.models"]},
        )

        conn = Tortoise.get_connection("default")
        await conn.execute_query("PRAGMA foreign_keys = ON;")
        await conn.execute_query("PRAGMA journal_mode = WAL;")

        await Tortoise.generate_schemas()
        await self.load_hashes()

    async def load_hashes(self):
        """Load all phashes from database into cache for similarity search."""
        images = await Image.all().values("id", "phash")
        self._hash_cache = {img["phash"]: img["id"] for img in images}

    async def find_similar(self, phash: str, threshold: int = 8) -> list[Image]:
        """
        Find images with similar perceptual hash within threshold.
        Returns list of Image objects that are potential duplicates.
        """
        if self._hash_cache is None or not self._hash_cache:
            return []
        
        # Linear scan with hamming distance check
        # For small datasets this is fine; for large datasets consider BKTree with proper setup
        similar_ids = []
        query_hash = imagehash.hex_to_hash(phash)
        
        for stored_phash, image_id in self._hash_cache.items():
            stored_hash = imagehash.hex_to_hash(stored_phash)
            distance = query_hash - stored_hash
            if distance <= threshold:
                similar_ids.append(image_id)
        
        if not similar_ids:
            return []
            
        return await Image.filter(id__in=similar_ids)

    async def add_image(
        self,
        phash: str,
        dhash: str,
        source_url: str,
        source_platform: str,
        guild_id: int,
        thread_id: int,
        message_id: int,
    ) -> Image:
        """Store a new image hash and add to cache."""
        image = await Image.create(
            phash=phash,
            dhash=dhash,
            source_url=source_url,
            source_platform=source_platform,
            guild_id=guild_id,
            thread_id=thread_id,
            message_id=message_id,
        )
        
        # Add to cache for future lookups
        if self._hash_cache is not None:
            self._hash_cache[phash] = image.id
        
        return image

    async def close(self):
        await Tortoise.close_connections()
