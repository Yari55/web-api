import os
from typing import Optional

from fastapi.responses import StreamingResponse
from playwright.async_api import (
    BrowserContext,
    BrowserType,
    Page,
    Playwright,
    async_playwright,
)

from llm import config
from llm.api.chat import Message
from llm.base.chat import AbstractChat
from llm.base.crawler import AbstractCrawler
from llm.logger import logger
from llm.provider.openai.client import OpenAIClient


class OpenAICrawler(AbstractCrawler, AbstractChat):
    playwright: Playwright
    context_page: Page
    browser_context: BrowserContext
    openai_client: OpenAIClient

    def __init__(self) -> None:
        self.index_url = "https://sharegpt.new.oaifree.com/"
        self.https_proxy = config.PROXY_SERVER

        if config.OPENAI_LOGIN_TYPE == "nologin":
            self.supported_model = ["gpt-3.5-turbo"]
        else:
            self.supported_model = ["gpt-3.5-turbo", "gpt-4", "gpt-4o"]

    async def start(self) -> None:
        self.playwright = await async_playwright().start()
        # Launch a browser context.
        chromium = self.playwright.chromium
        self.browser_context = await self.launch_browser(
            chromium,
            {"server": self.https_proxy} if self.https_proxy else None,
            config.USER_AGENT,
            headless=config.HEADLESS,
        )
        self.browser_context.set_default_timeout(180_000)
        # doesn't work now
        # stealth.min.js is a js script to prevent the website from detecting the crawler.
        # await self.browser_context.add_init_script(
        #     path=os.path.join(os.getcwd(), "libs/stealth.min.js")
        # )
        await self.browser_context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => false});"
        )

        self.context_page = await self.browser_context.new_page()
        self.context_page.set_default_timeout(180_000)

        user_agent = await self.context_page.evaluate("navigator.userAgent")
        if "HEADLESS" in user_agent:
            logger.warn(
                "The user-agent contains HEADLESS. Note that this might not bypass Cloudflare challenge."
            )

        self.openai_client = OpenAIClient(
            playwright_page=self.context_page
        )
        await self.openai_client.post_init()

    async def launch_browser(
        self,
        chromium: BrowserType,
        playwright_proxy: Optional[dict],
        user_agent: Optional[str] = None,
        headless: bool = True,
    ) -> BrowserContext:
        """Launch browser and create browser context"""
        if config.SAVE_LOGIN_STATE:
            user_data_dir = os.path.join(config.BROWSER_DATA, "openai")
            browser_context = await chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                accept_downloads=True,
                headless=headless,
                proxy=playwright_proxy,
                # viewport={"width": config.SCREEN_WIDTH, "height": config.SCREEN_HEIGHT},
                user_agent=user_agent,
                channel="chrome",
                # https://peter.sh/experiments/chromium-command-line-switches/
                # 网上的答案都不对!!!
                # 隐藏“Chrome is being controlled by automated test software”提示
                ignore_default_args=["--enable-automation"],
            )  # type: ignore
            return browser_context
        else:
            browser = await chromium.launch(
                headless=headless,
                proxy=playwright_proxy,
                channel="chrome",
                ignore_default_args=["--enable-automation"],
            )
            browser_context = await browser.new_context(
                # viewport={"width": config.SCREEN_WIDTH, "height": config.SCREEN_HEIGHT},
                user_agent=user_agent,
            )
            return browser_context

    async def stop(self) -> None:
        """Close browser context"""
        await self.browser_context.close()
        await self.playwright.stop()
        logger.info("[OpenAICrawler.close] Browser context closed ...")

    async def chat_completion(
        self, model: str, messages=list[Message], stream: Optional[bool] = False
    ):
        messages = [_.dict() for _ in messages]

        try:
            if stream:
                return StreamingResponse(
                    await self.openai_client.create_completion(
                        model, messages, stream=True
                    ),
                    media_type="text/event-stream",
                )
            else:
                return await self.openai_client.create_completion(model, messages)
        except Exception:
            return {
                "status": False,
                "error": {
                    "message": "An error occurred. please try again. Additionally, ensure that your request complies with OpenAI's policy.",
                    "type": "invalid_request_error",
                },
                "support": "https://github.com/adryfish/llm-web-api",
            }
