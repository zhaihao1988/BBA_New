from decimal import Decimal, getcontext

# --- 参数配置 ---
getcontext().prec = 38
POLICY_NO = 'mock3'
CERTI_NO = None # 批单号，如果为None则计算主单

# 精算假设参数
# 注意：以下参数中，除了 RATIO_IACF（获取费用率）从配置读取外，
# 其他参数（赔付率、维持费用率、非金融风险调整率）应从数据库读取
RATIO_IACF      = Decimal('0.20')  # 初始获取费用率 (20%) - 从配置读取，不从数据库读取
RATIO_CLAIM     = Decimal('0.50')  # 赔付率 (50%) - 已废弃，应从数据库读取
RATIO_MAINT_EXP = Decimal('0.10')  # 维持费用率 (10%) - 已废弃，应从数据库读取
RATIO_RA        = Decimal('0.03')  # 非金融风险调整率 (3%) - 已废弃，应从数据库读取
EXP_ADJ_RATIO   = Decimal('1.0')   # 经验调整占比 (100% 计入)
USE_OCI_OPTION  = True             # OCI 选择权 (True = 拆分, 利率变动计入 OCI)

# 计量方法配置
VAL_METHOD = '7'  # 计量方法，用于查询精算假设表（'7' 表示 BBA 方法）

# 组配置
GROUP_ID = 'QHPLIA2023ABBA300'  # 合同组ID，用于组维度生命周期仿真


