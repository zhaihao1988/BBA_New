package com.jdyx.cx.measure.strategy.impl;

import com.google.common.collect.Lists;
import com.jdyx.common.cache.measure.ConfMeasureActuarialAssumptionCacheService;
import com.jdyx.common.cache.measure.MeasureConfCommonClaimCacheService;
import com.jdyx.common.enums.EvaluateMethodTypeEnum;
import com.jdyx.common.measure.service.Measure1CfInfoService;
import com.jdyx.common.measure.service.MeasureCommonCacheService;
import com.jdyx.cx.measure.service.BaseMeasureCxService;
import com.jdyx.cx.measure.strategy.MeasureCfResultInfoStrategy;
import com.jdyx.measure.api.measure.domain.MeasureCfBasicData;
import com.jdyx.measure.api.measure.domain.MeasureCfResultInfo;
import com.kevin.common.utils.DateUtils;
import com.kevin.common.utils.StringUtils;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;

import java.math.BigDecimal;
import java.util.*;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.stream.Collectors;

/**
 * 产险-直保-BBA-7
 * 产险-直保-PAA-8
 *
 * @author 刘瑞奎.
 * @date 2024/10/24.
 */
@SuppressWarnings("DuplicatedCode")
@Slf4j
@RequiredArgsConstructor
@Service
public class MeasureCfResultInfo8 extends BaseMeasureCxService implements MeasureCfResultInfoStrategy {

  /** 11.计量明细统一接口 */
  private final Measure1CfInfoService measure1CfInfoService;
  /** 精算假设配置缓存数据服务 */
  private final ConfMeasureActuarialAssumptionCacheService confMeasureActuarialAssumptionCacheService;
  /** 理赔配置数据Service接口 */
  private final MeasureConfCommonClaimCacheService measureConfCommonClaimCacheService;
  private final PlatformTransactionManager transactionManager;
  private final MeasureCommonCacheService measureCommonCacheService;
  private final ThreadPoolExecutor threadPoolExecutor;


  public static void main(String[] args) {
    System.out.println(StringUtils.joinWith("_", "1", 3, "5"));
  }

  /**
   * 获取 计量明细计算策略方法
   *
   * @param measureCfBasicDataList 计量源数据
   * @param evaluateMethod 评估方法 {@link EvaluateMethodTypeEnum}
   * @param valMonth 评估时点 计量明细数据
   * @return java.util.List<com.jdyx.measure.api.measure.domain.MeasureCfResultInfo>
   * @author kevin.
   * @date 2024/10/21.
   */
  @Override
  @Async("threadPoolExecutor")
  public void doOperation(List<MeasureCfBasicData> measureCfBasicDataList, EvaluateMethodTypeEnum evaluateMethod, String valMonth, CountDownLatch latch) {
    try {
      log.error("===============线程池队列长度:{}", threadPoolExecutor.getQueue().size());
      long startTime = System.currentTimeMillis();
      //1.获取 上期评估时点 计量明细数据
      Map<String, Map<String, BigDecimal>> measureInfoCache = measureCommonCacheService.getMeasureInfoCache(evaluateMethod.getCode(),DateUtils.lastEndYear(valMonth, DateUtils.YYYYMM),
        MeasureCfResultInfo::getPremEopUnRecAmt, MeasureCfResultInfo::getIacfEopUnRec, MeasureCfResultInfo::getIcEopUnRecAmt, MeasureCfResultInfo::getIacfEopUnRecRein);
      //2.循环计算
      List<MeasureCfResultInfo> measureCfResultInfoList = Optional.of(measureCfBasicDataList).orElse(Lists.newArrayList()).stream().map(measureCfBasicData -> {
        //初始化对象
        MeasureCfResultInfo measureCfResultInfo = measure1CfInfoService.iniMeasureCfResultInfo();
        //主键 = 主键
//        measureCfResultInfo.setId(measureCfBasicData.getId());
        //1.当前评估时点 = 当前评估时点
        measure1CfInfoService.getValMonth(measureCfBasicData, measureCfResultInfo, evaluateMethod.getCode());
        //2.上期评估时点 = 上期评估时点
        measure1CfInfoService.getLastValMonth(measureCfBasicData, measureCfResultInfo, evaluateMethod.getCode());
        //3.计量单元编号 = 计量单元编号
        measure1CfInfoService.getUnitId(measureCfBasicData, measureCfResultInfo, evaluateMethod.getCode());
        //4.赠险标签 = 赠险标签
        measure1CfInfoService.getPresentFlag(measureCfBasicData, measureCfResultInfo, evaluateMethod.getCode());
        //5.险种代码 = 险种代码
        measure1CfInfoService.getRiskCode(measureCfBasicData, measureCfResultInfo, evaluateMethod.getCode());
        //6.签单日期 = 签单日期
        measure1CfInfoService.getUnderWriteDate(measureCfBasicData, measureCfResultInfo, evaluateMethod.getCode());
        //7.保修期 = 保修期
        measure1CfInfoService.getWarrantyPeriod(measureCfBasicData, measureCfResultInfo, evaluateMethod.getCode());
        //8.保险责任起期 = 保险责任起期
        measure1CfInfoService.getStartDate(measureCfBasicData, measureCfResultInfo, evaluateMethod.getCode());
        //9.保险评估起期 = 保险评估起期
        measure1CfInfoService.getEvaluateDate(measureCfBasicData, measureCfResultInfo, evaluateMethod.getCode());
        //10.保费总额 = 保费本币
        measure1CfInfoService.getPremiumCny(measureCfBasicData, measureCfResultInfo, evaluateMethod.getCode());
        //11.投资成分占比 = 投资成分占比
        measure1CfInfoService.getInvestProp(measureCfBasicData, measureCfResultInfo, evaluateMethod.getCode());
        //12.合同组合编号 = 合同组合编号
        measure1CfInfoService.getPortfolioId(measureCfBasicData, measureCfResultInfo, evaluateMethod.getCode());
        //13.保险获取现金流_本币 = 保险获取现金流_本币
        measure1CfInfoService.getIacfFolCny(measureCfBasicData, measureCfResultInfo, evaluateMethod.getCode());
        //14.币种 = 币种
        measure1CfInfoService.getCurrency(measureCfBasicData, measureCfResultInfo, evaluateMethod.getCode());
        //15.合同分组编号 = 合同组合编号
        measure1CfInfoService.getGroupId(measureCfBasicData, measureCfResultInfo, evaluateMethod.getCode());
        //16.是否当期新单
        measure1CfInfoService.getWhetherCurPolicy(measureCfBasicData, measureCfResultInfo, evaluateMethod.getCode());
        //17.保险责任止期 = 保险责任止期
        measure1CfInfoService.getEndDate(measureCfBasicData, measureCfResultInfo, evaluateMethod.getCode());
        //18.保障期限 = 保障期限
        measure1CfInfoService.getTerm(measureCfBasicData, measureCfResultInfo, evaluateMethod.getCode());
        //19.归属机构 = 归属机构
        measure1CfInfoService.getComCode(measureCfBasicData, measureCfResultInfo, evaluateMethod.getCode());
        //20.业务渠道 = 业务渠道
        measure1CfInfoService.getBusinessNature(measureCfBasicData, measureCfResultInfo, evaluateMethod.getCode());
        //21.条款险别段 = 条款险别段
        measure1CfInfoService.getCoverageSegment(measureCfBasicData, measureCfResultInfo, evaluateMethod.getCode());
        //22.车辆种类 = 车辆种类
        measure1CfInfoService.getCarKindCode(measureCfBasicData, measureCfResultInfo, evaluateMethod.getCode());
        //23.使用性质代码 = 使用性质代码
        measure1CfInfoService.getUseNatureCode(measureCfBasicData, measureCfResultInfo, evaluateMethod.getCode());
        //24.评估方法 = 评估方法
        measure1CfInfoService.getValMethod(measureCfBasicData, measureCfResultInfo, evaluateMethod.getCode());
        //48.保险获取现金流_本币_再保
        measure1CfInfoService.getIacfFolCnyRein(measureCfBasicData, measureCfResultInfo);
        //49.实际获取费用_再保
        measure1CfInfoService.getIacfActualRein(measureCfBasicData, measureCfResultInfo);
        //50.险类代码
        measure1CfInfoService.getClassCode(measureCfBasicData, measureCfResultInfo);
        //56.批单签单日期
        measure1CfInfoService.getCertiWriteDate(measureCfBasicData, measureCfResultInfo);
        //25.当期服务量
        measure1CfInfoService.getCurrServAmt(measureCfResultInfo, evaluateMethod.getCode());
        //26.当期及未来服务量
        measure1CfInfoService.getOtherServAmt(measureCfResultInfo, evaluateMethod.getCode());
        //27.当期确认比例
        measure1CfInfoService.getCurRecPct(measureCfResultInfo, evaluateMethod.getCode());
        //28.期初未确认保费
        measure1CfInfoService.getPremBopUnRecAmt(measureCfBasicData, measureInfoCache.getOrDefault(measureCfBasicData.getUnitId(),new HashMap<>()), measureCfResultInfo);
        //29.期初保费计息
        measure1CfInfoService.getPremInterestAmt(measureCfResultInfo);
        //30.当期确认的保费
        measure1CfInfoService.getPremCurRecAmt(measureCfResultInfo, evaluateMethod.getCode());
        //31.期末未确认保费
        measure1CfInfoService.getPremEopUnRecAmt(measureCfResultInfo, evaluateMethod.getCode());
        //33.1.实际获取费
        measure1CfInfoService.getIacfActual(measureCfResultInfo, measureCfBasicData);
        //32.期初未确认的IACF-a
        measure1CfInfoService.getIacfBopUnRecAmt(measureInfoCache.getOrDefault(measureCfBasicData.getUnitId(),new HashMap<>()), measureCfResultInfo, evaluateMethod.getCode());
        //33.IACF计息-a
        measure1CfInfoService.getIacfInterestAmt(measureCfResultInfo, evaluateMethod.getCode());

        //34.当期确认的IACF-a
        measure1CfInfoService.getIacfAmortAmt(measureCfResultInfo, evaluateMethod.getCode());
        //35.期末未确认IACF-a
        measure1CfInfoService.getIacfEopUnRec(measureCfResultInfo, evaluateMethod.getCode());
        //36.期初未确认的投资成分-a
        measure1CfInfoService.getIcBopUnRecAmt(measureInfoCache.getOrDefault(measureCfBasicData.getUnitId(),new HashMap<>()), measureCfResultInfo, evaluateMethod.getCode());
        //37.期初投资成分计息-a
        measure1CfInfoService.getIcInterestAmt(measureCfResultInfo, evaluateMethod.getCode());
        //38.当期确认的投资成分-a
        measure1CfInfoService.getIcPaidAmt(measureCfResultInfo, evaluateMethod.getCode());
        //39.期末未确认的投资成分-a
        measure1CfInfoService.getIcEopUnRecAmt(measureCfResultInfo, evaluateMethod.getCode());
        //40.保险合同收入-a
        measure1CfInfoService.getIsrAmt(measureCfResultInfo, evaluateMethod.getCode());
        //41.IFIE未到期利息-a
        measure1CfInfoService.getLrcIfieAmt(measureCfResultInfo, evaluateMethod.getCode());
        //42.未到期责任负债-非亏损部分-a
        measure1CfInfoService.getLrcNoLcAmt(measureCfResultInfo, evaluateMethod.getCode());
        //43.未经过保费-a
        measure1CfInfoService.getUnRecPremAmt(measureCfResultInfo, evaluateMethod.getCode());
        //44.预期未来现金流现值-a+
        measure1CfInfoService.getPvRepAmt(measureCfResultInfo, evaluateMethod.getCode(), measureCfBasicData);
        //45.未到期_非金融风险性调整-a+
        measure1CfInfoService.getLrcRaAmt(measureCfResultInfo, evaluateMethod.getCode());
        //46.保单号
        measure1CfInfoService.getPolicyNo(measureCfBasicData, measureCfResultInfo);
        //47.批单号
        measure1CfInfoService.getCertiNo(measureCfBasicData, measureCfResultInfo);
        //51.期初未确认的IACF_再保
        measure1CfInfoService.getIacfBopUnRecAmtRein(measureInfoCache.getOrDefault(measureCfBasicData.getUnitId(),new HashMap<>()), measureCfResultInfo);
        //52.IACF计息_再保
        measure1CfInfoService.getIacfInterestAmtRein(measureCfResultInfo);
        //53.当期确认的IACF_再保
        measure1CfInfoService.getIacfAmortAmtRein(measureCfResultInfo);
        //54.期末未确认IACF_再保
        measure1CfInfoService.getIacfEopUnRecRein(measureCfResultInfo);
        //55.未到期责任负债-非亏损部分_再保
        measure1CfInfoService.getLrcNoLcAmtRein(measureCfResultInfo);
        // 分摊因子  新增字段-2025/07/31
        // 如果10.保费-本币>=0，则分摊因子=max(44.预期未来现金流现值+45.未到期-非金融风险调整-42.未到期责任负债-非亏损部分,0)
        // 如果10.保费-本币<0，则分摊因子=min(44.预期未来现金流现值+45.未到期-非金融风险调整-42.未到期责任负债-非亏损部分,0)
        BigDecimal shareFactorBase = measureCfResultInfo.getPvRepAmt().add(measureCfResultInfo.getLrcRaAmt()).subtract(measureCfResultInfo.getLrcNoLcAmt());
        if (measureCfResultInfo.getPremiumCny().compareTo(BigDecimal.ZERO) >= 0) {
            measureCfResultInfo.setShareFactor(shareFactorBase.max(BigDecimal.ZERO));
        } else {
            measureCfResultInfo.setShareFactor(shareFactorBase.min(BigDecimal.ZERO));
        }
        
        // 分摊因子_再保  新增字段-2025/07/31
        // 如果10.保费-本币>=0，则分摊因子_再保=max(44.预期未来现金流现值+45.未到期-非金融风险调整-54.未到期责任负债-非亏损部分_再保,0)
        // 如果10.保费-本币<0，则分摊因子_再保=min(44.预期未来现金流现值+45.未到期-非金融风险调整-54.未到期责任负债-非亏损部分_再保,0)
        BigDecimal shareFactorReinBase = measureCfResultInfo.getPvRepAmt().add(measureCfResultInfo.getLrcRaAmt()).subtract(measureCfResultInfo.getLrcNoLcAmtRein());
        if (measureCfResultInfo.getPremiumCny().compareTo(BigDecimal.ZERO) >= 0) {
            measureCfResultInfo.setShareFactorRein(shareFactorReinBase.max(BigDecimal.ZERO));
        } else {
            measureCfResultInfo.setShareFactorRein(shareFactorReinBase.min(BigDecimal.ZERO));
        }
        return measureCfResultInfo;
      }).collect(Collectors.toList());
      long endTime = System.currentTimeMillis();
      log.error("===============明细处理耗时:{}秒", (endTime- startTime)/1000);
      measureCfResultInfoMapper.insertBatch(measureCfResultInfoList);
      log.error("===============明细插入数据库耗时:{}秒", (System.currentTimeMillis()- endTime)/1000);
    }catch (Exception e) {
      throw new RuntimeException(e);
    }finally {
      latch.countDown();
    }
  }

  @Override
  public void doOperation(List<MeasureCfBasicData> measureCfBasicDataList, EvaluateMethodTypeEnum evaluateMethod, String valMonth) {

  }

}
