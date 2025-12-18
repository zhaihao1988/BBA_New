# BBA Group Dimension Calculation Module

## 概述

BBA_group 是用于按合同组（group_id）维度进行IFRS 17 BBA计量的全新代码套。

## 核心特性

1. **基于CSM权重的组级利率曲线构建**
   - 按组内保单初始确认的CSM为权重
   - 构建合同组维度的多期利率曲线
   - 支持跨月份递归更新

2. **先逐单计算，再按组汇总判断**
   - 先对组内每张保单独立计算初始确认、CSM计息、LC分摊IFIE
   - 再按组汇总，判断合同组是CSM还是LC状态
   - 最后进行组级计量

3. **组级CSM/LC汇总计量**
   - 按组汇总组内所有保单的CSM和LC
   - 在组级进行状态判断

4. **基于保费权重的组级摊销比例计算**
   - 使用组内所有保单的保费作为权重
   - 当期/(当期+未来服务量)作为覆盖单元

## 目录结构

```
BBA_group/
├── __init__.py                 # 模块初始化
├── config.py                   # 配置
├── context.py                  # 组维度计算上下文
├── README.md                   # 本文件
├── data_access/                # 数据访问层
│   ├── __init__.py
│   └── group_loader.py         # 按组加载数据
├── logic/                      # 计算逻辑
│   ├── __init__.py
│   ├── group_rates_manager.py  # 组级利率曲线管理
│   ├── group_csm_lc_measurement.py  # 组级CSM/LC计量
│   ├── group_coverage_units.py      # 组级覆盖单元计算
│   ├── group_initial_recognition.py # 组级初始确认
│   └── group_iacf_amortization.py   # 组级IACF摊销
├── models/                     # 数据模型
│   ├── __init__.py
│   ├── group_cohort_state.py   # 组级合同组状态
│   └── group_policy_state.py   # 组级保单状态
├── scripts/                    # 主流程脚本
│   ├── __init__.py
│   └── run_group_simulation.py # 组维度生命周期仿真
└── utils/                      # 工具函数
    └── __init__.py
```

## 使用说明

### 1. 数据加载

```python
from BBA_group.data_access import load_policies_by_group

# 按group_id加载保单数据
policies_df = load_policies_by_group(
    group_id='GROUP001',
    run_date='202412',
    val_method='7'
)
```

### 2. 组级计算

```python
from BBA_group.scripts.run_group_simulation import GroupLifecycleSimulator

simulator = GroupLifecycleSimulator(
    group_id='GROUP001',
    run_date='202412',
    val_method='7'
)

# 运行组维度生命周期仿真
results = simulator.run()
```

## 与BBA_dev的关系

- BBA_dev: 按单（policy_no + certi_no）计算的原始代码
- BBA_group: 按组（group_id）维度计算的新代码套

两者可以并行使用，互不干扰。

## 开发计划

详见：`.cursor/plans/按合同组维度计量改造_0c56fdcf.plan.md`



