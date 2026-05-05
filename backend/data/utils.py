import re
import unicodedata


def normalize_name(name: str) -> str:
    """
    Normalize a player name for fuzzy matching across data sources.

    Steps:
      1. Unescape SQL single-quote escape sequences (\\' -> ')
      2. Remove periods so "C.J." matches "CJ", "Jr." matches "Jr"
      3. Remove name suffixes (Jr, Sr, II, III, IV) that differ between sources
      4. Strip diacritics via NFD decomposition (Acuña -> Acuna)
      5. Lowercase and collapse extra whitespace
    """
    name = name.replace("\\'", "'")
    name = name.replace(".", "")
    name = re.sub(r'\b(jr|sr|ii|iii|iv)\b', '', name, flags=re.IGNORECASE)
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
    return ' '.join(ascii_name.lower().split())