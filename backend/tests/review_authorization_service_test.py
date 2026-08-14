from __future__ import annotations

import pytest
from api.services.sr_db_service import SRDBService
from fastapi import HTTPException


def test_require_review_role_returns_matching_role(monkeypatch):
    service = SRDBService()
    monkeypatch.setattr(service, 'get_member_role', lambda *_: 'member')

    assert service.require_review_role(
        'sr-1', 'member@example.test', {'member', 'owner'},
    ) == 'member'


def test_require_review_owner_accepts_co_owner_and_rejects_member(monkeypatch):
    service = SRDBService()
    monkeypatch.setattr(
        service, 'get_member_role', lambda _sr_id,
        member_id: 'owner' if member_id == 'co-owner@example.test' else 'member',
    )

    service.require_review_owner('sr-1', 'co-owner@example.test')
    with pytest.raises(HTTPException) as exc_info:
        service.require_review_owner('sr-1', 'member@example.test')
    assert exc_info.value.status_code == 403


def test_require_review_owner_rejects_missing_membership(monkeypatch):
    service = SRDBService()
    monkeypatch.setattr(service, 'get_member_role', lambda *_: None)

    with pytest.raises(HTTPException) as exc_info:
        service.require_review_owner('sr-1', 'outsider@example.test')
    assert exc_info.value.status_code == 403
