package com.jdyx.cx.measure.service;

import com.kevin.common.core.domain.R;

/**
 * 未到期计量
 *
 * @author cjn
 * @date 2025/7/23.
 */
public interface MeasureCxDataService {

  /**
   * 未到期计量-直保计量源数据
   * @param valMethod 评估方法
   * @param valMonth 评估月
   * @return r
   */
  R<?> setUnexpiredMeasureData(String valMethod, String valMonth);

}
