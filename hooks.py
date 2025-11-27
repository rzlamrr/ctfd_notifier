from __future__ import annotations

import logging
from typing import Any, Callable

from flask import current_app

from CTFd.plugins.challenges import CHALLENGE_CLASSES
from CTFd.utils import get_config

from .utils import DEFAULT_MESSAGE_TEMPLATE, send_telegram_message

logger = logging.getLogger(__name__)


def _wrap_challenge_update(app, type_id: str) -> None:
    """Wrap a challenge type's update() method to notify when it becomes visible."""
    try:
        logger.info("ctfd_notifier: attempting to wrap '%s' challenge update()", type_id)
        chal_cls = CHALLENGE_CLASSES.get(type_id)
        if chal_cls is None:
            app.logger.warning(
                "ctfd_notifier: '%s' challenge class not found; no automatic notifications will be attached.",
                type_id,
            )
            return

        original_update = getattr(chal_cls, "update", None)
        logger.info("ctfd_notifier: original '%s' update method: %r", type_id, original_update)
        if original_update is None:
            app.logger.warning(
                "ctfd_notifier: '%s' challenge class has no update() method.", type_id
            )
            return

        func = getattr(original_update, "__func__", original_update)
        logger.info("ctfd_notifier: underlying '%s' update function: %r", type_id, func)

        def wrapper(cls, challenge, request, *args, **kwargs):
            old_state = getattr(challenge, "state", None)
            result = func(cls, challenge, request, *args, **kwargs)
            new_state = getattr(challenge, "state", None)

            if old_state != "visible" and new_state == "visible":
                try:
                    name = getattr(challenge, "name", "Unknown")
                    category = getattr(challenge, "category", "Uncategorized")
                    value = getattr(challenge, "value", None)

                    template = (
                        get_config("ctfd_notifier_message_template")
                        or DEFAULT_MESSAGE_TEMPLATE
                    )
                    safe_value = value if value is not None else ""

                    try:
                        text = template.format(
                            name=name,
                            challenge=name,
                            category=category,
                            value=safe_value,
                        )
                    except Exception as fmt_err:
                        current_app.logger.warning(
                            "ctfd_notifier: template format error (%s): %s; using default template",
                            type(fmt_err).__name__,
                            fmt_err,
                        )
                        fallback = DEFAULT_MESSAGE_TEMPLATE
                        text = fallback.format(
                            name=name,
                            challenge=name,
                            category=category,
                            value=safe_value,
                        )

                    url_root = current_app.config.get("URL_ROOT", "").rstrip("/")
                    if url_root:
                        text += f"\n\nAdmin: {url_root}/admin/challenges"

                    send_telegram_message(text)
                except Exception as e:  # noqa: BLE001
                    try:
                        current_app.logger.warning(
                            "ctfd_notifier: error while building/sending notification from update(): %s",
                            e,
                        )
                    except Exception:
                        pass

            return result

        wrapper.__name__ = getattr(func, "__name__", "wrapped_update")
        wrapper.__doc__ = getattr(func, "__doc__", None)
        wrapper.__wrapped__ = func  # type: ignore[attr-defined]

        setattr(chal_cls, "update", classmethod(wrapper))

        app.logger.info(
            "ctfd_notifier: wrapped '%s' challenge update() with Telegram notifier",
            type_id,
        )
    except Exception as e:  # noqa: BLE001
        try:
            app.logger.warning(
                "ctfd_notifier: failed to wrap %s challenge update(): %s", type_id, e
            )
        except Exception:
            pass


def wrap_standard_challenge_update(app) -> None:
    """Wrap standard challenge update() to send notifications.

    Dynamic challenge will be wrapped separately after it is registered
    by the dynamic_challenges plugin.
    """
    _wrap_challenge_update(app, "standard")


def wrap_dynamic_challenge_update(app) -> None:
    """Public helper to wrap dynamic challenge update() once available."""
    _wrap_challenge_update(app, "dynamic")
