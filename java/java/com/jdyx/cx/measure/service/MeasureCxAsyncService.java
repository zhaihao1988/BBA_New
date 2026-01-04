package com.jdyx.cx.measure.service;

import com.kevin.common.core.domain.R;

/**
 * 未到期计量
 *
 * @author kevin.
 * @date 2024/2/4.
 */
public interface MeasureCxAsyncService {

  /**
   *
   * @param valMethod 评估方法
   * @param valMonth 评估月
   * @return r
   */
  R<?> getUnexpiredMeasureResult(String valMethod, String valMonth);
}
