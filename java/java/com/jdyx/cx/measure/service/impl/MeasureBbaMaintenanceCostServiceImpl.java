package com.jdyx.cx.measure.service.impl;

import cn.hutool.core.collection.CollectionUtil;
import cn.hutool.core.date.DateUtil;
import com.google.common.collect.Lists;
import com.jdyx.common.cache.measure.ConfMeasureActuarialAssumptionCacheService;
import com.jdyx.common.measure.constant.NumberConstant;
import com.jdyx.common.measure.tools.UtilsCommon;
import com.jdyx.cx.measure.service.MeasureBbaMaintenanceCostService;
import com.jdyx.measure.api.measure.domain.*;
import com.kevin.common.constant.StringConstant;
import com.kevin.common.utils.DateUtils;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.util.*;

import static com.kevin.common.utils.DateUtils.YYYYMM;
import static com.kevin.common.utils.DateUtils.YYYYMMDD;

/**
 * 直保Bba维持费用相关_期初/当期/当期精算假设变动Service实现类业务层处理
 */
@Slf4j
@RequiredArgsConstructor
@Service
public class MeasureBbaMaintenanceCostServiceImpl implements MeasureBbaMaintenanceCostService {

  /**
   * 精算假设配置缓存数据服务
   */
  private final ConfMeasureActuarialAssumptionCacheService confMeasureActuarialAssumptionCacheService;

  /**
   * 生成 维持费用相关_期初数据
   *
   * @param measureCfBasicDataList       计量源数据
   * @param measureConfBbaBeginPeriodMap 经过天数配置_期初List
   * @return List<MeasureConfBbaBeginMaintenanceCost> 维持费用相关_期初数据
   */
  @Override
  public List<MeasureConfBbaBeginMaintenanceCost> setCxZbMeasureBbaBeginMaintenanceCost(List<MeasureCfBasicData> measureCfBasicDataList, Map<String, List<MeasureConfBbaBeginPeriod>> measureConfBbaBeginPeriodMap) {
    List<MeasureConfBbaBeginMaintenanceCost> measureConfBbaBeginMaintenanceCostList = Lists.newArrayList();
    Optional.ofNullable(measureCfBasicDataList).orElse(Lists.newArrayList()).forEach(entity -> {
      //获取精算假设配置表数据 维持费用率  (以险类代码、max(保险责任起期,上期评估时点)和评估方法匹配)
      String maxStartAndLastValMonth = DateUtil.compare(DateUtils.parseDate(entity.getStartDate()), DateUtils.parseDate(DateUtils.endMonth(entity.getLastValMonth(), YYYYMMDD)))
        > NumberConstant.LONG_ZERO ? DateUtils.parseDateToStr(YYYYMM, DateUtils.parseDate(entity.getStartDate())) : entity.getLastValMonth();
      // 维持费用率
      BigDecimal maintenanceExpenseRatio = confMeasureActuarialAssumptionCacheService.getConfMeasureActuarialAssumption(entity.getValMethod(), maxStartAndLastValMonth, entity.getClassCode(), StringConstant.STRING_NA,
        StringConstant.STRING_NA, StringConstant.STRING_NA, ConfMeasureActuarialAssumption::getMaintenanceExpenseRatio);
      List<MeasureConfBbaBeginMaintenanceCost> measureConfBbaBeginMaintenanceCosts = doBeginEvaluate(entity, measureConfBbaBeginPeriodMap.get(entity.getUnitId()), maintenanceExpenseRatio);
      if (CollectionUtil.isNotEmpty(measureConfBbaBeginMaintenanceCosts)) {
        measureConfBbaBeginMaintenanceCostList.addAll(measureConfBbaBeginMaintenanceCosts);
      }
    });
    return measureConfBbaBeginMaintenanceCostList;
  }

  /**
   * 生成 维持费用相关_当期数据
   *
   * @param measureCfBasicDataList         计量源数据
   * @param measureConfBbaCurrentPeriodMap 经过天数配置_当期
   * @return List<MeasureConfBbaCurrentMaintenanceCost> 维持费用相关_当期数据
   */
  @Override
  public List<MeasureConfBbaCurrentMaintenanceCost> setCxZbMeasureBbaCurrentMaintenanceCost(List<MeasureCfBasicData> measureCfBasicDataList, Map<String, List<MeasureConfBbaCurrentPeriod>> measureConfBbaCurrentPeriodMap) {
    List<MeasureConfBbaCurrentMaintenanceCost> measureConfBbaCurrentMaintenanceCostList = Lists.newArrayList();
    Optional.ofNullable(measureCfBasicDataList).orElse(Lists.newArrayList()).forEach(entity -> {
      //获取精算假设配置表数据 维持费用率  (以险类代码、max(保险责任起期,上期评估时点)和评估方法匹配)
      String maxStartAndLastValMonth = DateUtil.compare(DateUtils.parseDate(entity.getStartDate()), DateUtils.parseDate(DateUtils.endMonth(entity.getLastValMonth(), YYYYMMDD)))
        > NumberConstant.LONG_ZERO ? DateUtils.parseDateToStr(YYYYMM, DateUtils.parseDate(entity.getStartDate())) : entity.getLastValMonth();
      // 维持费用率
      BigDecimal maintenanceExpenseRatio = confMeasureActuarialAssumptionCacheService.getConfMeasureActuarialAssumption(entity.getValMethod(), maxStartAndLastValMonth, entity.getClassCode(), StringConstant.STRING_NA,
        StringConstant.STRING_NA, StringConstant.STRING_NA, ConfMeasureActuarialAssumption::getMaintenanceExpenseRatio);
      List<MeasureConfBbaCurrentMaintenanceCost> measureConfBbaCurrentMaintenanceCosts = doCurrentEvaluate(entity, measureConfBbaCurrentPeriodMap.get(entity.getUnitId()), maintenanceExpenseRatio);
        if (CollectionUtil.isNotEmpty(measureConfBbaCurrentMaintenanceCosts)) {
          measureConfBbaCurrentMaintenanceCostList.addAll(measureConfBbaCurrentMaintenanceCosts);
        }
    });
    return measureConfBbaCurrentMaintenanceCostList;
  }

  /**
   * 生成 维持费用相关_当期计算假设变动数据
   *
   * @param measureCfBasicDataList         计量源数据
   * @param measureConfBbaCurrentPeriodMap 经过天数配置_当期
   * @return List<MeasureConfBbaChangeCurrentMaintenanceCost> 维持费用相关_当期计算假设变动数据
   */
  @Override
  public List<MeasureConfBbaChangeCurrentMaintenanceCost> setCxZbMeasureBbaChangeCurrentMaintenanceCost(List<MeasureCfBasicData> measureCfBasicDataList, Map<String, List<MeasureConfBbaCurrentPeriod>> measureConfBbaCurrentPeriodMap) {
    List<MeasureConfBbaChangeCurrentMaintenanceCost> measureConfBbaChangeCurrentMaintenanceCostList = Lists.newArrayList();
    Optional.ofNullable(measureCfBasicDataList).orElse(Lists.newArrayList()).forEach(entity -> {
      //获取精算假设配置表数据 维持费用率 (匹配月 = 当期评估时点)
      BigDecimal maintenanceExpenseRatio = confMeasureActuarialAssumptionCacheService.getConfMeasureActuarialAssumption(entity.getValMethod(), entity.getValMonth(), entity.getClassCode(),
        StringConstant.STRING_NA, StringConstant.STRING_NA, StringConstant.STRING_NA, ConfMeasureActuarialAssumption::getMaintenanceExpenseRatio);
      List<MeasureConfBbaChangeCurrentMaintenanceCost> measureConfBbaChangeCurrentMaintenanceCosts = doChangeCurrentEvaluate(entity, measureConfBbaCurrentPeriodMap.get(entity.getUnitId()), maintenanceExpenseRatio);
      if (CollectionUtil.isNotEmpty(measureConfBbaChangeCurrentMaintenanceCosts)) {
        measureConfBbaChangeCurrentMaintenanceCostList.addAll(measureConfBbaChangeCurrentMaintenanceCosts);
      }
    });
    return measureConfBbaChangeCurrentMaintenanceCostList;
  }

  /**
   * 生成 维持费用相关_期初数据
   *
   * @param measureCfBasicData            计量源数据 (单个计量单元编号）
   * @param confMeasureBaaBeginPeriodList 经过天数配置_期初List (单个计量单元编号）
   * @param maintenanceExpenseRatio       维持费用率
   * @return List<MeasureConfBbaBeginMaintenanceCost> 维持费用相关_期初数据 (单个计量单元编号）
   */
  @Override
  public List<MeasureConfBbaBeginMaintenanceCost> doBeginEvaluate(MeasureCfBasicData measureCfBasicData,
                                                                  List<MeasureConfBbaBeginPeriod> confMeasureBaaBeginPeriodList, BigDecimal maintenanceExpenseRatio) {
    if (CollectionUtil.isEmpty(confMeasureBaaBeginPeriodList)) {
      return Lists.newArrayList();
    }

    //维持费用相关_期初数据List
    List<MeasureConfBbaBeginMaintenanceCost> confMeasureBaaBeginMaintenanceCostList = Lists.newArrayList();
    String valMonth = measureCfBasicData.getValMonth();
    String lastValMonth = measureCfBasicData.getLastValMonth();
    String unitId = measureCfBasicData.getUnitId();
    String riskCode = measureCfBasicData.getRiskCode();
    BigDecimal premiumCny = measureCfBasicData.getPremiumCny();
    String whetherCurPolicy = measureCfBasicData.getWhetherCurPolicy();
    String startDate = measureCfBasicData.getStartDate();
    String evaluateDate = measureCfBasicData.getEvaluateDate();
    String endDate = measureCfBasicData.getEndDate();
    String iniConfirm = measureCfBasicData.getIniConfirm();
    Long term = measureCfBasicData.getTerm();
    String classCode = measureCfBasicData.getClassCode();

    //"如果是否当期新单=1,则=4.保险责任起期
    //如果是否当期新单=0,则=date(year(1.当期评估时点),1,1)"
    String firstValMonth = whetherCurPolicy.equals(StringConstant.STRING_ONE) ? startDate.compareTo(iniConfirm) < 0 ? startDate : iniConfirm
      : whetherCurPolicy.equals(StringConstant.STRING_ZERO) ? DateUtils.beginYearMonth(valMonth, YYYYMMDD) : "";

    //max(7.保险评估起期,9.当期评估时点的期初评估时点)
    String maxEvaluateAndOpeningDateStr = DateUtil.compare(DateUtils.parseDate(evaluateDate), DateUtils.parseDate(firstValMonth)) > NumberConstant.LONG_ZERO ? evaluateDate : firstValMonth;
    // (8.保险责任止期-max(7.保险评估起期,9.当期评估时点的期初评估时点)+1)
    int EndSubMaxDateInt = UtilsCommon.differentDaysByMillisecond(DateUtils.parseDate(endDate), DateUtils.parseDate(maxEvaluateAndOpeningDateStr)) + 1;
    // =4.保费-本币*(max((8.保险责任止期-max(7.保险评估起期,9.当期评估时点的期初评估时点)+1),0)/(8.保险责任止期-7.保险评估起期+1))*对应的维持费用率
    // 备注:(以险类代码、max(保险责任起期,上期评估时点)和评估方法匹配)
    int endSubEvaluateDateInt = UtilsCommon.differentDaysByMillisecond(DateUtils.parseDate(endDate), DateUtils.parseDate(evaluateDate)) + 1;
    BigDecimal divided = BigDecimal.valueOf(Math.max(EndSubMaxDateInt, 0)).divide(BigDecimal.valueOf(endSubEvaluateDateInt), MathContext.DECIMAL128);
    BigDecimal amt = premiumCny.multiply(divided).multiply(maintenanceExpenseRatio).setScale(10, RoundingMode.HALF_UP);

    //=(year(a.保险责任止期)-year(5.当期评估时点的期初评估时点)*12)+month(a.保险责任止期)-month(5.当期评估时点的期初评估时点)
    int dutyMonth = DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(firstValMonth), DateUtils.parseDate(endDate));

    for (MeasureConfBbaBeginPeriod measureConfBbaBeginPeriod : confMeasureBaaBeginPeriodList) {
      MeasureConfBbaBeginMaintenanceCost entity = new MeasureConfBbaBeginMaintenanceCost();
      entity.setValMonth(valMonth);
      entity.setLastValMonth(lastValMonth);
      entity.setUnitId(unitId);
      entity.setRiskCode(riskCode);
      entity.setClassCode(classCode);
      entity.setPremiumCny(premiumCny);
      entity.setWhetherCurPolicy(whetherCurPolicy);
      entity.setStartDate(startDate);
      entity.setEvaluateDate(evaluateDate);
      entity.setEndDate(endDate);
      entity.setFirstValMonth(firstValMonth);
      entity.setTerm(term);
      entity.setAmt(amt);
      entity.setDutyMonth(dutyMonth);
      entity.setDutyPeriod(measureConfBbaBeginPeriod.getDutyPeriod());
      entity.setDutyPeriodValue(amt.multiply(new BigDecimal(measureConfBbaBeginPeriod.getDutyPeriodValue())));
      confMeasureBaaBeginMaintenanceCostList.add(entity);
    }
    return confMeasureBaaBeginMaintenanceCostList;
  }

  /**
   * 生成 维持费用相关_当期数据
   *
   * @param measureCfBasicData              计量源数据 (单个计量单元编号）
   * @param confMeasureBaaCurrentPeriodList 经过天数配置_当期List (单个计量单元编号）
   * @param maintenanceExpenseRatio         维持费用率
   * @return List<MeasureConfBbaCurrentMaintenanceCost> 维持费用相关_当期数据 (单个计量单元编号）
   */
  @Override
  public List<MeasureConfBbaCurrentMaintenanceCost> doCurrentEvaluate(MeasureCfBasicData measureCfBasicData,
                                                                      List<MeasureConfBbaCurrentPeriod> confMeasureBaaCurrentPeriodList, BigDecimal maintenanceExpenseRatio) {
    if (CollectionUtil.isEmpty(confMeasureBaaCurrentPeriodList)) {
      return Lists.newArrayList();
    }
    //维持费用相关_当期List
    List<MeasureConfBbaCurrentMaintenanceCost> confMeasureBaaCurrentMaintenanceCostList = Lists.newArrayList();
    String valMonth = measureCfBasicData.getValMonth();
    String lastValMonth = measureCfBasicData.getLastValMonth();
    String unitId = measureCfBasicData.getUnitId();
    String riskCode = measureCfBasicData.getRiskCode();
    BigDecimal premiumCny = measureCfBasicData.getPremiumCny();
    String startDate = measureCfBasicData.getStartDate();
    String evaluateDate = measureCfBasicData.getEvaluateDate();
    String endDate = measureCfBasicData.getEndDate();
    Long term = measureCfBasicData.getTerm();
    String classCode = measureCfBasicData.getClassCode();

    //max(7.保险评估起期,1.当期评估时点+1) + 1
    Date curValMonthEndDayAddOneDay = DateUtils.addDays(DateUtils.endMonth(valMonth), 1);
    String maxEvaluateAndCurrentDateStr = DateUtil.compare(DateUtils.parseDate(evaluateDate), curValMonthEndDayAddOneDay) > NumberConstant.LONG_ZERO
        ? evaluateDate : DateUtils.parseDateToStr(YYYYMMDD, curValMonthEndDayAddOneDay);
    // (8.保险责任止期-max(7.保险评估起期,1.当期评估时点+1)+1)
    int EndSubMaxDateInt = UtilsCommon.differentDaysByMillisecond(DateUtils.parseDate(endDate), DateUtils.parseDate(maxEvaluateAndCurrentDateStr)) + 1;
    // =4.保费-本币*(max((8.保险责任止期-max(7.保险评估起期,1.当期评估时点+1)+1),0)/(8.保险责任止期-7.保险评估起期+1))*对应的维持费用率
    // 备注:(以险类代码、max(保险责任起期,上期评估时点)和评估方法匹配)    // 备注:(以险类代码、max(保险责任起期,上期评估时点)和评估方法匹配)
    int endSubEvaluateDateInt = UtilsCommon.differentDaysByMillisecond(DateUtils.parseDate(endDate), DateUtils.parseDate(evaluateDate)) + 1;
    BigDecimal divided = BigDecimal.valueOf(Math.max(EndSubMaxDateInt, 0)).divide(BigDecimal.valueOf(endSubEvaluateDateInt), MathContext.DECIMAL128);
    BigDecimal amt = premiumCny.multiply(divided).multiply(maintenanceExpenseRatio).setScale(10, RoundingMode.HALF_UP);

    //=(year(8.保险责任止期)-year(1.当期评估时点)*12)+month(8.保险责任止期)-month(1.当期评估时点)
    int dutyMonth = DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(valMonth), DateUtils.parseDate(endDate));

    for (MeasureConfBbaCurrentPeriod measureConfBbaCurrentPeriod : confMeasureBaaCurrentPeriodList) {
      MeasureConfBbaCurrentMaintenanceCost entity = new MeasureConfBbaCurrentMaintenanceCost();
      entity.setValMonth(valMonth);
      entity.setLastValMonth(lastValMonth);
      entity.setUnitId(unitId);
      entity.setRiskCode(riskCode);
      entity.setClassCode(classCode);
      entity.setPremiumCny(premiumCny);
      entity.setAmt(amt);
      entity.setStartDate(startDate);
      entity.setEvaluateDate(evaluateDate);
      entity.setEndDate(endDate);
      entity.setTerm(term);
      entity.setDutyMonth(dutyMonth);
      entity.setDutyPeriod(measureConfBbaCurrentPeriod.getDutyPeriod());
      entity.setDutyPeriodValue(amt.multiply(new BigDecimal(measureConfBbaCurrentPeriod.getDutyPeriodValue())));
      confMeasureBaaCurrentMaintenanceCostList.add(entity);
    }
    return confMeasureBaaCurrentMaintenanceCostList;
  }

  /**
   * 生成 维持费用相关_当期计算假设变动数据
   *
   * @param measureCfBasicData              计量源数据
   * @param confMeasureBaaCurrentPeriodList 经过天数配置_当期List
   * @param maintenanceExpenseRatio         维持费用率
   * @return List<MeasureConfBbaChangeCurrentMaintenanceCost> 维持费用相关_当期精算假设变动数据
   */
  @Override
  public List<MeasureConfBbaChangeCurrentMaintenanceCost> doChangeCurrentEvaluate(MeasureCfBasicData measureCfBasicData,
                                                                                  List<MeasureConfBbaCurrentPeriod> confMeasureBaaCurrentPeriodList, BigDecimal maintenanceExpenseRatio) {
    if (CollectionUtil.isEmpty(confMeasureBaaCurrentPeriodList)) {
      return Lists.newArrayList();
    }
    //维持费用相关_当期计算假设变动数据List
    List<MeasureConfBbaChangeCurrentMaintenanceCost> confMeasureBaaChangeCurrentMaintenanceCostList = org.apache.commons.compress.utils.Lists.newArrayList();
    String valMonth = measureCfBasicData.getValMonth();
    String unitId = measureCfBasicData.getUnitId();
    String riskCode = measureCfBasicData.getRiskCode();
    BigDecimal premiumCny = measureCfBasicData.getPremiumCny();
    String evaluateDate = measureCfBasicData.getEvaluateDate();
    String endDate = measureCfBasicData.getEndDate();
    Long term = measureCfBasicData.getTerm();
    String classCode = measureCfBasicData.getClassCode();


    //max(7.保险评估起期,1.当期评估时点+1)
    Date curValMonthEndDayAddOneDay = DateUtils.addDays(DateUtils.endMonth(valMonth), 1);
    String maxEvaluateAndCurrentDateStr = DateUtil.compare(DateUtils.parseDate(evaluateDate), curValMonthEndDayAddOneDay) > NumberConstant.LONG_ZERO
        ? evaluateDate : DateUtils.parseDateToStr(YYYYMMDD, curValMonthEndDayAddOneDay);
    // (8.保险责任止期-max(7.保险评估起期,1.当期评估时点+1)+1)
    int EndSubMaxDateInt = UtilsCommon.differentDaysByMillisecond(DateUtils.parseDate(endDate), DateUtils.parseDate(maxEvaluateAndCurrentDateStr)) + 1;
    // =4.保费-本币*(max((8.保险责任止期-max(7.保险评估起期,1.当期评估时点+1)+1),0)/(8.保险责任止期-7.保险评估起期+1))*对应的维持费用率
    // 备注:(以险类代码、当期评估时点和评估方法匹配)
    int endSubEvaluateDateInt = UtilsCommon.differentDaysByMillisecond(DateUtils.parseDate(endDate), DateUtils.parseDate(evaluateDate)) + 1;
    BigDecimal divided = BigDecimal.valueOf(Math.max(EndSubMaxDateInt, 0)).divide(BigDecimal.valueOf(endSubEvaluateDateInt), MathContext.DECIMAL128);
    BigDecimal amt = premiumCny.multiply(divided).multiply(maintenanceExpenseRatio).setScale(10, RoundingMode.HALF_UP);

    //=(year(8.保险责任止期)-year(1.当期评估时点)*12)+month(8.保险责任止期)-month(1.当期评估时点)
    int dutyMonth = DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(valMonth), DateUtils.parseDate(endDate));

    //c.责任期间，责任期间值
    for (MeasureConfBbaCurrentPeriod measureConfBbaCurrentPeriod : confMeasureBaaCurrentPeriodList) {
      MeasureConfBbaChangeCurrentMaintenanceCost entity = new MeasureConfBbaChangeCurrentMaintenanceCost();
      entity.setValMonth(valMonth);
      entity.setUnitId(unitId);
      entity.setRiskCode(riskCode);
      entity.setClassCode(classCode);
      entity.setPremiumCny(premiumCny);
      entity.setAmt(amt);
      entity.setEvaluateDate(evaluateDate);
      entity.setEndDate(endDate);
      entity.setTerm(term);
      entity.setDutyMonth(dutyMonth);
      entity.setDutyPeriod(measureConfBbaCurrentPeriod.getDutyPeriod());
      entity.setDutyPeriodValue(amt.multiply(new BigDecimal(measureConfBbaCurrentPeriod.getDutyPeriodValue())));
      confMeasureBaaChangeCurrentMaintenanceCostList.add(entity);
    }
    return confMeasureBaaChangeCurrentMaintenanceCostList;
  }
}
