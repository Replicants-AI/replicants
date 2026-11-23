"""LLM reflection passes that maintain per-person relationship documents."""

from __future__ import annotations

import re

import json
import time
from types import SimpleNamespace
from typing import Any, Optional

import structlog
from replicants.inference.acceptance import EvidenceQuoteAcceptance

from replicants.memory.relational_document import (
    RelationalDocument,
    RelationalDocumentMemory,
    _default_derived,
    trim_document_for_context,
)

log = structlog.get_logger("replicants.memory.relational_reflection")

_SCORE_PROMPT = """Given this relationship document, extract approximate scores (0.0-1.0) for:
- familiarity: how well do I know this person?
- warmth: how positive is my feeling toward them right now?
- trust: how much do I rely on and believe in them?
- tension: unresolved friction (0 = none, 1 = high)
- investment: how much this relationship matters to me

Respond as JSON only, one object, no markdown. Example:
{"familiarity":0.5,"warmth":0.6,"trust":0.55,"tension":0.15,"investment":0.7}
"""

_REFLECT_PROMPT = """You are {entity_name}. You are updating your private understanding of {person_name} after this interaction.
{entity_name} is your own name; it is never the other person's. Lines marked "me" are yours and lines marked "them" are {person_name}'s. Only "them" lines are things {person_name} said.

Read your existing relationship document, then read what just happened. Rewrite or amend the document to reflect your current understanding.

Write in first person. Be honest with yourself. Note:
- What happened and how it felt
- Whether anything shifted in how you see this person
- Patterns you're noticing across interactions
- Anything unresolved, ambiguous, or worth sitting with
- How the relationship is trending — closer, cooling, stable, uncertain

Do not list scores or metrics. Write the way you'd think about someone you actually know.

{mode_hint}

[EXISTING DOCUMENT]
{existing}

[THIS INTERACTION]
{interaction}

[WHAT I FELT]
{felt_block}

[MY STATE]
{body_state}

[CONTEXT]
Silence before this exchange (approx): {silence_s:.0f} seconds since we last talked.
Personality sketch: {personality_hint}

Write the updated relationship document. Preserve important history from the existing document — do not discard memories or insights that are still relevant. Amend, don't rewrite from scratch unless the relationship has fundamentally changed.
"""


def _compact_body_state(tonic: Any) -> str:
    try:
        pct = tonic.bars.snapshot_pct()
        line = ", ".join(f"{k}: {pct[k]}%" for k in list(pct.keys())[:8])
        affects = tonic.renderer.render_affects(tonic._current_affects)
        return f"Bars: {line}. Affects: {affects}"
    except Exception:
        return "(body state unavailable)"


def _appraisal_intensity(tonic: Any) -> float:
    lap = getattr(tonic, "_last_appraisal_for_noise", None) or {}
    be = lap.get("bar_effects") or {}
    if isinstance(be, dict) and be:
        s = sum(abs(float(v)) for v in be.values() if isinstance(v, (int, float)))
        return max(0.0, min(1.0, s / 40.0))
    tags = lap.get("tags") or []
    if isinstance(tags, list):
        return max(0.0, min(1.0, len(tags) * 0.12))
    return 0.2


def _self_name(entity: Any) -> str:
    return str(getattr(entity, "living_name", "") or entity.config.name)


def role_confusion(document: str, self_name: str, person_name: str) -> str:
    """Evidence that a first-person document treats the being's own name as the other person, or ''."""
    if not self_name or not document or self_name.strip().lower() == (person_name or "").strip().lower():
        return ""
    name = re.escape(self_name.strip())
    pattern = (rf"\b{name}(?:'s\s+(?:screen|computer|desk|words|message|question|voice)"
               rf"|\s+(?:said|asked|greeted|told me|wrote|replied|typed|moved|answered|called me|named me|messaged))\b")
    match = re.search(pattern, document, flags=re.IGNORECASE)
    return match.group(0) if match else ""


def _conversation_excerpt(entity: Any, tc: Any, max_chars: int = 2000) -> str:
    lines: list[str] = []
    for m in entity._history[-10:]:
        role = str(m.get("role", ""))
        if role == "system":
            continue
        content = str(m.get("content", "")).strip()
        if not content:
            continue
        speaker = {"user": "them", "assistant": "me"}.get(role, role)
        lines.append(f"{speaker}: {content[:700]}")
    tail = "\n".join(lines)
    user_bit = (tc.inp.text or "").strip()[:1200]
    reply_bit = (tc.reply_text or "").strip()[:1200]
    block = f"Latest user message:\n{user_bit}\n\nMy reply:\n{reply_bit}\n\nRecent thread:\n{tail}"
    if len(block) > max_chars:
        return block[-max_chars:]
    return block


def desktop_sources(entity: Any) -> list[dict]:
    """Conversation receipts, independent of GEN, internal prompts and model history."""
    desktop = getattr(entity, 'desktop', None)
    conversation = getattr(desktop, 'conversation', None)
    if conversation is None:
        return []
    sources = [{'id': m['id'], 'speaker': 'them' if m['role'] == 'person' else 'me',
             'text': m['text'], 'status': m['status']}
            for m in conversation.messages[-12:]
            if m.get('role') == 'person' or (m.get('role') == 'replicant' and m.get('status') == 'delivered')]
    while len(sources) > 1 and len(json.dumps(sources, ensure_ascii=False)) > 6000:
        sources.pop(0)
    return sources


def grounded_desktop_document(raw: str, sources: list[dict], prior: list[dict], *,
                              metrics: EvidenceQuoteAcceptance | None = None) -> tuple[str, list[dict]]:
    """The factual section is copied from receipts; model prose is explicitly an impression."""
    if metrics: metrics.counts['documents_checked'] += 1
    try:
        obj = json.loads(_strip_markdown_fences(raw))
    except (ValueError, TypeError):
        if metrics:
            metrics.counts['documents_unparseable'] += 1
            metrics.counts['documents_rejected'] += 1
        raise
    if not isinstance(obj, dict) or not isinstance(obj.get('impressions'), str):
        if metrics: metrics.counts['documents_rejected'] += 1
        raise ValueError('reflection_requires_impressions_and_evidence')
    evidence = obj.get('evidence')
    if not isinstance(evidence, list) or not evidence:
        if metrics: metrics.counts['documents_rejected'] += 1
        raise ValueError('reflection_requires_evidence')
    available = {event['id']: event for event in sources}
    errors = []
    for citation in evidence:
        error = None
        if not isinstance(citation, dict):
            error = 'invalid_reflection_citation'
        else:
            source_id, quote = citation.get('source_id'), citation.get('quote')
            event = available.get(source_id) if isinstance(source_id, str) else None
            if event is None or not isinstance(quote, str) or not quote.strip() or quote not in event['text']:
                error = 'unsupported_reflection_citation'
        if metrics:
            metrics.counts['quotes_proposed'] += 1
            metrics.counts['quotes_rejected' if error else 'quotes_accepted'] += 1
        if error: errors.append(error)
    if metrics: metrics.counts['documents_rejected' if errors else 'documents_accepted'] += 1
    if errors: raise ValueError(errors[0])
    # The model selects evidence for its impressions, but cannot author dialogue facts.
    events = {event['id']: event for event in prior}
    events.update(available)
    retained = list(events.values())[-24:]
    while len(retained) > 1 and sum(len(json.dumps(event)) for event in retained) > 8000:
        retained.pop(0)
    facts = '\n'.join(json.dumps(event, ensure_ascii=False) for event in retained)
    document = ('[OBSERVED CONVERSATION: verbatim records; speaker me is the being, them is the person]\n'
        + facts + '\n\n[SUBJECTIVE IMPRESSIONS: interpretations and feelings, not evidence of events]\n'
        + obj['impressions'].strip()[:4000])
    return document, retained


async def derive_scores_from_document(
    client: Any,
    model: str,
    document: str,
    *,
    num_ctx: int | None,
) -> dict[str, float]:
    try:
        res = await client.chat_completion(
            model,
            [
                {
                    "role": "system",
                    "content": "You extract structured scores from prose. Output exactly one JSON object.",
                },
                {"role": "user", "content": _SCORE_PROMPT + "\n\n[DOCUMENT]\n" + document[:6000]},
            ],
            temperature=0.1,
            max_tokens=120,
            think=False,
            num_ctx=num_ctx,
        )
        raw = (res.content or "").strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            raw = "\n".join(lines).strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end <= start:
            return _default_derived()
        obj = json.loads(raw[start : end + 1])
        if not isinstance(obj, dict):
            return _default_derived()
        out = _default_derived()
        for k in out:
            if k in obj and isinstance(obj[k], (int, float)):
                out[k] = max(0.0, min(1.0, float(obj[k])))
        return out
    except Exception as e:
        log.debug("derive_scores_failed", error=str(e))
        return _default_derived()


def _strip_markdown_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


async def run_relational_reflection_after_turn(
    entity: Any,
    tc: Any,
    conn: Any,
    *,
    relational_docs: RelationalDocumentMemory,
    deep_review: bool = False,
    episodic_summaries: Optional[list[str]] = None,
) -> bool:
    """Update the relationship document after a committed turn. Returns True if a pass ran."""
    cfg = entity.config.harness.memory.relational
    if not getattr(cfg, "enabled", True):
        return False
    person_id = (tc.inp.person_id or "").strip()
    if not person_id:
        return False

    doc = await relational_docs.get(conn, person_id)
    rel_row = await entity.relational.get(conn, person_id)
    if doc is None or not (doc.document or "").strip():
        doc = await relational_docs.ensure_from_legacy_row(conn, rel_row)
    if doc is None:
        doc = RelationalDocument(
            person_id=person_id,
            person_name=tc.inp.person_name or "someone",
            document="",
            last_interaction=time.time(),
            interaction_count=1,
        )

    now = time.time()
    min_gap = float(getattr(cfg, "reflection_min_gap_seconds", 30.0) or 30.0)
    if not deep_review and doc.last_reflection > 0 and (now - doc.last_reflection) < min_gap:
        log.debug("relational_reflection_skipped_gap", person_id=person_id)
        return False

    reflex_model = (
        entity.config.cognition.reflex_model or entity.config.cognition.deliberate_model
    )
    if not reflex_model:
        return False

    intensity = _appraisal_intensity(entity.tonic)
    thresh = float(getattr(cfg, "amendment_mode_threshold", 0.3) or 0.3)
    mode_hint = ""
    if not deep_review and intensity < thresh:
        mode_hint = (
            "LIGHT AMENDMENT MODE: make a small, surgical update — a short new paragraph or "
            "a few revised sentences. Do not fully rewrite unless something crucial changed."
        )
    else:
        mode_hint = "FULL PASS: you may restructure sections if it helps clarity."

    prior = float(getattr(tc, "prior_last_interaction", 0.0) or 0.0)
    silence_s = max(0.0, now - prior) if prior > 0 else 0.0

    lap = getattr(entity.tonic, "_last_appraisal_for_noise", None) or {}
    tags = lap.get("tags") or []
    felt = lap.get("felt") or ""
    felt_block = ""
    if tags or felt:
        felt_block = f"tags: {', '.join(str(t) for t in tags if t)}\nfelt: {felt}"
    else:
        felt_block = "(no appraisal captured)"

    pending = doc.meta.get("pending_distillation") or []
    if isinstance(pending, list) and pending:
        felt_block += "\n\nNotes from background distillation:\n" + "\n".join(
            f"- {str(p)}" for p in pending[-8:]
        )

    personality_hint = (entity.config.personality.backstory or "")[:500]
    if not personality_hint.strip():
        personality_hint = f"I am {_self_name(entity)}."

    existing = (doc.document or "").strip() or "No prior relationship — this is the first interaction."

    sources = desktop_sources(entity)
    desktop_mode = getattr(entity, 'desktop', None) is not None
    interaction = json.dumps(sources, ensure_ascii=False) if desktop_mode else _conversation_excerpt(entity, tc)
    if deep_review and episodic_summaries:
        interaction += "\n\n[EPISODIC SNIPPETS INVOLVING THIS PERSON]\n" + "\n".join(
            f"- {s[:400]}" for s in episodic_summaries[:8]
        )

    max_tokens = int(
        getattr(cfg, "deep_review_max_tokens", 1200)
        if deep_review
        else getattr(cfg, "reflection_max_tokens", 800)
    )
    temp = float(getattr(cfg, "reflection_temperature", 0.4) or 0.4)

    prompt = _REFLECT_PROMPT.format(
        entity_name=_self_name(entity),
        person_name=tc.inp.person_name or "someone",
        mode_hint=mode_hint,
        existing=existing[:12000],
        interaction=interaction[:8000],
        felt_block=felt_block,
        body_state=_compact_body_state(entity.tonic),
        silence_s=silence_s,
        personality_hint=personality_hint,
    )
    if desktop_mode:
        prompt += ('\nFor this desktop life, the OBSERVED CONVERSATION section of an existing document '
            'contains source records. Other prose, body state, appraisal and private imagery are interpretations. '
            'Use only the source records in THIS INTERACTION as evidence of what anyone said. '
            'Silence supplies no spoken reply. Return one JSON object with "impressions" (your subjective '
            'first-person interpretation) and "evidence" (a nonempty list of {"source_id": an exact '
            'record id, "quote": an exact substring of that record text}). '
            'The runtime copies observed facts itself. An impression cannot establish a new perception, '
            'conversation, quotation or shared past. Label uncertainty in your interpretation.')

    try:
        res = await entity.client.chat_completion(
            reflex_model,
            [
                {
                    "role": "system",
                    "content": ("You maintain source-attributed relationship impressions. Output the requested JSON only."
                                if desktop_mode else "You maintain private relationship documents in first person. Output prose only."),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=temp,
            max_tokens=max_tokens,
            think=False,
            num_ctx=entity.config.effective_ollama_num_ctx(),
        )
        grounded_events = None
        if desktop_mode:
            new_doc_text, grounded_events = grounded_desktop_document(res.content or '', sources,
                doc.meta.get('observed_conversation', []), metrics=entity.evidence_quote_metrics)
        else:
            new_doc_text = _strip_markdown_fences(res.content or "")
        if len(new_doc_text) < 40:
            log.info("relational_reflection_too_short", person_id=person_id)
            return False
    except Exception as e:
        log.warning("relational_reflection_failed", error=str(e), person_id=person_id)
        return False

    checked_text = new_doc_text.split('[SUBJECTIVE IMPRESSIONS:', 1)[-1] if desktop_mode else new_doc_text
    confused = role_confusion(checked_text, _self_name(entity), tc.inp.person_name or "")
    if confused:
        # The being's own name attached to the other person (issue #18). Keep the previous document.
        log.warning("relational_reflection_role_confusion", person_id=person_id, evidence=confused)
        return False

    if desktop_mode and doc.document and doc.meta.get('evidence_format') != 1:
        doc.meta.setdefault('pre_evidence_document', doc.document)
    doc.document = new_doc_text
    if grounded_events is not None:
        doc.meta['observed_conversation'] = grounded_events
        doc.meta['evidence_format'] = 1
    doc.person_name = tc.inp.person_name or doc.person_name
    doc.last_interaction = now
    doc.last_reflection = now
    if rel_row:
        doc.interaction_count = max(doc.interaction_count, int(rel_row.interaction_count))
    doc.meta["last_reflection_mode"] = "deep" if deep_review else "turn"
    if isinstance(pending, list) and pending:
        doc.meta["pending_distillation"] = []

    if getattr(cfg, "score_derivation", True):
        doc.derived_scores = await derive_scores_from_document(
            entity.client,
            reflex_model,
            doc.document,
            num_ctx=entity.config.effective_ollama_num_ctx(),
        )
    await relational_docs.upsert(conn, doc)
    await relational_docs.sync_derived_to_relationship_row(conn, doc)

    log.info(
        "relational_reflection_applied",
        person_id=person_id,
        deep=deep_review,
        doc_chars=len(doc.document),
    )
    return True


async def run_consolidation_deep_reviews(entity: Any, conn: Any, relational_docs: RelationalDocumentMemory) -> int:
    """Called from memory consolidation — fuller rewrites when enough new material exists."""
    cfg = entity.config.harness.memory.relational
    if not getattr(cfg, "enabled", True) or not getattr(cfg, "deep_review_on_consolidation", True):
        return 0
    min_new = max(1, int(getattr(cfg, "deep_review_min_new_interactions", 3) or 3))

    cur = await conn.execute("SELECT person_id FROM relational_documents")
    rows = await cur.fetchall()
    if not rows:
        return 0

    count = 0
    for (pid,) in rows:
        doc = await relational_docs.get(conn, str(pid))
        if doc is None:
            continue
        baseline = float(doc.meta.get("interaction_count_at_last_deep_review") or 0)
        delta = int(doc.interaction_count) - int(baseline)
        if delta < min_new:
            continue
        episodic_summaries: list[str] = []
        try:
            eps = await entity.episodic.recall_about_person(conn, doc.person_id, limit=6)
            episodic_summaries = [e.summary for e in eps if e.summary]
        except Exception as e:
            log.debug("episodic_for_deep_review_failed", error=str(e))

        tc = SimpleNamespace(
            inp=SimpleNamespace(
                person_id=doc.person_id,
                person_name=doc.person_name,
                text="",
            ),
            reply_text="",
            prior_last_interaction=float(doc.last_interaction or 0.0),
        )
        ok = await run_relational_reflection_after_turn(
            entity,
            tc,
            conn,
            relational_docs=relational_docs,
            deep_review=True,
            episodic_summaries=episodic_summaries,
        )
        if ok:
            d2 = await relational_docs.get(conn, doc.person_id)
            if d2:
                d2.meta["interaction_count_at_last_deep_review"] = int(d2.interaction_count)
                await relational_docs.upsert(conn, d2)
            count += 1
    return count
