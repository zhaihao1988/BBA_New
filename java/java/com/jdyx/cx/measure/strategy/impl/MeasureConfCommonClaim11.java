package com.jdyx.cx.measure.strategy.impl;

import cn.hutool.core.bean.BeanUtil;
import cn.hutool.core.date.DateUtil;
import com.google.common.collect.Lists;
import com.jdyx.common.cache.measure.ConfMeasureActuarialAssumptionCacheService;
import com.jdyx.common.cache.measure.ConfMeasureClaimModelCacheService;
import com.jdyx.common.cache.measure.ConfMeasureCommonDisrateCacheService;
import com.jdyx.common.cache.measure.ConfMeasureDiscountRateCacheService;
import com.jdyx.common.enums.EvaluateMethodTypeEnum;
import com.jdyx.common.measure.constant.NumberConstant;
import com.jdyx.common.measure.constant.StringConstant;
import com.jdyx.common.measure.tools.UtilsCommon;
import com.jdyx.cx.measure.service.BaseMeasureCxService;
import com.jdyx.cx.measure.strategy.MeasureConfCommonClaimStrategy;
import com.jdyx.measure.api.measure.domain.MeasureCfBasicData;
import com.jdyx.measure.api.measure.domain.MeasureConfCommonClaim;
import com.jdyx.measure.api.measure.mapper.MeasureConfCommonClaimMapper;
import com.kevin.common.utils.DateUtils;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.DefaultTransactionDefinition;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.*;
import java.util.stream.Collectors;

/**
 * @author 郭文斌.
 * @date 2024/11/16.
 * @description 理赔配置计算再保PAA.
 */
@Slf4j
@RequiredArgsConstructor
@Service
public class MeasureConfCommonClaim11 extends BaseMeasureCxService implements MeasureConfCommonClaimStrategy {

  /** 折现利率表接口 */
  private final ConfMeasureCommonDisrateCacheService confMeasureCommonDisrateCacheService;

  /** 精算假设配置表接口 */
  private final ConfMeasureActuarialAssumptionCacheService confMeasureActuarialAssumptionCacheService;

  /** 赔付模式接口 */
  private final ConfMeasureClaimModelCacheService confMeasureClaimModelCacheService;

  /** 折现率表接口 */
  private final ConfMeasureDiscountRateCacheService confMeasureDiscountRateCacheService;

  private final PlatformTransactionManager transactionManager;
  private final MeasureConfCommonClaimMapper measureConfCommonClaimMapper;

  /**
   * 再保理赔配置表策略类方法
   * @param measureCfBasicDataList 基础数据
   * @param evaluateMethod 评估方法
   * @param valMonth 评估月份
   * @return 理赔配置表数据
   */
  @Override
  public List<MeasureConfCommonClaim> doOperation(List<MeasureCfBasicData> measureCfBasicDataList, EvaluateMethodTypeEnum evaluateMethod, String valMonth) {

    Map<String, MeasureConfCommonClaim> lastMeasureConfCommonClaimMap = getCommonClaimMap(DateUtils.lastEndYear(valMonth, DateUtils.YYYYMM), evaluateMethod.getCode(), MeasureConfCommonClaim::getPremEopUnRecAmt);;
    Map<String, BigDecimal> disRateMap = confMeasureCommonDisrateCacheService.getConfMeasureCommonDisRate(evaluateMethod.getCode(),valMonth);
    Map<String, Map<String, Object>> measureActuarialAssumptionMap = confMeasureActuarialAssumptionCacheService.getConfMeasureActuarialAssumption(evaluateMethod.getCode(), valMonth);
    Map<String, Map<Long, BigDecimal>> confMeasureClaimModelMap = confMeasureClaimModelCacheService.getConfMeasureClaimModelMapByYearAndMethod(String.valueOf(DateUtil.year(DateUtils.parseDate(valMonth))),evaluateMethod.getCode());
    Map<String, BigDecimal> confMeasureDiscountRateMap = confMeasureDiscountRateCacheService.getConfMeasureDiscountRateByValMonthAndValMethod(valMonth,
        evaluateMethod.getCode());

    //线程安全处理
    List<MeasureCfBasicData> synchronizedList = Collections.synchronizedList(measureCfBasicDataList);

    List<MeasureConfCommonClaim> confMeasureClaimList = Optional.of(synchronizedList).orElse(Lists.newArrayList()).parallelStream().map(e -> {
      MeasureConfCommonClaim confClaim = new MeasureConfCommonClaim();
      BeanUtil.copyProperties(e, confClaim);
      //投资成分
      if(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_11.getCode().equals(e.getValMethod())){
        confClaim.setInvestProp(e.getMinPayRate());
      }else if(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_10.getCode().equals(e.getValMethod())){
        confClaim.setInvestProp(e.getFloatingHandlingFeeRate());
      }
      //当期服务量
      confClaim.setCurrServAmt(computeCurrServAmt(e));
      //当期及未来服务量
      confClaim.setOtherServAmt(computeOtherServAmt(e));
      //当期确认比例
      confClaim.setCurRecPct(confClaim.getCurrServAmt().divide(confClaim.getOtherServAmt(), 10, RoundingMode.HALF_UP));
      //期初未确认保费
      confClaim.setPremBopUnRecAmt(computePremBopUnRecAmt(e,lastMeasureConfCommonClaimMap));
      //期初保费计息
      confClaim.setPremInterestAmt(computePremInterestAmt(confClaim,disRateMap));
      //当期确认的保费
      confClaim.setPremCurRecAmt(computePremCurRecAmt(confClaim));
      //期末未确认保费
      confClaim.setPremEopUnRecAmt(computePremEopUnRecAmt(confClaim));
      //未经过保费
      confClaim.setUnRecPremAmt(computeUnRecPremAmt(confClaim, evaluateMethod, disRateMap));
      //终极赔付金额
      confClaim.setUltimatePaidLoss(computeUltimatePaidLoss(confClaim,measureActuarialAssumptionMap));
      //预期赔付金额
      confClaim.setPvPaidLoss(computePvPaidLoss(confClaim,confMeasureClaimModelMap,confMeasureDiscountRateMap));
      confClaim.setCreateTime(new Date());
      confClaim.setUpdateTime(new Date());
      return confClaim;
    }).collect(Collectors.toList());
    batchesSaveCommit(confMeasureClaimList);
    return null;
  }

  /**
   * 提交数据到数据库
   *
   * @param confMeasureClaimList 待存储数据
   */
  private void batchesSaveCommit(List<MeasureConfCommonClaim> confMeasureClaimList) {
    DefaultTransactionDefinition def = new DefaultTransactionDefinition();
    def.setPropagationBehavior(DefaultTransactionDefinition.PROPAGATION_REQUIRES_NEW);
    // 获取事务状态
    TransactionStatus status = transactionManager.getTransaction(def);
    try {
      //存储明细数据
      boolean insertBatchStatus = measureConfCommonClaimMapper.insertBatch(confMeasureClaimList);
      log.info("本次存储理赔配置数据={}条", confMeasureClaimList.size());
      // 手动提交事务
      transactionManager.commit(status);
    } catch (Exception e) {
      // 发生异常时回滚事务
      transactionManager.rollback(status);
      log.error(e.getMessage(), e);
    }
  }

  /**
   * @param basic 计量源数据
   * @return 当期服务量
   */
  @Override
  public BigDecimal computeCurrServAmt(MeasureCfBasicData basic) {
    BigDecimal servAmt = BigDecimal.ZERO;
    Date valMonthDate = DateUtils.endMonth(basic.getValMonth());
    Date endDate = DateUtils.parseDate(basic.getEndDate());
    Date startDate = DateUtils.parseDate(basic.getStartDate());
    Date lastValMonthDatePlusOne = DateUtils.addDays(DateUtils.endMonth(basic.getLastValMonth()),1);
    Date evaluateDate = DateUtils.parseDate(basic.getEvaluateDate());

    //max(保险评估起期，上期评估时点）
    Date date = DateUtil.compare(startDate, lastValMonthDatePlusOne)
      > NumberConstant.LONG_ZERO ? startDate : lastValMonthDatePlusOne;

    if (StringConstant.STRING_ONE.equals(basic.getWhetherCurPolicy())) {
      if (DateUtils.getDateDiff(valMonthDate, endDate) > NumberConstant.LONG_ZERO) {
        servAmt = servAmt.max(BigDecimal.valueOf(basic.getTerm()));
      } else {
        servAmt = servAmt.max(BigDecimal.valueOf(UtilsCommon.differentDaysByMillisecond(valMonthDate, startDate)).add(BigDecimal.ONE));
      }
    } else {
      if (DateUtils.getDateDiff(valMonthDate, endDate) >= NumberConstant.LONG_ZERO) {
        servAmt = servAmt.max(BigDecimal.valueOf(UtilsCommon.differentDaysByMillisecond(endDate, date)).add(BigDecimal.ONE));
      } else {
        servAmt = servAmt.max(BigDecimal.valueOf(UtilsCommon.differentDaysByMillisecond(valMonthDate, date)).add(BigDecimal.ONE));
      }
    }
    servAmt = BigDecimal.ZERO.compareTo(servAmt) >= 0 ? BigDecimal.ZERO : servAmt;
    return servAmt;
  }

  /**
   * @param basic 计量源数据
   * @return 当期及未来服务量
   */
  @Override
  public BigDecimal computeOtherServAmt(MeasureCfBasicData basic) {
    BigDecimal otherServAmt;
    Date startDate = DateUtils.parseDate(basic.getStartDate());
    Date endDate = DateUtils.parseDate(basic.getEndDate());
    Date lastValMonthDate = DateUtils.addDays(DateUtils.endMonth(basic.getLastValMonth()),1);
    if (StringConstant.STRING_ONE.equals(basic.getWhetherCurPolicy())) {
      otherServAmt = BigDecimal.valueOf(UtilsCommon.differentDaysByMillisecond(endDate, startDate)).add(BigDecimal.ONE);
    } else {
      Date lastValPeriodPoint = DateUtils.getDateDiff(lastValMonthDate, startDate) > NumberConstant.LONG_ZERO ? lastValMonthDate : startDate;
      otherServAmt = BigDecimal.valueOf(UtilsCommon.differentDaysByMillisecond(endDate, lastValPeriodPoint)).add(BigDecimal.ONE);
    }
    return otherServAmt;
  }

  /**
   * @param basic 计量源数据
   * @return 上期末当期确认的保费map
   * 再保分出:
   * " ----如果22.是否当期新单=1 , 32.期初未确认保费=17.不含税毛分出保费
   *  ----如果22.是否当期新单 = 0 ,  32.期初未确认保费=上期35.期末未确认保费
   *  (备注：上期指的是2.上期评估时点的值)"
   * @return 期初未确认保费
   */
  @Override
  public BigDecimal computePremBopUnRecAmt(MeasureCfBasicData basic,Map<String,MeasureConfCommonClaim> lastMeasureCfCommonClaimMap) {
    BigDecimal premBopUnRecAmt;
    // BigDecimal premiumImpairment = Optional.ofNullable(basic.getPremiumImpairment()).orElse(BigDecimal.ZERO);
    // BigDecimal premium = basic.getValMethod().equals(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_11.getCode())?basic.getPremiumCny():basic.getNetPremiumCny();
    if (StringConstant.STRING_ONE.equals(basic.getWhetherCurPolicy())) {
        premBopUnRecAmt = basic.getPremiumCny();
      } else {
        premBopUnRecAmt = Optional.ofNullable(lastMeasureCfCommonClaimMap.get(basic.getUnitId())).map(MeasureConfCommonClaim::getPremEopUnRecAmt).orElse(BigDecimal.ZERO);
      }
    return Optional.of(premBopUnRecAmt).orElse(BigDecimal.ZERO);
  }
}
