import unicodedata


def normalize_name(name: str) -> str:
    """
    Normalize a player name for fuzzy matching across data sources.

    Steps:
      1. Unescape SQL single-quote escape sequences (\' -> ')
      2. Remove periods so "C.J." matches "CJ", "Jr." matches "Jr"
      3. Strip diacritics via NFD decomposition (Acuña -> Acuna)
      4. Lowercase and strip surrounding whitespace
    """
    name = name.replace("\\'", "'")
    name = name.replace(".", "")
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
    return ascii_name.lower().strip()