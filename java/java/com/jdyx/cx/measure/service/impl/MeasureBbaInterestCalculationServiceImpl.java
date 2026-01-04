package com.jdyx.cx.measure.service.impl;

import cn.hutool.core.date.DateUtil;
import com.jdyx.common.measure.constant.StringConstant;
import com.jdyx.cx.measure.service.MeasureBbaInterestCalculationService;
import com.jdyx.measure.api.measure.domain.MeasureCfBasicData;
import com.jdyx.measure.api.measure.domain.MeasureConfBbaBeginInterestCalculation;
import com.jdyx.measure.api.measure.domain.MeasureConfBbaCurrentInterestCalculation;
import com.kevin.common.utils.DateUtils;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.compress.utils.Lists;
import org.springframework.stereotype.Service;

import java.util.*;

/**
 * 直保Bba计息日期配置表_当期/期初Service实现类业务层处理
 */
@Slf4j
@RequiredArgsConstructor
@Service
public class MeasureBbaInterestCalculationServiceImpl implements MeasureBbaInterestCalculationService {
  /**
   * @param measureCfBasicDataList 计量基础数据
   * @return 期初计息日期配置list
   * @Author hzh
   * @date 2024/11/5
   */
  @Override
  public List<MeasureConfBbaBeginInterestCalculation> setCxZbMeasureBbaBeginInterestCalculation(List<MeasureCfBasicData> measureCfBasicDataList) {
    List<MeasureConfBbaBeginInterestCalculation> measureConfBbaBeginInterestCalculationList = Lists.newArrayList();
    Optional.ofNullable(measureCfBasicDataList).orElse(Lists.newArrayList()).forEach(entity -> {
      List<MeasureConfBbaBeginInterestCalculation> measureConfBbaBeginInterestCalculations = doBeginEvaluate(entity);
      measureConfBbaBeginInterestCalculationList.addAll(measureConfBbaBeginInterestCalculations);
    });
    return measureConfBbaBeginInterestCalculationList;
  }

  /**
   * @param measureCfBasicDataList 计量基础数据
   * @return 当期计息日期配置list
   * @Author hzh
   * @date 2024/11/5
   */
  @Override
  public List<MeasureConfBbaCurrentInterestCalculation> setCxZbMeasureBbaCurrentInterestCalculation(List<MeasureCfBasicData> measureCfBasicDataList) {
    List<MeasureConfBbaCurrentInterestCalculation> measureConfBbaCurrentInterestCalculationList = Lists.newArrayList();
    Optional.ofNullable(measureCfBasicDataList).orElse(Lists.newArrayList()).forEach(entity -> {
      List<MeasureConfBbaCurrentInterestCalculation> measureConfBbaCurrentInterestCalculations = doCurrentEvaluate(entity);
      measureConfBbaCurrentInterestCalculationList.addAll(measureConfBbaCurrentInterestCalculations);
    });
    return measureConfBbaCurrentInterestCalculationList;
  }

  /**
   * -
   *
   * @param basicData 计量基础数据（单个计量单元编号）
   * @return 当期计息日期配置list（单个计量单元编号）
   * @Author hzh
   * @date 2024/11/5
   */
  public List<MeasureConfBbaCurrentInterestCalculation> doCurrentEvaluate(MeasureCfBasicData basicData) {
    ArrayList<MeasureConfBbaCurrentInterestCalculation> resList = new ArrayList<>();
    String valMonth = basicData.getValMonth();
    String unitId = basicData.getUnitId();
    String riskCode = basicData.getRiskCode();
    String evaluateDate = basicData.getEvaluateDate();
    String endDate = basicData.getEndDate();

    //=(year(5.保险责任止期)-year(1.当期评估时点)*12)+month(5.保险责任止期)-month(1.当期评估时点)
    int dutyMonth = DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(valMonth), DateUtils.parseDate(endDate));

    for (int i = 1; i <= dutyMonth + 1; i++) {
      MeasureConfBbaCurrentInterestCalculation entity = new MeasureConfBbaCurrentInterestCalculation();
      entity.setValMonth(valMonth);
      entity.setUnitId(unitId);
      entity.setRiskCode(riskCode);
      entity.setEvaluateDate(evaluateDate);
      entity.setEndDate(endDate);
      entity.setDutyMonth(dutyMonth);
      entity.setDutyPeriod(i);
      entity.setDutyPeriodValue(getDutyPeriodValue(i, dutyMonth, endDate, valMonth));
      resList.add(entity);
    }
    return resList;
  }

  /**
   * -
   *
   * @param basicData 计量基础数据（单个计量单元编号）
   * @return 期初计息日期配置list（单个计量单元编号）
   * @Author hzh
   * @date 2024/11/5
   */
  public List<MeasureConfBbaBeginInterestCalculation> doBeginEvaluate(MeasureCfBasicData basicData) {
    ArrayList<MeasureConfBbaBeginInterestCalculation> resList = new ArrayList<>();
    String valMonth = basicData.getValMonth();
    String unitId = basicData.getUnitId();
    String riskCode = basicData.getRiskCode();
    String startDate = basicData.getStartDate();
    String evaluateDate = basicData.getEvaluateDate();
    String endDate = basicData.getEndDate();
    String iniConfirm = basicData.getIniConfirm();
    String whetherCurPolicy = basicData.getWhetherCurPolicy();

    //'如果是否当期新单=1,则=4.保险责任起期
    //如果是否当期新单=0,则=date(year(1.当期评估时点),1,1)
    String firstValMonth = StringConstant.STRING_ONE.equals(whetherCurPolicy) ? startDate.compareTo(iniConfirm) < 0 ? startDate : iniConfirm
      : DateUtils.beginYearMonth(valMonth, DateUtils.YYYYMMDD);

    //=(YEAR(保险责任止期)-YEAR(当当期评估时点的期初评估时点)*12)+MONTH(保险责任止期)-MONTH(当期评估时点的期初评估时点)
    int dutyMonth = DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(firstValMonth), DateUtils.parseDate(endDate));

    for (int i = 1; i <= dutyMonth +1 ; i++) {
      MeasureConfBbaBeginInterestCalculation entity = new MeasureConfBbaBeginInterestCalculation();
      entity.setValMonth(valMonth);
      entity.setUnitId(unitId);
      entity.setRiskCode(riskCode);
      entity.setStartDate(startDate);
      entity.setEvaluateDate(evaluateDate);
      entity.setEndDate(endDate);
      entity.setWhetherCurPolicy(whetherCurPolicy);
      entity.setFirstValMonth(firstValMonth);
      entity.setDutyMonth(dutyMonth);
      entity.setDutyPeriod(i);
      entity.setDutyPeriodValue(getDutyPeriodValue(i, dutyMonth, endDate, firstValMonth));
      resList.add(entity);
    }
    return resList;
  }

  /**
   * -
   *
   * @param valMonth   当期评估时点的期初评估时点 / 当期评估时点
   * @param endDate    保险责任止期
   * @param dutyPeriod 责任期间
   * @param dutyMonth  责任月份
   * @return 返回值描述
   * @Author hzh
   * @date 2024/11/5
   */
  public String getDutyPeriodValue(int dutyPeriod, int dutyMonth, String endDate, String valMonth) {
    if (dutyPeriod > dutyMonth + 1) {
      return StringConstant.STRING_ZERO;
    }
    if (dutyMonth == 0) {
      return endDate;
    }
    if (dutyMonth > 0) {
      if (dutyPeriod < dutyMonth + 1) {
        int valMonthYear = DateUtil.year(DateUtils.parseDate(valMonth));
        int valMonthMonth = DateUtil.month(DateUtils.parseDate(valMonth));
        int valMonthDay = 1;
        int newValMonthMonth = (valMonthMonth + dutyPeriod) % 12;
        int newValMonthYear = valMonthYear + (valMonthMonth + dutyPeriod) / 12;
        String dateString = String.format("%04d-%02d-%02d", newValMonthYear, newValMonthMonth + 1, valMonthDay);
        Date newvalMonth = DateUtils.parseDate(dateString);
        newvalMonth = DateUtils.addDays(newvalMonth, -1);
        return DateUtils.parseDateToStr(DateUtils.YYYYMMDD, newvalMonth);
      }
      return endDate;
    }
    return StringConstant.STRING_ZERO;
  }
}
