package com.bba.service;

import com.bba.entity.PolicyContract;
import com.bba.entity.RateCurve;
import com.bba.model.Assumptions;
import com.bba.model.CashFlow;
import com.bba.model.pv.PVSourceData;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Service
@Slf4j
@RequiredArgsConstructor
public class PVGeneratorService {

    private final DataLoaderService dataLoaderService;
    private final CashFlowProjectorService cashFlowProjectorService;
    private final PVCalculatorService pvCalculatorService;

    /**
     * Generate PV Source Data for a specific valuation date (usually EOP).
     * Replicates Python's pv_calculator.py logic for a single month.
     * 为特定的评估日期（通常是期末 EOP）生成 PV 原材料数据。
     * 复刻 Python pv_calculator.py 的单月计算逻辑。
     *
     * @param policy 保单数据
     * @param valuationDate 评估日期
     * @return PVSourceData 包含计算出的所有 PV 字段
     */
    public PVSourceData generatePVSourceData(PolicyContract policy, LocalDate valuationDate) {
        log.info("Generating PV Source Data for Policy: {}, Valuation Date: {}", policy.getPolicyNo(), valuationDate);

        PVSourceData pvData = new PVSourceData();
        pvData.setPolicyNo(policy.getPolicyNo());
        pvData.setValuationDate(valuationDate);
        pvData.setValuationMonth(valuationDate.format(java.time.format.DateTimeFormatter.ofPattern("yyyyMM")));
        pvData.setUnderWriteDate(policy.getUnderWriteDate());
        // [对齐Python最新口径] 批减单标记：以签单保费为负为准（PV原材料与计量阶段均按原始符号运行）
        boolean isReversalPolicy = policy.getSumPremiumNoTax() != null && policy.getSumPremiumNoTax().compareTo(BigDecimal.ZERO) < 0;
        pvData.getMetadata().put("is_reversal_policy", String.valueOf(isReversalPolicy));

        // 1. Prepare Dates / 准备日期
        LocalDate uwDate = policy.getUnderWriteDate();
        boolean isNewBusiness = (valuationDate.getYear() == uwDate.getYear());
        LocalDate yearStart = LocalDate.of(valuationDate.getYear(), 1, 1);
        LocalDate prevYearEnd = yearStart.minusDays(1);

        // 2. Fetch Rates / 获取利率曲线
        // Locked Curve: Based on UW Date / 锁定曲线：基于签单日
        List<RateCurve> lockedRates = loadRates("locked", uwDate);
        // Current Curve: Based on Valuation Date / 当前曲线：基于评估日
        List<RateCurve> currentRates = loadRates("current", valuationDate);
        
        // 3. Fetch Assumptions / 获取精算假设
        // UW Assumptions (for Initial Recognition) / 签单日假设（用于初始确认）
        Assumptions assumpUw = dataLoaderService.getAssumptions(policy.getClassCode(), uwDate.format(java.time.format.DateTimeFormatter.ofPattern("yyyyMM")), policy.getValMethod());
        // Current Valuation Assumptions (for EOP) / 当前评估日假设（用于期末计量）
        Assumptions assumpVal = dataLoaderService.getAssumptions(policy.getClassCode(), valuationDate.format(java.time.format.DateTimeFormatter.ofPattern("yyyyMM")), policy.getValMethod());
        // Previous Year End Assumptions (for BOP - only if not new business) / 上年末假设（用于期初计量 - 仅非新单）
        Assumptions assumpPrevYe = null;
        if (!isNewBusiness) {
            assumpPrevYe = dataLoaderService.getAssumptions(policy.getClassCode(), prevYearEnd.format(java.time.format.DateTimeFormatter.ofPattern("yyyyMM")), policy.getValMethod());
            if (assumpPrevYe == null) {
                log.warn("Previous Year End Assumptions not found, falling back to UW assumptions");
                assumpPrevYe = assumpUw;
            }
        }

        // 4. Project Cash Flows / 现金流预测
        // CF for Initial Recognition (based on UW assumptions) / 初始确认现金流（基于签单假设）
        List<CashFlow> cfUw = cashFlowProjectorService.projectPolicyFlows(policy, assumpUw);
        
        // CF for EOP (based on Val assumptions) / 期末现金流（基于当前假设）
        List<CashFlow> cfVal = cashFlowProjectorService.projectPolicyFlows(policy, assumpVal);
        
        // CF for BOP (based on Prev YE assumptions) / 期初现金流（基于上年末假设）
        List<CashFlow> cfPrevYe = null;
        if (!isNewBusiness) {
            cfPrevYe = cashFlowProjectorService.projectPolicyFlows(policy, assumpPrevYe);
        }

        // 5. Calculate PVs / 计算现值
        Map<String, BigDecimal> fields = pvData.getPvFields();

        // --- A. New Business Initial Recognition (Nb_Ini_Rec) / 新业务初始确认 ---
        // Only for New Business Year / 仅限新业务年度
        if (isNewBusiness) {
            calculateInitialRecognition(fields, cfUw, lockedRates, uwDate, assumpUw);
        }

        // --- B. In-Force Beginning of Period (If_Bop) / 有效业务期初 ---
        // Only for Non-New Business Year / 仅限非新业务年度
        if (!isNewBusiness && cfPrevYe != null) {
            // For BOP, we use Locked Rates (usually from previous year end)
            // But Python uses `rates_df` from `get_discount_factors("locked", uw_date)`.
            // So we pass lockedRates (which are loaded from UW date).
            // 对于 BOP，通常使用锁定利率（签单日利率）。
            calculateBop(fields, cfPrevYe, lockedRates, yearStart, uwDate, valuationDate, assumpPrevYe);
        }

        // --- C. End of Period (Nb_Eop or If_Eop) / 期末 ---
        String segment = isNewBusiness ? "Nb" : "If";
        calculateEop(fields, segment, cfVal, lockedRates, currentRates, valuationDate, uwDate, policy.getStartDate(), assumpVal);

        // Call unpack to populate strong-typed fields / 调用 unpack 方法填充强类型字段
        pvData.unpack();

        return pvData;
    }

    private List<RateCurve> loadRates(String type, LocalDate date) {
        return dataLoaderService.getRates(date.format(java.time.format.DateTimeFormatter.ofPattern("yyyyMM")));
    }

    private void calculateInitialRecognition(
            Map<String, BigDecimal> fields, 
            List<CashFlow> cf, 
            List<RateCurve> rates, 
            LocalDate uwDate,
            Assumptions assumptions
    ) {
        // LocalDate uwMonthMid = LocalDate.of(uwDate.getYear(), uwDate.getMonthValue(), 15);
        // PVCalculatorService handles logic using uwDate, but calculatePvInitialRecognition signature expects curveBaseDate and uwDate.
        
        BigDecimal pre = pvCalculatorService.calculatePvInitialRecognition(cf, CashFlow::getPremium, true, rates, uwDate, uwDate);
        BigDecimal acq = pvCalculatorService.calculatePvInitialRecognition(cf, CashFlow::getIacf, true, rates, uwDate, uwDate);
        BigDecimal cla = pvCalculatorService.calculatePvInitialRecognition(cf, CashFlow::getClaims, false, rates, uwDate, uwDate);
        BigDecimal mtn = pvCalculatorService.calculatePvInitialRecognition(cf, CashFlow::getExpenses, false, rates, uwDate, uwDate);
        
        if (pre == null) log.warn("DEBUG: pre is null in calculateInitialRecognition");
        if (acq == null) log.warn("DEBUG: acq is null in calculateInitialRecognition");
        if (cla == null) log.warn("DEBUG: cla is null in calculateInitialRecognition");
        if (mtn == null) log.warn("DEBUG: mtn is null in calculateInitialRecognition");

        // Handle nulls to avoid NPE
        if (cla == null) cla = BigDecimal.ZERO;
        if (mtn == null) mtn = BigDecimal.ZERO;

        BigDecimal rad = (cla.add(mtn)).multiply(assumptions.getRaRatio());

        // Correct keys matching PVSourceData.java
        fields.put("Pvfl_Nb_Ini_Cfa_Rec_Lkd_Pre_Amt", pre);
        fields.put("Pvfl_Nb_Ini_Cfa_Rec_Lkd_Acq_Amt", acq);
        fields.put("Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt", cla);
        fields.put("Pvfl_Nb_Ini_Cfa_Rec_Lkd_Mtn_Amt", mtn);
        fields.put("Pvfl_Nb_Ini_Cfa_Rec_Lkd_Rad_Amt", rad);
    }

    private void calculateBop(
            Map<String, BigDecimal> fields,
            List<CashFlow> cf,
            List<RateCurve> rates,
            LocalDate bopDate,
            LocalDate uwDate,
            LocalDate valuationDate,
            Assumptions assumptions
    ) {
        // [Assumption分支逻辑] 对齐 pv_calculator_assumption：
        // - Beg_Lcu：仅保存 Cla/Mtn/Rad（不保存 Pre/Acq），利率使用“上年末月份”的锁定曲线
        // - Beg_Wlk：仅保存 Cla/Mtn/Rad（用于IFIE_OCI等），折现基准日使用上年末(12/31)以避免BOP跳变

        LocalDate prevYearEnd = bopDate.minusDays(1);
        List<RateCurve> prevYearEndRates = loadRates("locked", prevYearEnd);

        // 只保留从当年1月起的现金流
        LocalDate yearStart = LocalDate.of(bopDate.getYear(), 1, 1);
        List<CashFlow> cfFromYearStart = cf.stream()
                .filter(c -> !c.getDate().isBefore(yearStart))
                .collect(Collectors.toList());

        // 先计算 If_Bop 的 Rep 字段（对齐 pv_calculator_assumption 的 If_Bop_Cca_Rep_Wlk / If_Bop_Cfa_Rep_Wlk）
        // - Cca：当期/过去不计息，未来折现至 valuationDate
        // - Cfa：未来折现至 valuationDate
        List<CashFlow> cfBopCurrent = cfFromYearStart.stream()
                .filter(c -> !c.getDate().isAfter(valuationDate))
                .collect(Collectors.toList());
        List<CashFlow> cfBopFuture = cfFromYearStart.stream()
                .filter(c -> c.getDate().isAfter(valuationDate))
                .collect(Collectors.toList());

        // BOP_Cca_Rep_Wlk
        BigDecimal bopCcaPre = pvCalculatorService.calculatePvCurrentPeriodNoInterest(cfBopCurrent, CashFlow::getPremium, rates, valuationDate, uwDate);
        BigDecimal bopCcaAcq = pvCalculatorService.calculatePvCurrentPeriodNoInterest(cfBopCurrent, CashFlow::getIacf, rates, valuationDate, uwDate);
        BigDecimal bopCcaCla = pvCalculatorService.calculatePvCurrentPeriodNoInterest(cfBopCurrent, CashFlow::getClaims, rates, valuationDate, uwDate);
        BigDecimal bopCcaMtn = pvCalculatorService.calculatePvCurrentPeriodNoInterest(cfBopCurrent, CashFlow::getExpenses, rates, valuationDate, uwDate);
        if (bopCcaCla == null) bopCcaCla = BigDecimal.ZERO;
        if (bopCcaMtn == null) bopCcaMtn = BigDecimal.ZERO;
        BigDecimal bopCcaRad = (bopCcaCla.add(bopCcaMtn)).multiply(assumptions.getRaRatio());

        fields.put("Pvfl_If_Bop_Cca_Rep_Wlk_Pre_Amt", bopCcaPre);
        fields.put("Pvfl_If_Bop_Cca_Rep_Wlk_Acq_Amt", bopCcaAcq);
        fields.put("Pvfl_If_Bop_Cca_Rep_Wlk_Cla_Amt", bopCcaCla);
        fields.put("Pvfl_If_Bop_Cca_Rep_Wlk_Mtn_Amt", bopCcaMtn);
        fields.put("Pvfl_If_Bop_Cca_Rep_Wlk_Rad_Amt", bopCcaRad);

        // BOP_Cfa_Rep_Wlk
        BigDecimal bopCfaPre = pvCalculatorService.calculatePvExact(cfBopFuture, CashFlow::getPremium, rates, valuationDate, uwDate);
        BigDecimal bopCfaAcq = pvCalculatorService.calculatePvExact(cfBopFuture, CashFlow::getIacf, rates, valuationDate, uwDate);
        BigDecimal bopCfaCla = pvCalculatorService.calculatePvExact(cfBopFuture, CashFlow::getClaims, rates, valuationDate, uwDate);
        BigDecimal bopCfaMtn = pvCalculatorService.calculatePvExact(cfBopFuture, CashFlow::getExpenses, rates, valuationDate, uwDate);
        if (bopCfaCla == null) bopCfaCla = BigDecimal.ZERO;
        if (bopCfaMtn == null) bopCfaMtn = BigDecimal.ZERO;
        BigDecimal bopCfaRad = (bopCfaCla.add(bopCfaMtn)).multiply(assumptions.getRaRatio());

        fields.put("Pvfl_If_Bop_Cfa_Rep_Wlk_Pre_Amt", bopCfaPre);
        fields.put("Pvfl_If_Bop_Cfa_Rep_Wlk_Acq_Amt", bopCfaAcq);
        fields.put("Pvfl_If_Bop_Cfa_Rep_Wlk_Cla_Amt", bopCfaCla);
        fields.put("Pvfl_If_Bop_Cfa_Rep_Wlk_Mtn_Amt", bopCfaMtn);
        fields.put("Pvfl_If_Bop_Cfa_Rep_Wlk_Rad_Amt", bopCfaRad);

        // Beg_Lcu（上年末曲线折现到BOP）
        BigDecimal claLcu = pvCalculatorService.calculatePvBegLcu(cfFromYearStart, CashFlow::getClaims, prevYearEndRates, bopDate);
        BigDecimal mtnLcu = pvCalculatorService.calculatePvBegLcu(cfFromYearStart, CashFlow::getExpenses, prevYearEndRates, bopDate);
        if (claLcu == null) claLcu = BigDecimal.ZERO;
        if (mtnLcu == null) mtnLcu = BigDecimal.ZERO;
        BigDecimal radLcu = (claLcu.add(mtnLcu)).multiply(assumptions.getRaRatio());

        fields.put("Pvfl_If_Bop_Cfa_Beg_Lcu_Cla_Amt", claLcu);
        fields.put("Pvfl_If_Bop_Cfa_Beg_Lcu_Mtn_Amt", mtnLcu);
        fields.put("Pvfl_If_Bop_Cfa_Beg_Lcu_Rad_Amt", radLcu);

        // Beg_Wlk（签单日锁定曲线折现到上年末12/31）
        // 注意：这里的 rates 参数（调用方传入）在当前实现中等同“签单月锁定曲线”
        BigDecimal claWlk = pvCalculatorService.calculatePvExact(cfFromYearStart, CashFlow::getClaims, rates, prevYearEnd, uwDate);
        BigDecimal mtnWlk = pvCalculatorService.calculatePvExact(cfFromYearStart, CashFlow::getExpenses, rates, prevYearEnd, uwDate);
        if (claWlk == null) claWlk = BigDecimal.ZERO;
        if (mtnWlk == null) mtnWlk = BigDecimal.ZERO;
        BigDecimal radWlk = (claWlk.add(mtnWlk)).multiply(assumptions.getRaRatio());

        fields.put("Pvfl_If_Bop_Cfa_Beg_Wlk_Cla_Amt", claWlk);
        fields.put("Pvfl_If_Bop_Cfa_Beg_Wlk_Mtn_Amt", mtnWlk);
        fields.put("Pvfl_If_Bop_Cfa_Beg_Wlk_Rad_Amt", radWlk);
    }

    private void calculateEop(
            Map<String, BigDecimal> fields,
            String segment,
            List<CashFlow> cf,
            List<RateCurve> lockedRates,
            List<RateCurve> currentRates,
            LocalDate valuationDate,
            LocalDate uwDate,
            LocalDate policyStartDate,
            Assumptions assumptions
    ) {
        // [Assumption分支逻辑] Nb 的“当期”从保险起期所在月份开始；If 的“当期”从年初开始
        LocalDate yearStart;
        if ("Nb".equals(segment) && policyStartDate != null) {
            // Python 使用月末日期过滤 (Date_Obj=MonthEnd)，等价于这里用“起期所在月的月初”作为起点
            yearStart = policyStartDate.withDayOfMonth(1);
        } else {
            yearStart = LocalDate.of(valuationDate.getYear(), 1, 1);
        }
        
        List<CashFlow> cfCurrent = cf.stream()
            .filter(c -> !c.getDate().isBefore(yearStart) && !c.getDate().isAfter(valuationDate))
            .collect(Collectors.toList());
        
        List<CashFlow> cfFuture = cf.stream()
            .filter(c -> c.getDate().isAfter(valuationDate))
            .collect(Collectors.toList());

        // --- Locked Curve (Wlk) ---
        // Eop_Cca_Rep_Wlk
        calculateAndPut(fields, String.format("Pvfl_%s_Eop_Cca_Rep_Wlk", segment), cfCurrent, lockedRates, valuationDate, uwDate, assumptions, true);
        
        // Eop_Cfa_Rep_Wlk
        calculateAndPut(fields, String.format("Pvfl_%s_Eop_Cfa_Rep_Wlk", segment), cfFuture, lockedRates, valuationDate, uwDate, assumptions, false);

        // --- Current Curve (Cur) ---
        // Eop_Cca_Rep_Cur
        calculateAndPut(fields, String.format("Pvfl_%s_Eop_Cca_Rep_Cur", segment), cfCurrent, currentRates, valuationDate, valuationDate, assumptions, true);
        
        // Eop_Cfa_Rep_Cur
        calculateAndPut(fields, String.format("Pvfl_%s_Eop_Cfa_Rep_Cur", segment), cfFuture, currentRates, valuationDate, valuationDate, assumptions, false);
    }

    private void calculateAndPut(
            Map<String, BigDecimal> fields,
            String prefix,
            List<CashFlow> cf,
            List<RateCurve> rates,
            LocalDate valuationDate,
            LocalDate curveBaseDate,
            Assumptions assumptions,
            boolean isCca
    ) {
        BigDecimal pre, acq, cla, mtn;
        if (isCca) {
            pre = pvCalculatorService.calculatePvCurrentPeriodNoInterest(cf, CashFlow::getPremium, rates, valuationDate, curveBaseDate);
            acq = pvCalculatorService.calculatePvCurrentPeriodNoInterest(cf, CashFlow::getIacf, rates, valuationDate, curveBaseDate);
            cla = pvCalculatorService.calculatePvCurrentPeriodNoInterest(cf, CashFlow::getClaims, rates, valuationDate, curveBaseDate);
            mtn = pvCalculatorService.calculatePvCurrentPeriodNoInterest(cf, CashFlow::getExpenses, rates, valuationDate, curveBaseDate);
        } else {
            pre = pvCalculatorService.calculatePvExact(cf, CashFlow::getPremium, rates, valuationDate, curveBaseDate);
            acq = pvCalculatorService.calculatePvExact(cf, CashFlow::getIacf, rates, valuationDate, curveBaseDate);
            cla = pvCalculatorService.calculatePvExact(cf, CashFlow::getClaims, rates, valuationDate, curveBaseDate);
            mtn = pvCalculatorService.calculatePvExact(cf, CashFlow::getExpenses, rates, valuationDate, curveBaseDate);
        }
        
        if (cla == null) cla = BigDecimal.ZERO;
        if (mtn == null) mtn = BigDecimal.ZERO;

        BigDecimal rad = (cla.add(mtn)).multiply(assumptions.getRaRatio());

        fields.put(prefix + "_Pre_Amt", pre);
        fields.put(prefix + "_Acq_Amt", acq);
        fields.put(prefix + "_Cla_Amt", cla);
        fields.put(prefix + "_Mtn_Amt", mtn);
        fields.put(prefix + "_Rad_Amt", rad);
    }
}