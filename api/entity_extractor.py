"""
===============================================================================
🧠 ENTITY EXTRACTOR v1.0 - Entity SEO dla GPT N-gram API
===============================================================================
Rozszerza S1 o:
1. Entity Extraction (spaCy NER)
2. Topical Coverage Map
3. Entity Relationships (rule-based)

Autor: BRAJEN Team
Data: 2025-01
===============================================================================
"""

import re
import math
from collections import Counter, defaultdict
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

# 🆕 v1.1: CSS garbage filter — prevent spaCy NER from picking up CSS pseudo-selectors
_CSS_ENTITY_BLACKLIST = {
    "where", "not", "root", "before", "after", "hover", "focus", "active",
    "first", "last", "nth", "checked", "disabled", "visited", "link",
    "inline", "block", "flex", "grid", "none", "auto", "inherit",
    "bold", "normal", "italic", "center", "wrap", "hidden", "visible",
    "relative", "absolute", "fixed", "static", "transparent", "solid",
    "pointer", "default", "button", "input", "label", "footer", "header",
    "widget", "sidebar", "container", "wrapper", "content", "section",
}

def _is_entity_garbage(text):
    """Check if entity text is CSS/JS artifact."""
    if not text or len(text) < 2:
        return True
    t = text.strip().lower()
    if t in _CSS_ENTITY_BLACKLIST:
        return True
    if re.search(r'[{};:.]|webkit|moz-|flex-|align-|data-', t, re.IGNORECASE):
        return True
    # High special char ratio
    special = sum(1 for c in t if c in '{}:;()[]<>=#.@_')
    if len(t) > 0 and special / len(t) > 0.2:
        return True
    return False

# ================================================================
# 📊 KONFIGURACJA
# ================================================================

# Mapowanie etykiet spaCy PL na czytelne typy
SPACY_LABEL_MAP = {
    "persName": "PERSON",
    "orgName": "ORGANIZATION",
    "placeName": "LOCATION",
    "geogName": "LOCATION",
    "date": "DATE",
    "time": "TIME",
    # spaCy pl_core_news labels
    "PER": "PERSON",
    "ORG": "ORGANIZATION",
    "LOC": "LOCATION",
    "GPE": "LOCATION",
    "DATE": "DATE",
    "TIME": "TIME",
    "MONEY": "MONEY",
    "PERCENT": "PERCENT",
}

# Typy encji ważne dla SEO (priorytetowe)
PRIORITY_ENTITY_TYPES = ["PERSON", "ORGANIZATION", "LOCATION", "DATE"]

# Wzorce do wykrywania relacji (Subject-Verb-Object)
# 🔧 v32.5: Rozszerzone wzorce - więcej czasowników, małe litery też
RELATION_PATTERNS = [
    # Podstawowe wzorce z wielkiej litery
    (r'(\b[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ]?[a-ząćęłńóśźż]+)?)\s+(oferuje|zapewnia|umożliwia|pozwala|daje|gwarantuje)\s+([a-ząćęłńóśźż\s]+)', "offers"),
    (r'(\b[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+(?:\s+[a-ząćęłńóśźż]+)?)\s+(wymaga|potrzebuje|obliguje)\s+([a-ząćęłńóśźż\s]+)', "requires"),
    (r'(\b[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)\s+(wpływa na|oddziałuje na|determinuje)\s+([a-ząćęłńóśźż\s]+)', "affects"),
    (r'(\b[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)\s+(reguluje|kontroluje|nadzoruje)\s+([a-ząćęłńóśźż\s]+)', "regulates"),
    
    # 🆕 Wzorce z małej litery (częste w tekstach SEO)
    (r'(\b[a-ząćęłńóśźż]+(?:\s+[a-ząćęłńóśźż]+)?)\s+(wspiera|wspomaga|pomaga|ułatwia)\s+([a-ząćęłńóśźż\s]+)', "supports"),
    (r'(\b[a-ząćęłńóśźż]+(?:\s+[a-ząćęłńóśźż]+)?)\s+(chroni|zabezpiecza|ochrania)\s+([a-ząćęłńóśźż\s]+)', "protects"),
    (r'(\b[a-ząćęłńóśźż]+(?:\s+[a-ząćęłńóśźż]+)?)\s+(poprawia|ulepsza|zwiększa|podnosi)\s+([a-ząćęłńóśźż\s]+)', "improves"),
    (r'(\b[a-ząćęłńóśźż]+(?:\s+[a-ząćęłńóśźż]+)?)\s+(zawiera|posiada|ma w składzie)\s+([a-ząćęłńóśźż\s]+)', "contains"),
    (r'(\b[a-ząćęłńóśźż]+(?:\s+[a-ząćęłńóśźż]+)?)\s+(redukuje|zmniejsza|obniża|ogranicza)\s+([a-ząćęłńóśźż\s]+)', "reduces"),
    (r'(\b[a-ząćęłńóśźż]+(?:\s+[a-ząćęłńóśźż]+)?)\s+(powoduje|wywołuje|skutkuje|prowadzi do)\s+([a-ząćęłńóśźż\s]+)', "causes"),
    
    # 🆕 Wzorce specyficzne dla branż
    (r'(\b[a-ząćęłńóśźż]+(?:\s+[a-ząćęłńóśźż]+)?)\s+(leczy|łagodzi|eliminuje)\s+([a-ząćęłńóśźż\s]+)', "treats"),  # medycyna
    (r'(\b[a-ząćęłńóśźż]+(?:\s+[a-ząćęłńóśźż]+)?)\s+(kosztuje|wymaga opłaty|wyceniano na)\s+([a-ząćęłńóśźż\s0-9]+)', "costs"),  # finanse
    (r'(\b[a-ząćęłńóśźż]+(?:\s+[a-ząćęłńóśźż]+)?)\s+(trwa|zajmuje|wymaga czasu)\s+([a-ząćęłńóśźż\s0-9]+)', "duration"),  # czas
]


# ================================================================
# 📦 STRUKTURY DANYCH
# ================================================================

@dataclass
class ExtractedEntity:
    """Encja wyekstrahowana z tekstu."""
    text: str
    type: str
    frequency: int = 1
    sources_count: int = 1
    importance: float = 0.5
    contexts: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "text": self.text,
            "type": self.type,
            "frequency": self.frequency,
            "sources_count": self.sources_count,
            "importance": round(self.importance, 3),
            "sample_context": self.contexts[0] if self.contexts else ""
        }


@dataclass
class EntityRelationship:
    """Relacja między encjami."""
    subject: str
    verb: str
    object: str
    relation_type: str
    frequency: int = 1
    
    def to_dict(self) -> Dict:
        return {
            "subject": self.subject,
            "verb": self.verb,
            "object": self.object,
            "type": self.relation_type,
            "frequency": self.frequency
        }


@dataclass
class TopicalCoverage:
    """Pokrycie tematyczne."""
    subtopic: str
    covered_by: int
    total_sources: int
    priority: str
    sample_h2: str = ""
    
    def to_dict(self) -> Dict:
        coverage_pct = self.covered_by / self.total_sources if self.total_sources > 0 else 0
        return {
            "subtopic": self.subtopic,
            "covered_by": f"{self.covered_by}/{self.total_sources}",
            "coverage_percent": round(coverage_pct * 100),
            "priority": self.priority,
            "sample_h2": self.sample_h2
        }


# ================================================================
# 🔧 FUNKCJE POMOCNICZE
# ================================================================

def normalize_entity_type(spacy_label: str) -> str:
    """Normalizuje etykietę spaCy do czytelnego typu."""
    return SPACY_LABEL_MAP.get(spacy_label, spacy_label)


def get_context(text: str, start: int, end: int, window: int = 50) -> str:
    """Wyciąga kontekst wokół encji."""
    ctx_start = max(0, start - window)
    ctx_end = min(len(text), end + window)
    context = text[ctx_start:ctx_end].strip()
    
    if ctx_start > 0:
        context = "..." + context
    if ctx_end < len(text):
        context = context + "..."
    
    return context


def calculate_entity_importance(entity: ExtractedEntity, total_sources: int) -> float:
    """Oblicza ważność encji dla SEO."""
    score = 0.3
    
    if entity.type in PRIORITY_ENTITY_TYPES:
        score += 0.2
    
    freq_score = min(0.25, math.log(entity.frequency + 1) * 0.08)
    score += freq_score
    
    if total_sources > 0:
        distribution = entity.sources_count / total_sources
        score += distribution * 0.25
    
    return min(1.0, score)


# ================================================================
# 🧠 GŁÓWNE FUNKCJE EKSTRAKCJI
# ================================================================

def extract_entities(
    nlp,
    texts: List[str],
    urls: List[str] = None
) -> List[ExtractedEntity]:
    """
    Wyciąga encje z listy tekstów konkurencji.
    """
    if not texts:
        return []
    
    urls = urls or [f"source_{i}" for i in range(len(texts))]
    
    entity_data = defaultdict(lambda: {
        "type": None,
        "frequency": 0,
        "sources": set(),
        "contexts": []
    })
    
    for idx, text in enumerate(texts):
        if not text or len(text) < 100:
            continue
        
        text_sample = text[:50000]
        
        try:
            doc = nlp(text_sample)
            
            for ent in doc.ents:
                ent_text = ent.text.strip()
                
                if len(ent_text) < 2 or len(ent_text) > 100:
                    continue
                
                if ent_text.isdigit():
                    continue
                
                # 🆕 v1.1: Skip CSS garbage entities
                if _is_entity_garbage(ent_text):
                    continue
                
                key = ent_text.lower()
                
                if entity_data[key]["type"] is None:
                    entity_data[key]["original_text"] = ent_text
                
                entity_data[key]["type"] = normalize_entity_type(ent.label_)
                entity_data[key]["frequency"] += 1
                entity_data[key]["sources"].add(urls[idx])
                
                if len(entity_data[key]["contexts"]) < 3:
                    ctx = get_context(text_sample, ent.start_char, ent.end_char)
                    if ctx not in entity_data[key]["contexts"]:
                        entity_data[key]["contexts"].append(ctx)
        
        except Exception as e:
            print(f"[ENTITY] ⚠️ Error processing text {idx}: {e}")
            continue
    
    entities = []
    total_sources = len(texts)
    
    for key, data in entity_data.items():
        entity = ExtractedEntity(
            text=data.get("original_text", key),
            type=data["type"],
            frequency=data["frequency"],
            sources_count=len(data["sources"]),
            contexts=data["contexts"]
        )
        entity.importance = calculate_entity_importance(entity, total_sources)
        entities.append(entity)
    
    entities.sort(key=lambda x: x.importance, reverse=True)
    
    return entities[:50]


def extract_entity_relationships(
    texts: List[str],
    entities: List[ExtractedEntity]
) -> List[EntityRelationship]:
    """Wykrywa relacje między encjami (rule-based)."""
    if not texts or not entities:
        return []
    
    combined_text = " ".join(texts)[:100000]
    entity_names = {e.text.lower() for e in entities}
    
    # 🆕 v32.6: Dodaj też główne słowa z tekstu (nie tylko NER entities)
    # Wyciągnij częste rzeczowniki z tekstu jako "pseudo-entities"
    common_nouns = set()
    words = combined_text.lower().split()
    word_freq = {}
    for w in words:
        if len(w) > 4:  # tylko słowa > 4 znaków
            word_freq[w] = word_freq.get(w, 0) + 1
    # Top 50 najczęstszych słów
    for word, freq in sorted(word_freq.items(), key=lambda x: -x[1])[:50]:
        if freq >= 2:
            common_nouns.add(word)
    
    # Połącz NER entities z common nouns
    all_relevant_terms = entity_names | common_nouns
    print(f"[ENTITY] 📊 Relevant terms for relationships: {len(entity_names)} NER + {len(common_nouns)} common = {len(all_relevant_terms)}")
    
    relationships = defaultdict(lambda: {"frequency": 0})
    
    for pattern, rel_type in RELATION_PATTERNS:
        matches = re.findall(pattern, combined_text, re.IGNORECASE)
        
        for match in matches:
            if len(match) >= 3:
                subject = match[0].strip()[:50]
                verb = match[1].strip()
                obj = match[2].strip()[:50]
                
                subj_lower = subject.lower()
                obj_lower = obj.lower()
                
                # 🔧 v32.6 FIX: Używaj all_relevant_terms (NER + common nouns)
                is_relevant = (
                    subj_lower in all_relevant_terms or 
                    obj_lower in all_relevant_terms or
                    any(e in subj_lower for e in all_relevant_terms if len(e) > 4) or
                    any(e in obj_lower for e in all_relevant_terms if len(e) > 4)
                )
                
                if is_relevant and len(subject) > 2 and len(obj) > 2:
                    key = f"{subject}|{verb}|{obj}"
                    relationships[key]["subject"] = subject
                    relationships[key]["verb"] = verb
                    relationships[key]["object"] = obj
                    relationships[key]["type"] = rel_type
                    relationships[key]["frequency"] += 1
    
    result = []
    for key, data in relationships.items():
        result.append(EntityRelationship(
            subject=data["subject"],
            verb=data["verb"],
            object=data["object"],
            relation_type=data["type"],
            frequency=data["frequency"]
        ))
    
    result.sort(key=lambda x: x.frequency, reverse=True)
    
    return result[:20]


def analyze_topical_coverage(
    h2_patterns: List[str],
    main_keyword: str,
    total_sources: int
) -> List[TopicalCoverage]:
    """Analizuje pokrycie tematyczne na podstawie H2 konkurencji."""
    if not h2_patterns:
        return []
    
    topic_groups = defaultdict(lambda: {"count": 0, "examples": []})
    
    for h2 in h2_patterns:
        h2_clean = h2.lower().strip()
        if not h2_clean or len(h2_clean) < 5:
            continue
        
        words = re.findall(r'\b[a-ząćęłńóśźż]{3,}\b', h2_clean)
        if not words:
            continue
        
        key_words = words[:3]
        key = " ".join(key_words)
        
        topic_groups[key]["count"] += 1
        if len(topic_groups[key]["examples"]) < 2:
            topic_groups[key]["examples"].append(h2)
    
    coverage_list = []
    
    for topic_key, data in topic_groups.items():
        count = data["count"]
        
        if total_sources > 0:
            coverage_ratio = count / total_sources
        else:
            coverage_ratio = 0
        
        if coverage_ratio >= 0.7:
            priority = "MUST"
        elif coverage_ratio >= 0.5:
            priority = "HIGH"
        elif coverage_ratio >= 0.3:
            priority = "MEDIUM"
        else:
            priority = "LOW"
        
        sample = data["examples"][0] if data["examples"] else topic_key
        
        coverage_list.append(TopicalCoverage(
            subtopic=topic_key,
            covered_by=count,
            total_sources=total_sources,
            priority=priority,
            sample_h2=sample
        ))
    
    priority_order = {"MUST": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    coverage_list.sort(key=lambda x: (priority_order.get(x.priority, 4), -x.covered_by))
    
    return coverage_list[:15]


# ================================================================
# 🎯 GŁÓWNA FUNKCJA
# ================================================================

def perform_entity_seo_analysis(
    nlp,
    sources: List[Dict],
    main_keyword: str,
    h2_patterns: List[str] = None
) -> Dict[str, Any]:
    """Wykonuje analizę Entity SEO."""
    
    # 🆕 v2.0: Import topical entities
    try:
        try:
            from .topical_entity_extractor import extract_topical_entities, generate_topical_summary
        except ImportError:
            from topical_entity_extractor import extract_topical_entities, generate_topical_summary
        TOPICAL_ENABLED = True
        print("[ENTITY] ✅ Topical entity extractor loaded")
    except ImportError as e:
        TOPICAL_ENABLED = False
        print(f"[ENTITY] ⚠️ Topical entity extractor not available: {e}")
    
    texts = [src.get("content", "") for src in sources if src.get("content")]
    urls = [src.get("url", f"source_{i}") for i, src in enumerate(sources)]
    
    if not texts:
        return {
            "entities": [],
            "entity_relationships": [],
            "topical_coverage": [],
            "entity_seo_summary": {
                "status": "NO_DATA",
                "message": "Brak tekstów do analizy"
            }
        }
    
    print(f"[ENTITY] 🔍 Analyzing {len(texts)} sources for: {main_keyword}")
    
    # 1️⃣ Ekstrakcja encji
    entities = extract_entities(nlp, texts, urls)
    print(f"[ENTITY] ✅ Extracted {len(entities)} entities")
    
    # 2️⃣ Relacje między encjami
    relationships = extract_entity_relationships(texts, entities)
    print(f"[ENTITY] ✅ Found {len(relationships)} relationships")
    
    # 3️⃣ Pokrycie tematyczne
    h2_list = h2_patterns or []
    for src in sources:
        h2_list.extend(src.get("h2_structure", []))
    
    topical = analyze_topical_coverage(h2_list, main_keyword, len(sources))
    print(f"[ENTITY] ✅ Found {len(topical)} topic clusters")
    
    # 4️⃣ Podsumowanie
    persons = [e for e in entities if e.type == "PERSON"]
    orgs = [e for e in entities if e.type == "ORGANIZATION"]
    locations = [e for e in entities if e.type == "LOCATION"]
    must_topics = [t for t in topical if t.priority == "MUST"]
    
    # 5️⃣ 🆕 v2.0: Topical/Concept Entities
    topical_entities_data = {}
    concept_entities_list = []
    if TOPICAL_ENABLED:
        try:
            concept_entities = extract_topical_entities(
                nlp=nlp,
                texts=texts,
                urls=urls,
                main_keyword=main_keyword,
                max_entities=30,
                min_frequency=2,
                min_sources=1,
            )
            topical_entities_data = generate_topical_summary(
                entities=concept_entities,
                main_keyword=main_keyword,
            )
            concept_entities_list = [e.to_dict() for e in concept_entities]
            print(f"[ENTITY] ✅ Topical entities: {len(concept_entities)} concepts found")
        except Exception as e:
            print(f"[ENTITY] ⚠️ Topical entity extraction error: {e}")
            topical_entities_data = {"status": "ERROR", "error": str(e)}
    
    summary = {
        "status": "OK",
        "total_entities": len(entities),
        "total_concepts": len(concept_entities_list),
        "entity_breakdown": {
            "persons": len(persons),
            "organizations": len(orgs),
            "locations": len(locations),
            "concepts": len(concept_entities_list),
            "other": len(entities) - len(persons) - len(orgs) - len(locations)
        },
        "top_entities": [e.text for e in entities[:5]],
        "top_concepts": [c.get("text", "") for c in concept_entities_list[:5]],
        "must_cover_topics": [t.subtopic for t in must_topics[:5]],
        "relationships_found": len(relationships)
    }
    
    return {
        "entities": [e.to_dict() for e in entities],
        "concept_entities": concept_entities_list,
        "topical_summary": topical_entities_data,
        "entity_relationships": [r.to_dict() for r in relationships],
        "topical_coverage": [t.to_dict() for t in topical],
        "entity_seo_summary": summary
    }
