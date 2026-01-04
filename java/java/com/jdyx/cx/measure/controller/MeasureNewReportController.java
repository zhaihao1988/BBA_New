package com.jdyx.cx.measure.controller;

import cn.dev33.satoken.annotation.SaIgnore;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.jdyx.common.enums.EvaluateMethodTypeEnum;
import com.jdyx.measure.api.measure.domain.IntMeasureResultCheck;
import com.jdyx.measure.api.measure.domain.IntMeasureResultCheckLic;
import com.jdyx.measure.api.measure.domain.IntMeasureResultCheckRein;
import com.jdyx.measure.api.measure.mapper.IntMeasureResultCheckLicMapper;
import com.jdyx.measure.api.measure.mapper.IntMeasureResultCheckMapper;
import com.jdyx.measure.api.measure.mapper.IntMeasureResultCheckReinMapper;
import com.kevin.common.core.domain.R;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * @author : [XiaoleiChen]
 * @version : [v1.0]
 * @className : MeasureNewReportController
 * @description : [描述说明该类的功能]
 * @createTime : [2025/12/2 11:19]
 * @updateUser : [LiuYanQiang]
 * @updateTime : [2025/12/2 11:19]
 * @updateRemark : [描述说明本次修改内容]
 */
@Slf4j
@Validated
@RequiredArgsConstructor
@RestController
@RequestMapping("/measure/new/report")
public class MeasureNewReportController {

  private final IntMeasureResultCheckMapper intMeasureResultCheckMapper;
  private final IntMeasureResultCheckReinMapper intMeasureResultCheckReinMapper;
  private final IntMeasureResultCheckLicMapper intMeasureResultCheckLicMapper;

  /**
   * 计量lrc报表
   *
   * @param valMethod 评估方法
   * @param valMonth  评估月
   * @return r
   */
  @SaIgnore
  @PostMapping("lrc")
  public R<?> setMeasureLrcReport(@RequestParam String valMethod, @RequestParam String valMonth) {
    try {
      log.info("valMethod={},valMonth={}", valMethod, valMonth);

      if (EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_8.getCode().equals(valMethod)) {
        int delete = intMeasureResultCheckMapper.delete(new LambdaQueryWrapper<IntMeasureResultCheck>()
          .eq(IntMeasureResultCheck::getValMonth, valMonth)
          .eq(IntMeasureResultCheck::getValMethod, valMethod));
        log.info("已删除计量直保LRC核算表{}条", delete);

        intMeasureResultCheckMapper.createResult(valMonth);
        log.info("成功创建计量直保LRC核算表");
      } else if (EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_10.getCode().equals(valMethod)) {
        int delete = intMeasureResultCheckReinMapper.delete(new LambdaQueryWrapper<IntMeasureResultCheckRein>()
          .eq(IntMeasureResultCheckRein::getValMonth, valMonth)
          .eq(IntMeasureResultCheckRein::getValMethod, valMethod));
        log.info("已删除计量再保分出LRC核算表{}条", delete);

        intMeasureResultCheckReinMapper.createReinOutResult(valMonth);
        log.info("成功创建计量再保分出LRC核算表");
      } else if (EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_11.getCode().equals(valMethod)) {
        int delete = intMeasureResultCheckReinMapper.delete(new LambdaQueryWrapper<IntMeasureResultCheckRein>()
          .eq(IntMeasureResultCheckRein::getValMonth, valMonth)
          .eq(IntMeasureResultCheckRein::getValMethod, valMethod));
        log.info("已删除计量再保分入LRC核算表{}条", delete);

        intMeasureResultCheckReinMapper.createReinInResult(valMonth);
        log.info("成功创建计量再保分入LRC核算表");
      }
    } catch (Exception e) {
      log.error("创建计量LRC核算表失败", e);
      return R.fail("创建计量LRC核算表失败: " + e.getMessage());
    }
    return R.ok();
  }

  /**
   * 计量lic报表
   *
   * @param valMethod 评估方法
   * @param valMonth  评估月
   * @return r
   */
  @SaIgnore
  @PostMapping("lic")
  public R<?> setMeasureLicReport(@RequestParam String valMethod, @RequestParam String valMonth) {
    try {
      log.info("valMethod={},valMonth={}", valMethod, valMonth);

      int delete = intMeasureResultCheckLicMapper.delete(new LambdaQueryWrapper<IntMeasureResultCheckLic>()
        .eq(IntMeasureResultCheckLic::getValMonth, valMonth)
        .eq(IntMeasureResultCheckLic::getValMethod, valMethod));
      log.info("已删除计量直保再保LIC核算表{}条", delete);

      intMeasureResultCheckLicMapper.createResult(valMonth,valMethod);
      log.info("成功创建计量直保再保LIC核算表");
    } catch (Exception e) {
      log.error("创建计量LIC核算表失败", e);
      return R.fail("创建计量LIC核算表失败: " + e.getMessage());
    }
    return R.ok();
  }
}
