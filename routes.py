from __future__ import annotations

import logging

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from CTFd.models import db
from CTFd.utils import get_config, set_config
from CTFd.utils.decorators import admins_only

from .utils import DEFAULT_MESSAGE_TEMPLATE

logger = logging.getLogger(__name__)


def register_admin_blueprint(app) -> None:
    """Register an admin blueprint to configure Telegram notifier settings."""
    notifier_bp = Blueprint(
        "ctfd_notifier_admin",
        __name__,
        template_folder="templates",
    )

    @notifier_bp.route("/admin/ctfd_notifier", methods=["GET", "POST"])
    @admins_only
    def config_view():
        if request.method == "POST":
            form_nonce = request.form.get("nonce", "")
            session_nonce = session.get("nonce", "")
            if not form_nonce or form_nonce != session_nonce:
                return redirect(url_for("admin.view_settings"))

            enabled = request.form.get("enabled", "off")
            enable_challenge = request.form.get("enable_challenge", "off")
            enable_solves = request.form.get("enable_solves", "off")
            bot_token = request.form.get("bot_token", "").strip()
            chat_id = request.form.get("chat_id", "").strip()
            message_template = request.form.get("message_template", "").strip()
            solve_template = request.form.get("solve_template", "").strip()
            first_blood_template = request.form.get("first_blood_template", "").strip()
            solve_limit = request.form.get("solve_limit", "").strip()
            challenge_thread_id = request.form.get("challenge_thread_id", "").strip()
            solve_thread_id = request.form.get("solve_thread_id", "").strip()

            set_config("ctfd_notifier_telegram_enabled", enabled)
            set_config("ctfd_notifier_challenge_enabled", enable_challenge)
            set_config("ctfd_notifier_solves_enabled", enable_solves)
            set_config("ctfd_notifier_telegram_bot_token", bot_token)
            set_config("ctfd_notifier_telegram_chat_id", chat_id)
            set_config(
                "ctfd_notifier_message_template",
                message_template or DEFAULT_MESSAGE_TEMPLATE,
            )
            set_config("ctfd_notifier_solve_template", solve_template)
            set_config("ctfd_notifier_solve_first_blood_template", first_blood_template)
            set_config("ctfd_notifier_solve_limit", solve_limit)
            set_config("ctfd_notifier_challenge_thread_id", challenge_thread_id)
            set_config("ctfd_notifier_solve_thread_id", solve_thread_id)

            db.session.commit()
            flash("CTFd Notifier settings updated", "success")
            return redirect(url_for("ctfd_notifier_admin.config_view"))

        enabled_raw = get_config("ctfd_notifier_telegram_enabled") or "off"
        enabled = str(enabled_raw).lower() in {"1", "true", "yes", "on", "on"}
        challenge_enabled_raw = get_config("ctfd_notifier_challenge_enabled") or "off"
        challenge_enabled = str(challenge_enabled_raw).lower() in {"1", "true", "yes", "on"}
        solves_enabled_raw = get_config("ctfd_notifier_solves_enabled") or "off"
        solves_enabled = str(solves_enabled_raw).lower() in {"1", "true", "yes", "on"}
        bot_token = get_config("ctfd_notifier_telegram_bot_token") or ""
        chat_id = get_config("ctfd_notifier_telegram_chat_id") or ""
        message_template = (
            get_config("ctfd_notifier_message_template") or DEFAULT_MESSAGE_TEMPLATE
        )
        solve_template = get_config("ctfd_notifier_solve_template") or "{user} solved {challenge} ({num})"
        first_blood_template = (
            get_config("ctfd_notifier_solve_first_blood_template")
            or "🩸 First Blood! ⚡️\n{user} solved {challenge}"
        )
        solve_limit = get_config("ctfd_notifier_solve_limit") or ""
        challenge_thread_id = get_config("ctfd_notifier_challenge_thread_id") or ""
        solve_thread_id = get_config("ctfd_notifier_solve_thread_id") or ""

        return render_template(
            "admin.html",
            enabled=enabled,
            challenge_enabled=challenge_enabled,
            solves_enabled=solves_enabled,
            bot_token=bot_token,
            chat_id=chat_id,
            message_template=message_template,
            solve_template=solve_template,
            first_blood_template=first_blood_template,
            solve_limit=solve_limit,
            challenge_thread_id=challenge_thread_id,
            solve_thread_id=solve_thread_id,
            nonce=session.get("nonce", ""),
        )

    app.register_blueprint(notifier_bp)
