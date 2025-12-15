import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd

# 将项目根目录加入路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from BBA_dev.utils import generate_ifrs17_103_report, generate_ifrs17_104_report


SIGN_FIX_COLUMNS = [
    # 跑批脚本 run_batch_process_assumption.py 写CSV时会对这两列做取反（历史原因）
    # 为了让 103/104 报表逻辑与“模拟器原始口径”一致，这里默认做自动校准
    "保险合同收入_摊销的CSM",
    "IFIE_P&L_未到期_CSM",
]


DERIVED_103_COLUMNS = [
    "opening_bel",
    "opening_ra",
    "opening_csm",
    "opening_lc",
    "opening_lic",
    "closing_bel",
    "closing_ra",
    "closing_csm",
    "closing_lic",
    "nb_initial_lc",
]


def _safe_filename(text: str) -> str:
    if text is None:
        return ""
    s = str(text).strip()
    for ch in ['\\', '/', ':', '*', '?', '"', '<', '>', '|']:
        s = s.replace(ch, "_")
    return s


def _normalize_certi_no(val) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    s = str(val).strip()
    if s == "" or s.lower() == "nan":
        return None
    return s


def _coerce_year(val) -> Optional[int]:
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    try:
        return int(val)
    except Exception:
        s = str(val).strip()
        if s == "" or s.lower() == "nan":
            return None
        return int(float(s))


def _fill_nan_numeric_to_zero(df: pd.DataFrame) -> pd.DataFrame:
    # 除 policy_no/certi_no/year 外都当作数值字段，NaN 统一置零，避免 Decimal('nan') 传播
    df = df.copy()
    for col in df.columns:
        if col in ("policy_no", "certi_no", "year"):
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            df[col] = df[col].fillna(0.0)
        else:
            # 有些列可能因混入空字符串导致object，这里尝试转数值
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return df


def _auto_fix_sign(df: pd.DataFrame, mode: str = "auto") -> Tuple[pd.DataFrame, Dict[str, bool]]:
    """
    mode:
      - none: 不处理
      - auto: 若某列绝大多数非零值为正，则整体取反（期望口径为“负数表示减少/费用”）
      - force_negative: 强制把非零值变成负数（取 -abs）
    """
    df = df.copy()
    applied = {}
    if mode == "none":
        return df, applied

    for col in SIGN_FIX_COLUMNS:
        if col not in df.columns:
            continue
        s = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        nz = s[s != 0]
        if len(nz) == 0:
            applied[col] = False
            continue
        if mode == "force_negative":
            df[col] = -nz.abs().reindex(s.index).fillna(0.0)
            applied[col] = True
            continue

        # auto
        pos_ratio = (nz > 0).mean()
        neg_ratio = (nz < 0).mean()
        if pos_ratio >= 0.60 and neg_ratio <= 0.40:
            df[col] = -s
            applied[col] = True
        else:
            applied[col] = False
    return df, applied


def _derive_fields_for_103(df: pd.DataFrame) -> pd.DataFrame:
    """
    103 报表脚本里会用到 opening_*/closing_* 以及 nb_initial_lc。
    跑批CSV默认没有这些字段，这里用已有列补齐：
      - closing_bel/ra/csm：来自“未到期责任负债_*”列
      - closing_lic：当前跑批逻辑未实现 LIC，统一 0
      - opening_*：最早年度期初按 0（从最早签单年份开始），后续年度由 103 脚本内部滚动
      - nb_initial_lc：用两条“亏损合同损益_新增合同…”相加近似
    """
    df = df.copy()

    # closing
    if "closing_bel" not in df.columns:
        df["closing_bel"] = (
            df.get("未到期责任负债_预期现金流_非亏损", 0.0)
            + df.get("未到期责任负债_预期现金流_亏损", 0.0)
        )
    if "closing_ra" not in df.columns:
        df["closing_ra"] = (
            df.get("未到期责任负债_非金融风险调整_非亏损", 0.0)
            + df.get("未到期责任负债_非金融风险调整_亏损", 0.0)
        )
    if "closing_csm" not in df.columns:
        df["closing_csm"] = df.get("未到期责任负债_CSM", 0.0)
    if "closing_lic" not in df.columns:
        df["closing_lic"] = 0.0

    # opening defaults (will only be used/validated for the first year in 103 script)
    for c in ["opening_bel", "opening_ra", "opening_csm", "opening_lc", "opening_lic"]:
        if c not in df.columns:
            df[c] = 0.0

    # nb_initial_lc
    if "nb_initial_lc" not in df.columns:
        df["nb_initial_lc"] = (
            df.get("亏损合同损益_新增合同预期现金流_赔付与费用现金流_亏损", 0.0)
            + df.get("亏损合同损益_新增合同非金融风险调整_亏损", 0.0)
        )

    return df


@dataclass(frozen=True)
class GroupKey:
    policy_no: str
    certi_no: Optional[str]


def _build_yearly_results(group_df: pd.DataFrame, key: GroupKey) -> List[Dict]:
    # 按year升序整理，生成器只需要 list[dict]
    group_df = group_df.sort_values("year", ascending=True)
    rows = []
    for _, r in group_df.iterrows():
        d = r.to_dict()
        d["policy_no"] = key.policy_no
        d["certi_no"] = key.certi_no
        d["year"] = int(d["year"])
        rows.append(d)
    return rows


def _generate_for_one(
    key: GroupKey,
    yearly_results: List[Dict],
    out_dir_103: str,
    out_dir_104: str,
    gen_103: bool,
    gen_104: bool,
) -> Tuple[GroupKey, Dict[str, Optional[str]], Optional[str]]:
    try:
        certi_part = f"_{_safe_filename(key.certi_no)}" if key.certi_no else ""
        out_paths = {"103": None, "104": None}

        if gen_103:
            os.makedirs(out_dir_103, exist_ok=True)
            out_103 = os.path.join(out_dir_103, f"ifrs17_103_report_{_safe_filename(key.policy_no)}{certi_part}.html")
            generate_ifrs17_103_report.main(
                yearly_results=yearly_results,
                output_html_path=out_103,
                policy_no=key.policy_no,
                certi_no=key.certi_no,
            )
            out_paths["103"] = out_103

        if gen_104:
            os.makedirs(out_dir_104, exist_ok=True)
            out_104 = os.path.join(out_dir_104, f"ifrs17_104_report_{_safe_filename(key.policy_no)}{certi_part}.html")
            generate_ifrs17_104_report.main(
                yearly_results=yearly_results,
                init_context=None,
                output_html_path=out_104,
                policy_no=key.policy_no,
                certi_no=key.certi_no,
            )
            out_paths["104"] = out_104

        return key, out_paths, None
    except Exception as e:
        return key, {"103": None, "104": None}, str(e)


def main():
    parser = argparse.ArgumentParser(
        description="基于跑批CSV（run_batch_process_assumption.py输出）批量生成IFRS17 103/104 HTML报表"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="输入CSV路径，例如 logs/bba_batch_results_assumption_202412-20%.csv",
    )
    parser.add_argument(
        "--output_dir",
        default=None,
        help="输出目录（默认：logs/ifrs17_reports_from_batch/<csv文件名不含扩展名>/）",
    )
    parser.add_argument("--workers", type=int, default=4, help="并行进程数（Windows下建议 1-4）")
    parser.add_argument("--limit", type=int, default=None, help="只处理前N个保单组合（调试用）")
    parser.add_argument("--policy", type=str, default=None, help="只处理指定policy_no（调试用）")
    parser.add_argument("--certi", type=str, default=None, help="只处理指定certi_no（调试用，可为空表示无批单）")
    parser.add_argument(
        "--aggregate",
        action="store_true",
        help="生成全量综合报表：按year对所有保单汇总求和，仅输出一套103/104（policy_no=ALL）",
    )
    parser.add_argument(
        "--sign_mode",
        choices=["auto", "none", "force_negative"],
        default="auto",
        help="CSM/IFIE_CSM符号校准策略（默认auto）",
    )
    parser.add_argument("--only_103", action="store_true", help="只生成103")
    parser.add_argument("--only_104", action="store_true", help="只生成104")

    args = parser.parse_args()

    input_csv = args.input
    if not os.path.exists(input_csv):
        raise FileNotFoundError(f"找不到输入文件: {input_csv}")

    csv_stem = os.path.splitext(os.path.basename(input_csv))[0]
    if args.output_dir:
        output_root = args.output_dir
    else:
        output_root = os.path.join(PROJECT_ROOT, "logs", "ifrs17_reports_from_batch", csv_stem)

    out_dir_103 = os.path.join(output_root, "103")
    out_dir_104 = os.path.join(output_root, "104")
    os.makedirs(output_root, exist_ok=True)

    gen_103 = True
    gen_104 = True
    if args.only_103 and not args.only_104:
        gen_104 = False
    if args.only_104 and not args.only_103:
        gen_103 = False

    # 读CSV
    df = pd.read_csv(input_csv, dtype={"policy_no": "string"}, low_memory=False)
    if "certi_no" not in df.columns:
        df["certi_no"] = None
    if "year" not in df.columns:
        raise ValueError("CSV缺少 year 列")

    # 规范化 key/year
    df["policy_no"] = df["policy_no"].astype(str).str.strip()
    df["certi_no"] = df["certi_no"].apply(_normalize_certi_no)
    df["year"] = df["year"].apply(_coerce_year)
    df = df[df["policy_no"].notna() & (df["policy_no"] != "")]
    df = df[df["year"].notna()]
    df["year"] = df["year"].astype(int)

    # 过滤调试条件
    if args.policy:
        df = df[df["policy_no"] == args.policy.strip()]
    if args.certi is not None:
        certi_filter = _normalize_certi_no(args.certi)
        df = df[df["certi_no"].fillna("").astype(str) == (certi_filter or "")]

    if len(df) == 0:
        print("⚠️ 过滤后无数据，结束。")
        return

    df = _fill_nan_numeric_to_zero(df)
    df, sign_applied = _auto_fix_sign(df, mode=args.sign_mode)

    # aggregate 模式：按 year 汇总所有数值字段，生成一套综合报表
    if args.aggregate:
        numeric_cols = [c for c in df.columns if c not in ("policy_no", "certi_no", "year")]
        agg = df.groupby("year", as_index=False)[numeric_cols].sum(numeric_only=True)
        agg["policy_no"] = "ALL"
        agg["certi_no"] = None
        # 调整列顺序（可读性）
        agg = agg[["policy_no", "certi_no", "year"] + numeric_cols]
        agg = _derive_fields_for_103(agg)

        key = GroupKey(policy_no="ALL", certi_no=None)
        yearly_results = _build_yearly_results(agg, key)

        print(f"输入: {input_csv}")
        print(f"输出目录: {output_root}")
        print("模式: aggregate（全量综合）")
        if args.sign_mode != "none":
            applied_cols = [k for k, v in sign_applied.items() if v]
            print(f"符号校准({args.sign_mode})已应用列: {applied_cols if applied_cols else '无'}")

        _, out_paths, err = _generate_for_one(key, yearly_results, out_dir_103, out_dir_104, gen_103, gen_104)
        if err:
            print(f"❌ 生成综合报表失败: {err}")
            raise SystemExit(1)
        print("=" * 80)
        print("✅ 综合报表生成完成")
        if gen_103:
            print(f"103: {out_paths['103']}")
        if gen_104:
            print(f"104: {out_paths['104']}")
        return

    # 明细模式（逐保单/批单）
    df = _derive_fields_for_103(df)

    # 分组（policy_no + certi_no）
    group_keys = []
    for (policy_no, certi_no), _ in df.groupby(["policy_no", "certi_no"], dropna=False):
        group_keys.append(GroupKey(policy_no=str(policy_no), certi_no=_normalize_certi_no(certi_no)))

    group_keys = sorted(group_keys, key=lambda k: (k.policy_no, k.certi_no or ""))
    if args.limit and args.limit > 0:
        group_keys = group_keys[: args.limit]

    print(f"输入: {input_csv}")
    print(f"输出目录: {output_root}")
    print(f"将处理保单组合数: {len(group_keys)}")
    if args.sign_mode != "none":
        applied_cols = [k for k, v in sign_applied.items() if v]
        print(f"符号校准({args.sign_mode})已应用列: {applied_cols if applied_cols else '无'}")

    # 逐组生成
    total = len(group_keys)
    done = 0
    failed = 0

    def get_group_df(k: GroupKey) -> pd.DataFrame:
        if k.certi_no:
            return df[(df["policy_no"] == k.policy_no) & (df["certi_no"] == k.certi_no)]
        return df[(df["policy_no"] == k.policy_no) & (df["certi_no"].isna())]

    # workers=1 时走串行，避免Windows多进程开销/环境问题
    if args.workers <= 1:
        for k in group_keys:
            gdf = get_group_df(k)
            yearly_results = _build_yearly_results(gdf, k)
            _, _, err = _generate_for_one(k, yearly_results, out_dir_103, out_dir_104, gen_103, gen_104)
            done += 1
            if err:
                failed += 1
                print(f"❌ 失败 {k.policy_no} {k.certi_no or ''}: {err}")
            if done % 50 == 0 or done == total:
                print(f"进度: {done}/{total}，失败: {failed}")
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futures = {}
            for k in group_keys:
                gdf = get_group_df(k)
                yearly_results = _build_yearly_results(gdf, k)
                fut = ex.submit(_generate_for_one, k, yearly_results, out_dir_103, out_dir_104, gen_103, gen_104)
                futures[fut] = k

            for fut in as_completed(futures):
                k = futures[fut]
                _, _, err = fut.result()
                done += 1
                if err:
                    failed += 1
                    print(f"❌ 失败 {k.policy_no} {k.certi_no or ''}: {err}")
                if done % 50 == 0 or done == total:
                    print(f"进度: {done}/{total}，失败: {failed}")

    print("=" * 80)
    print(f"✅ 完成：{done}/{total}，失败：{failed}")
    print(f"103输出: {out_dir_103 if gen_103 else '未生成'}")
    print(f"104输出: {out_dir_104 if gen_104 else '未生成'}")


if __name__ == "__main__":
    main()


