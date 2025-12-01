import logging

from CTFd.plugins.challenges import CHALLENGE_CLASSES

from .routes import register_admin_blueprint
from .hooks import wrap_standard_challenge_update, wrap_solve, event_publish_decorator

logger = logging.getLogger(__name__)


def load(app):
    """Plugin entrypoint for ctfd_notifier.

    - Wraps the standard challenge update() so notifications fire when
      challenges become visible.
    - Wraps the standard challenge solve() so static solves send notifications.
    - Registers the admin configuration blueprint.
    """
    from CTFd.utils import get_config

    debug_raw = get_config("ctfd_notifier_debug_enabled") or "off"
    debug_enabled = str(debug_raw).lower() in {"1", "true", "yes", "on"}

    if debug_enabled:
        logger.debug("ctfd_notifier: load() called, wrapping 'standard' challenge update()/solve() and registering admin blueprint")

    wrap_standard_challenge_update(app)

    # Wrap standard challenge solves here so static challenges send solve notifications
    try:
        standard_cls = CHALLENGE_CLASSES.get("standard")
        if standard_cls is not None:
            wrap_solve(standard_cls)
        elif debug_enabled:
            logger.debug("ctfd_notifier: 'standard' challenge class not found when trying to wrap solve()")
    except Exception as e:
        if debug_enabled:
            logger.debug("ctfd_notifier: failed to wrap standard challenge solve(): %s", e)

    # Wrap events_manager.publish to intercept notification events
    try:
        if hasattr(app, 'events_manager') and hasattr(app.events_manager, 'publish'):
            app.events_manager.publish = event_publish_decorator(app.events_manager.publish)
            if debug_enabled:
                logger.debug("ctfd_notifier: wrapped app.events_manager.publish")
        elif debug_enabled:
            logger.debug("ctfd_notifier: app.events_manager.publish not found")
    except Exception as e:
        if debug_enabled:
            logger.debug("ctfd_notifier: failed to wrap events_manager.publish: %s", e)

    register_admin_blueprint(app)