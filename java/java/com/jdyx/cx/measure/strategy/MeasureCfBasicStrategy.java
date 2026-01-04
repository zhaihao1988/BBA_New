package com.jdyx.cx.measure.strategy;

import com.jdyx.common.enums.EvaluateMethodTypeEnum;
import com.jdyx.measure.api.measure.domain.MeasureCfBasicData;
import java.util.List;

/**
 * 获取 计量模型基础数据
 *
 * @author 刘瑞奎.
 * @date 2024/10/21.
 */
public interface MeasureCfBasicStrategy {

  /**
   * 获取 计量模型基础数据策略方法
   *
   * @param evaluateMethod 评估方法 {@link EvaluateMethodTypeEnum}
   * @param valMonth 评估时点(yyyyMM)
   * @author kevin.
   * @date 2024/10/21.
   */
  void doOperation(EvaluateMethodTypeEnum evaluateMethod, String valMonth);

}
