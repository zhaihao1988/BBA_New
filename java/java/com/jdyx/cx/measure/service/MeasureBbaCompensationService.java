package com.jdyx.cx.measure.service;

import com.jdyx.measure.api.measure.domain.*;

import java.util.List;
import java.util.Map;

/**
 * 直保Bba赔款相关_期初/当期/当期精算假设变动Service业务层处理
 */
public interface MeasureBbaCompensationService {
  /**
   * 生成 赔款相关_期初
   *
   * @param measureCfBasicDataList         计量源数据
   * @param measureConfBbaCurrentPeriodMap 经过天数配置_期初
   * @return List<MeasureConfBbaBeginCompensation> 赔款相关相关_期初数据
   */
  List<MeasureConfBbaBeginCompensation> setCxZbMeasureBbaBeginCompensation(List<MeasureCfBasicData> measureCfBasicDataList, Map<String, List<MeasureConfBbaBeginPeriod>> measureConfBbaCurrentPeriodMap);

  /**
   * 生成 赔款相关相关_当期数据
   *
   * @param measureCfBasicDataList         计量源数据
   * @param measureConfBbaCurrentPeriodMap 经过天数配置_当期
   * @return List<MeasureConfBbaCurrentCompensation> 赔款相关相关_当期数据
   */
  List<MeasureConfBbaCurrentCompensation> setCxZbMeasureBbaCurrentCompensation(List<MeasureCfBasicData> measureCfBasicDataList, Map<String, List<MeasureConfBbaCurrentPeriod>> measureConfBbaCurrentPeriodMap);

  /**
   * 生成 赔款相关相关_当期计算假设变动数据
   *
   * @param measureCfBasicDataList           计量源数据
   * @param measureConfBbaCurrentPeriodMap   经过天数配置_当期
   * @return List<MeasureConfBbaChangeCurrentCompensation> 赔款相关相关_当期计算假设变动数据
   */
  List<MeasureConfBbaChangeCurrentCompensation> setCxZbMeasureBbaChangeCurrentCompensation(List<MeasureCfBasicData> measureCfBasicDataList, Map<String, List<MeasureConfBbaCurrentPeriod>> measureConfBbaCurrentPeriodMap);

  /**
   * 生成 赔款相关相关_期初数据
   *
   * @param measureCfBasicData            计量源数据 (单个计量单元编号）
   * @param confMeasureBaaBeginPeriodList 经过天数配置_期初List (单个计量单元编号）
   * @param measureActuarialAssumptionMap 精算假设配置
   * @return List<MeasureConfBbaBeginCompensation> 赔款相关相关_期初数据 (单个计量单元编号）
   */
  List<MeasureConfBbaBeginCompensation> doBeginEvaluate(MeasureCfBasicData measureCfBasicData, List<MeasureConfBbaBeginPeriod> confMeasureBaaBeginPeriodList,
                                                        Map<String, Object> measureActuarialAssumptionMap);

  /**
   * 生成 赔款相关相关_当期数据
   *
   * @param measureCfBasicData              计量源数据 (单个计量单元编号）
   * @param confMeasureBaaCurrentPeriodList 经过天数配置_当期List (单个计量单元编号）
   * @param measureActuarialAssumptionMap   精算假设配置
   * @return List<MeasureConfBbaCurrentCompensation> 赔款相关相关_当期数据 (单个计量单元编号）
   */
  List<MeasureConfBbaCurrentCompensation> doCurrentEvaluate(MeasureCfBasicData measureCfBasicData, List<MeasureConfBbaCurrentPeriod> confMeasureBaaCurrentPeriodList,
                                                            Map<String, Object> measureActuarialAssumptionMap);

  /**
   * 生成 赔款相关相关_当期计算假设变动数据
   *
   * @param measureCfBasicData              计量源数据 (单个计量单元编号）
   * @param confMeasureBaaCurrentPeriodList 经过天数配置_当期List (单个计量单元编号）
   * @param measureActuarialAssumptionMap   精算假设配置
   * @return List<MeasureConfBbaChangeCurrentCompensation> 赔款相关相关_当期精算假设变动数据
   */
  List<MeasureConfBbaChangeCurrentCompensation> doChangeCurrentEvaluate(MeasureCfBasicData measureCfBasicData, List<MeasureConfBbaCurrentPeriod> confMeasureBaaCurrentPeriodList,
                                                                        Map<String, Object> measureActuarialAssumptionMap);
}
