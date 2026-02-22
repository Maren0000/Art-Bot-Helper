import io
import re

import exception


def parse_bsky_url(link: str) -> tuple[str, str]:
    """
    Parse a Bluesky URL to extract handle and post rkey.
    URL format: https://bsky.app/profile/{handle}/post/{rkey}

    Returns: (handle, rkey)
    """
    match = re.match(r"https://bsky\.app/profile/([^/]+)/post/([^/?#]+)", link)
    if not match:
        raise exception.InvalidLink("Invalid Bluesky link format")
    return match.group(1), match.group(2)


async def bluesky_get(
    bot,
    link: str,
    image_num: int | None = None,
) -> tuple[dict, io.BytesIO, str]:
    """
    Fetch image from a Bluesky post using the official atproto SDK.

    Args:
        bot: The ArtBot instance with client and bsky_client attributes
        link: Bluesky post URL
        image_num: 1-indexed image number (default: 1)

    Returns:
        tuple: (post_data, image_bytes, image_filename)
    """
    if not bot.bsky_client:
        raise exception.RequestFailed(
            "Bluesky client not initialized. Set BLUESKY_IDENTIFIER and BLUESKY_APP_PASSWORD."
        )

    handle, rkey = parse_bsky_url(link)

    if handle.startswith("did:"):
        did = handle
    else:
        resolved = await bot.bsky_client.resolve_handle(handle)
        did = resolved.did

    uri = f"at://{did}/app.bsky.feed.post/{rkey}"
    response = await bot.bsky_client.get_posts([uri])

    if not response.posts:
        raise exception.RequestFailed("Bluesky post not found")

    post = response.posts[0]

    author_handle = post.author.handle
    author_display = post.author.display_name or author_handle

    images = []
    embed = post.embed

    if embed:
        if hasattr(embed, "images") and embed.images:
            images = embed.images
        elif hasattr(embed, "media") and embed.media:
            if hasattr(embed.media, "images") and embed.media.images:
                images = embed.media.images

    if not images:
        raise exception.RequestFailed("No images found in Bluesky post")

    idx = (image_num or 1) - 1
    if idx < 0 or idx >= len(images):
        raise exception.RequestFailed(f"Image {image_num} not found. Post has {len(images)} images.")

    image_data = images[idx]
    image_url = image_data.fullsize or image_data.thumb
    image_alt = image_data.alt or ""

    if not image_url:
        raise exception.RequestFailed("Could not get image URL from Bluesky post")

    img_resp = await bot.client.get(image_url)
    if img_resp.status != 200:
        raise exception.RequestFailed("Failed to download Bluesky image")

    image_bytes = await img_resp.read()

    ext = "jpg"
    if "png" in image_url.lower():
        ext = "png"
    elif "webp" in image_url.lower():
        ext = "webp"

    image_name = f"bsky_{rkey}_{idx + 1}.{ext}"

    post_data = {
        "title": image_alt or "Bluesky Post",
        "url": link,
        "author_handle": author_handle,
        "author_display": author_display,
        "author_url": f"https://bsky.app/profile/{author_handle}",
    }

    return post_data, io.BytesIO(image_bytes), image_name
