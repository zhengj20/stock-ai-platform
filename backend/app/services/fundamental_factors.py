"""基本面因子计算器 — 从财务数据提取标准化因子"""
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

class FundamentalFactorCalculator:
    """基本面因子计算器 — 从财务数据提取标准化因子"""
    
    @staticmethod
    def compute_from_financial(financial_data: dict) -> Optional[dict]:
        """从财务数据计算基本面因子"""
        if not financial_data:
            return None
        
        factors = {}
        
        # PE_TTM（市盈率TTM）— 越低越好，但需排除负值
        pe_ttm = financial_data.get('pe_ttm', 0) or 0
        if pe_ttm > 0:
            # PE评分：0-15低估(90分), 15-30合理(70分), 30-50偏高(40分), >50高估(20分)
            if pe_ttm <= 15:
                factors['pe_score'] = min(95, 70 + (15 - pe_ttm) * 1.7)
            elif pe_ttm <= 30:
                factors['pe_score'] = max(40, 70 - (pe_ttm - 15) * 2)
            elif pe_ttm <= 50:
                factors['pe_score'] = max(20, 40 - (pe_ttm - 30) * 1)
            else:
                factors['pe_score'] = max(10, 20 - (pe_ttm - 50) * 0.2)
        else:
            factors['pe_score'] = None  # PE为负或无数据
        
        # PB（市净率）— 越低越好
        pb = financial_data.get('pb', 0) or 0
        if pb > 0:
            # PB评分：0-1破净(85分), 1-2合理(70分), 2-4偏高(45分), >4高估(25分)
            if pb <= 1:
                factors['pb_score'] = min(90, 65 + (1 - pb) * 25)
            elif pb <= 2:
                factors['pb_score'] = max(45, 70 - (pb - 1) * 25)
            elif pb <= 4:
                factors['pb_score'] = max(25, 45 - (pb - 2) * 10)
            else:
                factors['pb_score'] = max(10, 25 - (pb - 4) * 3)
        else:
            factors['pb_score'] = None
        
        # ROE（净资产收益率）— 越高越好
        roe = financial_data.get('roe', 0) or 0
        if roe != 0:
            # ROE评分：>20%(95分), 15-20%(85分), 10-15%(70分), 5-10%(55分), <5%(35分)
            if roe >= 20:
                factors['roe_score'] = min(98, 85 + (roe - 20) * 1)
            elif roe >= 15:
                factors['roe_score'] = max(70, 70 + (roe - 15) * 3)
            elif roe >= 10:
                factors['roe_score'] = max(55, 55 + (roe - 10) * 3)
            elif roe >= 5:
                factors['roe_score'] = max(35, 35 + (roe - 5) * 4)
            else:
                factors['roe_score'] = max(10, 35 + roe * 2)
        else:
            factors['roe_score'] = None
        
        # 毛利率（gross_margin）— 越高越好
        gross_margin = financial_data.get('gross_margin', 0) or 0
        if gross_margin > 0:
            # 毛利率评分：>50%(95分), 30-50%(80分), 20-30%(65分), <20%(45分)
            if gross_margin >= 50:
                factors['gross_margin_score'] = min(98, 80 + (gross_margin - 50) * 0.3)
            elif gross_margin >= 30:
                factors['gross_margin_score'] = max(65, 65 + (gross_margin - 30) * 0.75)
            elif gross_margin >= 20:
                factors['gross_margin_score'] = max(45, 45 + (gross_margin - 20) * 2)
            else:
                factors['gross_margin_score'] = max(10, 45 + gross_margin * 2.25)
        else:
            factors['gross_margin_score'] = None
        
        # 营收同比增长率（revenue_yoy）— 越高越好
        revenue_yoy = financial_data.get('revenue_yoy', 0) or 0
        if revenue_yoy != 0:
            # 营收增长评分：>30%(95分), 10-30%(80分), 0-10%(65分), <0%(40分)
            if revenue_yoy >= 30:
                factors['revenue_growth_score'] = min(98, 80 + (revenue_yoy - 30) * 0.5)
            elif revenue_yoy >= 10:
                factors['revenue_growth_score'] = max(65, 65 + (revenue_yoy - 10) * 0.75)
            elif revenue_yoy >= 0:
                factors['revenue_growth_score'] = max(40, 40 + revenue_yoy * 2.5)
            else:
                factors['revenue_growth_score'] = max(10, 40 + revenue_yoy * 1.33)
        else:
            factors['revenue_growth_score'] = None
        
        # 净利润同比增长率（profit_yoy）— 越高越好
        profit_yoy = financial_data.get('profit_yoy', 0) or 0
        if profit_yoy != 0:
            # 利润增长评分：>30%(95分), 10-30%(80分), 0-10%(65分), <0%(40分)
            if profit_yoy >= 30:
                factors['profit_growth_score'] = min(98, 80 + (profit_yoy - 30) * 0.5)
            elif profit_yoy >= 10:
                factors['profit_growth_score'] = max(65, 65 + (profit_yoy - 10) * 0.75)
            elif profit_yoy >= 0:
                factors['profit_growth_score'] = max(40, 40 + profit_yoy * 2.5)
            else:
                factors['profit_growth_score'] = max(10, 40 + profit_yoy * 1.33)
        else:
            factors['profit_growth_score'] = None
        
        # EPS（每股收益）— 越高越好
        eps = financial_data.get('eps', 0) or 0
        if eps > 0:
            # EPS评分：>2(95分), 1-2(80分), 0.5-1(65分), <0.5(45分)
            if eps >= 2:
                factors['eps_score'] = min(98, 80 + (eps - 2) * 7.5)
            elif eps >= 1:
                factors['eps_score'] = max(65, 65 + (eps - 1) * 15)
            elif eps >= 0.5:
                factors['eps_score'] = max(45, 45 + (eps - 0.5) * 40)
            else:
                factors['eps_score'] = max(10, 45 + eps * 90)
        else:
            factors['eps_score'] = None
        
        # 资产负债率（debt_ratio）— 适中最好（倒U型）
        debt_ratio = financial_data.get('debt_ratio', 0) or 0
        if 0 < debt_ratio < 100:
            # 负债率评分：40-60%(85分), 30-40%或60-70%(70分), <30%或>70%(50分)
            if 40 <= debt_ratio <= 60:
                factors['debt_ratio_score'] = max(70, 85 - abs(debt_ratio - 50) * 0.3)
            elif 30 <= debt_ratio < 40 or 60 < debt_ratio <= 70:
                factors['debt_ratio_score'] = max(50, 70 - (min(abs(debt_ratio - 40), abs(debt_ratio - 60)) * 2))
            else:
                factors['debt_ratio_score'] = max(10, 50 - min(abs(debt_ratio - 30), abs(debt_ratio - 70)))
        else:
            factors['debt_ratio_score'] = None
        
        # 综合基本面评分（加权平均）
        fundamental_scores = {k: v for k, v in factors.items() if k.endswith('_score') and v is not None}
        if fundamental_scores:
            weights = {
                'pe_score': 0.25,
                'pb_score': 0.20,
                'roe_score': 0.25,
                'gross_margin_score': 0.10,
                'revenue_growth_score': 0.10,
                'profit_growth_score': 0.10,
            }
            
            total_weight = sum(weights.get(k, 0) for k in fundamental_scores.keys())
            weighted_sum = sum(fundamental_scores[k] * weights.get(k, 0) for k in fundamental_scores.keys())
            
            if total_weight > 0:
                factors['fundamental_score'] = round(weighted_sum / total_weight, 1)
        
        return factors
    
    @staticmethod
    def compute_combined_score(technical_factors: dict, financial_data: dict, 
                               technical_weight: float = 0.6, fundamental_weight: float = 0.4) -> float:
        """计算技术面+基本面的综合评分"""
        # 技术面评分（使用因子引擎）
        from app.services.factor_engine import StandardScorer
        tech_score = StandardScorer.score(technical_factors, "balanced")
        
        # 基本面评分
        fundamental_factors = FundamentalFactorCalculator.compute_from_financial(financial_data)
        if not fundamental_factors:
            return tech_score
        
        fund_score = fundamental_factors.get('fundamental_score', 50)
        
        # 加权综合
        combined = tech_score * technical_weight + fund_score * fundamental_weight
        return round(min(98, max(10, combined)), 1)

