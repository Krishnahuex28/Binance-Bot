import asyncio
import aiohttp
import logging
import re

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

    async def poll_loop(self):
        ANNOUNCE_URL = 'https://www.binance.com/gateway-api/v1/public/cms/article/list'
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(ANNOUNCE_URL, timeout=10) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            articles = data.get('data', {}).get('articles', [])
                            for art in articles:
                                aid = art.get('id') or art.get('articleId') or art.get('title')
                                if aid in self._seen_articles:
                                    continue
                                self._seen_articles.add(aid)
                                title = art.get('title', '')
                                title_lower = title.lower()
                                # Detect USDⓈ-Margined Perpetual listing
                                if 'will launch usd' in title_lower and 'perpetual' in title_lower:
                                    match = re.search(r'([A-Z0-9]{2,8}USDT)', title)
                                    if match:
                                        symbol = match.group(1)
                                        logger.info('New futures listing detected: %s', symbol)
                                        self.on_new_futures_listing(symbol)
            except Exception as e:
                logger.exception('Error in announcement polling: %s', e)

            await asyncio.sleep(self.poll_interval)

    async def run(self):
        await self.poll_loop()


