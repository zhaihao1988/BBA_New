package com.jdyx.cx.measure.strategy.impl;

import cn.hutool.core.lang.Opt;
import com.google.common.collect.Lists;
import com.jdyx.common.cache.measure.ConfMeasureActuarialAssumptionCacheService;
import com.jdyx.common.cache.measure.ConfMeasureCommonDisrateCacheService;
import com.jdyx.common.enums.EvaluateMethodTypeEnum;
import com.jdyx.common.measure.constant.StringConstant;
import com.jdyx.common.measure.service.MeasureBba1CfInfoService;
import com.jdyx.cx.measure.service.BaseMeasureCxService;
import com.jdyx.cx.measure.strategy.MeasureCfResultInfoStrategy;
import com.jdyx.measure.api.measure.domain.ConfMeasureActuarialAssumption;
import com.jdyx.measure.api.measure.domain.MeasureCfBasicData;
import com.jdyx.measure.api.measure.domain.MeasureCfResultInfo;
import com.kevin.common.utils.DateUtils;
import com.kevin.common.utils.StringUtils;
import com.kevin.common.utils.reflect.ReflectUtils;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.*;
import java.util.concurrent.CountDownLatch;

import static com.kevin.common.utils.DateUtils.YYYYMMDD;

/**
 * 产险-直保-BBA-7
 *
 * @author 陈佳能.
 * @date 2024/11/05.
 */
@SuppressWarnings("DuplicatedCode")
@Slf4j
@RequiredArgsConstructor
@Service
public class MeasureCfResultInfo7 extends BaseMeasureCxService implements MeasureCfResultInfoStrategy {

  /**
   * 11.计量明细统一接口
   */
  private final MeasureBba1CfInfoService measure1CfInfoService;
  /**
   * 折现利率表接口
   */
  private final ConfMeasureCommonDisrateCacheService confMeasureCommonDisrateCacheService;
  /**
   * 精算假设配置表接口
   */
  private final ConfMeasureActuarialAssumptionCacheService confMeasureActuarialAssumptionCacheService;

  @Override
  public void doOperation(List<MeasureCfBasicData> measureCfBasicDataList, EvaluateMethodTypeEnum evaluateMethod, String valMonth, CountDownLatch latch) {

  }

  /**
   * BBA获取 计量明细计算策略方法
   *
   * @param measureCfBasicDataList 计量源数据
   * @param evaluateMethod         评估方法 {@link EvaluateMethodTypeEnum}
   * @param valMonth               评估时点 计量明细数据
   * @return java.util.List<com.jdyx.measure.api.measure.domain.MeasureCfResultInfo>
   * @author 陈佳能.
   * @date 2024/11/05.
   */
  @Override
  public void doOperation(List<MeasureCfBasicData> measureCfBasicDataList,
                          EvaluateMethodTypeEnum evaluateMethod, String valMonth) {

    // f.折现率配置表--conf_measure_common_disrate
    // 1.获取 当前评估月的 折现利率map  <折现率类型_险种代码_预测月度, 折现利率>
    Map<String, BigDecimal> currentValMonDisrateMap = confMeasureCommonDisrateCacheService
      .getConfMeasureCommonDisRate(evaluateMethod.getCode(), valMonth);

    // h.精算假设配置表--conf_measure_actuarial_assumption
    // 2.获取 当前评估月的 精算假设  <(分组：险类代码+险种代码+车种代码+使用性质代码),<属性：属性值> >
    Map<String, Map<String, Object>> currentValMonActuarialAssumptionMap = confMeasureActuarialAssumptionCacheService
      .getConfMeasureActuarialAssumption(evaluateMethod.getCode(), valMonth);

    // 3.循环计算
    List<MeasureCfResultInfo> measureCfResultInfoList = Collections.synchronizedList(new ArrayList<>());
    Optional.ofNullable(measureCfBasicDataList).orElse(Lists.newArrayList()).parallelStream().forEach(entity -> {
      // 初始化对象
      MeasureCfResultInfo measureCfResultInfo = measure1CfInfoService.iniMeasureCfResultInfo();
      // 1.当前评估时点 = 当前评估时点 yyyyMM
      measure1CfInfoService.getValMonth(entity, measureCfResultInfo, evaluateMethod.getCode());
      // 2.上期评估时点 = 上期评估时点 yyyyMM
      measure1CfInfoService.getLastValMonth(entity, measureCfResultInfo, evaluateMethod.getCode());
      // 3.计量单元编号 = 计量单元编号
      measure1CfInfoService.getUnitId(entity, measureCfResultInfo, evaluateMethod.getCode());
      // 4.赠险标签 = 赠险标签
      measure1CfInfoService.getPresentFlag(entity, measureCfResultInfo, evaluateMethod.getCode());
      // 5.险种代码 = 险种代码
      measure1CfInfoService.getRiskCode(entity, measureCfResultInfo, evaluateMethod.getCode());
      // 64.险类代码 = 险类代码
      measureCfResultInfo.setClassCode(entity.getClassCode());
      // 6.签单日期 = 签单日期
      measure1CfInfoService.getUnderWriteDate(entity, measureCfResultInfo, evaluateMethod.getCode());
      // 7.保修期 = 保修期
      measure1CfInfoService.getWarrantyPeriod(entity, measureCfResultInfo, evaluateMethod.getCode());
      // 8.保险责任起期 = 保险责任起期
      measure1CfInfoService.getStartDate(entity, measureCfResultInfo, evaluateMethod.getCode());
      // 9.保险评估起期 = 保险评估起期
      measure1CfInfoService.getEvaluateDate(entity, measureCfResultInfo, evaluateMethod.getCode());
      // 10.保费总额 = 保费本币
      measure1CfInfoService.getPremiumCny(entity, measureCfResultInfo, evaluateMethod.getCode());
      // 11.投资成分占比 = 投资成分占比
      measure1CfInfoService.getInvestProp(entity, measureCfResultInfo, evaluateMethod.getCode());
      // 12.合同组合编号 = 合同组合编号
      measure1CfInfoService.getPortfolioId(entity, measureCfResultInfo, evaluateMethod.getCode());
      // 13.保险获取现金流_本币 = 保险获取现金流_本币
      measure1CfInfoService.getIacfFolCny(entity, measureCfResultInfo, evaluateMethod.getCode());
      // 14.币种 = 币种
      measure1CfInfoService.getCurrency(entity, measureCfResultInfo, evaluateMethod.getCode());
      // 15.合同分组编号 = 合同组编号
      measure1CfInfoService.getGroupId(entity, measureCfResultInfo, evaluateMethod.getCode());
      // 16.是否当期新单
      measure1CfInfoService.getWhetherCurPolicy(entity, measureCfResultInfo, evaluateMethod.getCode());
      // 17.保险责任止期 = 保险责任止期
      measure1CfInfoService.getEndDate(entity, measureCfResultInfo, evaluateMethod.getCode());
      // 18.保障期限 = 保障期限
      measure1CfInfoService.getTerm(entity, measureCfResultInfo, evaluateMethod.getCode());
      // 19.归属机构 = 归属机构
      measure1CfInfoService.getComCode(entity, measureCfResultInfo, evaluateMethod.getCode());
      // 20.业务渠道 = 业务渠道
      measure1CfInfoService.getBusinessNature(entity, measureCfResultInfo, evaluateMethod.getCode());
      // 21.条款险别段 = 条款险别段
      measure1CfInfoService.getCoverageSegment(entity, measureCfResultInfo, evaluateMethod.getCode());
      // 22.车辆种类 = 车辆种类
      measure1CfInfoService.getCarKindCode(entity, measureCfResultInfo, evaluateMethod.getCode());
      // 23.使用性质代码 = 使用性质代码
      measure1CfInfoService.getUseNatureCode(entity, measureCfResultInfo, evaluateMethod.getCode());
      // 24.评估方法 = 评估方法
      measure1CfInfoService.getValMethod(entity, measureCfResultInfo, evaluateMethod.getCode());
      // 25.计划缴费日期
      measure1CfInfoService.getPlanDate(entity, measureCfResultInfo, evaluateMethod.getCode());

      // 69	保单号
      measureCfResultInfo.setPolicyNo(entity.getPolicyNo());
      // 70	批单号
      measureCfResultInfo.setCertiNo(entity.getCertiNo());
      // 71	批单签单日期
      measureCfResultInfo.setCertiWriteDate(entity.getCertiWriteDate());
      //72.I17初始确认日期
      measureCfResultInfo.setIniConfirm(entity.getIniConfirm());

      // 55.当期评估时点的期初评估时点 yyyyMMdd
      measure1CfInfoService.getFirstValMonth(entity, measureCfResultInfo);

      // |预测月度|
      // (year(55.当期评估时点的期初时点)-year(25.计划缴费日期))*12+month(55.当期评估时点的期初时点)-month(25.计划缴费日期)  +1 的 折现率
      int termMonth = Math.abs(DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(measureCfResultInfo.getPlanDate()),
        DateUtils.parseDate(measureCfResultInfo.getFirstValMonth()))) + 1;

      // 获取 评估月度 = 当期评估时点  的折现率Map <NA_NA_预测月度, 折现利率>
      // 预测月度为(year(55.当期评估时点的期初时点)-year(25.计划缴费日期))*12+month(55.当期评估时点的期初时点)-month(25.计划缴费日期)  +1 的 折现率
      Map<String, BigDecimal> currentValMonthCommonDisRateMap = confMeasureCommonDisrateCacheService
        .getConfMeasureCommonDisRate(evaluateMethod.getCode(), measureCfResultInfo.getValMonth());
      BigDecimal currentValMonthCommonDisRate = currentValMonthCommonDisRateMap.get(
        String.format("%s_%s_%s", StringConstant.STRING_NA, StringConstant.STRING_NA, termMonth));


      // 获取 评估月度 = 保险责任起期 的折现率Map <NA_NA_预测月度, 折现利率>
      // 预测月度为(year(55.当期评估时点的期初时点)-year(25.计划缴费日期))*12+month(55.当期评估时点的期初时点)-month(25.计划缴费日期)  +1 的 折现率
      Map<String, BigDecimal> startDateCommonDisRateMap = confMeasureCommonDisrateCacheService
        .getConfMeasureCommonDisRate(evaluateMethod.getCode(), measureCfResultInfo.getStartDate().substring(0, 6));
      BigDecimal startDateCommonDisRate = startDateCommonDisRateMap.get(
        String.format("%s_%s_%s", StringConstant.STRING_NA, StringConstant.STRING_NA, termMonth));

      // 获取 评估月度 = 上期评估时点  的折现率Map <NA_NA_预测月度, 折现利率>
      // 预测月度为(year(55.当期评估时点的期初时点)-year(25.计划缴费日期))*12+month(55.当期评估时点的期初时点)-month(25.计划缴费日期)  +1 的 折现率
      Map<String, BigDecimal> lastValMonthCommonDisRateMap = confMeasureCommonDisrateCacheService
        .getConfMeasureCommonDisRate(evaluateMethod.getCode(), measureCfResultInfo.getLastValMonth());
      BigDecimal lastValMonthCommonDisRate = lastValMonthCommonDisRateMap.get(
        String.format("%s_%s_%s", StringConstant.STRING_NA, StringConstant.STRING_NA, termMonth));

      // 获取 评估月度 = max(保险责任起期, 上期评估时点) 的折现率Map <折现率类型_险种代码_预测月度, 折现利率>
      String lastValMonthStr = DateUtils.parseDateToStr(YYYYMMDD, DateUtils.endMonth(measureCfResultInfo.getLastValMonth()));
      String maxLastValMonthAndStartDateStr = measureCfResultInfo.getStartDate().compareTo(lastValMonthStr) > 0 ? measureCfResultInfo.getStartDate() : lastValMonthStr;
      Map<String, BigDecimal> maxLastValMonthAndStartDateCommonDisRateMap = confMeasureCommonDisrateCacheService
        .getConfMeasureCommonDisRate(evaluateMethod.getCode(), maxLastValMonthAndStartDateStr.substring(0, 6));

      // 获取 评估月度 = 签单日期 的折现率Map <折现率类型_险种代码_预测月度, 折现利率>
      Map<String, BigDecimal> underWriteDateDisRateMap = confMeasureCommonDisrateCacheService
        .getConfMeasureCommonDisRate(evaluateMethod.getCode(), measureCfResultInfo.getUnderWriteDate().substring(0, 6));


      // 当期评估时点 ra因子
      Map<String, Object> currentAssumptionMap = currentValMonActuarialAssumptionMap.get(StringUtils.joinWith("_",
        measureCfResultInfo.getClassCode(), StringConstant.STRING_NA,
        Opt.ofBlankAble(measureCfResultInfo.getCarKindCode()).orElse(StringConstant.STRING_NA),
        Opt.ofBlankAble(measureCfResultInfo.getUseNatureCode()).orElse(StringConstant.STRING_NA)));

      BigDecimal currentRaAssumption = (BigDecimal) Optional.ofNullable(
          currentAssumptionMap.get(ReflectUtils.getFieldName(ConfMeasureActuarialAssumption::getRa)))
        .orElse(BigDecimal.ZERO);

      // 当期评估时点的期初评估时点 ra因子
      // 获取 当期评估时点的期初评估时点 的 精算假设  <分组,<属性：属性值>>
      Map<String, Map<String, Object>> openingValMonActuarialAssumption = confMeasureActuarialAssumptionCacheService
        .getConfMeasureActuarialAssumption(evaluateMethod.getCode(), measureCfResultInfo.getFirstValMonth().substring(0, 6));

      Map<String, Object> actuarialAssumptionMap = openingValMonActuarialAssumption.get(StringUtils.joinWith("_",
        measureCfResultInfo.getClassCode(), StringConstant.STRING_NA,
        Opt.ofBlankAble(measureCfResultInfo.getCarKindCode()).orElse(StringConstant.STRING_NA),
        Opt.ofBlankAble(measureCfResultInfo.getUseNatureCode()).orElse(StringConstant.STRING_NA)));

      BigDecimal openingRaAssumption = (BigDecimal) Optional.ofNullable(
          actuarialAssumptionMap.get(ReflectUtils.getFieldName(ConfMeasureActuarialAssumption::getRa)))
        .orElse(BigDecimal.ZERO);

      // 计算：
      // 26.期初保费未来现金流现值
      measure1CfInfoService.getOpeningPvPremium(measureCfResultInfo);
      // 27.期初理赔未来现金流现值
      measure1CfInfoService.getOpeningPvPaidLoss(measureCfResultInfo);
      // 28.期初维持费用未来现金流现值
      measure1CfInfoService.getOpeningPvMaintenanceExpense(measureCfResultInfo);
      // 29.期初获取费用未来现金流现值
      measure1CfInfoService.getOpeningPvIacf(measureCfResultInfo);
      // 30.期初未来现金流现值
      measure1CfInfoService.getOpeningBel(measureCfResultInfo, evaluateMethod.getCode());
      // 31.期初非金融风险调整
      measure1CfInfoService.getOpeningRa(measureCfResultInfo, evaluateMethod.getCode(), openingRaAssumption);
      // 32.期初合约服务边际
      measure1CfInfoService.getOpeningCsm(measureCfResultInfo, evaluateMethod.getCode());
      // 33.期初损失成分
      measure1CfInfoService.getOpeningLc(measureCfResultInfo, evaluateMethod.getCode());
      // 34.当期保费未来现金流现值
      measure1CfInfoService.getCurrentPvPremium(measureCfResultInfo, evaluateMethod.getCode(), startDateCommonDisRate, lastValMonthCommonDisRate);
      // 35.当期理赔未来现金流现值
      measure1CfInfoService.getCurrentPvPaidLoss(measureCfResultInfo, evaluateMethod.getCode(), maxLastValMonthAndStartDateCommonDisRateMap);
      // 36.当期维持费用未来现金流现值
      measure1CfInfoService.getCurrentPvMaintenanceExpense(measureCfResultInfo, evaluateMethod.getCode(), maxLastValMonthAndStartDateCommonDisRateMap);
      // 37.当期获取费用未来现金流现值
      measure1CfInfoService.getCurrentPvIacf(measureCfResultInfo);
      // 38.当期未来现金流现值
      measure1CfInfoService.getCurrentBel(measureCfResultInfo, evaluateMethod.getCode());
      // 39.当期非金融风险调整
      measure1CfInfoService.getCurrentRa(measureCfResultInfo, evaluateMethod.getCode(), currentRaAssumption);
      // 40.当期理赔未来现金流现值-保单变动
      measure1CfInfoService.getCurrentPvPaidLossNop(measureCfResultInfo, evaluateMethod.getCode(), maxLastValMonthAndStartDateCommonDisRateMap);
      // 41.当期维持费用未来现金流现值-保单变动
      measure1CfInfoService.getCurrentPvMaintenanceExpenseNop(measureCfResultInfo, evaluateMethod.getCode(), maxLastValMonthAndStartDateCommonDisRateMap);
      // 42.当期未来现金流现值-保单变动
      measure1CfInfoService.getCurrentBelNop(measureCfResultInfo, evaluateMethod.getCode());
      // 43.当期非金融风险调整-保单变动
      measure1CfInfoService.getCurrentRaNop(measureCfResultInfo, evaluateMethod.getCode(), currentRaAssumption);
      // 44.当期理赔未来现金流现值-假设变动
      measure1CfInfoService.getCurrentPvPaidLossChg(measureCfResultInfo, evaluateMethod.getCode(), maxLastValMonthAndStartDateCommonDisRateMap);
      // 45.当期维持费用未来现金流现值-假设变动
      measure1CfInfoService.getCurrentPvMaintenanceExpenseChg(measureCfResultInfo, evaluateMethod.getCode(), maxLastValMonthAndStartDateCommonDisRateMap);
      // 46.当期未来现金流现值-假设变动
      measure1CfInfoService.getCurrentBelChg(measureCfResultInfo, evaluateMethod.getCode());
      // 47.当期非金融风险调整-假设变动
      measure1CfInfoService.getCurrentRaChg(measureCfResultInfo, evaluateMethod.getCode(), currentRaAssumption);
      // 48.当期理赔未来现金流现值-金融假设变动
      measure1CfInfoService.getCurrentPvPaidLossChgInt(measureCfResultInfo, evaluateMethod.getCode(), currentValMonDisrateMap);
      // 49.当期维持费用未来现金流现值-金融假设变动
      measure1CfInfoService.getCurrentPvMaintenanceExpenseChgInt(measureCfResultInfo, evaluateMethod.getCode(), currentValMonDisrateMap);
      // 65. 当期保费未来现金流现值-金融假设变动
      measure1CfInfoService.getCurrentPvPremiumChgInt(measureCfResultInfo, evaluateMethod.getCode(), currentValMonthCommonDisRate);
      // 66. 当期获取费用未来现金流现值-金融假设变动
      measure1CfInfoService.getCurrentPvIacfChgInt(measureCfResultInfo);
      // 50.当期未来现金流现值-金融假设变动
      measure1CfInfoService.getCurrentBelChgInt(measureCfResultInfo, evaluateMethod.getCode());
      // 51.当期非金融风险调整-金融假设变动
      measure1CfInfoService.getCurrentRaChgInt(measureCfResultInfo, evaluateMethod.getCode(), currentRaAssumption);
      // 52.当期服务量
      measure1CfInfoService.getBbaCurrServAmt(measureCfResultInfo, evaluateMethod.getCode());
      // 53.当期及未来服务量
      measure1CfInfoService.getBbaOtherServAmt(measureCfResultInfo);
      // 54.期初未满期保费
      measure1CfInfoService.getUnearnPremium(measureCfResultInfo);
      // 56 当期保费未来现金流现值-锁定期初利率
      measure1CfInfoService.getCurrentPvPremiumLockInt(measureCfResultInfo, evaluateMethod.getCode(), underWriteDateDisRateMap);
      // 57 当期理赔未来现金流现值-锁定期初利率
      //measure1CfInfoService.getCurrentPvPaidLossLockInt(measureCfResultInfo, evaluateMethod.getCode(), underWriteDateDisRateMap);
      // 58 当期维持费用未来现金流现值-锁定期初利率
      //measure1CfInfoService.getCurrentPvMaintenanceExpenseLockInt(measureCfResultInfo, evaluateMethod.getCode(), underWriteDateDisRateMap);
      // 59 当期获取费用未来现金流现值-锁定期初利率
      measure1CfInfoService.getCurrentPvIacfLockInt(measureCfResultInfo);
      // 60 当期未来现金流现值-锁定期初利率
      //measure1CfInfoService.getCurrentBelLockInt(measureCfResultInfo, evaluateMethod.getCode());
      // 61 当期理赔未来现金流现值-假设变动-锁定期初利率
      measure1CfInfoService.getCurrentPvPaidLossChgLockInt(measureCfResultInfo, evaluateMethod.getCode(), underWriteDateDisRateMap);
      // 62 当期维持费用未来现金流现值-假设变动-锁定期初利率
      measure1CfInfoService.getCurrentPvMaintenanceExpenseChgLockInt(measureCfResultInfo, evaluateMethod.getCode(), underWriteDateDisRateMap);
      // 63 当期未来现金流现值-假设变动-锁定期初利率
      measure1CfInfoService.getCurrentBelChgLockInt(measureCfResultInfo, evaluateMethod.getCode());
      // 67 当期非金融风险调整-锁定期初利率
      //measure1CfInfoService.getCurrentRaLockInt(measureCfResultInfo, evaluateMethod.getCode(), currentRaAssumption);
      // 67 当期非金融风险调整-假设变动-锁定期初利率
      measure1CfInfoService.getCurrentRaChgLockInt(measureCfResultInfo, evaluateMethod.getCode(), currentRaAssumption);

      measureCfResultInfoList.add(measureCfResultInfo);
    });
    measureCfResultInfoMapper.insertBatch(measureCfResultInfoList);
    log.info("measureCfResultInfo insert new Data {}-{}={}", valMonth, evaluateMethod.getCode(), measureCfResultInfoList.size());
  }

}
