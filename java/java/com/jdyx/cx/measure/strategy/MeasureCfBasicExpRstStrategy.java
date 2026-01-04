package com.jdyx.cx.measure.strategy;

import com.jdyx.measure.api.measure.domain.MeasureCfBbaExpRst;
import com.jdyx.measure.api.measure.domain.MeasureCfResultInfo;

import java.text.ParseException;
import java.util.List;

/**
 * @author hzh
 * @version 1.0
 * @description: 获取预期现金流数据
 * @date 2024/11/7
 */
public interface MeasureCfBasicExpRstStrategy {

  List<MeasureCfBbaExpRst> doOperation(List<MeasureCfResultInfo> list, String evaluateMethod, String valMonth) throws ParseException;
}
