import os
from dataclasses import dataclass
from typing import Callable, Any

import requests
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from CTFd.models import db
from CTFd.plugins.challenges import CHALLENGE_CLASSES
from CTFd.utils import config, get_config, set_config

import logging

logger = logging.getLogger(__name__)
from CTFd.utils.decorators import admins_only


# ----------------------------------------------------------------------
# Telegram configuration + sender
# ----------------------------------------------------------------------


@dataclass
class TelegramConfig:
    enabled: bool
    bot_token: str | None
    chat_id: str | None

    @classmethod
    def from_app(cls) -> "TelegramConfig":
        """
        Load configuration from CTFd config table or environment variables.

        Priority:
        1. CTFd config keys (set via admin UI)
        2. Environment variables
        3. app.config keys (fallback)
        """
        app = current_app
        logger.debug("ctfd_notifier: Loading TelegramConfig from app config and environment")

        # Enabled flag
        enabled_cfg = get_config("ctfd_notifier_telegram_enabled")
        if enabled_cfg is None:
            enabled_env = os.getenv("CTFD_NOTIFIER_TELEGRAM_ENABLED")
            enabled_app_cfg = app.config.get("CTFD_NOTIFIER_TELEGRAM_ENABLED", False)
            enabled_raw = enabled_env if enabled_env is not None else enabled_app_cfg
        else:
            enabled_raw = enabled_cfg

        enabled = str(enabled_raw).lower() in {"1", "true", "yes", "on"}

        # Bot token
        bot_token = (
            get_config("ctfd_notifier_telegram_bot_token")
            or os.getenv("CTFD_NOTIFIER_TELEGRAM_BOT_TOKEN")
            or app.config.get("CTFD_NOTIFIER_TELEGRAM_BOT_TOKEN")
        )

        # Chat ID
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


def send_telegram_message(text: str) -> None:
    """
    Send a message to Telegram using the configured bot.

    This function is intentionally best-effort: it should never raise inside
    the CTFd request lifecycle. All errors are swallowed after logging.
    """
    cfg = TelegramConfig.from_app()
    if not cfg.is_valid():
        logger.info(
            "ctfd_notifier: TelegramConfig invalid or disabled (enabled=%s, bot_token_set=%s, chat_id_set=%s); skipping send",
            cfg.enabled,
            bool(cfg.bot_token),
            bool(cfg.chat_id),
        )
        # Misconfigured or disabled; do nothing
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
        # Small timeout to avoid blocking admin UI
        resp = requests.post(url, json=payload, timeout=3)
        logger.info("ctfd_notifier: Telegram API response status=%s body=%s", resp.status_code, resp.text[:200])
    except Exception as e:  # noqa: BLE001
        try:
            current_app.logger.warning(
                "ctfd_notifier: failed to send telegram message: %s", e
            )
        except Exception:
            # If logging itself fails, silently ignore
            pass


# ----------------------------------------------------------------------
# Decorator for BaseChallenge.create
# ----------------------------------------------------------------------


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
            logger.info("ctfd_notifier: notify_on_challenge_create wrapper invoked for %s", getattr(cls, "__name__", cls))

            # Call original create
            challenge = create_func(cls, request, *args, **kwargs)

            logger.info("ctfd_notifier: challenge created: name=%s category=%s value=%s", getattr(challenge, "name", None), getattr(challenge, "category", None), getattr(challenge, "value", None))

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
        logger.info("ctfd_notifier: attempting to wrap 'standard' challenge create()")
        standard_cls = CHALLENGE_CLASSES.get("standard")
        if standard_cls is None:
            app.logger.warning(
                "ctfd_notifier: 'standard' challenge class not found; "
                "no automatic notifications will be attached."
            )
            return

        # Get the original create method (classmethod object)
        original_create = getattr(standard_cls, "create", None)
        logger.info("ctfd_notifier: original 'standard' create method: %r", original_create)
        if original_create is None:
            app.logger.warning(
                "ctfd_notifier: 'standard' challenge class has no create() method."
            )
            return

        # original_create is a function bound as classmethod; get the underlying function
        func = getattr(original_create, "__func__", original_create)
        logger.info("ctfd_notifier: underlying 'standard' create function: %r", func)

        # Apply our decorator to the underlying function
        wrapped = notify_on_challenge_create()(func)
        logger.info("ctfd_notifier: wrapped 'standard' create function: %r", wrapped)

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


# ----------------------------------------------------------------------
# Admin configuration UI
# ----------------------------------------------------------------------


def _register_admin_blueprint(app):
    """
    Register an admin blueprint to configure Telegram notifier settings.
    """
    notifier_bp = Blueprint(
        "ctfd_notifier_admin",
        __name__,
        template_folder="templates",
    )

    @notifier_bp.route("/admin/ctfd_notifier", methods=["GET", "POST"])
    @admins_only
    def config_view():
        if request.method == "POST":
            # Basic CSRF protection using CTFd's nonce stored in the session
            form_nonce = request.form.get("nonce", "")
            session_nonce = session.get("nonce", "")
            if not form_nonce or form_nonce != session_nonce:
                return redirect(url_for("admin.view_settings"))

            enabled = request.form.get("enabled", "off")
            bot_token = request.form.get("bot_token", "").strip()
            chat_id = request.form.get("chat_id", "").strip()

            set_config("ctfd_notifier_telegram_enabled", enabled)
            set_config("ctfd_notifier_telegram_bot_token", bot_token)
            set_config("ctfd_notifier_telegram_chat_id", chat_id)

            db.session.commit()
            flash("CTFd Notifier settings updated", "success")
            return redirect(url_for("ctfd_notifier_admin.config_view"))

        # GET: load current values
        enabled_raw = get_config("ctfd_notifier_telegram_enabled") or "off"
        enabled = str(enabled_raw).lower() in {"1", "true", "yes", "on", "on"}
        bot_token = get_config("ctfd_notifier_telegram_bot_token") or ""
        chat_id = get_config("ctfd_notifier_telegram_chat_id") or ""

        return render_template(
            "ctfd_notifier/admin.html",
            enabled=enabled,
            bot_token=bot_token,
            chat_id=chat_id,
            nonce=session.get("nonce", ""),
        )

    app.register_blueprint(notifier_bp)


# ----------------------------------------------------------------------
# Plugin entrypoint
# ----------------------------------------------------------------------


def load(app):
    """
    Plugin entrypoint.

    Responsibilities:
    - Wrap the existing 'standard' challenge type's create() method so that
      creating a standard challenge sends a Telegram notification.
    - Expose the notify_on_challenge_create decorator for other plugins
      (e.g., cyberstorm-learn) to use on their own BaseChallenge subclasses.
    - Provide an admin UI at /admin/ctfd_notifier to configure Telegram
      bot token, chat ID, and enabled flag.
    """
    _wrap_standard_challenge_create(app)
    _register_admin_blueprint(app)