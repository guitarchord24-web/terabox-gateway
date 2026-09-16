from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import aiohttp


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

UPSTREAMS = [
    "https://www.terabox.com",
    "https://www.1024terabox.com",
    "https://www.1024tera.com",
]


def normalize_surl(value: str) -> str:
    value = value.strip()

    if "/s/" in value:
        value = value.split("/s/", 1)[1].split("?", 1)[0].split("#", 1)[0]

    if len(value) == 23 and value.startswith("1"):
        value = value[1:]

    return value


def extract_js_token(html: str) -> str | None:
    patterns = [
        r'window\.jsToken\s*=\s*["\']([^"\']+)["\']',
        r'window\.jsToken\s*%3D\s*["\']([^"\']+)["\']',
        r'window\.jsToken\s*%3D\s*(?:%22|")([^"%]+)(?:%22|")',
        r'fn(?:%28|\()(?:"|%22|%27|\')([^"%\')]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


async def resolve_direct(
    url: str,
    cookies: dict[str, str] | None = None,
) -> dict[str, Any]:

    surl = normalize_surl(url)

    if not re.fullmatch(r"[A-Za-z0-9_-]{6,50}", surl):
        raise ValueError("Invalid TeraBox short URL")

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.terabox.com/",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    timeout = aiohttp.ClientTimeout(
        total=15,
        connect=8,
        sock_read=10,
    )

    cookie_jar = aiohttp.CookieJar(unsafe=True)

    if cookies:
        cookie_jar.update_cookies(cookies)

    async with aiohttp.ClientSession(
        headers=headers,
        timeout=timeout,
        cookie_jar=cookie_jar,
    ) as session:

        last_error: str | None = None

        for base in UPSTREAMS:

            try:
                share_url = f"{base}/sharing/link?surl={surl}"

                async with session.get(
                    share_url,
                    allow_redirects=True,
                ) as response:

                    html = await response.text(
                        errors="ignore"
                    )

                    if response.status != 200:
                        last_error = (
                            f"{base}: HTTP {response.status}"
                        )
                        continue

                    if len(html) < 500:
                        last_error = (
                            f"{base}: truncated HTML "
                            f"({len(html)} bytes)"
                        )
                        continue

                    js_token = extract_js_token(html)

                    if not js_token:
                        last_error = (
                            f"{base}: jsToken not found"
                        )
                        continue

                    api_url = (
                        f"{base}/share/list"
                        f"?app_id=250528"
                        f"&jsToken={js_token}"
                        f"&shorturl={surl}"
                        f"&root=1"
                    )

                    api_headers = {
                        "User-Agent": USER_AGENT,
                        "Accept": (
                            "application/json, "
                            "text/plain, */*"
                        ),
                        "Referer": str(response.url),
                        "X-Requested-With": "XMLHttpRequest",
                    }

                    async with session.get(
                        api_url,
                        headers=api_headers,
                    ) as api_response:

                        data = await api_response.json(
                            content_type=None
                        )

                        if api_response.status != 200:
                            last_error = (
                                f"{base}: API HTTP "
                                f"{api_response.status}"
                            )
                            continue

                        if not isinstance(data, dict):
                            last_error = (
                                f"{base}: invalid API response"
                            )
                            continue

                        errno = data.get("errno")

                        if errno not in (0, "0", None):
                            last_error = (
                                f"{base}: TeraBox errno "
                                f"{errno}"
                            )
                            continue

                        return {
                            "ok": True,
                            "surl": surl,
                            "jsToken": js_token,
                            "list": data.get("list", []),
                            "raw": data,
                        }

            except Exception as exc:
                last_error = f"{base}: {exc}"

        raise RuntimeError(
            last_error or "All TeraBox upstreams failed"
                    )
