

def is_emoji(ch: str) -> bool:
    # very naive check: emoji are outside BMP or in emoji ranges
    cp = ord(ch)
    return (0x1F300 <= cp <= 0x1FAFF) or (0x1F600 <= cp <= 0x1F64F) or (0x2600 <= cp <= 0x26FF)

