"""First-time Telethon userbot login.

Run this ONCE on the VPS to establish a persistent session. After that,
the ``telegram_ops`` skill family can reuse the cookie-style session file
without any interactive prompts.

Usage
-----

Outside the container (recommended, faster to iterate)::

    python -m agent.tools.telethon_login

Inside the container (if you installed nothing locally)::

    docker compose run --rm --service-ports agent \\
        python -m agent.tools.telethon_login

Interactive flow:

    1. Prompts for your phone number (international format, e.g. +628...).
    2. Telegram sends a login code to one of your other devices.
    3. You paste the code here.
    4. If you have 2FA enabled, you'll be asked for the password.
    5. Session is persisted to ``TELETHON_SESSION`` (``/app/data/userbot.session``
       by default) with mode 0600.

Security notes
--------------

* The .session file is a SQLite DB of auth keys. Treat it like a password.
* It's written under ``data/`` which is in ``.gitignore`` and backed by a
  Docker volume, so ``docker compose down`` will not lose it.
* You can revoke this session at any time from your Telegram app under
  ``Settings -> Devices``.

Requires ``TELEGRAM_API_ID`` and ``TELEGRAM_API_HASH`` from
https://my.telegram.org in ``.env``.
"""

from __future__ import annotations

import asyncio
import os
import stat
import sys
from pathlib import Path

from ..config import get_settings


async def _main() -> int:
    s = get_settings()
    if not s.telegram_api_id or not s.telegram_api_hash:
        print(
            "ERROR: TELEGRAM_API_ID and TELEGRAM_API_HASH are required.\n"
            "Obtain them from https://my.telegram.org and set in .env.",
            file=sys.stderr,
        )
        return 2

    try:
        from telethon import TelegramClient
    except ImportError:
        print("ERROR: telethon not installed. Run 'pip install .' first.", file=sys.stderr)
        return 2

    session_path = Path(s.telethon_session)
    session_path.parent.mkdir(parents=True, exist_ok=True)

    # Telethon expects the session path without the '.session' extension.
    # (It appends it internally.) Strip if present for convenience.
    stem = str(session_path)
    if stem.endswith(".session"):
        stem = stem[: -len(".session")]

    print(f"Creating Telethon session at: {stem}.session")
    print(f"Using API ID: {s.telegram_api_id}")
    print()

    # TelegramClient.start() is the canonical 'login flow' helper - it will
    # prompt on stdin for phone / code / 2FA password as needed and persist.
    client = TelegramClient(stem, int(s.telegram_api_id), s.telegram_api_hash)
    await client.start()
    me = await client.get_me()
    print()
    print(f"Logged in as: {me.first_name} (@{me.username}) id={me.id}")
    await client.disconnect()

    final_path = Path(f"{stem}.session")
    try:
        os.chmod(final_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        pass

    print(f"Session saved: {final_path}")
    print("You can now start the agent normally; telegram_ops skills will use this session.")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
