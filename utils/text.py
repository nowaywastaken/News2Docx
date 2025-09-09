def now_stamp() -> str:
    """Generate current timestamp string in YYYYMMDD_HHMMSS format."""
    import time
    return time.strftime("%Y%m%d_%H%M%S")


def count_english_words(text: str) -> int:
    """Count English words, excluding HTML tags and punctuation."""
    import re
    if not text:
        return 0
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Extract word-like tokens
    words = re.findall(r'\b\w+\b', text)
    return len(words)


def safe_filename(filename: str, max_length: int = 255) -> str:
    """Clean file name by removing unsafe characters and limiting length."""
    import os
    import re
    name = filename or f"untitled_{now_stamp()}"
    # Remove unsafe characters
    safe_name = re.sub(r'[^\w\s.-]', '', name)
    # Normalize whitespace and dots
    safe_name = re.sub(r'\s+', ' ', safe_name).strip()
    safe_name = re.sub(r'\.+', '.', safe_name)
    safe_name = safe_name.strip(' .') or f"untitled_{now_stamp()}"
    # Enforce length limit
    if len(safe_name) > max_length:
        name_part, ext = os.path.splitext(safe_name)
        ext_len = len(ext)
        max_name_len = max_length - ext_len
        safe_name = name_part[:max_name_len] + ext
    return safe_name
