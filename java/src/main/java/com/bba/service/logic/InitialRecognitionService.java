package com.bba.service.logic;

import com.bba.model.Assumptions;
import com.bba.model.CalculationContext;
import com.bba.model.CohortState;
import com.bba.model.pv.PVSourceData;
import com.bba.util.CalculationLogger;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.Map;

@Service
@Slf4j
@RequiredArgsConstructor
public class InitialRecognitionService {

    private final RatesManagerService ratesManagerService;

    public void run(CalculationContext context, CalculationLogger logger, Assumptions assumptions, CohortState cohortState) {
        logger.logSection("Part 1: 初始确认 (Initial Recognition) - New Business [Sec 1-3]");

        if (context.getPvSourceData() == null) {
            throw new IllegalArgumentException("❌ Error: PV Source Data is missing!");
        }

        logger.logItem(
            "PV原材料数据验证",
            "验证PV原材料数据已加载",
            "ensure_pv_source_data()",
            new HashMap<>(),
            "✅ 成功",
            "所有现值计算将严格使用PV原材料数据，确保数据完整性和准确性"
        );

        // Get actual premium
        // In Java, we assume context.policyData is populated or context.actualPremium is set
        if (context.getPolicyData() != null) {
             context.setActualPremium(context.getPolicyData().getSumPremiumNoTax());
        }
        
        // Use assumptions
        // ... (variables are used in logging or calculation if logic was dynamic, but here we read PV)
        
        // Spot Rate
        BigDecimal spotRate = ratesManagerService.calculateSpotRate(context.getRatesDf());
        logger.logItem(
            "即期利率（Spot Rate）",
            "[Sec 2.0] 新单初始确认时使用的即期利率",
            "利率曲线的第一个值",
            new HashMap<>(),
            spotRate,
            "新单初始确认时使用即期利率计算现值，计算完成后权重并入加权锁定利率"
        );

        String uwMonthStr = context.getUnderWriteDate().format(DateTimeFormatter.ofPattern("yyyyMM"));
        PVSourceData pvData = context.getPvSourceData().getData(uwMonthStr);
        if (pvData == null) {
            throw new IllegalArgumentException("❌ Error: PV data not found for month " + uwMonthStr);
        }

        // Reversal policy check
        boolean isReversalPolicy = Boolean.parseBoolean(pvData.getMetadata().getOrDefault("is_reversal_policy", "false").toString());
        // [对齐Python最新口径] 写入上下文：批减单不做“为匹配PV而取反”，仅在LC判定/分摊等处反转符号逻辑
        context.setReversalPolicy(isReversalPolicy);
        // In Java context we might need a flag
        // context.setReversalPolicy(isReversalPolicy); // If we add this field to context

        if (isReversalPolicy) {
            logger.logText("⚠️  **批减单标记**: 检测到批减单（签单保费为负值），计量时已使用取反后的值，输出时将取反所有结果");
        }

        // 1.1 PV Premium
        String pvFieldPrem = "Pvfl_Nb_Ini_Cfa_Rec_Lkd_Pre_Amt";
        BigDecimal pvPremium = pvData.getPvNbIniCfaRecLkdPreAmt() != null ? pvData.getPvNbIniCfaRecLkdPreAmt() : BigDecimal.ZERO;
        logItem(logger, "当年新增合同_初始确认_预期保费现值", "[Sec 2.1] 初始确认时，预期未来收到的保费折现值（从PV原材料数据读取）",
                pvFieldPrem, pvPremium, uwMonthStr);

        // 1.2 PV IACF
        String pvFieldIacf = "Pvfl_Nb_Ini_Cfa_Rec_Lkd_Acq_Amt";
        BigDecimal valIacf = pvData.getPvNbIniCfaRecLkdAcqAmt() != null ? pvData.getPvNbIniCfaRecLkdAcqAmt() : BigDecimal.ZERO;
        logItem(logger, "当年新增合同_初始确认_IACF现值", "[Sec 2.1] 初始确认时，预期支付的获取费用折现值（从PV原材料数据读取）",
                pvFieldIacf, valIacf, uwMonthStr);

        // 1.3 PV Claims
        String pvFieldClaims = "Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt";
        context.setInitFutClaim(pvData.getPvNbIniCfaRecLkdClaAmt() != null ? pvData.getPvNbIniCfaRecLkdClaAmt() : BigDecimal.ZERO);
        logItem(logger, "当年新增合同_初始确认_预期赔付现值", "[Sec 2.2] 初始确认时，预期赔付支出的折现值（从PV原材料数据读取）",
                pvFieldClaims, context.getInitFutClaim(), uwMonthStr);

        // 1.4 PV Maint
        String pvFieldMaint = "Pvfl_Nb_Ini_Cfa_Rec_Lkd_Mtn_Amt";
        context.setInitFutMaint(pvData.getPvNbIniCfaRecLkdMtnAmt() != null ? pvData.getPvNbIniCfaRecLkdMtnAmt() : BigDecimal.ZERO);
        logItem(logger, "当年新增合同_初始确认_预期维费现值", "[Sec 2.3] 初始确认时，预期维持费用的折现值（从PV原材料数据读取）",
                pvFieldMaint, context.getInitFutMaint(), uwMonthStr);

        // 1.5 RA
        String pvFieldRa = "Pvfl_Nb_Ini_Cfa_Rec_Lkd_Rad_Amt";
        context.setInitRa(pvData.getPvNbIniCfaRecLkdRadAmt() != null ? pvData.getPvNbIniCfaRecLkdRadAmt() : BigDecimal.ZERO);
        logItem(logger, "当年新增合同_初始确认_非金融风险调整(RA)", "[Sec 3.2] 初始确认时，对非金融风险的调整额（从PV原材料数据读取）",
                pvFieldRa, context.getInitRa(), uwMonthStr);

        // 1.6 CSM/LC
        BigDecimal pvInflow = pvPremium;
        BigDecimal pvOutflow = valIacf.add(context.getInitFutClaim()).add(context.getInitFutMaint());
        BigDecimal netInflow = pvInflow.subtract(pvOutflow);
        BigDecimal margin = netInflow.subtract(context.getInitRa());

        context.setNbInitialCsm(BigDecimal.ZERO);
        context.setNbInitialLc(BigDecimal.ZERO);

        // [对齐Python最新口径]
        // 正常保单：margin >= 0 为CSM，<0 为LC
        // 批减单：符号逻辑相反（margin <= 0 为CSM，>0 为LC），且取值保持原符号（CSM为负，LC为正）
        String csmStatus;
        boolean isReversal = context.isReversalPolicy();
        boolean isCsm = (!isReversal && margin.compareTo(BigDecimal.ZERO) >= 0)
                || (isReversal && margin.compareTo(BigDecimal.ZERO) <= 0);
        if (isCsm) {
            context.setNbInitialCsm(margin);
            context.setNbInitialLc(BigDecimal.ZERO);
            csmStatus = "Profitable (CSM)";
        } else {
            context.setNbInitialCsm(BigDecimal.ZERO);
            context.setNbInitialLc(margin);
            csmStatus = "Onerous (Loss Component) - 立即确认亏损";
        }

        Map<String, Object> vars = new HashMap<>();
        vars.put("PV_Prem", pvInflow);
        vars.put("PV_IACF", valIacf);
        vars.put("PV_Claims", context.getInitFutClaim());
        vars.put("PV_Maint", context.getInitFutMaint());
        vars.put("Net_Inflow", netInflow);
        vars.put("RA", context.getInitRa());
        vars.put("Margin", margin);

        logger.logItem(
            "当年新增合同_初始确认_CSM/LC",
            "[Sec 3.3] 初始确认时的合同服务边际或亏损（逐单判定）",
            "Net_Inflow = PV_Prem - (PV_Claims + PV_Maint + PV_IACF); Margin = Net_Inflow - RA",
            vars,
            margin,
            String.format("判定结果: %s. Initial CSM = %,.2f, Initial LC = %,.2f", csmStatus, context.getNbInitialCsm(), context.getNbInitialLc())
        );

        // Update weighted locked rate
        if (cohortState != null) {
            ratesManagerService.updateWeightedLockedRate(
                cohortState,
                spotRate,
                context.getActualPremium(),
                logger
            );
        }
    }

    private void logItem(CalculationLogger logger, String title, String desc, String pvField, BigDecimal value, String month) {
        Map<String, Object> vars = new HashMap<>();
        vars.put("PV字段", pvField);
        vars.put(pvField, value);
        vars.put("评估月", month);
        vars.put("数据来源", "PV原材料数据");
        
        logger.logItem(
            title,
            desc,
            pvField,
            vars,
            value,
            "从PV原材料数据读取：" + pvField
        );
    }
}
