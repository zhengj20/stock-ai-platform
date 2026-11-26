#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略组合引擎 (Strategy Combination Engine)
==========================================
多策略信号融合系统，将不同选股策略的结果进行投票/加权合成。

功能：
  1. 策略结果加载（支持CSV/JSON/Dict输入）
  2. 投票融合（多数表决）
  3. 加权融合（按策略历史表现分配权重）
  4. 置信度评估（信号一致性分析）
  5. 冲突检测（不同策略给出相反建议时预警）

用法:
    python strategy_combo.py vote --results result1.json result2.json result3.json
    python strategy_combo.py weight --results *.json --weights '{"ml":0.4,"factor":0.3,"flow":0.3}'
    python strategy_combo.py conflict --results *.json

作者: Hermes Agent
版本: 1.0.0
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

import pandas as pd
import numpy as np


# ==================================================================
# 策略结果加载器
# ==================================================================

class StrategyResultLoader:
    """从不同格式加载策略结果"""
    
    @staticmethod
    def load_from_json(json_path: str) -> pd.DataFrame:
        """
        从JSON文件加载策略结果
        
        支持的格式：
          - multi-factor输出: {"results": [{"股票": "xxx", "综合得分": xxx}]}
          - ml-stock-picker输出: {"top_stocks": [{"stock_name": "xxx", "combined_score": xxx}]}
          - capital-flow输出: CSV格式的DataFrame
        """
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # 尝试识别格式
        if "top_stocks" in data:
            # ML选股格式
            df = pd.DataFrame(data["top_stocks"])
            if "stock_name" in df.columns:
                df.rename(columns={"stock_name": "股票"}, inplace=True)
            if "combined_score" in df.columns:
                df.rename(columns={"combined_score": "得分"}, inplace=True)
            df["策略来源"] = Path(json_path).stem
            return df[["股票", "得分", "策略来源"]] if all(c in df.columns for c in ["股票", "得分"]) else pd.DataFrame()
        
        elif "results" in data:
            # 多因子格式
            results = data["results"]
            if isinstance(results, list) and len(results) > 0:
                df = pd.DataFrame(results)
                if "股票" in df.columns and "综合得分" in df.columns:
                    df.rename(columns={"综合得分": "得分"}, inplace=True)
                    df["策略来源"] = Path(json_path).stem
                    return df[["股票", "得分", "策略来源"]]
        
        elif isinstance(data, list):
            # 直接是列表格式
            df = pd.DataFrame(data)
            if "stock" in df.columns:
                df.rename(columns={"stock": "股票"}, inplace=True)
            score_col = next((c for c in ["total_score", "得分", "score"] if c in df.columns), None)
            if score_col:
                df.rename(columns={score_col: "得分"}, inplace=True)
                df["策略来源"] = Path(json_path).stem
                return df[["股票", "得分", "策略来源"]]
        
        # 无法识别格式，返回空DataFrame
        print(f"  ⚠️ {json_path} 格式无法识别")
        return pd.DataFrame()
    
    @staticmethod
    def load_from_csv(csv_path: str, strategy_name: str = "") -> pd.DataFrame:
        """从CSV文件加载策略结果"""
        df = pd.read_csv(csv_path, encoding="utf-8-sig")
        
        # 尝试标准化列名
        col_map = {}
        for col in df.columns:
            c_lower = col.lower()
            if "股票" in col or "stock" in c_lower or "name" in c_lower:
                col_map[col] = "股票"
            elif "得分" in col or "score" in c_lower:
                col_map[col] = "得分"
        
        df.rename(columns=col_map, inplace=True)
        
        if "股票" in df.columns and "得分" in df.columns:
            df["策略来源"] = strategy_name or Path(csv_path).stem
            return df[["股票", "得分", "策略来源"]]
        
        print(f"  ⚠️ {csv_path} 缺少必要列")
        return pd.DataFrame()
    
    @staticmethod
    def load_from_dict(results: Dict[str, List[Dict]], strategy_name: str) -> pd.DataFrame:
        """从字典加载结果"""
        df = pd.DataFrame(results)
        if "股票" in df.columns and "得分" in df.columns:
            df["策略来源"] = strategy_name
            return df[["股票", "得分", "策略来源"]]
        return pd.DataFrame()


# ==================================================================
# 投票融合器
# ==================================================================

class VotingFuser:
    """多数表决融合"""
    
    @staticmethod
    def fuse(all_results: pd.DataFrame, top_n_per_strategy: int = 20, 
             min_votes: int = 2) -> pd.DataFrame:
        """
        投票融合：统计每只股票被多少个策略选中
        
        Args:
            all_results: 合并后的所有策略结果DataFrame
            top_n_per_strategy: 每个策略只考虑前N名
            min_votes: 最少票数阈值
            
        Returns:
            按票数排序的DataFrame
        """
        if all_results.empty:
            return pd.DataFrame()
        
        # 每个策略只取Top N
        ranked = []
        for source, group in all_results.groupby("策略来源"):
            top_n = group.nsmallest(top_n_per_strategy, "得分") if _is_lower_better(group) else group.nlargest(top_n_per_strategy, "得分")
            top_n["票数"] = 1
            ranked.append(top_n[["股票", "得分", "策略来源", "票数"]])
        
        if not ranked:
            return pd.DataFrame()
        
        combined = pd.concat(ranked, ignore_index=True)
        
        # 按股票分组，统计票数和平均得分
        vote_summary = combined.groupby("股票").agg(
            票数=("票数", "sum"),
            平均得分=("得分", "mean"),
            策略列表=("策略来源", lambda x: ", ".join(x))
        ).reset_index()
        
        # 过滤最少票数
        vote_summary = vote_summary[vote_summary["票数"] >= min_votes]
        
        # 按票数降序，票数相同按平均得分排序
        vote_summary = vote_summary.sort_values(
            ["票数", "平均得分"], 
            ascending=[False, False]
        ).reset_index(drop=True)
        
        vote_summary["排名"] = range(1, len(vote_summary) + 1)
        vote_summary["置信度"] = vote_summary["票数"] / combined["策略来源"].nunique() * 100
        
        return vote_summary
    
    @staticmethod
    def consensus_score(all_results: pd.DataFrame) -> Dict[str, Any]:
        """计算策略共识度"""
        n_strategies = all_results["策略来源"].nunique()
        
        # 找出所有策略共同选中的股票
        stock_votes = all_results.groupby("股票")["策略来源"].nunique().reset_index()
        stock_votes.columns = ["股票", "票数"]
        
        consensus = stock_votes[stock_votes["票数"] == n_strategies]
        
        return {
            "总策略数": n_strategies,
            "完全共识股票数": len(consensus),
            "完全共识股票": list(consensus["股票"]) if len(consensus) > 0 else [],
            "最高票数": int(stock_votes["票数"].max()) if not stock_votes.empty else 0,
        }


# ==================================================================
# 加权融合器
# ==================================================================

class WeightedFuser:
    """加权评分融合"""
    
    @staticmethod
    def fuse(all_results: pd.DataFrame, 
             weights: Optional[Dict[str, float]] = None) -> pd.DataFrame:
        """
        加权融合：按策略权重计算综合得分
        
        Args:
            all_results: 合并后的所有策略结果DataFrame
            weights: 策略权重字典，如 {"ml": 0.4, "factor": 0.3, "flow": 0.3}
                     None则等权
            
        Returns:
            按加权得分排序的DataFrame
        """
        if all_results.empty:
            return pd.DataFrame()
        
        # 标准化各策略得分到0-100范围
        normalized = all_results.copy()
        
        for source, group in normalized.groupby("策略来源"):
            mask = normalized["策略来源"] == source
            scores = normalized.loc[mask, "得分"]
            
            if scores.max() != scores.min():
                normalized.loc[mask, "标准化得分"] = (scores - scores.min()) / (scores.max() - scores.min()) * 100
            else:
                normalized.loc[mask, "标准化得分"] = 50.0
        
        # 计算权重
        sources = normalized["策略来源"].unique()
        if weights is None:
            weights = {s: 1.0 / len(sources) for s in sources}
        
        # 归一化权重（只考虑存在的策略）
        total_w = sum(weights.get(s, 0) for s in sources)
        norm_weights = {s: weights.get(s, 0) / total_w for s in sources if weights.get(s, 0) > 0}
        
        # 按股票分组，计算加权得分
        stock_scores = {}
        stock_strategies = {}
        
        for _, row in normalized.iterrows():
            stock = row["股票"]
            source = row["策略来源"]
            score = row["标准化得分"]
            
            if stock not in stock_scores:
                stock_scores[stock] = 0.0
                stock_strategies[stock] = []
            
            weight = norm_weights.get(source, 0)
            stock_scores[stock] += score * weight
            stock_strategies[stock].append(source)
        
        # 构建结果DataFrame
        result_list = []
        for stock, weighted_score in stock_scores.items():
            n_sources = len(stock_strategies[stock])
            result_list.append({
                "股票": stock,
                "加权得分": round(weighted_score, 2),
                "参与策略数": n_sources,
                "策略列表": ", ".join(stock_strategies[stock]),
                "置信度": round(n_sources / len(sources) * 100, 1)
            })
        
        result_df = pd.DataFrame(result_list)
        result_df = result_df.sort_values("加权得分", ascending=False).reset_index(drop=True)
        result_df["排名"] = range(1, len(result_df) + 1)
        
        return result_df


# ==================================================================
# 冲突检测器
# ==================================================================

class ConflictDetector:
    """策略信号冲突检测"""
    
    @staticmethod
    def detect(all_results: pd.DataFrame, 
               buy_threshold: float = 60.0,
               sell_threshold: float = 40.0) -> List[Dict[str, Any]]:
        """
        检测不同策略对同一股票给出相反信号
        
        Args:
            all_results: 合并后的所有策略结果DataFrame
            buy_threshold: 买入信号阈值（得分高于此值）
            sell_threshold: 卖出信号阈值（得分低于此值）
            
        Returns:
            冲突列表
        """
        conflicts = []
        
        for stock, group in all_results.groupby("股票"):
            scores = group[["策略来源", "得分"]].to_dict("records")
            
            buy_signals = [s["策略来源"] for s in scores if s["得分"] >= buy_threshold]
            sell_signals = [s["策略来源"] for s in scores if s["得分"] <= sell_threshold]
            
            if buy_signals and sell_signals:
                conflicts.append({
                    "股票": stock,
                    "冲突类型": "买入vs卖出",
                    "看多策略": ", ".join(buy_signals),
                    "看空策略": ", ".join(sell_signals),
                    "建议": "谨慎对待，等待信号明确"
                })
        
        return conflicts
    
    @staticmethod
    def divergence_report(all_results: pd.DataFrame) -> Dict[str, Any]:
        """生成策略分歧报告"""
        n_strategies = all_results["策略来源"].nunique()
        n_stocks = all_results["股票"].nunique()
        
        # 计算每只股票的得分标准差（衡量分歧程度）
        stock_stats = all_results.groupby("股票")["得分"].agg(["mean", "std", "count"]).reset_index()
        stock_stats.columns = ["股票", "平均得分", "得分标准差", "策略数"]
        
        # 高分歧：标准差>30
        high_divergence = stock_stats[stock_stats["得分标准差"] > 30]
        # 低分歧（共识）：标准差<10
        low_divergence = stock_stats[stock_stats["得分标准差"] < 10]
        
        return {
            "总股票数": n_stocks,
            "总策略数": n_strategies,
            "高分歧股票数": len(high_divergence),
            "高共识股票数": len(low_divergence),
            "平均分歧度": round(float(stock_stats["得分标准差"].mean()), 2) if not stock_stats.empty else 0,
        }


# ==================================================================
# 相关性分析器（去冗余加权）
# ==================================================================

class CorrelationAnalyzer:
    """策略间相关性分析，用于去冗余权重调整"""

    @staticmethod
    def compute_correlation_matrix(all_results: pd.DataFrame) -> np.ndarray:
        """
        计算各策略得分之间的 Pearson 相关系数矩阵。

        Args:
            all_results: 包含 ["股票", "得分", "策略来源"] 的 DataFrame

        Returns:
            (n_strategies, n_strategies) 的相关系数矩阵，行列索引对应 strategies 列表
        """
        pivot = all_results.pivot_table(index="股票", columns="策略来源", values="得分")
        return pivot.corr().values

    @staticmethod
    def adjust_weights_for_correlation(
        weights: Dict[str, float],
        all_results: pd.DataFrame,
        threshold: float = 0.7,
        penalty: float = 0.3,
    ) -> Dict[str, float]:
        """
        对高相关策略降低权重，减少冗余。

        逻辑：
          - correlation > threshold 的策略对，双方权重各乘以 (1 - penalty)
          - 所有权重重新归一化到和为 1.0

        Args:
            weights: {策略名: 原始权重}
            all_results: 策略结果 DataFrame
            threshold: 相关性阈值（默认 0.7）
            penalty: 惩罚比例（默认 0.3，即降 30%）

        Returns:
            调整后的权重字典
        """
        sources = list(weights.keys())
        n = len(sources)
        if n < 2:
            return weights.copy()

        corr_matrix = CorrelationAnalyzer.compute_correlation_matrix(all_results)
        source_idx = {s: i for i, s in enumerate(sources)}

        # 标记哪些策略需要降权（与任一其他策略相关 > threshold）
        penalized = set()
        for i in range(n):
            for j in range(i + 1, n):
                if abs(corr_matrix[i][j]) > threshold:
                    penalized.add(sources[i])
                    penalized.add(sources[j])

        adjusted = {}
        for s, w in weights.items():
            if s in penalized:
                adjusted[s] = w * (1 - penalty)
            else:
                adjusted[s] = w

        # 归一化
        total = sum(adjusted.values())
        if total > 0:
            adjusted = {s: v / total for s, v in adjusted.items()}

        return adjusted


# ==================================================================
# 组合引擎主类
# ==================================================================

class StrategyComboEngine:
    """策略组合引擎"""

    def __init__(self):
        self.loader = StrategyResultLoader()
        self.voting_fuser = VotingFuser()
        self.weighted_fuser = WeightedFuser()
        self.conflict_detector = ConflictDetector()
        self.correlation_analyzer = CorrelationAnalyzer()
    
    def load_results(self, file_paths: List[str]) -> pd.DataFrame:
        """加载多个策略结果文件"""
        all_dfs = []
        
        for path in file_paths:
            p = Path(path)
            if not p.exists():
                print(f"  ⚠️ 文件不存在: {path}")
                continue
            
            if p.suffix.lower() == ".json":
                df = self.loader.load_from_json(str(p))
            elif p.suffix.lower() == ".csv":
                df = self.loader.load_from_csv(str(p))
            else:
                print(f"  ⚠️ 不支持的文件格式: {path}")
                continue
            
            if not df.empty:
                all_dfs.append(df)
                print(f"  ✅ 加载 {path}: {len(df)}条记录")
        
        if not all_dfs:
            return pd.DataFrame()
        
        return pd.concat(all_dfs, ignore_index=True)
    
    def vote_fuse(self, all_results: pd.DataFrame, top_n: int = 20, 
                  min_votes: int = 2) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """执行投票融合"""
        result_df = self.voting_fuser.fuse(all_results, top_n_per_strategy=top_n, min_votes=min_votes)
        consensus = self.voting_fuser.consensus_score(all_results)
        return result_df, consensus
    
    def weight_fuse(self, all_results: pd.DataFrame, 
                    weights: Optional[Dict[str, float]] = None) -> pd.DataFrame:
        """执行加权融合"""
        return self.weighted_fuser.fuse(all_results, weights)
    
    def detect_conflicts(self, all_results: pd.DataFrame) -> Tuple[List[Dict], Dict]:
        """检测策略冲突和分歧"""
        conflicts = self.conflict_detector.detect(all_results)
        divergence = self.conflict_detector.divergence_report(all_results)
        return conflicts, divergence

    def smart_weight_fuse(
        self,
        all_results: pd.DataFrame,
        base_weights: Optional[Dict[str, float]] = None,
    ) -> pd.DataFrame:
        """
        智能加权融合：基于策略相关性自动调整权重后再做加权融合。

        Args:
            all_results: 合并后的所有策略结果 DataFrame
            base_weights: 基础权重字典，None 则等权

        Returns:
            按调整后加权得分排序的 DataFrame，额外包含 correlation_adjustment 列
        """
        if all_results.empty:
            return pd.DataFrame()

        sources = list(all_results["策略来源"].unique())

        # 确定基础权重
        if base_weights is None:
            base_weights = {s: 1.0 / len(sources) for s in sources}

        # 相关性调整
        adjusted_weights = self.correlation_analyzer.adjust_weights_for_correlation(
            base_weights, all_results
        )

        # 找出被降权的策略
        penalized_strategies = [
            s for s, w in adjusted_weights.items() if w < base_weights.get(s, 0)
        ]

        # 执行加权融合
        result_df = self.weighted_fuser.fuse(all_results, adjusted_weights)

        # 附加相关性调整信息
        adjustment_info = json.dumps(
            {
                "原始权重": {k: round(v, 4) for k, v in base_weights.items()},
                "调整后权重": {k: round(v, 4) for k, v in adjusted_weights.items()},
                "降权策略": penalized_strategies,
            },
            ensure_ascii=False,
        )
        result_df["correlation_adjustment"] = adjustment_info

        return result_df


# ==================================================================
# 辅助函数
# ==================================================================

def _is_lower_better(df: pd.DataFrame) -> bool:
    """判断得分是否是越低越好（当前默认都是越高越好）"""
    return False


# ==================================================================
# CLI入口
# ==================================================================

def main():
    parser = argparse.ArgumentParser(
        description="策略组合引擎 - 多策略信号融合",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
用法示例:
  # 投票融合（多数表决）
  python strategy_combo.py vote --results ml_result.json factor_result.json flow_result.json

  # 加权融合
  python strategy_combo.py weight --results *.json \\
      --weights '{"ml_output":0.4,"选股结果":0.3,"capital_flow":0.3}'

  # 冲突检测
  python strategy_combo.py conflict --results *.json

  # 完整分析（投票+加权+冲突）
  python strategy_combo.py full --results *.json
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="命令")
    
    # vote子命令
    vote_parser = subparsers.add_parser("vote", help="投票融合")
    vote_parser.add_argument("--results", nargs="+", required=True,
                            help="策略结果文件路径(JSON/CSV)")
    vote_parser.add_argument("--top_n", type=int, default=20,
                            help="每个策略考虑前N名 (默认: 20)")
    vote_parser.add_argument("--min_votes", type=int, default=2,
                            help="最少票数阈值 (默认: 2)")
    
    # weight子命令
    weight_parser = subparsers.add_parser("weight", help="加权融合")
    weight_parser.add_argument("--results", nargs="+", required=True,
                              help="策略结果文件路径")
    weight_parser.add_argument("--weights", type=str, default=None,
                              help='策略权重JSON，如 \'{"ml":0.4,"factor":0.3}\'' )
    
    # conflict子命令
    conflict_parser = subparsers.add_parser("conflict", help="冲突检测")
    conflict_parser.add_argument("--results", nargs="+", required=True,
                                help="策略结果文件路径")
    
    # full子命令
    full_parser = subparsers.add_parser("full", help="完整分析")
    full_parser.add_argument("--results", nargs="+", required=True,
                            help="策略结果文件路径")
    full_parser.add_argument("--weights", type=str, default=None,
                            help='加权融合的策略权重JSON')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    engine = StrategyComboEngine()
    
    # 加载结果
    print("📂 加载策略结果...")
    all_results = engine.load_results(args.results)
    
    if all_results.empty:
        print("❌ 没有有效数据")
        sys.exit(1)
    
    print(f"✅ 共加载 {len(all_results)} 条记录，{all_results['策略来源'].nunique()} 个策略\n")
    
    # 解析权重
    weights = None
    if hasattr(args, "weights") and args.weights:
        try:
            weights = json.loads(args.weights)
        except json.JSONDecodeError as e:
            print(f"❌ 权重JSON解析失败: {e}")
            sys.exit(1)
    
    if args.command == "vote":
        result_df, consensus = engine.vote_fuse(
            all_results, 
            top_n=args.top_n,
            min_votes=args.min_votes
        )
        
        print("=" * 80)
        print("🗳️ 投票融合结果:")
        print("=" * 80)
        if not result_df.empty:
            display_cols = ["排名", "股票", "票数", "平均得分", "置信度", "策略列表"]
            available_cols = [c for c in display_cols if c in result_df.columns]
            print(result_df[available_cols].to_string(index=False))
        
        print(f"\n📊 共识分析:")
        print(json.dumps(consensus, ensure_ascii=False, indent=2))
    
    elif args.command == "weight":
        result_df = engine.weight_fuse(all_results, weights)
        
        print("=" * 80)
        print("⚖️ 加权融合结果:")
        print("=" * 80)
        if not result_df.empty:
            display_cols = ["排名", "股票", "加权得分", "置信度", "策略列表"]
            available_cols = [c for c in display_cols if c in result_df.columns]
            print(result_df[available_cols].to_string(index=False))
    
    elif args.command == "conflict":
        conflicts, divergence = engine.detect_conflicts(all_results)
        
        print("=" * 80)
        print("⚠️ 策略冲突检测:")
        print("=" * 80)
        
        if conflicts:
            for c in conflicts:
                print(f"\n  📌 {c['股票']}:")
                print(f"     看多: {c['看多策略']}")
                print(f"     看空: {c['看空策略']}")
                print(f"     建议: {c['建议']}")
        else:
            print("\n  ✅ 未检测到明显冲突")
        
        print(f"\n📊 分歧报告:")
        print(json.dumps(divergence, ensure_ascii=False, indent=2))
    
    elif args.command == "full":
        # 投票融合
        vote_df, consensus = engine.vote_fuse(all_results)
        
        print("=" * 80)
        print("🗳️ 投票融合结果:")
        print("=" * 80)
        if not vote_df.empty:
            display_cols = ["排名", "股票", "票数", "平均得分", "置信度"]
            available_cols = [c for c in display_cols if c in vote_df.columns]
            print(vote_df[available_cols].to_string(index=False))
        
        # 加权融合
        weight_df = engine.weight_fuse(all_results, weights)
        
        print(f"\n{'=' * 80}")
        print("⚖️ 加权融合结果:")
        print("=" * 80)
        if not weight_df.empty:
            display_cols = ["排名", "股票", "加权得分", "置信度"]
            available_cols = [c for c in display_cols if c in weight_df.columns]
            print(weight_df[available_cols].to_string(index=False))
        
        # 冲突检测
        conflicts, divergence = engine.detect_conflicts(all_results)
        
        print(f"\n{'=' * 80}")
        print("⚠️ 策略冲突:")
        print("=" * 80)
        
        if conflicts:
            for c in conflicts[:5]:  # 只显示前5个
                print(f"  📌 {c['股票']}: {c['看多策略']} vs {c['看空策略']}")
        else:
            print("  ✅ 未检测到明显冲突")
        
        print(f"\n📊 共识分析:")
        print(json.dumps(consensus, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
