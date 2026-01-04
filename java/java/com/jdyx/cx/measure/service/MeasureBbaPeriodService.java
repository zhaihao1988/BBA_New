package com.jdyx.cx.measure.service;

import com.jdyx.measure.api.measure.domain.MeasureCfBasicData;
import com.jdyx.measure.api.measure.domain.MeasureConfBbaBeginPeriod;
import com.jdyx.measure.api.measure.domain.MeasureConfBbaCurrentPeriod;

import java.util.List;

/**
 * 直保Bba经过天数配置表_当期/期初Service业务层处理
 */
public interface MeasureBbaPeriodService {
  /**
   *
   * @param measureCfBasicDataList 计量基础数据
   * @return 期初经过天数配置list
   * @Author hzh
   * @date 2024/11/5
   */
  List<MeasureConfBbaBeginPeriod> setCxZbMeasureBbaBeginPeriod(List<MeasureCfBasicData> measureCfBasicDataList);

  /**
   *
   * @param measureCfBasicDataList 计量基础数据
   * @return 当期经过天数配置list
   * @Author hzh
   * @date 2024/11/5
   */
  List<MeasureConfBbaCurrentPeriod> setCxZbMeasureBbaCurrentPeriod(List<MeasureCfBasicData> measureCfBasicDataList);

  /**
   *
   * @param basicData 计量基础数据（单个计量单元编号）
   * @return 当期经过天数配置list（单个计量单元编号）
   * @Author hzh
   * @date 2024/11/5
   */
  List<MeasureConfBbaCurrentPeriod> doCurrentEvaluate(MeasureCfBasicData basicData);

  /**
   *
   * @param basicData 计量基础数据（单个计量单元编号）
   * @return 期初经过天数配置list（单个计量单元编号）
   * @Author hzh
   * @date 2024/11/5
   */
  List<MeasureConfBbaBeginPeriod> doBeginEvaluate(MeasureCfBasicData basicData);

  /**
   * 经过天数配置
   *
   * @param judgeMonth 判断时点
   * @param warrantyPeriod 保修期
   * @param dutyPeriod 责任期间
   * @param dutyMonth 责任月份
   * @param endDate 保险责任止期
   * @param evaluateDate 评估时点
   * @return 该经过天数的值
   * @Author hzh
   * @date 2024/11/5
   */
  String getDutyPeriodValue(int dutyPeriod, int dutyMonth, int warrantyPeriod, String judgeMonth, String endDate, String evaluateDate);
}
