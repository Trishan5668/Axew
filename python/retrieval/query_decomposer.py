"""Decompose natural-language prompts into structured ParsedQuery."""

from __future__ import annotations

import re
from typing import List, Optional

from python.enrichment.monetary_parser import MonetaryParser
from python.retrieval.event_matcher import ParsedQuery
from python.retrieval.types import DecomposedQuery

ACTION_TAXONOMY = {
    "TRANSFER": ["give", "hand", "pass", "present", "pay"],
    "RECEIVE": ["take", "accept", "receive"],
    "LAUGH": ["laugh", "chuckle", "giggle"],
    "APPLAUD": ["applaud", "clap", "cheer"],
    "SPEAK": ["say", "tell", "mention", "deny", "admit", "ask"],
}

SPEAKER_ROLE_PATTERNS = [
    (re.compile(r"\binterviewer\b", re.I), "interviewer"),
    (re.compile(r"\bhost\b", re.I), "interviewer"),
    (re.compile(r"\bvijay\s+mallya\b", re.I), "Vijay Mallya"),
]

_nlp = None


class QueryDecomposer:
    """Entity, action, topic, and paraphrase decomposition for transcript search."""

    MONEY_RE = re.compile(r"\b\d+\s*(?:rupees?|rs\.?|₹|\$|dollars?|lakhs?|crores?)\b", re.I)
    HINDI_TOKENS = {"yeh", "lo", "hai", "ko", "diya", "tha", "kya", "aur"}
    ACTION_TERMS = {
        "give": ["give", "gives", "gave", "hand over", "transfer", "pay", "payment", "here take", "yeh lo"],
        "talk": ["talk", "talks", "discuss", "mention", "explain", "says", "asks"],
        "emotion": ["emotional", "cry", "upset", "serious", "heartfelt"],
        "humor": ["funny", "joke", "laugh", "humor", "banter"],
        "debate": ["debate", "argue", "disagree", "controversy"],
    }
    CONCEPT_TERMS = {
        "money/finance": ["money", "rupee", "rs", "payment", "debt", "funding", "finance", "bank", "loan"],
        "controversy": ["controversy", "scam", "fraud", "case", "accuse"],
        "emotional": ["emotional", "cry", "heartfelt", "sad"],
        "joke/humor": ["funny", "joke", "laugh", "humor"],
        "personal story": ["story", "journey", "childhood", "life"],
        "advice": ["advice", "suggest", "recommend", "lesson"],
        "opening": ["intro", "opening", "beginning", "start"],
    }

    def __init__(self) -> None:
        self._paraphrase_cache: dict[str, list[str]] = {}

    def decompose(self, raw_query: str) -> DecomposedQuery:
        query = (raw_query or "").strip()
        lower = query.lower()
        entities = self._extract_entities(query)
        for pat, name in SPEAKER_ROLE_PATTERNS:
            if pat.search(query) and name not in entities:
                entities.append(name)

        actions = self._extract_actions(lower)
        concepts = [
            label for label, terms in self.CONCEPT_TERMS.items()
            if any(re.search(rf"\b{re.escape(t)}", lower) for t in terms)
        ]
        monetary_refs = self._extract_money(query)
        paraphrases = self._generate_paraphrases(query, entities, monetary_refs)
        lang_hint = self._lang_hint(query)

        terms: list[str] = [query]
        terms.extend(entities)
        terms.extend(actions)
        terms.extend(concepts)
        terms.extend(monetary_refs)
        terms.extend(paraphrases)
        if lang_hint == "hinglish":
            terms.extend(self._hinglish_variants(lower))

        search_terms = self._dedupe([t for t in terms if t and t.strip()])
        return DecomposedQuery(
            original=query,
            entities=entities,
            actions=actions,
            semantic_concepts=concepts,
            monetary_refs=monetary_refs,
            paraphrases=paraphrases,
            search_terms=search_terms,
            lang_hint=lang_hint,
            entity_anchored=bool(entities),
        )

    def _extract_entities(self, query: str) -> list[str]:
        entities: list[str] = []
        nlp = self._get_nlp()
        if nlp is not None:
            try:
                for ent in nlp(query).ents:
                    if ent.label_ in {"PERSON", "ORG", "MONEY", "GPE"}:
                        entities.append(ent.text.strip())
            except Exception:
                pass
        for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", query):
            entities.append(m.group(1))
        return self._dedupe(entities)

    def _extract_actions(self, lower: str) -> list[str]:
        actions: list[str] = []
        for variants in self.ACTION_TERMS.values():
            if any(re.search(rf"\b{re.escape(v)}", lower) for v in variants):
                actions.extend(variants[:4])
        return self._dedupe(actions)

    def _extract_money(self, query: str) -> list[str]:
        refs = [m.group(0).strip() for m in self.MONEY_RE.finditer(query)]
        if refs:
            refs.extend(["give money", "hand over", "payment", "transfer", "here take", "yeh lo"])
        return self._dedupe(refs)

    def _generate_paraphrases(self, query: str, entities: list[str], money: list[str]) -> list[str]:
        import hashlib

        key = hashlib.sha256(query.lower().encode("utf-8")).hexdigest()
        if key in self._paraphrase_cache:
            return self._paraphrase_cache[key]
        entity = entities[0] if entities else "the guest"
        amount = money[0] if money else ""
        base = [
            f"{entity} moment",
            f"where {entity} talks about this",
            query.replace("where ", "").replace("part where ", ""),
            f"{entity} receives {amount}".strip(),
            f"interviewer pays {entity} {amount}".strip(),
        ]
        if amount:
            base.extend([f"handing {amount} to {entity}", f"{amount} scene", f"{amount} yeh lo moment"])
        paraphrases = self._dedupe([p for p in base if p and p.lower() != query.lower()])[:5]
        self._paraphrase_cache[key] = paraphrases
        return paraphrases

    def _lang_hint(self, query: str) -> str:
        lower_tokens = set(re.findall(r"\b\w+\b", query.lower()))
        if re.search(r"[\u0900-\u097F]", query) or lower_tokens & self.HINDI_TOKENS:
            return "hinglish"
        return "en"

    def _hinglish_variants(self, lower: str) -> list[str]:
        variants = []
        mapping = {
            "yeh lo": "here take",
            "diya": "gave",
            "paisa": "money",
            "paise": "money",
            "rupaye": "rupees",
            "kya": "what",
            "hai": "is",
            "aur": "and",
        }
        variants.append(lower)
        translated = lower
        for src, dst in mapping.items():
            if src in translated:
                translated = translated.replace(src, dst)
                variants.append(dst)
        variants.append(translated)
        return self._dedupe(variants)

    def _dedupe(self, values: list[str]) -> list[str]:
        seen = set()
        out = []
        for value in values:
            cleaned = value.strip(" ,.")
            key = cleaned.lower()
            if cleaned and key not in seen:
                out.append(cleaned)
                seen.add(key)
        return out

    def _get_nlp(self):
        global _nlp
        if _nlp is None:
            try:
                import spacy
                try:
                    _nlp = spacy.load("en_core_web_sm")
                except OSError:
                    _nlp = False
            except ImportError:
                _nlp = False
        return _nlp if _nlp is not False else None


class QueryParser:
    def __init__(self) -> None:
        self.monetary_parser = MonetaryParser()

    def parse(self, prompt: str) -> ParsedQuery:
        intent_action = self._intent_action(prompt)
        entities: List[str] = []
        for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", prompt):
            entities.append(m.group(1))
        for pat, name in [
            (r"vijay\s+mallya", "Vijay Mallya"),
            (r"kingfisher", "Kingfisher Airlines"),
            (r"\bsbi\b", "SBI"),
            (r"\bpnb\b", "PNB"),
        ]:
            if re.search(pat, prompt, re.I) and name not in entities:
                entities.append(name)

        subject, verb, obj, recipient = self._parse_structure(prompt)

        actions: List[str] = []
        lower = prompt.lower()
        for atype, verbs in ACTION_TAXONOMY.items():
            if any(re.search(rf"\b{re.escape(v)}", lower) for v in verbs):
                actions.append(atype)

        monetary = None
        parsed_money = self.monetary_parser.parse_text(prompt)
        if parsed_money:
            amount, currency = parsed_money[0]
            monetary = {"amount": amount, "currency": currency}
            if not obj:
                obj = self._extract_money_text(prompt) or f"{amount:g} {currency}"
        else:
            m = re.search(r"\b(\d+)\s*(?:rupee|rs|â‚¹)", prompt, re.I)
            if m:
                monetary = {"amount": float(m.group(1)), "currency": "INR"}
                if not obj:
                    obj = m.group(0)

        speaker_roles = [label for pat, label in SPEAKER_ROLE_PATTERNS if pat.search(prompt)]
        if subject and subject.lower() == "interviewer" and "interviewer" not in speaker_roles:
            speaker_roles.append("interviewer")
        if subject and subject not in entities and subject[:1].isupper():
            entities.append(subject)
        if recipient and recipient not in entities and recipient[:1].isupper():
            entities.append(recipient)

        from python.retrieval.temporal_reasoner import TemporalReasoner

        temporals = TemporalReasoner().extract_modifiers(prompt)

        return ParsedQuery(
            intent_action=intent_action,
            subject=subject,
            verb=verb,
            object=obj,
            recipient=recipient,
            entities=entities,
            action_types=actions,
            monetary=monetary,
            speaker_roles=speaker_roles,
            temporal_modifiers=temporals,
            raw_query=prompt,
        )

    def _parse_structure(self, prompt: str) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        nlp = self._get_nlp()
        if nlp is not None:
            try:
                doc = nlp(prompt)
                target = None
                known_verbs = {verb for verbs in ACTION_TAXONOMY.values() for verb in verbs}
                for token in doc:
                    if token.lemma_.lower() in known_verbs:
                        target = token
                        break
                if target is None:
                    target = next((token for token in doc if token.pos_ == "VERB"), None)

                if target is not None:
                    subject = None
                    obj = None
                    recipient = None
                    for child in target.children:
                        if child.dep_ in {"nsubj", "nsubjpass"}:
                            subject = self._expand_span(child)
                        elif child.dep_ in {"dobj", "obj", "attr", "oprd"}:
                            obj = self._expand_span(child)
                        elif child.dep_ == "iobj":
                            recipient = self._expand_span(child)
                        elif child.dep_ == "prep" and child.lemma_.lower() in {"to", "for"}:
                            for grandchild in child.children:
                                if grandchild.dep_ == "pobj":
                                    recipient = self._expand_span(grandchild)
                    return (
                        self._normalize_subject(subject),
                        target.lemma_.lower(),
                        obj.strip(" ,.") if obj else None,
                        self._normalize_subject(recipient),
                    )
            except Exception:
                pass

        transfer = re.search(
            r"(?:where|when|part where|part when|only the part where|keep only the part where)?\s*"
            r"(?P<subject>interviewer|host|[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)?\s*"
            r"(?P<verb>gives?|gave|hands?|handed|pays?|paid|passes?|passed|laughs?|laughed|speaks?|spoke|mentions?|mentioned)\s*"
            r"(?P<object>.+?)?"
            r"(?:\s+to\s+(?P<recipient>[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*|him|her))?$",
            prompt,
            re.IGNORECASE,
        )
        if transfer:
            return (
                self._normalize_subject(transfer.group("subject")),
                transfer.group("verb").lower() if transfer.group("verb") else None,
                transfer.group("object").strip(" ,.") if transfer.group("object") else None,
                self._normalize_subject(transfer.group("recipient")),
            )
        return None, None, None, None

    def _extract_money_text(self, prompt: str) -> Optional[str]:
        match = re.search(
            r"\b(\d[\d,]*(?:\.\d+)?)\s*(rupees?|rs\.?|â‚¹|inr|dollars?|usd|pounds?|gbp)\b",
            prompt,
            re.IGNORECASE,
        )
        return match.group(0) if match else None

    def _intent_action(self, prompt: str) -> str:
        lower = prompt.lower()
        if re.search(r"keep\s+only|only\s+the\s+part|show\s+only|just\s+the", lower):
            return "keep_segment"
        if re.search(r"\bextract\b|\bisolate\b", lower):
            return "extract_clip"
        if re.search(r"\bremove\b|\bdelete\b|\bcut\s+out\b", lower):
            return "remove_segment"
        return "keep_segment"

    def _expand_span(self, token) -> str:
        return " ".join(t.text for t in token.subtree)

    def _normalize_subject(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        cleaned = value.strip(" ,.")
        if cleaned.lower() == "host":
            return "interviewer"
        return cleaned

    def _get_nlp(self):
        global _nlp
        if _nlp is None:
            try:
                import spacy

                try:
                    _nlp = spacy.load("en_core_web_sm")
                except OSError:
                    _nlp = False
            except ImportError:
                _nlp = False
        return _nlp if _nlp is not False else None
