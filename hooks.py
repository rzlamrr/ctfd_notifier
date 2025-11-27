from __future__ import annotations

import logging
from typing import Any, Callable

from flask import current_app

from CTFd.plugins.challenges import CHALLENGE_CLASSES, BaseChallenge
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


def wrap_standard_challenge_create(app) -> None:
    """Wrap the existing 'standard' challenge class's create() method in-place."""
    try:
        logger.info("ctfd_notifier: attempting to wrap 'standard' challenge create()")
        standard_cls = CHALLENGE_CLASSES.get("standard")
        if standard_cls is None:
            app.logger.warning(
                "ctfd_notifier: 'standard' challenge class not found; "
                "no automatic notifications will be attached.",
            )
            return

        original_create = getattr(standard_cls, "create", None)
        logger.info("ctfd_notifier: original 'standard' create method: %r", original_create)
        if original_create is None:
            app.logger.warning(
                "ctfd_notifier: 'standard' challenge class has no create() method."
            )
            return

        func = getattr(original_create, "__func__", original_create)
        logger.info("ctfd_notifier: underlying 'standard' create function: %r", func)

        wrapped = notify_on_challenge_create()(func)
        logger.info("ctfd_notifier: wrapped 'standard' create function: %r", wrapped)

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
