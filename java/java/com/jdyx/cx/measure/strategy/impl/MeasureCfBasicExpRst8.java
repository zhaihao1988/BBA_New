package com.jdyx.cx.measure.strategy.impl;

import cn.hutool.core.date.DateUtil;
import cn.hutool.core.lang.Opt;
import cn.hutool.core.util.StrUtil;
import com.jdyx.common.cache.measure.ConfMeasureActuarialAssumptionCacheService;
import com.jdyx.common.cache.measure.ConfMeasureCommonDisrateCacheService;
import com.jdyx.cx.measure.service.BaseMeasureCxService;
import com.jdyx.cx.measure.strategy.MeasureCfBasicExpRstStrategy;
import com.jdyx.measure.api.measure.domain.*;
import com.jdyx.measure.api.measure.service.IConfMeasureCsmInterestService;
import com.jdyx.measure.api.measure.service.IMeasureConfBbaBeginCompensationService;
import com.jdyx.measure.api.measure.service.IMeasureConfBbaBeginMaintenanceCostService;
import com.kevin.common.constant.StringConstant;
import com.kevin.common.utils.DateUtils;
import com.kevin.common.utils.StringUtils;
import com.kevin.common.utils.reflect.ReflectUtils;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import javax.annotation.Resource;
import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.text.ParseException;
import java.util.*;

import static com.jdyx.common.measure.tools.UtilsCommon.calculateRatePow;
import static com.kevin.common.utils.DateUtils.YYYYMM;
import static com.kevin.common.utils.DateUtils.YYYYMMDD;

/**
 * @author hzh
 * @version 1.0
 * @description: 获取直保BAA预取现金流数据
 * @date 2024/11/7
 */
@Slf4j
@RequiredArgsConstructor
@Service
public class MeasureCfBasicExpRst8 extends BaseMeasureCxService implements MeasureCfBasicExpRstStrategy {

    /*精算假设配置*/
    @Resource
    private ConfMeasureActuarialAssumptionCacheService confMeasureActuarialAssumptionCacheService;
    /*折现率配置*/
    @Resource
    private ConfMeasureCommonDisrateCacheService confMeasureCommonDisrateCacheService;
    /*csm计息配置*/
    @Resource
    private IConfMeasureCsmInterestService confMeasureCsmInterestService;

    @Resource
    private IMeasureConfBbaBeginMaintenanceCostService measureConfBbaBeginMaintenanceCostService;

    @Resource
    private IMeasureConfBbaBeginCompensationService measureConfBbaBeginCompensationService;

    @Override
    public List<MeasureCfBbaExpRst> doOperation(List<MeasureCfResultInfo> list, String valMethod, String valMonth) throws ParseException {

        log.info("直保BBA预期现金流【{}】...startEvaluate", valMonth);

        // 精算假设配置 (分组：险种代码+车种代码+使用性质代码)
        Map<String, Map<String, Object>> currentActuarialAssumptionMap =
                confMeasureActuarialAssumptionCacheService.getConfMeasureActuarialAssumption(valMethod, valMonth);


        // 1.获取 当前评估月的 折现利率map  <折现率类型_险种代码_预测月度, 折现利率>
        Map<String, BigDecimal> currentValMonDisrateMap = confMeasureCommonDisrateCacheService
                .getConfMeasureCommonDisRate(valMethod, valMonth);


        ArrayList<MeasureCfBbaExpRst> resList = new ArrayList<>();
        // 获取计量明细数据
        for (MeasureCfResultInfo e : list) {
            MeasureCfBbaExpRst entity = new MeasureCfBbaExpRst();
            entity.setValMethod(e.getValMethod());
            entity.setLastValMonth(e.getLastValMonth());
            //计划缴费日期
            entity.setPlanDate(e.getPlanDate());
            entity.setValMonth(e.getValMonth());
            entity.setUnitId(e.getUnitId());
            entity.setClassCode(e.getClassCode());
            entity.setRiskCode(e.getRiskCode());
            entity.setGroupId(e.getGroupId());
            entity.setComCode(e.getComCode());
            entity.setBusinessNature(e.getBusinessNature());
            entity.setCoverageSegment(e.getCoverageSegment());
            entity.setCarKindCode(e.getCarKindCode());
            entity.setUseNatureCode(e.getUseNatureCode());
            entity.setPortfolioId(e.getPortfolioId());
            entity.setCurrency(e.getCurrency());
            entity.setStartDate(e.getStartDate());
            entity.setEndDate(e.getEndDate());
            entity.setFirstValMonth(e.getFirstValMonth());
            entity.setIniConfirm(e.getIniConfirm());
            entity.setUnderWriteDate(e.getUnderWriteDate());
            // 是否当期新单
            entity.setWhetherCurPolicy(e.getWhetherCurPolicy());
            // 当期服务量
            entity.setCurrServAmt(e.getCurrServAmt());
            // 当期及未来服务量
            entity.setOtherServAmt(e.getOtherServAmt());
            // 当期服务比例
            entity.setCurRecPct(e.getCurrServAmt().divide(entity.getOtherServAmt(), MathContext.DECIMAL128));
            // 新单初始确认GPV（Current Rate）
            entity.setInitGpvNb("0".equals(e.getWhetherCurPolicy()) ? BigDecimal.ZERO : e.getOpeningBel());
            // 新单初始确认RA（Current Rate）
            entity.setInitRaNb("0".equals(e.getWhetherCurPolicy()) ? BigDecimal.ZERO : e.getOpeningRa());
            // 当期新确认最小计量单元的初始CSM
            entity.setInitCsmNb("0".equals(e.getWhetherCurPolicy()) ? BigDecimal.ZERO : e.getOpeningCsm());
            //"当期新确认最小计量单元的初始LC；
            entity.setInitLcNb("0".equals(e.getWhetherCurPolicy()) ? BigDecimal.ZERO : e.getOpeningLc());
            // 新单初始确认的获取费用
            entity.setInitIacfNb("0".equals(e.getWhetherCurPolicy()) ? BigDecimal.ZERO : e.getOpeningPvIacf());


            // 预测月度
            // ((year(1.当期评估时点)-year(52.当期评估时点的期初评估时点))*12+month(1.当期评估时点)-month(52.当期评估时点的期初评估时时点)+1))
            int currentSubOpeningTermMonth = DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(entity.getFirstValMonth()),
                    DateUtils.parseDate(DateUtils.endMonth(valMonth, YYYYMMDD))) + 1;

            int currentSubInitConfirmTermMonth = DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(entity.getIniConfirm()),
                    DateUtils.parseDate(DateUtils.endMonth(valMonth, YYYYMMDD))) + 1;

            // min(51.保险责任止期,1.当期评估时点)
            String minEndAndCurrentDate = Integer.parseInt(e.getEndDate()) < Integer.parseInt(DateUtils.endMonth(e.getValMonth(), YYYYMMDD)) ?
                    e.getEndDate() : DateUtils.endMonth(e.getValMonth(), YYYYMMDD);

            // max(53.签单日期 , 2.上期评估时点),
            String maxUnderAndLastMonth = entity.getStartDate().compareTo(DateUtils.endMonth(e.getLastValMonth(), YYYYMMDD)) > 0 ? e.getStartDate().substring(0, 6) : e.getLastValMonth();

            // 预测月度为(year(min(51.保险责任止期,1.当期评估时点))-year(52.当期评估时点的期初评估时点))*12+month(min(51.保险责任止期,1.当期评估时点))-month(52.当期评估时点的期初评估时点)+1)
            // ^((min(51.保险责任止期,1.当期评估时点)-52.当期评估时点的期初评估时点+1)/365)-1)
            int minEndAndCurrentDateTermMonth = (DateUtil.year(DateUtils.parseDate(minEndAndCurrentDate))
                    - DateUtil.year(DateUtils.parseDate(e.getFirstValMonth()))) * 12
                    + DateUtil.month(DateUtils.parseDate(minEndAndCurrentDate))
                    - DateUtil.month(DateUtils.parseDate(e.getFirstValMonth())) + 1;


            // 获取 评估月度 = 当期  的折现率Map
            Map<String, BigDecimal> currentValMonthCommonDisRateMap = confMeasureCommonDisrateCacheService
                    .getConfMeasureCommonDisRate(valMethod, valMonth);

            BigDecimal currentPointCurrentSubOpeningTermMonthCommonDisRate = currentValMonthCommonDisRateMap.get(
                    String.format("%s_%s_%s", StringConstant.STRING_NA, StringConstant.STRING_NA, currentSubOpeningTermMonth));

            BigDecimal currentPointCurrentSubInitConfirmTermMonthCommonDisRate = currentValMonthCommonDisRateMap.get(
                    String.format("%s_%s_%s", StringConstant.STRING_NA, StringConstant.STRING_NA, currentSubInitConfirmTermMonth));


            // 获取 评估月度 = 期初时点  的折现率Map
            Map<String, BigDecimal> openingValMonthCommonDisRateMap = confMeasureCommonDisrateCacheService
                    .getConfMeasureCommonDisRate(valMethod, entity.getFirstValMonth().substring(0, 6));

            BigDecimal openingPointAndCurrentSubOpeningTermMonthCommonDisRate = openingValMonthCommonDisRateMap.get(
                    String.format("%s_%s_%s", StringConstant.STRING_NA, StringConstant.STRING_NA, currentSubOpeningTermMonth));


            // 获取 评估月度 = 初始确认日  的折现率Map
            Map<String, BigDecimal> initConfirmMonthCommonDisRateMap = confMeasureCommonDisrateCacheService
                    .getConfMeasureCommonDisRate(valMethod, entity.getIniConfirm().substring(0, 6));

            BigDecimal initConfirmPointAndCurrentSubInitConfirmTermMonthCommonDisRate = initConfirmMonthCommonDisRateMap.get(
                    String.format("%s_%s_%s", StringConstant.STRING_NA, StringConstant.STRING_NA, currentSubInitConfirmTermMonth));


            // 表b(评估月为min(51.保险责任止期,1.当期评估时点),预测月度为(year(min(51.保险责任止期,1.当期评估时点))-year(52.当期评估时点的期初评估时点))*12+month(min(51.保险责任止期,1.当期评估时点))-month(52.当期评估时点的期初评估时点)+1)^((min(51.保险责任止期,1.当期评估时点)-52.当期评估时点的期初评估时点+1)/365)-1))
            // BigDecimal minEndAndCurrentDisRate = confMeasureCommonDisrateCacheService.getConfMeasureCommonDisRate(
            //   valMethod, minEndAndCurrentDate.substring(0,6), StringConstant.STRING_NA, StringConstant.STRING_NA, (long) minEndAndCurrentDateTermMonth);
            // BigDecimal minEndAndCurrentDisRatePow = calculateRatePow(minEndAndCurrentDisRate,
            //   minEndAndCurrentDate, e.getFirstValMonth(), BigDecimal.ONE);

            // 表b(评估月为53.签单日期,预测月度为(year(min(51.保险责任止期,1.当期评估时点))-year(52.当期评估时点的期初评估时点))*12+month(min(51.保险责任止期,1.当期评估时点))-month(52.当期评估时点的期初评估时点)+1)^((min(51.保险责任止期,1.当期评估时点)-52.当期评估时点的期初评估时点+1)/365)))
            BigDecimal underWritePointMinEndAndCurSubOpeningDisRate = confMeasureCommonDisrateCacheService.getConfMeasureCommonDisRate(
                    valMethod, DateUtils.parseDateToStr(YYYYMM, DateUtils.parseDate(e.getUnderWriteDate())), StringConstant.STRING_NA, StringConstant.STRING_NA, (long) minEndAndCurrentDateTermMonth);
            BigDecimal underWritePointMinEndAndCurSubOpeningDisRatePow = calculateRatePow(underWritePointMinEndAndCurSubOpeningDisRate,
                    minEndAndCurrentDate, e.getFirstValMonth(), BigDecimal.ONE);

            // 评估月度为max(53.签单日期 , 2.上期评估时点), 且预测月度为(year(min(51.保险责任止期,1.当期评估时点))-year(52.当期评估时点的期初评估时点))*12+month(min(51.保险责任止期,1.当期评估时点))-month(52.当期评估时点的期初评估时点)+1)^((min(51.保险责任止期,1.当期评估时点)-52.当期评估时点的期初评估时点+1)/365))
            BigDecimal maxUnderLastPointMinEndCurSubOpeningDisRate = confMeasureCommonDisrateCacheService.getConfMeasureCommonDisRate(valMethod, maxUnderAndLastMonth, StringConstant.STRING_NA, StringConstant.STRING_NA, (long) minEndAndCurrentDateTermMonth);
            BigDecimal maxUnderLastPointMinEndCurSubOpeningDisRatePow = calculateRatePow(maxUnderLastPointMinEndCurSubOpeningDisRate,
                    minEndAndCurrentDate, e.getFirstValMonth(), BigDecimal.ONE);


            /**
             *  21 预期现金流，保费:
             *  '--如果55.计划缴费日期>=52.当期评估时点的期初评估时点且55.计划缴费日期<=1.当期评估时点，则21.预期现金流-保费=表a.premium_cny
             * --如果55.计划缴费日期<52.当期评估时点的期初评估时点且55.计划缴费日期>当期评估时点,则21.预期现金流-保费=0
             */
            if(entity.getPlanDate().compareTo(entity.getFirstValMonth()) >= 0 && entity.getPlanDate().compareTo(entity.getValMonth()) <= 0) {
                entity.setExpcPremInc(e.getPremiumCny());
            }else if(entity.getPlanDate().compareTo(entity.getFirstValMonth()) < 0 && entity.getPlanDate().compareTo(entity.getValMonth()) > 0) {
              entity.setExpcPremInc(BigDecimal.ZERO);
            }else {
                entity.setExpcPremInc(BigDecimal.ZERO);
            }
            /**
             * 22 预期现金流，IACF现金流
             * '--如果55.计划缴费日期>=52.当期评估时点的期初评估时点且55.计划缴费日期<=1.当期评估时点，则22.预期现金流-IACF现金流=表a.保险获取现金流-本币
             * --如果55.计划缴费日期<52.当期评估时点的期初评估时点且55.计划缴费日期>当期评估时点,则22.预期现金流-IACF现金流=0
             */
            if(entity.getPlanDate().compareTo(entity.getFirstValMonth()) >= 0 && entity.getPlanDate().compareTo(entity.getValMonth()) <= 0) {
              entity.setExpcIacfOut(e.getIacfFolCny());
            }else if(entity.getPlanDate().compareTo(entity.getFirstValMonth()) < 0 && entity.getPlanDate().compareTo(entity.getValMonth()) > 0) {
              entity.setExpcIacfOut(BigDecimal.ZERO);
            }else {
              entity.setExpcIacfOut(BigDecimal.ZERO);
            }
            /**
             * 23 预期现金流，保险服务费用
             *
             // '=取表e(对应当期评估时点，计量单元编号，评估方法的所有duty_period_value汇总) -
             取表e(对应当期评估时点，计量单元编号，评估方法,
             编号>=((year(1.当期评估时点)-year(52.当期评估时点的期初评估时点))*12+month(1.当期评估时点)-month(52.当期评估时点的期初评估时点)+1)
             的所有duty_period_value汇总)
             */
          int BeginMaintenanceCostNo = Math.abs(DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(entity.getValMonth()),
            DateUtils.parseDate(entity.getFirstValMonth()))) + 2;

          BigDecimal BeginMaintenanceCostSum1 = Optional.ofNullable(measureConfBbaBeginMaintenanceCostService.selDataByUnitIdValMonth(entity.getUnitId(), entity.getValMonth()))
            .orElse(Arrays.asList(new MeasureConfBbaBeginMaintenanceCost()))
            .stream().map(MeasureConfBbaBeginMaintenanceCost::getDutyPeriodValue)
            .reduce(BigDecimal.ZERO, BigDecimal::add);

          BigDecimal BeginMaintenanceCostSum2 = Optional.ofNullable(measureConfBbaBeginMaintenanceCostService.selDataByUnitIdValMonth(entity.getUnitId(), entity.getValMonth()))
            .orElse(Arrays.asList(new MeasureConfBbaBeginMaintenanceCost()))
            .stream().filter(cost->cost.getDutyPeriod() >= BeginMaintenanceCostNo)
            .map(MeasureConfBbaBeginMaintenanceCost::getDutyPeriodValue)
            .reduce(BigDecimal.ZERO, BigDecimal::add);

          entity.setExpcMeOut(BeginMaintenanceCostSum1.subtract(BeginMaintenanceCostSum2));
            /**
             * 24 预期现金流，赔付的保险成分
             * =(
             *     取表h(对应当期评估时点，计量单元编号，评估方法的所有duty_period_value汇总)
             *     -
             *     取表h(
             *         对应当期评估时点，
             *         计量单元编号，
             *         评估方法，
             *         编号 >= ((year(1.当期评估时点) - year(52.当期评估时点的期初评估时点)) * 12 + month(1.当期评估时点) - month(52.当期评估时点的期初评估时点) + 1)
             *     )的所有duty_period_value汇总
             * )
             * *
             * (
             *     1 -
             *     (
             *         取表a.11.invest_prop /
             *         (取表g.赔付率 * (1 + 间接理赔费用率))
             *     )
             * )
             */
          // 当期精算假设配置
          Map<String, Object> currentRiskCodeActuarialAssumptionMap = currentActuarialAssumptionMap.get(
            StringUtils.joinWith("_", Opt.ofNullable(entity.getClassCode()).orElse(StringConstant.STRING_NA), StringConstant.STRING_NA,
              Opt.ofBlankAble(e.getCarKindCode()).orElse(StringConstant.STRING_NA),
              Opt.ofBlankAble(e.getUseNatureCode()).orElse(StringConstant.STRING_NA)));
          // 赔付率
          BigDecimal lossRatio = (BigDecimal) Opt.ofNullable(currentRiskCodeActuarialAssumptionMap.get(
            StrUtil.toUnderlineCase(ReflectUtils.getFieldName(ConfMeasureActuarialAssumption::getLossRatio)))).orElse(BigDecimal.ZERO);
          // 间接理赔费用率
          BigDecimal indirectClaimsExpenseRatio = (BigDecimal) Opt.ofNullable(currentRiskCodeActuarialAssumptionMap.get(
            StrUtil.toUnderlineCase(ReflectUtils.getFieldName(ConfMeasureActuarialAssumption::getIndirectClaimsExpenseRatio)))).orElse(BigDecimal.ZERO);
          BigDecimal divide = e.getInvestProp().divide(lossRatio.multiply(BigDecimal.ONE.add(indirectClaimsExpenseRatio)), 10, RoundingMode.HALF_UP);

          int beginCompensationNo = Math.abs(DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(entity.getValMonth()),
            DateUtils.parseDate(entity.getFirstValMonth()))) + 2;

          BigDecimal beginCompensationSum1 = Optional.ofNullable(measureConfBbaBeginCompensationService.selDataByUnitIdValMonth(entity.getUnitId(), entity.getValMonth()))
            .orElse(Arrays.asList(new MeasureConfBbaBeginCompensation()))
            .stream().map(MeasureConfBbaBeginCompensation::getDutyPeriodValue)
            .reduce(BigDecimal.ZERO, BigDecimal::add);

          BigDecimal beginCompensationSum2 = Optional.ofNullable(measureConfBbaBeginCompensationService.selDataByUnitIdValMonth(entity.getUnitId(), entity.getValMonth()))
            .orElse(Arrays.asList(new MeasureConfBbaBeginCompensation()))
            .stream().filter(cost->cost.getDutyPeriod() >= beginCompensationNo)
            .map(MeasureConfBbaBeginCompensation::getDutyPeriodValue)
            .reduce(BigDecimal.ZERO, BigDecimal::add);

          BigDecimal beginCompensationSum = beginCompensationSum1.subtract(beginCompensationSum2);
          //预期现金流，赔付的保险成分
          entity.setExpcClmOutIns(beginCompensationSum.multiply(BigDecimal.ONE.subtract(divide)));

            /**
             * 25 预期现金流，赔付的投资成分
             *(
             *     取表h(
             *         对应当期评估时点，
             *         计量单元编号，
             *         评估方法
             *     )的所有duty_period_value汇总
             *     -
             *     取表h(
             *         对应当期评估时点，
             *         计量单元编号，
             *         评估方法,
             *         编号 >= (
             *             (year(1.当期评估时点) - year(52.当期评估时点的期初评估时点)) * 12
             *             + month(1.当期评估时点) - month(52.当期评估时点的期初评估时点)+ 1
             *         )
             *     )的所有duty_period_value汇总
             * )
             * *
             * (
             *     取表a11.invest_prop
             *     /
             *     (
             *         取表g.赔付率
             *         *
             *         (1 + 间接理赔费用率)
             *     )
             * )
             */
            entity.setExpcClmOutInv(beginCompensationSum.multiply(divide));

          /**
           * 26 预期GPV 损益表IFIE	expc_ifie_gpv_pl
           =表a(26.opening_pv_premium)
           -表a(34.current_pv_premium)

           -表a(28.opening_pv_maintenance_expense)
           +表a(36.current_pv_maintenance_expense)
           -(表a(27.opening_pv_paid_loss)
           +表a(35.current_pv_paid_loss)

           -21.预期现金流,保费 expc_prem_inc
           +23.预期现金流,保险服务费用 expc_me_out
           +24.预期现金流,赔付的保险成分 expc_clm_out_ins
           +25.预期现金流,赔付的投资成分) expc_clm_out_inv
           */
          entity.setExpcIfieGpvPl(e.getOpeningPvPremium()
            .subtract(e.getCurrentPvPremium())
            .subtract(e.getOpeningPvMaintenanceExpense())
            .add(e.getCurrentPvMaintenanceExpense())
            .subtract(e.getOpeningPvPaidLoss())
            .add(e.getCurrentPvPaidLoss())
              .subtract(entity.getExpcPremInc())
              .add(entity.getExpcMeOut())
              .add(entity.getExpcClmOutIns())
              .add(entity.getExpcClmOutInv()));

            /**
             * 41 计入其他综合收益的保险财务损益-GPV（不含汇兑损益）	oci_inc_gpv
             * =50.current_bel_chg_int - 46.current_bel_chg
             */
            entity.setOciIncGpv(e.getCurrentBelChgInt().subtract(e.getCurrentBelChg()));


            /**
             * 28 预期RA 释放	expc_ra_rels
             * =表a.(51.current_ra_chg_int)*15.当期服务比例
             */
            entity.setExpcRaRels(e.getCurrentRaChgInt()
                    .multiply(e.getCurRecPct()).setScale(10, RoundingMode.HALF_UP));
            // 新单初始确认现金流入现值
            entity.setInitDcfInvNb("0".equals(entity.getWhetherCurPolicy()) ? BigDecimal.ZERO : e.getOpeningPvPremium());
            // 新单初始确认现金流出现值
            entity.setInitDcfOutNb("0".equals(entity.getWhetherCurPolicy()) ? BigDecimal.ZERO : e.getOpeningPvPaidLoss().add(e.getOpeningPvMaintenanceExpense()));


            /**
             * 计入损益的保险财务损益-CSM计息	csm_int_accret
             * --如果6.是否当期新单=1,
             * 取表a(30.opening_csm)*(取表f(合同分组编码匹配,且预测月度为(year(min(51.保险责任止期,1.当期评估时点))-year(52.当期评估时点的期初评估时点))*12+month(min(51.保险责任止期,1.当期评估时点))-month(52.当期评估时点的期初评估时点)+1)^((min(51.保险责任止期,1.当期评估时点)-50.保险责任起期+1)/365)-1)
             * --如果6.是否当期新单=0,0
             */
            BigDecimal csmIntAccret = BigDecimal.ZERO;
            if ("1".equals(entity.getWhetherCurPolicy())) {
                // 获取 csm计息配置利率值
                BigDecimal csmDisRate = confMeasureCsmInterestService.selDataByGroupIdTermMonth(entity.getGroupId(), (long) minEndAndCurrentDateTermMonth);
                BigDecimal csmDisRatePow = calculateRatePow(csmDisRate, minEndAndCurrentDate, e.getStartDate(), BigDecimal.ONE);
                csmIntAccret = e.getOpeningCsm().multiply(csmDisRatePow.subtract(BigDecimal.ONE)).setScale(10, RoundingMode.HALF_UP);
            }
            entity.setCsmIntAccret(csmIntAccret);

            // CSM当期摊销比例 =15.当期服务比例
            entity.setCsmReleaseRate(entity.getCurRecPct());
            // 当期LC分摊比例 =15.当期服务比例
            entity.setLcAmortRate(entity.getCurRecPct());

            // IACF计息 直接=0
            entity.setIacfIntAccret(BigDecimal.ZERO);

            // IACF当期摊销比例 =15.当期服务比例
            entity.setIacfReleaseRate(entity.getCurRecPct());

            // 计入损益的保险财务损益-计息-LC部分
            /**
             * 36 计入损益的保险财务损益-计息-LC部分	lc_int_accret_pl
             * --如果6.是否当期新单=1,19.init_lc_nb/(23.expc_me_out+24.expc_clm_out_ins+25.expc_clm_out_inv+17.init_ra_nb)*26.expc_ifie_gpv_pl
             * --如果6.是否当期新单=0,0
             * 备注：分母可能为0，所以设定当分母为0的时候，整条数据为0
             */
            if ("0".equals(entity.getWhetherCurPolicy())) {
                entity.setLcIntAccretPl(BigDecimal.ZERO);
            } else {
                BigDecimal add = entity.getExpcMeOut().add(entity.getExpcClmOutIns()).add(entity.getExpcClmOutInv()).add(entity.getInitRaNb());
                if (add.compareTo(BigDecimal.ZERO) == 0) {
                    entity.setLcIntAccretPl(BigDecimal.ZERO);
                } else {
                    entity.setLcIntAccretPl(entity.getInitLcNb().divide(add, MathContext.DECIMAL128).multiply(entity.getExpcIfieGpvPl()).setScale(10, RoundingMode.HALF_UP));
                }
            }

            // 计入损益的保险财务损益-金融假设变动-RA（不含汇兑损益）
            entity.setExpcIfieRaPlFa(BigDecimal.ZERO);

            /**
             * 38 计入其他综合收益的保险财务损益-RA（不含汇兑损益）
             *
             * =51.current_ra_chg_int - 47.current_ra_chg
             */

            entity.setExpcIfieRaOci(e.getCurrentRaChgInt().subtract(e.getCurrentRaChg()));

            // 39 RA假设变更
            entity.setRaBasisChg(e.getCurrentRaNop().subtract(e.getCurrentRaChg()));
            // 40 GPV假设变更
            entity.setGpvBasisChg(e.getCurrentBelNop().subtract(e.getCurrentBelChg()));


            // 42 保单数经验调整-GPV
            entity.setChgGpvNop(e.getCurrentBel().subtract(e.getCurrentBelNop()));
            // 43 保单数经验调整-RA
            entity.setChgRaNop(e.getCurrentRa().subtract(e.getCurrentRaNop()));
            // 期末GPV（资产负债表）
            entity.setGpvActlBs(BigDecimal.ZERO);
            // 期末RA（资产负债表）
            entity.setRaActlBs(BigDecimal.ZERO);
            // 期末GPV（损益表）
            entity.setGpvActlPl(BigDecimal.ZERO);
            // 期末RA（损益表）
            entity.setRaActlPl(BigDecimal.ZERO);

            /**
             * 51 初始确认ra计息
             *=17.init_ra_nb*取表b.((评估月为52.签单日期,预测月度为(year(min(51.保险责任止期,1.当期评估时点))-year(52.当期评估时点的期初评估时点))*12+month(min(51.保险责任止期,1.当期评估时点))-month(52.当期评估时点的期初评估时点)+1的利率)^((min(51.保险责任止期,1.当期评估时点)-52.当期评估时点的期初评估时点+1)/365)-1)
             * */

            entity.setRaIntAccret(entity.getInitRaNb().multiply(underWritePointMinEndAndCurSubOpeningDisRatePow.subtract(BigDecimal.ONE)).setScale(10, RoundingMode.HALF_UP));

            resList.add(entity);
        }

        log.info("直保BBA预期现金流...endEvaluate");

        return resList;
    }
}
