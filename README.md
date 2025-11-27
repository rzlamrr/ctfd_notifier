# ctfd_notifier plugin

This plugin adds Telegram notifications for CTFd, for both **new challenges** and **challenge solves**, with configuration exposed in the CTFd admin UI.

## Features

- Telegram bot notifications to a single chat or channel.
- Challenge creation notifications when a challenge becomes **visible**.
- Solve notifications with:
  - “First Blood” special message for the first solver.
  - Per-solve message with solve position (`(1)`, `(2)`, …).
  - Optional maximum solves per challenge (stop notifying after N solves).
- Separate enable/disable switches for:
  - Challenge creation notifications.
  - Solve notifications.
- Optional Telegram topic/thread IDs for:
  - Challenge creation messages.
  - Solve messages.
- Works for:
  - Standard/static challenges.
  - Dynamic challenges, via changes applied in the `dynamic_challenges` plugin (see `dynamic.patch`).

## How it works

### Entry point (`__init__.py`)

The plugin entry point is `ctfd_notifier.load(app)`:

- Looks up the `"standard"` challenge type from `CTFd.plugins.challenges.CHALLENGE_CLASSES`.
- Wraps the standard challenge `update()` via `wrap_standard_challenge_update(app)` so that when a challenge’s `state` changes from non-`visible` to `visible`, a Telegram notification is sent.
- Wraps the standard challenge `solve()` via `wrap_solve(standard_cls)` so standard/static solves send Telegram messages.
- Registers the admin configuration blueprint (`register_admin_blueprint(app)`).

Dynamic challenges are wired separately inside the `dynamic_challenges` plugin (see below).

### Hooks (`hooks.py`)

#### Challenge update hook

`_wrap_challenge_update(app, type_id)`:

- Retrieves the challenge class from `CHALLENGE_CLASSES[type_id]`.
- Wraps its `update()` method so that after the original update:
  - It checks `old_state` and `new_state`.
  - If `old_state != "visible"` and `new_state == "visible"`, it builds a message using:
    - `ctfd_notifier_message_template` (or a default) and placeholders: `{name}`, `{challenge}`, `{category}`, `{value}`.
  - Sends the message via `send_telegram_message(...)`, optionally to a configured thread (see below).

`wrap_standard_challenge_update(app)` calls `_wrap_challenge_update(app, "standard")` for the default challenge type.

#### Solve hook

`wrap_solve(cls)` wraps a challenge class’s `solve` classmethod:

- Calls the original `solve` to record the solve in the database.
- Uses `Solves` and `db.func.count` to count solves for that `challenge_id` and compute the solve position `num` (1-based).
- Respects `ctfd_notifier_solve_limit`:
  - If set and `solve_count > limit`, no message is sent.
- Respects `ctfd_notifier_solves_enabled`:
  - If disabled, solves are recorded but no notifications are sent.
- Builds a Telegram message:
  - If `solve_count == 1` (first solve), uses:
    - `ctfd_notifier_solve_first_blood_template` or default  
      `🩸 First Blood! ⚡️\n{user} solved {challenge}`
  - Otherwise, uses:
    - `ctfd_notifier_solve_template` or default  
      `{user} solved {challenge} ({num})`
- Falls back to a safe default if templates are invalid.
- Appends an optional challenge URL if `URL_ROOT` is configured.
- Sends the message via `send_telegram_message(...)`, using the solve thread ID if configured.

The standard/static challenge is wrapped inside `ctfd_notifier.load()`; the dynamic challenge calls `wrap_solve(DynamicValueChallenge)` from its own plugin’s `load(app)`.

### Dynamic challenges (`dynamic.patch`)

Dynamic challenges are defined in `CTFd/plugins/dynamic_challenges/__init__.py` as `DynamicValueChallenge`. They are integrated with the notifier by:

- Registering the dynamic challenge class under `CHALLENGE_CLASSES["dynamic"]`.
- In `dynamic_challenges.load(app)`:
  - Calling `wrap_dynamic_challenge_update(app)` from `ctfd_notifier.hooks` to wrap the `update()` for the `"dynamic"` type, so dynamic challenges send creation/visibility notifications.
  - Calling `wrap_solve(DynamicValueChallenge)` so dynamic solves send solve notifications.

The `dynamic.patch` file documents or applies the code changes needed in `dynamic_challenges` to import and call these wrappers (for example, adding `from CTFd.plugins.ctfd_notifier.hooks import wrap_dynamic_challenge_update, wrap_solve` and the corresponding calls in `load(app)`).

## Telegram sending (`utils.py`)

`send_telegram_message(text, *, thread_config_key=None)`:

- Reads Telegram config from CTFd config or environment via `TelegramConfig.from_app()`:
  - `ctfd_notifier_telegram_enabled`
  - `ctfd_notifier_telegram_bot_token`
  - `ctfd_notifier_telegram_chat_id`
- If config is invalid/disabled, returns silently.
- Builds payload for `sendMessage`:
  - `chat_id`, `text`, `parse_mode="Markdown"`, `disable_web_page_preview=True`.
- If `thread_config_key` is provided:
  - Reads that config (e.g. `ctfd_notifier_challenge_thread_id` / `ctfd_notifier_solve_thread_id`).
  - If a valid integer is present, sets `message_thread_id` in the payload.
- Sends the payload with `requests.post` to `https://api.telegram.org/bot{TOKEN}/sendMessage`.
- Any errors are caught and logged via `current_app.logger.warning`, but never break CTFd.

## Admin UI (`routes.py` and `templates/admin.html`)

The admin blueprint is registered at `/admin/ctfd_notifier`. The form lets admins configure:

- Global:
  - Enable/disable all Telegram notifications.
  - Bot token and chat ID.
- Challenge creation:
  - Enable/disable challenge notifications (`ctfd_notifier_challenge_enabled`).
  - Message template (`ctfd_notifier_message_template`).
  - Challenge thread ID (`ctfd_notifier_challenge_thread_id`).
- Solves:
  - Enable/disable solve notifications (`ctfd_notifier_solves_enabled`).
  - First blood template (`ctfd_notifier_solve_first_blood_template`).
  - Solve template (`ctfd_notifier_solve_template`).
  - Solve limit per challenge (`ctfd_notifier_solve_limit`).
  - Solve thread ID (`ctfd_notifier_solve_thread_id`).

The UI is implemented in `templates/admin.html` as a set of Bootstrap cards grouped by function (Telegram connection, challenge creation notifications, solve notifications).
