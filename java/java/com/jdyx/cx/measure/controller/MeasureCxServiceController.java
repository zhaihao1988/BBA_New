package com.jdyx.cx.measure.controller;

import cn.dev33.satoken.annotation.SaIgnore;
import com.jdyx.common.api.anotation.ProcessAnnotation;
import com.jdyx.cx.measure.service.MeasureCxBbaService;
import com.jdyx.cx.measure.service.MeasureCxZbService;
import com.kevin.common.annotation.RepeatSubmit;
import com.kevin.common.core.domain.R;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.text.ParseException;

/**
 * 计量服务
 *
 * @author kevin.
 * @date 2024/1/17.
 */
@Slf4j
@Validated
@RequiredArgsConstructor
@RestController
@RequestMapping("/measure")
public class MeasureCxServiceController {

  private final MeasureCxZbService measureCxService;
  private final MeasureCxBbaService measureCxBbaService;

  /**
   * 1.获取(产险PAA/BBA) 获取基础数据
   *
   * @param valMethod 评估方法  {@link com.jdyx.common.enums.EvaluateMethodTypeEnum}
   * @param valMonth 评估月(默认当月跑上月)
   * @return r 返回处理状态
   */
  @RepeatSubmit()
  @SaIgnore
  @PostMapping("/setCxZbMeasureCfBasicDataRst")
  @ProcessAnnotation
  public R<?> setCxZbMeasureCfBasicDataRst(@RequestParam String valMethod, @RequestParam String valMonth,
                                           @RequestParam(defaultValue = "measure") String processCode) {
     return measureCxService.setCxPiMeasureCfBasicDataRst(valMethod, valMonth);
  }

  /**
   * 2.计算(产险直保/再保BBA)  理赔配置表
   */
  @RepeatSubmit()
  @SaIgnore
  @PostMapping("/setCxZbMeasureConfCommonClaim")
  @ProcessAnnotation
  public R<?> setCxZbMeasureConfCommonClaim(@RequestParam String valMethod, @RequestParam String valMonth,
                                            @RequestParam(defaultValue = "measure") String processCode) {
    log.info("valMethod={},valMonth={}", valMethod, valMonth);
    return measureCxService.setCxZbMeasureConfCommonClaim(valMethod, valMonth);
  }

  /**
   * 2.1 计算(产险直保/再保分入)  实际费用表
   * @param valMethod 评估方法，适用 8,11
   * @param valMonth 评估月yyyymm
   * @return
   */
  @RepeatSubmit()
  @SaIgnore
  @PostMapping("/setCxMeasureActualExpense")
  public R<?> setCxMeasureActualExpense(@RequestParam String valMethod, @RequestParam String valMonth) {
    return measureCxService.setCxMeasureActualExpense(valMethod, valMonth);
  }

  /**
   * 3.1 计算(产险直保/再保PAA)  PAA当期计量明细
   *
   * @param valMethod 评估方法
   * @param valMonth 评估月(默认当月跑上月)
   * @return r 返回处理状态
   */
  @SaIgnore
  @PostMapping("/setCxZbMeasureCfResultInfoRst")
  @RepeatSubmit()
  @ProcessAnnotation
  public R<?> setCxZbResultMeasureInfo(@RequestParam String valMethod, @RequestParam String valMonth,
                                       @RequestParam(defaultValue = "measure") String processCode) {
      log.info("enter setCxZbMeasureCfResultInfoRst,valMethod={},valMonth={}", valMethod, valMonth);
      //计量明细查询
      measureCxService.setCxPiPaaMeasureCfResultInfoRst(valMethod, valMonth);
      //计算明细计量汇总写入预期现金流表
      measureCxService.setCxInfoToCfBasicExpRst(valMethod, valMonth);
      return R.ok();
  }

  /**
   * 2.1 (产险直保/再保分入)  计量核算表
   * @param valMethod 评估方法，适用 8,11
   * @param valMonth 评估月yyyymm
   * @return
   */
  @RepeatSubmit()
  @SaIgnore
  @PostMapping("/setCxMeasureResultCheck")
  public R<?> setCxMeasureResultCheck(@RequestParam String valMethod, @RequestParam String valMonth) {
    return measureCxService.setCxMeasureResultCheck(valMethod, valMonth);
  }

  /**
   * 计量核算表LIC
   * @param valMonth 评估月yyyymm
   * @return
   */
  @RepeatSubmit()
  @SaIgnore
  @PostMapping("/setCxMeasureResultCheckLic")
  public R<?> setCxMeasureResultCheckLic(@RequestParam String valMethod, @RequestParam String valMonth) {
    return measureCxService.setCxMeasureResultCheckLic(valMethod, valMonth);
  }

  /**
   * 3.2 计算(产险直保BBA)  当期计量明细
   *
   * @param valMethod 评估方法
   * @param valMonth 评估月(默认当月跑上月)
   * @return r 返回处理状态
   */
  @RepeatSubmit()
  @SaIgnore
  @PostMapping("/setCxZbBbaMeasureCfResultInfoRst")
  @ProcessAnnotation
  public R<?> setCxZbBbaMeasureCfResultInfoRst(@RequestParam String valMethod, @RequestParam String valMonth,
                                               @RequestParam(defaultValue = "measure") String processCode) {
    log.info("valMethod={},valMonth={}", valMethod, valMonth);
    return measureCxService.setCxPiBbaMeasureCfResultInfoRst(valMethod, valMonth);
  }

  /**
   * 4.计量明细输送至分摊平台
   *
   * @param valMethod 评估方法，默认直保PAA
   * @param valMonth 评估月(默认当月跑上月)
   * @author hzh
   * @date 2024/10/23
   */
  @RepeatSubmit()
  @SaIgnore
  @PostMapping("/setCxZbResultAllocation")
  @ProcessAnnotation
  public R<?> setCxZbResultAllocation(@RequestParam(defaultValue = "8") String valMethod, @RequestParam String valMonth,
                                      @RequestParam(defaultValue = "measure") String processCode) {
    log.info("evaluateMethod={},valMonth={}", valMethod, valMonth);
    return measureCxService.setCxZbResultAllocation(valMethod, valMonth);
  }

  /**
   * - 5.1 计算明细计量写入预期现金流表（2.0）
   *
   * @param valMethod 评估方法，默认BBA
   * @param valMonth 评估月(默认当月跑上月)
   * @return 返回值描述
   * @Author hzh
   * @date 2024/11/7
   */
  @RepeatSubmit()
  @SaIgnore
  @PostMapping("/setCxZbBbaCfBasicCalcRst")
  @ProcessAnnotation
  public R<?> setCxZbBbaCfBasicCalcRst(@RequestParam(defaultValue = "7") String valMethod, @RequestParam String valMonth,
                                       @RequestParam(defaultValue = "measure") String processCode) throws ParseException {
    log.info("预期现金流接口..enter,valMethod={},valMonth={}", valMethod, valMonth);

    R<?> res = measureCxService.setCxMeasureCfBbaExpRst(valMethod, valMonth);
    log.info("预期现金流接口..end");
    return res;
  }

  /**
   * - 5.2 计量源数据写入实际现金流（2.0）
   *
   * @param valMethod 评估方法，默认BBA
   * @param valMonth 评估月(默认当月跑上月)
   * @return 返回值描述
   * @Author hzh
   * @date 2024/11/7
   */
  @RepeatSubmit()
  @SaIgnore
  @PostMapping("/setCxZbMeasureCfBasicCalcRst")
  @ProcessAnnotation
  public R<?> setCxZbMeasureCfBbaBasicCalcRst(@RequestParam(defaultValue = "7") String valMethod, @RequestParam String valMonth,
                                              @RequestParam(defaultValue = "measure") String processCode) {
    log.info("实际现金流接口..enter,valMethod={},valMonth={}", valMethod, valMonth);
    R<?> res = measureCxService.setCxZbMeasureCfBbaBasicCalcRst(valMethod, valMonth);
    log.info("实际现金流接口..end");
    return res;
  }

  /**
   * 5.3 BBA计量核心计算
   * @param valMethod 评估方法
   * @param valMonth 评估月
   * @return
   */
  @RepeatSubmit()
  @SaIgnore
  @PostMapping("/setCxMeasureResultBbaCore")
  @ProcessAnnotation
  public R<?> setCxMeasureResultBbaCore(@RequestParam(defaultValue = "7") String valMethod, @RequestParam String valMonth,
                                        @RequestParam(defaultValue = "measure") String processCode) {
    log.info("bba核心计量计算,valMethod={},valMonth={}", valMethod, valMonth);
    return measureCxBbaService.setCxMeasureResultBbaCore(valMethod, valMonth);
  }


//  /**
//   * 3.计算明细计量汇总写入预期现金流表
//   *
//   * @param valMethod 评估方法
//   * @param riOrPi 直保或再保(RI-再保,PI-直保)
//   * @param valMonth 评估月(默认当月跑上月)
//   * @return r
//   */
//  @SaIgnore
//  @PostMapping("/setCxZbBbaCfBasicCalcRst")
//  public R<?> setCxZbBbaCfBasicCalcRst(@RequestParam String valMethod, @RequestParam(defaultValue = "PI") String riOrPi, @RequestParam String valMonth) {
//    log.info("valMethod={},valMonth={}", valMethod, valMonth);
//    return measureCxService.setCxInfoToCfBasicExpRst(valMethod, DateUtils.lastEndMonth(valMonth));
//  }

  /**
   * 计算(产险直保BBA)  经过天数配置_期初
   * @param valMethod 评估方法
   * @param valMonth 评估月(默认当月跑上月)
   * @return r
   */
  @RepeatSubmit()
  @SaIgnore
  @PostMapping("/setCxZbMeasureBbaBeginPeriod")
  public R<?> setCxZbMeasureBbaBeginPeriod(@RequestParam String valMethod, @RequestParam String valMonth) {
    log.info("valMethod={},valMonth={}", valMethod, valMonth);
    return measureCxService.setCxZbMeasureBbaBeginPeriod(valMethod, valMonth);
  }

  /**
   * 计算(产险直保BBA)  经过天数配置_当期
   * @param valMethod 评估方法
   * @param valMonth 评估月(默认当月跑上月)
   * @return r
   */
  @RepeatSubmit()
  @SaIgnore
  @PostMapping("/setCxZbMeasureBbaCurrentPeriod")
  public R<?> setCxZbMeasureBbaCurrentPeriod(@RequestParam String valMethod, @RequestParam String valMonth) {
    log.info("valMethod={},valMonth={}", valMethod, valMonth);
    return measureCxService.setCxZbMeasureBbaCurrentPeriod(valMethod, valMonth);
  }

  /**
   * 计算(产险直保BBA)  计息日期配置_期初
   * @param valMethod 评估方法
   * @param valMonth 评估月(默认当月跑上月)
   * @return r
   */
  @RepeatSubmit()
  @SaIgnore
  @PostMapping("/setCxZbMeasureBbaBeginInterestCalculation")
  public R<?> setCxZbMeasureBbaBeginInterestCalculation(@RequestParam String valMethod, @RequestParam String valMonth) {
    log.info("valMethod={},valMonth={}", valMethod, valMonth);
    return measureCxService.setCxZbMeasureBbaBeginInterestCalculation(valMethod, valMonth);
  }

  /**
   * 计算(产险直保BBA)  计息日期配置_当期
   * @param valMethod 评估方法
   * @param valMonth 评估月(默认当月跑上月)
   * @return r
   */
  @RepeatSubmit()
  @SaIgnore
  @PostMapping("/setCxZbMeasureBbaCurrentInterestCalculation")
  public R<?> setCxZbMeasureBbaCurrentInterestCalculation(@RequestParam String valMethod, @RequestParam String valMonth) {
    log.info("valMethod={},valMonth={}", valMethod, valMonth);
    return measureCxService.setCxZbMeasureBbaCurrentInterestCalculation(valMethod, valMonth);
  }

  /**
   * 计算(产险直保BBA)  维持费用相关_期初
   * @param valMethod 评估方法
   * @param valMonth 评估月(默认当月跑上月)
   * @return r
   */
  @RepeatSubmit()
  @SaIgnore
  @PostMapping("/setCxZbMeasureBbaBeginMaintenanceCost")
  public R<?> setCxZbMeasureBbaBeginMaintenanceCost(@RequestParam String valMethod, @RequestParam String valMonth) {
    log.info("valMethod={},valMonth={}", valMethod, valMonth);
    return measureCxService.setCxZbMeasureBbaBeginMaintenanceCost(valMethod, valMonth);
  }

  /**
   * 计算(产险直保BBA)  维持费用相关_当期
   * @param valMethod 评估方法
   * @param valMonth 评估月(默认当月跑上月)
   * @return r
   */
  @RepeatSubmit()
  @SaIgnore
  @PostMapping("/setCxZbMeasureBbaCurrentMaintenanceCost")
  public R<?> setCxZbMeasureBbaCurrentMaintenanceCost(@RequestParam String valMethod, @RequestParam String valMonth) {
    log.info("valMethod={},valMonth={}", valMethod, valMonth);
    return measureCxService.setCxZbMeasureBbaCurrentMaintenanceCost(valMethod, valMonth);
  }

  /**
   * 计算(产险直保BBA)  维持费用相关_当期计算假设变动数据
   * @param valMethod 评估方法
   * @param valMonth 评估月(默认当月跑上月)
   * @return r
   */
  @RepeatSubmit()
  @SaIgnore
  @PostMapping("/setCxZbMeasureBbaChangeCurrentMaintenanceCost")
  public R<?> setCxZbMeasureBbaChangeCurrentMaintenanceCost(@RequestParam String valMethod, @RequestParam String valMonth) {
    log.info("valMethod={},valMonth={}", valMethod, valMonth);
    return measureCxService.setCxZbMeasureBbaChangeCurrentMaintenanceCost(valMethod, valMonth);
  }

  /**
   * 计算(产险直保BBA)  赔款相关_期初
   * @param valMethod 评估方法
   * @param valMonth 评估月(默认当月跑上月)
   * @return r
   */
  @RepeatSubmit()
  @SaIgnore
  @PostMapping("/setCxZbMeasureBbaBeginCompensation")
  public R<?> setCxZbMeasureBbaBeginCompensation(@RequestParam String valMethod, @RequestParam String valMonth) {
    log.info("valMethod={},valMonth={}", valMethod, valMonth);
    return measureCxService.setCxZbMeasureBbaBeginCompensation(valMethod, valMonth);
  }

  /**
   * 计算(产险直保BBA)  赔款相关_当期
   * @param valMethod 评估方法
   * @param valMonth 评估月(默认当月跑上月)
   * @return r
   */
  @RepeatSubmit()
  @SaIgnore
  @PostMapping("/setCxZbMeasureBbaCurrentCompensation")
  public R<?> setCxZbMeasureBbaCurrentCompensation(@RequestParam String valMethod, @RequestParam String valMonth) {
    log.info("valMethod={},valMonth={}", valMethod, valMonth);
    return measureCxService.setCxZbMeasureBbaCurrentCompensation(valMethod, valMonth);
  }

  /**
   * 计算(产险直保BBA)  赔款相关_当期计算假设变动数据
   * @param valMethod 评估方法
   * @param valMonth 评估月(默认当月跑上月)
   * @return r
   */
  @RepeatSubmit()
  @SaIgnore
  @PostMapping("/setCxZbMeasureBbaChangeCurrentCompensation")
  public R<?> setCxZbMeasureBbaChangeCurrentCompensation(@RequestParam String valMethod, @RequestParam String valMonth) {
    log.info("valMethod={},valMonth={}", valMethod, valMonth);
    return measureCxService.setCxZbMeasureBbaChangeCurrentCompensation(valMethod, valMonth);
  }

  /**
   * 计算(产险直保BBA)  经过天数，计息日期，维持费用相关，赔款相关整合接口
   * @param valMethod 评估方法
   * @param valMonth 评估月(默认当月跑上月)
   * @return r
   */
  @RepeatSubmit()
  @SaIgnore
  @PostMapping("/setCxZbMeasureBbaConfigurationAll")
  @ProcessAnnotation
  public R<?> setCxZbMeasureBbaConfigurationAll(@RequestParam String valMethod, @RequestParam String valMonth,
                                                @RequestParam(defaultValue = "measure") String processCode) {
    log.info("valMethod={},valMonth={}", valMethod, valMonth);
    measureCxService.setCxZbMeasureBbaBeginPeriod(valMethod, valMonth);
    measureCxService.setCxZbMeasureBbaCurrentPeriod(valMethod, valMonth);
    measureCxService.setCxZbMeasureBbaBeginInterestCalculation(valMethod, valMonth);
    measureCxService.setCxZbMeasureBbaCurrentInterestCalculation(valMethod, valMonth);
    measureCxService.setCxZbMeasureBbaBeginMaintenanceCost(valMethod, valMonth);
    measureCxService.setCxZbMeasureBbaCurrentMaintenanceCost(valMethod, valMonth);
    measureCxService.setCxZbMeasureBbaChangeCurrentMaintenanceCost(valMethod, valMonth);
    measureCxService.setCxZbMeasureBbaBeginCompensation(valMethod, valMonth);
    measureCxService.setCxZbMeasureBbaCurrentCompensation(valMethod, valMonth);
    measureCxService.setCxZbMeasureBbaChangeCurrentCompensation(valMethod, valMonth);
    return R.ok();
  }

}
