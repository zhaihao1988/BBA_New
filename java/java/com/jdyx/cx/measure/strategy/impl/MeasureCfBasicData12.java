package com.jdyx.cx.measure.strategy.impl;

import com.jdyx.common.enums.EvaluateMethodTypeEnum;
import com.jdyx.cx.measure.strategy.MeasureCfBasicStrategy;
import com.jdyx.measure.api.measure.domain.MeasureCfBasicData;
import java.util.Collections;
import java.util.List;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

/**
 * 产险-直保-PAA
 *
 * @author 刘瑞奎.
 * @date 2024/10/21.
 */
@SuppressWarnings("DuplicatedCode")
@Slf4j
@RequiredArgsConstructor
@Service
public class MeasureCfBasicData12 implements MeasureCfBasicStrategy {

  /**
   * 获取 计量模型基础数据策略方法
   *
   * @param evaluateMethod 评估方法 {@link EvaluateMethodTypeEnum}
   * @param valMonth 评估时点(yyyyMM)
   * @return java.util.List<com.jdyx.measure.api.measure.domain.MeasureCfBasicData>
   * @author kevin.
   * @date 2024/10/21.
   */
  @Override
  public void doOperation(EvaluateMethodTypeEnum evaluateMethod, String valMonth) {

//    return Collections.emptyList();
  }
}
