package com.jdyx.cx.measure.service;

import com.jdyx.measure.api.measure.domain.*;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

/**
 * 直保Bba维持费用相关_期初/当期/当期精算假设变动Service业务层处理
 */
public interface MeasureBbaMaintenanceCostService {
  /**
   * 生成 维持费用相关_期初数据
   *
   * @param measureCfBasicDataList       计量源数据
   * @param measureConfBbaBeginPeriodMap 经过天数配置_期初
   * @return List<MeasureConfBbaBeginMaintenanceCost> 维持费用相关_期初数据
   */
  List<MeasureConfBbaBeginMaintenanceCost> setCxZbMeasureBbaBeginMaintenanceCost(List<MeasureCfBasicData> measureCfBasicDataList, Map<String, List<MeasureConfBbaBeginPeriod>> measureConfBbaBeginPeriodMap);

  /**
   * 生成 维持费用相关_当期数据
   *
   * @param measureCfBasicDataList         计量源数据
   * @param measureConfBbaCurrentPeriodMap 经过天数配置_当期
   * @return List<MeasureConfBbaCurrentMaintenanceCost> 维持费用相关_当期数据
   */
  List<MeasureConfBbaCurrentMaintenanceCost> setCxZbMeasureBbaCurrentMaintenanceCost(List<MeasureCfBasicData> measureCfBasicDataList, Map<String, List<MeasureConfBbaCurrentPeriod>> measureConfBbaCurrentPeriodMap);

  /**
   * 生成 维持费用相关_当期计算假设变动数据
   *
   * @param measureCfBasicDataList         计量源数据
   * @param measureConfBbaCurrentPeriodMap 经过天数配置_当期
   * @return List<MeasureConfBbaChangeCurrentMaintenanceCost> 维持费用相关_当期计算假设变动数据
   */
  List<MeasureConfBbaChangeCurrentMaintenanceCost> setCxZbMeasureBbaChangeCurrentMaintenanceCost(List<MeasureCfBasicData> measureCfBasicDataList, Map<String, List<MeasureConfBbaCurrentPeriod>> measureConfBbaCurrentPeriodMap);

  /**
   * 生成 维持费用相关_期初数据
   *
   * @param measureCfBasicData            计量源数据 (单个计量单元编号）
   * @param confMeasureBaaBeginPeriodList 经过天数配置_期初List (单个计量单元编号）
   * @param maintenanceExpenseRatio       维持费用率
   * @return List<MeasureConfBbaBeginMaintenanceCost> 维持费用相关_期初数据 (单个计量单元编号）
   */
  List<MeasureConfBbaBeginMaintenanceCost> doBeginEvaluate(MeasureCfBasicData measureCfBasicData, List<MeasureConfBbaBeginPeriod> confMeasureBaaBeginPeriodList,
                                                           BigDecimal maintenanceExpenseRatio);

  /**
   * 生成 维持费用相关_当期数据
   *
   * @param measureCfBasicData              计量源数据 (单个计量单元编号）
   * @param confMeasureBaaCurrentPeriodList 经过天数配置_当期List (单个计量单元编号）
   * @param maintenanceExpenseRatio         维持费用率
   * @return List<MeasureConfBbaCurrentMaintenanceCost> 维持费用相关_当期数据 (单个计量单元编号）
   */
  List<MeasureConfBbaCurrentMaintenanceCost> doCurrentEvaluate(MeasureCfBasicData measureCfBasicData, List<MeasureConfBbaCurrentPeriod> confMeasureBaaCurrentPeriodList,
                                                               BigDecimal maintenanceExpenseRatio);

  /**
   * 生成 维持费用相关_当期计算假设变动数据
   *
   * @param measureCfBasicData              计量源数据
   * @param confMeasureBaaCurrentPeriodList 经过天数配置_当期List
   * @param maintenanceExpenseRatio         维持费用率
   * @return List<MeasureConfBbaChangeCurrentMaintenanceCost> 维持费用相关_当期精算假设变动数据
   */
  List<MeasureConfBbaChangeCurrentMaintenanceCost> doChangeCurrentEvaluate(MeasureCfBasicData measureCfBasicData, List<MeasureConfBbaCurrentPeriod> confMeasureBaaCurrentPeriodList,
                                                                           BigDecimal maintenanceExpenseRatio);
}
