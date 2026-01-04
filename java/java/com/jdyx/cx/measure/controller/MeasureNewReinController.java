package com.jdyx.cx.measure.controller;

import cn.dev33.satoken.annotation.SaIgnore;
import com.jdyx.cx.measure.service.IntMeasureCxNewReinService;
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
 * @className : MeasureNewReinController
 * @description : 新版计量 直保，再保
 * @createTime : [2025/8/1 11:14]
 * @updateUser : [LiuYanQiang]
 * @updateTime : [2025/8/1 11:14]
 * @updateRemark : [描述说明本次修改内容]
 */
@Slf4j
@Validated
@RequiredArgsConstructor
@RestController
@RequestMapping("/measure/new")
public class MeasureNewReinController {

  private final IntMeasureCxNewReinService intMeasureCxNewReinService;

  /**
   * 再保分入计算LRC
   *
   * @param valMethod 评估方法
   * @param valMonth  评估月
   * @return r
   */
  @SaIgnore
  @PostMapping("rein/in/lrc")
  public R<?> setMeasureLrcReinInResult(@RequestParam String valMethod, @RequestParam String valMonth) {
    try {
      log.info("valMethod={},valMonth={}", valMethod, valMonth);
      return intMeasureCxNewReinService.getGdqLrcReinInMeasureResult(valMethod, valMonth);
    } catch (Exception e) {
      log.error("LRC计量计算失败", e);
      return R.fail("LRC计量计算失败: " + e.getMessage());
    }

  }

  /**
   * 再保分出计算LRC
   *
   * @param valMethod 评估方法
   * @param valMonth  评估月
   * @return r
   */
  @SaIgnore
  @PostMapping("rein/out/lrc")
  public R<?> setMeasureLrcReinOutResult(@RequestParam String valMethod, @RequestParam String valMonth) {
    try {
      log.info("valMethod={},valMonth={}", valMethod, valMonth);
      return intMeasureCxNewReinService.getGdqLrcReinOutMeasureResult(valMethod, valMonth);
    } catch (Exception e) {
      log.error("LRC计量计算失败", e);
      return R.fail("LRC计量计算失败: " + e.getMessage());
    }
  }

  /**
   * 再保分入计算LRC月结
   *
   * @param valMethod 评估方法
   * @param valMonth  评估月
   * @return r
   */
  @SaIgnore
  @PostMapping("rein/in/lrc/month")
  public R<?> setMeasureLrcReinInByMonthResult(@RequestParam String valMethod, @RequestParam String valMonth) {
    try {
      log.info("valMethod={},valMonth={}", valMethod, valMonth);
      return intMeasureCxNewReinService.getLrcReinInMeasureByMonthResult(valMethod, valMonth);
    } catch (Exception e) {
      log.error("LRC计量计算失败", e);
      return R.fail("LRC计量计算失败: " + e.getMessage());
    }

  }

  /**
   * 再保分出计算LRC月结
   *
   * @param valMethod 评估方法
   * @param valMonth  评估月
   * @return r
   */
  @SaIgnore
  @PostMapping("rein/out/lrc/month")
  public R<?> setMeasureLrcReinOutByMonthResult(@RequestParam String valMethod, @RequestParam String valMonth) {
    try {
      log.info("valMethod={},valMonth={}", valMethod, valMonth);
      return intMeasureCxNewReinService.getLrcReinOutMeasureByMonthResult(valMethod, valMonth);
    } catch (Exception e) {
      log.error("LRC计量计算失败", e);
      return R.fail("LRC计量计算失败: " + e.getMessage());
    }

  }

//  /**
//   * 再保分入分出LRC分录月结
//   *
//   * @param valMonth 评估月
//   * @return r
//   */
//  @SaIgnore
//  @PostMapping("rein/in/lrc/le/month")
//  public R<?> setMeasureLrcLeReinByMonthResult(@RequestParam String valMonth) {
//    try {
//      log.info("valMonth={}", valMonth);
//      return intMeasureCxNewReinService.setMeasureLrcLeReinByMonthResult(valMonth);
//    } catch (Exception e) {
//      log.error("再保分入分出LRC分录计算失败", e);
//      return R.fail("再保分入分出LRC分录计算失败: " + e.getMessage());
//    }
//  }

}
