from __future__ import annotations

import logging
from typing import Any, Callable

from flask import current_app

from CTFd.plugins.challenges import CHALLENGE_CLASSES
from CTFd.utils import get_config

from .utils import DEFAULT_MESSAGE_TEMPLATE, send_telegram_message

logger = logging.getLogger(__name__)


def wrap_solve(cls):
    """Class decorator to wrap BaseChallenge.solve and send a Telegram notification."""

    original = getattr(cls, "solve", None)
    if original is None:
        return cls

    func = getattr(original, "__func__", original)

    def solve_wrapper(chal_cls, user, team, challenge, request, *args, **kwargs):
        result = func(chal_cls, user, team, challenge, request, *args, **kwargs)

        try:
            from CTFd.models import Solves, db  # local import to avoid cycles

            name = getattr(challenge, "name", "Unknown")

            # Compute solve position for this challenge (1-based)
            solve_count = (
                db.session.query(db.func.count(Solves.id))
                .filter(Solves.challenge_id == getattr(challenge, "id", None))
                .scalar()
            ) or 0

            user_name = getattr(user, "name", "Unknown")

            # Respect max solve notifications limit, if set
            max_solves_raw = get_config("ctfd_notifier_solve_limit")
            try:
                max_solves = int(max_solves_raw) if max_solves_raw not in (None, "") else None
            except (TypeError, ValueError):
                max_solves = None

            if max_solves is not None and solve_count > max_solves:
                return result

            # Skip entirely if solves notifications are disabled
            solves_enabled_raw = get_config("ctfd_notifier_solves_enabled") or "off"
            solves_enabled = str(solves_enabled_raw).lower() in {"1", "true", "yes", "on"}
            if not solves_enabled:
                return result

            # First Blood special message
            if solve_count == 1:
                template = get_config("ctfd_notifier_solve_first_blood_template") or (
                    "🩸 First Blood! ⚡️\n{user} solved {challenge}"
                )
                try:
                    text = template.format(user=user_name, challenge=name)
                except Exception:
                    # Fallback if template is invalid
                    fallback = "🩸 First Blood! ⚡️\n{user} solved {challenge}"
                    text = fallback.format(user=user_name, challenge=name)
                    fallback = "🩸 First Blood! ⚡️\n{user} solved {challenge}"
                    text = fallback.format(user=user_name, challenge=name)
            else:
                template = get_config("ctfd_notifier_solve_template") or "{user} solved {challenge} ({num})"

                try:
                    text = template.format(
                        user=user_name,
                        challenge=name,
                        num=solve_count,
                    )
                except Exception:
                    # Fallback if template is invalid
                    fallback = "{user} solved {challenge} ({num})"
                    text = fallback.format(
                        user=user_name,
                        challenge=name,
                        num=solve_count,
                    )

            url_root = current_app.config.get("URL_ROOT", "").rstrip("/")
            if url_root:
                text += f"\n\nChallenge: {url_root}/challenges#{name}-{challenge.id}"

            send_telegram_message(text, thread_config_key="ctfd_notifier_solve_thread_id")
        except Exception:
            # Never break solves on notification errors
            pass

        return result

    cls.solve = classmethod(solve_wrapper)
    return cls


def _wrap_challenge_update(app, type_id: str) -> None:
    """Wrap a challenge type's update() method to notify when it becomes visible."""
    try:
        logger.debug("ctfd_notifier: attempting to wrap '%s' challenge update()", type_id)
        chal_cls = CHALLENGE_CLASSES.get(type_id)
        if chal_cls is None:
            app.logger.warning(
                "ctfd_notifier: '%s' challenge class not found; no automatic notifications will be attached.",
                type_id,
            )
            return

        original_update = getattr(chal_cls, "update", None)
        logger.debug("ctfd_notifier: original '%s' update method: %r", type_id, original_update)
        if original_update is None:
            app.logger.warning(
                "ctfd_notifier: '%s' challenge class has no update() method.", type_id
            )
            return

        func = getattr(original_update, "__func__", original_update)
        logger.debug("ctfd_notifier: underlying '%s' update function: %r", type_id, func)

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

                    send_telegram_message(text, thread_config_key="ctfd_notifier_challenge_thread_id")
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
