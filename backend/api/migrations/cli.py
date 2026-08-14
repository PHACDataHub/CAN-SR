from __future__ import annotations

import argparse

from api.core.config import settings
from api.services.cit_db_service import cits_dp_service
from api.services.citation_legacy_adoption_service import citation_legacy_adoption_service
from api.services.review_schema_service import review_schema_service


def main() -> None:
    parser = argparse.ArgumentParser(description='CAN-SR database migrations')
    parser.add_argument(
        'command', choices=[
            'migrate', 'verify', 'status', 'refresh-checksums', 'adopt-legacy',
            'cleanup-set-answer-validation',
        ],
    )
    parser.add_argument(
        '--sr-id', help='Systematic-review ID for legacy citation-table adoption',
    )
    parser.add_argument(
        '--table-name', help='Configured dynamic citation-table name to adopt',
    )
    parser.add_argument(
        '--actor-id', help='Operator identity recorded in the adoption audit event',
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Validate legacy adoption without writing metadata',
    )
    parser.add_argument('--step', choices=['l1', 'l2', 'parameters'])
    parser.add_argument(
        '--execute', action='store_true',
        help='Actually clear matching legacy validation metadata; default is report-only',
    )
    args = parser.parse_args()
    if args.command == 'migrate':
        result = review_schema_service.migrate(settings.VERSION)
    elif args.command == 'refresh-checksums':
        result = review_schema_service.refresh_checksums()
    elif args.command == 'adopt-legacy':
        missing = [
            flag for flag, value in (
                ('--sr-id', args.sr_id), ('--table-name', args.table_name),
                ('--actor-id', args.actor_id),
            ) if not value
        ]
        if missing:
            parser.error(f"adopt-legacy requires {', '.join(missing)}")
        result = citation_legacy_adoption_service.adopt(
            args.sr_id, args.table_name, args.actor_id, dry_run=args.dry_run,
        )
    elif args.command == 'cleanup-set-answer-validation':
        if not args.table_name or not args.step:
            parser.error(
                'cleanup-set-answer-validation requires --table-name and --step',
            )
        result = cits_dp_service.cleanup_set_answer_validation_metadata(
            args.table_name, args.step, execute=args.execute,
        )
    else:
        result = review_schema_service.verify_schema()
    print(result)


if __name__ == '__main__':
    main()
