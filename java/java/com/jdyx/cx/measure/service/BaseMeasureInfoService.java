package com.jdyx.cx.measure.service;

import com.baomidou.mybatisplus.core.toolkit.support.SFunction;
import com.baomidou.mybatisplus.extension.conditions.query.LambdaQueryChainWrapper;
import com.google.common.collect.Maps;
import com.jdyx.common.measure.service.SuperBaseService;
import com.jdyx.measure.api.measure.domain.MeasureCfResultInfo;
import com.jdyx.measure.api.measure.mapper.MeasureCfBasicDataMapper;
import com.jdyx.measure.api.measure.mapper.MeasureCfResultInfoMapper;
import com.kevin.common.utils.EntityFieldValueGetterUtils;
import com.kevin.common.utils.StringUtils;
import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Collectors;
import javax.annotation.Resource;
import lombok.extern.slf4j.Slf4j;

/**
 * 计量明细 基类
 *
 * @author kevin.
 * @date 2024/2/6.
 */
@SuppressWarnings({"DuplicatedCode", "LambdaBodyCanBeCodeBlock"})
@Slf4j
public abstract class BaseMeasureInfoService extends SuperBaseService {

  /** 计量明细结果Mapper接口 */
  @Resource
  protected MeasureCfResultInfoMapper measureCfResultInfoMapper;

  @Resource
  protected MeasureCfBasicDataMapper measureCfBasicDataMapper;


  /**
   * 获取 计量明细数据.
   *
   * @param valMonth 评估时点(yyyyMM).
   * @param evaluateMethod 评估方法.
   * @return 计量单元编号分组.
   */
  protected BigDecimal getMeasureCfBasicDataMapMap(String valMonth, String evaluateMethod, String unitId, String variableName) {
    //实际现金流
    List<MeasureCfResultInfo> infoList = new LambdaQueryChainWrapper<>(measureCfResultInfoMapper)
      //1.评估时点
      .eq(MeasureCfResultInfo::getValMonth, valMonth)
      //2.评估方法
      .eq(MeasureCfResultInfo::getValMethod, evaluateMethod)
      //3.计量单元编号
      .eq(MeasureCfResultInfo::getUnitId, unitId).list();
    //对数据按照计量单元编号 进行分组
    return StringUtils.isNotEmpty(infoList) ? (BigDecimal) EntityFieldValueGetterUtils.getVariableValue(infoList.get(0), variableName) : BigDecimal.ZERO;
  }

  /**
   * 获取 计量明细数据汇总结果.
   *
   * @param valMonth 评估时点(yyyyMM).
   * @param evaluateMethod 评估方法.
   * @return 合同分组编号.
   */
  protected final Map<String, MeasureCfResultInfo> getMeasureCfBasicDataMapMap(String valMonth, String evaluateMethod, String csmGroupNo, SFunction<MeasureCfResultInfo, ?> column) {
    //实际现金流
    List<MeasureCfResultInfo> infoList = new LambdaQueryChainWrapper<>(measureCfResultInfoMapper).select(column)
      //1.评估时点
      .eq(MeasureCfResultInfo::getValMonth, valMonth).eq(MeasureCfResultInfo::getGroupId, csmGroupNo)
      //2.评估方法
      .eq(MeasureCfResultInfo::getValMethod, evaluateMethod).list();
    //对数据按照计量单元编号 进行分组
    return Optional.of(infoList.stream().collect(Collectors.toMap(MeasureCfResultInfo::getGroupId, e -> e, (v1, v2) -> v1))).orElse(Maps.newHashMap());
  }


}
