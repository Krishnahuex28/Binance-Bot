import asyncio
import aiohttp
import logging
import re
from datetime import datetime, timezone, timedelta
from config import config
from bs4 import BeautifulSoup
import cloudscraper

logger = logging.getLogger('announce_watcher')


class AnnounceWatcher:
    def __init__(self, on_new_futures_listing, poll_interval=60):
        """
        on_new_futures_listing: callback(symbol: str) when a new futures listing is detected.
        poll_interval: seconds between each poll
        """
        self.on_new_futures_listing = on_new_futures_listing
        self.poll_interval = poll_interval
        self._seen_articles = set()
        # Browser-like headers to avoid 403 blocks
        self._headers = {
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/125.0.0.0 Safari/537.36"
                        ),
                        "Accept": "application/json, text/plain, */*",
                        "Accept-Language": "en-US,en;q=0.9",
                        "Content-Type": "application/json",
                        "Referer": "https://www.binance.com/en/support/announcement",
                        "Origin": "https://www.binance.com",
                        "Connection": "keep-alive",
                        "X-UI-LANG": "en",
                        "clienttype": "web",
                        "Cookie": "lang=en; bnc_location=US; theme=dark;"
                    }

        # Extra headers/cookie to reduce 403s
        self._headers.update({
            'X-UI-LANG': 'en',
            'X-TRACE-ID': 'announcewatcher',
            'clienttype': 'web',
        })
        self._headers['Cookie'] = 'lang=en; bnc_location=US;'
        # HTML source (primary): Binance Futures announcements list
        self._list_url = 'https://www.binance.com/en/support/announcement/list/48'

    @staticmethod
    def _extract_articles(data: dict):
        d = data.get('data', {}) if isinstance(data, dict) else {}
        if isinstance(d, dict) and 'articles' in d and isinstance(d['articles'], list):
            return d['articles']
        # Some endpoints return catalogs with embedded articles
        catalogs = d.get('catalogs')
        if isinstance(catalogs, list):
            for cat in catalogs:
                if isinstance(cat, dict) and isinstance(cat.get('articles'), list):
                    return cat['articles']
        # Fallback: find first list of items that look like articles
        if isinstance(d, dict):
            for value in d.values():
                if isinstance(value, list) and value and isinstance(value[0], dict) and 'title' in value[0]:
                    return value
        return []

    @staticmethod
    def _extract_from_html(html: str):
        """Parse announcement list HTML and yield dicts with id, title, href and publishTime if detectable."""
        soup = BeautifulSoup(html, 'html.parser')
        items = []
        # Look for anchors that link to announcement detail pages
        for a in soup.select('a'):
            href = a.get('href') or ''
            if '/support/announcement/' not in href:
                continue
            title = (a.get_text(strip=True) or '')
            if not title:
                continue
            tl = title.lower()
            if 'perpetual' not in tl or 'usdt' not in tl:
                continue
            art_id = href.rstrip('/').split('/')[-1] or title
            # Try time from adjacent <time> or data attributes
            publish_ms = None
            t = a.find_next('time')
            time_text = ''
            if t is not None:
                time_text = t.get('datetime') or t.get_text(strip=True)
            if time_text:
                try:
                    iso = time_text.replace('Z', '+00:00')
                    dt = datetime.fromisoformat(iso)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    publish_ms = int(dt.timestamp() * 1000)
                except Exception:
                    publish_ms = None
            item = {'id': art_id, 'title': title, 'href': href}
            if publish_ms is not None:
                item['publishTime'] = publish_ms
            items.append(item)
        return items

    @staticmethod
    def _parse_launch_time_from_text(text: str) -> int | None:
        """Extract launch time in ms from free text lines like 'trading will commence at 2025-10-11 08:00 (UTC)'."""
        try:
            # Common patterns with UTC
            patterns = [
                r'(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})(?:\s*\(UTC\)|\s*UTC)',
                r'(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2})(?:\s*\(UTC\)|\s*UTC)',
                r'(\d{4}\.\d{2}\.\d{2})\s+(\d{2}:\d{2})(?:\s*\(UTC\)|\s*UTC)'
            ]
            for pat in patterns:
                m = re.search(pat, text)
                if m:
                    date_part = m.group(1).replace('/', '-').replace('.', '-')
                    time_part = m.group(2)
                    dt = datetime.fromisoformat(f"{date_part} {time_part}+00:00")
                    return int(dt.timestamp() * 1000)
        except Exception:
            return None
        return None

    async def _fetch_article_launch_time(self, session: aiohttp.ClientSession, href: str) -> int | None:
        """Fetch article detail page and attempt to parse the stated launch time (UTC) in ms."""
        try:
            url = href if href.startswith('http') else f"https://www.binance.com{href}"
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
                # Quick parse of visible text
                soup = BeautifulSoup(html, 'html.parser')
                text = soup.get_text(" ", strip=True)
                return self._parse_launch_time_from_text(text)
        except Exception:
            return None

    @staticmethod
    def _extract_timestamp_ms(art: dict) -> int | None:
        # Common Binance fields for publish time
        candidate_keys = [
            'releaseDate', 'publishDate', 'publishTime', 'createTime', 'ctime',
            'updateTime', 'gmtCreate', 'startTime', 'startTimeMs'
        ]
        for key in candidate_keys:
            if key in art and art[key] is not None:
                val = art[key]
                try:
                    # If string number, cast
                    if isinstance(val, str) and val.isdigit():
                        val = int(val)
                    if isinstance(val, (int, float)):
                        iv = int(val)
                        # Heuristic: treat as ms if magnitude large
                        if iv > 10_000_000_000:  # > ~2001 in seconds → assume ms
                            return iv
                        # seconds → convert to ms
                        return iv * 1000
                except Exception:
                    continue
        return None

    @staticmethod
    def _is_article_recent(art: dict, max_age_minutes: int) -> tuple[bool, str]:
        ts_ms = AnnounceWatcher._extract_timestamp_ms(art)
        if ts_ms is None:
            return True, 'no_timestamp'
        published = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        age = datetime.now(tz=timezone.utc) - published
        return age <= timedelta(minutes=max_age_minutes), published.isoformat()

    async def poll_loop(self):
        logger.info('Starting announcement poller interval=%ss url=%s', self.poll_interval, self._list_url)
        while True:
            try:
                async with aiohttp.ClientSession(headers=self._headers) as session:
                    # HTML scraping (single source of truth)
                    articles = []
                    async with session.get(self._list_url, timeout=10) as resp:
                        status = resp.status
                        if status != 200:
                            logger.warning('Announcement HTTP status %s for %s', status, self._list_url)
                            # Cloudflare/Suspicious response (202/403/5xx): try cloudscraper synchronously
                            if status in (202, 403, 429, 503):
                                try:
                                    scraper = cloudscraper.create_scraper()
                                    html = scraper.get(self._list_url).text
                                    articles = self._extract_from_html(html)
                                    logger.debug('Cloudscraper parsed %d items', len(articles))
                                except Exception as e:
                                    logger.debug('Cloudscraper fallback failed: %s', e)
                        else:
                            html = await resp.text()
                            articles = self._extract_from_html(html)
                            logger.debug('Parsed %d items from announcement list', len(articles))

                    if not articles:
                        logger.warning('No articles parsed from announcement list')
                    else:
                        for art in articles:
                            aid = art.get('id') or art.get('articleId') or art.get('title')
                            if aid in self._seen_articles:
                                continue
                            self._seen_articles.add(aid)
                            title = art.get('title', '')
                            title_lower = title.lower()
                            # Detect USDⓈ-Margined Perpetual listing
                            if 'will launch usd' in title_lower and 'perpetual' in title_lower:
                                is_recent, published_str = self._is_article_recent(art, config.ANNOUNCE_MAX_AGE_MINUTES)
                                if not is_recent:
                                    logger.info('Skipping stale listing (published %s): %s', published_str, title)
                                    continue
                                match = re.search(r'([A-Z0-9]{2,8}USDT)', title)
                                if match:
                                    symbol = match.group(1)
                                    # Attempt to fetch launch time from article page
                                    launch_ms = await self._fetch_article_launch_time(session, art.get('href', ''))
                                    if launch_ms:
                                        launch_dt = datetime.fromtimestamp(launch_ms / 1000, tz=timezone.utc).isoformat()
                                        logger.info('New futures listing detected: %s, launch time (UTC): %s', symbol, launch_dt)
                                    else:
                                        logger.info('New futures listing detected: %s (launch time unknown)', symbol)
                                    logger.info('New futures listing detected: %s', symbol)
                                    self.on_new_futures_listing(symbol)
            except Exception as e:
                logger.exception('Error in announcement polling: %s', e)

            logger.debug('Poll cycle complete. Sleeping %ss', self.poll_interval)
            await asyncio.sleep(self.poll_interval)

    async def run(self):
        await self.poll_loop()


