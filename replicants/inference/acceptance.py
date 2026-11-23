"""Session-local validation counts. Acceptance measures checks, not model accuracy."""
from collections import Counter
import time


def _rate(numerator: int, denominator: int):
    return numerator / denominator if denominator else None


class AppraisalAcceptance:
    def __init__(self):
        self.started_at = time.time()
        self.counts = Counter()

    def record(self, *, proposed: int, rejected: int = 0, checked: bool = False):
        self.counts['drafts'] += 1
        if not proposed:
            self.counts['drafts_without_effects'] += 1
            return
        if not checked:
            self.counts['unchecked_appraisals'] += 1
            self.counts['unchecked_bars_retained'] += proposed
            return
        self.counts['checked_appraisals'] += 1
        self.counts['checked_bars_proposed'] += proposed
        self.counts['checked_bars_retained'] += proposed - rejected
        self.counts['checked_bars_rejected'] += rejected
        self.counts['fully_accepted' if not rejected else 'partially_accepted' if rejected < proposed else 'fully_rejected'] += 1

    def snapshot(self):
        counts = {key: self.counts[key] for key in (
            'drafts', 'drafts_without_effects', 'checked_appraisals', 'unchecked_appraisals',
            'fully_accepted', 'partially_accepted', 'fully_rejected', 'checked_bars_proposed',
            'checked_bars_retained', 'checked_bars_rejected', 'unchecked_bars_retained')}
        return {'scope': 'current brain process', 'started_at': self.started_at, **counts,
                'checked_appraisal_full_acceptance_rate': _rate(counts['fully_accepted'], counts['checked_appraisals']),
                'checked_bar_acceptance_rate': _rate(counts['checked_bars_retained'], counts['checked_bars_proposed'])}


class EvidenceQuoteAcceptance:
    def __init__(self):
        self.started_at = time.time()
        self.counts = Counter()

    def snapshot(self):
        counts = {key: self.counts[key] for key in (
            'documents_checked', 'documents_accepted', 'documents_rejected',
            'documents_unparseable', 'quotes_proposed', 'quotes_accepted', 'quotes_rejected')}
        return {'scope': 'current brain process; completed desktop reflection drafts',
                'started_at': self.started_at, **counts,
                'evidence_quote_acceptance_rate': _rate(counts['quotes_accepted'], counts['quotes_proposed'])}
