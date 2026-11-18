from decimal import Decimal

MAX_TOLERANCE_HUMIDITY = 100
MAX_TOLERANCE_THICKNESS = 1000


def tolerance_text(value):
    """校验并规范化容差；冻结与展示共用同一份十进制文本。"""
    if isinstance(value, bool):
        raise ValueError('容差必须为数值')
    try:
        number = Decimal(str(value))
    except Exception:
        raise ValueError('容差必须为数值')
    if not number.is_finite():
        raise ValueError('容差必须为有限数值')
    if number <= 0:
        raise ValueError('容差必须大于0')
    return format(number.normalize(), 'f')


def check_tolerances(humidity, thickness):
    humidity = tolerance_text(humidity)
    thickness = tolerance_text(thickness)
    if Decimal(humidity) > MAX_TOLERANCE_HUMIDITY:
        raise ValueError('湿度容差不能超过100个百分点')
    if Decimal(thickness) > MAX_TOLERANCE_THICKNESS:
        raise ValueError('厚度容差不能超过1000毫米')
    return humidity, thickness
