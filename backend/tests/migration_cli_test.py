from __future__ import annotations

import sys

import pytest
from api.migrations import cli


def test_adopt_legacy_requires_scope_and_actor_arguments(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['can-sr-migrations', 'adopt-legacy'])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 2
    assert 'adopt-legacy requires --sr-id, --table-name, --actor-id' in capsys.readouterr().err


def test_adopt_legacy_passes_validated_arguments_to_service(monkeypatch, capsys):
    monkeypatch.setattr(
        sys, 'argv', [
            'can-sr-migrations', 'adopt-legacy', '--sr-id', 'sr-1',
            '--table-name', 'sr_1_citations', '--actor-id', 'owner@example.test', '--dry-run',
        ],
    )
    calls = []
    monkeypatch.setattr(
        cli.citation_legacy_adoption_service, 'adopt',
        lambda *args, **kwargs: calls.append(
            (args, kwargs),
        ) or {'dry_run': True},
    )

    cli.main()

    assert calls == [
        (('sr-1', 'sr_1_citations', 'owner@example.test'), {'dry_run': True}),
    ]
    assert "'dry_run': True" in capsys.readouterr().out


def test_cleanup_set_answer_validation_is_scoped_and_dry_run_by_default(monkeypatch, capsys):
    monkeypatch.setattr(
        sys, 'argv', [
            'can-sr-migrations', 'cleanup-set-answer-validation',
            '--table-name', 'sr_1_citations', '--step', 'l1',
        ],
    )
    calls = []
    monkeypatch.setattr(
        cli.cits_dp_service, 'cleanup_set_answer_validation_metadata',
        lambda *args, **kwargs: calls.append(
            (args, kwargs),
        ) or {'dry_run': True},
    )

    cli.main()

    assert calls == [
        (('sr_1_citations', 'l1'), {'execute': False}),
    ]
    assert "'dry_run': True" in capsys.readouterr().out
