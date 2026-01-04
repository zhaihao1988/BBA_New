package com.jdyx.cx.measure.service;

import com.kevin.common.core.domain.R;

/**
 * 计量平台2.0
 *
 * @author kevin.
 * @date 2024/2/4.
 */
public interface MeasureCxLicUnsettledService {

  /**
   *
   * @param valMethod 评估方法
   * @param valMonth 评估月
   * @return r
   */
  R<?> getUnsettledMeasureResult(String valMethod, String valMonth);

}
