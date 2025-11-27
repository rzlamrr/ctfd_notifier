import logging

from .routes import register_admin_blueprint
from .hooks import wrap_standard_challenge_update, wrap_solve

logger = logging.getLogger(__name__)


def load(app):
    """Plugin entrypoint for ctfd_notifier.

    - Wraps the standard challenge update() so notifications fire when
      challenges become visible.
    - Registers the admin configuration blueprint.
    """
    logger.info("ctfd_notifier: load() called, wrapping 'standard' challenge update() and registering admin blueprint")
    wrap_standard_challenge_update(app)
    register_admin_blueprint(app)