from fnmatch import fnmatch


def matches(pattern: str, value: str, *, case_sensitive: bool = True) -> bool:
    if pattern == "*":
        return True
    if not case_sensitive:
        return fnmatch(value.lower(), pattern.lower())
    return fnmatch(value, pattern)
