package com.jdyx.cx.measure.controller;

import cn.dev33.satoken.annotation.SaIgnore;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.jdyx.common.enums.EvaluateMethodTypeEnum;
import com.jdyx.cx.measure.service.*;
import com.jdyx.measure.api.measure.domain.MeasureResultAccountingScenarioAccount;
import com.jdyx.measure.api.measure.mapper.MeasureResultAccountingScenarioAccountMapper;
import com.kevin.common.core.domain.R;
import com.kevin.common.utils.DateUtils;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 未到期计量
 *
 * @author cjn
 * @date 2025/7/23.
 */
@Slf4j
@Validated
@RequiredArgsConstructor
@RestController
@RequestMapping("/measure")
public class MeasureNewController {

  private final MeasureCxLrcService measureCxNewService;
  private final MeasureCxCsLrcService measureCxCsLrcService;
  private final MeasureCxLicUnsettledService measureCxLicUnsettledService;
  private final MeasureCxGdqLrcService measureCxGdqLrcService;
  private final MeasureCxMonthsLrcService measureCxMonthsLrcService;
  private final MeasureCxDataService measureCxDataService;
  private final MeasureResultAccountingScenarioAccountMapper accountingScenarioAccountMapper;



  /**
   * 未到期计量-直保计量源数据加工（包含失效单）-月结
   *
   * @param valMethod 评估方法
   * @param valMonth 评估月
   * @return r
   */
  @SaIgnore
  @PostMapping("/unexpired/data")
  public R<?> measureDataLrc(@RequestParam String valMethod, @RequestParam String valMonth) {
    log.info("valMethod={},valMonth={}", valMethod, valMonth);
    return measureCxDataService.setUnexpiredMeasureData(valMethod, valMonth);
  }

  /**
   * 未到期计量-2312有效保单-过渡期
   *
   * @param valMethod 评估方法
   * @param valMonth 评估月
   * @return r
   */
  @SaIgnore
  @PostMapping("/unexpired")
  public R<?> measureResultLrc(@RequestParam String valMethod, @RequestParam String valMonth) {
    log.info("valMethod={},valMonth={}", valMethod, valMonth);
    return measureCxNewService.getUnexpiredMeasureResult(valMethod, valMonth);
  }

  /**
   * 未到期计量-测算
   *
   * @param valMethod 评估方法
   * @param valMonth 评估月
   * @return r
   */
  @SaIgnore
  @PostMapping("/unexpired/cs")
  public R<?> measureResultCsLrc(@RequestParam String valMethod, @RequestParam String valMonth) {
    log.info("valMethod={},valMonth={}", valMethod, valMonth);
    return measureCxCsLrcService.getUnexpiredMeasureResult(valMethod, valMonth);
  }

  /**
   * 过渡期未到期计量：截至2024-12-31 有效过的保单-过渡期
   *
   * @param valMethod 评估方法
   * @param valMonth 评估月
   * @return r
   */
  @SaIgnore
  @PostMapping("/unexpired/gdq")
  public R<?> measureResultGdqLrc(@RequestParam String valMethod, @RequestParam String valMonth) {
    log.info("valMethod={},valMonth={}", valMethod, valMonth);
    return measureCxGdqLrcService.getUnexpiredMeasureResult(valMethod, valMonth);
  }

  /**
   * 未到期计量,月结
   *
   * @param valMethod 评估方法
   * @param valMonth 评估月
   * @return r
   */
  @SaIgnore
  @PostMapping("/unexpired/months")
  public R<?> measureResultMonthsLrc(@RequestParam String valMethod, @RequestParam String valMonth) {
    log.info("valMethod={},valMonth={}", valMethod, valMonth);
    return measureCxMonthsLrcService.getUnexpiredMeasureResult(valMethod, valMonth);
  }

  /**
   * 未决计量-过渡期+月结
   *
   * @param valMethod 评估方法
   * @param valMonth 评估月
   * @return r
   */
  @SaIgnore
  @PostMapping("/unsettled")
  public R<?> measureResultUnsettled(@RequestParam String valMethod, @RequestParam String valMonth) {
    log.info("valMethod={},valMonth={}", valMethod, valMonth);
    return measureCxLicUnsettledService.getUnsettledMeasureResult(valMethod, valMonth);
  }

  /**
   * 分录计量-过渡期（2024-12-31）-年累计值
   *
   * @param valMethod 评估方法
   * @param valMonth 评估月
   * @return r
   */
  @SaIgnore
  @PostMapping("/accountingScenarioAccount/gdq")
  public R<?> accountingScenarioAccountGdq(@RequestParam String valMethod, @RequestParam String valMonth) {
    log.info("valMethod={},valMonth={}", valMethod, valMonth);
    //根据不同的 valMethod 调用通用处理方法
    if (EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_8.getCode().equals(valMethod)) {
      // 直保
      int delete = accountingScenarioAccountMapper.delete(
        new LambdaQueryWrapper<MeasureResultAccountingScenarioAccount>()
          .eq(MeasureResultAccountingScenarioAccount::getValMonth, valMonth)
          .eq(MeasureResultAccountingScenarioAccount::getValMethod, valMethod));
      log.info("已删除旧计量分录结果表{}条", delete);

      int create = accountingScenarioAccountMapper.createAccountResultGdqDirect();
      log.info("已创建新计量分录结果表{}条", create);
    } else if (EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_10.getCode().equals(valMethod)) {
      // 再保分出
      int delete = accountingScenarioAccountMapper.delete(
        new LambdaQueryWrapper<MeasureResultAccountingScenarioAccount>()
          .eq(MeasureResultAccountingScenarioAccount::getValMonth, valMonth)
          .eq(MeasureResultAccountingScenarioAccount::getValMethod, valMethod));
      log.info("已删除旧计量分录结果表{}条", delete);

      //未决
      int unsettled = accountingScenarioAccountMapper.createAccountResultReinOut(valMonth, valMethod);
      //未到期
      int unexpired = accountingScenarioAccountMapper.createAccountResultGdqReinOut();
      log.info("已创建新计量分录结果表未决{}条,未到期{}条", unsettled,unexpired);
    } else if (EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_11.getCode().equals(valMethod)) {
      // 再保分入
      int delete = accountingScenarioAccountMapper.delete(
        new LambdaQueryWrapper<MeasureResultAccountingScenarioAccount>()
          .eq(MeasureResultAccountingScenarioAccount::getValMonth, valMonth)
          .eq(MeasureResultAccountingScenarioAccount::getValMethod, valMethod));
      log.info("已删除旧计量分录结果表{}条", delete);

      //未决
      int unsettled = accountingScenarioAccountMapper.createAccountResultReinIn(valMonth, valMethod, DateUtils.lastEndMonth(valMonth));
      //未到期
      int unexpired = accountingScenarioAccountMapper.createAccountResultGdqReinIn();
      log.info("已创建新计量分录结果表未决{}条,未到期{}条", unsettled,unexpired);
    }
    return R.ok();
  }

  /**
   * 分录计量-月结
   *
   * @param valMethod 评估方法
   * @param valMonth 评估月
   * @return r
   */
  @SaIgnore
  @PostMapping("/accountingScenarioAccount")
  public R<?> accountingScenarioAccount(@RequestParam String valMethod, @RequestParam String valMonth) {
    log.info("valMethod={},valMonth={}", valMethod, valMonth);
    //根据不同的 valMethod 调用通用处理方法
    if (EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_8.getCode().equals(valMethod)) {
      // 直保
      int delete = accountingScenarioAccountMapper.delete(
        new LambdaQueryWrapper<MeasureResultAccountingScenarioAccount>()
          .eq(MeasureResultAccountingScenarioAccount::getValMonth, valMonth)
          .eq(MeasureResultAccountingScenarioAccount::getValMethod, valMethod));
      log.info("已删除旧计量分录结果表{}条", delete);
      //未决+未到期
      int create = accountingScenarioAccountMapper.createAccountResultDirect(valMonth, valMethod, DateUtils.lastEndMonth(valMonth));
      //已决
      int settled = accountingScenarioAccountMapper.createAccountResultDirectYj(valMonth, valMethod, DateUtils.lastEndMonth(valMonth));
      log.info("已创建新计量分录结果表未决+未到期{}条,已决{}条", create,settled);
    } else if (EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_10.getCode().equals(valMethod)) {
      // 再保分出
      int delete = accountingScenarioAccountMapper.delete(
        new LambdaQueryWrapper<MeasureResultAccountingScenarioAccount>()
          .eq(MeasureResultAccountingScenarioAccount::getValMonth, valMonth)
          .eq(MeasureResultAccountingScenarioAccount::getValMethod, valMethod));
      log.info("已删除旧计量分录结果表{}条", delete);

      //未决
      int unsettled = accountingScenarioAccountMapper.createAccountResultReinOut(valMonth, valMethod);
      //未到期
      int unexpired = accountingScenarioAccountMapper.insertMeasureLrcLeReinOutByMonthResult(valMonth);
      log.info("已创建新计量分录结果表未决{}条,未到期{}条", unsettled,unexpired);
    } else if (EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_11.getCode().equals(valMethod)) {
      // 再保分入
      int delete = accountingScenarioAccountMapper.delete(
        new LambdaQueryWrapper<MeasureResultAccountingScenarioAccount>()
          .eq(MeasureResultAccountingScenarioAccount::getValMonth, valMonth)
          .eq(MeasureResultAccountingScenarioAccount::getValMethod, valMethod));
      log.info("已删除旧计量分录结果表{}条", delete);

      //未决
      int unsettled = accountingScenarioAccountMapper.createAccountResultReinIn(valMonth, valMethod, DateUtils.lastEndMonth(valMonth));
      //未到期
      int unexpired = accountingScenarioAccountMapper.insertMeasureLrcLeReinInByMonthResult(valMonth);
      //已决
      int settled = accountingScenarioAccountMapper.createAccountResultReinInYj(valMonth, valMethod, DateUtils.lastEndMonth(valMonth));
      log.info("已创建新计量分录结果表未决+已决{}条,未到期{}条,已决{}条", unsettled,unexpired,settled);
    }
    return R.ok();
  }


}
