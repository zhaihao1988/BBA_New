package com.jdyx.cx.measure.strategy;

import com.jdyx.common.enums.EvaluateMethodTypeEnum;
import com.jdyx.measure.api.measure.domain.MeasureCfBasicData;
import com.jdyx.measure.api.measure.domain.MeasureCfResultInfo;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;

/**
 * 获取 计量模型基础数据
 *
 * @author 刘瑞奎.
 * @date 2024/10/21.
 */
public interface MeasureCfResultInfoStrategy {

  /**
   * 获取 计量明细计算策略方法
   *
   * @param measureCfBasicDataList 计量源数据
   * @param evaluateMethod 评估方法 {@link EvaluateMethodTypeEnum}
   * @param valMonth 评估时点 计量明细数据
   * @author kevin.
   * @date 2024/10/21.
   */
  void doOperation(List<MeasureCfBasicData> measureCfBasicDataList, EvaluateMethodTypeEnum evaluateMethod, String valMonth, CountDownLatch latch);

  /**
   * 获取 计量明细计算策略方法
   *
   * @param measureCfBasicDataList 计量源数据
   * @param evaluateMethod 评估方法 {@link EvaluateMethodTypeEnum}
   * @param valMonth 评估时点 计量明细数据
   * @author kevin.
   * @date 2024/10/21.
   */
  void doOperation(List<MeasureCfBasicData> measureCfBasicDataList, EvaluateMethodTypeEnum evaluateMethod, String valMonth);

}
