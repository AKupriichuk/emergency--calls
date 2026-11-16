"""Run Alembic migrations without shipping alembic.ini in the image.

script_location is set directly on the Config object instead of being read
from an .ini file, so the final image needs no Alembic config file.
"""

from __future__ import annotations

import sys

from alembic import command
from alembic.config import Config


def main(argv: list[str]) -> None:
    action = argv[0] if argv else "upgrade"
    revision = argv[1] if len(argv) > 1 else "head"

    config = Config()
    config.set_main_option("script_location", "migrations")
    config.set_main_option("prepend_sys_path", ".")

    if action == "upgrade":
        command.upgrade(config, revision)
    elif action == "downgrade":
        command.downgrade(config, revision)
    else:
        raise SystemExit(f"unsupported action: {action}")


if __name__ == "__main__":
    main(sys.argv[1:])
