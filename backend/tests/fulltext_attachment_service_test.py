from __future__ import annotations

from api.services.fulltext_attachment_service import format_combined_fulltext
from api.services.fulltext_attachment_service import validate_pdf


def test_validate_pdf_accepts_pdf_signature_after_whitespace():
    digest = validate_pdf(b'\n\t%PDF-1.7\nbody')
    assert len(digest) == 32


def test_validate_pdf_rejects_non_pdf_bytes():
    try:
        validate_pdf(b'not a pdf')
    except ValueError as exc:
        assert str(exc) == 'invalid_pdf'
    else:
        raise AssertionError('Expected invalid PDF to be rejected')


def test_combined_fulltext_has_unambiguous_document_boundaries():
    result = format_combined_fulltext(
        [
            ('study.pdf', 'main', '[0] Main study methods.'),
            (
                'appendix.pdf', 'supplementary',
                '[0] Supplementary outcome table.',
            ),
        ],
        'fallback',
    )

    assert '=== DOCUMENT: study.pdf (main) ===' in result
    assert '=== DOCUMENT: appendix.pdf (supplementary) ===' in result
    assert result.index('study.pdf') < result.index('appendix.pdf')
    assert '[0] Main study methods.' in result
    assert '[1] Supplementary outcome table.' in result


def test_combined_fulltext_reindexes_each_documents_local_sentence_ids():
    result = format_combined_fulltext(
        [
            ('main.pdf', 'main', '[0] First.\n\n[1] Second.'),
            ('supp.pdf', 'supplementary', '[0] Third.\n\n[1] Fourth.'),
        ],
        'fallback',
    )

    assert result.count('[0]') == 1
    assert '[2] Third.' in result
    assert '[3] Fourth.' in result


def test_combined_fulltext_uses_legacy_fallback_without_extracted_documents():
    assert format_combined_fulltext(
        [], '[0] Legacy text.',
    ) == '[0] Legacy text.'
