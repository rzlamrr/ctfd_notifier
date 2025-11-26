import os
from dataclasses import dataclass
from typing import Callable, Any

import requests
from flask import current_app

from CTFd.plugins.challenges import BaseChallenge as CTFdBaseChallenge
from CTFd.plugins.challenges import CHALLENGE_CLASSES


@dataclass
class TelegramConfig:
    enabled: bool
    bot_token: str | None
    chat_id: str | None

    @classmethod
    def from_app(cls) -> "TelegramConfig":
        """
        Load configuration from environment variables or app.config.

        Priority:
        1. Environment variables
        2. app.config keys
        """
        app = current_app

        enabled_env = os.getenv("CTFD_NOTIFIER_TELEGRAM_ENABLED")
        enabled_cfg = app.config.get("CTFD_NOTIFIER_TELEGRAM_ENABLED", False)
        enabled = str(enabled_env or enabled_cfg).lower() in {"1", "true", "yes", "on"}

        bot_token = (
            os.getenv("CTFD_NOTIFIER_TELEGRAM_BOT_TOKEN")
            or app.config.get("CTFD_NOTIFIER_TELEGRAM_BOT_TOKEN")
        )
        chat_id = (
            os.getenv("CTFD_NOTIFIER_TELEGRAM_CHAT_ID")
            or app.config.get("CTFD_NOTIFIER_TELEGRAM_CHAT_ID")
        )

        return cls(enabled=enabled, bot_token=bot_token, chat_id=chat_id)

    def is_valid(self) -> bool:
        return self.enabled and bool(self.bot_token) and bool(self.chat_id)


def send_telegram_message(text: str) -> None:
    """
    Send a message to Telegram using the configured bot.

    This function is intentionally best-effort: it should never raise inside
    the CTFd request lifecycle. All errors are swallowed after logging.
    """
    cfg = TelegramConfig.from_app()
    if not cfg.is_valid():
        # Misconfigured or disabled; do nothing
        return

    try:
        url = f"https://api.telegram.org/bot{cfg.bot_token}/sendMessage"
        payload = {
            "chat_id": cfg.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        # Small timeout to avoid blocking admin UI
        requests.post(url, json=payload, timeout=3)
    except Exception as e:  # noqa: BLE001
        try:
            current_app.logger.warning(
                "ctfd_notifier: failed to send telegram message: %s", e
            )
        except Exception:
            # If logging itself fails, silently ignore
            pass


def notify_on_challenge_create(
    message_builder: Callable[[Any], str] | None = None,
):
    """
    Decorator factory for BaseChallenge.create to send a Telegram notification
    whenever a new challenge is created.

    Usage inside a plugin that defines a custom challenge type:

        from CTFd.plugins.challenges import BaseChallenge
        from CTFd.plugins.ctfd_notifier import notify_on_challenge_create

        class MyChallenge(BaseChallenge):
            id = "my_chal"
            name = "My Challenge"

            @classmethod
            @notify_on_challenge_create()
            def create(cls, request):
                ...

    Or with a custom message:

        @notify_on_challenge_create(
            lambda chal: f"New challenge: {chal.name} ({chal.category})"
        )
    """

    def decorator(create_func: Callable[..., Any]):
        def wrapper(cls, request, *args, **kwargs):
            # Call original create
            challenge = create_func(cls, request, *args, **kwargs)

            try:
                # Build default message if no custom builder is provided
                if message_builder is not None:
                    text = message_builder(challenge)
                else:
                    # Generic default message
                    name = getattr(challenge, "name", "Unknown")
                    category = getattr(challenge, "category", "Uncategorized")
                    value = getattr(challenge, "value", None)

                    # URL_ROOT is optional; best-effort
                    url_root = current_app.config.get("URL_ROOT", "").rstrip("/")

                    text = (
                        "*New challenge created*\n"
                        f"Name: `{name}`\n"
                        f"Category: `{category}`\n"
                    )
                    if value is not None:
                        text += f"Value: `{value}`\n"
                    if url_root:
                        text += f"\nAdmin: {url_root}/admin/challenges"

                send_telegram_message(text)
            except Exception as e:  # noqa: BLE001
                try:
                    current_app.logger.warning(
                        "ctfd_notifier: error while building/sending notification: %s",
                        e,
                    )
                except Exception:
                    pass

            return challenge

        # Preserve attributes that CTFd might inspect (e.g., __name__)
        wrapper.__name__ = getattr(create_func, "__name__", "wrapped_create")
        wrapper.__doc__ = getattr(create_func, "__doc__", None)
        wrapper.__wrapped__ = create_func  # type: ignore[attr-defined]
        return classmethod(wrapper)

    return decorator


def _wrap_standard_challenge_create(app):
    """
    Wrap the existing 'standard' challenge class's create() method in-place
    so that all its attributes (templates, scripts, etc.) remain unchanged.
    """
    try:
        standard_cls = CHALLENGE_CLASSES.get("standard")
        if standard_cls is None:
            app.logger.warning(
                "ctfd_notifier: 'standard' challenge class not found; "
                "no automatic notifications will be attached."
            )
            return

        # Get the original create method (classmethod object)
        original_create = getattr(standard_cls, "create", None)
        if original_create is None:
            app.logger.warning(
                "ctfd_notifier: 'standard' challenge class has no create() method."
            )
            return

        # original_create is a function bound as classmethod; get the underlying function
        func = getattr(original_create, "__func__", original_create)

        # Apply our decorator to the underlying function
        wrapped = notify_on_challenge_create()(func)

        # Replace the create method on the class
        setattr(standard_cls, "create", wrapped)

        app.logger.info(
            "ctfd_notifier: wrapped 'standard' challenge create() with Telegram notifier"
        )
    except Exception as e:  # noqa: BLE001
        try:
            app.logger.warning(
                "ctfd_notifier: failed to wrap standard challenge create(): %s", e
            )
        except Exception:
            pass


def load(app):
    """
    Plugin entrypoint.

    Responsibilities:
    - Wrap the existing 'standard' challenge type's create() method so that
      creating a standard challenge sends a Telegram notification.
    - Expose the notify_on_challenge_create decorator for other plugins
      (e.g., cyberstorm-learn) to use on their own BaseChallenge subclasses.
    """
    _wrap_standard_challenge_create(app)