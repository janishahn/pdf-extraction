from __future__ import annotations

from typing import Tuple


def thirds_partition(total_questions: int) -> Tuple[int, int, int]:
    base = total_questions // 3
    rem = total_questions % 3
    first = base + (1 if rem > 0 else 0)
    second = base + (1 if rem > 1 else 0)
    third = base
    return first, second, third


def points_for_index(total_questions: int, one_based_index: int) -> int:
    f, s, _ = thirds_partition(total_questions)
    if one_based_index <= f:
        return 3
    if one_based_index <= f + s:
        return 4
    return 5
