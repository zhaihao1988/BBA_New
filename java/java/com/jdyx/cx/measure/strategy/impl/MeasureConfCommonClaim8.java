package com.jdyx.cx.measure.strategy.impl;

import cn.hutool.core.bean.BeanUtil;
import cn.hutool.core.date.DateUtil;
import com.google.common.collect.Lists;
import com.jdyx.common.cache.measure.ConfMeasureActuarialAssumptionCacheService;
import com.jdyx.common.cache.measure.ConfMeasureClaimModelCacheService;
import com.jdyx.common.cache.measure.ConfMeasureCommonDisrateCacheService;
import com.jdyx.common.cache.measure.ConfMeasureDiscountRateCacheService;
import com.jdyx.common.enums.EvaluateMethodTypeEnum;
import com.jdyx.cx.measure.service.BaseMeasureCxService;
import com.jdyx.cx.measure.strategy.MeasureConfCommonClaimStrategy;
import com.jdyx.measure.api.measure.domain.MeasureCfBasicData;
import com.jdyx.measure.api.measure.domain.MeasureCfResultInfo;
import com.jdyx.measure.api.measure.domain.MeasureConfCommonClaim;
import com.jdyx.measure.api.measure.mapper.MeasureConfCommonClaimMapper;
import com.kevin.common.utils.DateUtils;
import java.util.Collections;
import java.util.Date;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.DefaultTransactionDefinition;

/**
 * @author 郭文斌.
 * @date 2024/11/16.
 * @description 理赔配置计算直保PAA.
 */
@Slf4j
@RequiredArgsConstructor
@Service
public class MeasureConfCommonClaim8 extends BaseMeasureCxService implements MeasureConfCommonClaimStrategy {
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
   * 直保理赔配置表策略类方法
   * @param measureCfBasicDataList 基础数据
   * @param evaluateMethod 评估方法
   * @param valMonth 评估月份
   * @return
   */
  @Override
  public List<MeasureConfCommonClaim> doOperation(List<MeasureCfBasicData> measureCfBasicDataList, EvaluateMethodTypeEnum evaluateMethod, String valMonth) {
    //获取上期期末未确认保费
    Map<String, MeasureConfCommonClaim> lastMeasureConfCommonClaimMap = getCommonClaimMap(DateUtils.lastEndYear(valMonth, DateUtils.YYYYMM), evaluateMethod.getCode(), MeasureConfCommonClaim::getPremEopUnRecAmt);
    //获取折现利率
    Map<String,BigDecimal> disRateMap = confMeasureCommonDisrateCacheService.getConfMeasureCommonDisRate(evaluateMethod.getCode(),valMonth);
    //获取精算假设配置
    Map<String, Map<String, Object>> measureActuarialAssumptionMap = confMeasureActuarialAssumptionCacheService.getConfMeasureActuarialAssumption(evaluateMethod.getCode(), valMonth);
    //获取赔付模式
    Map<String, Map<Long, BigDecimal>> confMeasureClaimModelMap = confMeasureClaimModelCacheService.getConfMeasureClaimModelMapByYearAndMethod(String.valueOf(DateUtil.year(DateUtils.parseDate(valMonth))),evaluateMethod.getCode());
    //获取折现率
    Map<String, BigDecimal> confMeasureDiscountRateMap = confMeasureDiscountRateCacheService.getConfMeasureDiscountRateByValMonthAndValMethod(valMonth,
        evaluateMethod.getCode());

    AtomicInteger count = new AtomicInteger(measureCfBasicDataList.size());
    //线程安全处理
    List<MeasureCfBasicData> synchronizedList = Collections.synchronizedList(measureCfBasicDataList);

    List<MeasureConfCommonClaim> confMeasureClaimList = Optional.of(synchronizedList).orElse(Lists.newArrayList()).parallelStream().map(e -> {
      MeasureConfCommonClaim confClaim = new MeasureConfCommonClaim();
      BeanUtil.copyProperties(e, confClaim);
      //获取保障期限
      confClaim.setTerm(String.valueOf(e.getTerm()));
      //计算当期服务量
      confClaim.setCurrServAmt(computeCurrServAmt(e));
      //计算当期及未来服务量
      confClaim.setOtherServAmt(computeOtherServAmt(e));
      //计算当期确认比例
      confClaim.setCurRecPct(confClaim.getCurrServAmt().divide(confClaim.getOtherServAmt(), 10, RoundingMode.HALF_UP));
      //计算期初未确认保费
      confClaim.setPremBopUnRecAmt(computePremBopUnRecAmt(e, lastMeasureConfCommonClaimMap));
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

}
