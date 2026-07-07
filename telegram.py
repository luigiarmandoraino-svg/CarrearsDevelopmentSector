from __future__ import annotations

import os
from typing import Optional

import httpx

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LuigiJobBot/1.0; +https://example.local)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class FetchError(RuntimeError):
    pass


async def fetch_url(url: str, use_playwright: bool = False, timeout: int = 40) -> str:
    if use_playwright:
        return await fetch_with_playwright(url, timeout=timeout)
    async with httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=timeout) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.text


async def fetch_json(url: str, params: Optional[dict] = None, timeout: int = 40) -> dict:
    headers = dict(DEFAULT_HEADERS)
    headers["Accept"] = "application/json"
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=timeout) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()


async def fetch_with_playwright(url: str, timeout: int = 40) -> str:
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        raise FetchError("Playwright is not installed. Run: pip install playwright && playwright install chromium") from exc

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent=DEFAULT_HEADERS["User-Agent"])
        await page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
        content = await page.content()
        await browser.close()
        return content
