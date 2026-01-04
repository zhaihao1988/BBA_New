package com.jdyx.cx.measure.service.impl;

import cn.hutool.core.collection.CollectionUtil;
import cn.hutool.core.date.DateUtil;
import cn.hutool.core.util.StrUtil;
import com.google.common.collect.Lists;
import com.jdyx.common.cache.measure.ConfMeasureActuarialAssumptionCacheService;
import com.jdyx.common.measure.tools.UtilsCommon;
import com.jdyx.cx.measure.service.MeasureBbaCompensationService;
import com.jdyx.measure.api.measure.domain.*;
import com.kevin.common.constant.NumberConstant;
import com.kevin.common.constant.StringConstant;
import com.kevin.common.utils.DateUtils;
import com.kevin.common.utils.reflect.ReflectUtils;
import java.util.Date;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static com.jdyx.common.measure.constant.NumberConstant.LONG_ZERO;

/**
 * 直保Bba赔款相关_期初/当期/当期精算假设变动Service实现类业务层处理
 */
@Slf4j
@RequiredArgsConstructor
@Service
public class MeasureBbaCompensationServiceImpl implements MeasureBbaCompensationService {

  /**
   * 精算假设配置缓存数据服务
   */
  private final ConfMeasureActuarialAssumptionCacheService confMeasureActuarialAssumptionCacheService;

  /**
   * 生成 赔款相关_期初
   *
   * @param measureCfBasicDataList       计量源数据
   * @param measureConfBbaBeginPeriodMap 经过天数配置_期初
   * @return List<MeasureConfBbaBeginCompensation> 赔款相关相关_期初数据
   */
  @Override
  public List<MeasureConfBbaBeginCompensation> setCxZbMeasureBbaBeginCompensation(List<MeasureCfBasicData> measureCfBasicDataList, Map<String, List<MeasureConfBbaBeginPeriod>> measureConfBbaBeginPeriodMap) {
    List<MeasureConfBbaBeginCompensation> measureConfBbaBeginCompensationList = Lists.newArrayList();
    Optional.ofNullable(measureCfBasicDataList).orElse(Lists.newArrayList()).forEach(entity -> {
      //获取精算假设配置表数据 (以险类代码、max(保险责任起期,上期评估时点)和评估方法匹配)
      String maxEvaluateAndLastValMonthStr = DateUtil.compare(DateUtils.parseDate(entity.getStartDate()), DateUtils.endMonth(entity.getLastValMonth())) > LONG_ZERO ?
        entity.getStartDate().substring(0,6) : entity.getLastValMonth().substring(0,6);
      Map<String, Object> assumptionMap = confMeasureActuarialAssumptionCacheService.getConfMeasureActuarialAssumption(entity.getValMethod(), maxEvaluateAndLastValMonthStr, entity.getClassCode(), StringConstant.STRING_NA,
        StringConstant.STRING_NA, StringConstant.STRING_NA);

      List<MeasureConfBbaBeginCompensation> measureConfBbaBeginCompensations = doBeginEvaluate(entity, measureConfBbaBeginPeriodMap.get(entity.getUnitId()), assumptionMap);
      if (CollectionUtil.isNotEmpty(measureConfBbaBeginCompensations)) {
        measureConfBbaBeginCompensationList.addAll(measureConfBbaBeginCompensations);
      }
    });
    return measureConfBbaBeginCompensationList;
  }

  /**
   * 生成 赔款相关相关_当期数据
   *
   * @param measureCfBasicDataList         计量源数据
   * @param measureConfBbaCurrentPeriodMap 经过天数配置_当期
   * @return List<MeasureConfBbaCurrentCompensation> 赔款相关相关_当期数据
   */
  @Override
  public List<MeasureConfBbaCurrentCompensation> setCxZbMeasureBbaCurrentCompensation(List<MeasureCfBasicData> measureCfBasicDataList, Map<String, List<MeasureConfBbaCurrentPeriod>> measureConfBbaCurrentPeriodMap) {
    List<MeasureConfBbaCurrentCompensation> measureConfBbaCurrentCompensationList = Lists.newArrayList();
    Optional.ofNullable(measureCfBasicDataList).orElse(Lists.newArrayList()).forEach(entity -> {
      //获取精算假设配置表数据 (以险类代码、max(保险责任起期,上期评估时点)和评估方法匹配)
      String maxEvaluateAndLastValMonthStr = DateUtil.compare(DateUtils.parseDate(entity.getStartDate()), DateUtils.endMonth(entity.getLastValMonth())) > LONG_ZERO ?
        entity.getStartDate().substring(0,6) : entity.getLastValMonth().substring(0,6);
      Map<String, Object> assumptionMap = confMeasureActuarialAssumptionCacheService.getConfMeasureActuarialAssumption(entity.getValMethod(), maxEvaluateAndLastValMonthStr, entity.getClassCode(), StringConstant.STRING_NA,
        StringConstant.STRING_NA, StringConstant.STRING_NA);

      List<MeasureConfBbaCurrentCompensation> measureConfBbaCurrentCompensations = doCurrentEvaluate(entity, measureConfBbaCurrentPeriodMap.get(entity.getUnitId()), assumptionMap);
      if (CollectionUtil.isNotEmpty(measureConfBbaCurrentCompensations)) {
        measureConfBbaCurrentCompensationList.addAll(measureConfBbaCurrentCompensations);
      }
    });
    return measureConfBbaCurrentCompensationList;
  }

  /**
   * 生成 赔款相关相关_当期计算假设变动数据
   *
   * @param measureCfBasicDataList           计量源数据
   * @param measureConfBbaCurrentPeriodMap   经过天数配置_当期
   * @return List<MeasureConfBbaChangeCurrentCompensation> 赔款相关相关_当期计算假设变动数据
   */
  @Override
  public List<MeasureConfBbaChangeCurrentCompensation> setCxZbMeasureBbaChangeCurrentCompensation(List<MeasureCfBasicData> measureCfBasicDataList, Map<String, List<MeasureConfBbaCurrentPeriod>> measureConfBbaCurrentPeriodMap) {
    List<MeasureConfBbaChangeCurrentCompensation> measureConfBbaChangeCurrentCompensationList = Lists.newArrayList();
    Optional.ofNullable(measureCfBasicDataList).orElse(Lists.newArrayList()).forEach(entity -> {
      //获取精算假设配置表数据 (以险类代码、当期评估时点和评估方法匹配)
      Map<String, Object> assumptionMap = confMeasureActuarialAssumptionCacheService.getConfMeasureActuarialAssumption(entity.getValMethod(), entity.getValMonth(), entity.getClassCode(),
        StringConstant.STRING_NA, StringConstant.STRING_NA, StringConstant.STRING_NA);
      List<MeasureConfBbaChangeCurrentCompensation> measureConfBbaChangeCurrentCompensations = doChangeCurrentEvaluate(entity, measureConfBbaCurrentPeriodMap.get(entity.getUnitId()), assumptionMap);
      if (CollectionUtil.isNotEmpty(measureConfBbaChangeCurrentCompensations)) {
        measureConfBbaChangeCurrentCompensationList.addAll(measureConfBbaChangeCurrentCompensations);
      }
    });
    return measureConfBbaChangeCurrentCompensationList;
  }

  /**
   * 生成 赔款相关相关_期初数据
   *
   * @param basicData                     计量源数据 (单个计量单元编号）
   * @param confMeasureBaaBeginPeriodList 经过天数配置_期初List (单个计量单元编号）
   * @param measureActuarialAssumptionMap 精算假设配置
   * @return List<MeasureConfBbaBeginCompensation> 赔款相关相关_期初数据 (单个计量单元编号）
   */
  @Override
  public List<MeasureConfBbaBeginCompensation> doBeginEvaluate(MeasureCfBasicData basicData, List<MeasureConfBbaBeginPeriod> confMeasureBaaBeginPeriodList, Map<String, Object> measureActuarialAssumptionMap) {

    if (CollectionUtil.isEmpty(confMeasureBaaBeginPeriodList)) {
      return Lists.newArrayList();
    }
    //生成赔款期初配置数据List
    List<MeasureConfBbaBeginCompensation> measureConfBbaBeginCompensationList = new ArrayList<>();
    String valMonth = basicData.getValMonth();
    String lastValMonth = basicData.getLastValMonth();
    String unitId = basicData.getUnitId();
    String riskCode = basicData.getRiskCode();
    BigDecimal premiumCny = basicData.getPremiumCny();
    String whetherCurPolicy = basicData.getWhetherCurPolicy();
    String startDate = basicData.getStartDate();
    String evaluateDate = basicData.getEvaluateDate();
    String endDate = basicData.getEndDate();
    Long term = basicData.getTerm();
    String classCode = basicData.getClassCode();
    String iniConfirm = basicData.getIniConfirm();

    //"如果是否当期新单=1,则=4.保险责任起期
    //如果是否当期新单=0,则=date(year(1.当期评估时点),1,1)"
    String firstValMonth = whetherCurPolicy.equals(StringConstant.STRING_ONE) ? startDate.compareTo(iniConfirm) < 0 ? startDate : iniConfirm
      : whetherCurPolicy.equals(StringConstant.STRING_ZERO) ? DateUtils.beginYearMonth(valMonth, DateUtils.YYYYMMDD) : "";

    //max(7.保险评估起期,9.当期评估时点的期初评估时点)
    String maxEvaluateAndOpeningDateStr = DateUtil.compare(DateUtils.parseDate(evaluateDate), DateUtils.parseDate(firstValMonth)) > LONG_ZERO ? evaluateDate : firstValMonth;
    // =4.保费-本币*(max((8.保险责任止期-max(7.保险评估起期,9.当期评估时点的期初评估时点)+1)/(8.保险责任止期-7.保险评估起期+1),0))*对应的(赔付率*(1+间接理赔费用率))
    // 备注:(以险类代码、max(保险责任起期,上期评估时点)和评估方法匹配)
    int diff1 = UtilsCommon.differentDaysByMillisecond(DateUtils.parseDate(endDate), DateUtils.parseDate(maxEvaluateAndOpeningDateStr)) + 1;
    int diff2 = UtilsCommon.differentDaysByMillisecond(DateUtils.parseDate(endDate), DateUtils.parseDate(evaluateDate)) + 1;
    BigDecimal lossRatio = (BigDecimal) measureActuarialAssumptionMap.get(
        StrUtil.toUnderlineCase(ReflectUtils.getFieldName(ConfMeasureActuarialAssumption::getLossRatio)));
    BigDecimal indirectClaimsExpenseRatio = (BigDecimal) measureActuarialAssumptionMap.get(
        StrUtil.toUnderlineCase(ReflectUtils.getFieldName(ConfMeasureActuarialAssumption::getIndirectClaimsExpenseRatio)));
    BigDecimal divided = BigDecimal.valueOf(diff1).divide(BigDecimal.valueOf(diff2), 10, RoundingMode.DOWN);
    BigDecimal amt = premiumCny.multiply(divided.max(BigDecimal.ZERO))
      .multiply(lossRatio).multiply(BigDecimal.ONE.add(indirectClaimsExpenseRatio));

    //=(year(a.保险责任止期)-year(5.当期评估时点的期初评估时点)*12)+month(a.保险责任止期)-month(5.当期评估时点的期初评估时点)
    int dutyMonth = DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(firstValMonth), DateUtils.parseDate(endDate));

    for (MeasureConfBbaBeginPeriod measureConfBbaBeginPeriod : confMeasureBaaBeginPeriodList) {
      MeasureConfBbaBeginCompensation entity = new MeasureConfBbaBeginCompensation();
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
      measureConfBbaBeginCompensationList.add(entity);
    }
    return measureConfBbaBeginCompensationList;
  }

  /**
   * 生成 赔款相关相关_当期数据
   *
   * @param basicData                       计量源数据 (单个计量单元编号）
   * @param confMeasureBaaCurrentPeriodList 经过天数配置_当期List (单个计量单元编号）
   * @param measureActuarialAssumptionMap   精算假设配置
   * @return List<MeasureConfBbaCurrentCompensation> 赔款相关相关_当期数据 (单个计量单元编号）
   */
  @Override
  public List<MeasureConfBbaCurrentCompensation> doCurrentEvaluate(MeasureCfBasicData basicData, List<MeasureConfBbaCurrentPeriod> confMeasureBaaCurrentPeriodList, Map<String, Object> measureActuarialAssumptionMap) {

    if (CollectionUtil.isEmpty(confMeasureBaaCurrentPeriodList)) {
      return Lists.newArrayList();
    }
    //生成赔款当期配置数据List
    List<MeasureConfBbaCurrentCompensation> measureConfBbaCurrentCompensationList = new ArrayList<>();
    String valMonth = basicData.getValMonth();
    String lastValMonth = basicData.getLastValMonth();
    String unitId = basicData.getUnitId();
    String riskCode = basicData.getRiskCode();
    BigDecimal premiumCny = basicData.getPremiumCny();
    String startDate = basicData.getStartDate();
    String evaluateDate = basicData.getEvaluateDate();
    String endDate = basicData.getEndDate();
    Long term = basicData.getTerm();
    String classCode = basicData.getClassCode();

    //max(7.保险评估起期,1.当期评估时点+1)
    Date curValMonthEndDayAddOneDay = DateUtils.addDays(DateUtils.endMonth(valMonth), 1);
    String maxEvaluateAndCurrentDateStr = DateUtil.compare(DateUtils.parseDate(evaluateDate), curValMonthEndDayAddOneDay) > LONG_ZERO ?
      evaluateDate : DateUtils.parseDateToStr(DateUtils.YYYYMMDD, curValMonthEndDayAddOneDay);
    // =4.保费-本币*(max((8.保险责任止期-max(7.保险评估起期,1.当期评估时点+1)+1)/(8.保险责任止期-7.保险评估起期+1),0))*对应的(赔付率*(1+间接理赔费用率))
    // 备注:(以险类代码、max(保险责任起期,上期评估时点)和评估方法匹配)
    int diff1 = UtilsCommon.differentDaysByMillisecond(DateUtils.parseDate(endDate), DateUtils.parseDate(maxEvaluateAndCurrentDateStr)) + 1;
    int diff2 = UtilsCommon.differentDaysByMillisecond(DateUtils.parseDate(endDate), DateUtils.parseDate(evaluateDate)) + 1;
    BigDecimal lossRatio = (BigDecimal) measureActuarialAssumptionMap.get(
        StrUtil.toUnderlineCase(ReflectUtils.getFieldName(ConfMeasureActuarialAssumption::getLossRatio)));
    BigDecimal indirectClaimsExpenseRatio = (BigDecimal) measureActuarialAssumptionMap.get(
        StrUtil.toUnderlineCase(ReflectUtils.getFieldName(ConfMeasureActuarialAssumption::getIndirectClaimsExpenseRatio)));
    BigDecimal divided = BigDecimal.valueOf(diff1).divide(BigDecimal.valueOf(diff2), 10, RoundingMode.DOWN);
    BigDecimal amt = premiumCny.multiply(divided.max(BigDecimal.ZERO)
      .multiply(lossRatio).multiply(BigDecimal.ONE.add(indirectClaimsExpenseRatio)));

    //=(year(8.保险责任止期)-year(1.当期评估时点)*12)+month(8.保险责任止期)-month(1.当期评估时点)
    int dutyMonth = DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(valMonth), DateUtils.parseDate(endDate));

    for (MeasureConfBbaCurrentPeriod measureConfBbaCurrentPeriod : confMeasureBaaCurrentPeriodList) {
      MeasureConfBbaCurrentCompensation entity = new MeasureConfBbaCurrentCompensation();
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
      measureConfBbaCurrentCompensationList.add(entity);
    }
    return measureConfBbaCurrentCompensationList;
  }

  /**
   * 生成 赔款相关相关_当期计算假设变动数据
   *
   * @param basicData                       计量源数据 (单个计量单元编号）
   * @param confMeasureBaaCurrentPeriodList 经过天数配置_当期List (单个计量单元编号）
   * @param measureActuarialAssumptionMap   精算假设配置
   * @return List<MeasureConfBbaChangeCurrentCompensation> 赔款相关相关_当期精算假设变动数据
   */
  @Override
  public List<MeasureConfBbaChangeCurrentCompensation> doChangeCurrentEvaluate(MeasureCfBasicData basicData, List<MeasureConfBbaCurrentPeriod> confMeasureBaaCurrentPeriodList, Map<String, Object> measureActuarialAssumptionMap) {

    if (CollectionUtil.isEmpty(confMeasureBaaCurrentPeriodList)) {
      return Lists.newArrayList();
    }
    //赔款当期变动配置数据List
    List<MeasureConfBbaChangeCurrentCompensation> measureConfBbaChangeCurrentCompensationList = new ArrayList<>();
    String valMonth = basicData.getValMonth();
    String unitId = basicData.getUnitId();
    String riskCode = basicData.getRiskCode();
    BigDecimal premiumCny = basicData.getPremiumCny();
    String startDate = basicData.getStartDate();
    String evaluateDate = basicData.getEvaluateDate();
    String endDate = basicData.getEndDate();
    Long term = basicData.getTerm();
    String classCode = basicData.getClassCode();

    //max(7.保险评估起期,1.当期评估时点+1)
    Date curValMonthEndDayAddOneDay = DateUtils.addDays(DateUtils.endMonth(valMonth), 1);
    String maxEvaluateAndCurrentDateStr = DateUtil.compare(DateUtils.parseDate(evaluateDate), curValMonthEndDayAddOneDay) > NumberConstant.LONG_ZERO ?
      evaluateDate : DateUtils.parseDateToStr(DateUtils.YYYYMMDD, curValMonthEndDayAddOneDay);
    //==4.保费-本币*((8.保险责任止期-max(7.保险评估起期,1.当期评估时点+1)+1)/(8.保险责任止期-7.保险评估起期+1))*对应的(赔付率*(1+间接理赔费用率))
    // =4.保费-本币*(max((8.保险责任止期-max(7.保险评估起期,1.当期评估时点+1)+1),0)/(8.保险责任止期-7.保险评估起期+1))*对应的(赔付率*(1+间接理赔费用率))   备注:(以险类代码、当期评估时点和评估方法匹配)
    int diff1 = UtilsCommon.differentDaysByMillisecond(DateUtils.parseDate(endDate), DateUtils.parseDate(maxEvaluateAndCurrentDateStr)) + 1;
    int diff2 = UtilsCommon.differentDaysByMillisecond(DateUtils.parseDate(endDate), DateUtils.parseDate(evaluateDate)) + 1;
    BigDecimal lossRatio = (BigDecimal) measureActuarialAssumptionMap.get(
        StrUtil.toUnderlineCase(ReflectUtils.getFieldName(ConfMeasureActuarialAssumption::getLossRatio)));
    BigDecimal indirectClaimsExpenseRatio = (BigDecimal) measureActuarialAssumptionMap.get(
        StrUtil.toUnderlineCase(ReflectUtils.getFieldName(ConfMeasureActuarialAssumption::getIndirectClaimsExpenseRatio)));
    BigDecimal divided = BigDecimal.valueOf(diff1).divide(BigDecimal.valueOf(diff2), 10, RoundingMode.DOWN);
    BigDecimal amt = premiumCny.multiply(divided.max(BigDecimal.ZERO))
        .multiply(lossRatio).multiply(BigDecimal.ONE.add(indirectClaimsExpenseRatio));

    //=(year(8.保险责任止期)-year(1.当期评估时点)*12)+month(8.保险责任止期)-month(1.当期评估时点)
    int dutyMonth = DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(valMonth), DateUtils.parseDate(endDate));

    for (MeasureConfBbaCurrentPeriod measureConfBbaCurrentPeriod : confMeasureBaaCurrentPeriodList) {
      MeasureConfBbaChangeCurrentCompensation entity = new MeasureConfBbaChangeCurrentCompensation();
      entity.setValMonth(valMonth);
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
      measureConfBbaChangeCurrentCompensationList.add(entity);
    }
    return measureConfBbaChangeCurrentCompensationList;
  }
}
