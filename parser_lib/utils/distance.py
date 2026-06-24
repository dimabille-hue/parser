"""String distance algorithms"""


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein distance between two strings
    
    Args:
        s1: First string
        s2: Second string
        
    Returns:
        Levenshtein distance (number of edits needed)
    """
    if len(s1) < len(s2):
        s1, s2 = s2, s1
    if not s2:
        return len(s1)
    
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1, start=1):
        curr = [i]
        for j, c2 in enumerate(s2, start=1):
            cost = 0 if c1 == c2 else 1
            curr.append(min(curr[-1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]
