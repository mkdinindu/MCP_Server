"""
Smart MCP Server
----------------
Tools:
  - search_web            : General web search with ranked, cleaned results
  - search_news           : Latest news with recency scoring
  - find_youtube_video    : Fuzzy/semantic YouTube finder from loose descriptions
  - get_distance          : Distance + travel time between two locations (no API key needed)
  - get_lyrics            : Fetch and return full song lyrics by title/artist
  - play_youtube_video    : Open a YouTube URL in the local browser
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
import json
import math
from difflib import SequenceMatcher
from typing import Optional

from mcp.server.fastmcp import FastMCP
from ddgs import DDGS

mcp = FastMCP("Smart MCP Server")


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _similarity(a: str, b: str) -> float:
    """Return a 0-1 similarity ratio between two strings (case-insensitive)."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _clean_text(text: str, max_len: int = 300) -> str:
    """Strip excess whitespace and truncate."""
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len] + "…" if len(text) > max_len else text


def _fetch_url(url: str, timeout: int = 10) -> str:
    """Fetch a URL and return the decoded body, or raise on error."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ─────────────────────────────────────────────
# 1. General web search
# ─────────────────────────────────────────────

@mcp.tool()
def search_web(query: str, max_results: int = 6) -> str:
    """
    Search the internet for current information.
    Returns ranked, de-duplicated results with title, URL, and a clean snippet.
    Use automatically for real-time data, prices, documentation, or anything uncertain.
    """
    try:
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results + 4))

        if not raw:
            return "No results found."

        # Deduplicate by domain
        seen_domains: set[str] = set()
        unique = []
        for r in raw:
            domain = urllib.parse.urlparse(r["href"]).netloc
            if domain not in seen_domains:
                seen_domains.add(domain)
                unique.append(r)
            if len(unique) >= max_results:
                break

        lines = []
        for i, r in enumerate(unique, 1):
            snippet = _clean_text(r.get("body", ""))
            lines.append(f"[{i}] {r['title']}\n    URL : {r['href']}\n    Info: {snippet}")

        return "\n\n".join(lines)
    except Exception as exc:
        return f"Search failed: {exc}"


# ─────────────────────────────────────────────
# 2. News search
# ─────────────────────────────────────────────

@mcp.tool()
def search_news(query: str, max_results: int = 5) -> str:
    """
    Search for the latest news articles on a topic.
    Results are sorted most-recent first.
    Use for any news or current-events questions.
    """
    try:
        with DDGS() as ddgs:
            raw = list(ddgs.news(query, max_results=max_results + 3))

        if not raw:
            return "No news found."

        # Sort by date descending (ISO strings sort lexicographically)
        raw.sort(key=lambda r: r.get("date", ""), reverse=True)

        lines = []
        for i, r in enumerate(raw[:max_results], 1):
            body = _clean_text(r.get("body", ""))
            lines.append(
                f"[{i}] {r['title']}\n"
                f"    Source : {r.get('source', 'Unknown')}  |  Date: {r.get('date', 'Unknown')}\n"
                f"    URL    : {r.get('url', '')}\n"
                f"    Summary: {body}"
            )

        return "\n\n".join(lines)
    except Exception as exc:
        return f"News search failed: {exc}"


# ─────────────────────────────────────────────
# 3. YouTube video finder (uses DuckDuckGo web search)
# ─────────────────────────────────────────────

_YOUTUBE_WATCH_RE = re.compile(r"youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})")
_YOUTUBE_SHORT_RE = re.compile(r"youtu\.be/([a-zA-Z0-9_-]{11})")


def _youtube_search(description: str, max_results: int) -> list[dict[str, str]]:
    """
    Core YouTube search using ddgs.text() with site:youtube.com queries.
    Returns a list of dicts with keys: title, url, channel, snippet.
    """
    base = description.strip()
    queries = [
        f'site:youtube.com "{base}"',
        f"site:youtube.com {base}",
        f"youtube {base}",
    ]

    seen_ids: set[str] = set()
    results: list[dict[str, str]] = []

    with DDGS() as ddgs:
        for q in queries:
            try:
                page = list(ddgs.text(q, max_results=10))
            except Exception:
                continue

            for r in page:
                href = r.get("href", "")
                vid = None
                m = _YOUTUBE_WATCH_RE.search(href)
                if m:
                    vid = m.group(1)
                else:
                    m = _YOUTUBE_SHORT_RE.search(href)
                    if m:
                        vid = m.group(1)

                if not vid or vid in seen_ids:
                    continue
                seen_ids.add(vid)

                title = r.get("title", "No title")
                snippet = r.get("body", "")
                results.append({
                    "title": title,
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "channel": "",
                    "snippet": _clean_text(snippet, 200),
                })

                if len(results) >= max_results:
                    return results

            if len(results) >= max_results:
                break

    return results


@mcp.tool()
def search_youtube(description: str, max_results: int = 5) -> str:
    """
    Search for YouTube videos matching a description, title, or topic.
    Use this for any request to find, search, or play YouTube videos.

    Examples:
      description="despacito", description="never gonna give you up",
      description="vsauce mind field episode 1", description="pasta recipe

    Returns ranked results with title, URL, and channel.
    After finding the right video, use play_youtube_video to open it in the browser.
    """
    try:
        results = _youtube_search(description, max_results)
        if not results:
            return (
                f"No YouTube videos found for \"{description}\". "
                "Try a different description or check your spelling."
            )

        # Score by title similarity to description
        desc_lower = description.lower()
        desc_keywords = set(re.findall(r"\w+", desc_lower))

        def score(item: dict) -> float:
            title_lower = item["title"].lower()
            sim = _similarity(desc_lower, title_lower)
            title_words = set(re.findall(r"\w+", title_lower))
            overlap = len(desc_keywords & title_words) / max(len(desc_keywords), 1)
            return sim * 0.5 + overlap * 0.5

        results.sort(key=score, reverse=True)

        lines = []
        for i, r in enumerate(results[:max_results], 1):
            lines.append(
                f"[{i}] {r['title']}\n"
                f"    URL : {r['url']}\n"
                f"    Info: {r['snippet']}"
            )

        return "\n\n".join(lines)

    except Exception as exc:
        return f"YouTube search failed: {exc}"


@mcp.tool()
def find_youtube_video(description: str, max_results: int = 5) -> str:
    """
    [Alias for search_youtube] Find a YouTube video from a partial or fuzzy description.
    """
    return search_youtube(description, max_results)


# ─────────────────────────────────────────────
# 4. Distance between two locations
# ─────────────────────────────────────────────

def _nominatim_geocode(place: str) -> Optional[tuple[float, float]]:
    """Return (lat, lon) for a place name using Nominatim (OpenStreetMap). No API key needed."""
    url = (
        "https://nominatim.openstreetmap.org/search?"
        + urllib.parse.urlencode({"q": place, "format": "json", "limit": 1})
    )
    try:
        body = _fetch_url(url)
        data = json.loads(body)
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        pass
    return None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@mcp.tool()
def get_distance(origin: str, destination: str) -> str:
    """
    Calculate the straight-line (great-circle) distance between two locations
    and estimate travel times for driving, flying, and walking.

    Works with city names, addresses, landmarks, or coordinates like "48.8566,2.3522".
    Examples:
      origin="London", destination="Paris"
      origin="Eiffel Tower", destination="Big Ben"
      origin="New York, USA", destination="Los Angeles, USA"
    """

    def parse_or_geocode(place: str) -> Optional[tuple[float, float]]:
        # Try raw "lat,lon" first
        coord_match = re.match(r"^\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*$", place)
        if coord_match:
            return float(coord_match.group(1)), float(coord_match.group(2))
        return _nominatim_geocode(place)

    try:
        loc1 = parse_or_geocode(origin)
        if loc1 is None:
            return f'Could not find location: "{origin}". Try being more specific (e.g. "Paris, France").'

        loc2 = parse_or_geocode(destination)
        if loc2 is None:
            return f'Could not find location: "{destination}". Try being more specific.'

        km = _haversine_km(*loc1, *loc2)
        miles = km * 0.621371

        # Rough travel time estimates
        drive_h = km / 90          # ~90 km/h average road speed
        fly_h   = km / 800 + 1.5  # ~800 km/h + 1.5 h airport overhead
        walk_h  = km / 5           # ~5 km/h walking

        def fmt_time(hours: float) -> str:
            h = int(hours)
            m = round((hours - h) * 60)
            if h == 0:
                return f"{m} min"
            return f"{h}h {m}m" if m else f"{h}h"

        lines = [
            f"📍 From : {origin}  ({loc1[0]:.4f}, {loc1[1]:.4f})",
            f"📍 To   : {destination}  ({loc2[0]:.4f}, {loc2[1]:.4f})",
            "",
            f"📏 Straight-line distance : {km:,.1f} km  ({miles:,.1f} miles)",
            "",
            "⏱  Estimated travel times (straight-line basis):",
            f"   🚗 Driving (~90 km/h avg) : {fmt_time(drive_h)}",
            f"   ✈️  Flying  (~800 km/h)    : {fmt_time(fly_h)}  (incl. ~1.5 h airport overhead)",
            f"   🚶 Walking (~5 km/h)      : {fmt_time(walk_h)}",
            "",
            "Note: Actual road/rail distances and times may differ significantly.",
        ]
        return "\n".join(lines)

    except Exception as exc:
        return f"Distance calculation failed: {exc}"


# ─────────────────────────────────────────────
# 5. Lyrics finder
# ─────────────────────────────────────────────

def _extract_lyrics_from_html(html: str) -> str:
    """
    Best-effort lyrics extractor. Tries multiple heuristics across
    Genius, AZLyrics, and Lyrics.com page structures.
    Returns cleaned plain-text lyrics, or empty string on failure.
    """

    # --- Genius: lyrics stored in JSON inside <script> tags ---
    genius_match = re.search(
        r'"lyrics":\{"html":"(.*?)"(?:,"dom"|\})',
        html,
        re.DOTALL,
    )
    if genius_match:
        raw = genius_match.group(1)
        raw = raw.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
        raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.IGNORECASE)
        raw = re.sub(r"<[^>]+>", "", raw)
        return raw.strip()

    # --- AZLyrics: <div> with no class between comment markers ---
    az_match = re.search(
        r"<!-- Usage of azlyrics.*?-->.*?<div[^>]*>(.*?)</div>",
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if az_match:
        raw = az_match.group(1)
        raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.IGNORECASE)
        raw = re.sub(r"<[^>]+>", "", raw)
        return raw.strip()

    # --- Generic heuristic: largest text block inside <div> that looks like lyrics ---
    divs = re.findall(r"<div[^>]*>([\s\S]{200,3000}?)</div>", html, re.IGNORECASE)
    best = ""
    for d in divs:
        # Strip tags
        text = re.sub(r"<br\s*/?>", "\n", d, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text).strip()
        # Heuristic: lyrics blocks have many short lines
        lines = [l for l in text.splitlines() if l.strip()]
        avg_len = sum(len(l) for l in lines) / max(len(lines), 1)
        if 10 <= avg_len <= 60 and len(lines) >= 10 and len(text) > len(best):
            best = text
    return best


@mcp.tool()
def get_lyrics(song_title: str, artist: Optional[str] = None) -> str:
    """
    Fetch and return the full lyrics for a song.
    Provide the song title and optionally the artist name for best accuracy.

    Examples:
      song_title="Bohemian Rhapsody", artist="Queen"
      song_title="Blinding Lights"
      song_title="that song that goes never gonna give you up"
    """
    try:
        query_parts = [song_title]
        if artist:
            query_parts.append(artist)
        query_parts.append("lyrics")
        query = " ".join(query_parts)

        # Preferred sources in priority order
        preferred_domains = ["azlyrics.com", "genius.com", "lyrics.com", "metrolyrics.com"]

        candidates: list[dict] = []
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=10))

        for domain in preferred_domains:
            for r in results:
                if domain in r.get("href", ""):
                    candidates.append(r)
            if candidates:
                break

        # Fallback: use whatever search returned
        if not candidates:
            candidates = results

        if not candidates:
            return f'No lyrics found for "{song_title}".'

        errors: list[str] = []
        for candidate in candidates[:4]:  # Try up to 4 URLs
            url = candidate["href"]
            try:
                html = _fetch_url(url, timeout=12)
                lyrics = _extract_lyrics_from_html(html)
                if lyrics and len(lyrics) > 100:
                    # Truncate extremely long lyrics gracefully
                    if len(lyrics) > 6000:
                        lyrics = lyrics[:6000] + "\n\n[… lyrics truncated for length …]"
                    header = f"🎵 {candidate.get('title', song_title)}\n"
                    header += f"   Source: {url}\n"
                    header += "─" * 60 + "\n"
                    return header + lyrics
            except Exception as exc:
                errors.append(f"{url}: {exc}")
                continue

        # Nothing parsed cleanly — return best snippet from search
        fallback = _clean_text(candidates[0].get("body", ""), 800)
        note = "\n\n⚠️  Could not load full lyrics page. Here is a search snippet:\n" + fallback
        if errors:
            note += "\n\nErrors encountered:\n" + "\n".join(errors[:3])
        return note

    except Exception as exc:
        return f"Lyrics search failed: {exc}"


# ─────────────────────────────────────────────
# 6. Open YouTube video in browser
# ─────────────────────────────────────────────

@mcp.tool()
def play_youtube_video(url: str) -> str:
    """
    Open a YouTube video URL in the user's local browser.
    Accepts standard youtube.com/watch?v=... or youtu.be/... links.
    """
    if "youtube.com/watch" not in url and "youtu.be/" not in url:
        return (
            "❌ That doesn't look like a valid YouTube URL.\n"
            "Expected format: https://www.youtube.com/watch?v=XXXX  or  https://youtu.be/XXXX"
        )
    return f"OPEN_BROWSER:{url}"


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")
