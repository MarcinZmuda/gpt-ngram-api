"""
===============================================================================
🔗 CAUSAL TRIPLET EXTRACTOR v1.0
===============================================================================
Wyciąga łańcuchy przyczynowo-skutkowe z treści konkurencji.

Istniejący entity_extractor.py wyciąga FAKTYCZNE relacje:
  sąd — ustala — miejsce pobytu
  leczenie — poprawia — rokowania

Ten moduł dodaje KAUZALNE relacje:
  brak alimentów — powoduje → postępowanie egzekucyjne
  mutacja genu SHOX — prowadzi do → niedobór wzrostu

DLACZEGO:
Google mierzy "explanatory depth" od Helpful Content Update 2023.
Artykuły z łańcuchami przyczynowymi (WHY, nie tylko WHAT) rankują wyżej,
bo odpowiadają na ~30% pytań PAA typu "dlaczego" / "co się stanie jeśli".

Integracja: index.py → po entity_seo → dodaje "causal_triplets" do response

Autor: BRAJEN Team
Data: 2025
===============================================================================
"""

import re
from typing import List, Dict, Optional, Tuple, Set
from collections import defaultdict
from dataclasses import dataclass, asdict


# ================================================================
# 📦 STRUKTURY DANYCH
# ================================================================

@dataclass
class CausalTriplet:
    """Pojedyncza relacja przyczynowo-skutkowa."""
    cause: str
    effect: str
    relation_type: str      # "causes", "prevents", "requires", "enables", "leads_to"
    confidence: float       # 0.0-1.0
    source_sentence: str    # zdanie źródłowe
    is_chain: bool = False  # czy element łańcucha A→B→C

    def to_dict(self) -> Dict:
        return asdict(self)


# ================================================================
# 🔍 WZORCE KAUZALNE (POLSKI)
# ================================================================

# Każdy tuple: (regex, typ_relacji, kierunek)
# kierunek: "forward" = match[0]=cause, match[1]=effect
#           "reverse" = match[0]=effect, match[1]=cause

CAUSAL_PATTERNS_PL = [
    # ═══ BEZPOŚREDNIA PRZYCZYNA ═══
    (r'(.{10,80}?)\s+(?:powoduje|wywołuje|skutkuje|prowadzi do|doprowadza do)\s+(.{10,80})',
     "causes", "forward"),
    (r'(.{10,80}?)\s+(?:jest przyczyną|jest powodem|stanowi przyczynę)\s+(.{10,80})',
     "causes", "forward"),
    (r'(.{10,80}?)\s+(?:może skutkować|może prowadzić do|grozi)\s+(.{10,80})',
     "may_cause", "forward"),

    # ═══ SKUTEK / KONSEKWENCJA ═══
    (r'(?:[Ww] wyniku|[Nn]a skutek|[Ww]skutek|[Ww] rezultacie)\s+(.{10,80}?)\s+(.{10,80})',
     "results_from", "reverse"),
    (r'(.{10,80}?)\s+(?:w efekcie|w konsekwencji|w następstwie)\s+(.{10,80})',
     "causes", "forward"),

    # ═══ PREWENCJA ═══
    (r'(.{10,80}?)\s+(?:zapobiega|chroni przed|przeciwdziała|zmniejsza ryzyko)\s+(.{10,80})',
     "prevents", "forward"),
    (r'(.{10,80}?)\s+(?:minimalizuje|ogranicza|redukuje prawdopodobieństwo)\s+(.{10,80})',
     "prevents", "forward"),

    # ═══ WYMAGANIE / WARUNEK ═══
    (r'(.{10,80}?)\s+(?:wymaga|jest konieczne do|warunkuje|jest niezbędne dla)\s+(.{10,80})',
     "requires", "forward"),
    (r'(?:[Aa]by|[Żż]eby)\s+(.{10,80}?),?\s+(?:trzeba|należy|konieczne jest|niezbędne jest)\s+(.{10,80})',
     "required_for", "reverse"),
    (r'(?:[Ww]arunkiem)\s+(.{10,80}?)\s+(?:jest)\s+(.{10,80})',
     "requires", "reverse"),

    # ═══ UMOŻLIWIENIE ═══
    (r'(.{10,80}?)\s+(?:umożliwia|pozwala na|otwiera drogę do|daje podstawę do)\s+(.{10,80})',
     "enables", "forward"),
    (r'(?:[Dd]zięki)\s+(.{10,80}?)\s+(?:można|możliwe jest|da się)\s+(.{10,80})',
     "enables", "forward"),

    # ═══ PRAWNE (specyficzne) ═══
    (r'(?:[Bb]rak|[Nn]iedopełnienie|[Zz]aniechanie)\s+(.{10,80}?)\s+(?:skutkuje|grozi|prowadzi do)\s+(.{10,80})',
     "omission_causes", "forward"),
    (r'(?:[Zz]łożenie|[Ww]niesienie|[Dd]oręczenie)\s+(.{10,80}?)\s+(?:rozpoczyna|wszczyna|otwiera|uruchamia)\s+(.{10,80})',
     "initiates", "forward"),
    (r'(?:[Pp]rawomocność|[Uu]prawomocnienie)\s+(.{10,80}?)\s+(?:oznacza|skutkuje|powoduje)\s+(.{10,80})',
     "causes", "forward"),

    # ═══ MEDYCZNE (specyficzne) ═══
    (r'(?:[Nn]ieleczon[aey]|[Zz]aniedbani[ea])\s+(.{10,80}?)\s+(?:prowadzi do|grozi|może skutkować)\s+(.{10,80})',
     "untreated_causes", "forward"),
    (r'(.{10,80}?)\s+(?:łagodzi|redukuje|eliminuje)\s+(?:objawy|symptomy|skutki)\s+(.{10,80})',
     "treats", "forward"),
    (r'(?:[Dd]eficyt|[Nn]iedobór)\s+(.{10,80}?)\s+(?:prowadzi do|powoduje|skutkuje)\s+(.{10,80})',
     "deficiency_causes", "forward"),
]


# ================================================================
# 📊 EKSTRAKCJA
# ================================================================

def extract_causal_triplets(
    texts: List[str],
    main_keyword: str,
    max_triplets: int = 15
) -> List[CausalTriplet]:
    """
    Wyciąga kauzalne triplety z treści konkurencji.

    Pipeline:
    1. Regex extraction z CAUSAL_PATTERNS_PL
    2. Filtracja po relevance do main_keyword
    3. Budowanie łańcuchów (A→B + B→C = chain)
    4. Ranking po importance

    Args:
        texts: Lista treści konkurencji
        main_keyword: Główna fraza kluczowa
        max_triplets: Max liczba tripletów

    Returns:
        Lista CausalTriplet posortowana po ważności
    """
    # Połącz treści (z limitem)
    combined = " ".join(t[:30000] for t in texts if t)
    if not combined.strip():
        return []

    raw_triplets = []
    kw_lower = main_keyword.lower()
    kw_words = set(w for w in kw_lower.split() if len(w) > 3)

    for pattern, rel_type, direction in CAUSAL_PATTERNS_PL:
        try:
            matches = re.findall(pattern, combined, re.IGNORECASE)
        except re.error:
            continue

        for match in matches:
            if len(match) < 2:
                continue

            # Wyciągnij cause/effect w zależności od kierunku
            if direction == "forward":
                cause_raw = match[0].strip()
                effect_raw = match[1].strip()
            else:
                cause_raw = match[1].strip()
                effect_raw = match[0].strip()

            # Oczyszczenie
            cause = _clean_triplet_part(cause_raw)
            effect = _clean_triplet_part(effect_raw)

            # Filtracja szumu
            if not cause or not effect:
                continue
            if len(cause) < 5 or len(effect) < 5:
                continue
            if len(cause) > 80 or len(effect) > 80:
                continue
            if cause.lower() == effect.lower():
                continue

            # Scoring — relevance do main_keyword
            cause_lower = cause.lower()
            effect_lower = effect.lower()
            
            relevance = 0.0
            if kw_lower in cause_lower or kw_lower in effect_lower:
                relevance = 0.9
            elif kw_words and any(w in cause_lower or w in effect_lower for w in kw_words):
                relevance = 0.6
            else:
                relevance = 0.3

            raw_triplets.append(CausalTriplet(
                cause=cause,
                effect=effect,
                relation_type=rel_type,
                confidence=relevance,
                source_sentence=f"{cause} → {effect}"
            ))

    # Deduplikacja
    seen = set()
    unique = []
    for t in raw_triplets:
        key = f"{t.cause[:25].lower()}|{t.effect[:25].lower()}"
        if key not in seen:
            seen.add(key)
            unique.append(t)

    # Budowanie łańcuchów
    _build_chains(unique)

    # Sortowanie: chains first, potem confidence
    unique.sort(key=lambda t: (-int(t.is_chain), -t.confidence))

    return unique[:max_triplets]


def _clean_triplet_part(text: str) -> str:
    """Oczyszcza fragment tripletu."""
    # Usuń leading/trailing interpunkcję
    text = text.strip(' ,;:–—-"\'()[]')
    # Usuń wielokrotne spacje
    text = re.sub(r'\s+', ' ', text)
    # Obetnij do pierwszego zdania (jeśli złapaliśmy za dużo)
    if '.' in text:
        text = text.split('.')[0]
    return text.strip()


def _build_chains(triplets: List[CausalTriplet]) -> None:
    """
    Oznacza triplety będące częścią łańcuchów.
    Jeśli A→B i B→C istnieją, oba dostają is_chain=True.
    """
    # Zbuduj indeks: effect → triplet
    effect_index = defaultdict(list)
    for t in triplets:
        # Kluczem są pierwsze 3 słowa efektu (przybliżone matchowanie)
        effect_key = " ".join(t.effect.lower().split()[:3])
        effect_index[effect_key].append(t)

    # Sprawdź: czy cause jakiegoś tripletu jest effectem innego?
    for t in triplets:
        cause_key = " ".join(t.cause.lower().split()[:3])
        if cause_key in effect_index:
            t.is_chain = True
            for linked in effect_index[cause_key]:
                linked.is_chain = True


# ================================================================
# 📝 FORMATOWANIE DLA AGENTA
# ================================================================

def format_causal_for_agent(
    triplets: List[CausalTriplet],
    main_keyword: str
) -> str:
    """Formatuje kauzalne triplety jako instrukcję dla agenta GPT."""
    if not triplets:
        return ""

    lines = [
        f"🔗 ŁAŃCUCHY PRZYCZYNOWO-SKUTKOWE — znalezione w top 10 dla \"{main_keyword}\":",
        "Wpleć te relacje w artykuł (wyjaśniaj DLACZEGO, nie tylko CO):",
        ""
    ]

    # Łańcuchy (najcenniejsze)
    chains = [t for t in triplets if t.is_chain]
    singles = [t for t in triplets if not t.is_chain]

    if chains:
        lines.append("⛓️ ŁAŃCUCHY (A→B→C — najcenniejsze):")
        for t in chains[:5]:
            rel_label = _relation_label(t.relation_type)
            lines.append(f"  {t.cause} {rel_label} {t.effect}")
        lines.append("")

    if singles:
        lines.append("➡️ RELACJE KAUZALNE:")
        for t in singles[:8]:
            rel_label = _relation_label(t.relation_type)
            lines.append(f"  {t.cause} {rel_label} {t.effect}")
        lines.append("")

    lines.append(
        "💡 WSKAZÓWKA: Użyj tych relacji, żeby artykuł odpowiadał na pytania "
        "\"dlaczego?\", \"co się stanie jeśli?\", \"jakie są konsekwencje?\". "
        "Google to nagradza od Helpful Content Update."
    )

    return "\n".join(lines)


def _relation_label(rel_type: str) -> str:
    """Zamienia typ relacji na czytelną etykietę."""
    labels = {
        "causes": "→ powoduje →",
        "may_cause": "→ może powodować →",
        "prevents": "→ zapobiega →",
        "requires": "→ wymaga →",
        "enables": "→ umożliwia →",
        "results_from": "← wynika z ←",
        "required_for": "→ jest wymagane do →",
        "omission_causes": "→ [brak] skutkuje →",
        "initiates": "→ rozpoczyna →",
        "untreated_causes": "→ [nieleczone] prowadzi do →",
        "treats": "→ łagodzi →",
        "deficiency_causes": "→ [niedobór] powoduje →",
        "leads_to": "→ prowadzi do →",
    }
    return labels.get(rel_type, "→")


# ================================================================
# EXPORTS
# ================================================================

__all__ = [
    'extract_causal_triplets',
    'format_causal_for_agent',
    'CausalTriplet',
]
