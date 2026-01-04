package com.jdyx.cx.measure.service;

import com.jdyx.common.enums.RiOrPiTypeEnum;
import com.kevin.common.core.domain.R;

/**
 * 计量服务(产险直保)
 *
 * @author kevin.
 * @date 2024/2/4.
 */
public interface MeasureCxBbaService {
  /**
   * - BBA核心计量计算
   *
   * @param valMethod 评估方法，默认BBA-7
   * @param valMonth 评估月
   * @return 返回值描述
   * @Author cjn
   * @date 2024/12/26
   */
  R<?> setCxMeasureResultBbaCore(String valMethod, String valMonth);
}
