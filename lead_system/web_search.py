"""Free, zero-dependency web search & digital presence enricher for LeadOS.

Searches DuckDuckGo HTML (TR locale) for each business to discover:
1. Hidden official websites not listed on Google Maps.
2. Online ordering / delivery / ad / social platforms (Yemeksepeti, GetirYemek,
   Trendyol Yemek, Migros Yemek, Uber Eats, TripAdvisor, Instagram, Facebook, etc.).
"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from urllib.request import Request, urlopen

from .store import is_directory_url, is_social_url


PLATFORM_PATTERNS: list[tuple[str, str, tuple[str, ...]]] = [
    ("Yemeksepeti", "delivery", ("yemeksepeti.com",)),
    ("GetirYemek", "delivery", ("getir.com", "getiryemek.com")),
    ("Trendyol Yemek", "delivery", ("trendyol.com", "tgoyemek.com")),
    ("Migros Yemek", "delivery", ("migros.com.tr",)),
    ("Uber Eats", "delivery", ("ubereats.com",)),
    ("TıklaGelsin", "delivery", ("tiklagelsin.com",)),
    ("Fuudy", "delivery", ("fuudy.co",)),
    ("Instagram", "social", ("instagram.com",)),
    ("Facebook", "social", ("facebook.com", "fb.com")),
    ("TikTok", "social", ("tiktok.com",)),
    ("YouTube", "social", ("youtube.com", "youtu.be")),
    ("X / Twitter", "social", ("x.com", "twitter.com")),
    ("LinkedIn", "social", ("linkedin.com",)),
    ("TripAdvisor", "directory", ("tripadvisor.com", "tripadvisor.com.tr")),
    ("Foursquare", "directory", ("foursquare.com",)),
    ("Yandex Maps", "directory", ("yandex.com.tr", "yandex.com")),
    ("Zomato", "directory", ("zomato.com",)),
]

SEARCH_EXCLUDED_HOSTS = {
    "google.com", "google.com.tr", "maps.google.com", "duckduckgo.com",
    "facebook.com", "fb.com", "instagram.com", "tiktok.com", "youtube.com",
    "youtu.be", "linkedin.com", "x.com", "twitter.com",
    "yemeksepeti.com", "getir.com", "getiryemek.com", "trendyol.com",
    "tgoyemek.com", "migros.com.tr", "ubereats.com", "tiklagelsin.com", "fuudy.co",
    "firmasec.com", "foursquare.com", "tripadvisor.com", "tripadvisor.com.tr",
    "yelp.com", "buldum.com", "find.com.tr", "iyifirma.com", "yandex.com.tr",
    "yandex.com", "zomato.com", "sikayetvar.com", "eksisozluk.com",
    "sahibinden.com", "armut.com", "wikipedia.org", "tr.wikipedia.org",
    "biletimgo.com", "revieweuro.com", "restaurantguru.com", "sluurpy.com",
    "menulux.com", "qr-menu.com", "linktr.ee", "hepsiburada.com", "n11.com",
    "samsunetkinlik.com", "samsunanakent.com", "neredekal.com", "otelz.com",
    "booking.com", "hotels.com", "airbnb.com", "enuygun.com",
}

GENERIC_BUSINESS_WORDS = {
    "cafe", "kafe", "restaurant", "restoran", "lokanta", "patisserie",
    "pastanesi", "market", "otel", "hotel", "kuafor", "kuaför", "giyim",
    "mobilya", "coffee", "kahve", "burger", "burgerci", "kebap", "kebab",
    "pide", "lahmacun", "doner", "döner", "istanbul", "ankara", "izmir",
    "samsun", "antalya", "bursa", "turkiye", "türkiye", "turkey", "home",
    "house", "kitchen", "mutfak", "bistro", "grill", "bar", "pub", "shop",
    "store", "salon", "beauty", "hair", "studio",
}


def _norm_words(value: Any) -> list[str]:
    return re.findall(r"[a-zA-ZçÇğĞıİöÖşŞüÜ0-9]{3,}", str(value or "").lower())


def _host_of(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return (parsed.hostname or "").lower().removeprefix("www.")


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def _is_excluded_host(host: str) -> bool:
    return not host or any(_host_matches(host, blocked) for blocked in SEARCH_EXCLUDED_HOSTS)


def _match_official_website(business_name: str, url: str, title: str, snippet: str) -> bool:
    host = _host_of(url)
    if _is_excluded_host(host) or is_social_url(url) or is_directory_url(url):
        return False
    name_words = [w for w in _norm_words(business_name) if w not in GENERIC_BUSINESS_WORDS]
    if not name_words:
        name_words = _norm_words(business_name)
    if not name_words:
        return False
    host_tokens = set(_norm_words(host.replace(".", " ").replace("-", " ")))
    compact_host = re.sub(r"[^a-z0-9]", "", host.split(".")[0].lower())
    compact_name = re.sub(r"[^a-z0-9]", "", business_name.lower())
    if len(compact_name) >= 5 and compact_name in compact_host:
        return True
    haystack = host_tokens | set(_norm_words(f"{title} {snippet}"))
    matches = [w for w in name_words if w in haystack]
    host_matches = [w for w in name_words if w in host_tokens or (len(w) >= 4 and w in compact_host)]
    return bool(host_matches) and (len(matches) >= 2 or any(len(w) >= 5 for w in host_matches))


def _ddg_html_search(query: str, timeout: int = 12) -> list[dict[str, str]]:
    """Query DuckDuckGo HTML endpoint with Turkish locale (no API key needed)."""
    url = "https://html.duckduckgo.com/html/?" + urlencode({"q": query, "kl": "tr-tr"})
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.5",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        html = resp.read(500_000).decode("utf-8", errors="replace")

    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    # Extract result links and surrounding title/snippet blocks
    blocks = re.split(r'<div[^>]+class="[^"]*result[^"]*"', html)
    for block in blocks[1:20]:
        href_match = re.search(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, flags=re.I | re.S)
        if not href_match:
            continue
        raw_href, raw_title = href_match.group(1), href_match.group(2)
        if "uddg=" in raw_href:
            parsed_q = parse_qs(urlparse(raw_href).query)
            target_url = unquote(parsed_q.get("uddg", [""])[0])
        elif raw_href.startswith(("http://", "https://")):
            target_url = raw_href
        else:
            continue
        if not target_url.startswith(("http://", "https://")) or target_url in seen_urls:
            continue
        seen_urls.add(target_url)
        snippet_match = re.search(r'class="result__snippet"[^>]*>(.*?)</(?:a|div)>', block, flags=re.I | re.S)
        title = re.sub(r"<[^>]+>", " ", raw_title)
        title = " ".join(title.split())[:200]
        snippet = re.sub(r"<[^>]+>", " ", snippet_match.group(1)) if snippet_match else ""
        snippet = " ".join(snippet.split())[:300]
        results.append({"url": target_url, "title": title, "snippet": snippet})
        if len(results) >= 12:
            break
    return results


def search_business_presence(
    business_name: str,
    location_hint: str = "",
    timeout: int = 12,
) -> dict[str, Any]:
    """Search the web for a business to find hidden websites & delivery/ad platforms."""
    clean_name = " ".join(str(business_name or "").split()).strip()
    clean_loc = " ".join(str(location_hint or "").split()).strip()
    if not clean_name:
        return {
            "search_query": "",
            "discovered_website": "",
            "online_platforms": [],
            "delivery_platforms": [],
            "social_platforms": [],
            "platform_links": {},
            "results_count": 0,
        }

    query = f'"{clean_name}" {clean_loc}'.strip() if clean_loc else f'"{clean_name}" Türkiye'
    results: list[dict[str, str]] = []
    for attempt in range(2):
        try:
            results = _ddg_html_search(query, timeout=timeout)
            if results:
                break
        except (HTTPError, URLError, TimeoutError, OSError):
            if attempt == 0:
                time.sleep(0.8)

    # Fallback without quotes if quoted search returned nothing
    if not results and clean_loc:
        try:
            results = _ddg_html_search(f"{clean_name} {clean_loc}", timeout=timeout)
        except (HTTPError, URLError, TimeoutError, OSError):
            results = []

    discovered_website = ""
    discovered_instagram = ""
    online_platforms: list[str] = []
    delivery_platforms: list[str] = []
    social_platforms: list[str] = []
    platform_links: dict[str, str] = {}

    for item in results:
        url = item["url"]
        title = item["title"]
        snippet = item["snippet"]
        host = _host_of(url)

        matched_platform = False
        for label, kind, domains in PLATFORM_PATTERNS:
            if any(_host_matches(host, d) for d in domains):
                matched_platform = True
                if label not in online_platforms:
                    online_platforms.append(label)
                    platform_links[label] = url
                if kind == "delivery" and label not in delivery_platforms:
                    delivery_platforms.append(label)
                elif kind == "social" and label not in social_platforms:
                    social_platforms.append(label)
                if label == "Instagram" and not discovered_instagram:
                    discovered_instagram = url
                break

        if not matched_platform and not discovered_website:
            if _match_official_website(clean_name, url, title, snippet):
                discovered_website = url

    return {
        "search_query": query,
        "discovered_website": discovered_website,
        "discovered_instagram": discovered_instagram,
        "online_platforms": online_platforms,
        "delivery_platforms": delivery_platforms,
        "social_platforms": social_platforms,
        "platform_links": platform_links,
        "results_count": len(results),
    }
