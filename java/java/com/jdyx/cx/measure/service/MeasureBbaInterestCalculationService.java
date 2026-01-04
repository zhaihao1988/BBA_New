package com.jdyx.cx.measure.service;

import com.jdyx.measure.api.measure.domain.MeasureCfBasicData;
import com.jdyx.measure.api.measure.domain.MeasureConfBbaBeginInterestCalculation;
import com.jdyx.measure.api.measure.domain.MeasureConfBbaCurrentInterestCalculation;

import java.util.List;

/**
 * 直保Bba计息日期配置表_当期/期初Service业务层处理
 */
public interface MeasureBbaInterestCalculationService {
  /**
   * @param measureCfBasicDataList 计量基础数据
   * @return 期初计息日期配置list
   * @Author hzh
   * @date 2024/11/5
   */
  List<MeasureConfBbaBeginInterestCalculation> setCxZbMeasureBbaBeginInterestCalculation(List<MeasureCfBasicData> measureCfBasicDataList);

  /**
   * @param measureCfBasicDataList 计量基础数据
   * @return 当期计息日期配置list
   * @Author hzh
   * @date 2024/11/5
   */
  List<MeasureConfBbaCurrentInterestCalculation> setCxZbMeasureBbaCurrentInterestCalculation(List<MeasureCfBasicData> measureCfBasicDataList);

  /**
   * @param basicData 计量基础数据（单个计量单元编号）
   * @return 当期计息日期配置list（单个计量单元编号）
   * @Author hzh
   * @date 2024/11/5
   */
  List<MeasureConfBbaCurrentInterestCalculation> doCurrentEvaluate(MeasureCfBasicData basicData);

  /**
   * @param basicData 计量基础数据（单个计量单元编号）
   * @return 期初计息日期配置list（单个计量单元编号）
   * @Author hzh
   * @date 2024/11/5
   */
  List<MeasureConfBbaBeginInterestCalculation> doBeginEvaluate(MeasureCfBasicData basicData);

  /**
   * @param valMonth   当期评估时点的期初评估时点 / 当期评估时点
   * @param endDate    保险责任止期
   * @param dutyPeriod 责任期间
   * @param dutyMonth  责任月份
   * @return 返回值描述
   * @Author hzh
   * @date 2024/11/5
   */
  String getDutyPeriodValue(int dutyPeriod, int dutyMonth, String endDate, String valMonth);
}
