from __future__ import annotations

import logging
from typing import Any, Callable

from flask import current_app

from CTFd.plugins.challenges import CHALLENGE_CLASSES, BaseChallenge

from CTFd.plugins.challenges import BaseChallenge
from CTFd.utils import get_config

from .utils import DEFAULT_MESSAGE_TEMPLATE, send_telegram_message

logger = logging.getLogger(__name__)


def notify_on_challenge_create(
    message_builder: Callable[[Any], str] | None = None,
):
    """Decorator factory for BaseChallenge.create to send a Telegram notification."""

    def decorator(create_func: Callable[..., Any]):
        def wrapper(cls, request, *args, **kwargs):
            logger.info(
                "ctfd_notifier: notify_on_challenge_create wrapper invoked for %s",
                getattr(cls, "__name__", cls),
            )

            challenge = create_func(cls, request, *args, **kwargs)

            logger.info(
                "ctfd_notifier: challenge created: name=%s category=%s value=%s",
                getattr(challenge, "name", None),
                getattr(challenge, "category", None),
                getattr(challenge, "value", None),
            )

            try:
                if message_builder is not None:
                    text = message_builder(challenge)
                else:
                    name = getattr(challenge, "name", "Unknown")
                    category = getattr(challenge, "category", "Uncategorized")
                    value = getattr(challenge, "value", None)

                    template = (
                        get_config("ctfd_notifier_message_template")
                        or DEFAULT_MESSAGE_TEMPLATE
                    )
                    safe_value = value if value is not None else ""

                    # Support both {name} and {challenge} as placeholders
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

        wrapper.__name__ = getattr(create_func, "__name__", "wrapped_create")
        wrapper.__doc__ = getattr(create_func, "__doc__", None)
        wrapper.__wrapped__ = create_func  # type: ignore[attr-defined]
        return classmethod(wrapper)

    return decorator


def wrap_standard_challenge_update(app) -> None:
    """Wrap the existing 'standard' challenge class's update() method.

    We send a notification only when the challenge transitions to a visible
    state so that admins finish configuring it first.
    """
    try:
        logger.info("ctfd_notifier: attempting to wrap 'standard' challenge update()")
        standard_cls = CHALLENGE_CLASSES.get("standard")
        if standard_cls is None:
            app.logger.warning(
                "ctfd_notifier: 'standard' challenge class not found; "
                "no automatic notifications will be attached.",
            )
            return

        original_update = getattr(standard_cls, "update", None)
        logger.info("ctfd_notifier: original 'standard' update method: %r", original_update)
        if original_update is None:
            app.logger.warning(
                "ctfd_notifier: 'standard' challenge class has no update() method."
            )
            return

        func = getattr(original_update, "__func__", original_update)
        logger.info("ctfd_notifier: underlying 'standard' update function: %r", func)

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

        setattr(standard_cls, "update", classmethod(wrapper))

        app.logger.info(
            "ctfd_notifier: wrapped 'standard' challenge update() with Telegram notifier"
        )
    except Exception as e:  # noqa: BLE001
        try:
            app.logger.warning(
                "ctfd_notifier: failed to wrap standard challenge update(): %s", e
            )
        except Exception:
            pass
