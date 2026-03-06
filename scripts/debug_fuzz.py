import sys
sys.path.append('src')

from rapidfuzz import fuzz

metrics = []
for n1, n2 in [
    ("akane yanagi", "kana yanagi"),
    ("mito", "mito uzumaki"),
]:
    print(f"Comparing '{n1}' vs '{n2}':")
    print(f"  ratio: {fuzz.ratio(n1, n2)}")
    print(f"  partial_ratio: {fuzz.partial_ratio(n1, n2)}")
    print(f"  token_sort_ratio: {fuzz.token_sort_ratio(n1, n2)}")
    print(f"  token_set_ratio: {fuzz.token_set_ratio(n1, n2)}")
    print()
