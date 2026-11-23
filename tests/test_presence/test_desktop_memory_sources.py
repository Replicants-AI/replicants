import json
from types import SimpleNamespace

import pytest

from replicants.memory.relational_reflection import desktop_sources, grounded_desktop_document
from replicants.inference.acceptance import EvidenceQuoteAcceptance


def test_relationship_sources_come_from_conversation_receipts_and_keep_speakers():
    entity = SimpleNamespace(_history=[{'role': 'user', 'content': 'an internal wake prompt'}],
        desktop=SimpleNamespace(conversation=SimpleNamespace(messages=[
            {'id': 'p1', 'role': 'person', 'text': 'hello Rill', 'status': 'processing'},
            {'id': 'b1', 'role': 'replicant', 'text': 'hello', 'status': 'delivered'},
            {'id': 'b2', 'role': 'replicant', 'text': 'unheard words', 'status': 'failed'}])))
    assert desktop_sources(entity) == [
        {'id': 'p1', 'speaker': 'them', 'text': 'hello Rill', 'status': 'processing'},
        {'id': 'b1', 'speaker': 'me', 'text': 'hello', 'status': 'delivered'}]


@pytest.mark.parametrize('citation', [
    {'source_id': 'private-thought', 'quote': 'morning light'},
    {'source_id': 'p1', 'quote': 'we watched morning light'},
    {'source_id': 'p1', 'quote': ''},
])
def test_private_imagery_cannot_supply_relationship_evidence(citation):
    sources = [{'id': 'p1', 'speaker': 'them', 'text': 'hello Rill', 'status': 'completed'}]
    raw = json.dumps({'impressions': 'I feel curious.', 'evidence': [citation]})
    with pytest.raises(ValueError, match='unsupported_reflection_citation'):
        grounded_desktop_document(raw, sources, [])


def test_facts_are_copied_and_subjective_impressions_are_labeled():
    sources = [{'id': 'p1', 'speaker': 'them', 'text': 'hello Rill', 'status': 'completed'}]
    document, events = grounded_desktop_document(json.dumps({
        'impressions': 'I keep imagining morning light; this is my image.',
        'evidence': [{'source_id': 'p1', 'quote': 'hello Rill'}]}), sources, [])
    facts, impressions = document.split('[SUBJECTIVE IMPRESSIONS:', 1)
    assert 'morning light' not in facts
    assert 'morning light' in impressions
    assert events == sources


def test_quote_metrics_count_every_proposal_even_when_document_is_rejected():
    metrics = EvidenceQuoteAcceptance()
    assert metrics.snapshot()['evidence_quote_acceptance_rate'] is None
    sources = [{'id': 'p1', 'speaker': 'them', 'text': 'hello Rill', 'status': 'completed'}]
    raw = json.dumps({'impressions': 'I wonder.', 'evidence': [
        {'source_id': 'p1', 'quote': 'invented'},
        {'source_id': 'p1', 'quote': 'hello'},
        {'source_id': [], 'quote': 'hello'},
        'malformed']})
    with pytest.raises(ValueError, match='unsupported_reflection_citation'):
        grounded_desktop_document(raw, sources, [], metrics=metrics)
    snapshot = metrics.snapshot()
    assert snapshot['quotes_proposed'] == 4 and snapshot['quotes_accepted'] == 1
    assert snapshot['quotes_rejected'] == 3 and snapshot['evidence_quote_acceptance_rate'] == .25
    assert snapshot['documents_rejected'] == 1 and snapshot['documents_accepted'] == 0
    with pytest.raises(ValueError):
        grounded_desktop_document('bad json', sources, [], metrics=metrics)
    assert metrics.snapshot()['documents_unparseable'] == 1
    assert metrics.snapshot()['quotes_proposed'] == 4
