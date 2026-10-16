from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings
from app.repositories.database import Database


def main() -> None:
    parser = argparse.ArgumentParser(description="惠民智导数据库迁移、备份与恢复")
    parser.add_argument("action", choices=("migrate", "backup", "restore", "purge"))
    parser.add_argument("path", nargs="?", type=Path, help="backup/restore文件路径")
    arguments = parser.parse_args()
    database = Database(settings.database_path)
    if arguments.action == "migrate":
        database.initialize()
        print(f"DATABASE_MIGRATED version={database.schema_version}")
    elif arguments.action == "backup":
        if arguments.path is None:
            parser.error("backup必须提供目标路径")
        database.initialize()
        print(f"DATABASE_BACKUP_OK path={database.backup_to(arguments.path)}")
    elif arguments.action == "restore":
        if arguments.path is None:
            parser.error("restore必须提供备份路径")
        database.restore_from(arguments.path)
        print(f"DATABASE_RESTORE_OK version={database.schema_version}")
    else:
        database.initialize()
        count = database.purge_expired(settings.data_retention_days)
        print(f"DATABASE_PURGE_OK count={count}")


if __name__ == "__main__":
    main()
