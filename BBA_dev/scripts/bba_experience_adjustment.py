import pandas as pd
from decimal import Decimal, getcontext
from dateutil.relativedelta import relativedelta
from datetime import datetime
from pathlib import Path
import sys

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bba_model.data_access.db_utils import get_db_connection
from BBA_dev.utils.pv_source_loader import load_pv_source_data

# --- 1. 参数配置 ---
getcontext().prec = 38
POLICY_NO = '1440003000004501220210000004'

# 精算假设参数
RATIO_IACF      = Decimal('0.20')  # 初始获取费用率 (20%)
RATIO_CLAIM     = Decimal('0.50')  # 赔付率 (50%)
RATIO_MAINT_EXP = Decimal('0.10')  # 维持费用率 (10%)
RATIO_RA        = Decimal('0.03')  # 非金融风险调整率 (3%)
EXP_ADJ_RATIO   = Decimal('1.0')   # 经验调整占比 (100% 计入)
USE_OCI_OPTION  = True             # OCI 选择权 (True = 拆分, 利率变动计入 OCI)

class CalculationLogger:
    @staticmethod
    def log_section(title):
        print(f"\n{'='*100}")
        print(f" {title}")
        print(f"{'='*100}")

    @staticmethod
    def log_item(item_name, definition, formula, values, result, note=None):
        print(f"\n[{item_name}]")
        print(f"  定义: {definition}")
        print(f"  公式: {formula}")
        
        # Format values for display
        val_str_list = []
        for k, v in values.items():
            if isinstance(v, Decimal):
                val_str_list.append(f"{k}={v:,.2f}")
            else:
                val_str_list.append(f"{k}={v}")
        
        print(f"  数值: {', '.join(val_str_list)}")
        
        if isinstance(result, Decimal):
            print(f"  结果: {result:,.2f}")
        else:
            print(f"  结果: {result}")
            
        if note:
            print(f"  说明: {note}")

# 注意：所有现值计算函数已删除，必须从PV原材料数据读取
# 系统要求必须使用PV原材料数据，不允许使用旧的计算方式

def calculate_bba_measurement():
    logger = CalculationLogger()
    logger.log_section(f"BBA计量展示：CSM 构建、经验调整与计息 (使用真实数据库利率曲线)")
    print(f"保单号: {POLICY_NO}")
    print(f"假设: 赔付={RATIO_CLAIM:.0%}, 维费={RATIO_MAINT_EXP:.0%}, RA={RATIO_RA:.0%}")

    conn = get_db_connection()
    
    try:
        # --- 1. 获取保单数据并确定计量起点 ---
        print("\n[Step 0] 获取保单数据并确定计量起点...")
        data_query = f"""
            SELECT sum_premium_no_tax, under_write_date, start_date, end_date, stat_date
            FROM bi_to_cas25.pi_policy_data_info_mon 
            WHERE policy_no = '{POLICY_NO}' 
            ORDER BY stat_date DESC LIMIT 1
        """
        df_data = pd.read_sql_query(data_query, conn)
        
        if df_data.empty:
            print("错误：未找到保单数据。")
            return
            
        policy_data = df_data.iloc[0]
        
        under_write_date = policy_data['under_write_date']
        if isinstance(under_write_date, pd.Timestamp):
            under_write_date = under_write_date.date()
            
        start_date = policy_data['start_date']
        end_date = policy_data['end_date']
        year = under_write_date.year
        val_month_str = under_write_date.strftime('%Y%m')
        
        delta = relativedelta(end_date, start_date)
        total_months = delta.years * 12 + delta.months
        if total_months == 0 and delta.days > 0: total_months = 1
            
        print(f"✅ 签单日 (初始确认日): {under_write_date}")
        print(f"✅ 计量年度: {year}年")
        print(f"✅ 对应利率曲线月份: {val_month_str}")
        print(f"ℹ️  保单起期: {start_date.date()} -> 止期: {end_date.date()} (总月数: {total_months})")

        # --- 2. 加载PV原材料数据（强制要求） ---
        print(f"\n[Step 0.1] 加载PV原材料数据...")
        pv_source_data = load_pv_source_data(POLICY_NO)
        if pv_source_data is None:
            raise ValueError(
                f"❌ 错误: PV原材料数据不可用！\n"
                f"   保单号: {POLICY_NO}\n"
                f"   请先运行 pv_calculator.py 生成PV原材料数据文件: logs/pv_source_data_{POLICY_NO}.json\n"
                f"   系统要求必须使用PV原材料数据，不允许使用旧的计算方式。"
            )
        
        # 获取初始确认评估月的数据
        pv_data_ini = pv_source_data.get_data(val_month_str)
        if pv_data_ini is None:
            raise ValueError(
                f"❌ 错误: 找不到评估月 {val_month_str} 的PV原材料数据！\n"
                f"   签单日期: {under_write_date}\n"
                f"   请确保 pv_calculator.py 已计算该评估月的PV数据。"
            )
        
        # 获取期末评估月的数据（如果存在）
        eop_month_str = f"{year}12"
        pv_data_eop = pv_source_data.get_data(eop_month_str)
        
        print(f"✅ 成功加载PV原材料数据（初始确认月: {val_month_str}）")
        if pv_data_eop:
            print(f"✅ 成功加载PV原材料数据（期末评估月: {eop_month_str}）")
        
        # 保留利率曲线用于计息因子计算（如果需要）
        rates_query = f"""
            SELECT term_month, forward_disrate_value 
            FROM measure_platform.conf_measure_month_disrate
            WHERE val_month = '{val_month_str}'
            ORDER BY term_month
        """
        rates_df = pd.read_sql_query(rates_query, conn)
        if rates_df.empty:
            print(f"⚠️ 警告: 未找到 {val_month_str} 的利率曲线（仅用于计息因子计算）。")

        # ==========================================================================================
        # Part 1: 初始确认 (Initial Recognition) - New Business
        # ==========================================================================================
        logger.log_section("Part 1: 初始确认 (Initial Recognition) - New Business")

        actual_premium = Decimal(policy_data['sum_premium_no_tax'] or 0)
        
        # 1.1 保费现值
        logger.log_item(
            "当年新增合同_初始确认_预期保费现值",
            "初始确认时，预期未来收到的保费折现值",
            "Actual Premium (Assuming single premium)",
            {"Actual Premium": actual_premium},
            actual_premium
        )
        
        # 1.2 IACF 现值
        val_iacf = actual_premium * RATIO_IACF
        logger.log_item(
            "当年新增合同_初始确认_IACF现值",
            "初始确认时，预期支付的获取费用折现值",
            "Premium * IACF Ratio",
            {"Premium": actual_premium, "IACF Ratio": RATIO_IACF},
            val_iacf
        )

        # 1.3 赔付现值（从PV原材料数据读取）
        # 预期当期 + 预期未来
        init_fut_claim_current = pv_data_ini.get_field('Pvfl_Nb_Ini_Cca_Rec_Lkd_Cla_Amt')
        init_fut_claim_future = pv_data_ini.get_field('Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt')
        init_fut_claim = init_fut_claim_current + init_fut_claim_future
        logger.log_item(
            "当年新增合同_初始确认_预期赔付现值",
            "初始确认时，预期未来赔付支出的折现值（从PV原材料数据读取）",
            "Pvfl_Nb_Ini_Cca_Rec_Lkd_Cla_Amt + Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt",
            {"Source": "PV原材料数据", "Current": init_fut_claim_current, "Future": init_fut_claim_future},
            init_fut_claim,
            note="从pv_calculator.py计算的PV原材料数据中读取"
        )

        # 1.4 维费现值（从PV原材料数据读取）
        # 预期当期 + 预期未来
        init_fut_maint_current = pv_data_ini.get_field('Pvfl_Nb_Ini_Cca_Rec_Lkd_Mtn_Amt')
        init_fut_maint_future = pv_data_ini.get_field('Pvfl_Nb_Ini_Cfa_Rec_Lkd_Mtn_Amt')
        init_fut_maint = init_fut_maint_current + init_fut_maint_future
        logger.log_item(
            "当年新增合同_初始确认_预期维费现值",
            "初始确认时，预期未来维持费用的折现值（从PV原材料数据读取）",
            "Pvfl_Nb_Ini_Cca_Rec_Lkd_Mtn_Amt + Pvfl_Nb_Ini_Cfa_Rec_Lkd_Mtn_Amt",
            {"Source": "PV原材料数据", "Current": init_fut_maint_current, "Future": init_fut_maint_future},
            init_fut_maint,
            note="从pv_calculator.py计算的PV原材料数据中读取"
        )

        # 1.5 RA（从PV原材料数据读取）
        # 预期当期 + 预期未来
        init_ra_current = pv_data_ini.get_field('Pvfl_Nb_Ini_Cca_Rec_Lkd_Rad_Amt')
        init_ra_future = pv_data_ini.get_field('Pvfl_Nb_Ini_Cfa_Rec_Lkd_Rad_Amt')
        init_ra = init_ra_current + init_ra_future
        logger.log_item(
            "当年新增合同_初始确认_非金融风险调整(RA)",
            "初始确认时，对非金融风险的调整额（从PV原材料数据读取）",
            "Pvfl_Nb_Ini_Cca_Rec_Lkd_Rad_Amt + Pvfl_Nb_Ini_Cfa_Rec_Lkd_Rad_Amt",
            {"Source": "PV原材料数据", "Current": init_ra_current, "Future": init_ra_future},
            init_ra,
            note="从pv_calculator.py计算的PV原材料数据中读取"
        )

        # 1.6 初始 CSM/LC 计算
        pv_inflow = actual_premium
        pv_outflow = val_iacf + init_fut_claim + init_fut_maint
        net_inflow = pv_inflow - pv_outflow
        initial_csm_calc = net_inflow - init_ra
        
        nb_initial_csm = Decimal('0')
        nb_initial_lc = Decimal('0')
        
        if initial_csm_calc >= 0:
            nb_initial_csm = initial_csm_calc
            csm_status = "Profitable (CSM)"
        else:
            nb_initial_lc = -initial_csm_calc
            csm_status = "Onerous (Loss Component)"

        logger.log_item(
            "当年新增合同_初始确认_CSM/LC",
            "初始确认时的合同服务边际或亏损",
            "Inflow - Outflow - RA",
            {
                "Inflow (Premium)": pv_inflow,
                "Outflow (IACF+Claim+Maint)": pv_outflow,
                "Net Inflow": net_inflow,
                "RA": init_ra
            },
            initial_csm_calc,
            note=f"判定结果: {csm_status}. Initial CSM = {nb_initial_csm:,.2f}, Initial LC = {nb_initial_lc:,.2f}"
        )

        # ==========================================================================================
        # Part 2: 经验调整 (Experience Adjustment)
        # ==========================================================================================
        logger.log_section("Part 2: 经验调整 (Experience Adjustment)")
        
        # 模拟实际发生额 (需确认来源)
        # 假设当前评估日为年底，计算从初始确认日到年底的实际发生额
        # 这里暂时假设实际 = 预期 (无偏差)，但在日志中展示公式
        
        # 计算当期预期流出 (从初始确认到年底)
        # 简单按月数比例估算预期流出 (Nominal)
        months_passed = 12 - under_write_date.month + 1 # 包含当月
        if months_passed < 0: months_passed = 0
        
        expected_claim_nominal = (actual_premium * RATIO_CLAIM / total_months) * months_passed
        actual_claim_incurred = expected_claim_nominal # 暂定实际=预期
        
        expected_maint_nominal = (actual_premium * RATIO_MAINT_EXP / total_months) * months_passed
        actual_maint_incurred = expected_maint_nominal # 暂定实际=预期

        # 2.1 保费现金流变化
        # 假设一次性趸交，且已在初始确认时全部收到，故后续无保费现金流变化
        prem_var = Decimal('0')
        logger.log_item(
            "保费现金流变化 (经验调整)",
            "实际保费与预期保费的差异",
            "Actual Premium Received - Expected Premium Received",
            {"Actual": actual_premium, "Expected": actual_premium}, # 假设全部收到
            prem_var
        )

        # 2.2 IACF 现金流变化 (新增)
        # 假设实际 IACF = 预期 IACF
        expected_iacf_nominal = actual_premium * RATIO_IACF
        actual_iacf_incurred = expected_iacf_nominal # 暂定实际=预期
        
        iacf_var = actual_iacf_incurred - expected_iacf_nominal
        logger.log_item(
            "IACF 现金流变化 (经验调整)",
            "实际获取费用与预期获取费用的差异",
            "Actual IACF - Expected IACF",
            {"Actual IACF": actual_iacf_incurred, "Expected IACF": expected_iacf_nominal},
            iacf_var,
            note="当前暂无实际IACF数据，假设为0偏差"
        )

        # ==========================================================================================
        # Part 3: 计息 (Interest Accretion)
        # ==========================================================================================
        logger.log_section("Part 3: 计息 (Interest Accretion)")

        # 3.1 确定计息因子
        # 注意：计息因子需要基于利率曲线计算，这里保留计算逻辑
        # 但可以考虑从PV原材料数据的元数据中获取，或使用简化的计算方式
        eop_date = datetime(year, 12, 31).date()
        months_accretion = eop_date.month - under_write_date.month
        if months_accretion < 0: months_accretion = 0
        
        # 简化的计息因子计算（基于利率曲线）
        # 如果rates_df为空，使用默认值0
        if rates_df.empty:
            accretion_factor = Decimal('0')
        else:
            rates_map = dict(zip(rates_df['term_month'], rates_df['forward_disrate_value'].apply(Decimal)))
            cum_rate = Decimal('1.0')
            for t in range(1, months_accretion + 1):
                r_t = rates_map.get(t, Decimal('0'))
                cum_rate *= (Decimal('1') + r_t)
            accretion_factor = cum_rate - Decimal('1')
        
        logger.log_item(
            "计息因子",
            "从初始确认日到期末的累积利率因子",
            "PRODUCT(1+r_t) - 1",
            {"Start Month": under_write_date.month, "End Month": 12, "Months": months_accretion},
            accretion_factor
        )

        # 3.2 新增合同 CSM 计息
        nb_interest_csm = nb_initial_csm * accretion_factor
        logger.log_item(
            "当年新增合同_CSM计息",
            "新增合同CSM随时间推移产生的利息",
            "Initial CSM * Accretion Factor",
            {"Initial CSM": nb_initial_csm, "Factor": accretion_factor},
            nb_interest_csm
        )

        # 3.3 新增合同 LC 计息
        nb_interest_lc = nb_initial_lc * accretion_factor
        logger.log_item(
            "当年新增合同_LC计息",
            "新增合同亏损成分随时间推移产生的利息",
            "Initial LC * Accretion Factor",
            {"Initial LC": nb_initial_lc, "Factor": accretion_factor},
            nb_interest_lc
        )

        # ==========================================================================================
        # Part 4: CSM/LC 判定与分配 (Allocation & Determination)
        # ==========================================================================================
        logger.log_section("Part 4: CSM/LC 判定与分配 (Allocation & Determination)")
        
        # 4.0 被CSM/LC吸收的变化 (Changes Absorbed by CSM/LC)
        # 包括：保费、IACF、赔付、维持、RA 等的变化 (通常指对未来现金流现值的调整)
        # 注意：此处为了演示，将计算出的 Variance 视为对 CSM 的调整
        
        # A. 赔付变化 (视为未来假设变更的影响)
        # B. 维费变化
        # C. RA 变化 (未来部分) - 假设为 0
        ra_change_future = Decimal('0')
        
        # 计算总 CSM 调整额
        # 公式: Total = Prem_Var (Future) - IACF_Var (Future) - RA_Change
        # 用户指示: 目前仅关注保费、IACF 与 RA 相关的经验调整
        # 假设所有 Variance 都被吸收至 CSM/LC
        
        exp_adj_csm_impact = prem_var - iacf_var - ra_change_future
        
        logger.log_item(
            "被CSM/LC吸收的变化_合计",
            "调整CSM/LC的总金额 (保费 - IACF - RA)",
            "Prem_Var - IACF_Var - RA_Change",
            {
                "Prem Var": prem_var,
                "IACF Var": iacf_var,
                "RA Change": ra_change_future
            },
            exp_adj_csm_impact,
            note="根据指示，将这些变化计入CSM调整"
        )

        # 4.1 LC 分摊比例 (New Business)
        # 公式: NB_LC / (NB_LC + NB_PV_Outflows_at_Initial) ? 
        # 图片公式: NB_LC / (NB_LC + NB_Expected_Claims_PV + NB_Expected_Maint_PV + NB_RA)
        # 注意：分母应该是 "Loss Component + PV of Future Cash Outflows" 也就是 "PV of Future Cash Outflows - PV of Future Cash Inflows" (如果 LC = Out - In)
        # 让我们看图片定义:
        # NB_LC分摊比例 = IF(NB_Initial_LC > 0, NB_Initial_LC / (NB_Initial_LC + NB_Initial_Claim_PV + NB_Initial_Maint_PV + NB_Initial_RA), 0)
        
        nb_lc_ratio = Decimal('0')
        denom = nb_initial_lc + init_fut_claim + init_fut_maint + init_ra
        
        if nb_initial_lc > 0 and denom > 0:
            nb_lc_ratio = nb_initial_lc / denom
            
        logger.log_item(
            "当年新增合同_LC分摊比例",
            "用于将变动分摊到亏损成分的比例",
            "Initial LC / (Initial LC + Claim PV + Maint PV + RA)",
            {
                "Initial LC": nb_initial_lc, 
                "Claim PV": init_fut_claim,
                "Maint PV": init_fut_maint,
                "RA": init_ra
            },
            nb_lc_ratio
        )

        # 4.2 分摊的经验调整 (Allocated Experience Adjustment)
        # 图片公式: NB_Allocated_Exp_Adj = (NB_Exp_Adj_Claims + NB_Exp_Adj_Maint) * NB_LC_Ratio
        # 注意：这里是 "Changes in estimates" 还是 "Experience Adjustment"?
        # 图片中 "LC分摊IFIE" 包含 "赔付与费用", "非金融风险调整", "利率变化".
        # 这里我们只计算了 经验调整 (Experience Adjustment)。
        # 假设 exp_adj_csm_impact 是总变动。
        
        # 这里的逻辑是：如果存在 LC，那么一部分“不利变动”或“有利变动”会由 LC 吸收/释放，而不是 CSM。
        # 但通常 Experience Adjustment 直接计入 P&L (如果与过往服务相关) 或 CSM (如果与未来服务相关)。
        # BBA下，Current Service 的 Experience Variance 直接进 P&L，不调 CSM。
        # 只有 Future Service 的变动才调 CSM。
        # **关键点**: 图片中的 "经验调整" 似乎是指 "与未来服务相关的变动" 或者是 "投资成分的经验调整"？
        # 或者图片标题是 "Experience Adjustment"，但内容其实是 "Changes in estimates of future cash flows"?
        # 让我们假设 exp_adj_csm_impact 是需要调整 CSM 的部分。
        
        allocated_lc_exp_adj = exp_adj_csm_impact * nb_lc_ratio
        
        logger.log_item(
            "当年新增合同_分摊的LC变动(被吸收的变化)",
            "按比例分摊给LC的变化额",
            "Total Absorbed Changes * LC Ratio",
            {"Total Impact": exp_adj_csm_impact, "Ratio": nb_lc_ratio},
            allocated_lc_exp_adj
        )

        # 4.3 期末余额计算
        # 汇总
        
        # CSM 变动
        # 期初(0) + 新增(nb_initial_csm) + 计息(nb_interest_csm) + 吸收的变化(exp_adj_csm_impact - allocated_lc_exp_adj)
        # 注意：如果 exp_adj_csm_impact 是负的（亏损），且有 LC，那么一部分由 LC 承担。
        # CSM 承担的部分 = Total - Allocated to LC
        
        csm_absorbed = exp_adj_csm_impact - allocated_lc_exp_adj
        
        end_csm_before_amort = nb_initial_csm + nb_interest_csm + csm_absorbed
        
        # LC 变动
        # 期初(0) + 新增(nb_initial_lc) + 计息(nb_interest_lc) - 分摊的变化(allocated_lc_exp_adj)
        # 注意符号：如果 exp_adj_csm_impact 是负（不利），allocated 是负。
        # LC 余额应该增加（亏损扩大）。所以应该是 LC - allocated (if allocated is negative impact) -> LC + abs(allocated)
        # 让我们统一符号：
        # LC 是正值代表亏损余额。
        # 不利变动 (exp_adj < 0)。
        # allocated_lc_exp_adj < 0.
        # LC 余额变动 = - allocated_lc_exp_adj (即增加亏损)
        
        lc_change = -allocated_lc_exp_adj
        end_lc_before_amort = nb_initial_lc + nb_interest_lc + lc_change

        # ==========================================================================================
        # Part 6: IACF 摊销 (IACF Amortization)
        # ==========================================================================================
        logger.log_section("Part 6: IACF 摊销 (IACF Amortization)")
        
        # 逻辑: IACF 不考虑时间价值 (Interest = 0)
        
        # 6.1 期初待摊 IACF 余额
        bop_iacf = Decimal('0') # 新增合同
        logger.log_item(
            "年初待摊IACF余额",
            "期初尚未摊销的获取费用余额",
            "BOP Balance",
            {"BOP": bop_iacf},
            bop_iacf
        )
        
        # 6.2 期初待摊 IACF 计息
        # 逻辑: 当IACF是否考虑货币时间价值 = 0 -> 0
        iacf_interest_bop = Decimal('0')
        logger.log_item(
            "年初待摊IACF计息",
            "期初余额产生的利息 (不考虑时间价值)",
            "0 (Logic: No Time Value)",
            {},
            iacf_interest_bop
        )
        
        # 6.3 当年新增 IACF
        # 逻辑: 否则 - (新增合同-初始确认-预期未来IACF(不折现) + ...)
        # 简化为: 预期 IACF (名义值)
        nb_iacf_addition = expected_iacf_nominal
        logger.log_item(
            "当年新增IACF",
            "本期新增业务带来的获取费用 (名义值)",
            "Expected IACF Nominal",
            {"Expected IACF": expected_iacf_nominal},
            nb_iacf_addition
        )
        
        # 6.4 当年新增 IACF 计息
        # 逻辑: 当IACF是否考虑货币时间价值 = 0 -> 0
        iacf_interest_nb = Decimal('0')
        logger.log_item(
            "当年新增IACF计息",
            "新增IACF产生的利息 (不考虑时间价值)",
            "0 (Logic: No Time Value)",
            {},
            iacf_interest_nb
        )
        
        # 6.5 IACF 变化 (Variance)
        # 逻辑: 否则: - (Actual - Expected) ...
        # 这里使用 Part 2 计算的 iacf_var (Actual - Expected)
        # 注意符号: 如果 Actual > Expected, 意味着花费更多。
        # 在待摊余额中，这通常增加待摊资产 (Asset Increase)。
        # 公式: IACF变化 = Actual - Expected
        iacf_change = iacf_var
        logger.log_item(
            "IACF变化",
            "实际与预期获取费用的差异",
            "Actual IACF - Expected IACF",
            {"Actual": actual_iacf_incurred, "Expected": expected_iacf_nominal},
            iacf_change
        )
        
        # 6.6 IACF 经验调整
        # 逻辑: - 经验调整中IACF
        # 暂时设为 0
        iacf_exp_adj = Decimal('0')
        logger.log_item(
            "IACF经验调整",
            "其他经验调整项",
            "Manual Input",
            {},
            iacf_exp_adj
        )
        
        # 6.7 摊销比例
        # 逻辑: 简单按时间比例 (Passed Months / Total Months)
        # 2021年: 7个月. 总: 363个月.
        iacf_amort_ratio = Decimal('0')
        if total_months > 0:
            iacf_amort_ratio = Decimal(months_passed) / Decimal(total_months)
            
        logger.log_item(
            "IACF摊销比例",
            "本期摊销的比例 (基于时间)",
            "Passed Months / Total Months",
            {"Passed": months_passed, "Total": total_months},
            iacf_amort_ratio
        )
        
        # 6.8 摊销的 IACF
        # 逻辑: - (sum(余额, 计息, 新增, 新增计息, 变化) * 比例 + 经验调整)
        # 注意: 这里的 "IACF经验调整" 在公式里是加在括号内还是外?
        # 文本: - (sum(...) * 比例 + IACF经验调整)
        
        iacf_balance_base = bop_iacf + iacf_interest_bop + nb_iacf_addition + iacf_interest_nb + iacf_change
        
        iacf_amort_amount = - (iacf_balance_base * iacf_amort_ratio + iacf_exp_adj)
        
        logger.log_item(
            "摊销的IACF",
            "本期摊销计入费用的金额 (负值代表减少余额)",
            "- (Sum(Balance+Additions+Var) * Ratio + ExpAdj)",
            {"Base Sum": iacf_balance_base, "Ratio": iacf_amort_ratio, "ExpAdj": iacf_exp_adj},
            iacf_amort_amount
        )
        
        # 6.9 期末待摊 IACF 余额
        # 逻辑: Sum(All components)
        eop_iacf_balance = iacf_balance_base + iacf_exp_adj + iacf_amort_amount # Wait, exp_adj is already in amort formula?
        # Text: Sum(年初... 摊销的IACF)
        # Let's check if exp_adj is a separate line item in the sum.
        # Text: Sum(年初待摊IACF余额，... IACF经验调整，摊销的IACF)
        # So yes, we add it.
        
        eop_iacf_balance = iacf_balance_base + iacf_exp_adj + iacf_amort_amount
        
        logger.log_item(
            "期末待摊IACF余额",
            "期末剩余的待摊获取费用",
            "Sum(BOP + Interest + NB + NB Interest + Var + ExpAdj + Amortization)",
            {
                "Base": iacf_balance_base,
                "ExpAdj": iacf_exp_adj,
                "Amortization": iacf_amort_amount
            },
            eop_iacf_balance
        )

        # ==========================================================================================
        # Part 7: 保险合同收入 (Insurance Revenue)
        # ==========================================================================================
        logger.log_section("Part 7: 保险合同收入 (Insurance Revenue)")
        
        # 7.1 预期赔付与费用释放 (Expected Claims & Expenses Release)
        # 逻辑: 期初预期 - 期末预期 (调整后)
        # 简化逻辑: 
        # 1. 计算期初预期在当期的释放 (BOP Expected PV - EOP Expected PV of BOP Cashflows)
        # 2. 计算新增业务在当期的释放 (NB Initial PV - EOP Expected PV of NB Cashflows)
        # 由于我们没有详细的逐单现金流，这里使用简化近似：
        # 释放额 ≈ (期初PV + 新增PV) * (1 + 利率) - 期末PV
        # 或者更简单：当期预期的名义流出 (Nominal Outflow)
        # BBA下，Revenue = Expected Claims + Expected Expenses + RA Release + CSM Release + IACF Amortization
        # 注意：不包含投资成分。
        
        # 计算当期预期的赔付和维费 (Nominal)
        # 已经在 Part 2 计算过: expected_claim_nominal, expected_maint_nominal
        # 但 Revenue 需要的是 "Expected Claims & Expenses incurred in the period"
        # 这正是 expected_claim_nominal + expected_maint_nominal
        
        revenue_expected_claims = expected_claim_nominal
        revenue_expected_maint = expected_maint_nominal
        
        # 考虑亏损分摊 (Loss Component Allocation)
        # 如果有 LC，部分预期赔付/费用被视为 "Repayment of LC"，不计入 Revenue。
        # 分摊比例: LC Ratio (使用期初或新增的比例? 通常是期初比例 + 动态调整)
        # 这里简化使用 nb_lc_ratio (因为是纯新增业务)
        
        revenue_claims_expenses_gross = revenue_expected_claims + revenue_expected_maint
        revenue_claims_expenses_lc_alloc = revenue_claims_expenses_gross * nb_lc_ratio
        revenue_claims_expenses_net = revenue_claims_expenses_gross - revenue_claims_expenses_lc_alloc
        
        logger.log_item(
            "保险合同收入_预期赔付与费用",
            "当期预期的赔付和维持费用释放 (扣除亏损分摊)",
            "(Expected Claims + Expected Maint) * (1 - LC Ratio)",
            {
                "Expected Claims": revenue_expected_claims,
                "Expected Maint": revenue_expected_maint,
                "LC Ratio": nb_lc_ratio
            },
            revenue_claims_expenses_net,
            note=f"Gross: {revenue_claims_expenses_gross:,.2f}, Allocated to LC: {revenue_claims_expenses_lc_alloc:,.2f}"
        )
        
        # 7.2 RA 释放 (RA Release)
        # 修改逻辑: 使用倒挤法 (Roll-forward approach)
        # RA_Release = (Start_RA + New_RA + RA_Interest) - End_RA
        
        # Step A: 获取期末利率曲线 (用于计算 End_RA)
        # 注意：RA通常基于当前假设(Current Rates)计算
        eop_month_str = eop_date.strftime('%Y%m')
        rates_query_eop = f"""
            SELECT term_month, forward_disrate_value 
            FROM measure_platform.conf_measure_month_disrate
            WHERE val_month = '{eop_month_str}'
            ORDER BY term_month
        """
        rates_df_eop = pd.read_sql_query(rates_query_eop, conn)
        if rates_df_eop.empty: rates_df_eop = rates_df # Fallback

        # Step B: 计算 End_BEL (基于 Current Rates) - 从PV原材料数据读取
        if pv_data_eop is None:
            raise ValueError(
                f"❌ 错误: 找不到期末评估月 {eop_month_str} 的PV原材料数据！\n"
                f"   请确保 pv_calculator.py 已计算该评估月的PV数据。"
            )
        
        # 从PV原材料数据读取期末现值（基于当前利率）
        # 预期未来赔付现值（期末利率）
        pv_eop_claims_curr = pv_data_eop.get_field('Pvfl_Nb_Eop_Cfa_Rep_Cur_Cla_Amt')
        # 预期未来维费现值（期末利率）
        pv_eop_maint_curr = pv_data_eop.get_field('Pvfl_Nb_Eop_Cfa_Rep_Cur_Mtn_Amt')
        end_bel_current = pv_eop_claims_curr + pv_eop_maint_curr
        
        # Step C: 计算 End_RA
        end_ra = end_bel_current * RATIO_RA
        
        # Step D: 计算 RA Interest (需与IFIE一致)
        # 这里简单使用 init_ra * accretion_factor (假设首日生成)
        ra_interest = init_ra * accretion_factor
        
        # Step E: 倒挤 Release
        # Start_RA (0) + New_RA (init_ra) + Interest (ra_interest) - End_RA
        ra_release_gross = (Decimal('0') + init_ra + ra_interest) - end_ra
        
        # 扣除 LC 分摊
        ra_release_lc_alloc = ra_release_gross * nb_lc_ratio
        ra_release_net = ra_release_gross - ra_release_lc_alloc
        
        logger.log_item(
            "保险合同收入_RA释放",
            "当期释放的非金融风险调整 (倒挤法: Start + New + Int - End)",
            "(Init_RA + RA_Interest - End_RA) * (1 - LC Ratio)",
            {
                "Init RA": init_ra, 
                "RA Interest": ra_interest,
                "End RA (calc from End BEL)": end_ra,
                "LC Ratio": nb_lc_ratio
            },
            ra_release_net,
            note=f"End BEL(Current): {end_bel_current:,.2f}"
        )
        
        # 7.3 CSM 摊销 (CSM Amortization)
        # 修改逻辑: 修正摊销比例公式
        # Ratio = Current_Period_Units / (Current_Period_Units + Remaining_Units)
        
        current_period_months = months_passed  # 本期经过月数 (e.g. 8)
        remaining_months = total_months - months_passed # 剩余月数 (e.g. 363 - 8 = 355)
        if remaining_months < 0: remaining_months = 0
        
        csm_amort_ratio_corrected = Decimal('1')
        denom_units = Decimal(current_period_months + remaining_months)
        
        if denom_units > 0:
            csm_amort_ratio_corrected = Decimal(current_period_months) / denom_units
        
        csm_amort_amount = end_csm_before_amort * csm_amort_ratio_corrected
        
        logger.log_item(
            "保险合同收入_CSM摊销",
            "当期确认的合同服务边际 (修正公式)",
            "CSM Balance * [Current / (Current + Remaining)]",
            {
                "CSM Balance": end_csm_before_amort, 
                "Current Months": current_period_months,
                "Remaining Months": remaining_months,
                "Ratio": csm_amort_ratio_corrected
            },
            csm_amort_amount
        )
        
        # 更新期末 CSM
        end_csm_final = end_csm_before_amort - csm_amort_amount
        
        # 7.4 IACF 摊销 (Revenue Impact)
        # 逻辑: 这里的 IACF 摊销是指 "Recovery of Insurance Acquisition Cash Flows"
        # 在 BBA 下，Revenue 中包含一部分用于覆盖 IACF 的金额。
        # 金额等于 Expense 中的 IACF Amortization。
        # 注意符号: Expense 中是负值 (Cost), Revenue 中是正值 (Income).
        # 取绝对值。
        
        revenue_iacf_amort = abs(iacf_amort_amount)
        
        logger.log_item(
            "保险合同收入_IACF摊销",
            "当期回收的获取费用",
            "Abs(IACF Amortization Expense)",
            {"IACF Amort Expense": iacf_amort_amount},
            revenue_iacf_amort
        )
        
        # 7.5 经验调整 (Experience Adjustment) - Revenue Part
        # 逻辑: 指与保费相关的经验调整 (Premium Experience Adjustment)
        # 公式: 收到保费的差异。
        # 我们在 Part 2 计算了 prem_var.
        # 如果实际收到 > 预期收到，Revenue 增加? 
        # BBA 下，Premium Experience Adjustment (Current Service) 进 Revenue。
        # Future Service 进 CSM。
        # 假设 prem_var 是 Current Service 部分 (例如分期缴费的当期部分)。
        # 这里假设 prem_var = 0.
        
        revenue_exp_adj = prem_var
        
        logger.log_item(
            "保险合同收入_经验调整",
            "与当期服务相关的保费经验调整",
            "Premium Variance (Current Service)",
            {"Prem Var": prem_var},
            revenue_exp_adj
        )
        
        # 7.6 投资成分 (Investment Component)
        # 逻辑: 剔除投资成分。
        # 假设: 0 (直保无投资成分)
        revenue_inv_comp = Decimal('0')
        
        # 7.7 保险合同收入合计
        total_revenue = (
            revenue_claims_expenses_net +
            ra_release_net +
            csm_amort_amount +
            revenue_iacf_amort +
            revenue_exp_adj - 
            revenue_inv_comp
        )
        
        logger.log_item(
            "保险合同收入_合计",
            "当期确认的总保险合同收入",
            "Sum(Exp Claims Net + RA Net + CSM Amort + IACF Amort + Exp Adj - Inv Comp)",
            {
                "Exp Claims Net": revenue_claims_expenses_net,
                "RA Net": ra_release_net,
                "CSM Amort": csm_amort_amount,
                "IACF Amort": revenue_iacf_amort
            },
            total_revenue
        )

        # ==========================================================================================
        # Part 8: 保险财务损益 (IFIE)
        # ==========================================================================================
        logger.log_section("Part 8: 保险财务损益 (IFIE)")
        
        # 8.0 获取期末利率曲线 (Current Rates at EOP)
        # 用于计算 OCI (如果启用) 或 Total Finance Expense (如果 OCI=0)
        # 假设 OCI Option = 0 (不拆分)，则 IFIE = Total Change (Current Rates)
        # 但根据图片，似乎要展示 "Locked-in" 的部分。
        # 我们先计算 Locked-in 部分 (Accretion)，然后计算 Current 部分，展示两者。
        
        eop_month_str = eop_date.strftime('%Y%m')
        print(f"\n[Step 8.0] 获取期末 ({eop_month_str}) 利率曲线...")
        
        rates_query_eop = f"""
            SELECT term_month, forward_disrate_value 
            FROM measure_platform.conf_measure_month_disrate
            WHERE val_month = '{eop_month_str}'
            ORDER BY term_month
        """
        rates_df_eop = pd.read_sql_query(rates_query_eop, conn)
        
        if rates_df_eop.empty:
             print(f"⚠️ 警告: 未找到 {eop_month_str} 的利率曲线。使用初始曲线代替 (假设利率不变)。")
             rates_df_eop = rates_df
        else:
             print(f"✅ 成功获取 {eop_month_str} 利率曲线 ({len(rates_df_eop)} 条记录)。")

        # 8.1 预期现金流的 IFIE (IFIE_BEL)
        # 逻辑: 
        # IFIE_BEL (Locked-in) = PV_EOP(Locked-in) - PV_Initial(Locked-in) + FV_Current_CashFlows(Locked-in)
        # 这实际上等于 Liability_BOP * Accretion_Factor (如果现金流完全匹配)
        # 但我们按公式计算。
        
        # A. PV_EOP (Locked-in) - 从PV原材料数据读取
        # 从PV原材料数据读取期末现值（基于加权初始确认利率）
        pv_eop_claims_lockedin = pv_data_eop.get_field('Pvfl_Nb_Eop_Cfa_Rep_Wlk_Cla_Amt')
        pv_eop_maint_lockedin = pv_data_eop.get_field('Pvfl_Nb_Eop_Cfa_Rep_Wlk_Mtn_Amt')
        
        # B. FV_Current_CashFlows (Locked-in)
        # 当期发生的现金流，积累到期末。
        # 假设均匀分布。
        # 简化: 使用 expected_claim_nominal (当期总额) * (1 + r_avg * 0.5)?
        # 或者更精确: 逐月积累。
        # 让我们写一个简单的积累函数。
        
        def calculate_accumulated_value(nominal_amount, months_duration, rates_df, start_offset):
            # 假设 nominal_amount 均匀分布在 months_duration 中
            if months_duration <= 0: return Decimal('0')
            monthly_amt = nominal_amount / Decimal(months_duration)
            total_fv = Decimal('0')
            
            rates_map = dict(zip(rates_df['term_month'], rates_df['forward_disrate_value'].apply(Decimal)))
            
            # 对于第 m 个月发生的现金流 (m=1..duration)
            # 它需要积累 (duration - m + 0.5?) 个月?
            # 简单点: 假设月末发生，积累 (duration - m) 个月。
            # 第1个月末发生，积累 duration-1 个月。
            # 第 duration 个月末发生，积累 0 个月。
            
            for m in range(1, months_duration + 1):
                # 积累因子: 从 m+1 到 duration
                accum_factor = Decimal('1.0')
                # 利率取值: start_offset + t
                # t 从 m+1 到 duration
                for t in range(m + 1, months_duration + 1):
                    r = rates_map.get(start_offset + t, Decimal('0'))
                    accum_factor *= (Decimal('1') + r)
                
                total_fv += monthly_amt * accum_factor
            return total_fv

        fv_current_claims_lockedin = calculate_accumulated_value(expected_claim_nominal, months_passed, rates_df, 0)
        fv_current_maint_lockedin = calculate_accumulated_value(expected_maint_nominal, months_passed, rates_df, 0)
        
        # C. PV_Initial (Locked-in)
        # 已经在 Part 1 计算: init_fut_claim, init_fut_maint
        
        # 计算 IFIE_BEL (Locked-in)
        ifie_bel_claims_lockedin = pv_eop_claims_lockedin - init_fut_claim + fv_current_claims_lockedin
        ifie_bel_maint_lockedin = pv_eop_maint_lockedin - init_fut_maint + fv_current_maint_lockedin
        
        ifie_bel_total_lockedin = ifie_bel_claims_lockedin + ifie_bel_maint_lockedin
        
        logger.log_item(
            "IFIE_预期现金流 (Locked-in)",
            "基于锁定利率计算的负债利息费用 (Unwinding of Discount)",
            "PV_EOP(Locked-in) - PV_Initial(Locked-in) + FV_Current(Locked-in)",
            {
                "PV EOP Claims": pv_eop_claims_lockedin,
                "PV Init Claims": init_fut_claim,
                "FV Curr Claims": fv_current_claims_lockedin,
                "PV EOP Maint": pv_eop_maint_lockedin
            },
            ifie_bel_total_lockedin
        )
        
        # 8.2 非金融风险调整的 IFIE (IFIE_RA)
        # 逻辑: RA 同样有时间价值释放。
        # IFIE_RA = PV_EOP(RA) - PV_Initial(RA) + Released_RA_Accumulated?
        # 通常 RA 也是折现计算的。
        # RA = (PV_Claims + PV_Maint) * Ratio.
        # 所以 IFIE_RA 应该是 IFIE_BEL * Ratio.
        
        ifie_ra_lockedin = ifie_bel_total_lockedin * RATIO_RA
        
        logger.log_item(
            "IFIE_非金融风险调整 (Locked-in)",
            "RA 的利息费用",
            "IFIE_BEL * RA Ratio",
            {"IFIE BEL": ifie_bel_total_lockedin, "RA Ratio": RATIO_RA},
            ifie_ra_lockedin
        )
        
        # 8.3 CSM 的 IFIE (IFIE_CSM)
        # 逻辑: 就是 CSM 计息。
        # 已经在 Part 3 计算: nb_interest_csm
        
        ifie_csm = nb_interest_csm
        
        logger.log_item(
            "IFIE_CSM",
            "CSM 的利息费用 (Accretion)",
            "Calculated in Part 3",
            {},
            ifie_csm
        )
        
        # 8.4 IFIE 总计 (P&L) 与 OCI 拆分
        # 逻辑:
        # IFIE_Total (Current Rates) = IFIE_LockedIn + Effect_of_Rate_Change
        # 若 OCI选择权 = 1 (True):
        #   IFIE_P&L = IFIE_LockedIn
        #   IFIE_OCI = Effect_of_Rate_Change
        # 若 OCI选择权 = 0 (False):
        #   IFIE_P&L = IFIE_Total
        #   IFIE_OCI = 0
        
        # 计算 PV_EOP (Current Rates) - 从PV原材料数据读取
        # 从PV原材料数据读取期末现值（基于当前利率）
        pv_eop_claims_current = pv_data_eop.get_field('Pvfl_Nb_Eop_Cfa_Rep_Cur_Cla_Amt')
        pv_eop_maint_current = pv_data_eop.get_field('Pvfl_Nb_Eop_Cfa_Rep_Cur_Mtn_Amt')
        
        liability_eop_lockedin = pv_eop_claims_lockedin + pv_eop_maint_lockedin
        liability_eop_current = pv_eop_claims_current + pv_eop_maint_current
        
        effect_of_rate_change_bel = liability_eop_current - liability_eop_lockedin
        effect_of_rate_change_ra = effect_of_rate_change_bel * RATIO_RA
        
        total_rate_change_effect = effect_of_rate_change_bel + effect_of_rate_change_ra
        
        ifie_locked_in_total = ifie_bel_total_lockedin + ifie_ra_lockedin + ifie_csm
        ifie_total_current = ifie_locked_in_total + total_rate_change_effect
        
        ifie_pl = Decimal('0')
        ifie_oci = Decimal('0')
        
        if USE_OCI_OPTION:
            ifie_pl = ifie_locked_in_total
            ifie_oci = total_rate_change_effect
            oci_status = "拆分 (Split)"
        else:
            ifie_pl = ifie_total_current
            ifie_oci = Decimal('0')
            oci_status = "不拆分 (No Split)"
            
        logger.log_item(
            "IFIE_计入损益 (P&L)",
            f"计入当期损益的保险财务费用 (OCI模式: {oci_status})",
            "IFIE_LockedIn (if OCI=1) else IFIE_Total",
            {
                "IFIE Locked-in": ifie_locked_in_total,
                "IFIE Total": ifie_total_current,
                "OCI Option": USE_OCI_OPTION
            },
            ifie_pl
        )
        
        logger.log_item(
            "IFIE_计入OCI (其他综合收益)",
            "计入其他综合收益的保险财务费用 (利率变动影响)",
            "Effect of Rate Change (if OCI=1) else 0",
            {
                "Rate Change Effect": total_rate_change_effect,
                "OCI Option": USE_OCI_OPTION
            },
            ifie_oci
        )
        
        # 8.5 亏损分摊 (Onerous Contract Split)
        # IFIE P&L 和 IFIE OCI 都需要分摊到 LC。
        
        # P&L 分摊
        ifie_pl_lc = ifie_pl * nb_lc_ratio
        ifie_pl_non_lc = ifie_pl - ifie_pl_lc
        
        # OCI 分摊
        ifie_oci_lc = ifie_oci * nb_lc_ratio
        ifie_oci_non_lc = ifie_oci - ifie_oci_lc
        
        logger.log_item(
            "IFIE_P&L_分摊",
            "IFIE(P&L) 分摊到亏损成分(LC)和非亏损成分",
            "IFIE_P&L * LC Ratio",
            {"Total P&L": ifie_pl, "LC Ratio": nb_lc_ratio},
            ifie_pl_non_lc,
            note=f"Non-LC: {ifie_pl_non_lc:,.2f}, LC: {ifie_pl_lc:,.2f}"
        )
        
        logger.log_item(
            "IFIE_OCI_分摊",
            "IFIE(OCI) 分摊到亏损成分(LC)和非亏损成分",
            "IFIE_OCI * LC Ratio",
            {"Total OCI": ifie_oci, "LC Ratio": nb_lc_ratio},
            ifie_oci_non_lc,
            note=f"Non-LC: {ifie_oci_non_lc:,.2f}, LC: {ifie_oci_lc:,.2f}"
        )

        logger.log_section("Part 5: 汇总 (Summary)")
        
        print(f"CSM 变动表:")
        print(f"  期初余额:          0.00")
        print(f"  + 本年新增:        {nb_initial_csm:,.2f}")
        print(f"  + 计息:            {nb_interest_csm:,.2f}")
        print(f"  + 经验调整(CSM):    {csm_absorbed:,.2f}")
        print(f"  - 摊销:            {csm_amort_amount:,.2f}")
        print(f"  = 期末CSM余额:      {end_csm_final:,.2f}")
        
        print(f"\nLC (亏损成分) 变动表:")
        print(f"  期初余额:          0.00")
        print(f"  + 本年新增:        {nb_initial_lc:,.2f}")
        print(f"  + 计息:            {nb_interest_lc:,.2f}")
        print(f"  + 经验调整(LC):     {lc_change:,.2f}")
        print(f"  = 摊销前LC余额:     {end_lc_before_amort:,.2f}")
        
        print(f"\nIACF (待摊获取费用) 变动表:")
        print(f"  期初余额:          {bop_iacf:,.2f}")
        print(f"  + 本年新增:        {nb_iacf_addition:,.2f}")
        print(f"  + 计息:            {iacf_interest_nb:,.2f}")
        print(f"  + 变化(Variance):  {iacf_change:,.2f}")
        print(f"  + 摊销:            {iacf_amort_amount:,.2f}")
        print(f"  = 期末余额:         {eop_iacf_balance:,.2f}")

        # ==========================================================================================
        # Part 9: 期末未到期责任负债 (LRC Closing Balance)
        # ==========================================================================================
        logger.log_section("Part 9: 期末未到期责任负债 (LRC Closing Balance)")
        
        # 9.1 预期保费现金流现值 (PV Future Premiums)
        # 假设趸交，期末无未来保费
        # 如果是期缴，需计算 PV_EOP_Premiums
        # 这里假设 Future Premiums = 0
        lrc_bel_premium = Decimal('0')
        
        logger.log_item(
            "预期保费现金流现值",
            "期末预期未来收到的保费现值 (负债方向: 流入为负)",
            "- PV_EOP_Premiums",
            {"Future Premiums": 0},
            lrc_bel_premium
        )
        
        # 9.2 预期IACF现值 (PV Future IACF)
        # 假设 IACF 随保费支付，无未来 IACF
        lrc_bel_iacf = Decimal('0')
        
        logger.log_item(
            "预期IACF现值",
            "期末预期未来支付的获取费用现值",
            "PV_EOP_IACF",
            {"Future IACF": 0},
            lrc_bel_iacf
        )
        
        # 9.3 预期赔付与费用现金流现值 (PV Future Claims & Expenses)
        # 使用 Part 8 计算的 pv_eop_claims_current 和 pv_eop_maint_current (基于期末利率)
        lrc_bel_claims_expenses = pv_eop_claims_current + pv_eop_maint_current
        
        logger.log_item(
            "预期赔付与费用现金流现值",
            "期末预期未来赔付和维持费用的现值 (基于期末利率)",
            "PV_EOP_Claims + PV_EOP_Maint",
            {
                "PV EOP Claims": pv_eop_claims_current,
                "PV EOP Maint": pv_eop_maint_current
            },
            lrc_bel_claims_expenses
        )
        
        # 9.4 预期现金流现值 (Total BEL)
        lrc_bel_total = lrc_bel_premium + lrc_bel_iacf + lrc_bel_claims_expenses
        
        logger.log_item(
            "预期现金流现值 (BEL)",
            "履约现金流的现值估计",
            "Sum(Premium, IACF, Claims & Expenses)",
            {},
            lrc_bel_total
        )
        
        # 9.5 预期非金融风险调整 (Risk Adjustment)
        # 基于期末 BEL 计算 RA
        # RA = BEL * Ratio
        lrc_ra = lrc_bel_total * RATIO_RA
        
        logger.log_item(
            "预期非金融风险调整 (RA)",
            "期末非金融风险调整余额",
            "BEL * RA Ratio",
            {"BEL": lrc_bel_total, "Ratio": RATIO_RA},
            lrc_ra
        )
        
        # 9.6 CSM
        # 期末 CSM 余额 (Part 7 计算的 end_csm_final)
        lrc_csm = end_csm_final
        
        logger.log_item(
            "CSM (合同服务边际)",
            "期末合同服务边际余额",
            "End CSM Balance",
            {},
            lrc_csm
        )
        
        # 9.7 期末未到期责任负债余额 (Total LRC)
        lrc_total = lrc_bel_total + lrc_ra + lrc_csm
        
        logger.log_item(
            "期末未到期责任负债余额 (Total LRC)",
            "期末未到期责任负债总额",
            "BEL + RA + CSM",
            {"BEL": lrc_bel_total, "RA": lrc_ra, "CSM": lrc_csm},
            lrc_total
        )

    except Exception as e:
        print(f"发生错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if conn: conn.close()

if __name__ == "__main__":
    calculate_bba_measurement()