import asyncio
import argparse
from schema import Chat_Schema
from database import Keys,Podcasts,Session

try:
    from playwright.async_api import async_playwright, Error as PlaywrightError
except ImportError:
    async_playwright = None
    PlaywrightError = Exception

class ServiceError(Exception):
    def __init__(self, status_code : int,detail : str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail

class Chat():
    def __init__(self,chat : Chat_Schema) -> None:
        self.p = None
        self.browser = None
        self.url = chat.url
        self.style = chat.style
        self.user_email = chat.user_email
        self.exchanges = chat.exchanges
        self.session = Session()

    async def load_browser(self):
        if async_playwright is None:
            raise ServiceError(
                status_code=500,
                detail="Playwright is not installed in this Python environment.",
            )
        try:
            self.p = await async_playwright().start()
            self.browser = await self.p.chromium.launch()
        except PlaywrightError as exc:
            msg = str(exc)
            if "libnspr4.so" in msg:
                raise ServiceError(
                    status_code=500,
                    detail=(
                        "Playwright dependency missing: libnspr4.so. "
                        "Install system deps with 'playwright install --with-deps chromium' "
                        "or install package 'libnspr4'."
                    ),
                )
            raise ServiceError(status_code=500, detail=f"Browser launch failed: {msg}")

    async def close_browser(self):
        if self.browser is not None:
            await self.browser.close()
            self.browser = None
        if self.p is not None:
            await self.p.stop()
            self.p = None

    async def get_url_content(self):
        try:
            await self.load_browser()
            page = await self.browser.new_page() # type: ignore
            response = await page.goto(url=self.url, wait_until="domcontentloaded")
            if response is not None and response.status >= 400:
                raise ServiceError(
                    status_code=400,
                    detail=f"URL returned HTTP {response.status}",
                )
            text_content = await page.evaluate(
                "() => document.body ? document.body.innerText : ''"
            )
            await page.close()
            return text_content
        except ServiceError:
            raise
        except Exception as exc:
            raise ServiceError(status_code=500, detail=f"Unable to process URL: {exc}")
        finally:
            await self.close_browser()

    async def chat(self):
        try:
            key_check = self.session.query(Keys).filter(Keys.useremail == self.user_email).first()
            if key_check is None:
                return {
                    "success": False,
                    "error": "No API key found please add it in settings",
                    "redirect": "/setting.html",
                }
            return {
                "success": True,
                "message": "API key found",
            }
        except ServiceError:
            raise
        except Exception as e:
            raise ServiceError(status_code=500,detail=f"Invalid request {e}")
        finally:
            self.session.close()
