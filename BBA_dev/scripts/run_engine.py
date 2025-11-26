import pandas as pd
from dateutil.relativedelta import relativedelta
from bba_model.config import POLICY_NO
from bba_model.context import CalculationContext
from bba_model.utils.logger import CalculationLogger
from bba_model.data_access import loader
from bba_model.logic import (
    initial_recognition,
    experience_adj,
    interest_accretion,
    csm_allocation,
    iacf_amortization,
    revenue,
    ifie,
    lrc_closing
)

def main():
    # 1. 初始化
    logger = CalculationLogger()
    context = CalculationContext() 
    
    logger.log_section(f"BBA计量展示：CSM 构建、经验调整与计息 (使用真实数据库利率曲线)")
    print(f"保单号: {POLICY_NO}")
    
    # 2. 加载数据
    print("\n[Step 0] 获取保单数据并确定计量起点...")
    df_data = loader.get_policy_data(POLICY_NO)
    if df_data.empty:
        print("错误：未找到保单数据。")
        return
    
    context.policy_data = df_data.iloc[0]
    
    # 处理日期和期限
    uw_date = context.policy_data['under_write_date']
    if isinstance(uw_date, pd.Timestamp):
        uw_date = uw_date.date()
    context.under_write_date = uw_date
    
    context.start_date = context.policy_data['start_date']
    context.end_date = context.policy_data['end_date']
    context.year = uw_date.year
    context.val_month_str = uw_date.strftime('%Y%m')
    
    delta = relativedelta(context.end_date, context.start_date)
    context.total_months = delta.years * 12 + delta.months
    if context.total_months == 0 and delta.days > 0: context.total_months = 1
        
    print(f"✅ 签单日 (初始确认日): {context.under_write_date}")
    print(f"✅ 计量年度: {context.year}年")
    print(f"✅ 对应利率曲线月份: {context.val_month_str}")
    print(f"ℹ️  保单起期: {context.start_date.date()} -> 止期: {context.end_date.date()} (总月数: {context.total_months})")

    print(f"\n[Step 0.1] 获取数据库中的月度远期利率曲线...")
    context.rates_df = loader.get_rates(context.val_month_str)
    if context.rates_df.empty:
        print(f"⚠️ 警告: 未找到 {context.val_month_str} 的利率曲线。")
        return
    print(f"✅ 成功获取 {context.val_month_str} 利率曲线 ({len(context.rates_df)} 条记录)。")

    # 3. 执行流水线 (Pipeline)
    initial_recognition.run(context, logger)   # Part 1
    experience_adj.run(context, logger)        # Part 2
    interest_accretion.run(context, logger)    # Part 3
    csm_allocation.calculate_absorption(context, logger) # Part 4
    
    iacf_amortization.run(context, logger)     # Part 6
    revenue.run(context, logger)               # Part 7
    
    ifie.run(context, logger)                  # Part 8
    
    lrc_closing.run_summary(context, logger)   # Part 5 (汇总)
    lrc_closing.run_closing(context, logger)   # Part 9 (期末负债)

if __name__ == "__main__":
    main()

