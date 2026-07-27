from __future__ import annotations

import argparse

from api.core.config import settings
from api.services.review_schema_service import review_schema_service


def main() -> None:
    parser = argparse.ArgumentParser(description='CAN-SR database migrations')
    parser.add_argument('command', choices=['migrate', 'verify', 'status'])
    args = parser.parse_args()
    if args.command == 'migrate':
        result = review_schema_service.migrate(settings.VERSION)
    else:
        result = review_schema_service.verify_schema()
    print(result)


if __name__ == '__main__':
    main()
