import logging
import os
from dataclasses import dataclass

import requests
from flask import current_app

from CTFd.utils import get_config

logger = logging.getLogger(__name__)


DEFAULT_MESSAGE_TEMPLATE = (
    "*New challenge created*\n"
    "Name: `{name}`\n"
    "Category: `{category}`\n"
    "Value: `{value}`"
)


@dataclass
class TelegramConfig:
    enabled: bool
    bot_token: str | None
    chat_id: str | None

    @classmethod
    def from_app(cls) -> "TelegramConfig":
        app = current_app
        logger.debug("ctfd_notifier: Loading TelegramConfig from app config and environment")

        enabled_cfg = get_config("ctfd_notifier_telegram_enabled")
        if enabled_cfg is None:
            enabled_env = os.getenv("CTFD_NOTIFIER_TELEGRAM_ENABLED")
            enabled_app_cfg = app.config.get("CTFD_NOTIFIER_TELEGRAM_ENABLED", False)
            enabled_raw = enabled_env if enabled_env is not None else enabled_app_cfg
        else:
            enabled_raw = enabled_cfg

        enabled = str(enabled_raw).lower() in {"1", "true", "yes", "on"}

        bot_token = (
            get_config("ctfd_notifier_telegram_bot_token")
            or os.getenv("CTFD_NOTIFIER_TELEGRAM_BOT_TOKEN")
            or app.config.get("CTFD_NOTIFIER_TELEGRAM_BOT_TOKEN")
        )

        chat_id = (
            get_config("ctfd_notifier_telegram_chat_id")
            or os.getenv("CTFD_NOTIFIER_TELEGRAM_CHAT_ID")
            or app.config.get("CTFD_NOTIFIER_TELEGRAM_CHAT_ID")
        )

        logger.debug(
            "ctfd_notifier: Resolved TelegramConfig(enabled=%s, bot_token_set=%s, chat_id_set=%s)",
            enabled,
            bool(bot_token),
            bool(chat_id),
        )
        return cls(enabled=enabled, bot_token=bot_token, chat_id=chat_id)

    def is_valid(self) -> bool:
        return self.enabled and bool(self.bot_token) and bool(self.chat_id)


def send_telegram_message(text: str, *, thread_config_key: str | None = None) -> None:
    cfg = TelegramConfig.from_app()
    if not cfg.is_valid():
        logger.info(
            "ctfd_notifier: TelegramConfig invalid or disabled (enabled=%s, bot_token_set=%s, chat_id_set=%s); skipping send",
            cfg.enabled,
            bool(cfg.bot_token),
            bool(cfg.chat_id),
        )
        return

    try:
        logger.info("ctfd_notifier: Sending Telegram message to chat_id=%s", cfg.chat_id)
        url = f"https://api.telegram.org/bot{cfg.bot_token}/sendMessage"
        payload = {
            "chat_id": cfg.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        # Optional topic/thread ID support
        if thread_config_key:
            thread_raw = get_config(thread_config_key)
            try:
                thread_id = int(thread_raw) if thread_raw not in (None, "") else None
            except (TypeError, ValueError):
                thread_id = None

            if thread_id is not None:
                payload["message_thread_id"] = thread_id
        resp = requests.post(url, json=payload, timeout=3)
        logger.info(
            "ctfd_notifier: Telegram API response status=%s body=%s",
            resp.status_code,
            resp.text[:200],
        )
    except Exception as e:  # noqa: BLE001
        try:
            current_app.logger.warning(
                "ctfd_notifier: failed to send telegram message: %s", e
            )
        except Exception:
            pass
