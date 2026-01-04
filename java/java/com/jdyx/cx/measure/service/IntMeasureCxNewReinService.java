package com.jdyx.cx.measure.service;

import com.kevin.common.core.domain.R;

import java.io.IOException;

/**
 * 未到期计量
 *
 * @author kevin.
 * @date 2024/2/4.
 */
public interface IntMeasureCxNewReinService {

  /**
   *
   * @param valMethod 评估方法
   * @param valMonth 评估月
   * @return r
   */
  R<?> getGdqLrcReinInMeasureResult(String valMethod, String valMonth);

  R<?> getGdqLrcReinOutMeasureResult(String valMethod, String valMonth) throws IOException;

  R<?> getLrcReinInMeasureByMonthResult(String valMethod, String valMonth);

  R<?> getLrcReinOutMeasureByMonthResult(String valMethod, String valMonth) throws IOException;

//  R<?> setMeasureLrcLeReinByMonthResult(String valMonth);
}
