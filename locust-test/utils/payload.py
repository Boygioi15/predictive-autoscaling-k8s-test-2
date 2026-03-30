import random
import string

def random_text(size: int) -> str:
    words = []
    for _ in range(size // 5):
        w = ''.join(random.choices(string.ascii_lowercase, k=5))
        words.append(w)
    return " ".join(words)
