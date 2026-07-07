"""Core art-posting pipeline, shared by the Discord commands (cogs/post.py)
and the userscript HTTP API (web/api.py).

Every function takes the bot instance explicitly instead of a commands.Context
so the pipeline can run outside a Discord command invocation.
"""
from __future__ import annotations

import datetime
import io
import json
import re

import discord
from discord.ext import commands
from base64 import b64encode

import exception
from utils import bluesky_get, compute_hashes, detect_platform, imagehash, pixiv_ajax_get


def error_description(error: Exception) -> tuple[str, str | None]:
    """Return (user-facing description, optional python-error-string) for an error."""
    if isinstance(error, commands.MissingRequiredArgument):
        return (
            "Command format is incorrect! Please format the command as `/post gacha {series} {safety_level} {chara1,chara2} {link}`",
            str(error),
        )
    if isinstance(error, commands.BadArgument):
        return ("Incorrect argument! Check if the {series} and {safety_level} are correct.", str(error))
    if isinstance(error, exception.InvalidLink):
        return (
            "Invalid link! Please check {link} argument\nSupported Sites:\n"
            "- Pixiv (<https://www.pixiv.net>)\n- Bluesky (<https://bsky.app>)",
            None,
        )
    if isinstance(error, exception.ForumNotFound):
        return ("Could not find correct forum channel! Check that {series} and {safety_level} is correct.", None)
    if isinstance(error, exception.AccessDenied):
        return ("You do not have access to the channel you are trying to post to!", None)
    if isinstance(error, exception.ThreadsNotFound):
        return (
            "Could not find all character threads!\nMissing threads:\n"
            + str(error).lstrip("Command raised an exception: str: "),
            None,
        )
    if isinstance(error, exception.NotPoster):
        return ("You aren't allowed to post art!", None)
    if isinstance(error, exception.RequestFailed):
        return ("The bot has failed to contact an external server. Please try again or ping Maren about this issue.", None)
    if isinstance(error, exception.AIImageFound):
        return ("The artist has labeled that this image has been AI assisted. As such, it cannot be added to this server.", None)
    if isinstance(error, exception.CharacterDetectFail):
        return ("The automatic character detector has failed. Please use resubmit the link with the character list.", None)
    if isinstance(error, exception.DuplicateImageFound):
        return (
            "This image has already been posted to this server!\n"
            + str(error).lstrip("Command raised an exception: str: "),
            None,
        )
    return ("Unknown error occurred while using the command", str(error))


def error_payload(error: Exception) -> tuple[int, str, str]:
    """Map a pipeline exception to (http_status, code, message) for the API."""
    message, _ = error_description(error)
    if isinstance(error, exception.InvalidLink):
        return 400, "invalid_link", message
    if isinstance(error, exception.ForumNotFound):
        return 400, "forum_not_found", message
    if isinstance(error, exception.ThreadsNotFound):
        return 409, "threads_not_found", message
    if isinstance(error, exception.DuplicateImageFound):
        return 409, "duplicate", message
    if isinstance(error, exception.AIImageFound):
        return 422, "ai_image", message
    if isinstance(error, exception.CharacterDetectFail):
        return 422, "detection_failed", message
    if isinstance(error, exception.NotPoster):
        return 403, "not_poster", message
    if isinstance(error, exception.AccessDenied):
        return 403, "access_denied", message
    if isinstance(error, exception.RequestFailed):
        return 502, "upstream_failed", message
    return 500, "internal_error", message


async def tags_model_pass(bot, hq_image: io.BytesIO, image_name: str, on_status=None) -> tuple[set, str, str]:
    """
    Run ML model on image to detect characters, series, and safety rating.

    Args:
        bot: the ArtBot instance
        hq_image: BytesIO of the high-quality image
        image_name: Filename to determine image format
        on_status: optional async callable(text) for progress updates

    Returns:
        tuple: (characters_set, series_str, safety_str)
    """
    # Reset stream position and read image bytes
    hq_image.seek(0)
    image = hq_image.read()
    hq_image.seek(0)  # Reset for later use

    # Determine format from filename
    if ".png" in image_name.lower():
        mime = "image/png"
    elif ".webp" in image_name.lower():
        mime = "image/webp"
    elif ".gif" in image_name.lower():
        mime = "image/gif"
    else:
        mime = "image/jpeg"

    gradioIn = f"data:{mime};base64,{b64encode(image).decode('utf-8')}"

    image_input = {
        "url": gradioIn,
        "is_stream": False
    }

    if on_status:
        await on_status("🤖 Running character & series detection model...")

    result = await bot.tagger.predict(image_input)

    charas = set()
    for chara in result.characters:
        if chara in bot.config.char_map:
            charas.add(bot.config.char_map[chara])

    series = ""
    for series_can in result.copyrights:
        if series_can in bot.config.series_map:
            series = bot.config.series_map[series_can]
            break

    safety = ""
    if result.rating is not None:
        safety = bot.config.safety_map.get(result.rating, "")

    return charas, series, safety


def tags_pixiv_pass(config, ajax_resp: dict) -> tuple[set, str]:
    chara_tags = set()
    series = ""
    for tag_dict in ajax_resp['body']['tags']['tags']:
        tag = tag_dict['tag']
        if tag in config.char_map:
            chara_tags.add(config.char_map[tag])
        elif tag in config.series_map:
            series = config.series_map[tag]

    return chara_tags, series


def _normalize_text(text: str) -> str:
    return re.sub(r"[_\s]+", " ", text.lower())


def tags_text_pass(config, text: str) -> tuple[set, str]:
    """
    Scan free text (e.g. a tweet body with hashtags) for known character and
    series tags — the twitter analog of tags_pixiv_pass.

    Underscores and whitespace are treated as equivalent so "ushio_noa",
    "ushio noa" and "#ushio_noa" all match the same char_map key. Keys only
    match on word boundaries to avoid short-tag false positives.
    """
    charas = set()
    series = ""
    if not text:
        return charas, series

    norm = _normalize_text(text)

    def key_in_text(tag: str) -> bool:
        key = _normalize_text(tag)
        if not key or key not in norm:
            return False
        return re.search(rf"(?<!\w){re.escape(key)}(?!\w)", norm) is not None

    for tag, name in config.char_map.items():
        if key_in_text(tag):
            charas.add(name)

    for tag, name in config.series_map.items():
        if key_in_text(tag):
            series = name
            break

    return charas, series


def find_forum_by_name(guild: discord.Guild, series: str, safety: str) -> discord.ForumChannel | None:
    """Find the forum channel named {series}-{safety}, or None."""
    if not series or not safety:
        return None
    for channel in guild.channels:
        if channel.name == f"{series}-{safety}":
            return channel
    return None


async def check_duplicate(bot, image: io.BytesIO, guild_id: int) -> tuple[dict, list]:
    """
    Check if image is a duplicate and return hashes.
    Returns (hashes_dict, list_of_similar_images).
    """
    # Reset stream position for reading
    image.seek(0)
    hashes = compute_hashes(image)
    image.seek(0)  # Reset for later use

    # Convert ImageHash objects to hex strings for storage/comparison
    hash_strings = {
        "phash": str(hashes["phash"]),
        "dhash": str(hashes["dhash"]),
    }

    # Find similar images in database
    similar = await bot.db.find_similar(hash_strings["phash"])

    # Filter to same guild and check if truly similar using phash + dhash
    duplicates = []
    for img in similar:
        if img.guild_id == guild_id:
            # Double-check with dhash for accuracy
            stored_phash = imagehash.hex_to_hash(img.phash)
            stored_dhash = imagehash.hex_to_hash(img.dhash)

            phash_similar = (hashes["phash"] - stored_phash) <= 8
            dhash_similar = (hashes["dhash"] - stored_dhash) <= 10

            if phash_similar and dhash_similar:
                duplicates.append(img)

    return hash_strings, duplicates


def _max_upload_size(guild: discord.Guild) -> int:
    return 52428799 if guild.premium_tier > 1 else 10485759


async def validate_uploaded_image(bot, image_bytes: bytes, image_name: str, guild: discord.Guild) -> tuple[io.BytesIO, dict, bool]:
    """
    Validate an image uploaded directly (userscript twitter path): duplicate
    check + upload-size fallback determination.

    Returns:
        tuple: (hq_image, hashes, embed_fallback)

    Raises:
        DuplicateImageFound: If image was already posted to this guild
    """
    hq_image = io.BytesIO(image_bytes)
    hashes, duplicates = await check_duplicate(bot, hq_image, guild.id)
    if duplicates:
        dup = duplicates[0]
        raise exception.DuplicateImageFound(
            f"Post: https://discord.com/channels/{dup.guild_id}/{dup.thread_id}/{dup.message_id}"
        )

    embed_fallback = hq_image.getbuffer().nbytes > _max_upload_size(guild)
    return hq_image, hashes, embed_fallback


async def fetch_and_validate_image(bot, link: str, guild: discord.Guild, image_num: int | None = None, on_status=None) -> tuple[dict, io.BytesIO, str, dict, bool, str]:
    """
    Validate link, fetch image from supported platform, check for duplicates, and determine fallback mode.

    Returns:
        tuple: (post_data, hq_image, image_name, hashes, embed_fallback, platform)

    Raises:
        InvalidLink: If link is not from a supported platform
        DuplicateImageFound: If image was already posted to this guild
    """
    platform = detect_platform(link)
    embed_fallback = False

    if platform == "pixiv":
        post_data, hq_image, image_name = await pixiv_ajax_get(bot, link, image_num, on_status=on_status)
    elif platform == "bluesky":
        post_data, hq_image, image_name = await bluesky_get(
            bot,
            link,
            image_num,
            on_status=on_status,
        )
    else:
        raise exception.InvalidLink("Invalid Link! Supported platforms: Pixiv, Bluesky")

    # Check for duplicates before proceeding
    if on_status:
        await on_status("🔍 Hashing image & checking for duplicates...")
    hashes, duplicates = await check_duplicate(bot, hq_image, guild.id)
    if duplicates:
        dup = duplicates[0]
        raise exception.DuplicateImageFound(
            f"Post: https://discord.com/channels/{dup.guild_id}/{dup.thread_id}/{dup.message_id}"
        )

    # Determine if we need embed fallback based on server boost level
    if hq_image.getbuffer().nbytes > _max_upload_size(guild):
        embed_fallback = True

    return post_data, hq_image, image_name, hashes, embed_fallback, platform


async def find_character_threads(forum_channel: discord.ForumChannel, characters: str, on_status=None) -> tuple[list, list, list]:
    """
    Find all character threads, group threads, and "All Characters" thread in forum.

    Args:
        forum_channel: The forum channel to search
        characters: Comma-separated character names

    Returns:
        tuple: (threads, thread_names, group_names)

    Raises:
        ThreadsNotFound: If any required threads are missing
    """
    charas = characters.lower().replace("_", " ").split(",")
    charas = [chara.strip() for chara in charas]

    threads = []
    thread_names = []
    group_names = []

    # Helper to process a thread
    def process_thread(thread):
        if thread.name == "All Characters" and "All Characters" not in thread_names:
            threads.append(thread)
            thread_names.append("All Characters")

        if thread.name.lower() in charas and thread.name.lower() not in thread_names:
            threads.append(thread)
            thread_names.append(thread.name.lower())
            if (len(thread.applied_tags) != 0 and
                thread.applied_tags[0].name != "Indie" and
                thread.applied_tags[0].name.lower() + " (group)" not in group_names):
                group_names.append(thread.applied_tags[0].name.lower() + " (group)")

    if on_status:
        await on_status(f"🔎 Searching {forum_channel.name} for character threads...")

    # Search active threads
    for thread in forum_channel.threads:
        process_thread(thread)
        if len(threads) == len(charas) + 1:
            break

    # Search archived threads if needed
    if len(threads) != len(charas) + 1:
        if on_status:
            await on_status(f"📂 Searching archived threads in {forum_channel.name}...")
        async for thread in forum_channel.archived_threads():
            process_thread(thread)
            if len(threads) == len(charas) + 1:
                break

    # Find group threads
    if group_names:
        for group_name in group_names:
            for thread in forum_channel.threads:
                if group_name == thread.name.lower() and thread.name.lower() not in thread_names:
                    threads.append(thread)
                    thread_names.append(thread.name.lower())
                    break
            if group_name not in thread_names:
                async for thread in forum_channel.archived_threads():
                    if group_name == thread.name.lower() and thread.name.lower() not in thread_names:
                        threads.append(thread)
                        thread_names.append(thread.name.lower())
                        break

    # Check for missing threads
    if len(threads) != len(charas) + len(group_names) + 1:
        missing = []
        if "All Characters" not in thread_names:
            missing.append("All Characters")
        for chara_name in charas:
            if chara_name not in thread_names:
                missing.append(chara_name)
        for group_name in group_names:
            if group_name not in thread_names:
                missing.append(group_name)
        raise exception.ThreadsNotFound("\n".join(f"- {name}" for name in missing))

    return threads, thread_names, group_names


async def store_image_hash(bot, hashes: dict, link: str, platform: str, guild_id: int, thread_id: int, message_id: int):
    """Store image hashes in database for duplicate detection. Returns the created Image."""
    return await bot.db.add_image(
        phash=hashes["phash"],
        dhash=hashes["dhash"],
        source_url=link,
        source_platform=platform,
        guild_id=guild_id,
        thread_id=thread_id,
        message_id=message_id,
    )


async def send_webhook(bot, embed, post: discord.Message, channel_name: str, link: str):
    if channel_name in bot.config.webhooks:
        embed.set_image(url=post.embeds[0].image.url)
        for webhook_url in bot.config.webhooks[channel_name]:
            await bot.client.post(webhook_url, data={"payload_json": json.dumps({"content": f"<{link}>", "embeds": [embed.to_dict()]})})


async def create_embed_and_send(bot, link: str, post_data: dict, threads: list, poster_name: str, guild_id: int, channel_name: str, embed_fallback: bool, hq_image: bytes, image_name: str, hashes: dict, image_num: int | None = None, platform: str = "pixiv", on_status=None) -> tuple[str, int | None]:
    msg = ""

    # Build embed based on platform
    if platform == "pixiv":
        embed_title = post_data['body']["title"]
        embed_url = post_data['body']["extraData"]["meta"]["canonical"]
        embed_author_name = "@" + post_data['body']['userName']
        embed_author_url = "https://www.pixiv.net/users/" + post_data['body']["userId"]
        fallback_link = link.replace("pixiv", "phixiv")
    elif platform == "bluesky":
        embed_title = post_data.get("title", "Bluesky Post")
        embed_url = post_data.get("url", link)
        embed_author_name = "@" + post_data.get("author_handle", "unknown")
        embed_author_url = post_data.get("author_url", link)
        fallback_link = link  # No phixiv equivalent for Bluesky
    elif platform == "twitter":
        # Tweet text length is unpredictable, so it is never used as the title
        # (it only feeds tags_text_pass for detection).
        embed_title = "Twitter Post"
        embed_url = post_data.get("url", link)
        embed_author_name = "@" + post_data.get("author_handle", "unknown")
        embed_author_url = f"https://x.com/{post_data.get('author_handle', '')}"
        fallback_link = embed_url.replace("//x.com", "//fxtwitter.com").replace("//twitter.com", "//fxtwitter.com")
    else:
        embed_title = "Art Post"
        embed_url = link
        embed_author_name = "Unknown"
        embed_author_url = link
        fallback_link = link

    if not embed_fallback:
        embed = discord.Embed(
        title=embed_title,
        url=embed_url,
        color=discord.Color.purple(),
        timestamp=datetime.datetime.now()
        )
        embed.set_author(name=embed_author_name, url=embed_author_url)
        embed.add_field(name="Original Poster", value=poster_name, inline=False)
        embed.set_image(url="attachment://"+image_name)
        embed.set_footer(text="Maren's Art Bot Services")
    else:
        if image_num and platform == "pixiv":
            embed = "Poster: "+ poster_name + "\n" + fallback_link + "/" + str(image_num)
        else:
            embed = "Poster: "+ poster_name + "\n" + fallback_link

    first_post = None
    total = len(threads)
    for idx, thread in enumerate(threads, start=1):
        if on_status:
            await on_status(f"📤 Posting to thread {idx} of {total}: #{thread.name}")
        if not embed_fallback:
            post = await thread.send(content=f"<{link}>",embed=embed, file=discord.File(io.BytesIO(hq_image),filename=image_name))
        else:
            post = await thread.send(content=embed)

        # Store first post for hash tracking
        if first_post is None:
            first_post = post

        if thread == threads[len(threads)-1]:
            msg += "- " + post.jump_url
        else:
            msg += "- " + post.jump_url + "\n"

    # Store image hash in database after successful posting
    post_id = None
    if first_post is not None:
        if on_status:
            await on_status("💾 Recording post in database...")
        image = await store_image_hash(
            bot,
            hashes=hashes,
            link=link,
            platform=platform,
            guild_id=guild_id,
            thread_id=first_post.channel.id,
            message_id=first_post.id,
        )
        post_id = image.id

    await send_webhook(bot, embed, post, channel_name, link)

    if embed_fallback:
        if platform == "pixiv":
            msg += "\n**NOTE:** Older embed system (Phixiv) has been used due to the image being too big to upload directly."
        else:
            msg += "\n**NOTE:** Image was too large to upload directly. Linked version shown instead."
    return msg, post_id
