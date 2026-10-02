import re
import unicodedata
from typing import Optional

try:
    import khmernormalizer
    HAS_KHMERNORMALIZER = True
except ImportError:
    HAS_KHMERNORMALIZER = False

try:
    from khmernltk import word_tokenize
    HAS_KHMERNLTK = True
except ImportError:
    HAS_KHMERNLTK = False


KHMER_DIGIT_MAP = {
    '០': '0',
    '១': '1',
    '២': '2',
    '៣': '3',
    '៤': '4',
    '៥': '5',
    '៦': '6',
    '៧': '7',
    '៨': '8',
    '៩': '9',
}


def normalize_khmer_digits(text: str) -> str:
    """Convert Khmer numerals (០-៩) to standard ASCII digits (0-9)."""
    return "".join(KHMER_DIGIT_MAP.get(char, char) for char in text)


def clean_khmer_text(text: str) -> str:
    """
    Orthographic normalization pipeline for mixed Khmer and English commercial text:
    1. Unicode NFKC standardization
    2. Zero-width spaces stripping (\\u200b, \\u200c, \\u200d)
    3. Reordering misplaced subscript consonants & vowels via khmernormalizer
    4. Normalizing Khmer digits to ASCII digits
    5. Duplicate whitespace stripping
    """
    if not text:
        return ""

    # 1. Unicode NFKC
    normalized = unicodedata.normalize("NFKC", text)

    # 2. Strip zero-width spaces
    normalized = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", normalized)

    # 3. Canonical reordering via khmernormalizer if installed
    if HAS_KHMERNORMALIZER:
        try:
            normalized = khmernormalizer.normalize(normalized)
        except Exception:
            pass

    # 4. Digits normalization
    normalized = normalize_khmer_digits(normalized)

    # 5. Clean whitespace
    normalized = re.sub(r"[ \t]+", " ", normalized)
    return normalized.strip()


def segment_khmer_text(text: str) -> str:
    """
    Orthographic normalization + word segmentation for Khmer-English text:
    1. Apply clean_khmer_text (NFKC, ZWSP strip, canonical reorder, digit norm)
    2. Segment continuous Khmer words into space-separated tokens via khmer-nltk,
       strictly preserving line breaks so bullet points and multiline items stay distinct.
    """
    if not text:
        return ""

    lines = text.split("\n")
    segmented_lines = []
    for line in lines:
        cleaned = clean_khmer_text(line)
        if cleaned and HAS_KHMERNLTK:
            try:
                tokens = word_tokenize(cleaned, return_tokens=True)
                words = [t.strip() for t in tokens if t.strip()]
                segmented_lines.append(" ".join(words))
            except Exception:
                segmented_lines.append(cleaned)
        else:
            segmented_lines.append(cleaned)

    return "\n".join(segmented_lines)
