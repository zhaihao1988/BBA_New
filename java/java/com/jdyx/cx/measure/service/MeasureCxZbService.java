package com.jdyx.cx.measure.service;

import com.jdyx.measure.api.measure.domain.MeasureResultCheckLicBo;
import com.jdyx.measure.api.measure.domain.MeasureResultCheckLicVo;
import com.kevin.common.core.domain.PageQuery;
import com.kevin.common.core.domain.R;
import com.kevin.common.core.page.TableDataInfo;

import java.text.ParseException;

/**
 * 计量服务(产险直保)
 *
 * @author kevin.
 * @date 2024/2/4.
 */
public interface MeasureCxZbService {

  /**
   * 1.获取(产险直保PAA/BBA) 获取基础数据
   *
   * @param valMethod 评估方法(1-BBA,2-PBBA,3-VFA,4-PAA)
   * @param valMonth 评估月
   * @return r
   */
  R<?> setCxPiMeasureCfBasicDataRst(String valMethod, String valMonth);


  /**
   * 2.计算(产险直保/再保PAA)  PAA当期计量明细
   *
   * @param valMethod 评估方法(1-BBA,2-PBBA,3-VFA,4-PAA)
   * @param valMonth 评估时点(yyyyMM)
   * @return r
   */
  void setCxPiPaaMeasureCfResultInfoRst(String valMethod, String valMonth);


  /**
   * 3.计量(产险直保/再保PAA) 获取未决CASE等数据写入实际现金流表中
   *
   * @param valMethod 评估方法
   * @param valMonth 评估时点
   * @return r
   */
  R<?> setCxPiPaaCfBasicCalcRst(String valMethod, String valMonth);

  /***
   * @description: 输送至分摊平台
   * @param evaluateMethod 评估方法，当前仅直保PAA
   * @param valMonth 评估月
   * @author hzh
   * @date 2024/10/23
   */
  R<?> setCxZbResultAllocation(String evaluateMethod, String valMonth);

  /**
   * 2.计算(产险直保BBA)  当期计量明细
   *
   * @param valMethod 评估方法(1-BBA,2-PBBA,3-VFA,4-PAA)
   * @param valMonth 评估时点(yyyyMM)
   * @return r
   */
  R<?>  setCxPiBbaMeasureCfResultInfoRst(String valMethod, String valMonth);

  /**
   * 3.计算明细计量汇总写入预期现金流表
   *
   * @param valMethod 评估方法
   * @param valMonth 评估时点
   * @return r
   */
  void setCxInfoToCfBasicExpRst(String valMethod, String valMonth);

  /**
   * 3.计量核算表
   *
   * @param valMethod 评估方法
   * @param valMonth 评估时点
   * @return r
   */
  R<?> setCxMeasureResultCheck(String valMethod, String valMonth);

  /**
   * - 直保BBA 计算明细计量汇总写入预期现金流表（2.0）
   *
   * @Author hzh
   * @date 2024/11/7
   */
  R<?> setCxMeasureCfBbaExpRst(String valMethod, String valMonth) throws ParseException;

  /**
   * 计算(产险直保/再保BBA)  理赔配置表
   */
  R<?> setCxZbMeasureConfCommonClaim(String valMethod, String valMonth);

  /**
   * 计算(产险直保/再保分入)  实际费用表
   */
  R<?> setCxMeasureActualExpense(String valMethod, String valMonth);

  /**
   * 计算(产险直保BBA)  经过天数配置_期初
   *
   * @param valMethod 评估方法
   * @param valMonth 评估时点
   * @return r
   */
  R<?> setCxZbMeasureBbaBeginPeriod(String valMethod, String valMonth);

  /**
   * 计算(产险直保BBA)  经过天数配置_当期
   *
   * @param valMethod 评估方法
   * @param valMonth 评估时点
   * @return r
   */
  R<?> setCxZbMeasureBbaCurrentPeriod(String valMethod, String valMonth);

  /**
   * 计算(产险直保BBA)  计息日期配置_期初
   *
   * @param valMethod 评估方法
   * @param valMonth 评估时点
   * @return r
   */
  R<?> setCxZbMeasureBbaBeginInterestCalculation(String valMethod, String valMonth);

  /**
   * 计算(产险直保BBA)  计息日期配置_当期
   *
   * @param valMethod 评估方法
   * @param valMonth 评估时点
   * @return r
   */
  R<?> setCxZbMeasureBbaCurrentInterestCalculation(String valMethod, String valMonth);

  /**
   * 计算(产险直保BBA)  维持费用相关_期初
   *
   * @param valMethod 评估方法
   * @param valMonth 评估时点
   * @return r
   */
  R<?> setCxZbMeasureBbaBeginMaintenanceCost(String valMethod, String valMonth);

  /**
   * 计算(产险直保BBA)  维持费用相关_当期
   *
   * @param valMethod 评估方法
   * @param valMonth 评估时点
   * @return r
   */
  R<?> setCxZbMeasureBbaCurrentMaintenanceCost(String valMethod, String valMonth);

  /**
   * 计算(产险直保BBA)  维持费用相关_当期计算假设变动数据
   *
   * @param valMethod 评估方法
   * @param valMonth 评估时点
   * @return r
   */
  R<?> setCxZbMeasureBbaChangeCurrentMaintenanceCost(String valMethod, String valMonth);

  /**
   * 计算(产险直保BBA)  赔款相关_期初
   * @param valMethod 评估方法
   * @param valMonth 评估月
   * @return r
   */
  R<?> setCxZbMeasureBbaBeginCompensation(String valMethod, String valMonth);

  /**
   * 计算(产险直保BBA)  赔款相关_当期
   * @param valMethod 评估方法
   * @param valMonth 评估月
   * @return r
   */
  R<?> setCxZbMeasureBbaCurrentCompensation(String valMethod, String valMonth);

  /**
   * 计算(产险直保BBA)  赔款相关_当期计算假设变动数据
   * @param valMethod 评估方法
   * @param valMonth 评估月
   * @return r
   */
  R<?> setCxZbMeasureBbaChangeCurrentCompensation(String valMethod, String valMonth);

  /**
   * - 5.计量源数据写入实际现金流（2.0）
   *
   * @param valMethod 评估方法，默认BBA
   * @param valMonth 评估月(默认当月跑上月)
   * @return 返回值描述
   * @Author hzh
   * @date 2024/11/7
   */
  R<?> setCxZbMeasureCfBbaBasicCalcRst(String valMethod, String valMonth);

  R<?> setCxMeasureResultCheckLic(String valMethod, String valMonth);
}
