package com.jdyx.cx.measure.strategy;

import com.jdyx.common.enums.EvaluateMethodTypeEnum;
import com.jdyx.measure.api.measure.domain.MeasureCfBasicData;
import com.jdyx.measure.api.measure.domain.MeasureConfCommonClaim;
import java.util.List;

/**
 * @author 郭文斌.
 * @date 2024/11/16.
 * @description 理赔配置计算策略.
 */
public interface MeasureConfCommonClaimStrategy {

  /**
   * 计算方法.
   *
   * @param measureCfBasicDataList 基础数据
   * @param evaluateMethod 评估方法
   * @param valMonth 评估月份
   * @return java.util.List<com.jdyx.measure.api.measure.domain.MeasureConfCommonClaim>
   * @author 郭文斌.
   * @date 2024/11/16.
   */
  List<MeasureConfCommonClaim> doOperation(List<MeasureCfBasicData> measureCfBasicDataList, EvaluateMethodTypeEnum evaluateMethod, String valMonth);
}
