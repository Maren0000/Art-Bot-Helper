def detect_platform(link: str) -> str:
    if "pixiv.net" in link:
        return "pixiv"
    if "bsky.app" in link:
        return "bluesky"
    return "unknown"
