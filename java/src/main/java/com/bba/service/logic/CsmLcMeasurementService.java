package com.bba.service.logic;

import com.bba.entity.RateCurve;
import com.bba.model.CalculationContext;
import com.bba.model.CohortState;
import com.bba.model.PolicyState;
import com.bba.model.pv.PVSourceData;
import com.bba.util.CalculationLogger;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class CsmLcMeasurementService {

    private final RatesManagerService ratesManagerService;
    private final CoverageUnitsService coverageUnitsService;

    private static final DateTimeFormatter YYYYMM = DateTimeFormatter.ofPattern("yyyyMM");

    public void run(
            CalculationContext context,
            CalculationLogger logger,
            CohortState cohortState,
            PolicyState policyState,
            List<PolicyState> policies
    ) {
        logger.logSection("Part 3-8.5.5: CSM/LC计量 (CSM/LC Measurement)");

        // 步骤1：CSM计息
        calculateCsmInterest(context, logger, cohortState, policyState);

        // 步骤2：LC分摊IFIE
        calculateLcIfieAllocation(context, logger, cohortState);

        // 步骤3：合同组状态判定
        determineCohortStatus(cohortState, context, logger, policies);

        // 步骤4：LC计量（先于CSM计量，因为CSM计量需要LC的结果）
        calculateLcMeasurement(context, logger);

        // 步骤5：CSM计量
        calculateCsmMeasurement(context, logger);
    }

    // --- Part 3: CSM Interest Accretion ---

    private void calculateCsmInterest(
            CalculationContext context,
            CalculationLogger logger,
            CohortState cohortState,
            PolicyState policyState
    ) {
        logger.logSection("Part 3: CSM计息 (Interest Accretion) [Sec 6]");

        if (context.getPvSourceData() == null) {
            throw new IllegalArgumentException("❌ 错误: PV原材料数据不可用！");
        }

        if (context.getEopDate() == null) {
            context.setEopDate(LocalDate.of(context.getYear(), 12, 31));
        }

        LocalDate uwDate = context.getUnderWriteDate();
        if (uwDate == null) {
            throw new IllegalArgumentException("❌ 错误: context.underWriteDate 未设置");
        }
        String uwMonthStr = uwDate.format(YYYYMM);

        String valMonthStr = context.getValMonthStr();
        if (valMonthStr == null) {
            valMonthStr = context.getEopDate().format(YYYYMM);
        }

        // Get Wlk Curve from PV Data
        List<RateCurve> wlkCurve = getWlkCurveFromPvData(context, uwMonthStr);
        if (wlkCurve == null || wlkCurve.isEmpty()) {
            logger.logItem(
                    "锁定利率曲线缺失",
                    "[Sec 6.1] 无法从PV原材料数据获取签单年月的Wlk利率曲线",
                    "UW Month: " + uwMonthStr,
                    null,
                    BigDecimal.ZERO,
                    "请确保PV原材料数据包含签单月份的利率曲线信息"
            );
            return;
        }

        LocalDate stopDate = null;
        if (policyState != null && policyState.getEndDate() != null) {
            stopDate = policyState.getEndDate();
        } else if (context.getEndDate() != null) {
            stopDate = context.getEndDate();
        }

        BigDecimal bopCsmLc = getBopCsmLc(context, cohortState);

        BigDecimal nbInitialCsm = context.getNbInitialCsm() != null ? context.getNbInitialCsm() : BigDecimal.ZERO;

        // Separate CSM and LC
        BigDecimal bopCsm = bopCsmLc.compareTo(BigDecimal.ZERO) >= 0 ? bopCsmLc : BigDecimal.ZERO;

        String bopMonthStr = LocalDate.of(context.getYear(), 1, 1).format(YYYYMM);

        // IF CSM Interest
        InterestResult ifResult = calculateIfCsmInterest(bopCsm, wlkCurve, uwDate, bopMonthStr, valMonthStr, stopDate);
        BigDecimal ifInterestCsm = ifResult.interest;

        // NB CSM Interest
        InterestResult nbResult = calculateNbCsmInterest(nbInitialCsm, wlkCurve, uwDate, valMonthStr, stopDate);
        BigDecimal nbInterestCsm = nbResult.interest;

        context.setIfInterestCsm(ifInterestCsm);
        context.setNbInterestCsm(nbInterestCsm);

        BigDecimal ifCsmPostInterest = bopCsm.add(ifInterestCsm);
        BigDecimal nbCsmPostInterest = nbInitialCsm.add(nbInterestCsm);

        if (cohortState != null) {
            cohortState.setCsmInterest(ifInterestCsm.add(nbInterestCsm));
        }

        Map<String, Object> meta = new HashMap<>();
        meta.put("IF_年初CSM余额", bopCsm);
        meta.put("当年新增合同CSM", nbInitialCsm);
        meta.put("期初有效合同CSM计息", ifInterestCsm);
        meta.put("新增合同CSM计息", nbInterestCsm);
        meta.put("IF_计息后CSM", ifCsmPostInterest);
        meta.put("NB_计息后CSM", nbCsmPostInterest);

        logger.logItem(
                "CSM计息明细",
                "[Sec 6] CSM计息明细（文档对照）",
                "IF_计息后CSM = IF_年初CSM余额 + IF_CSM计息\nNB_计息后CSM = NB_新增CSM + NB_CSM计息",
                meta,
                ifInterestCsm.add(nbInterestCsm),
                "CSM计息结果，用于后续净余额试算"
        );
    }

    // --- Part 7: LC IFIE Allocation ---

    private void calculateLcIfieAllocation(CalculationContext context, CalculationLogger logger, CohortState cohortState) {
        logger.logSection("Part 7: LC分摊IFIE (LC IFIE Allocation) [Sec 7]");

        String eopMonthStr = context.getValMonthStr();
        PVSourceData pvData = context.getPvSourceData().getData(eopMonthStr);
        if (pvData == null) {
            throw new IllegalArgumentException("❌ 错误: 找不到评估月 " + eopMonthStr + " 的PV原材料数据！");
        }

        boolean isReversal = context.isReversalPolicy();
        BigDecimal bopCsmLc = getBopCsmLc(context, cohortState);

        BigDecimal nbInitialCsmLc = context.getNbInitialCsm() != null ? context.getNbInitialCsm() : BigDecimal.ZERO;
        if (nbInitialCsmLc.compareTo(BigDecimal.ZERO) == 0 && context.getNbInitialLc() != null) {
            BigDecimal nbLcVal = context.getNbInitialLc();
            boolean isNbLc = (!isReversal && nbLcVal.compareTo(BigDecimal.ZERO) < 0)
                    || (isReversal && nbLcVal.compareTo(BigDecimal.ZERO) > 0);
            if (isNbLc) nbInitialCsmLc = nbLcVal;
        }

        // IF LC Allocation
        // 正常保单：LC < 0；批减单：LC > 0（符号逻辑相反）
        boolean isIfLc = (!isReversal && bopCsmLc.compareTo(BigDecimal.ZERO) < 0)
                || (isReversal && bopCsmLc.compareTo(BigDecimal.ZERO) > 0);
        BigDecimal ifBopLc = isIfLc ? bopCsmLc : BigDecimal.ZERO;

        logger.logItem("IF_年初LC", "[LC IFIE分摊] 期初有效合同年初LC（直接取数）", "IF_年初LC = IF_年初CSM/LC（如果<0，则为LC）",
                mapOf("IF_年初CSM/LC", bopCsmLc, "IF_年初LC", ifBopLc), ifBopLc, "使用统一字段逻辑");

        BigDecimal ifLcIfieRatio = context.getIfLcIfieRatio() != null ? context.getIfLcIfieRatio() : BigDecimal.ZERO;
        BigDecimal pvIfInitClaims = BigDecimal.ZERO;
        BigDecimal pvIfInitMaint = BigDecimal.ZERO;
        BigDecimal pvIfInitRa = BigDecimal.ZERO;
        BigDecimal denomIf = BigDecimal.ZERO;

        if (isIfLc) {
            pvIfInitClaims = getPvAmount(pvData.getPvIfBopCfaBegLcuClaAmt());
            pvIfInitMaint = getPvAmount(pvData.getPvIfBopCfaBegLcuMtnAmt());
            pvIfInitRa = getPvAmount(pvData.getPvIfBopCfaBegLcuRadAmt());
            denomIf = pvIfInitClaims.add(pvIfInitMaint).add(pvIfInitRa);

            BigDecimal denomIfAbs = denomIf.abs();
            if (ifLcIfieRatio.compareTo(BigDecimal.ZERO) == 0 && denomIfAbs.compareTo(BigDecimal.ZERO) > 0) {
                ifLcIfieRatio = ifBopLc.abs().divide(denomIfAbs, 16, RoundingMode.HALF_UP);
                context.setIfLcIfieRatio(ifLcIfieRatio);
            }
        }

        logger.logItem("IF_LC IFIE分摊比例", "[LC IFIE分摊] 期初有效合同LC IFIE分摊比例",
                "IF_LC IFIE分摊比例 = IF_年初LC / (IF_预期赔付现金流_年初现值 + IF_预期维持费用现金流_年初现值 + IF_预期非金融风险调整_年初现值)",
                mapOf("IF_年初LC", ifBopLc, "分母合计", denomIf, "IF_LC IFIE分摊比例", ifLcIfieRatio), ifLcIfieRatio, null);

        // IF Accretion
        BigDecimal pvIfBopCfaRepWlkClaims = getPvAmount(pvData.getPvIfBopCfaRepWlkClaAmt());
        BigDecimal pvIfBopCfaRepWlkMaint = getPvAmount(pvData.getPvIfBopCfaRepWlkMtnAmt());
        BigDecimal pvIfBopCcaRepWlkClaims = getPvAmount(pvData.getPvIfBopCcaRepWlkClaAmt());
        BigDecimal pvIfBopCcaRepWlkMaint = getPvAmount(pvData.getPvIfBopCcaRepWlkMtnAmt());
        BigDecimal pvIfBopCfaBegWlkClaims = getPvAmount(pvData.getPvIfBopCfaBegWlkClaAmt());
        BigDecimal pvIfBopCfaBegWlkMaint = getPvAmount(pvData.getPvIfBopCfaBegWlkMtnAmt());

        BigDecimal ifIfieAccretionClaims = pvIfBopCfaRepWlkClaims.add(pvIfBopCfaRepWlkMaint)
                .add(pvIfBopCcaRepWlkClaims).add(pvIfBopCcaRepWlkMaint)
                .subtract(pvIfBopCfaBegWlkClaims).subtract(pvIfBopCfaBegWlkMaint);

        logger.logItem("IF_待分摊IFIE_计息_赔付与费用", "[LC IFIE分摊] IF_待分摊IFIE_计息_赔付与费用", "公式：[Bop_Cfa_Rep_Wlk] + [Bop_Cca_Rep_Wlk] - [Bop_Cfa_Beg_Wlk]",
                null, ifIfieAccretionClaims, null);

        BigDecimal pvIfBopCfaRepWlkRa = getPvAmount(pvData.getPvIfBopCfaRepWlkRadAmt());
        BigDecimal pvIfBopCfaBegWlkRa = getPvAmount(pvData.getPvIfBopCfaBegWlkRadAmt());
        BigDecimal pvIfBopCcaRepWlkRa = getPvAmount(pvData.getPvIfBopCcaRepWlkRadAmt());

        BigDecimal ifIfieAccretionRa = pvIfBopCfaRepWlkRa.subtract(pvIfBopCfaBegWlkRa).add(pvIfBopCcaRepWlkRa);
        logger.logItem("IF_待分摊IFIE_计息_非金融风险调整", "[LC IFIE分摊] IF_待分摊IFIE_计息_非金融风险调整", "公式：[Bop_Cfa_Rep_Wlk] - [Bop_Cfa_Beg_Wlk] + [Bop_Cca_Rep_Wlk]",
                null, ifIfieAccretionRa, null);

        // IF Rate Change
        BigDecimal pvIfEopCfaRepCurClaims = getPvAmount(pvData.getPvIfEopCfaRepCurClaAmt());
        BigDecimal pvIfEopCfaRepWlkClaims = getPvAmount(pvData.getPvIfEopCfaRepWlkClaAmt());
        BigDecimal pvIfEopCfaRepCurMaint = getPvAmount(pvData.getPvIfEopCfaRepCurMtnAmt());
        BigDecimal pvIfEopCfaRepWlkMaint = getPvAmount(pvData.getPvIfEopCfaRepWlkMtnAmt());
        BigDecimal pvIfBopCfaBegLcuClaims = getPvAmount(pvData.getPvIfBopCfaBegLcuClaAmt());
        // pvIfBopCfaBegWlkClaims already defined
        BigDecimal pvIfBopCfaBegLcuMaint = getPvAmount(pvData.getPvIfBopCfaBegLcuMtnAmt());
        // pvIfBopCfaBegWlkMaint already defined

        BigDecimal termEndDiff = pvIfEopCfaRepCurClaims.subtract(pvIfEopCfaRepWlkClaims)
                .add(pvIfEopCfaRepCurMaint).subtract(pvIfEopCfaRepWlkMaint);
        BigDecimal termBegDiff = pvIfBopCfaBegLcuClaims.subtract(pvIfBopCfaBegWlkClaims)
                .add(pvIfBopCfaBegLcuMaint).subtract(pvIfBopCfaBegWlkMaint);

        BigDecimal ifIfieRateChangeClaims = termEndDiff.subtract(termBegDiff);
        logger.logItem("IF_待分摊IFIE_利率变化的影响_赔付与费用", "[LC IFIE分摊] IF_待分摊IFIE_利率变化的影响_赔付与费用", "公式：([Eop_Cfa_Rep_Cur] - [Eop_Cfa_Rep_Wlk]) - ([Bop_Cfa_Beg_Lcu] - [Bop_Cfa_Beg_Wlk])",
                null, ifIfieRateChangeClaims, null);

        BigDecimal pvIfEopCfaRepCurRa = getPvAmount(pvData.getPvIfEopCfaRepCurRadAmt());
        BigDecimal pvIfEopCfaRepWlkRa = getPvAmount(pvData.getPvIfEopCfaRepWlkRadAmt());
        BigDecimal pvIfBopCfaBegLcuRa = getPvAmount(pvData.getPvIfBopCfaBegLcuRadAmt());
        // pvIfBopCfaBegWlkRa already defined

        BigDecimal termEndDiffRa = pvIfEopCfaRepCurRa.subtract(pvIfEopCfaRepWlkRa);
        BigDecimal termBegDiffRa = pvIfBopCfaBegLcuRa.subtract(pvIfBopCfaBegWlkRa);

        BigDecimal ifIfieRateChangeRa = termEndDiffRa.subtract(termBegDiffRa);
        logger.logItem("IF_待分摊IFIE_利率变化的影响_非金融风险调整", "[LC IFIE分摊] IF_待分摊IFIE_利率变化的影响_非金融风险调整", "公式：([Eop_Cfa_Rep_Cur] - [Eop_Cfa_Rep_Wlk]) - ([Bop_Cfa_Beg_Lcu] - [Bop_Cfa_Beg_Wlk])",
                null, ifIfieRateChangeRa, null);

        // IF Results
        BigDecimal ifLcIfieClaimsBeforeSign = ifIfieAccretionClaims.add(ifIfieRateChangeClaims).multiply(ifLcIfieRatio);
        BigDecimal ifLcIfieRaBeforeSign = ifIfieAccretionRa.add(ifIfieRateChangeRa).multiply(ifLcIfieRatio);
        BigDecimal ifLcIfieTotalBeforeSign = ifLcIfieClaimsBeforeSign.add(ifLcIfieRaBeforeSign);

        BigDecimal ifLcIfieClaims, ifLcIfieRa, ifLcIfieTotal;
        // LC IFIE分摊应与LC本金同方向（正常保单为负，批减单为正）
        if (isIfLc) {
            BigDecimal lcSign = ifBopLc.compareTo(BigDecimal.ZERO) < 0 ? BigDecimal.ONE.negate() : BigDecimal.ONE;
            ifLcIfieClaims = ifLcIfieClaimsBeforeSign.abs().multiply(lcSign);
            ifLcIfieRa = ifLcIfieRaBeforeSign.abs().multiply(lcSign);
            ifLcIfieTotal = ifLcIfieTotalBeforeSign.abs().multiply(lcSign);
        } else {
            ifLcIfieClaims = ifLcIfieClaimsBeforeSign;
            ifLcIfieRa = ifLcIfieRaBeforeSign;
            ifLcIfieTotal = ifLcIfieTotalBeforeSign;
        }

        BigDecimal ifLcAfterIfie = ifBopLc.add(ifLcIfieTotal);

        context.setIfLcAfterIfie(ifLcAfterIfie);
        context.setIfLcIfieTotal(ifLcIfieTotal);
        context.setIfLcIfieCf(ifLcIfieClaims);
        context.setIfLcIfieRa(ifLcIfieRa);

        // NB LC Allocation
        boolean isNbLc = (!isReversal && nbInitialCsmLc.compareTo(BigDecimal.ZERO) < 0)
                || (isReversal && nbInitialCsmLc.compareTo(BigDecimal.ZERO) > 0);
        BigDecimal nbInitialLc = isNbLc ? nbInitialCsmLc : BigDecimal.ZERO;

        BigDecimal nbLcIfieRatio = context.getNbLcRatio() != null ? context.getNbLcRatio() : BigDecimal.ZERO;
        BigDecimal initFutClaim = context.getInitFutClaim() != null ? context.getInitFutClaim() : BigDecimal.ZERO;
        BigDecimal initFutMaint = context.getInitFutMaint() != null ? context.getInitFutMaint() : BigDecimal.ZERO;
        BigDecimal initRa = context.getInitRa() != null ? context.getInitRa() : BigDecimal.ZERO;
        BigDecimal denomNb = initFutClaim.add(initFutMaint).add(initRa);

        BigDecimal denomNbAbs = denomNb.abs();
        if (isNbLc && nbLcIfieRatio.compareTo(BigDecimal.ZERO) == 0 && denomNbAbs.compareTo(BigDecimal.ZERO) > 0) {
            nbLcIfieRatio = nbInitialLc.abs().divide(denomNbAbs, 16, RoundingMode.HALF_UP);
            context.setNbLcRatio(nbLcIfieRatio);
        }

        logger.logItem("NB_LC IFIE分摊比例", "[LC IFIE分摊] 新增合同LC IFIE分摊比例", "NB_LC IFIE分摊比例 = |NB_年初LC| / (汇总当年各新增年月_预期赔付+维费+RA_初始确认现值)",
                mapOf("NB_年初LC", nbInitialLc, "分母合计", denomNb, "NB_LC IFIE分摊比例", nbLcIfieRatio), nbLcIfieRatio, null);

        // NB Accretion
        BigDecimal pvNbEopFutClaimsWlk = getPvAmount(pvData.getPvNbEopCfaRepWlkClaAmt());
        BigDecimal pvNbEopFutMaintWlk = getPvAmount(pvData.getPvNbEopCfaRepWlkMtnAmt());
        BigDecimal pvNbEopCurClaimsWlk = getPvAmount(pvData.getPvNbEopCcaRepWlkClaAmt());
        BigDecimal pvNbEopCurMaintWlk = getPvAmount(pvData.getPvNbEopCcaRepWlkMtnAmt());
        BigDecimal pvNbIniFutClaimsLkd = getPvAmount(pvData.getPvNbIniCfaRecLkdClaAmt());
        BigDecimal pvNbIniFutMaintLkd = getPvAmount(pvData.getPvNbIniCfaRecLkdMtnAmt());

        BigDecimal nbIfieAccretionClaims = pvNbEopFutClaimsWlk.add(pvNbEopFutMaintWlk)
                .add(pvNbEopCurClaimsWlk).add(pvNbEopCurMaintWlk)
                .subtract(pvNbIniFutClaimsLkd).subtract(pvNbIniFutMaintLkd);
        logger.logItem("NB_待分摊IFIE_计息_赔付与费用", "[LC IFIE分摊] NB_待分摊IFIE_计息_赔付与费用", "公式：[Eop_Cfa_Rep_Wlk] - [Ini_Cfa_Rec_Lkd] + [Eop_Cca_Rep_Wlk]",
                null, nbIfieAccretionClaims, null);

        BigDecimal pvNbEopFutRaWlk = getPvAmount(pvData.getPvNbEopCfaRepWlkRadAmt());
        BigDecimal pvNbEopCurRaWlk = getPvAmount(pvData.getPvNbEopCcaRepWlkRadAmt());
        BigDecimal pvNbIniFutRaLkd = getPvAmount(pvData.getPvNbIniCfaRecLkdRadAmt());

        BigDecimal nbIfieAccretionRa = pvNbEopFutRaWlk.subtract(pvNbIniFutRaLkd).add(pvNbEopCurRaWlk);
        logger.logItem("NB_待分摊IFIE_计息_非金融风险调整", "[LC IFIE分摊] NB_待分摊IFIE_计息_非金融风险调整", "公式：[Eop_Cfa_Rep_Wlk] - [Ini_Cfa_Rec_Lkd] + [Eop_Cca_Rep_Wlk]",
                null, nbIfieAccretionRa, null);

        // NB Rate Change
        BigDecimal pvNbEopCfaRepCurClaims = getPvAmount(pvData.getPvNbEopCfaRepCurClaAmt());
        BigDecimal pvNbEopCfaRepWlkClaims = getPvAmount(pvData.getPvNbEopCfaRepWlkClaAmt());
        BigDecimal pvNbEopCfaRepCurMaint = getPvAmount(pvData.getPvNbEopCfaRepCurMtnAmt());
        BigDecimal pvNbEopCfaRepWlkMaint = getPvAmount(pvData.getPvNbEopCfaRepWlkMtnAmt());

        BigDecimal nbIfieRateChangeClaims = pvNbEopCfaRepCurClaims.subtract(pvNbEopCfaRepWlkClaims)
                .add(pvNbEopCfaRepCurMaint).subtract(pvNbEopCfaRepWlkMaint);
        logger.logItem("NB_待分摊IFIE_利率变化的影响_赔付与费用", "[LC IFIE分摊] NB_待分摊IFIE_利率变化的影响_赔付与费用", "公式：[Eop_Cfa_Rep_Cur] - [Eop_Cfa_Rep_Wlk]",
                null, nbIfieRateChangeClaims, null);

        BigDecimal pvNbEopCfaRepCurRa = getPvAmount(pvData.getPvNbEopCfaRepCurRadAmt());
        BigDecimal pvNbEopCfaRepWlkRa = getPvAmount(pvData.getPvNbEopCfaRepWlkRadAmt());

        BigDecimal nbIfieRateChangeRa = pvNbEopCfaRepCurRa.subtract(pvNbEopCfaRepWlkRa);
        logger.logItem("NB_待分摊IFIE_利率变化的影响_非金融风险调整", "[LC IFIE分摊] NB_待分摊IFIE_利率变化的影响_非金融风险调整", "公式：[Eop_Cfa_Rep_Cur] - [Eop_Cfa_Rep_Wlk]",
                null, nbIfieRateChangeRa, null);

        // NB Results
        BigDecimal nbLcIfieClaimsBeforeSign = nbIfieAccretionClaims.add(nbIfieRateChangeClaims).multiply(nbLcIfieRatio);
        BigDecimal nbLcIfieRaBeforeSign = nbIfieAccretionRa.add(nbIfieRateChangeRa).multiply(nbLcIfieRatio);
        BigDecimal nbLcIfieTotalBeforeSign = nbLcIfieClaimsBeforeSign.add(nbLcIfieRaBeforeSign);

        BigDecimal nbLcIfieClaims, nbLcIfieRa, nbLcIfieTotal;
        if (isNbLc) {
            BigDecimal lcSign = nbInitialLc.compareTo(BigDecimal.ZERO) < 0 ? BigDecimal.ONE.negate() : BigDecimal.ONE;
            nbLcIfieClaims = nbLcIfieClaimsBeforeSign.abs().multiply(lcSign);
            nbLcIfieRa = nbLcIfieRaBeforeSign.abs().multiply(lcSign);
            nbLcIfieTotal = nbLcIfieTotalBeforeSign.abs().multiply(lcSign);
        } else {
            nbLcIfieClaims = nbLcIfieClaimsBeforeSign;
            nbLcIfieRa = nbLcIfieRaBeforeSign;
            nbLcIfieTotal = nbLcIfieTotalBeforeSign;
        }

        BigDecimal nbLcAfterIfie = nbInitialLc.add(nbLcIfieTotal);

        context.setNbLcAfterIfie(nbLcAfterIfie);
        context.setNbLcIfieTotal(nbLcIfieTotal);
        context.setNbLcIfieCf(nbLcIfieClaims);
        context.setNbLcIfieRa(nbLcIfieRa);

        // Store accretion/rate change for later use
        context.setIfIfieAccretionClaims(ifIfieAccretionClaims);
        context.setIfIfieAccretionRa(ifIfieAccretionRa);
        context.setIfIfieRateChangeClaims(ifIfieRateChangeClaims);
        context.setIfIfieRateChangeRa(ifIfieRateChangeRa);
        context.setNbIfieAccretionClaims(nbIfieAccretionClaims);
        context.setNbIfieAccretionRa(nbIfieAccretionRa);
        context.setNbIfieRateChangeClaims(nbIfieRateChangeClaims);
        context.setNbIfieRateChangeRa(nbIfieRateChangeRa);

        logger.logItem("LC分摊IFIE明细", "[Sec 7] LC分摊IFIE明细", "LC分摊IFIE = IF_LC分摊IFIE + NB_LC分摊IFIE",
                mapOf("IF_LC分摊IFIE", ifLcIfieTotal, "NB_LC分摊IFIE", nbLcIfieTotal), ifLcIfieTotal.add(nbLcIfieTotal), null);
    }

    // --- Part 8.5.5: Cohort Status Determination ---

    private void determineCohortStatus(
            CohortState cohortState,
            CalculationContext context,
            CalculationLogger logger,
            List<PolicyState> policies
    ) {
        logger.logSection("Part 8.5.5: 合同组状态判定 (Cohort Status Determination) [Sec 8.5.5]");

        boolean isReversal = context.isReversalPolicy();
        BigDecimal bopCsmLc = getBopCsmLc(context, cohortState);
        // 正常保单：CSM>=0，LC<0；批减单：符号逻辑相反（CSM<=0，LC>0）
        BigDecimal ifBopCsm = ((!isReversal && bopCsmLc.compareTo(BigDecimal.ZERO) >= 0)
                || (isReversal && bopCsmLc.compareTo(BigDecimal.ZERO) <= 0)) ? bopCsmLc : BigDecimal.ZERO;
        BigDecimal ifBopLc = ((!isReversal && bopCsmLc.compareTo(BigDecimal.ZERO) < 0)
                || (isReversal && bopCsmLc.compareTo(BigDecimal.ZERO) > 0)) ? bopCsmLc : BigDecimal.ZERO;

        // [修复] IF_计息后CSM只使用IF部分计息（context.ifInterestCsm），不能用 cohortState.csmInterest(IF+NB合计)
        BigDecimal ifInterestCsm = context.getIfInterestCsm() != null ? context.getIfInterestCsm() : BigDecimal.ZERO;
        BigDecimal ifCsmPost = ifBopCsm.add(ifInterestCsm);

        BigDecimal nbInitialCsm = context.getNbInitialCsm() != null ? context.getNbInitialCsm() : BigDecimal.ZERO;
        BigDecimal nbInitialLc = context.getNbInitialLc() != null ? context.getNbInitialLc() : BigDecimal.ZERO;

        BigDecimal nbCsmPost = nbInitialCsm.add(context.getNbInterestCsm() != null ? context.getNbInterestCsm() : BigDecimal.ZERO);
        BigDecimal nbLcBase = nbInitialLc;

        BigDecimal ifLcIfieTotal = context.getIfLcIfieTotal() != null ? context.getIfLcIfieTotal() : BigDecimal.ZERO;
        BigDecimal nbLcIfieTotal = context.getNbLcIfieTotal() != null ? context.getNbLcIfieTotal() : BigDecimal.ZERO;

        BigDecimal ifLcPost = ifBopLc.add(ifLcIfieTotal);
        BigDecimal nbLcPost = nbLcBase.add(nbLcIfieTotal);

        BigDecimal netTrial = ifCsmPost.add(nbCsmPost).add(ifLcPost).add(nbLcPost);

        logger.logItem("合同组净余额试算值", "[Sec 8.5.5] 步骤1：计算合同组净余额试算值", "Net_trial = IF_计息后CSM + NB_计息后CSM + IF_分摊后IFIE后LC + NB_分摊后IFIE后LC",
                mapOf("IF_计息后CSM", ifCsmPost, "NB_计息后CSM", nbCsmPost, "IF_分摊后IFIE后LC", ifLcPost, "NB_分摊后IFIE后LC", nbLcPost, "Net_trial", netTrial),
                netTrial, "不包含当期履约现金流变化");

        BigDecimal cohortCsm, cohortLc;
        String status;
        boolean isProfitable;

        // 正常保单：net_trial >= 0 为CSM，<0 为LC
        // 批减单：符号逻辑相反（net_trial <= 0 为CSM，>0 为LC），且取值保持原符号（CSM为负，LC为正）
        boolean isCsm = (!isReversal && netTrial.compareTo(BigDecimal.ZERO) >= 0)
                || (isReversal && netTrial.compareTo(BigDecimal.ZERO) <= 0);
        if (isCsm) {
            cohortCsm = netTrial;
            cohortLc = BigDecimal.ZERO;
            isProfitable = true;
            status = "盈利 (Profitable)";
        } else {
            cohortCsm = BigDecimal.ZERO;
            cohortLc = netTrial;
            isProfitable = false;
            status = "亏损 (Onerous)";
        }

        if (cohortState != null) {
            cohortState.setProfitable(isProfitable);
            cohortState.setNetTrial(netTrial);
        }

        logger.logItem("合同组最终状态", "[Sec 8.5.5] 步骤2：确定合同组最终状态", "IF(Net_trial >= 0, 盈利, 亏损)",
                mapOf("Net_trial", netTrial, "合同组 CSM", cohortCsm, "合同组 LC", cohortLc), netTrial, "判定结果: " + status);

        if (policies != null && cohortState != null) {
            for (PolicyState policy : policies) {
                if (isProfitable) {
                    policy.setInitialLc(BigDecimal.ZERO);
                } else {
                    policy.setInitialCsm(BigDecimal.ZERO);
                }
            }
        }

        BigDecimal cohortCsmLc = cohortCsm.add(cohortLc);
        // 正常保单：>=0 视为CSM；批减单：<=0 视为CSM
        boolean isCsmBucket = (!isReversal && cohortCsmLc.compareTo(BigDecimal.ZERO) >= 0)
                || (isReversal && cohortCsmLc.compareTo(BigDecimal.ZERO) <= 0);
        if (isCsmBucket) {
            context.setEndCsmBeforeAmort(cohortCsmLc);
            context.setEndLcBeforeAmort(BigDecimal.ZERO);
        } else {
            context.setEndCsmBeforeAmort(BigDecimal.ZERO);
            context.setEndLcBeforeAmort(cohortCsmLc);
        }
    }

    // --- Part LC: LC Measurement ---

    private void calculateLcMeasurement(CalculationContext context, CalculationLogger logger) {
        logger.logSection("Part LC: LC计量 (LC Measurement)");

        boolean isReversal = context.isReversalPolicy();
        String eopMonthStr = context.getValMonthStr();
        PVSourceData pvData = context.getPvSourceData().getData(eopMonthStr);
        if (pvData == null) {
            throw new IllegalArgumentException("❌ 错误: 找不到评估月 " + eopMonthStr + " 的PV原材料数据！");
        }

        // Calculate CSM Amort Ratio or use default/IACF ratio
        BigDecimal csmAmortRatio = context.getCsmAmortRatio();
        if (csmAmortRatio == null) {
            BigDecimal csmAmortAmount = context.getCsmAmortAmount();
            BigDecimal endCsmBeforeAmort = context.getEndCsmBeforeAmort();
            if (csmAmortAmount != null && endCsmBeforeAmort != null && endCsmBeforeAmort.compareTo(BigDecimal.ZERO) != 0) {
                // 分子取绝对值，分母保留符号（对齐Python）
                csmAmortRatio = csmAmortAmount.abs().divide(endCsmBeforeAmort, 16, RoundingMode.HALF_UP);
            } else {
                csmAmortRatio = context.getIacfAmortRatio() != null ? context.getIacfAmortRatio() : BigDecimal.ZERO;
            }
        }

        BigDecimal bopLc = context.getBopLc() != null ? context.getBopLc() : BigDecimal.ZERO;
        BigDecimal nbInitialLcTotal = context.getNbInitialLc() != null ? context.getNbInitialLc() : BigDecimal.ZERO;
        BigDecimal ifLcIfieTotal = context.getIfLcIfieTotal() != null ? context.getIfLcIfieTotal() : BigDecimal.ZERO;
        BigDecimal nbLcIfieTotal = context.getNbLcIfieTotal() != null ? context.getNbLcIfieTotal() : BigDecimal.ZERO;

        BigDecimal deltaCsmLc = context.getExpAdjCsmImpact() != null ? context.getExpAdjCsmImpact() : BigDecimal.ZERO;
        BigDecimal deltaCfTotal = context.getDeltaCfTotal() != null ? context.getDeltaCfTotal() : BigDecimal.ZERO;

        // --- Total Portion ---
        logger.logSection("LC计量_合计部分（先计算）");

        BigDecimal bopLcTotal = bopLc;
        BigDecimal lcIfieTotal = ifLcIfieTotal.add(nbLcIfieTotal);

        BigDecimal cohortLcForRatio = context.getEndLcBeforeAmort() != null ? context.getEndLcBeforeAmort() : BigDecimal.ZERO;
        BigDecimal lcAllocationRatioTotal = BigDecimal.ZERO;

        BigDecimal pvIfBegClaims = getPvAmount(pvData.getPvIfBopCfaBegLcuClaAmt());
        BigDecimal pvIfBegMaint = getPvAmount(pvData.getPvIfBopCfaBegLcuMtnAmt());
        BigDecimal pvIfBegRa = getPvAmount(pvData.getPvIfBopCfaBegLcuRadAmt());

        BigDecimal pvNbInitClaims = getPvAmount(pvData.getPvNbIniCfaRecLkdClaAmt());
        BigDecimal pvNbInitMaint = getPvAmount(pvData.getPvNbIniCfaRecLkdMtnAmt());
        BigDecimal pvNbInitRa = getPvAmount(pvData.getPvNbIniCfaRecLkdRadAmt());

        BigDecimal denomTotal = pvIfBegClaims.add(pvNbInitClaims)
                .add(pvIfBegMaint).add(pvNbInitMaint)
                .add(pvIfBegRa).add(pvNbInitRa)
                .add(context.getIfIfieAccretionClaims()).add(context.getNbIfieAccretionClaims())
                .add(context.getIfIfieAccretionRa()).add(context.getNbIfieAccretionRa())
                .add(context.getIfIfieRateChangeClaims()).add(context.getNbIfieRateChangeClaims())
                .add(context.getIfIfieRateChangeRa()).add(context.getNbIfieRateChangeRa());

        boolean isLcForRatio = (!isReversal && cohortLcForRatio.compareTo(BigDecimal.ZERO) < 0)
                || (isReversal && cohortLcForRatio.compareTo(BigDecimal.ZERO) > 0);
        if (isLcForRatio && denomTotal.compareTo(BigDecimal.ZERO) > 0) {
            lcAllocationRatioTotal = cohortLcForRatio.abs().divide(denomTotal.abs(), 16, RoundingMode.HALF_UP);
        }

        logger.logItem("LC分摊比例_合计", "[LC计量] LC分摊比例_合计", "LC分摊比例_合计 = |合同组LC| / SUM(...)",
                mapOf("合同组LC", cohortLcForRatio, "分母合计", denomTotal, "LC分摊比例_合计", lcAllocationRatioTotal), lcAllocationRatioTotal, null);

        BigDecimal pvIfCurClaims = getPvAmount(pvData.getPvIfBopCcaRepWlkClaAmt());
        BigDecimal pvIfCurMaint = getPvAmount(pvData.getPvIfBopCcaRepWlkMtnAmt());
        BigDecimal pvIfCurRa = getPvAmount(pvData.getPvIfBopCcaRepWlkRadAmt());
        BigDecimal pvNbCurClaims = getPvAmount(pvData.getPvNbIniCcaRepWlkClaAmt());
        BigDecimal pvNbCurMaint = getPvAmount(pvData.getPvNbIniCcaRepWlkMtnAmt());
        BigDecimal pvNbCurRa = getPvAmount(pvData.getPvNbIniCcaRepWlkRadAmt());

        BigDecimal allocatedLcTotal = pvIfCurClaims.add(pvIfCurMaint).add(pvIfCurRa)
                .add(pvNbCurClaims).add(pvNbCurMaint).add(pvNbCurRa)
                .multiply(lcAllocationRatioTotal);

        BigDecimal cohortLc = context.getEndLcBeforeAmort();
        BigDecimal cohortCsm = context.getEndCsmBeforeAmort();
        BigDecimal bopCsm = context.getBopCsm() != null ? context.getBopCsm() : BigDecimal.ZERO;
        BigDecimal nbInitialCsm = context.getNbInitialCsm() != null ? context.getNbInitialCsm() : BigDecimal.ZERO;
        BigDecimal csmInterest = (context.getIfInterestCsm() != null ? context.getIfInterestCsm() : BigDecimal.ZERO)
                .add(context.getNbInterestCsm() != null ? context.getNbInterestCsm() : BigDecimal.ZERO);

        BigDecimal sumLcTest = cohortLc.add(allocatedLcTotal).add(deltaCsmLc);
        BigDecimal sumCsmTest = cohortCsm.add(deltaCsmLc);

        BigDecimal allocatedLcExpAdjTotal;
        boolean isLcBucket = (!isReversal && cohortLc.compareTo(BigDecimal.ZERO) < 0)
                || (isReversal && cohortLc.compareTo(BigDecimal.ZERO) > 0);
        boolean lcStaysLc = (!isReversal && sumLcTest.compareTo(BigDecimal.ZERO) < 0)
                || (isReversal && sumLcTest.compareTo(BigDecimal.ZERO) > 0);
        boolean csmTurnsLc = cohortLc.compareTo(BigDecimal.ZERO) == 0 &&
                ((!isReversal && sumCsmTest.compareTo(BigDecimal.ZERO) < 0) ||
                        (isReversal && sumCsmTest.compareTo(BigDecimal.ZERO) > 0));
        if ((isLcBucket && lcStaysLc) || csmTurnsLc) {
            allocatedLcExpAdjTotal = deltaCsmLc.add(bopCsm).add(nbInitialCsm).add(csmInterest);
        } else {
            allocatedLcExpAdjTotal = bopLcTotal.add(nbInitialLcTotal).add(lcIfieTotal).add(allocatedLcTotal).negate();
        }

        BigDecimal lcBalanceToAdjustTotal = bopLcTotal.add(nbInitialLcTotal).add(lcIfieTotal).add(allocatedLcTotal).add(allocatedLcExpAdjTotal);

        // --- CF Portion ---
        logger.logSection("LC计量_预期现金流部分");

        BigDecimal bopLcCf = bopLc; // Assumption

        BigDecimal nbInitialLcCf;
        BigDecimal denomNbInit = pvNbInitClaims.add(pvNbInitMaint).add(pvNbInitRa);
        if (denomNbInit.compareTo(BigDecimal.ZERO) > 0) {
            nbInitialLcCf = nbInitialLcTotal.multiply(pvNbInitClaims.add(pvNbInitMaint)).divide(denomNbInit, 16, RoundingMode.HALF_UP);
        } else {
            nbInitialLcCf = BigDecimal.ZERO;
        }

        BigDecimal lcIfieCf = (context.getIfLcIfieCf() != null ? context.getIfLcIfieCf() : BigDecimal.ZERO)
                .add(context.getNbLcIfieCf() != null ? context.getNbLcIfieCf() : BigDecimal.ZERO);

        BigDecimal allocatedLcCf = pvIfCurClaims.add(pvIfCurMaint).add(pvNbCurClaims).add(pvNbCurMaint).multiply(lcAllocationRatioTotal);

        BigDecimal allocatedLcExpAdjCf;
        if (lcBalanceToAdjustTotal.compareTo(BigDecimal.ZERO) == 0) {
            allocatedLcExpAdjCf = bopLcTotal.add(nbInitialLcTotal).add(lcIfieTotal).add(allocatedLcTotal).negate();
        } else {
            if (deltaCsmLc.compareTo(BigDecimal.ZERO) != 0) {
                allocatedLcExpAdjCf = allocatedLcExpAdjTotal.multiply(deltaCfTotal).divide(deltaCsmLc, 16, RoundingMode.HALF_UP);
            } else {
                allocatedLcExpAdjCf = BigDecimal.ZERO;
            }
        }

        BigDecimal lcBalanceToAdjustCf = bopLcCf.add(nbInitialLcCf).add(lcIfieCf).add(allocatedLcCf).add(allocatedLcExpAdjCf);

        BigDecimal lcAdjustCf = csmAmortRatio.compareTo(BigDecimal.ONE) >= 0 ? lcBalanceToAdjustCf.negate() : BigDecimal.ZERO;
        BigDecimal endLcCf = lcBalanceToAdjustCf.add(lcAdjustCf);

        context.setLcAdjustCf(lcAdjustCf);
        context.setAllocatedLcCf(allocatedLcCf);
        context.setAllocatedLcExpAdjCf(allocatedLcExpAdjCf);
        context.setEndLcCf(endLcCf);
        context.setNbInitialLcCf(nbInitialLcCf);

        logger.logItem("LC计量_预期现金流", "[LC计量] 预期现金流部分的LC计量", "...", mapOf("期末LC余额_预期现金流", endLcCf), endLcCf, null);

        // --- RA Portion ---
        logger.logSection("LC计量_非金融风险调整部分");

        BigDecimal bopLcRa = BigDecimal.ZERO;
        BigDecimal nbInitialLcRa = nbInitialLcTotal.subtract(nbInitialLcCf);

        BigDecimal lcIfieRa = (context.getIfLcIfieRa() != null ? context.getIfLcIfieRa() : BigDecimal.ZERO)
                .add(context.getNbLcIfieRa() != null ? context.getNbLcIfieRa() : BigDecimal.ZERO);

        BigDecimal allocatedLcRa = pvIfCurRa.add(pvNbCurRa).multiply(lcAllocationRatioTotal);

        BigDecimal allocatedLcExpAdjRa = allocatedLcExpAdjTotal.subtract(allocatedLcExpAdjCf);

        BigDecimal lcBalanceToAdjustRa = bopLcRa.add(nbInitialLcRa).add(lcIfieRa).add(allocatedLcRa).add(allocatedLcExpAdjRa);

        BigDecimal lcAdjustRa = csmAmortRatio.compareTo(BigDecimal.ONE) >= 0 ? lcBalanceToAdjustRa.negate() : BigDecimal.ZERO;
        BigDecimal endLcRa = lcBalanceToAdjustRa.add(lcAdjustRa);

        context.setLcAdjustRa(lcAdjustRa);
        context.setAllocatedLcRa(allocatedLcRa);
        context.setAllocatedLcExpAdjRa(allocatedLcExpAdjRa);
        context.setEndLcRa(endLcRa);
        context.setNbInitialLcRa(nbInitialLcRa);

        logger.logItem("LC计量_非金融风险调整", "[LC计量] 非金融风险调整部分的LC计量", "...", mapOf("期末LC余额_非金融风险调整", endLcRa), endLcRa, null);

        // --- Total Final ---
        logger.logSection("LC计量_合计部分（最终汇总）");

        BigDecimal lcAdjustTotal = csmAmortRatio.compareTo(BigDecimal.ONE) >= 0 ? lcBalanceToAdjustTotal.negate() : BigDecimal.ZERO;
        BigDecimal endLcTotal = lcBalanceToAdjustTotal.add(lcAdjustTotal);

        context.setLcChange(allocatedLcExpAdjTotal);
        context.setEndLcFinal(endLcTotal);
        context.setAllocatedLcTotal(allocatedLcTotal);

        logger.logItem("LC计量_合计", "[LC计量] 合计部分的LC计量", "...", mapOf("期末LC余额_合计", endLcTotal), endLcTotal, null);
    }

    // --- Part 8.2: CSM Measurement ---

    private void calculateCsmMeasurement(CalculationContext context, CalculationLogger logger) {
        logger.logSection("Part 8.2: CSM计量 (CSM Measurement) [Sec 8.2]");

        BigDecimal cohortCsm = context.getEndCsmBeforeAmort() != null ? context.getEndCsmBeforeAmort() : BigDecimal.ZERO;

        BigDecimal deltaCsmLc = context.getExpAdjCsmImpact() != null ? context.getExpAdjCsmImpact() : BigDecimal.ZERO;
        BigDecimal deltaCfTotal = context.getDeltaCfTotal() != null ? context.getDeltaCfTotal() : BigDecimal.ZERO;

        BigDecimal allocatedLcExpAdjTotal = context.getLcChange() != null ? context.getLcChange() : BigDecimal.ZERO;
        BigDecimal allocatedLcExpAdjCf = context.getAllocatedLcExpAdjCf() != null ? context.getAllocatedLcExpAdjCf() : BigDecimal.ZERO;

        BigDecimal csmAbsorbedTotal = deltaCsmLc.subtract(allocatedLcExpAdjTotal);
        // BigDecimal csmAbsorbedCf = deltaCfTotal.subtract(allocatedLcExpAdjCf); // 预留：如需拆分CF吸收可启用
        // BigDecimal csmAbsorbedRa = csmAbsorbedTotal.subtract(csmAbsorbedCf); // 预留：如需拆分CF/RA吸收可启用

        context.setCsmAbsorbed(csmAbsorbedTotal);

        logger.logItem("被CSM吸收的变化", "[Sec 8.2] 被CSM吸收的变化", "被CSM吸收的变化 = 被CSM/LC吸收的变化合计 - 被LC吸收的变化",
                mapOf("被CSM/LC吸收的变化合计", deltaCsmLc, "被LC吸收的变化", allocatedLcExpAdjTotal, "被CSM吸收的变化", csmAbsorbedTotal),
                csmAbsorbedTotal, "通过总变化减去LC吸收部分得到CSM吸收部分");

        LocalDate startOfYear = LocalDate.of(context.getYear(), 1, 1);
        boolean isInitialYear = context.isInitialYear();

        BigDecimal csmAmortRatio;
        if (context.getPolicies() != null && !context.getPolicies().isEmpty()) {
            csmAmortRatio = coverageUnitsService.calculateCoverageUnitsReleased(
                    context.getPolicies(),
                    context.getEopDate(),
                    startOfYear,
                    logger,
                    isInitialYear
            ).divide(coverageUnitsService.calculateCoverageUnitsRemaining(
                    context.getPolicies(),
                    context.getEopDate(),
                    logger
            ).add(coverageUnitsService.calculateCoverageUnitsReleased(
                    context.getPolicies(),
                    context.getEopDate(),
                    startOfYear,
                    logger,
                    isInitialYear
            )), 16, RoundingMode.HALF_UP);
        } else {
            csmAmortRatio = BigDecimal.ZERO;
        }

        BigDecimal csmBeforeAmortAdjusted = cohortCsm.add(csmAbsorbedTotal);

        BigDecimal csmAmortAmount;
        BigDecimal csmFinal;
        if (csmBeforeAmortAdjusted.compareTo(BigDecimal.ZERO) <= 0) {
            csmAmortAmount = BigDecimal.ZERO;
            csmFinal = csmBeforeAmortAdjusted;
        } else {
            csmAmortAmount = csmBeforeAmortAdjusted.multiply(csmAmortRatio).negate();
            csmFinal = csmBeforeAmortAdjusted.add(csmAmortAmount);
        }

        context.setCsmAmortAmount(csmAmortAmount);
        context.setEndCsmFinal(csmFinal);
        context.setCsmAmortRatio(csmAmortRatio);

        logger.logItem("CSM摊销与期末余额", "[Sec 8.2] CSM摊销与期末余额计算", "期末CSM = 摊销前CSM + CSM摊销",
                mapOf("摊销前CSM", csmBeforeAmortAdjusted, "CSM摊销", csmAmortAmount, "期末CSM", csmFinal), csmFinal, null);
    }

    // --- Helpers ---

    private BigDecimal getBopCsmLc(CalculationContext context, CohortState cohortState) {
        BigDecimal bopCsm = context.getBopCsm();
        BigDecimal bopLc = context.getBopLc();

        if (bopCsm == null && cohortState != null){
            bopCsm = cohortState.getBopCsm();
        }
        if (bopLc == null && cohortState != null){bopLc = cohortState.getBopLc();}

        BigDecimal bopCsmVal = bopCsm != null ? bopCsm : BigDecimal.ZERO;
        BigDecimal bopLcVal = bopLc != null ? bopLc : BigDecimal.ZERO;

        return bopCsmVal.add(bopLcVal);
    }

    private BigDecimal getPvAmount(BigDecimal value) {
        return value != null ? value : BigDecimal.ZERO;
    }

    private List<RateCurve> getWlkCurveFromPvData(CalculationContext context, String uwMonthStr) {
        PVSourceData pvData = context.getPvSourceData().getData(uwMonthStr);
        if (pvData != null) {
             // In a real implementation, this would parse the curve from PV data
             // For now, we assume ratesManagerService can handle this or we fallback
             // Python implementation: return context.rates_manager.get_wlk_curve(uw_month_str)
             // or parse from pv_data.
        }
        // Fallback: use ratesManager
        return ratesManagerService.getRates(uwMonthStr, "Yield Curve"); // Assumption
    }

    // --- Helper Methods for Interest Calculation ---

    private int monthsFromUwToTarget(LocalDate uwDate, String targetMonthStr) {
        if (uwDate == null || targetMonthStr == null) {
            return 0;
        }
        try {
            LocalDate firstDayOfMonth = LocalDate.parse(targetMonthStr + "01", DateTimeFormatter.ofPattern("yyyyMMdd"));
            LocalDate targetDate = firstDayOfMonth.with(java.time.temporal.TemporalAdjusters.lastDayOfMonth());

            java.time.Period period = java.time.Period.between(uwDate, targetDate);
            int months = period.getYears() * 12 + period.getMonths();

            if (targetDate.isAfter(uwDate) && months == 0) {
                months = 1;
            }
            return Math.max(months, 0);
        } catch (Exception e) {
            return 0;
        }
    }

    private InterestResult calculateNbCsmInterest(
            BigDecimal principal,
            List<RateCurve> wlkCurve,
            LocalDate uwDate,
            String valMonthStr,
            LocalDate stopDate
    ) {
        if (wlkCurve == null || wlkCurve.isEmpty() || principal == null || principal.compareTo(BigDecimal.ZERO) == 0) {
            return new InterestResult(BigDecimal.ZERO, BigDecimal.ZERO);
        }

        int monthsDiff = monthsFromUwToTarget(uwDate, valMonthStr);
        if (monthsDiff <= 0) {
            return new InterestResult(BigDecimal.ZERO, BigDecimal.ZERO);
        }

        int actualMonthsDiff = monthsDiff;
        if (stopDate != null) {
            try {
                LocalDate valDate = LocalDate.parse(valMonthStr + "01", DateTimeFormatter.ofPattern("yyyyMMdd"));
                if (stopDate.getYear() == valDate.getYear()) {
                    if (stopDate.getMonthValue() < valDate.getMonthValue()) {
                        String stopMonthStr = stopDate.format(YYYYMM);
                        actualMonthsDiff = monthsFromUwToTarget(uwDate, stopMonthStr);
                    }
                }
            } catch (Exception e) {
                // Ignore
            }
        }

        if (actualMonthsDiff <= 0) {
            return new InterestResult(BigDecimal.ZERO, BigDecimal.ZERO);
        }

        Map<Integer, BigDecimal> ratesMap = wlkCurve.stream()
                .collect(Collectors.toMap(RateCurve::getTermMonth, RateCurve::getForwardDisrateValue, (k1, k2) -> k1));

        int maxTerm = wlkCurve.stream().mapToInt(RateCurve::getTermMonth).max().orElse(0);

        BigDecimal factor = BigDecimal.ONE;

        // Term 1: wlk[1] / 2
        BigDecimal r1 = ratesMap.getOrDefault(1, BigDecimal.ZERO);
        factor = factor.multiply(BigDecimal.ONE.add(r1.divide(new BigDecimal("2"), 10, RoundingMode.HALF_UP)));

        // Term 2 to actualMonthsDiff
        for (int term = 2; term <= actualMonthsDiff; term++) {
            BigDecimal r = ratesMap.get(term);
            if (r == null && maxTerm > 0) {
                r = ratesMap.getOrDefault(maxTerm, BigDecimal.ZERO);
            } else if (r == null) {
                r = BigDecimal.ZERO;
            }
            factor = factor.multiply(BigDecimal.ONE.add(r));
        }

        BigDecimal interest = principal.multiply(factor.subtract(BigDecimal.ONE));
        return new InterestResult(interest, factor.subtract(BigDecimal.ONE));
    }

    private InterestResult calculateIfCsmInterest(
            BigDecimal principal,
            List<RateCurve> wlkCurve,
            LocalDate uwDate,
            String bopMonthStr,
            String valMonthStr,
            LocalDate stopDate
    ) {
        if (wlkCurve == null || wlkCurve.isEmpty() || principal == null || principal.compareTo(BigDecimal.ZERO) == 0) {
            return new InterestResult(BigDecimal.ZERO, BigDecimal.ZERO);
        }

        int bopMonthsDiff = monthsFromUwToTarget(uwDate, bopMonthStr);
        int valMonthsDiff = monthsFromUwToTarget(uwDate, valMonthStr);

        if (valMonthsDiff <= bopMonthsDiff) {
            return new InterestResult(BigDecimal.ZERO, BigDecimal.ZERO);
        }

        int actualValMonthsDiff = valMonthsDiff;
        if (stopDate != null) {
            try {
                LocalDate valDate = LocalDate.parse(valMonthStr + "01", DateTimeFormatter.ofPattern("yyyyMMdd"));
                if (stopDate.getYear() == valDate.getYear()) {
                    if (stopDate.getMonthValue() < valDate.getMonthValue()) {
                        String stopMonthStr = stopDate.format(YYYYMM);
                        actualValMonthsDiff = monthsFromUwToTarget(uwDate, stopMonthStr);
                    }
                }
            } catch (Exception e) {
                // Ignore
            }
        }

        if (actualValMonthsDiff <= bopMonthsDiff) {
            return new InterestResult(BigDecimal.ZERO, BigDecimal.ZERO);
        }

        Map<Integer, BigDecimal> ratesMap = wlkCurve.stream()
                .collect(Collectors.toMap(RateCurve::getTermMonth, RateCurve::getForwardDisrateValue, (k1, k2) -> k1));

        int maxTerm = wlkCurve.stream().mapToInt(RateCurve::getTermMonth).max().orElse(0);

        BigDecimal factor = BigDecimal.ONE;

        for (int term = bopMonthsDiff + 1; term <= actualValMonthsDiff; term++) {
            BigDecimal r = ratesMap.get(term);
            if (r == null && maxTerm > 0) {
                r = ratesMap.getOrDefault(maxTerm, BigDecimal.ZERO);
            } else if (r == null) {
                r = BigDecimal.ZERO;
            }
            factor = factor.multiply(BigDecimal.ONE.add(r));
        }

        BigDecimal interest = principal.multiply(factor.subtract(BigDecimal.ONE));
        return new InterestResult(interest, factor.subtract(BigDecimal.ONE));
    }

    @Data
    @AllArgsConstructor
    private static class InterestResult {
        BigDecimal interest;
        BigDecimal factor;
    }

    private Map<String, Object> mapOf(Object... args) {
        Map<String, Object> map = new HashMap<>();
        if (args != null) {
            for (int i = 0; i < args.length; i += 2) {
                if (i + 1 < args.length && args[i] != null) {
                    map.put(args[i].toString(), args[i + 1]);
                }
            }
        }
        return map;
    }

}
