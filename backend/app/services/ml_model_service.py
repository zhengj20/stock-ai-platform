"""
ML选股服务 — 加载训练好的LightGBM/XGBoost模型进行实时预测

设计原则：
1. 模型文件存储在 skills/ml-stock-picker/ml_output/ 目录
2. 支持热更新：检测到新模型文件时自动重新加载
3. 降级策略：模型不可用时回退到因子引擎评分
"""

import json
import logging
import os
import pickle
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 尝试导入ML库（可选依赖）
try:
    import lightgbm as lgb
    HAS_LGB = True
except ImportError:
    HAS_LGB = False

try:
    import xgboost as xgb
    HAS_XGB = True
except ImportError:
    HAS_XGB = False


class MLModelService:
    """ML模型服务 — 加载、管理、预测"""
    
    # 默认模型目录
    DEFAULT_MODEL_DIR = Path(__file__).parent.parent.parent.parent / "skills" / "ml-stock-picker" / "ml_output"
    
    def __init__(self, model_dir: Optional[str] = None):
        self.model_dir = Path(model_dir) if model_dir else self.DEFAULT_MODEL_DIR
        self.classifier = None  # LightGBM/XGBoost分类器
        self.regressor = None   # LightGBM/XGBoost回归器
        self.feature_names = [] # 特征名列表
        self.scaler = None      # StandardScaler（如有）
        self.model_loaded_at = None
        self._last_check_time = 0
        self._check_interval = 300  # 5分钟检查一次模型更新
    
    def load_models(self) -> bool:
        """加载分类器和回归器模型"""
        try:
            # 加载分类器
            clf_path = self.model_dir / "model_classifier.pkl"
            if clf_path.exists():
                with open(clf_path, 'rb') as f:
                    model_data = pickle.load(f)
                
                # 支持直接模型或包装格式
                if isinstance(model_data, dict):
                    self.classifier = model_data.get('model')
                    self.scaler = model_data.get('scaler')
                else:
                    self.classifier = model_data
                
                logger.info(f"分类器模型已加载: {clf_path}")
            else:
                logger.warning(f"未找到分类器模型: {clf_path}")
            
            # 加载回归器
            reg_path = self.model_dir / "model_regressor.pkl"
            if reg_path.exists():
                with open(reg_path, 'rb') as f:
                    model_data = pickle.load(f)
                
                if isinstance(model_data, dict):
                    self.regressor = model_data.get('model')
                    if self.scaler is None:
                        self.scaler = model_data.get('scaler')
                else:
                    self.regressor = model_data
                
                logger.info(f"回归器模型已加载: {reg_path}")
            else:
                logger.warning(f"未找到回归器模型: {reg_path}")
            
            # 加载特征名
            feature_names_path = self.model_dir / "feature_names.json"
            if feature_names_path.exists():
                with open(feature_names_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.feature_names = data.get('features', [])
                logger.info(f"特征名已加载: {len(self.feature_names)} 个")
            
            # 检查是否有至少一个模型
            if self.classifier is None and self.regressor is None:
                return False
            
            self.model_loaded_at = datetime.now()
            return True
            
        except Exception as e:
            logger.error(f"加载ML模型失败: {e}")
            return False
    
    def ensure_models_loaded(self) -> bool:
        """确保模型已加载（带热更新检查）"""
        now = time.time()
        
        # 首次加载或定期检查更新
        if self.classifier is None and self.regressor is None:
            return self.load_models()
        
        # 定期检查模型文件是否更新
        if now - self._last_check_time > self._check_interval:
            self._last_check_time = now
            try:
                clf_path = self.model_dir / "model_classifier.pkl"
                reg_path = self.model_dir / "model_regressor.pkl"
                
                # 检查文件修改时间
                if (clf_path.exists() and clf_path.stat().st_mtime > os.path.getmtime(str(self.model_dir))):
                    logger.info("检测到模型更新，重新加载...")
                    return self.load_models()
            except Exception:
                pass
        
        return True
    
    def predict_single(self, features: Dict[str, float]) -> Optional[Dict[str, Any]]:
        """对单只股票进行预测"""
        if not self.ensure_models_loaded():
            return None
        
        try:
            # 构建特征向量（按训练时的顺序）
            feature_vector = []
            for fname in self.feature_names:
                val = features.get(fname, 0.0)
                # 处理NaN和极端值
                if pd.isna(val) or abs(val) > 1e8:
                    val = 0.0
                feature_vector.append(float(val))
            
            X = pd.DataFrame([feature_vector], columns=self.feature_names)
            
            result = {
                'class_score': None,
                'regression_score': None,
                'combined_score': None,
                'prediction': None,
                'confidence': None,
            }
            
            # 分类预测（上涨概率）
            if self.classifier is not None:
                try:
                    if hasattr(self.classifier, 'predict_proba'):
                        proba = self.classifier.predict_proba(X)[0]
                        result['class_score'] = float(proba[1]) if len(proba) > 1 else float(proba[0])
                        result['prediction'] = '上涨' if result['class_score'] > 0.5 else '下跌'
                        result['confidence'] = max(result['class_score'], 1 - result['class_score'])
                    elif hasattr(self.classifier, 'predict'):
                        pred = self.classifier.predict(X)[0]
                        result['prediction'] = '上涨' if pred == 1 else '下跌'
                except Exception as e:
                    logger.debug(f"分类预测失败: {e}")
            
            # 回归预测（收益率）
            if self.regressor is not None:
                try:
                    reg_pred = self.regressor.predict(X)[0]
                    result['regression_score'] = float(reg_pred)
                except Exception as e:
                    logger.debug(f"回归预测失败: {e}")
            
            # 综合评分（分类和回归的加权平均）
            scores = []
            if result['class_score'] is not None:
                scores.append(result['class_score'])
            if result['regression_score'] is not None:
                # 将收益率映射到0-1范围（sigmoid）
                reg_normalized = 1 / (1 + np.exp(-result['regression_score']))
                scores.append(reg_normalized)
            
            if scores:
                result['combined_score'] = float(np.mean(scores))
            
            return result
            
        except Exception as e:
            logger.debug(f"ML预测失败: {e}")
            return None
    
    def predict_batch(self, stocks_features: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """批量预测"""
        results = []
        
        for stock_data in stocks_features:
            code = stock_data.get('code', '')
            features = stock_data.get('features', {})
            
            ml_result = self.predict_single(features)
            
            if ml_result and ml_result['combined_score'] is not None:
                results.append({
                    'code': code,
                    'name': stock_data.get('name', ''),
                    'price': stock_data.get('price', 0),
                    'change_pct': stock_data.get('change_pct', 0),
                    'ml_score': int(ml_result['combined_score'] * 100),
                    'prediction': ml_result['prediction'],
                    'confidence': ml_result['confidence'],
                    'class_score': ml_result['class_score'],
                    'regression_score': ml_result['regression_score'],
                })
            else:
                # 降级：使用因子引擎评分
                factors = stock_data.get('factors', {})
                if factors:
                    from app.services.factor_engine import StandardScorer
                    score = StandardScorer.score(factors, "balanced")
                    results.append({
                        'code': code,
                        'name': stock_data.get('name', ''),
                        'price': stock_data.get('price', 0),
                        'change_pct': stock_data.get('change_pct', 0),
                        'ml_score': int(score),
                        'prediction': '中性',
                        'confidence': 0.5,
                        'class_score': None,
                        'regression_score': None,
                    })
        
        return results
    
    def get_model_info(self) -> Dict[str, Any]:
        """获取模型信息"""
        info = {
            'model_dir': str(self.model_dir),
            'classifier_loaded': self.classifier is not None,
            'regressor_loaded': self.regressor is not None,
            'feature_count': len(self.feature_names),
            'loaded_at': self.model_loaded_at.isoformat() if self.model_loaded_at else None,
        }
        
        # 检查模型文件
        clf_path = self.model_dir / "model_classifier.pkl"
        reg_path = self.model_dir / "model_regressor.pkl"
        
        info['classifier_file'] = str(clf_path)
        info['regressor_file'] = str(reg_path)
        info['classifier_exists'] = clf_path.exists()
        info['regressor_exists'] = reg_path.exists()
        
        return info


# 全局ML模型服务实例
ml_model_service = MLModelService()

