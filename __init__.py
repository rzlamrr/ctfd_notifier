import logging

from CTFd.plugins.challenges import CHALLENGE_CLASSES

from .routes import register_admin_blueprint
from .hooks import wrap_standard_challenge_update, wrap_solve

logger = logging.getLogger(__name__)


def load(app):
    """Plugin entrypoint for ctfd_notifier.

    - Wraps the standard challenge update() so notifications fire when
      challenges become visible.
    - Wraps the standard challenge solve() so static solves send notifications.
    - Registers the admin configuration blueprint.
    """
    logger.debug("ctfd_notifier: load() called, wrapping 'standard' challenge update()/solve() and registering admin blueprint")

    wrap_standard_challenge_update(app)

    # Wrap standard challenge solves here so static challenges send solve notifications
    try:
        standard_cls = CHALLENGE_CLASSES.get("standard")
        if standard_cls is not None:
            wrap_solve(standard_cls)
        else:
            logger.warning("ctfd_notifier: 'standard' challenge class not found when trying to wrap solve()")
    except Exception as e:
        logger.warning("ctfd_notifier: failed to wrap standard challenge solve(): %s", e)

    register_admin_blueprint(app)