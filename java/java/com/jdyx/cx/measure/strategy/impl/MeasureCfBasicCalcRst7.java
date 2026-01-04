package com.jdyx.cx.measure.strategy.impl;

import cn.hutool.core.date.DateUtil;
import com.jdyx.common.cache.measure.ConfMeasureCommonDisrateCacheService;
import com.jdyx.common.dataplatform.service.CxPublicDbService;
import com.jdyx.common.enums.EvaluateMethodTypeEnum;
import com.jdyx.common.measure.constant.StringConstant;
import com.jdyx.common.measure.tools.UtilsCommon;
import com.jdyx.cx.measure.service.BaseMeasureCxService;
import com.jdyx.cx.measure.strategy.MeasureCfBbaBasicCalcRstStrategy;
import com.jdyx.measure.api.measure.domain.MeasureCfBasicData;
import com.jdyx.measure.api.measure.domain.MeasureCfBbaBasicCalcRst;
import com.jdyx.measure.api.measure.domain.MeasureConfBbaBeginInterestCalculation;
import com.jdyx.measure.api.measure.service.IMeasureCfBbaBasicCalcRstService;
import com.jdyx.measure.api.measure.service.IMeasureConfBbaBeginInterestCalculationService;
import com.jdyx.measureprepare.api.domain.*;
import com.kevin.common.utils.DateUtils;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.*;

import static com.kevin.common.utils.DateUtils.YYYYMMDD;

/**
 * @author lzl
 * @version 1.0
 * @description: 获取直保BAA实际现金流数据
 * @date 2024/12/17
 */
@Slf4j
@RequiredArgsConstructor
@Service
public class MeasureCfBasicCalcRst7 extends BaseMeasureCxService implements MeasureCfBbaBasicCalcRstStrategy{

  private final CxPublicDbService cxPublicDbService;
  /* 通用利率配置缓存服务 */
  private final ConfMeasureCommonDisrateCacheService confMeasureCommonDisrateCacheService;
  /* 计息日期配置表_期初 */
  private final IMeasureConfBbaBeginInterestCalculationService measureConfBbaBeginInterestCalculationService;
  /* 直保BBA实际现金流 */
  private final IMeasureCfBbaBasicCalcRstService measureCfBbaBasicCalcRstService;


  @Override
  public List<MeasureCfBbaBasicCalcRst> doOperation(List<MeasureCfBasicData> measureCfBasicDataList, String valMethod, String valMonth) {
    log.info("直保BBA实际现金流【{}】...startEvaluate", valMonth);

    Date endMothDate = DateUtils.endMonth(valMonth);

    //获取保险获取现金流_跟单_本币数据  <unitId, 保险获取现金流_跟单_本币>
    Map<String, BigDecimal> ppJlIacfFolMap = getPpJlIacfFolMap(valMonth, valMethod, TPpJlIacfFol::getIacfFolCny);

    //保险获取现金流_非跟单_本币(根据当前评估日期的年份=当期评估时点的年份进行汇总)
    Map<String, BigDecimal> ppJlIacfUnfolMap = getPpJlIacfUnfolMap(valMonth, valMethod, TPpJlIacfUnfol::getIacfOutUnfolCny);

    //保险获取现金流_非跟单_实际维持费用(根据当前评估日期的年份=当期评估时点的年份进行汇总)
    Map<String, BigDecimal> ppJlIacfUnfolAndMaintenanceMap = getPpJlIacfUnfolMap(valMonth, valMethod, TPpJlIacfUnfol::getMaintenanceRealCny);

    // g.产险直保计量_已决间接理赔费用-t_pp_jl_ulae_settled  ulae_settled_past_cny + ulae_settled_curr_cny
    Map<String, BigDecimal> ppJlUlaeSettledMap = getPpJlUlaeSettledSum(valMethod, valMonth, TPpJlUlaeSettled::getUlaeSettledPastCny, TPpJlUlaeSettled::getUlaeSettledCurrCny);


    List<MeasureCfBbaBasicCalcRst> resList = new ArrayList<>();
    for (MeasureCfBasicData m : measureCfBasicDataList) {
      MeasureCfBbaBasicCalcRst entity = new MeasureCfBbaBasicCalcRst();
      //1.当期评估时点
      entity.setValMonth(m.getValMonth());
      //2 上期评估时点
      entity.setLastValMonth(m.getLastValMonth());
      //3计量单元编号
      entity.setUnitId(m.getUnitId());
      //4 险种代码
      entity.setRiskCode(m.getRiskCode());
      //5 签单日期
      entity.setUnderWriteDate(m.getUnderWriteDate());
      //6 保修期
      entity.setWarrantyPeriod(m.getWarrantyPeriod());
      //7 保险责任起期
      entity.setStartDate(m.getStartDate());
      //8 保险评估起期
      entity.setEvaluateDate(m.getEvaluateDate());
      //9 保费-本币
      entity.setPremiumCny(m.getPremiumCny());
      //10 投资成分占比
      entity.setInvestProp(m.getInvestProp());
      //11 合同组合编码
      entity.setPortfolioId(m.getPortfolioId());
      //12 保险获取现金流_本币
      entity.setIacfFolCny(m.getIacfFolCny());
      //13 币种
      entity.setCurrency(m.getCurrency());
      //14 合同分组编码
      entity.setGroupId(m.getGroupId());
      //15 是否当期新单
      entity.setWhetherCurPolicy(m.getWhetherCurPolicy());
      //16 保险责任止期
      entity.setEndDate(m.getEndDate());
      //17 保障期限
      entity.setTerm(m.getTerm());
      //18 归属机构
      entity.setComCode(m.getComCode());
      //19 业务渠道
      entity.setBusinessNature(m.getBusinessNature());
      //20 车辆种类
      entity.setCarKindCode(m.getCarKindCode());
      //21 使用性质代码
      entity.setUseNatureCode(m.getUseNatureCode());
      //22 评估方法
      entity.setValMethod(valMethod);
      // 30 当期评估时点的期初评估时点
      // 如果 是否当期新单=1,则= 保险责任起期
      // 如果 是否当期新单=0，则=date(year(1.当期评估时点),1,1)
      String openingValDate = "1".equals(entity.getWhetherCurPolicy()) ? entity.getStartDate() :
        DateUtils.beginYearMonth(entity.getValMonth(), YYYYMMDD);

      entity.setFirstValMonth(openingValDate);
      // 23 实际保费收入
      // 公共库(产险)-产险直保计量_实收实付_保费手续费
      TPpJlActualRecPayPremFee ppJlActualRecPayPremFee = cxPublicDbService.getPpJlActualRecPayPremFeeByUnitId(endMothDate, EvaluateMethodTypeEnum.getEnumType(valMethod).getText(), entity.getUnitId());
      // 当月收取保费_本币
      BigDecimal recPayPremFeePremInCny = Objects.isNull(ppJlActualRecPayPremFee) ?BigDecimal.ZERO : ppJlActualRecPayPremFee.getPremInCny();

      entity.setActlPremInc(recPayPremFeePremInCny);

      //24  实际发生IACF(b保险获取现金流,跟单 本币+ 汇总的g.保险获取现金流 非跟单 本币(根据当前评估日期的年份=当期评估时点的年份进行汇总)
      entity.setActlIacfOut(ppJlIacfFolMap.containsKey(entity.getUnitId()) ? ppJlIacfFolMap.get(entity.getUnitId()).add(Optional.ofNullable(ppJlIacfUnfolMap.get(entity.getUnitId())).orElse(BigDecimal.ZERO)) : BigDecimal.ZERO);

      //25 实际发生赔款
      TPpJlClmSettled clmSettled = cxPublicDbService.getPpJlClmSettledByUnitId(entity.getUnitId());
      BigDecimal settledLoss = Objects.isNull(clmSettled) ? BigDecimal.ZERO : clmSettled.getSettledLossPastCny().add(clmSettled.getSettledLossCurrCny());

      entity.setSettledLoss(settledLoss);

      //26 期初投资成分
      // "如果15.是否当期新单=1 , =9.保费-本币*10.投资成分占比
      // 如果15.是否当期新单 = 0 , =上期29.期末未确认的投资成分"
      if ("1".equals(entity.getWhetherCurPolicy())) {
        entity.setIcBopUnRecAmt(entity.getPremiumCny().multiply(entity.getInvestProp()).setScale(10, RoundingMode.HALF_UP));
      } else{
        // 上期29.期末未确认的投资成分(当期评估时点=上期期末，相同计量单元编号)
        MeasureCfBbaBasicCalcRst measureCfBbaBasicCalcRst = measureCfBbaBasicCalcRstService.selectUnRecAmt(
            entity.getLastValMonth(), entity.getUnitId());
        entity.setIcBopUnRecAmt(Objects.isNull(measureCfBbaBasicCalcRst) ? BigDecimal.ZERO : measureCfBbaBasicCalcRst.getIcEopUnRecAmt());
      }

      /**
       * 27 期初投资成分计息
       * =26.ic_bop_un_rec_amt*(c.评估月对应30.当期评估时点的期初评估时点，预测月度对应编号的利率)^((e.对应编号且对应计量单元编号的计息日期-1.当前评估时点+1)/365)
       * 备注：这一条编号从(year(1.当期评估时点)-year(55.当期评估时点的期初评估时点))*12+month(1.当期评估时点)-month(55.当期评估时点的期初评估时点)+1
       */

      // 备注：这一条编号从(year(1.当期评估时点)-year(55.当期评估时点的期初评估时点))*12+month(1.当期评估时点)-month(55.当期评估时点的期初评估时点)+1
      long termMonth = (DateUtil.year(DateUtils.parseDate(entity.getValMonth()))
                      - DateUtil.year(DateUtils.parseDate(openingValDate)) * 12L
                     + DateUtil.month(DateUtils.parseDate(entity.getValMonth()))
                     - DateUtil.month(DateUtils.parseDate(openingValDate)) + 1L);

      MeasureConfBbaBeginInterestCalculation beginInterestCalculation = measureConfBbaBeginInterestCalculationService
          // ValMonth yyyyMMdd
          .selDataByUnitIdValMonth(entity.getUnitId(), entity.getValMonth(), termMonth);

      // =.ic_bop_un_rec_amt*(f.对应55.当期评估时点的期初评估时点的编号的利率)^((e.对应编号且对应计量单元编号的计息日期-1.当前评估时点+1)/365)
      BigDecimal disRate = confMeasureCommonDisrateCacheService.getConfMeasureCommonDisRate(entity.getValMethod(), openingValDate.substring(0,6), StringConstant.STRING_NA, StringConstant.STRING_NA, termMonth);

      BigDecimal ratePow;
      if (Objects.isNull(beginInterestCalculation) || disRate.equals(BigDecimal.ZERO)) {
        ratePow = BigDecimal.ZERO;
      }else{
        ratePow = UtilsCommon.calculateRatePow(disRate, beginInterestCalculation.getDutyPeriodValue(), DateUtils.endMonth(entity.getValMonth(), YYYYMMDD), BigDecimal.ONE);
      }

      entity.setIcInterestAmt(entity.getIcBopUnRecAmt().multiply(ratePow).setScale(10, RoundingMode.HALF_UP));


      //28 实际赔付的投资成分
      BigDecimal totalInterest = entity.getIcBopUnRecAmt().add(entity.getIcInterestAmt());
      entity.setActlClmOutInv(entity.getSettledLoss().subtract(totalInterest).compareTo(BigDecimal.ZERO) <= 0 ?
        entity.getSettledLoss(): totalInterest);
      //29 期末未确认的投资成分
      entity.setIcEopUnRecAmt(entity.getIcBopUnRecAmt().add(entity.getIcInterestAmt()).subtract(entity.getActlClmOutInv()));

      // 34	实际维持费用	actl_me_out
      entity.setActlMeOut(ppJlIacfUnfolAndMaintenanceMap.getOrDefault(entity.getUnitId(), BigDecimal.ZERO));

      // 35	实际赔付的保险成分	actl_clm_out_ins =25.settled_loss- 28.actl_clm_out_inv
      entity.setActlClmOutIns(entity.getSettledLoss().subtract(entity.getActlClmOutInv()));

      // 36	已决间接理赔费用	ulae
      entity.setUlae(ppJlUlaeSettledMap.getOrDefault(entity.getUnitId(), BigDecimal.ZERO));



      resList.add(entity);
    }
    log.info("直保BBA实际现金流...endEvaluate");
    return resList;
  }
}
