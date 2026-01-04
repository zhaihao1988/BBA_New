package com.jdyx.cx.measure.strategy;

import com.jdyx.measure.api.measure.domain.MeasureCfBasicData;
import com.jdyx.measure.api.measure.domain.MeasureCfBbaBasicCalcRst;
import com.jdyx.measureprepare.api.domain.TPpJlClmSettled;
import com.jdyx.measureprepare.api.domain.vo.TPpJlActualRecPayPremFeeVo;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

public interface MeasureCfBbaBasicCalcRstStrategy {
  List<MeasureCfBbaBasicCalcRst> doOperation(List<MeasureCfBasicData> measureCfBasicDataList, String valMethod, String valMonth);
}
