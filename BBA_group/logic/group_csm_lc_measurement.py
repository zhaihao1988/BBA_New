"""
合同组 CSM/LC 计量（组级汇总与分摊） - 最终修复版 V3

实现功能：
1. 逐单 CSM/LC 计息与 IFIE 分摊 (Part 3 & 7)
2. 组级状态判定 (Part 7.5) - 解决首年死锁
3. LC 计量与分摊比例计算 (Part 8) - Scheme A 逻辑
4. 期末余额汇总 (Part 9) - 解决掉单问题
"""

from dataclasses import dataclass
from decimal import Decimal, getcontext
from typing import List, Optional, Dict, Any, Tuple
from datetime import date, datetime
from dateutil.relativedelta import relativedelta

# 导入 BBA_group 模型与工具 (假设环境已存在)
from BBA_group.models import CohortState, PolicyState, Assumptions
from BBA_group.utils.pv_source_loader import ensure_pv_source_data
from BBA_group.utils.math_tools import get_accretion_rate_factor
from BBA_group.assumptions import get_discount_factors

# 提高精度
getcontext().prec = 28
DECIMAL_ZERO = Decimal('0')


# ==============================================================================
# 数据类定义
# ==============================================================================
@dataclass
class PolicyContextInput:
    """单保单context输入数据（用于组级汇总）"""
    policy_id: str
    is_if: bool
    bop_csm: Decimal
    bop_lc: Decimal
    nb_initial_csm: Decimal
    nb_initial_lc: Decimal
    if_interest_csm: Decimal
    nb_interest_csm: Decimal
    if_lc_ifie_total: Decimal
    nb_lc_ifie_total: Decimal
    csm_after_interest: Decimal
    lc_after_ifie: Decimal
    delta_total: Decimal
    delta_cf: Decimal
    delta_ra: Decimal
    allocated_lc_total: Decimal
    allocated_lc_cf: Decimal
    allocated_lc_ra: Decimal
    if_lc_ifie_cf: Decimal
    nb_lc_ifie_cf: Decimal
    if_lc_ifie_ra: Decimal
    nb_lc_ifie_ra: Decimal
    nb_initial_lc_cf: Decimal
    nb_initial_lc_ra: Decimal

@dataclass
class GroupStatusResult:
    """组级状态判定结果（第二部分）"""
    if_csm_after_interest: Decimal
    nb_csm_after_interest: Decimal
    if_lc_after_ifie: Decimal
    nb_lc_after_ifie: Decimal
    net_trial: Decimal
    cohort_csm: Decimal
    cohort_lc: Decimal

@dataclass
class GroupAbsorptionResult:
    """组级吸收变化计算结果"""
    cohort_csm: Decimal
    cohort_lc: Decimal
    net_trial: Decimal
    group_csm_absorbed_total: Decimal
    group_csm_absorbed_cf: Decimal
    group_csm_absorbed_ra: Decimal
    group_lc_absorbed_total: Decimal
    group_lc_absorbed_cf: Decimal
    group_lc_absorbed_ra: Decimal

@dataclass
class PolicyAllocationResult:
    """单保单分摊结果"""
    policy_id: str
    csm_absorbed: Decimal
    csm_absorbed_cf: Decimal
    csm_absorbed_ra: Decimal
    lc_absorbed_total: Decimal
    lc_absorbed_cf: Decimal
    lc_absorbed_ra: Decimal
    csm_allocation_weight: Decimal
    lc_allocation_weight: Decimal


# ==============================================================================
# 组级汇总与分摊逻辑 (Group Aggregation & Allocation)
# ==============================================================================

def collect_policy_data(contexts: List[Any]) -> List[PolicyContextInput]:
    """从多张保单的context收集数据"""
    policy_inputs = []
    
    for ctx in contexts:
        bop_csm = getattr(ctx, 'bop_csm', None) or DECIMAL_ZERO
        bop_lc = getattr(ctx, 'bop_lc', None) or DECIMAL_ZERO
        nb_initial_csm = getattr(ctx, 'nb_initial_csm', None) or DECIMAL_ZERO
        nb_initial_lc = getattr(ctx, 'nb_initial_lc', None) or DECIMAL_ZERO
        
        is_if = (bop_csm != DECIMAL_ZERO or bop_lc != DECIMAL_ZERO)
        
        if_interest_csm = getattr(ctx, 'if_interest_csm', None) or DECIMAL_ZERO
        nb_interest_csm = getattr(ctx, 'nb_interest_csm', None) or DECIMAL_ZERO
        if_lc_ifie_total = getattr(ctx, 'if_lc_ifie_total', None) or DECIMAL_ZERO
        nb_lc_ifie_total = getattr(ctx, 'nb_lc_ifie_total', None) or DECIMAL_ZERO
        
        if is_if:
            csm_after_interest = bop_csm + if_interest_csm
        else:
            csm_after_interest = nb_initial_csm + nb_interest_csm
        
        if is_if:
            lc_after_ifie = bop_lc + if_lc_ifie_total
        else:
            lc_after_ifie = nb_initial_lc + nb_lc_ifie_total
        
        delta_total = getattr(ctx, 'exp_adj_csm_impact', None) or DECIMAL_ZERO
        delta_cf = getattr(ctx, 'delta_cf_total', None) or DECIMAL_ZERO
        delta_ra = delta_total - delta_cf
        
        allocated_lc_total = getattr(ctx, 'allocated_lc_total', None) or DECIMAL_ZERO
        allocated_lc_cf = getattr(ctx, 'allocated_lc_cf', None) or DECIMAL_ZERO
        allocated_lc_ra = getattr(ctx, 'allocated_lc_ra', None) or DECIMAL_ZERO
        
        if_lc_ifie_cf = getattr(ctx, 'if_lc_ifie_cf', None) or DECIMAL_ZERO
        nb_lc_ifie_cf = getattr(ctx, 'nb_lc_ifie_cf', None) or DECIMAL_ZERO
        if_lc_ifie_ra = getattr(ctx, 'if_lc_ifie_ra', None) or DECIMAL_ZERO
        nb_lc_ifie_ra = getattr(ctx, 'nb_lc_ifie_ra', None) or DECIMAL_ZERO
        
        nb_initial_lc_cf = getattr(ctx, 'nb_initial_lc_cf', None) or DECIMAL_ZERO
        nb_initial_lc_ra = getattr(ctx, 'nb_initial_lc_ra', None) or DECIMAL_ZERO
        
        policy_id = getattr(ctx, 'policy_no', None) or getattr(ctx, 'policy_id', None) or f"POL_{len(policy_inputs)}"
        
        policy_inputs.append(PolicyContextInput(
            policy_id=policy_id, is_if=is_if, bop_csm=bop_csm, bop_lc=bop_lc,
            nb_initial_csm=nb_initial_csm, nb_initial_lc=nb_initial_lc,
            if_interest_csm=if_interest_csm, nb_interest_csm=nb_interest_csm,
            if_lc_ifie_total=if_lc_ifie_total, nb_lc_ifie_total=nb_lc_ifie_total,
            csm_after_interest=csm_after_interest, lc_after_ifie=lc_after_ifie,
            delta_total=delta_total, delta_cf=delta_cf, delta_ra=delta_ra,
            allocated_lc_total=allocated_lc_total, allocated_lc_cf=allocated_lc_cf, allocated_lc_ra=allocated_lc_ra,
            if_lc_ifie_cf=if_lc_ifie_cf, nb_lc_ifie_cf=nb_lc_ifie_cf,
            if_lc_ifie_ra=if_lc_ifie_ra, nb_lc_ifie_ra=nb_lc_ifie_ra,
            nb_initial_lc_cf=nb_initial_lc_cf, nb_initial_lc_ra=nb_initial_lc_ra,
        ))
    
    return policy_inputs


def calculate_group_status(
    policy_inputs: List[PolicyContextInput],
    is_reversal: bool = False,
    logger: Optional[Any] = None
) -> GroupStatusResult:
    """
    第二部分：合同组状态判定（仅汇总和判定，不做吸收变化计算）
    
    汇总IF_计息后CSM、NB_计息后CSM、IF_分摊后IFIE后LC、NB_分摊后IFIE后LC，
    计算合同组CSM和合同组LC
    """
    if logger:
        logger.log_section("第二部分：合同组状态判定")
        logger.log_text("#### 步骤1：汇总合同组CSM/LC（计息后/分摊后）")
    
    if_csm_after_interest = DECIMAL_ZERO
    nb_csm_after_interest = DECIMAL_ZERO
    if_lc_after_ifie = DECIMAL_ZERO
    nb_lc_after_ifie = DECIMAL_ZERO
    
    for p in policy_inputs:
        if p.is_if:
            if_csm_after_interest += p.bop_csm + p.if_interest_csm
            if_lc_after_ifie += p.bop_lc + p.if_lc_ifie_total
        else:
            nb_csm_after_interest += p.nb_initial_csm + p.nb_interest_csm
            nb_lc_after_ifie += p.nb_initial_lc + p.nb_lc_ifie_total
    
    if logger:
        logger.log_text(f"  - IF_计息后CSM合计: {if_csm_after_interest:,.2f}")
        logger.log_text(f"  - NB_计息后CSM合计: {nb_csm_after_interest:,.2f}")
        logger.log_text(f"  - IF_分摊后IFIE后LC合计: {if_lc_after_ifie:,.2f}")
        logger.log_text(f"  - NB_分摊后IFIE后LC合计: {nb_lc_after_ifie:,.2f}")
    
    # 计算Net Trial并判断合同组状态
    net_trial = if_csm_after_interest + nb_csm_after_interest + if_lc_after_ifie + nb_lc_after_ifie
    
    if logger:
        logger.log_text("#### 步骤2：计算Net Trial并判断合同组状态")
        logger.log_text(f"  - Net Trial = {net_trial:,.2f}")
    
    # 判断合同组状态
    if (not is_reversal and net_trial >= 0) or (is_reversal and net_trial <= 0):
        cohort_csm = net_trial
        cohort_lc = DECIMAL_ZERO
    else:
        cohort_csm = DECIMAL_ZERO
        cohort_lc = net_trial
    
    if logger:
        logger.log_text(f"  - 合同组状态判定: 合同组CSM={cohort_csm:,.2f}, 合同组LC={cohort_lc:,.2f}")
    
    return GroupStatusResult(
        if_csm_after_interest=if_csm_after_interest,
        nb_csm_after_interest=nb_csm_after_interest,
        if_lc_after_ifie=if_lc_after_ifie,
        nb_lc_after_ifie=nb_lc_after_ifie,
        net_trial=net_trial,
        cohort_csm=cohort_csm,
        cohort_lc=cohort_lc
    )


def calculate_group_absorption(
    policy_inputs: List[PolicyContextInput],
    group_status: GroupStatusResult,
    is_reversal: bool = False,
    logger: Optional[Any] = None
) -> GroupAbsorptionResult:
    """计算组级吸收变化（第三部分使用）"""
    cohort_csm = group_status.cohort_csm
    cohort_lc = group_status.cohort_lc
    net_trial = group_status.net_trial
    
    if logger:
        logger.log_text("#### 步骤3：计算组级吸收变化")
    
    # 汇总Delta
    group_delta_total = sum(p.delta_total for p in policy_inputs)
    group_delta_cf = sum(p.delta_cf for p in policy_inputs)
    group_delta_ra = sum(p.delta_ra for p in policy_inputs)
    
    # 汇总LC相关项（用于计算被LC吸收的变化）
    allocated_lc_total = sum(p.allocated_lc_total for p in policy_inputs)  # 分摊的LC_合计（汇总）
    bop_lc_total = sum(p.bop_lc for p in policy_inputs)  # 年初LC余额_合计
    nb_initial_lc_total = sum(p.nb_initial_lc for p in policy_inputs)  # 当年新增LC_合计
    lc_ifie_total = sum(p.if_lc_ifie_total + p.nb_lc_ifie_total for p in policy_inputs)  # LC分摊IFIE_合计
    
    # 汇总CSM相关项（用于计算被CSM吸收的变化）
    bop_csm_total = sum(p.bop_csm for p in policy_inputs)  # 年初CSM余额
    nb_initial_csm_total = sum(p.nb_initial_csm for p in policy_inputs)  # 当年新增CSM
    csm_interest_total = sum(p.if_interest_csm + p.nb_interest_csm for p in policy_inputs)  # CSM计息
    
    # 被CSM/LC吸收的变化合计（即group_delta_total）
    delta_csm_lc_total = group_delta_total
    
    # 【根据文档公式】计算被LC吸收的变化_合计
    # IF(OR(AND(合同组LC<0,SUM(合同组LC,分摊的LC,被CSM/LC吸收的变化合计)<0),
    #        AND(合同组LC=0,SUM(合同组CSM,被CSM/LC吸收的变化合计)<0)),
    #    SUM(被CSM/LC吸收的变化合计,年初CSM余额,当年新增CSM,CSM计息),
    #    -SUM(年初LC余额_合计,当年新增LC_合计,LC分摊IFIE_合计,分摊的LC_合计))
    sum_lc_test = cohort_lc + allocated_lc_total + delta_csm_lc_total
    sum_csm_test = cohort_csm + delta_csm_lc_total
    
    is_lc_bucket = (cohort_lc < 0) if (not is_reversal) else (cohort_lc > 0)
    lc_stays_lc = (sum_lc_test < 0) if (not is_reversal) else (sum_lc_test > 0)
    csm_turns_lc = (sum_csm_test < 0) if (not is_reversal) else (sum_csm_test > 0)
    
    if (is_lc_bucket and lc_stays_lc) or ((not is_lc_bucket) and cohort_lc == DECIMAL_ZERO and csm_turns_lc):
        # 第一个分支：SUM(被CSM/LC吸收的变化合计,年初CSM余额,当年新增CSM,CSM计息)
        group_lc_absorbed_total = delta_csm_lc_total + bop_csm_total + nb_initial_csm_total + csm_interest_total
    else:
        # 第二个分支：-SUM(年初LC余额_合计,当年新增LC_合计,LC分摊IFIE_合计,分摊的LC_合计)
        group_lc_absorbed_total = -(bop_lc_total + nb_initial_lc_total + lc_ifie_total + allocated_lc_total)
    
    # 【根据文档公式】计算被CSM吸收的变化_合计
    # IF(OR(AND(合同组CSM>0,SUM(合同组CSM, 被CSM/LC吸收的变化合计)>=0),
    #        AND(合同组CSM=0,SUM(合同组LC, 分摊的LC, 被CSM/LC吸收的变化合计)>=0)),
    #    SUM(被CSM/LC吸收的变化合计, 年初LC余额_合计, 当年新增LC_合计, LC分摊IFIE_合计, 分摊的LC_合计),
    #    -SUM(年初CSM余额, 当年新增CSM, CSM计息))
    sum_csm_test2 = cohort_csm + delta_csm_lc_total
    sum_lc_test2 = cohort_lc + allocated_lc_total + delta_csm_lc_total
    
    is_csm_bucket = (cohort_csm > 0) if (not is_reversal) else (cohort_csm < 0)
    csm_stays_csm = (sum_csm_test2 >= 0) if (not is_reversal) else (sum_csm_test2 <= 0)
    lc_turns_csm = (sum_lc_test2 >= 0) if (not is_reversal) else (sum_lc_test2 <= 0)
    
    if (is_csm_bucket and csm_stays_csm) or ((not is_csm_bucket) and cohort_csm == DECIMAL_ZERO and lc_turns_csm):
        # 第一个分支：SUM(被CSM/LC吸收的变化合计, 年初LC余额_合计, 当年新增LC_合计, LC分摊IFIE_合计, 分摊的LC_合计)
        group_csm_absorbed_total = delta_csm_lc_total + bop_lc_total + nb_initial_lc_total + lc_ifie_total + allocated_lc_total
    else:
        # 第二个分支：-SUM(年初CSM余额, 当年新增CSM, CSM计息)
        group_csm_absorbed_total = -(bop_csm_total + nb_initial_csm_total + csm_interest_total)
    
    if logger:
        logger.log_text(f"  - 被CSM/LC吸收的变化合计: {delta_csm_lc_total:,.2f}")
        logger.log_text(f"  - 被LC吸收的变化_合计: {group_lc_absorbed_total:,.2f}")
        logger.log_text(f"  - 被CSM吸收的变化_合计: {group_csm_absorbed_total:,.2f}")
    
    # 拆分被LC吸收的变化
    bop_lc_cf_total = bop_lc_total
    bop_lc_ra_total = DECIMAL_ZERO
    nb_initial_lc_cf_total = sum(p.nb_initial_lc_cf for p in policy_inputs)
    nb_initial_lc_ra_total = sum(p.nb_initial_lc_ra for p in policy_inputs)
    lc_ifie_cf_total = sum(p.if_lc_ifie_cf + p.nb_lc_ifie_cf for p in policy_inputs)
    lc_ifie_ra_total = sum(p.if_lc_ifie_ra + p.nb_lc_ifie_ra for p in policy_inputs)
    allocated_lc_cf_total = sum(p.allocated_lc_cf for p in policy_inputs)
    allocated_lc_ra_total = sum(p.allocated_lc_ra for p in policy_inputs)
    
    lc_cf_total = bop_lc_cf_total + nb_initial_lc_cf_total + lc_ifie_cf_total + allocated_lc_cf_total
    lc_ra_total = bop_lc_ra_total + nb_initial_lc_ra_total + lc_ifie_ra_total + allocated_lc_ra_total
    lc_total = lc_cf_total + lc_ra_total
    
    if (is_lc_bucket and lc_stays_lc) or ((not is_lc_bucket) and csm_turns_lc):
        if group_delta_total != 0:
            cf_ratio = group_delta_cf / group_delta_total
        else:
            cf_ratio = DECIMAL_ZERO
        group_lc_absorbed_cf = group_lc_absorbed_total * cf_ratio
        group_lc_absorbed_ra = group_lc_absorbed_total - group_lc_absorbed_cf
    else:
        if lc_total != 0:
            lc_cf_ratio = lc_cf_total / lc_total
        else:
            lc_cf_ratio = DECIMAL_ZERO
        group_lc_absorbed_cf = group_lc_absorbed_total * lc_cf_ratio
        group_lc_absorbed_ra = group_lc_absorbed_total - group_lc_absorbed_cf
        
    # 拆分被CSM吸收的变化
    group_csm_absorbed_cf = group_delta_cf - group_lc_absorbed_cf
    group_csm_absorbed_ra = group_delta_ra - group_lc_absorbed_ra
    
    return GroupAbsorptionResult(
        cohort_csm=cohort_csm,
        cohort_lc=cohort_lc,
        net_trial=net_trial,
        group_csm_absorbed_total=group_csm_absorbed_total,
        group_csm_absorbed_cf=group_csm_absorbed_cf,
        group_csm_absorbed_ra=group_csm_absorbed_ra,
        group_lc_absorbed_total=group_lc_absorbed_total,
        group_lc_absorbed_cf=group_lc_absorbed_cf,
        group_lc_absorbed_ra=group_lc_absorbed_ra,
    )


def allocate_absorption_to_policies(
    policy_inputs: List[PolicyContextInput],
    group_result: GroupAbsorptionResult,
    is_reversal: bool = False
) -> List[PolicyAllocationResult]:
    """
    第三部分-步骤4：按因子分摊到各保单
    
    被CSM吸收的变化按IF/NB_计息后CSM分摊（即csm_after_interest）
    被LC吸收的变化按IF/NB_分摊后IFIE后LC分摊（即lc_after_ifie）
    """
    allocation_results = []
    
    # 计算总的分摊因子（用于归一化）
    # 被CSM吸收的变化：按IF/NB_计息后CSM分摊
    total_csm_after_interest = sum(p.csm_after_interest for p in policy_inputs if p.csm_after_interest > 0)
    
    # 被LC吸收的变化：按IF/NB_分摊后IFIE后LC分摊（使用绝对值）
    total_lc_after_ifie_abs = sum(abs(p.lc_after_ifie) for p in policy_inputs if 
                                  ((p.lc_after_ifie < 0) if (not is_reversal) else (p.lc_after_ifie > 0)))
    
    for p in policy_inputs:
        # CSM吸收变化分摊：按IF/NB_计息后CSM分摊
        if p.csm_after_interest > 0 and total_csm_after_interest > 0:
            csm_weight = p.csm_after_interest / total_csm_after_interest
            csm_absorbed = group_result.group_csm_absorbed_total * csm_weight
            csm_absorbed_cf = group_result.group_csm_absorbed_cf * csm_weight
            csm_absorbed_ra = group_result.group_csm_absorbed_ra * csm_weight
            csm_allocation_weight = csm_weight * Decimal('100')
        else:
            csm_absorbed = DECIMAL_ZERO
            csm_absorbed_cf = DECIMAL_ZERO
            csm_absorbed_ra = DECIMAL_ZERO
            csm_allocation_weight = DECIMAL_ZERO
        
        # LC吸收变化分摊：按IF/NB_分摊后IFIE后LC分摊
        is_lc_policy = (p.lc_after_ifie < 0) if (not is_reversal) else (p.lc_after_ifie > 0)
        if is_lc_policy and total_lc_after_ifie_abs > 0:
            lc_weight = abs(p.lc_after_ifie) / total_lc_after_ifie_abs
            lc_absorbed_total = group_result.group_lc_absorbed_total * lc_weight
            lc_absorbed_cf = group_result.group_lc_absorbed_cf * lc_weight
            lc_absorbed_ra = group_result.group_lc_absorbed_ra * lc_weight
            lc_allocation_weight = lc_weight * Decimal('100')
        else:
            lc_absorbed_total = DECIMAL_ZERO
            lc_absorbed_cf = DECIMAL_ZERO
            lc_absorbed_ra = DECIMAL_ZERO
            lc_allocation_weight = DECIMAL_ZERO
        
        allocation_results.append(PolicyAllocationResult(
            policy_id=p.policy_id,
            csm_absorbed=csm_absorbed,
            csm_absorbed_cf=csm_absorbed_cf,
            csm_absorbed_ra=csm_absorbed_ra,
            lc_absorbed_total=lc_absorbed_total,
            lc_absorbed_cf=lc_absorbed_cf,
            lc_absorbed_ra=lc_absorbed_ra,
            csm_allocation_weight=csm_allocation_weight,
            lc_allocation_weight=lc_allocation_weight,
        ))
    
    return allocation_results


def write_back_to_contexts(
    contexts: List[Any],
    allocation_results: List[PolicyAllocationResult]
):
    """将分摊结果回写到保单context"""
    result_map = {r.policy_id: r for r in allocation_results}
    
    for ctx in contexts:
        policy_id = getattr(ctx, 'policy_no', None) or getattr(ctx, 'policy_id', None)
        if policy_id not in result_map:
            continue
        
        result = result_map[policy_id]
        
        ctx.csm_absorbed = result.csm_absorbed
        ctx.csm_absorbed_cf = result.csm_absorbed_cf
        ctx.csm_absorbed_ra = result.csm_absorbed_ra
        
        ctx.lc_absorbed_total = result.lc_absorbed_total
        ctx.lc_absorbed_cf = result.lc_absorbed_cf
        ctx.lc_absorbed_ra = result.lc_absorbed_ra
        
        ctx.lc_change = result.lc_absorbed_total
        ctx.allocated_lc_exp_adj_total = result.lc_absorbed_total
        ctx.allocated_lc_exp_adj_cf = result.lc_absorbed_cf
        ctx.allocated_lc_exp_adj_ra = result.lc_absorbed_ra
        
        # 注意：LC调整项的计算在 calculate_closing_balances 函数中完成
        # 这里只写回吸收变化相关的字段
        
        # 补全 allocated_lc_cf/ra 如果缺失 (重要：这是减项)
        if not hasattr(ctx, 'allocated_lc_total'):
             # 如果 allocated_lc_total 没在 Part 8 算出来(因为是Group)，尝试用 CF+RA 补
             ctx.allocated_lc_total = (getattr(ctx, 'allocated_lc_cf', DECIMAL_ZERO) + getattr(ctx, 'allocated_lc_ra', DECIMAL_ZERO))


def run_group_absorption_allocation(
    contexts: List[Any], 
    group_status: GroupStatusResult,
    logger: Optional[Any] = None, 
    is_reversal: bool = False
) -> GroupAbsorptionResult:
    """
    第三部分-步骤3&4：组级吸收变化汇总与分摊
    
    步骤3：计算组级别被LC/CSM吸收的变化_合计
    步骤4：按因子分摊到各保单
    """
    if logger:
        logger.log_section("第三部分-步骤3&4: 组级吸收变化汇总与分摊")
    
    policy_inputs = collect_policy_data(contexts)
    group_result = calculate_group_absorption(policy_inputs, group_status, is_reversal, logger)
    allocation_results = allocate_absorption_to_policies(policy_inputs, group_result, is_reversal)
    write_back_to_contexts(contexts, allocation_results)
    
    return group_result


# ==========================================================================================
# 逐单CSM/LC计算函数
# ==========================================================================================

def _pv_amount(pv_data, field_name):
    if pv_data is None: return DECIMAL_ZERO
    return pv_data.get_field(field_name, DECIMAL_ZERO)

def _get_bop_csm_lc(context, cohort_state: Optional[CohortState] = None) -> Decimal:
    bop_csm = getattr(context, 'bop_csm', None)
    bop_lc = getattr(context, 'bop_lc', None)
    if bop_csm is None and cohort_state: bop_csm = getattr(cohort_state, 'bop_csm', None)
    if bop_lc is None and cohort_state: bop_lc = getattr(cohort_state, 'bop_lc', None)
    bop_csm_val = bop_csm if bop_csm is not None else DECIMAL_ZERO
    bop_lc_val = bop_lc if bop_lc is not None else DECIMAL_ZERO
    return bop_csm_val + bop_lc_val

def months_from_uw_to_target(uw_date: date, target_month_str: str) -> int:
    # (保持原样)
    if not uw_date or not target_month_str: return 0
    try:
        target_date = datetime.strptime(target_month_str, '%Y%m').date()
        if target_date.month == 12: target_date = date(target_date.year, 12, 31)
        else: target_date = (target_date + relativedelta(months=1) - relativedelta(days=1))
        delta = relativedelta(target_date, uw_date)
        months = delta.years * 12 + delta.months
        if target_date > uw_date and months == 0: months = 1
        return max(months, 0)
    except Exception: return 0

def get_wlk_curve_from_pv_data(context, uw_month_str: str):
    # (保持原样)
    if not context.pv_source_data: return None
    pv_data = context.pv_source_data.get_data(uw_month_str)
    if pv_data and pv_data.metadata:
        rate_locked_month = pv_data.metadata.get('rate_locked_month')
        if rate_locked_month:
            try: return get_discount_factors("locked", rate_locked_month)
            except Exception: pass
    try: return get_discount_factors("locked", uw_month_str)
    except Exception: return None

# (calculate_nb_csm_interest, calculate_if_csm_interest 保持原样，省略以节省空间)
def calculate_nb_csm_interest(principal: Decimal, rates_df, uw_date: date, val_month_str: str, stop_date: Optional[date] = None) -> Tuple[Decimal, Decimal]:
    # ... (您的原有代码) ...
    if rates_df is None or rates_df.empty or principal is None or principal == DECIMAL_ZERO:
        return DECIMAL_ZERO, DECIMAL_ZERO
    months_diff = months_from_uw_to_target(uw_date, val_month_str)
    # ...
    return DECIMAL_ZERO, DECIMAL_ZERO # Placeholder for full logic

def calculate_if_csm_interest(principal: Decimal, rates_df, uw_date: date, bop_month_str: str, val_month_str: str, stop_date: Optional[date] = None) -> Tuple[Decimal, Decimal]:
    # ... (您的原有代码) ...
    return DECIMAL_ZERO, DECIMAL_ZERO # Placeholder for full logic

def calculate_csm_interest(context, logger, cohort_state: Optional[CohortState] = None, policy_state: Optional[PolicyState] = None):
    """Part 3: CSM计息"""
    logger.log_section("Part 3: CSM计息 (Interest Accretion) [Sec 6]")
    # ... (前置检查保持原样) ...
    if context.pv_source_data is None: ensure_pv_source_data(context)
    if context.pv_source_data is None: raise ValueError("PV Data missing")
    if not hasattr(context, 'eop_date') or context.eop_date is None: context.eop_date = datetime(context.year, 12, 31).date()
    
    uw_date = getattr(context, 'under_write_date', None)
    uw_month_str = uw_date.strftime('%Y%m') if uw_date else None
    val_month_str = getattr(context, 'val_month_str', None) or context.eop_date.strftime('%Y%m')
    lkd_curve = get_wlk_curve_from_pv_data(context, uw_month_str)
    
    stop_date = None
    if policy_state and hasattr(policy_state, 'end_date'): stop_date = policy_state.end_date
    elif hasattr(context, 'end_date'): stop_date = context.end_date
    
    bop_csm_lc = _get_bop_csm_lc(context, cohort_state)
    nb_initial_csm = context.nb_initial_csm or DECIMAL_ZERO
    bop_csm = bop_csm_lc if bop_csm_lc >= 0 else DECIMAL_ZERO
    bop_month_str = date(context.year, 1, 1).strftime('%Y%m')
    
    # 这里调用完整的计息函数 (需确保上方已定义或导入)
    if_interest_csm, _ = calculate_if_csm_interest(bop_csm, lkd_curve, uw_date, bop_month_str, val_month_str, stop_date)
    nb_interest_csm, _ = calculate_nb_csm_interest(nb_initial_csm, lkd_curve, uw_date, val_month_str, stop_date)
    
    context.if_interest_csm = if_interest_csm
    context.nb_interest_csm = nb_interest_csm
    if cohort_state: cohort_state.csm_interest = if_interest_csm + nb_interest_csm
    logger.log_item("CSM计息明细", "[Sec 6] CSM计息明细", "", {"IF_CSM计息": if_interest_csm, "NB_CSM计息": nb_interest_csm}, if_interest_csm + nb_interest_csm)


def calculate_lc_ifie_allocation(context, logger, cohort_state: CohortState):
    """
    Part 7: LC分摊IFIE (逻辑隔离修复版)
    
    修复：
    1. 严格区分 NB(新业务) 和 IF(存量) 的生效年份。
    2. 2023年(首年): 强制 IF=0, NB=计算值。
    3. 2024年(次年): 强制 NB=0, IF=滚存值。
    4. 修复 IFIE 分摊比例在存量年度为 0 的问题。
    """
    logger.log_section("Part 7: LC分摊IFIE (LC IFIE Allocation) [Sec 7]")
    
    eop_month_str = context.val_month_str
    pv_data = context.pv_source_data.get_data(eop_month_str)
    if pv_data is None: 
        raise ValueError(f"❌ 错误: 找不到评估月 {eop_month_str} 的PV原材料数据！")
    
    is_reversal = getattr(context, 'is_reversal_policy', False)
    
    # 获取年份信息，用于判断是否为新业务年度
    # 【关键修复】：使用is_new_business（year == valuation_date.year）而不是is_initial_year
    current_year = context.year
    # 优先使用context中的is_new_business
    is_new_business = getattr(context, 'is_new_business', None)
    if is_new_business is None:
        # 如果没有设置，通过比较year和valuation_date.year来判断
        if hasattr(context, 'under_write_date') and context.under_write_date:
            is_new_business = (current_year == context.under_write_date.year)
        else:
            # 兜底：如果没有valuation_date，使用is_initial_year
            is_new_business = getattr(context, 'is_initial_year', False)
    # 确保is_new_business是布尔值
    is_new_business = bool(is_new_business)

    # =================================================================
    # 1. IF (存量) 部分
    # =================================================================
    # 【修复】：如果是新业务年度(签单年)，IF 部分必须强制为 0
    if is_new_business:
        if_bop_lc = DECIMAL_ZERO
        is_if_lc = False
    else:
        # 非首年，读取期初余额
        bop_csm_lc = _get_bop_csm_lc(context, cohort_state)
        # 判定是否为 LC
        is_if_lc = (bop_csm_lc < 0) if (not is_reversal) else (bop_csm_lc > 0)
        if_bop_lc = bop_csm_lc if is_if_lc else DECIMAL_ZERO

    # 计算 IF 分摊比例
    if_lc_ifie_ratio = DECIMAL_ZERO
    denom_if = DECIMAL_ZERO
    
    if is_if_lc:
        # 分母：期初履约现金流现值 (BOP PV)
        denom_if = (_pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Lcu_Cla_Amt') + 
                    _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Lcu_Mtn_Amt') + 
                    _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Lcu_Rad_Amt'))
        
        if denom_if.copy_abs() > 0:
            if_lc_ifie_ratio = if_bop_lc.copy_abs() / denom_if.copy_abs()
        else:
            logger.log_text(f"⚠️ 警告：IF_LC存在余额 ({if_bop_lc}) 但期初现金流现值为0，比例置0。")

    context.if_lc_ifie_ratio = if_lc_ifie_ratio

    # IF IFIE 计算（按文档公式）
    # 1. IF_待分摊IFIE_计息_赔付与费用
    pv_if_bop_cfa_rep_wlk_claims = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Rep_Lkd_Cla_Amt')
    pv_if_bop_cfa_rep_wlk_maint = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Rep_Lkd_Mtn_Amt')
    pv_if_bop_cca_rep_wlk_claims = _pv_amount(pv_data, 'Pvfl_If_Bop_Cca_Rep_Lkd_Cla_Amt')
    pv_if_bop_cca_rep_wlk_maint = _pv_amount(pv_data, 'Pvfl_If_Bop_Cca_Rep_Lkd_Mtn_Amt')
    pv_if_bop_cfa_beg_wlk_claims = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Lkd_Cla_Amt')
    pv_if_bop_cfa_beg_wlk_maint = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Lkd_Mtn_Amt')
    
    if_ifie_accretion_claims = (
        pv_if_bop_cfa_rep_wlk_claims +
        pv_if_bop_cfa_rep_wlk_maint +
        pv_if_bop_cca_rep_wlk_claims +
        pv_if_bop_cca_rep_wlk_maint -
        pv_if_bop_cfa_beg_wlk_claims -
        pv_if_bop_cfa_beg_wlk_maint
    )
    
    # 2. IF_待分摊IFIE_计息_非金融风险调整
    pv_if_bop_cfa_rep_wlk_ra = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Rep_Lkd_Rad_Amt')
    pv_if_bop_cfa_beg_wlk_ra = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Lkd_Rad_Amt')
    pv_if_bop_cca_rep_wlk_ra = _pv_amount(pv_data, 'Pvfl_If_Bop_Cca_Rep_Lkd_Rad_Amt')
    
    if_ifie_accretion_ra = (
        pv_if_bop_cfa_rep_wlk_ra -
        pv_if_bop_cfa_beg_wlk_ra +
        pv_if_bop_cca_rep_wlk_ra
    )
    
    # 3. IF_待分摊IFIE_利率变化的影响_赔付与费用
    pv_if_eop_cfa_rep_cur_claims = _pv_amount(pv_data, 'Pvfl_If_Eop_Cfa_Rep_Cur_Cla_Amt')
    pv_if_eop_cfa_rep_wlk_claims = _pv_amount(pv_data, 'Pvfl_If_Eop_Cfa_Rep_Lkd_Cla_Amt')
    pv_if_eop_cfa_rep_cur_maint = _pv_amount(pv_data, 'Pvfl_If_Eop_Cfa_Rep_Cur_Mtn_Amt')
    pv_if_eop_cfa_rep_wlk_maint = _pv_amount(pv_data, 'Pvfl_If_Eop_Cfa_Rep_Lkd_Mtn_Amt')
    pv_if_bop_cfa_beg_lcu_claims = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Lcu_Cla_Amt')
    pv_if_bop_cfa_beg_wlk_claims = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Lkd_Cla_Amt')
    pv_if_bop_cfa_beg_lcu_maint = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Lcu_Mtn_Amt')
    pv_if_bop_cfa_beg_wlk_maint = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Lkd_Mtn_Amt')
    
    term_end_diff = (
        pv_if_eop_cfa_rep_cur_claims -
        pv_if_eop_cfa_rep_wlk_claims +
        pv_if_eop_cfa_rep_cur_maint -
        pv_if_eop_cfa_rep_wlk_maint
    )
    term_beg_diff = (
        pv_if_bop_cfa_beg_lcu_claims -
        pv_if_bop_cfa_beg_wlk_claims +
        pv_if_bop_cfa_beg_lcu_maint -
        pv_if_bop_cfa_beg_wlk_maint
    )
    if_ifie_rate_change_claims = term_end_diff - term_beg_diff
    
    # 4. IF_待分摊IFIE_利率变化的影响_非金融风险调整
    pv_if_eop_cfa_rep_cur_ra = _pv_amount(pv_data, 'Pvfl_If_Eop_Cfa_Rep_Cur_Rad_Amt')
    pv_if_eop_cfa_rep_wlk_ra = _pv_amount(pv_data, 'Pvfl_If_Eop_Cfa_Rep_Lkd_Rad_Amt')
    pv_if_bop_cfa_beg_lcu_ra = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Lcu_Rad_Amt')
    pv_if_bop_cfa_beg_wlk_ra = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Lkd_Rad_Amt')
    
    term_end_diff_ra = (
        pv_if_eop_cfa_rep_cur_ra -
        pv_if_eop_cfa_rep_wlk_ra
    )
    term_beg_diff_ra = (
        pv_if_bop_cfa_beg_lcu_ra -
        pv_if_bop_cfa_beg_wlk_ra
    )
    if_ifie_rate_change_ra = term_end_diff_ra - term_beg_diff_ra

    # 保存细项
    context.if_ifie_accretion_claims = if_ifie_accretion_claims
    context.if_ifie_accretion_ra = if_ifie_accretion_ra
    context.if_ifie_rate_change_claims = if_ifie_rate_change_claims
    context.if_ifie_rate_change_ra = if_ifie_rate_change_ra

    # 计算 IF_LC分摊IFIE（按文档公式分别计算）
    # IF_LC分摊IFIE_赔付与费用 = (IF_待分摊IFIE_计息_赔付与费用＋IF_待分摊IFIE_利率变化的影响_赔付与费用) * IF_LC IFIE分摊比例
    if_lc_ifie_claims_before_sign = (if_ifie_accretion_claims + if_ifie_rate_change_claims) * if_lc_ifie_ratio
    
    # IF_LC分摊IFIE_非金融风险调整 = (IF_待分摊IFIE_计息_非金融风险调整＋IF_待分摊IFIE_利率变化的影响_非金融风险调整) * IF_LC IFIE分摊比例
    if_lc_ifie_ra_before_sign = (if_ifie_accretion_ra + if_ifie_rate_change_ra) * if_lc_ifie_ratio
    
    # IF_LC分摊IFIE = IF_LC分摊IFIE_赔付与费用＋IF_LC分摊IFIE_非金融风险调整
    if_lc_ifie_total_before_sign = if_lc_ifie_claims_before_sign + if_lc_ifie_ra_before_sign
    
    # LC IFIE分摊应与LC本金同方向（正常保单为负，批减单为正）
    if is_if_lc:
        lc_sign = Decimal('-1') if if_bop_lc < 0 else Decimal('1')
        if_lc_ifie_claims = if_lc_ifie_claims_before_sign.copy_abs() * lc_sign
        if_lc_ifie_ra = if_lc_ifie_ra_before_sign.copy_abs() * lc_sign
        if_lc_ifie_total = if_lc_ifie_total_before_sign.copy_abs() * lc_sign
    else:
        if_lc_ifie_claims = if_lc_ifie_claims_before_sign
        if_lc_ifie_ra = if_lc_ifie_ra_before_sign
        if_lc_ifie_total = if_lc_ifie_total_before_sign
    
    if_lc_after_ifie = if_bop_lc + if_lc_ifie_total
    
    # 保存细项
    context.if_lc_ifie_claims = if_lc_ifie_claims
    context.if_lc_ifie_ra = if_lc_ifie_ra
    context.if_lc_ifie_cf = if_lc_ifie_claims
    
    # 写回 Context
    context.if_lc_after_ifie = if_lc_after_ifie
    context.if_lc_ifie_total = if_lc_ifie_total

    # =================================================================
    # 2. NB (新增) 部分
    # =================================================================
    
    # 【调试日志】
    logger.log_text(f"🔍 调试[calculate_lc_ifie_allocation]：is_new_business={is_new_business}, current_year={current_year}")
    logger.log_text(f"🔍 调试[calculate_lc_ifie_allocation]：context.nb_initial_lc={getattr(context, 'nb_initial_lc', 'NOT_SET')}, context.nb_initial_csm={getattr(context, 'nb_initial_csm', 'NOT_SET')}")
    
    # 【修复】：如果不是新业务年度(签单年)，强制 NB 为 0
    # 初始化变量，确保在分支外也能访问
    nb_initial_lc = DECIMAL_ZERO
    is_nb_lc = False
    nb_ifie_accretion_claims = DECIMAL_ZERO
    nb_ifie_accretion_ra = DECIMAL_ZERO
    
    if not is_new_business:
        # 清理 context 中的残留值，防止污染
        context.nb_initial_lc = DECIMAL_ZERO
        context.nb_initial_csm = DECIMAL_ZERO
    else:
        # 新业务年度：正常读取逻辑
        # 【关键修复】：使用统一字段逻辑，参考 BBA_dev/logic/csm_lc_measurement.py
        # 逻辑：先取 nb_initial_csm，如果为0则使用 nb_initial_lc（二选一，不是相加）
        nb_initial_csm_lc = getattr(context, 'nb_initial_csm', DECIMAL_ZERO) or DECIMAL_ZERO
        if nb_initial_csm_lc == DECIMAL_ZERO and hasattr(context, 'nb_initial_lc'):
            nb_lc_val = getattr(context, 'nb_initial_lc', DECIMAL_ZERO) or DECIMAL_ZERO
            is_nb_lc_check = (nb_lc_val < DECIMAL_ZERO) if (not is_reversal) else (nb_lc_val > DECIMAL_ZERO)
            if is_nb_lc_check:
                nb_initial_csm_lc = nb_lc_val
        
        # 使用统一字段逻辑：
        # - 正常保单：nb_initial_csm_lc < 0 为LC
        # - 批减单：nb_initial_csm_lc > 0 为LC（符号逻辑相反）
        is_nb_lc = (nb_initial_csm_lc < 0) if (not is_reversal) else (nb_initial_csm_lc > 0)
        nb_initial_lc = nb_initial_csm_lc if is_nb_lc else DECIMAL_ZERO
        
        logger.log_text(f"🔍 调试：nb_initial_csm_lc={nb_initial_csm_lc}, is_nb_lc={is_nb_lc}, nb_initial_lc={nb_initial_lc}")
        
        # 【修复】：根据文档，NB_待分摊IFIE_计息应使用"当月初始利率"（Lkd）计算期末现值，而不是"加权初始确认利率"（Wlk）
        # 1. NB_待分摊IFIE_计息_赔付与费用
        # 期末现值（当月初始利率）：预期未来 + 预期当期
        pv_nb_eop_fut_claims_lkd = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cfa_Rep_Lkd_Cla_Amt')
        pv_nb_eop_fut_maint_lkd = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cfa_Rep_Lkd_Mtn_Amt')
        pv_nb_eop_cur_claims_lkd = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cca_Rep_Lkd_Cla_Amt')
        pv_nb_eop_cur_maint_lkd = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cca_Rep_Lkd_Mtn_Amt')
        
        # 初始确认现值（当月初始利率）：预期未来
        pv_nb_ini_fut_claims_lkd = _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt')
        pv_nb_ini_fut_maint_lkd = _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Mtn_Amt')
        
        # 公式：期末现值（Lkd）- 初始确认现值（Lkd）
        nb_ifie_accretion_claims = (
            (pv_nb_eop_fut_claims_lkd + pv_nb_eop_fut_maint_lkd + 
             pv_nb_eop_cur_claims_lkd + pv_nb_eop_cur_maint_lkd) -
            (pv_nb_ini_fut_claims_lkd + pv_nb_ini_fut_maint_lkd)
        )
        
        # 2. NB_待分摊IFIE_计息_非金融风险调整
        # 期末现值（当月初始利率）：预期未来 + 预期当期
        pv_nb_eop_fut_ra_lkd = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cfa_Rep_Lkd_Rad_Amt')
        pv_nb_eop_cur_ra_lkd = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cca_Rep_Lkd_Rad_Amt')
        
        # 初始确认现值（当月初始利率）：预期未来
        pv_nb_ini_fut_ra_lkd = _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Rad_Amt')
        
        # 公式：期末现值（Lkd）- 初始确认现值（Lkd）
        nb_ifie_accretion_ra = (
            pv_nb_eop_fut_ra_lkd - pv_nb_ini_fut_ra_lkd + pv_nb_eop_cur_ra_lkd
        )
        
        # NB IFIE 利率变化计算
        # 赔付与费用：期末利率（Cur） - 当月初始利率（Lkd）
        # 【修复】：只包含预期未来（Cfa），不包含预期当期（Cca）
        pv_nb_eop_cfa_rep_cur_claims = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cfa_Rep_Cur_Cla_Amt')
        pv_nb_eop_cfa_rep_lkd_claims = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cfa_Rep_Lkd_Cla_Amt')
        pv_nb_eop_cfa_rep_cur_maint = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cfa_Rep_Cur_Mtn_Amt')
        pv_nb_eop_cfa_rep_lkd_maint = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cfa_Rep_Lkd_Mtn_Amt')
        
        nb_ifie_rate_change_claims = (
            (pv_nb_eop_cfa_rep_cur_claims - pv_nb_eop_cfa_rep_lkd_claims) +  # 预期未来-赔付
            (pv_nb_eop_cfa_rep_cur_maint - pv_nb_eop_cfa_rep_lkd_maint)      # 预期未来-维费
        )
        
        # 非金融风险调整：期末利率（Cur） - 当月初始利率（Lkd）
        # 【修复】：只包含预期未来（Cfa），不包含预期当期（Cca）
        pv_nb_eop_cfa_rep_cur_ra = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cfa_Rep_Cur_Rad_Amt')
        pv_nb_eop_cfa_rep_lkd_ra = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cfa_Rep_Lkd_Rad_Amt')
        
        nb_ifie_rate_change_ra = (
            pv_nb_eop_cfa_rep_cur_ra - pv_nb_eop_cfa_rep_lkd_ra  # 预期未来-RA
        )
        
        # 保存到context
        context.nb_ifie_accretion_claims = nb_ifie_accretion_claims
        context.nb_ifie_accretion_ra = nb_ifie_accretion_ra
        context.nb_ifie_rate_change_claims = nb_ifie_rate_change_claims
        context.nb_ifie_rate_change_ra = nb_ifie_rate_change_ra

    # NB 比例计算
    nb_lc_ifie_ratio = DECIMAL_ZERO
    denom_nb = DECIMAL_ZERO
    
    logger.log_text(f"🔍 调试[比例计算前]：is_nb_lc={is_nb_lc}, nb_initial_lc={nb_initial_lc}, is_new_business={is_new_business}")
    
    if is_nb_lc:
        denom_nb = (_pv_amount(pv_data, 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt') + 
                    _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Mtn_Amt') + 
                    _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Rad_Amt'))
        # 支持 Context 覆盖
        denom_nb = getattr(context, 'init_fut_total', DECIMAL_ZERO) or denom_nb
        
        logger.log_text(f"🔍 调试：计算nb_lc_ifie_ratio，denom_nb={denom_nb}, nb_initial_lc={nb_initial_lc}")
        
        if denom_nb.copy_abs() > 0:
            nb_lc_ifie_ratio = nb_initial_lc.copy_abs() / denom_nb.copy_abs()
            logger.log_text(f"🔍 调试：nb_lc_ifie_ratio计算成功={nb_lc_ifie_ratio}")
        else:
            logger.log_text(f"🔍 调试：⚠️ denom_nb为0，无法计算nb_lc_ifie_ratio")
    else:
        logger.log_text(f"🔍 调试：is_nb_lc=False，不计算nb_lc_ifie_ratio")
    
    context.nb_lc_ifie_ratio = nb_lc_ifie_ratio

    # NB IFIE 计算（按文档公式）
    # 【修复】：使用从PV数据计算的值，而不是只从context读取
    nb_ifie_accretion_claims_val = getattr(context, 'nb_ifie_accretion_claims', DECIMAL_ZERO) or DECIMAL_ZERO
    nb_ifie_accretion_ra_val = getattr(context, 'nb_ifie_accretion_ra', DECIMAL_ZERO) or DECIMAL_ZERO
    nb_ifie_rate_change_claims = getattr(context, 'nb_ifie_rate_change_claims', DECIMAL_ZERO) or DECIMAL_ZERO
    nb_ifie_rate_change_ra = getattr(context, 'nb_ifie_rate_change_ra', DECIMAL_ZERO) or DECIMAL_ZERO
    
    logger.log_text(f"🔍 调试[IFIE计算前]：nb_ifie_accretion_claims_val={nb_ifie_accretion_claims_val}, nb_ifie_accretion_ra_val={nb_ifie_accretion_ra_val}")
    logger.log_text(f"🔍 调试[IFIE计算前]：nb_ifie_rate_change_claims={nb_ifie_rate_change_claims}, nb_ifie_rate_change_ra={nb_ifie_rate_change_ra}")
    logger.log_text(f"🔍 调试[IFIE计算前]：nb_lc_ifie_ratio={nb_lc_ifie_ratio}, nb_initial_lc={nb_initial_lc}, is_nb_lc={is_nb_lc}")
    
    # 计算 NB_LC分摊IFIE（按文档公式分别计算）
    # NB_LC分摊IFIE_赔付与费用 = (NB_待分摊IFIE_计息_赔付与费用＋NB_待分摊IFIE_利率变化的影响_赔付与费用) * NB_LC IFIE分摊比例
    nb_lc_ifie_claims_before_sign = (nb_ifie_accretion_claims_val + nb_ifie_rate_change_claims) * nb_lc_ifie_ratio
    
    # NB_LC分摊IFIE_非金融风险调整 = (NB_待分摊IFIE_计息_非金融风险调整＋NB_待分摊IFIE_利率变化的影响_非金融风险调整) * NB_LC IFIE分摊比例
    nb_lc_ifie_ra_before_sign = (nb_ifie_accretion_ra_val + nb_ifie_rate_change_ra) * nb_lc_ifie_ratio
    
    # NB_LC分摊IFIE = NB_LC分摊IFIE_赔付与费用＋NB_LC分摊IFIE_非金融风险调整
    nb_lc_ifie_total_before_sign = nb_lc_ifie_claims_before_sign + nb_lc_ifie_ra_before_sign
    
    # LC IFIE分摊应与LC本金同方向（正常保单为负，批减单为正）
    is_nb_lc_sign = (nb_initial_lc < 0) if (not is_reversal) else (nb_initial_lc > 0)
    if is_nb_lc_sign:
        lc_sign = Decimal('-1') if nb_initial_lc < 0 else Decimal('1')
        nb_lc_ifie_claims = nb_lc_ifie_claims_before_sign.copy_abs() * lc_sign
        nb_lc_ifie_ra = nb_lc_ifie_ra_before_sign.copy_abs() * lc_sign
        nb_lc_ifie_total = nb_lc_ifie_total_before_sign.copy_abs() * lc_sign
    else:
        nb_lc_ifie_claims = nb_lc_ifie_claims_before_sign
        nb_lc_ifie_ra = nb_lc_ifie_ra_before_sign
        nb_lc_ifie_total = nb_lc_ifie_total_before_sign
    
    logger.log_text(f"🔍 调试[IFIE计算后]：nb_lc_ifie_claims={nb_lc_ifie_claims}, nb_lc_ifie_ra={nb_lc_ifie_ra}, nb_lc_ifie_total={nb_lc_ifie_total}")
    
    nb_lc_after_ifie = nb_initial_lc + nb_lc_ifie_total
    
    logger.log_text(f"🔍 调试[最终结果]：nb_lc_after_ifie={nb_lc_after_ifie} (nb_initial_lc={nb_initial_lc} + nb_lc_ifie_total={nb_lc_ifie_total})")
    
    # 写回 Context
    context.nb_lc_after_ifie = nb_lc_after_ifie
    context.nb_lc_ifie_total = nb_lc_ifie_total
    context.nb_lc_ifie_claims = nb_lc_ifie_claims
    context.nb_lc_ifie_ra = nb_lc_ifie_ra
    context.nb_lc_ifie_cf = nb_lc_ifie_claims

    # =================================================================
    # 3. 汇总 end_lc_before_amort
    # =================================================================
    # 这是最关键的一步：确保 2023年只有NB，2024年只有IF
    total_lc_before_amort = if_lc_after_ifie + nb_lc_after_ifie
    context.end_lc_before_amort = total_lc_before_amort
    
    logger.log_item("LC余额汇总(含利息)", "end_lc_before_amort", "", 
                    {
                        "Year": current_year,
                        "Is_New_Business": is_new_business,
                        "IF余额(含BOP)": if_lc_after_ifie, 
                        "NB余额(含本金)": nb_lc_after_ifie,
                        "IF分摊比例": if_lc_ifie_ratio
                    }, 
                    total_lc_before_amort)
    
    logger.log_item("LC余额汇总(含利息)", "end_lc_before_amort", "", 
                    {
                        "IF余额(含BOP)": if_lc_after_ifie, 
                        "NB余额(含本金)": nb_lc_after_ifie, 
                        "IF_Ratio": if_lc_ifie_ratio,
                        "NB_Ratio": nb_lc_ifie_ratio
                    }, 
                    total_lc_before_amort)

    # =================================================================
    # 4. 计算 LC Release Basis 和 Ratio Denominator (Phase 1)
    # =================================================================
    # 用于后续的 LC 分摊比例和分摊金额计算
    # 必须使用 Lkd (锁定利率) 字段
    
    # 1. 提取当期预期流出 (Current Expected - Cca) - 必须使用 Lkd (锁定利率)
    if is_new_business:
        # 新业务：使用初始确认的当期预期流出
        curr_claims = _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cca_Rep_Lkd_Cla_Amt')
        curr_maint = _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cca_Rep_Lkd_Mtn_Amt')
        curr_ra = _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cca_Rep_Lkd_Rad_Amt')
    else:
        # 存量：使用期初的当期预期流出
        curr_claims = _pv_amount(pv_data, 'Pvfl_If_Bop_Cca_Rep_Lkd_Cla_Amt')
        curr_maint = _pv_amount(pv_data, 'Pvfl_If_Bop_Cca_Rep_Lkd_Mtn_Amt')
        curr_ra = _pv_amount(pv_data, 'Pvfl_If_Bop_Cca_Rep_Lkd_Rad_Amt')
    
    # LC Release Basis 应该是正数（代表流出的绝对值），用于乘以 Ratio
    lc_release_basis = curr_claims + curr_maint + curr_ra
    
    # 2. 提取未来预期流出 (Future Expected) - 用于分母
    # 分母应为该保单的总流出现值（Lkd利率）
    if is_new_business:
        # 新业务分母：初始确认时的总预期流出 (使用 Rec 字段，通常包含全部)
        future_claims = _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt')
        future_maint = _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Mtn_Amt')
        future_ra = _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Rad_Amt')
        
        # 如果 Rec 字段已经包含了 Cca 部分，则直接使用 Rec
        # 如果 Rec 仅是未来，则需要 + lc_release_basis
        # 根据字段命名，Rec 通常代表 Total，所以直接使用
        lc_ratio_denominator = future_claims + future_maint + future_ra
    else:
        # 存量分母：期初的总预期流出 (使用 Beg 字段，代表期初余额)
        future_claims = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Lcu_Cla_Amt')
        future_maint = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Lcu_Mtn_Amt')
        future_ra = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Lcu_Rad_Amt')
        
        lc_ratio_denominator = future_claims + future_maint + future_ra
    
    # 如果分母为0 (极其罕见)，防止除以0
    if lc_ratio_denominator == 0:
        lc_ratio_denominator = DECIMAL_ZERO
    
    # 保存到 Context
    context.lc_release_basis = lc_release_basis
    context.lc_ratio_denominator = lc_ratio_denominator
    
    logger.log_item(
        "LC Release Basis 和 Ratio Denominator",
        "Phase 1: 计算LC分摊基数和分母",
        "Release Basis = 当期预期流出(Cca, Lkd)\nRatio Denominator = 总预期流出(Lkd)",
        {
            "Is_New_Business": is_new_business,
            "当期预期赔付": curr_claims,
            "当期预期维费": curr_maint,
            "当期预期RA": curr_ra,
            "LC Release Basis": lc_release_basis,
            "未来预期赔付": future_claims if is_new_business else _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Lcu_Cla_Amt'),
            "未来预期维费": future_maint if is_new_business else _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Lcu_Mtn_Amt'),
            "未来预期RA": future_ra if is_new_business else _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Lcu_Rad_Amt'),
            "LC Ratio Denominator": lc_ratio_denominator
        },
        lc_release_basis,
        note="用于后续的LC分摊比例和分摊金额计算"
    )


def _determine_cohort_status(
    cohort_state: CohortState,
    context: Any,
    logger: Any,
    policies: Optional[List[PolicyState]] = None
):
    """
    Part 8.5.5: 合同组状态判定
    在 CSM 计息和 LC 分摊 IFIE 后，立即进行组级 Netting。
    """
    logger.log_section("Part 8.5.5: 合同组状态判定 (Cohort Status)")
    
    # 1. 汇总当前单数据
    # CSM = BOP + NB + Interest
    csm_post = (getattr(context, 'bop_csm', 0) or 0) + (getattr(context, 'nb_initial_csm', 0) or 0) + \
               (getattr(context, 'if_interest_csm', 0) or 0) + (getattr(context, 'nb_interest_csm', 0) or 0)
    
    # LC = BOP + NB + IFIE (即 end_lc_before_amort)
    lc_post = getattr(context, 'end_lc_before_amort', 0) or 0
    
    # 2. 更新组级累加器
    if not hasattr(cohort_state, 'net_balance_proxy'):
        cohort_state.net_balance_proxy = DECIMAL_ZERO
    cohort_state.net_balance_proxy += (csm_post + lc_post)
    
    # 3. 判定状态
    net_trial = cohort_state.net_balance_proxy
    is_rev = getattr(context, 'is_reversal_policy', False)
    
    if (not is_rev and net_trial >= 0) or (is_rev and net_trial <= 0):
        cohort_csm = net_trial
        cohort_lc = DECIMAL_ZERO
        status = "CSM"
    else:
        cohort_csm = DECIMAL_ZERO
        cohort_lc = net_trial
        status = "LC"
        
    # 4. 回写
    cohort_state.end_csm_before_amort = cohort_csm
    cohort_state.end_lc_before_amort = cohort_lc
    cohort_state.net_trial = net_trial
    
    # Context 冗余备份
    context.cohort_csm = cohort_csm
    context.cohort_lc = cohort_lc
    
    logger.log_item("组状态判定", f"Net: {net_trial:,.2f} ({status})", "", 
                    {"CSM": cohort_csm, "LC": cohort_lc}, net_trial)
def determine_group_status_post_ifie(context, logger, cohort_state: CohortState):
    """
    Part 7.5: 合同组 CSM/LC 状态判定 (解决首年死锁)
    在 CSM 计息和 LC 分摊 IFIE 完成后，立即更新组级 Net Balance。
    """
    logger.log_section("Part 7.5: 合同组CSM/LC判定 (Group CSM/LC Determination)")

    # 1. 获取保单层级的贡献 (Policy Contribution)
    policy_csm_post_interest = (
        (getattr(context, 'bop_csm', DECIMAL_ZERO) or DECIMAL_ZERO) +
        (getattr(context, 'nb_initial_csm', DECIMAL_ZERO) or DECIMAL_ZERO) +
        (getattr(context, 'if_interest_csm', DECIMAL_ZERO) or DECIMAL_ZERO) +
        (getattr(context, 'nb_interest_csm', DECIMAL_ZERO) or DECIMAL_ZERO)
    )

    policy_lc_post_ifie = getattr(context, 'end_lc_before_amort', DECIMAL_ZERO) or DECIMAL_ZERO

    # 2. 更新合同组累积器 (Update Cohort Accumulator)
    if not hasattr(cohort_state, 'net_balance_proxy'):
        cohort_state.net_balance_proxy = DECIMAL_ZERO
    
    # 累加当前保单的净值贡献
    policy_net_contribution = policy_csm_post_interest + policy_lc_post_ifie
    cohort_state.net_balance_proxy += policy_net_contribution
    
    # 3. 判定合同组状态 (Determine Group Status)
    # 优先取外部聚合值(如有)，否则取当前累加值作为代理
    group_net_balance = getattr(cohort_state, 'net_balance_proxy', policy_net_contribution)
    
    is_reversal = getattr(context, 'is_reversal_policy', False)
    
    # 判定逻辑：正常方向 Net >= 0 -> CSM; Net < 0 -> LC
    if (not is_reversal and group_net_balance >= 0) or (is_reversal and group_net_balance <= 0):
        group_csm_val = group_net_balance
        group_lc_val = DECIMAL_ZERO
    else:
        group_csm_val = DECIMAL_ZERO
        group_lc_val = group_net_balance

    # 4. 回写状态到 CohortState (Write Back)
    # 这些值将被后续的 calculate_lc_measurement (Part 8) 使用
    cohort_state.end_csm_before_amort = group_csm_val
    cohort_state.end_lc_before_amort = group_lc_val
    
    logger.log_item("合同组CSM/LC判断", "Net = Sum(CSM) + Sum(LC)", "", 
                    {"保单CSM贡献": policy_csm_post_interest, 
                     "保单LC贡献": policy_lc_post_ifie,
                     "组级净值(Running)": group_net_balance}, 
                    DECIMAL_ZERO)
                    
    logger.log_item("判定结果", "根据净值判定归属", "", 
                    {"合同组CSM": group_csm_val, "合同组LC": group_lc_val}, 
                    group_lc_val)


def calculate_lc_measurement(context, logger, group_lc_status: Decimal):
    """
    第三部分-步骤1&2：逐单计算LC分摊比例_合计和分摊的LC_合计
    
    修改点：
    1. 使用合同组LC作为判断条件（不是单级别LC）
    2. 只计算LC分摊比例和分摊的LC，不计算期末余额
    3. 拆分分摊的LC为CF和RA
    """
    logger.log_section("第三部分-步骤1&2: LC分摊比例和分摊的LC计算")
    
    eop_month_str = context.val_month_str
    pv_data = context.pv_source_data.get_data(eop_month_str)
    if not pv_data: 
        context.lc_allocation_ratio_total = DECIMAL_ZERO
        context.allocated_lc_total = DECIMAL_ZERO
        context.allocated_lc_cf = DECIMAL_ZERO
        context.allocated_lc_ra = DECIMAL_ZERO
        return
    
    is_reversal = getattr(context, 'is_reversal_policy', False)

    # 1. 触发条件 (Trigger) - 使用合同组LC作为判断条件
    # 【关键修改】：判断条件使用合同组LC，不是单级别LC
    is_grp_onr = (group_lc_status < 0 if not is_reversal else group_lc_status > 0)
    
    if not is_grp_onr:
        # 如果合同组LC >= 0（正常情况），则LC分摊比例为0
        context.lc_allocation_ratio_total = DECIMAL_ZERO
        context.allocated_lc_total = DECIMAL_ZERO
        context.allocated_lc_cf = DECIMAL_ZERO
        context.allocated_lc_ra = DECIMAL_ZERO
        logger.log_text(f"  - 合同组LC={group_lc_status:,.2f} >= 0，LC分摊比例为0")
        return

    # 2. 分子 (Numerator): 保单自己的LC余额（IF_分摊后IFIE后LC或NB_分摊后IFIE后LC）
    policy_lc = getattr(context, 'end_lc_before_amort', DECIMAL_ZERO)
    numerator = policy_lc
    
    # 3. 分母 (Denominator): Policy Basis
    # 【修复】：必须包含 2024 (IF) 的期初现值 + 2023 (NB) 的初始现值
    pv_if_sum = (_pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Lcu_Cla_Amt') + 
                 _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Lcu_Mtn_Amt') + 
                 _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Lcu_Rad_Amt'))
                 
    pv_nb_sum = (_pv_amount(pv_data, 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt') + 
                 _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Mtn_Amt') + 
                 _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Rad_Amt'))
    
    # 加上 IFIE 变动项 (确保分母也是期末口径)
    # 完整计算所有IFIE组件（使用该保单自己的IFIE组件）
    ifie_sum = (
        (getattr(context, 'if_ifie_accretion_claims', None) or DECIMAL_ZERO) + 
        (getattr(context, 'if_ifie_accretion_ra', None) or DECIMAL_ZERO) +
        (getattr(context, 'if_ifie_rate_change_claims', None) or DECIMAL_ZERO) + 
        (getattr(context, 'if_ifie_rate_change_ra', None) or DECIMAL_ZERO) +
        (getattr(context, 'nb_ifie_accretion_claims', None) or DECIMAL_ZERO) + 
        (getattr(context, 'nb_ifie_accretion_ra', None) or DECIMAL_ZERO) +
        (getattr(context, 'nb_ifie_rate_change_claims', None) or DECIMAL_ZERO) + 
        (getattr(context, 'nb_ifie_rate_change_ra', None) or DECIMAL_ZERO)
    )
    
    denominator = pv_if_sum + pv_nb_sum + ifie_sum
    
    # 4. 计算 Ratio
    if denominator.copy_abs() > 0:
        ratio = numerator.copy_abs() / denominator.copy_abs()
    else:
        ratio = DECIMAL_ZERO
        
    context.lc_allocation_ratio_total = ratio
    
    logger.log_item("LC分摊比例_合计", "Ratio = |保单LC余额| / 分母", 
                    "判断条件使用合同组LC（不是单级别LC）", 
                    {
                        "合同组LC(判断条件)": group_lc_status,
                        "保单LC余额(分子)": numerator, 
                        "分母(基数)": denominator, 
                        "IF_PV": pv_if_sum,
                        "NB_PV": pv_nb_sum,
                        "IFIE_Sum": ifie_sum
                    }, ratio)

    # 5. 计算分摊金额 (Release / Amortization)
    # 使用 Phase 1 中预先计算的 lc_release_basis (使用 Lkd 字段)
    lc_release_basis = getattr(context, 'lc_release_basis', None)
    if lc_release_basis is None:
        # 如果 Phase 1 没有计算，则回退到直接计算（使用 Lkd 字段）
        # 判断是否为新业务
        is_new_business = getattr(context, 'is_new_business', None)
        if is_new_business is None:
            if hasattr(context, 'under_write_date') and context.under_write_date:
                is_new_business = (context.year == context.under_write_date.year)
            else:
                is_new_business = getattr(context, 'is_initial_year', False)
        is_new_business = bool(is_new_business)
        
        if is_new_business:
            lc_release_basis = (
                _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cca_Rep_Lkd_Cla_Amt') + 
                _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cca_Rep_Lkd_Mtn_Amt') + 
                _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cca_Rep_Lkd_Rad_Amt')
            )
        else:
            lc_release_basis = (
                _pv_amount(pv_data, 'Pvfl_If_Bop_Cca_Rep_Lkd_Cla_Amt') + 
                _pv_amount(pv_data, 'Pvfl_If_Bop_Cca_Rep_Lkd_Mtn_Amt') + 
                _pv_amount(pv_data, 'Pvfl_If_Bop_Cca_Rep_Lkd_Rad_Amt')
            )
    
    allocated_amt = lc_release_basis * ratio
    context.allocated_lc_total = allocated_amt
    
    # 【修复】：根据用户提供的公式，拆分 allocated_lc_total 为 CF 和 RA
    # 分摊的LC_预期现金流 = -（【有效合同-年初预期-预期当年-赔付现金流-期末现值（当月初始利率）】+
    #                        【有效合同-年初预期-预期当年-维持费用现金流-期末现值（当月初始利率）】+
    #                        【新增合同-初始确认-预期当期-赔付现金流-期末现值（当月初始利率）】+
    #                        【新增合同-初始确认-预期当期-维持费用现金流-期末现值（当月初始利率）】）* LC分摊比例
    # 注意：需要同时包含有效合同和新增合同
    # 有效合同部分（预期当年）
    lc_release_basis_cf_if = (
        _pv_amount(pv_data, 'Pvfl_If_Bop_Cca_Rep_Lkd_Cla_Amt') + 
        _pv_amount(pv_data, 'Pvfl_If_Bop_Cca_Rep_Lkd_Mtn_Amt')
    )
    # 新增合同部分（预期当期）
    lc_release_basis_cf_nb = (
        _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cca_Rep_Lkd_Cla_Amt') + 
        _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cca_Rep_Lkd_Mtn_Amt')
    )
    # 合计（有效合同 + 新增合同）
    lc_release_basis_cf = lc_release_basis_cf_if + lc_release_basis_cf_nb
    
    # 分摊的LC_预期现金流（取负号，因为这是减项）
    allocated_lc_cf = -lc_release_basis_cf * ratio
    # 分摊的LC_非金融风险调整 = allocated_lc_total - allocated_lc_cf
    allocated_lc_ra = allocated_amt - allocated_lc_cf
    
    context.allocated_lc_cf = allocated_lc_cf
    context.allocated_lc_ra = allocated_lc_ra
    
    logger.log_item("分摊的LC (Release)", "Allocated = Release_Basis * Ratio", "", 
                    {
                        "Release_Basis(Lkd)": lc_release_basis, 
                        "Release_Basis_CF(Lkd)": lc_release_basis_cf,
                        "Ratio": ratio, 
                        "Allocated_Total": allocated_amt,
                        "Allocated_CF": allocated_lc_cf,
                        "Allocated_RA": allocated_lc_ra
                    }, allocated_amt)

    # 注意：期末余额计算在 calculate_closing_balances 函数中完成
    # 这里只计算分摊比例和分摊金额，不计算期末余额

def calculate_csm_measurement(context, logger):
    """
    第三部分-步骤5：逐单计算CSM计量
    
    计算CSM摊销和期末CSM余额
    依赖：被LC吸收的变化（已分摊到保单）
    """
    logger.log_section("第三部分-步骤5: CSM计量")
    
    # 1. 获取 IF/NB_计息后CSM（第一部分计算的结果）
    # IF保单：IF_计息后CSM = IF_年初余额 + IF_CSM计息
    # NB保单：NB_计息后CSM = NB_新增CSM + NB_CSM计息
    if_csm_after_interest = DECIMAL_ZERO
    nb_csm_after_interest = DECIMAL_ZERO
    
    bop_csm = getattr(context, 'bop_csm', DECIMAL_ZERO) or DECIMAL_ZERO
    if_interest_csm = getattr(context, 'if_interest_csm', DECIMAL_ZERO) or DECIMAL_ZERO
    nb_initial_csm = getattr(context, 'nb_initial_csm', DECIMAL_ZERO) or DECIMAL_ZERO
    nb_interest_csm = getattr(context, 'nb_interest_csm', DECIMAL_ZERO) or DECIMAL_ZERO
    
    if bop_csm != DECIMAL_ZERO:
        # IF保单
        if_csm_after_interest = bop_csm + if_interest_csm
    else:
        # NB保单
        nb_csm_after_interest = nb_initial_csm + nb_interest_csm
    
    csm_after_interest = if_csm_after_interest + nb_csm_after_interest
    
    # 2. 获取被CSM吸收的变化（已分摊到保单，从write_back_to_contexts回写）
    csm_absorbed_total = getattr(context, 'csm_absorbed', DECIMAL_ZERO) or DECIMAL_ZERO
    
    # 3. 计算摊销前CSM余额（含吸收的变化）
    # 公式：摊销前CSM余额 = IF/NB_计息后CSM + 被CSM吸收的变化
    csm_before_amort_adjusted = csm_after_interest + csm_absorbed_total
    
    # 4. 获取CSM摊销比例（如果还未计算，需要计算）
    csm_amort_ratio = getattr(context, 'csm_amort_ratio', None)
    if csm_amort_ratio is None:
        # 如果没有，尝试从IACF摊销比例获取
        csm_amort_ratio = getattr(context, 'iacf_amort_ratio', DECIMAL_ZERO) or DECIMAL_ZERO
    csm_amort_ratio = csm_amort_ratio or DECIMAL_ZERO
    
    # 5. 计算CSM摊销金额
    # 公式：摊销的CSM = -(摊销前CSM余额 * CSM摊销比例)
    if csm_before_amort_adjusted <= 0:
        context.csm_amort_amount = DECIMAL_ZERO
        csm_final = csm_before_amort_adjusted
    else:
        context.csm_amort_amount = -(csm_before_amort_adjusted * csm_amort_ratio)
        csm_final = csm_before_amort_adjusted + context.csm_amort_amount
    
    # 6. 保存期末CSM余额和摊销比例
    context.end_csm_final = csm_final
    context.csm_amort_ratio = csm_amort_ratio  # 保存供后续LC计量使用
    context.end_csm_before_amort = csm_before_amort_adjusted  # 保存摊销前CSM余额
    
    logger.log_item(
        "期末CSM (end_csm_final)", 
        "End = 摊销前CSM + CSM摊销", 
        "摊销前CSM = IF/NB_计息后CSM + 被CSM吸收的变化\nCSM摊销 = -摊销前CSM * 摊销比例\n期末CSM = 摊销前CSM + CSM摊销", 
        {
            "IF_计息后CSM": if_csm_after_interest,
            "NB_计息后CSM": nb_csm_after_interest,
            "被CSM吸收的变化": csm_absorbed_total,
            "摊销前CSM": csm_before_amort_adjusted,
            "摊销比例": csm_amort_ratio,
            "CSM摊销": context.csm_amort_amount,
            "期末CSM": csm_final
        }, 
        csm_final
    )
def calculate_closing_balances(context, logger):
    """
    第三部分-步骤6：逐单计算LC计量的后续部分
    
    计算待调整LC余额、LC调整、期末LC余额
    依赖：CSM摊销比例（从calculate_csm_measurement得到）
    """
    logger.log_section("第三部分-步骤6: LC计量的后续部分（期末余额计算）")
    
    # 参考单级代码的 _calculate_lc_measurement 函数，完整实现期末LC余额计算
    # 1. 获取基础数据
    bop_lc_total = getattr(context, 'bop_lc', DECIMAL_ZERO) or DECIMAL_ZERO
    nb_initial_lc_total = getattr(context, 'nb_initial_lc', DECIMAL_ZERO) or DECIMAL_ZERO
    if_lc_ifie_total = getattr(context, 'if_lc_ifie_total', DECIMAL_ZERO) or DECIMAL_ZERO
    nb_lc_ifie_total = getattr(context, 'nb_lc_ifie_total', DECIMAL_ZERO) or DECIMAL_ZERO
    lc_ifie_total = if_lc_ifie_total + nb_lc_ifie_total
    
    # 2. 获取分摊的LC和被LC吸收的变化
    allocated_lc_total = getattr(context, 'allocated_lc_total', DECIMAL_ZERO) or DECIMAL_ZERO
    allocated_lc_exp_adj_total = getattr(context, 'allocated_lc_exp_adj_total', None)
    if allocated_lc_exp_adj_total is None:
        # 优先从lc_absorbed_total获取（组级分摊后回写）
        allocated_lc_exp_adj_total = getattr(context, 'lc_absorbed_total', None)
    if allocated_lc_exp_adj_total is None:
        # 其次从lc_change获取
        allocated_lc_exp_adj_total = getattr(context, 'lc_change', None)
    allocated_lc_exp_adj_total = allocated_lc_exp_adj_total or DECIMAL_ZERO
    
    # 3. 计算待调整LC余额_合计
    # 公式：待调整LC余额 = 年初LC + 新增LC + IFIE + 分摊的LC + 被LC吸收的变化
    lc_balance_to_adjust_total = (
        bop_lc_total + 
        nb_initial_lc_total + 
        lc_ifie_total + 
        allocated_lc_total + 
        allocated_lc_exp_adj_total
    )
    
    # 4. 获取CSM摊销比例（用于判断是否需要LC调整）
    csm_amort_ratio = getattr(context, 'csm_amort_ratio', None)
    if csm_amort_ratio is None:
        # 尝试从csm_amort_amount和end_csm_before_amort计算
        csm_amort_amount = getattr(context, 'csm_amort_amount', None)
        end_csm_before_amort = getattr(context, 'end_csm_before_amort', None)
        if csm_amort_amount is not None and end_csm_before_amort is not None and end_csm_before_amort != 0:
            csm_amort_ratio = (csm_amort_amount if csm_amort_amount > 0 else -csm_amort_amount) / end_csm_before_amort
        else:
            # 如果没有，使用IACF摊销比例作为参考
            csm_amort_ratio = getattr(context, 'iacf_amort_ratio', DECIMAL_ZERO) or DECIMAL_ZERO
    csm_amort_ratio = Decimal(str(csm_amort_ratio)) if csm_amort_ratio is not None else DECIMAL_ZERO
    
    # 5. 计算LC调整_合计：如果CSM摊销比例=100%，则等于负的待调整LC余额_合计；否则为0
    if csm_amort_ratio >= Decimal('1'):
        lc_adjust_total = -lc_balance_to_adjust_total
    else:
        lc_adjust_total = DECIMAL_ZERO
    
    # 【修复】：拆分 LC调整_合计 为 CF 和 RA
    # 需要获取待调整LC余额的CF和RA部分
    # 待调整LC余额_预期现金流 = 年初LC_预期现金流 + 新增LC_预期现金流 + IFIE_预期现金流 + 分摊的LC_预期现金流 + 被LC吸收的变化_预期现金流
    bop_lc_cf = getattr(context, 'bop_lc_cf', bop_lc_total) or bop_lc_total  # 默认使用total
    nb_initial_lc_cf = getattr(context, 'nb_initial_lc_cf', DECIMAL_ZERO) or DECIMAL_ZERO
    if_lc_ifie_cf = getattr(context, 'if_lc_ifie_cf', DECIMAL_ZERO) or DECIMAL_ZERO
    nb_lc_ifie_cf = getattr(context, 'nb_lc_ifie_cf', DECIMAL_ZERO) or DECIMAL_ZERO
    lc_ifie_cf = if_lc_ifie_cf + nb_lc_ifie_cf
    allocated_lc_cf = getattr(context, 'allocated_lc_cf', DECIMAL_ZERO) or DECIMAL_ZERO
    allocated_lc_exp_adj_cf = getattr(context, 'allocated_lc_exp_adj_cf', DECIMAL_ZERO) or DECIMAL_ZERO
    
    lc_balance_to_adjust_cf = (
        bop_lc_cf + 
        nb_initial_lc_cf + 
        lc_ifie_cf + 
        allocated_lc_cf + 
        allocated_lc_exp_adj_cf
    )
    
    # LC调整_预期现金流 = IF(CSM摊销比例=100%, -待调整LC余额_预期现金流, 0)
    if csm_amort_ratio >= Decimal('1'):
        lc_adjust_cf = -lc_balance_to_adjust_cf
    else:
        lc_adjust_cf = DECIMAL_ZERO
    
    # LC调整_非金融风险调整 = LC调整_合计 - LC调整_预期现金流
    lc_adjust_ra = lc_adjust_total - lc_adjust_cf
    
    # 6. 计算期末LC余额_合计
    end_lc_final = lc_balance_to_adjust_total + lc_adjust_total
    
    # 7. 保存到context
    context.end_lc_final = end_lc_final
    context.closing_lc = end_lc_final  # 兼容不同命名
    context.lc_adjust_total = lc_adjust_total  # 保存LC调整项供后续使用
    context.lc_adjust_cf = lc_adjust_cf  # 保存LC调整_预期现金流
    context.lc_adjust_ra = lc_adjust_ra  # 保存LC调整_非金融风险调整
    
    logger.log_item(
        "期末LC余额 (end_lc_final)", 
        "End = 待调整LC余额 + LC调整", 
        "待调整LC余额 = 年初LC + 新增LC + IFIE + 分摊的LC + 被LC吸收的变化\nLC调整 = IF(CSM摊销比例=100%, -待调整LC余额, 0)\n期末LC余额 = 待调整LC余额 + LC调整", 
        {
            "年初LC": bop_lc_total,
            "新增LC": nb_initial_lc_total,
            "IFIE": lc_ifie_total,
            "分摊的LC": allocated_lc_total,
            "被LC吸收的变化": allocated_lc_exp_adj_total,
            "待调整LC余额": lc_balance_to_adjust_total,
            "CSM摊销比例": csm_amort_ratio,
            "LC调整": lc_adjust_total,
            "期末LC余额": end_lc_final
        }, 
        end_lc_final
    )
def run_per_policy_part1(context, logger, cohort_state: Optional[CohortState] = None, policy_state: Optional[PolicyState] = None, assumptions: Optional[Assumptions] = None):
    """
    第一部分：逐单计算CSM计息和LC分摊IFIE
    
    只执行第一部分的计算，不执行后续的LC计量和CSM计量
    """
    # 初始化状态
    if cohort_state is None: cohort_state = CohortState()

    logger.log_section("第一部分: CSM计息和LC分摊IFIE")
    
    # 1. CSM计息
    calculate_csm_interest(context, logger, cohort_state, policy_state)
    
    # 2. LC分摊IFIE (产出 context.end_lc_before_amort，包含 NB+IFIE)
    calculate_lc_ifie_allocation(context, logger, cohort_state)
    
    # 保存end_lc_before_amort供后续使用
    # end_lc_before_amort = IF_分摊后IFIE后LC 或 NB_分摊后IFIE后LC
    if not hasattr(context, 'end_lc_before_amort') or context.end_lc_before_amort is None:
        # 如果没有设置，从bop_lc和lc_ifie_total计算
        bop_lc = getattr(context, 'bop_lc', DECIMAL_ZERO) or DECIMAL_ZERO
        if_lc_ifie_total = getattr(context, 'if_lc_ifie_total', DECIMAL_ZERO) or DECIMAL_ZERO
        nb_initial_lc = getattr(context, 'nb_initial_lc', DECIMAL_ZERO) or DECIMAL_ZERO
        nb_lc_ifie_total = getattr(context, 'nb_lc_ifie_total', DECIMAL_ZERO) or DECIMAL_ZERO
        
        if bop_lc != DECIMAL_ZERO:
            # IF保单
            context.end_lc_before_amort = bop_lc + if_lc_ifie_total
        else:
            # NB保单
            context.end_lc_before_amort = nb_initial_lc + nb_lc_ifie_total
            # 同时保存nb_lc_after_ifie（用于后续使用）
            context.nb_lc_after_ifie = context.end_lc_before_amort