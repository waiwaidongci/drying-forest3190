"""配对对照的确定性算法。

选对只读取初始湿度与厚度。实测时长在配对名单定稿之后才参与差值估计，
不进入候选、代价、排序或任何选对分支。

字典序目标：
1. 合格配对数最多；
2. 按容差折算的总差最小；
3. 总差同分时，按两组样本编号升序逐位比较，取字典序最小的一份名单。
每件试件最多配对一次。
"""
import hashlib
import json
import math
from decimal import Decimal
from fractions import Fraction
from functools import reduce
from math import gcd

import numpy as np
from scipy import stats
from scipy.optimize import linear_sum_assignment

CONFIDENCE = 0.95
MAX_CANDIDATE_PAIRS = 60000
MAX_TIEBREAK_CHECKS = 8000
FLOAT_EXACT = 2.0 ** 52


def digest(value):
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(text.encode()).hexdigest()


def _decimal(value):
    try:
        number = Decimal(str(value))
    except Exception:
        raise ValueError('容差与工艺量必须为数值')
    if not number.is_finite():
        raise ValueError('容差与工艺量必须为有限数值')
    return number


def _decimal_places(value):
    return max(0, -_decimal(value).as_tuple().exponent)


def specimen(record):
    """只保留选对所需字段；实测时长在这里被刻意丢弃。"""
    values = record['values']
    return {
        'reference': str(record['reference']),
        'moisture': _decimal(values['moisture']),
        'thickness': _decimal(values['thickness']),
    }


def _assign(rows, columns, weights, penalty):
    """最大基数、最小总代价的一对一指派。

    每行都有一条专属空配列，代价为 penalty；penalty 大于任何完整配对的
    总代价，所以先保证真实配对最多，再保证总折算差最小。
    """
    matrix = np.full((len(rows), len(columns) + len(rows)), float(penalty), dtype=np.float64)
    for row_index, row in enumerate(rows):
        for column_index, column in enumerate(columns):
            weight = weights.get((row, column))
            if weight is not None:
                matrix[row_index, column_index] = float(weight)
    assignment_rows, assignment_columns = linear_sum_assignment(matrix)
    selected = []
    for row_index, column_index in zip(assignment_rows, assignment_columns):
        if column_index < len(columns) and (rows[row_index], columns[column_index]) in weights:
            selected.append((rows[row_index], columns[column_index]))
    return selected


def compute_pairing(records_a, records_b, tolerance_humidity, tolerance_thickness):
    humidity_tolerance = _decimal(tolerance_humidity)
    thickness_tolerance = _decimal(tolerance_thickness)
    if humidity_tolerance <= 0 or thickness_tolerance <= 0:
        raise ValueError('湿度与厚度容差都必须大于0')

    group_a = sorted((specimen(r) for r in records_a), key=lambda x: x['reference'])
    group_b = sorted((specimen(r) for r in records_b), key=lambda x: x['reference'])
    if not group_a or not group_b:
        raise ValueError('两组都必须至少有一条试件')

    places = max(
        [_decimal_places(x['moisture']) for x in group_a + group_b]
        + [_decimal_places(x['thickness']) for x in group_a + group_b]
        + [_decimal_places(humidity_tolerance), _decimal_places(thickness_tolerance)]
    )
    factor = Decimal(10) ** places

    def scaled(value):
        return int(_decimal(value) * factor)

    humidity_limit = scaled(humidity_tolerance)
    thickness_limit = scaled(thickness_tolerance)
    denominator = humidity_limit * thickness_limit

    raw = {}
    candidate_count_a = {}
    candidate_count_b = {}
    for i, a in enumerate(group_a):
        for j, b in enumerate(group_b):
            moisture_gap = abs(scaled(a['moisture']) - scaled(b['moisture']))
            thickness_gap = abs(scaled(a['thickness']) - scaled(b['thickness']))
            if moisture_gap > humidity_limit or thickness_gap > thickness_limit:
                continue
            raw[(i, j)] = moisture_gap * thickness_limit + thickness_gap * humidity_limit
            candidate_count_a[i] = candidate_count_a.get(i, 0) + 1
            candidate_count_b[j] = candidate_count_b.get(j, 0) + 1
    if len(raw) > MAX_CANDIDATE_PAIRS:
        raise ValueError('容差内的候选配对过多，请收紧湿度或厚度容差后重新受理')

    weights = raw
    if raw:
        common = reduce(gcd, raw.values())
        if common > 1:
            weights = {key: value // common for key, value in raw.items()}
        largest = max(weights.values())
        sides = max(len(group_a), len(group_b))
        penalty = largest * (min(len(group_a), len(group_b)) + 1) + 1
        if penalty * sides * 2 > FLOAT_EXACT:
            raise ValueError('容差或样本数值的小数位过多，请把容差取整到较少小数位后重新受理')

    selected = []
    if weights:
        all_a = list(range(len(group_a)))
        all_b = list(range(len(group_b)))
        penalty = max(weights.values()) * (min(len(group_a), len(group_b)) + 1) + 1
        baseline = _assign(all_a, all_b, weights, penalty)
        target_count = len(baseline)
        target_cost = sum(weights[key] for key in baseline)
        # 字典序定序：按A组编号从小到大，为每件试件挑编号最小的可行B组试件，
        # 只要剩余行仍能补足目标配对数与目标总差，就固定它。
        chosen_b = {}
        used_b = set()
        fixed_cost = 0
        checks = 0
        aborted = False
        for position, i in enumerate(all_a):
            if len(chosen_b) + (len(all_a) - position) < target_count:
                break
            for j in all_b:
                if j in used_b or (i, j) not in weights:
                    continue
                remaining_a = all_a[position + 1:]
                remaining_b = [column for column in all_b if column not in used_b and column != j]
                if len(remaining_b) < target_count - len(chosen_b) - 1:
                    continue
                checks += 1
                if checks > MAX_TIEBREAK_CHECKS:
                    aborted = True
                    break
                completion = _assign(remaining_a, remaining_b, weights, penalty)
                if len(completion) < target_count - len(chosen_b) - 1:
                    continue
                if fixed_cost + weights[(i, j)] + sum(weights[key] for key in completion) != target_cost:
                    continue
                chosen_b[i] = j
                used_b.add(j)
                fixed_cost += weights[(i, j)]
                break
            if aborted:
                break
        if not aborted and len(chosen_b) == target_count and fixed_cost == target_cost:
            selected = sorted(chosen_b.items())
            tiebreak = 'reference_order'
        else:
            selected = sorted(baseline, key=lambda key: (group_a[key[0]]['reference'], group_b[key[1]]['reference']))
            tiebreak = 'baseline'
    else:
        tiebreak = 'reference_order'

    return _output(group_a, group_b, selected, raw, candidate_count_a, candidate_count_b, denominator, humidity_tolerance, thickness_tolerance, tiebreak)


def _output(group_a, group_b, selected, raw, candidate_count_a, candidate_count_b, denominator, humidity_tolerance, thickness_tolerance, tiebreak):
    pairs = []
    total_numerator = 0
    for number, (i, j) in enumerate(selected, start=1):
        a, b = group_a[i], group_b[j]
        numerator = raw[(i, j)]
        total_numerator += numerator
        pairs.append({
            'pair_no': number,
            'reference_a': a['reference'],
            'reference_b': b['reference'],
            'moisture_a': float(a['moisture']),
            'moisture_b': float(b['moisture']),
            'moisture_gap': float(abs(a['moisture'] - b['moisture'])),
            'thickness_a': float(a['thickness']),
            'thickness_b': float(b['thickness']),
            'thickness_gap': float(abs(a['thickness'] - b['thickness'])),
            'normalized_cost': float(Fraction(numerator, denominator)) if denominator else 0.0,
        })

    used_a = {i for i, _ in selected}
    used_b = {j for _, j in selected}
    unmatched = []
    for i, a in enumerate(group_a):
        if i in used_a:
            continue
        count = candidate_count_a.get(i, 0)
        unmatched.append({
            'group': 'A',
            'reference': a['reference'],
            'moisture': float(a['moisture']),
            'thickness': float(a['thickness']),
            'candidate_count': count,
            'reason': '另一组没有落在容差内的试件' if count == 0 else '容差内候选均已被更优配对占用',
        })
    for j, b in enumerate(group_b):
        if j in used_b:
            continue
        count = candidate_count_b.get(j, 0)
        unmatched.append({
            'group': 'B',
            'reference': b['reference'],
            'moisture': float(b['moisture']),
            'thickness': float(b['thickness']),
            'candidate_count': count,
            'reason': '另一组没有落在容差内的试件' if count == 0 else '容差内候选均已被更优配对占用',
        })

    return {
        'pairs': pairs,
        'unmatched': unmatched,
        'candidate_pairs': len(raw),
        'tiebreak': tiebreak,
        'total_normalized_cost': float(Fraction(total_numerator, denominator)) if denominator else 0.0,
        'tolerance_humidity': format(humidity_tolerance.normalize(), 'f'),
        'tolerance_thickness': format(thickness_tolerance.normalize(), 'f'),
    }


def compute_estimate(pairs, records_a, records_b, confidence=CONFIDENCE):
    """由已冻结的配对名单和实测时长计算配对差值与平均差区间。"""
    minutes = {}
    for record in records_a:
        minutes[('A', str(record['reference']))] = _decimal(record['values']['minutes'])
    for record in records_b:
        minutes[('B', str(record['reference']))] = _decimal(record['values']['minutes'])
    differences = []
    for pair in pairs:
        try:
            value = minutes[('A', pair['reference_a'])] - minutes[('B', pair['reference_b'])]
        except KeyError:
            raise ValueError('配对名单与冻结样本不一致，请重新受理')
        differences.append(float(value))
    count = len(differences)
    if count < 2:
        raise ValueError('有效配对不足2对，无法估计平均差与区间；请补充容差内试件后另行受理')
    mean = sum(differences) / count
    variance = sum((value - mean) ** 2 for value in differences) / (count - 1)
    deviation = math.sqrt(variance)
    standard_error = deviation / math.sqrt(count)
    critical = float(stats.t.ppf((1 + confidence) / 2, count - 1))
    margin = critical * standard_error
    return {
        'pair_count': count,
        'mean_diff_minutes': mean,
        'ci_low_minutes': mean - margin,
        'ci_high_minutes': mean + margin,
        'confidence': confidence,
        'standard_deviation': deviation,
        'standard_error': standard_error,
        'degrees_of_freedom': count - 1,
        'critical_value': critical,
        'direction': 'A组减B组（A组实测时长 − B组实测时长）',
        'method': '配对差值单样本t区间：均值 ± t(0.975, n−1) × 标准差/√n；不比较两组各自独立的平均时长。',
    }


def pair_rows(pairs, records_a, records_b):
    """把配对名单与实测时长合并成逐对明细，供页面与CSV共用。"""
    minutes = {}
    for record in records_a:
        minutes[('A', str(record['reference']))] = float(record['values']['minutes'])
    for record in records_b:
        minutes[('B', str(record['reference']))] = float(record['values']['minutes'])
    rows = []
    for pair in pairs:
        minutes_a = minutes[('A', pair['reference_a'])]
        minutes_b = minutes[('B', pair['reference_b'])]
        rows.append({
            'pair_no': pair['pair_no'],
            'reference_a': pair['reference_a'],
            'minutes_a': minutes_a,
            'reference_b': pair['reference_b'],
            'minutes_b': minutes_b,
            'diff_minutes': minutes_a - minutes_b,
            'moisture_gap': pair['moisture_gap'],
            'thickness_gap': pair['thickness_gap'],
            'normalized_cost': pair['normalized_cost'],
        })
    return rows
