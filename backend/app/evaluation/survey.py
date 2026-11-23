"""설문 응답으로 가중치를 구하는 순수 함수.

- 쌍대비교(AHP): 항목 둘씩 "어느 쪽이 얼마나 더 중요한가"를 1~9 척도로 묻고, 행렬의 고유벡터로 가중치를 구한다.
  응답자가 여러 명이면 칸별 기하평균으로 합친다. 일관성 비율(CR)이 0.1을 넘으면 응답이 모순된다는 뜻이다.
- 100점 배분(constant sum): 항목에 100점을 나눠 주게 하고 응답자별로 정규화한 뒤 평균한다. 쌍대비교보다 쉽다.
두 방법의 결과가 비슷하면 가중치를 더 믿을 수 있다.
"""

import math
from statistics import fmean
from typing import Sequence

Matrix = list[list[float]]

# 항목 수별 무작위 일관성 지수 (Saaty)
_RI = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32}


def pairwise_matrix(n: int, answers: dict[tuple[int, int], float]) -> Matrix:
    """answers[(i, j)] = i가 j보다 몇 배 중요한가 (i<j). 반대칸은 역수로 채운다."""
    m = [[1.0] * n for _ in range(n)]
    for (i, j), v in answers.items():
        if v <= 0:
            raise ValueError("쌍대비교 값은 0보다 커야 합니다.")
        m[i][j] = v
        m[j][i] = 1.0 / v
    return m


def geometric_mean_matrix(matrices: Sequence[Matrix]) -> Matrix:
    """여러 응답자의 쌍대비교 행렬을 칸별 기하평균으로 합친다."""
    if not matrices:
        raise ValueError("응답이 없습니다.")
    n = len(matrices[0])
    return [[math.exp(fmean(math.log(m[i][j]) for m in matrices)) for j in range(n)] for i in range(n)]


def ahp_weights(matrix: Matrix, iterations: int = 200) -> tuple[list[float], float]:
    """(가중치, 일관성 비율 CR). 가중치의 합은 1."""
    n = len(matrix)
    w = [1.0 / n] * n
    for _ in range(iterations):  # 거듭제곱법으로 주 고유벡터를 구한다
        nxt = [sum(matrix[i][j] * w[j] for j in range(n)) for i in range(n)]
        total = sum(nxt)
        nxt = [x / total for x in nxt]
        if max(abs(a - b) for a, b in zip(nxt, w)) < 1e-12:
            w = nxt
            break
        w = nxt
    lam = fmean(sum(matrix[i][j] * w[j] for j in range(n)) / w[i] for i in range(n))
    ci = (lam - n) / (n - 1) if n > 1 else 0.0
    ri = _RI.get(n, 1.32)
    return w, (ci / ri if ri > 0 else 0.0)


def constant_sum_weights(rows: Sequence[Sequence[float]]) -> list[float]:
    """응답자별 100점 배분 → 각자 합 1로 정규화한 뒤 평균. 합이 0인 응답은 버린다."""
    normalized = [[v / sum(r) for v in r] for r in rows if sum(r) > 0]
    if not normalized:
        raise ValueError("유효한 응답이 없습니다.")
    n = len(normalized[0])
    return [fmean(r[i] for r in normalized) for i in range(n)]
