package com.jdyx.cx.measure.service;

import com.kevin.common.core.domain.R;

/**
 * 未到期计量
 *
 * @author cjn
 * @date 2025/7/23.
 */
public interface MeasureCxGdqLrcService {

  /**
   * 未到期计量
   * @param valMethod 评估方法
   * @param valMonth 评估月
   * @return r
   */
  R<?> getUnexpiredMeasureResult(String valMethod, String valMonth);

}
