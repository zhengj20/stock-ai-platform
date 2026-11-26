"""数据清洗工具 - 统一处理 NaN/Inf/None 等异常值"""
import math
import re


def sanitize_number(value, default=0.0):
    """将 NaN/Inf/None 转换为默认值，返回 float"""
    if value is None:
        return default
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default


def sanitize_dict_numbers(d: dict) -> dict:
    """递归清理字典中所有数值类型的 NaN/Inf"""
    if not isinstance(d, dict):
        return d
    result = {}
    for k, v in d.items():
        if isinstance(v, dict):
            result[k] = sanitize_dict_numbers(v)
        elif isinstance(v, list):
            result[k] = [sanitize_dict_numbers(item) if isinstance(item, dict) else sanitize_number(item) for item in v]
        elif isinstance(v, (int, float)):
            result[k] = sanitize_number(v)
        else:
            result[k] = v
    return result


def safe_format(value, fmt="{:.2f}"):
    """安全格式化数值，NaN/Inf 返回 "--" """
    num = sanitize_number(value)
    if num == 0.0 and value is not None and str(value).lower() in ("nan", "inf", "-inf", "none", ""):
        return "--"
    try:
        return fmt.format(num)
    except (ValueError, TypeError):
        return "--"


def get_stock_board(code: str) -> str:
    """
    根据股票代码判断所属板块
    返回: 'main' (主板), 'gem' (创业板), 'star' (科创板), 'bj' (北交所), 'unknown'
    """
    code = str(code).strip()
    if not code:
        return 'unknown'
    if code.startswith('300') or code.startswith('301'):
        return 'gem'
    if code.startswith('688') or code.startswith('689'):
        return 'star'
    if code.startswith('8') or code.startswith('4'):
        return 'bj'
    if code.startswith('60') or code.startswith('000') or code.startswith('001') or code.startswith('002') or code.startswith('003'):
        return 'main'
    return 'unknown'


def is_st_stock(name: str) -> bool:
    """判断是否为ST/*ST股票"""
    if not name:
        return False
    name = str(name).strip()
    return name.startswith('ST') or name.startswith('*ST')


def is_special_stock(name: str) -> bool:
    """判断是否为特殊股票（S股、退市股、DR除权股等），这些通常不计入涨跌停统计"""
    if not name:
        return False
    name = str(name).strip()
    if name.startswith('S') and not name.startswith('ST') and not name.startswith('*ST'):
        return True
    if '退' in name:
        return True
    if name.startswith('DR') or name.startswith('XR') or name.startswith('XD'):
        return True
    return False


def get_limit_pct(code: str, name: str = '') -> float:
    """
    获取股票的涨跌停幅度（百分比，正数）
    
    规则：
    - 沪/深主板：正常±10%，ST/*ST±5%
    - 创业板：±20%（含ST）
    - 科创板：±20%（含ST）
    - 北交所：±30%（含ST）
    - 特殊股(S/退/DR)：返回 0（不参与涨跌停统计）
    """
    if is_special_stock(name):
        return 0.0
    
    board = get_stock_board(code)
    is_st = is_st_stock(name)
    
    if board in ('gem', 'star'):
        return 20.0
    if board == 'bj':
        return 30.0
    if board == 'main':
        return 5.0 if is_st else 10.0
    return 10.0


def is_limit_up(price: float, limit_up_price: float, code: str = '', name: str = '',
                prev_close: float = None, use_price_match: bool = True) -> bool:
    """
    严格判断是否涨停
    
    Args:
        price: 当前价/收盘价
        limit_up_price: 涨停价
        code: 股票代码
        name: 股票名称
        prev_close: 前收盘价（可选，用于百分比校验）
        use_price_match: 是否使用涨停价匹配（True）还是百分比计算（False）
    
    Returns:
        True 表示涨停
    """
    price = sanitize_number(price)
    limit_up_price = sanitize_number(limit_up_price)
    
    if price <= 0 or limit_up_price <= 0:
        return False
    
    if is_special_stock(name):
        return False
    
    limit_pct = get_limit_pct(code, name)
    if limit_pct <= 0:
        return False
    
    if use_price_match:
        diff_pct = abs(price - limit_up_price) / limit_up_price * 100
        return diff_pct < 0.1
    
    if prev_close and prev_close > 0:
        actual_pct = (price - prev_close) / prev_close * 100
        return abs(actual_pct - limit_pct) < 0.1
    
    return False


def is_limit_down(price: float, limit_down_price: float, code: str = '', name: str = '',
                  prev_close: float = None, use_price_match: bool = True) -> bool:
    """
    严格判断是否跌停
    
    Args:
        price: 当前价/收盘价
        limit_down_price: 跌停价
        code: 股票代码
        name: 股票名称
        prev_close: 前收盘价（可选，用于百分比校验）
        use_price_match: 是否使用跌停价匹配（True）还是百分比计算（False）
    
    Returns:
        True 表示跌停
    """
    price = sanitize_number(price)
    limit_down_price = sanitize_number(limit_down_price)
    
    if price <= 0 or limit_down_price <= 0:
        return False
    
    if is_special_stock(name):
        return False
    
    limit_pct = get_limit_pct(code, name)
    if limit_pct <= 0:
        return False
    
    if use_price_match:
        diff_pct = abs(price - limit_down_price) / limit_down_price * 100
        return diff_pct < 0.1
    
    if prev_close and prev_close > 0:
        actual_pct = (price - prev_close) / prev_close * 100
        return abs(actual_pct + limit_pct) < 0.1
    
    return False
