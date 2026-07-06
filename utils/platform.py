from urllib.parse import urlparse


def detect_platform(link: str) -> str:
    host = urlparse(link).netloc.lower().removeprefix("www.").removeprefix("mobile.")
    if host in ("twitter.com", "x.com"):
        return "twitter"
    if "pixiv.net" in link:
        return "pixiv"
    if "bsky.app" in link:
        return "bluesky"
    return "unknown"
