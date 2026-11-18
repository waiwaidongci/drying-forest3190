"""配对对照的算法与流程测试；不依赖外部服务。

运行：cd backend && python3 -m pytest -q tests
"""
import itertools
import math
import os
import sys
from fractions import Fraction

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.pairing import compute_pairing, compute_estimate, pair_rows


def record(reference, moisture, thickness, minutes=60.0):
    return {'reference': reference, 'values': {'moisture': moisture, 'thickness': thickness, 'minutes': minutes}}


def brute(records_a, records_b, tolerance_humidity, tolerance_thickness):
    """小规模穷举：最大配对数 → 最小总折算差 → 编号字典序。"""
    a = sorted((r['reference'], Fraction(str(r['values']['moisture'])), Fraction(str(r['values']['thickness']))) for r in records_a)
    b = sorted((r['reference'], Fraction(str(r['values']['moisture'])), Fraction(str(r['values']['thickness']))) for r in records_b)
    th = Fraction(str(tolerance_humidity))
    tt = Fraction(str(tolerance_thickness))
    for size in range(min(len(a), len(b)), -1, -1):
        found = []
        for rows in itertools.combinations(range(len(a)), size):
            for cols in itertools.permutations(range(len(b)), size):
                total = Fraction(0)
                edges = []
                valid = True
                for row, col in zip(rows, cols):
                    gap_m = abs(a[row][1] - b[col][1])
                    gap_t = abs(a[row][2] - b[col][2])
                    if gap_m > th or gap_t > tt:
                        valid = False
                        break
                    total += gap_m / th + gap_t / tt
                    edges.append((a[row][0], b[col][0]))
                if valid:
                    found.append((total, tuple(edges)))
        if found:
            found.sort(key=lambda item: (item[0], item[1]))
            return found[0]
    return None


@pytest.mark.parametrize('seed', range(12))
def test_matches_exhaustive_search(seed):
    import random
    rng = random.Random(seed)
    records_a = [record(f'A{i + 1}', rng.choice([10, 10.5, 11, 12]), rng.choice([1, 1.2, 2, 2.5])) for i in range(rng.randint(1, 4))]
    records_b = [record(f'B{i + 1}', rng.choice([10, 10.5, 11, 12]), rng.choice([1, 1.2, 2, 2.5])) for i in range(rng.randint(1, 4))]
    tolerance_humidity = rng.choice([0.5, 1, 1.5])
    tolerance_thickness = rng.choice([0.2, 0.5, 1])
    result = compute_pairing(records_a, records_b, tolerance_humidity, tolerance_thickness)
    expected = brute(records_a, records_b, tolerance_humidity, tolerance_thickness)
    if expected is None:
        assert result['pairs'] == []
        return
    total, edges = expected
    assert [(p['reference_a'], p['reference_b']) for p in result['pairs']] == list(edges)
    assert result['total_normalized_cost'] == pytest.approx(float(total), abs=1e-9)


def test_each_specimen_paired_at_most_once():
    records_a = [record('A1', 10, 1), record('A2', 10, 1), record('A3', 10, 1)]
    records_b = [record('B1', 10, 1), record('B2', 11, 1)]
    result = compute_pairing(records_a, records_b, 5, 5)
    references_a = [p['reference_a'] for p in result['pairs']]
    references_b = [p['reference_b'] for p in result['pairs']]
    assert len(set(references_a)) == len(references_a)
    assert len(set(references_b)) == len(references_b)
    assert len(result['pairs']) == 2


def test_maximum_cardinality_beats_cheaper_smaller_matching():
    # 贪心会先配 A1-B1（最省），只剩 A2 无候选；最优应配 2 对。
    records_a = [record('A1', 10, 1), record('A2', 10, 1)]
    records_b = [record('B1', 10, 1), record('B2', 10.5, 1)]
    result = compute_pairing(records_a, records_b, 1, 1)
    assert len(result['pairs']) == 2


def test_tie_break_follows_reference_order():
    records_a = [record('A1', 10, 1), record('A2', 12, 1)]
    records_b = [record('B1', 11, 1), record('B2', 11, 1)]
    result = compute_pairing(records_a, records_b, 5, 5)
    assert result['total_normalized_cost'] == pytest.approx(0.4)
    assert [(p['reference_a'], p['reference_b']) for p in result['pairs']] == [('A1', 'B1'), ('A2', 'B2')]


def test_minutes_do_not_influence_matching():
    base_a = [record('A1', 10, 1, 10), record('A2', 20, 2, 20)]
    base_b = [record('B1', 10, 1, 900), record('B2', 20, 2, 800)]
    changed_b = [record('B1', 10, 1, 1), record('B2', 20, 2, 1)]
    first = compute_pairing(base_a, base_b, 2, 2)
    second = compute_pairing(base_a, changed_b, 2, 2)
    assert [(p['reference_a'], p['reference_b']) for p in first['pairs']] == [(p['reference_a'], p['reference_b']) for p in second['pairs']]


def test_unmatched_records_carry_reason():
    records_a = [record('A1', 10, 1), record('A2', 90, 9)]
    records_b = [record('B1', 10, 1)]
    result = compute_pairing(records_a, records_b, 1, 1)
    unmatched = {row['reference']: row for row in result['unmatched']}
    assert 'A2' in unmatched
    assert unmatched['A2']['candidate_count'] == 0
    assert '容差' in unmatched['A2']['reason']


def test_estimate_uses_paired_differences_only():
    records_a = [record('A1', 10, 1, 50), record('A2', 20, 1, 70), record('A3', 30, 1, 60)]
    records_b = [record('B1', 10, 1, 40), record('B2', 20, 1, 30), record('B3', 30, 1, 20)]
    pairing = compute_pairing(records_a, records_b, 1, 1)
    estimate = compute_estimate(pairing['pairs'], records_a, records_b)
    differences = [10.0, 40.0, 40.0]
    mean = sum(differences) / 3
    expected_se = math.sqrt(sum((d - mean) ** 2 for d in differences) / 2 / 3)
    assert estimate['pair_count'] == 3
    assert estimate['mean_diff_minutes'] == pytest.approx(mean)
    assert estimate['standard_error'] == pytest.approx(expected_se)
    assert estimate['ci_low_minutes'] < mean < estimate['ci_high_minutes']


def test_insufficient_pairs_rejected_for_interval():
    records_a = [record('A1', 10, 1, 50), record('A2', 90, 9, 60)]
    records_b = [record('B1', 10, 1, 40)]
    pairing = compute_pairing(records_a, records_b, 1, 1)
    with pytest.raises(ValueError):
        compute_estimate(pairing['pairs'], records_a, records_b)


def test_tolerance_must_be_positive():
    with pytest.raises(ValueError):
        compute_pairing([record('A1', 10, 1)], [record('B1', 10, 1)], 0, 1)


def test_pair_rows_align_with_pairs():
    records_a = [record('A1', 10, 1, 50)]
    records_b = [record('B1', 10, 1, 40)]
    pairing = compute_pairing(records_a, records_b, 1, 1)
    rows = pair_rows(pairing['pairs'], records_a, records_b)
    assert rows[0]['diff_minutes'] == pytest.approx(10)
