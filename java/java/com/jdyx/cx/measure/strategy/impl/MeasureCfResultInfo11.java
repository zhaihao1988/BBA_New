package com.jdyx.cx.measure.strategy.impl;

import cn.hutool.core.lang.Opt;
import com.google.common.collect.Lists;
import com.jdyx.common.enums.EvaluateMethodTypeEnum;
import com.jdyx.common.measure.constant.StringConstant;
import com.jdyx.common.measure.service.MeasureCommonCacheService;
import com.jdyx.common.measure.service.MeasurePaa11CfInfoService;
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

import java.math.BigDecimal;
import java.util.*;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.stream.Collectors;

/**
 * 产险-再保-PAA（再保分入，再保分出）
 * EVALUATE_METHOD_TYPE_10 ，EVALUATE_METHOD_TYPE_11
 */
@Slf4j
@RequiredArgsConstructor
@Service
public class MeasureCfResultInfo11 extends BaseMeasureCxService implements MeasureCfResultInfoStrategy {

  private final MeasurePaa11CfInfoService measurePaa11CfInfoService;
  private final ThreadPoolExecutor threadPoolExecutor;
  private final MeasureCommonCacheService measureCommonCacheService;

  @Override
  @Async("threadPoolExecutor")
  public void doOperation(List<MeasureCfBasicData> measureCfBasicDataList, EvaluateMethodTypeEnum evaluateMethod, String valMonth, CountDownLatch latch) {
    try {
      if (!Objects.equals(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_11, evaluateMethod) && !Objects.equals(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_10, evaluateMethod)) {
        return;
      }
      log.error("===============线程池队列长度:{}", threadPoolExecutor.getQueue().size());
      long startTime = System.currentTimeMillis();
      //分摊平台数据
      Map<String, BigDecimal> resultAllocationMap;
      if(Objects.equals(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_10, evaluateMethod)){
        resultAllocationMap = measureCommonCacheService.getMeasureAllocationCache(valMonth);
      } else {
        resultAllocationMap = new HashMap<>();
      }

      //获取 上期评估时点 计量明细数据 期末未确认IACF
//      Map<String, MeasureCfResultInfo> lastMeasureCfResultInfoMap = getMeasureCfResultInfoMap(DateUtils.lastEndYear(valMonth, DateUtils.YYYYMM), evaluateMethod.getCode(),
//        MeasureCfResultInfo::getIacfEopUnRec, MeasureCfResultInfo::getIcEopUnRecAmt, MeasureCfResultInfo::getPremEopUnRecAmt, MeasureCfResultInfo::getIacfEopUnRecRein);
      Map<String, Map<String, BigDecimal>> measureInfoCache = measureCommonCacheService.getMeasureInfoCache(evaluateMethod.getCode(),DateUtils.lastEndYear(valMonth, DateUtils.YYYYMM),
        MeasureCfResultInfo::getIacfEopUnRec, MeasureCfResultInfo::getIcEopUnRecAmt, MeasureCfResultInfo::getPremEopUnRecAmt, MeasureCfResultInfo::getIacfEopUnRecRein);

      //线程安全处理
//    List<MeasureCfBasicData> synchronizedList = Collections.synchronizedList(measureCfBasicDataList);

      //遍历计量源数据
      Map<String, BigDecimal> finalResultAllocationMap = resultAllocationMap;
      List<MeasureCfResultInfo> measureCfResultInfoList = Optional.ofNullable(measureCfBasicDataList).orElse(Lists.newArrayList()).stream().map(measureCfBasicData -> {
        //初始化对象
        MeasureCfResultInfo measureCfResultInfo = measurePaa11CfInfoService.iniMeasureCfResultInfo();
        //主键
        measureCfResultInfo.setId(measureCfBasicData.getId());
        //1.当期评估时点
        measurePaa11CfInfoService.getValMonth(measureCfBasicData, measureCfResultInfo);
        //2.上期评估时点
        measurePaa11CfInfoService.getLastValMonth(measureCfBasicData, measureCfResultInfo);
        //3.计量层级编号
        measurePaa11CfInfoService.getUnitId(measureCfBasicData, measureCfResultInfo);
        //4.合约/临分标识
        measurePaa11CfInfoService.getContractFlag(measureCfBasicData, measureCfResultInfo);
        //5.分出类型(再保分出)
        measurePaa11CfInfoService.getReinType(measureCfBasicData, measureCfResultInfo, evaluateMethod);
        //6.临分类型
        measurePaa11CfInfoService.getEnquiryType(measureCfBasicData, measureCfResultInfo);
        //7.合约类型
        measurePaa11CfInfoService.getContractType(measureCfBasicData, measureCfResultInfo);
        //8.合约ID
        measurePaa11CfInfoService.getContractId(measureCfBasicData, measureCfResultInfo);
        //9.合约分项号
        measurePaa11CfInfoService.getSectionNo(measureCfBasicData, measureCfResultInfo);
        //10.超赔层
        measurePaa11CfInfoService.getSectionLayerNo(measureCfBasicData, measureCfResultInfo);
        //11.临分保单号（再保分入），保单号（再保分出）
        measurePaa11CfInfoService.getPolicyNo(measureCfBasicData, measureCfResultInfo);
        //13.分出比例（再保分出）
        measurePaa11CfInfoService.getShareRate(measureCfBasicData, measureCfResultInfo, evaluateMethod);
        //14.批单号
        measurePaa11CfInfoService.getCertiNo(measureCfBasicData, measureCfResultInfo);
        //15.险种代码
        measurePaa11CfInfoService.getRiskCode(measureCfBasicData, measureCfResultInfo);
        //16.签单日期
        measurePaa11CfInfoService.getUnderWriteDate(measureCfBasicData, measureCfResultInfo);
        //17.批单生效日
        measurePaa11CfInfoService.getModifyDate(measureCfBasicData, measureCfResultInfo);
        //18.保险责任起期
        measurePaa11CfInfoService.getStartDate(measureCfBasicData, measureCfResultInfo);
        //19.保费-本币
        measurePaa11CfInfoService.getPremiumCny(measureCfBasicData, measureCfResultInfo, evaluateMethod);
        //24.手续费_本币
        measurePaa11CfInfoService.getCommission(measureCfBasicData, measureCfResultInfo, evaluateMethod);
        //20.不含税净分出保费（再保分出）
        measurePaa11CfInfoService.getNetPremiumCny(measureCfBasicData, measureCfResultInfo, evaluateMethod);
        //21.投资成分占比
        measurePaa11CfInfoService.getInvestProp(measureCfBasicData, measureCfResultInfo, evaluateMethod);
        //22.合同组合编码
        measurePaa11CfInfoService.getPortfolioId(measureCfBasicData, measureCfResultInfo);
        //23.保险获取现金流_本币（再保分入）
        measurePaa11CfInfoService.getIacfFolCny(measureCfBasicData, measureCfResultInfo, evaluateMethod);
        //25.不含税经纪费_本币（再保分入）
        measurePaa11CfInfoService.getBrokerageFee(measureCfBasicData, measureCfResultInfo, evaluateMethod);
        //26.币种
        measurePaa11CfInfoService.getCurrency(measureCfBasicData, measureCfResultInfo);
        //27.合同分组编码
        measurePaa11CfInfoService.getGroupId(measureCfBasicData, measureCfResultInfo);
        //28.是否当期新单
        measurePaa11CfInfoService.getWhetherCurPolicy(measureCfBasicData, measureCfResultInfo);
        //29.保险责任止期
        measurePaa11CfInfoService.getEndDate(measureCfBasicData, measureCfResultInfo);
        //30.保障期限
        measurePaa11CfInfoService.getTerm(measureCfBasicData, measureCfResultInfo);
        //31.归属机构
        measurePaa11CfInfoService.getComCode(measureCfBasicData, measureCfResultInfo);
        //32.车辆种类
        measurePaa11CfInfoService.getCarKindCode(measureCfBasicData, measureCfResultInfo);
        //33.使用性质代码
        measurePaa11CfInfoService.getUseNatureCode(measureCfBasicData, measureCfResultInfo);
        //34.评估方法
        measurePaa11CfInfoService.getValMethod(measureCfBasicData, measureCfResultInfo);
        //57.实际获取费用(再保分入)
        measurePaa11CfInfoService.getIacfActual(measureCfBasicData, measureCfResultInfo, evaluateMethod);
        //58.保险获取现金流_本币_再保(再保分入)
        measurePaa11CfInfoService.getIacfFolCnyRein(measureCfBasicData, measureCfResultInfo, evaluateMethod);
        //59.实际获取费用_再保(再保分入)
        measurePaa11CfInfoService.getIacfActualRein(measureCfBasicData, measureCfResultInfo, evaluateMethod);
        //60.险类代码
        measurePaa11CfInfoService.getClassCode(measureCfBasicData, measureCfResultInfo);
        //66.确认时间(再保分入)
        measurePaa11CfInfoService.getConfirmDate(measureCfBasicData, measureCfResultInfo, evaluateMethod);
        //67.批单签单日期(再保分出)
        measurePaa11CfInfoService.getCertiWriteDate(measureCfBasicData, measureCfResultInfo, evaluateMethod);
        //35.当期服务量
        measurePaa11CfInfoService.getCurrServAmt(measureCfResultInfo);
        //36.当期及未来服务量
        measurePaa11CfInfoService.getOtherServAmt(measureCfResultInfo);
        //37.当期确认比例
        measurePaa11CfInfoService.getCurRecPct(measureCfResultInfo);
        //38.期初未确认保费
        measurePaa11CfInfoService.getPremBopUnRecAmt(measureCfBasicData, measureCfResultInfo, measureInfoCache.getOrDefault(measureCfBasicData.getUnitId(),new HashMap<>()), evaluateMethod);
        //39.期初保费计息
        measurePaa11CfInfoService.getPremInterestAmt(measureCfResultInfo);
        //40.当期确认的保费
        measurePaa11CfInfoService.getPremCurRecAmt(measureCfResultInfo);
        //41.期末未确认的保费
        measurePaa11CfInfoService.getPremEopUnRecAmt(measureCfResultInfo);
        //42.期初未确认的IACF（再保分入）
        measurePaa11CfInfoService.getIacfBopUnRecAmt(measureCfResultInfo, measureInfoCache.getOrDefault(measureCfBasicData.getUnitId(),new HashMap<>()), evaluateMethod);
        //43.IACF计息（再保分入）
        measurePaa11CfInfoService.getIacfInterestAmt(measureCfResultInfo, evaluateMethod);
        //44.当期确认的IACF（再保分入）
        measurePaa11CfInfoService.getIacfAmortAmt(measureCfResultInfo, evaluateMethod.getCode());
        //45.期末未确认IACF（再保分入）
        measurePaa11CfInfoService.getIacfEopUnRec(measureCfResultInfo, evaluateMethod.getCode());
        //46.期初未确认的投资成分
        measurePaa11CfInfoService.getIcBopUnRecAmt(measureCfResultInfo, measureInfoCache.getOrDefault(measureCfBasicData.getUnitId(),new HashMap<>()), evaluateMethod);
        //47.期初投资成分计息
        measurePaa11CfInfoService.getIcInterestAmt(measureCfResultInfo);
        //48.当期确认的投资成分
        measurePaa11CfInfoService.getIcPaidAmt(measureCfResultInfo);
        //49.期末未确认的投资成分
        measurePaa11CfInfoService.getIcEopUnRecAmt(measureCfResultInfo);
        //50.保险合同收入
        measurePaa11CfInfoService.getIsrAmt(measureCfResultInfo);
        //51.IFIE未到期利息
        measurePaa11CfInfoService.getLrcIfieAmt(measureCfResultInfo, evaluateMethod);
        //52.未到期责任负债-非亏损部分(再保分入,再保分出)
        measurePaa11CfInfoService.getLrcNoLcAmt(measureCfResultInfo, evaluateMethod);
        //53.未经过保费(再保分入,再保分出)
        measurePaa11CfInfoService.getUnRecPremAmt(measureCfResultInfo, evaluateMethod);
        //54.预期未来现金流现值(再保分入,再保分出)
        measurePaa11CfInfoService.getPvRepAmt(measureCfResultInfo, measureCfBasicData, evaluateMethod);
        //55.未到期-金融风险调整(再保分入,再保分出)
        measurePaa11CfInfoService.getLrcRaAmt(measureCfResultInfo, evaluateMethod);
        //56.亏损摊回部分（再保分出）
        String key = StringUtils.joinWith("_", Opt.ofBlankAble(measureCfResultInfo.getPolicyNo()).orElse(StringConstant.STRING_NA), Opt.ofBlankAble(measureCfResultInfo.getCertiNo()).orElse(StringConstant.STRING_NA),
          Opt.ofBlankAble(measureCfResultInfo.getRiskCode()).orElse(StringConstant.STRING_NA));
        measurePaa11CfInfoService.setLrcLcChangeAmt(measureCfResultInfo, evaluateMethod, finalResultAllocationMap.get(key));
        //61.期初未确认的IACF_再保(再保分入)
        measurePaa11CfInfoService.getIacfBopUnRecAmtRein(measureCfResultInfo, measureInfoCache.getOrDefault(measureCfBasicData.getUnitId(),new HashMap<>()), evaluateMethod);
        //62.IACF计息_再保(再保分入)
        measurePaa11CfInfoService.getIacfInterestAmtRein(measureCfResultInfo, evaluateMethod);
        //63.当期确认的IACF_再保(再保分入)
        measurePaa11CfInfoService.getIacfAmortAmtRein(measureCfResultInfo, evaluateMethod);
        //64.期末未确认IACF_再保(再保分入)
        measurePaa11CfInfoService.getIacfEopUnRecRein(measureCfResultInfo, evaluateMethod);
        //65.未到期责任负债-非亏损部分_再保(再保分入)
        measurePaa11CfInfoService.getLrcNoLcAmtRein(measureCfResultInfo, evaluateMethod);
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
      log.error("===============评估方法;{},明细处理耗时:{}秒",evaluateMethod.getCode(), (endTime- startTime)/1000);
      measureCfResultInfoMapper.insertBatch(measureCfResultInfoList);
      log.error("===============评估方法;{},明细插入数据库耗时:{}秒",evaluateMethod.getCode(), (System.currentTimeMillis()- endTime)/1000);
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
