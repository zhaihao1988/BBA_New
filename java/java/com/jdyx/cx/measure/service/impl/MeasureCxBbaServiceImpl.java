package com.jdyx.cx.measure.service.impl;

import cn.hutool.core.collection.CollectionUtil;
import cn.hutool.core.date.DateUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.conditions.query.LambdaQueryChainWrapper;
import com.jdyx.common.cache.measure.ConfMeasureCommonDisrateCacheService;
import com.jdyx.common.enums.EvaluateMethodTypeEnum;
import com.jdyx.common.measure.constant.StringConstant;
import com.jdyx.cx.measure.service.BaseMeasureCxService;
import com.jdyx.cx.measure.service.MeasureCxBbaService;
import com.jdyx.measure.api.measure.domain.*;
import com.jdyx.measure.api.measure.mapper.*;
import com.jdyx.measure.api.measure.service.IConfMeasureBbaNettingService;
import com.jdyx.measure.api.measure.service.IMeasureCfBbaBasicCalcRstService;
import com.jdyx.measure.api.measure.service.IMeasureCfBbaExpRstService;
import com.jdyx.measure.api.measure.service.IMeasureResultBbaCoreService;
import com.kevin.common.core.domain.R;
import com.kevin.common.utils.DateUtils;
import com.kevin.common.utils.StringUtils;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import javax.annotation.Resource;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.*;

import static com.kevin.common.utils.DateUtils.YYYYMMDD;


/**
 * BBA模型
 *
 * @author cjn
 * @date 2024/12/26.
 */
@SuppressWarnings("DuplicatedCode")
@Slf4j
@RequiredArgsConstructor
@Service
public class MeasureCxBbaServiceImpl extends BaseMeasureCxService implements MeasureCxBbaService {
  @Resource
  private MeasureCfBbaExpRstMapper measureCfBbaExpRstMapper;
  @Resource
  private ConfMeasureCsmInterestMapper confMeasureCsmInterestMapper;
  @Autowired
  private IMeasureResultBbaCoreService measureResultBbaCoreService;
  @Autowired
  private IMeasureCfBbaBasicCalcRstService measureCfBbaBasicCalcRstService;
  @Autowired
  private IConfMeasureBbaNettingService confMeasureBbaNettingService;
  @Autowired
  private IMeasureCfBbaExpRstService measureCfBbaExpRstService;
  @Autowired
  private MeasureResultBbaCoreMapper measureResultBbaCoreMapper;
  @Autowired
  private ConfMeasureCommonDisrateCacheService confMeasureCommonDisrateCacheService;

  /**
   * BBA核心计量计算
   * @param valMethod 评估方法，默认BBA-7
   * @param valMonth 评估月
   * @return
   */
  @Override
  public R<?> setCxMeasureResultBbaCore(String valMethod, String valMonth) {
    //根据合同分组 汇总查询bba预期现金流数据
    List<MeasureCfBbaExpRst> bbaExpRstDataByGroupIdAndDate = measureCfBbaExpRstMapper.getBbaExpRstDataByGroupIdAndDate(valMonth, valMethod);
    //根据合同分组、是否当期新单 汇总查询bba预期现金流数据
    Map<String, MeasureCfBbaExpRst> measureCfBbaExpRstByGroupAndPolicy = measureCfBbaExpRstService.getMeasureCfBbaExpRstByGroupAndPolicy(valMonth, valMethod);
    //上期 根据合同分组 汇总bba核心计量数据
    Map<String, MeasureResultBbaCore> lastValMonthCore = measureResultBbaCoreService.getBbaResultCoreByGroupId(DateUtils.lastEndYear(valMonth, DateUtils.YYYYMM).substring(0,6));
    //当月 根据合同分组 汇总bba实际现金流
    Map<String, MeasureCfBbaBasicCalcRst> bbaBasicCalcRstMap = measureCfBbaBasicCalcRstService.getBbaBasicCalcRstByGroupId(valMonth);
    //计量轧差表
    Map<String, ConfMeasureBbaNetting> bbaNettingMap = confMeasureBbaNettingService.getBbaNettingByGroupId(valMonth);

    List<MeasureResultBbaCore> bbaCoreList = new ArrayList<>();
    bbaExpRstDataByGroupIdAndDate.forEach(r->{
      MeasureResultBbaCore measureResultBbaCore = new MeasureResultBbaCore();
      //1.当期评估时点
      getValMonth(measureResultBbaCore,r);
      //2.上期评估时点
      getLastValMonth(measureResultBbaCore,r);
      //3.合同分组编码
      getGroupId(measureResultBbaCore,r);
      //4.上一期期末CSM
      getCsmIf(measureResultBbaCore,r,lastValMonthCore);
      //5.当期新单CSM
      getInitCsmNb(measureResultBbaCore,r);
      //6.计息前CSM
      getCsmBfInv(measureResultBbaCore,r);
      //7.当期CSM的计息
      getCsmIntAccret(measureResultBbaCore,r);
      //8.计息后的CSM
      getCsmAfInv(measureResultBbaCore,r);
      //9.CSM总吸收项
      getCsmAdjTot(measureResultBbaCore,r,bbaBasicCalcRstMap,bbaNettingMap);

      //12.期初LC
      getLcIf(measureResultBbaCore,r,lastValMonthCore);
      //13.当期新单LC
      getInitLcNb(measureResultBbaCore,r);
      //14.计息前的LC
      getLcBfInv(measureResultBbaCore,r);
      //15.LC的部分计息
      getLcIntAccretPl(measureResultBbaCore,r,measureCfBbaExpRstByGroupAndPolicy);
      //16.计息后的LC
      getLcAfInv(measureResultBbaCore,r);
      //26.分摊前的LC
      getLcBfAmort(measureResultBbaCore,r);
      //27.当期LC分摊比例
      getLcAmortRate(measureResultBbaCore,r);
      //28.LC当期分摊(不含期末分摊调整）
      getLcAmortAmt(measureResultBbaCore,r);
      //29.LC摊后余额
      getLcAfAmort(measureResultBbaCore,r);
      //10.损失后续确认和转回RA占比
      getCsmAdjRaProp(measureResultBbaCore,r,bbaNettingMap);
      //11.损失后续确认和转回BEL占比
      getCsmAdjBelProp(measureResultBbaCore,r);
      //17.CSM调整项
      getCsmAdjAmt(measureResultBbaCore,r);
      //18.摊销前的CSM
      getCsmBfAmort(measureResultBbaCore,r);
      //19.当期CSM摊销比例
      getCsmReleaseRate(measureResultBbaCore,r);
      //20.CSM当期摊销额
      getCsmRelease(measureResultBbaCore,r);
      //21.CSM摊后余额
      getCsmAfAmort(measureResultBbaCore,r);
      //22.CSM期末值
      getCsmIfEnd(measureResultBbaCore,r);
      //23.损失后续确认和转回
      getLcAdjAmt(measureResultBbaCore,r);
      //24.损失后续确认和转回拆分至bel
      getLcAdjAmtBel(measureResultBbaCore,r);
      //25.损失后续确认和转回拆分至ra
      getLcAdjAmtRa(measureResultBbaCore,r);
      //62.LC余额 lc_amort =29.lc_af_amort-23.lc_adj_amt
      getLcAmort(measureResultBbaCore,r);
      //30.计入其他综合的保险财务损益-GPV
      getExpcIfieGpvOci(measureResultBbaCore,r);
      //31.计入其他综合收益的保险财务损益-RA
      getExpcIfieRaOci(measureResultBbaCore,r);
      //32.OCI分摊至LC部分的比例
      getLcIntOciAllocRate(measureResultBbaCore,r);
      //33.计入其他综合收益的保险财务损益-LC部分
      getLcIntAccretOci(measureResultBbaCore,r);
      //34.LC期末分摊调整
      getLcAmortEnd(measureResultBbaCore,r);
      //35.亏损合同的分摊总数
      getLcAmortTot(measureResultBbaCore,r);
      //36.LC期末余额
      getLcIfEnd(measureResultBbaCore,r);
      //37.上一期期末IACF
      getIacfIf(measureResultBbaCore,r,lastValMonthCore);
      //38.当期新单初始确认的IACF
      getInitIacfNb(measureResultBbaCore,r);
      //39.计息前的IACF
      getIacfBfInv(measureResultBbaCore,r);
      //40.IACF的利息
      getIacfIntAccret(measureResultBbaCore,r);
      //41.计息后的IACF
      getIacfAfInv(measureResultBbaCore,r);
      //42.预期IACF发生数
      getExpcIacfOut(measureResultBbaCore,r);
      //43.财务实际IACF发生数
      getActlIacfOut(measureResultBbaCore,r,bbaBasicCalcRstMap);
      //44.调整后的IACF
      getIacfBfAmort(measureResultBbaCore,r);
      //45.IACF当期摊销比例
      getIacfReleaseRate(measureResultBbaCore,r);
      //46.IACF当期摊销
      getIacfRelease(measureResultBbaCore,r);
      //47.IACF摊后余额
      getIacfAfAmort(measureResultBbaCore,r);
      //48.IACF期末值
      getIacfIfEnd(measureResultBbaCore,r);
      // 49	上一期期末ra
      getRaIf(measureResultBbaCore,r,lastValMonthCore);
      // 50	当期新单初始确认的ra
      getInitRaNb(measureResultBbaCore,r);
      // 51	计息前的ra
      getRaBfInv(measureResultBbaCore);
      // 52	ra的计息
      getRaIntAccret(measureResultBbaCore, r);
      // 54	预期RA 损益表IFIE
      getExpcIfieRaPl(measureResultBbaCore);
      // 55	计息后的ra
      getRaAfInv(measureResultBbaCore);
      // 56	ra当期摊销比例	ra_release_rate
      getRaReleaseRate(measureResultBbaCore,r);
      // 57	ra当期摊销	ra_release
      getRaRelease(measureResultBbaCore);
      // 58	ra摊后余额	ra_af_amort
      getRaAfAmort(measureResultBbaCore);
      // 59	ra的吸收项	ra_adj_tot
      getraAdjTot(measureResultBbaCore,r, bbaNettingMap);
      // 60	调整后的ra	ra_bf_amort
      getRaBfAmort(measureResultBbaCore);
      // 61	ra期末值	ra_if_end
      getRaIfEnd(measureResultBbaCore);
      bbaCoreList.add(measureResultBbaCore);
    });


    // 清除当月旧数据
    measureResultBbaCoreMapper.delete(new LambdaQueryWrapper<MeasureResultBbaCore>()
        .eq(MeasureResultBbaCore::getValMonth, valMonth));

    // 新增
    if (CollectionUtil.isNotEmpty(bbaCoreList)) {
      measureResultBbaCoreMapper.insertBatch(bbaCoreList);
    }

    return R.ok();
  }



  /**
   * LC余额 =29.lc_af_amort-23.lc_adj_amt
   * @param measureResultBbaCore bba core
   * @param r exp
   */
  private void getLcAmort(MeasureResultBbaCore measureResultBbaCore, MeasureCfBbaExpRst r) {
    measureResultBbaCore.setLcAmort(measureResultBbaCore.getLcAfAmort().subtract(measureResultBbaCore.getLcAdjAmt()));
  }

  private void getValMonth(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    measureResultBbaCore.setValMonth(measureCfBbaExpRst.getValMonth());
  }
  private void getGroupId(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    measureResultBbaCore.setGroupId(measureCfBbaExpRst.getGroupId());
  }
  private void getLastValMonth(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    measureResultBbaCore.setLastValMonth(measureCfBbaExpRst.getLastValMonth());
  }

  private void getCsmIf(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst,Map<String, MeasureResultBbaCore> lastValMonthCoreMap) {
    //根据合同分组编码取核心计量表上期评估时点的期末22.csm，如果没有则为0
    MeasureResultBbaCore lastMeasureResultBbaCore = lastValMonthCoreMap.get(measureCfBbaExpRst.getGroupId());
    if(null != lastMeasureResultBbaCore){
      measureResultBbaCore.setCsmIf(Optional.ofNullable(lastMeasureResultBbaCore.getCsmIfEnd()).orElse(BigDecimal.ZERO));
    }else {
      measureResultBbaCore.setCsmIf(BigDecimal.ZERO);
    }
  }

  private void getInitCsmNb(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //根据合同分组编码,当前评估时点汇总表a(18.init_csm_nb)
    measureResultBbaCore.setInitCsmNb(measureCfBbaExpRst.getInitCsmNb());
  }

  private void getCsmBfInv(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //=4.csm_if + 5.init_csm_nb
    measureResultBbaCore.setCsmBfInv(measureResultBbaCore.getCsmIf().add(measureResultBbaCore.getInitCsmNb()));
  }

  /**
   * 3.csm_if*
   * (取表f对应合同分组编码，预测月度为((year(当期评估时点)-year(上期评估时点))*12+month(当期评估时点)-month(上期评估时点)+1)
   * ^((1.当前评估时点-2.上期评估时点)/365)-1)
   * +根据合同分组编码汇总取表a(31.csm_int_accret)
   * @param measureResultBbaCore
   * @param measureCfBbaExpRst
   */
  private void getCsmIntAccret(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //当期评估时点(YYYYMMDD)
    String valMonthDay = DateUtils.endMonth(measureCfBbaExpRst.getValMonth(), YYYYMMDD);
    //上期评估时点(YYYYMMDD)
    String valMonthDayLast = DateUtils.endMonth(measureCfBbaExpRst.getLastValMonth(), YYYYMMDD);
    //经过月份
    long betweenMonth = DateUtil.betweenMonth(DateUtils.parseDate(valMonthDayLast), DateUtils.parseDate(valMonthDay), false);
    //经过天数
    long betweenDay = DateUtil.betweenDay(DateUtils.parseDate(valMonthDayLast), DateUtils.parseDate(valMonthDay), false);

    //根据合同分组编码，查询csm计息配置表
    List<ConfMeasureCsmInterest> measureCsmInterestList = new LambdaQueryChainWrapper<>(confMeasureCsmInterestMapper)
      .select(ConfMeasureCsmInterest::getDisrateValue)
      .eq(ConfMeasureCsmInterest::getGroupId, measureCfBbaExpRst.getGroupId())
      .eq(ConfMeasureCsmInterest::getTerMonth,betweenMonth+1).list();
    log.info("csm计息配置表:{},{}",measureCsmInterestList,betweenMonth+1);

    //取表f对应合同分组编码，预测月度为((year(当期评估时点)-year(上期评估时点))*12+month(当期评估时点)-month(上期评估时点)+1)* ^((1.当前评估时点-2.上期评估时点)/365)
    BigDecimal disrate =  CollectionUtil.isEmpty(measureCsmInterestList) ?BigDecimal.ZERO:measureCsmInterestList.get(0).getDisrateValue();
    double pow = Math.pow(disrate.doubleValue(), BigDecimal.valueOf(betweenDay).divide(new BigDecimal(365), 10, RoundingMode.HALF_UP).doubleValue());
    //csm_if * (disrate-1) + 根据合同分组编码汇总取表a(31.csm_int_accret)
    measureResultBbaCore.setCsmIntAccret(measureResultBbaCore.getCsmIf()
      .multiply(BigDecimal.valueOf(pow)
        .subtract(BigDecimal.ONE))
      .add(measureCfBbaExpRst.getCsmIntAccret()));
  }

  private void getCsmAfInv(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //'=6.csm_bf_inv + 7.csm_int_accret
    measureResultBbaCore.setCsmAfInv(measureResultBbaCore.getCsmBfInv().add(measureResultBbaCore.getCsmIntAccret()));
  }

  /**
   * '=根据合同分组编码及当期评估时点汇总表a(40.gpv_basis_chg+39.ra_basis_chg+25.expc_clm_out_inv-21.expc_prem_inc+22.expc_iacf_out+42.chg_gpv_nop+43.chg_ra_nop)
   * +根据合同分组编码及当期评估时点汇总表b(-actl_clm_out_inv+actl_prem_inc-actl_iacf_out)
   * +对应合同分组编码及当期评估时点取表c(check_gpv+check_ra)
   * @param measureResultBbaCore
   * @param measureCfBbaExpRst
   */
  private void getCsmAdjTot(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst,Map<String, MeasureCfBbaBasicCalcRst> bbaBasicCalcRstMap, Map<String, ConfMeasureBbaNetting> bbaNettingMap) {
    BigDecimal calcRstSumAmt = BigDecimal.ZERO;
    BigDecimal gachaSumAmt = BigDecimal.ZERO;
    //根据合同分组编码及当期评估时点汇总表b(-actl_clm_out_inv+actl_prem_inc-actl_iacf_out)
    MeasureCfBbaBasicCalcRst measureCfBbaBasicCalcRst = bbaBasicCalcRstMap.get(measureCfBbaExpRst.getGroupId());
    if(null != measureCfBbaBasicCalcRst){
      calcRstSumAmt = Optional.ofNullable(measureCfBbaBasicCalcRst.getActlPremInc()).orElse(BigDecimal.ZERO)
        .subtract(Optional.ofNullable(measureCfBbaBasicCalcRst.getActlClmOutInv()).orElse(BigDecimal.ZERO))
        .subtract(Optional.ofNullable(measureCfBbaBasicCalcRst.getActlIacfOut()).orElse(BigDecimal.ZERO));
    }
    //对应合同分组编码及当期评估时点取表c(check_gpv+check_ra)
    ConfMeasureBbaNetting confMeasureBbaNetting = bbaNettingMap.get(measureCfBbaExpRst.getGroupId());
    if(null != confMeasureBbaNetting){
      gachaSumAmt = Optional.ofNullable(confMeasureBbaNetting.getCheckGpv()).orElse(BigDecimal.ZERO)
        .add(Optional.ofNullable(confMeasureBbaNetting.getCheckRa()).orElse(BigDecimal.ZERO));
    }
    //根据合同分组编码及当期评估时点汇总表a(40.gpv_basis_chg+39.ra_basis_chg+25.expc_clm_out_inv-21.expc_prem_inc+22.expc_iacf_out+42.chg_gpv_nop+43.chg_ra_nop)
    measureResultBbaCore.setCsmAdjTot(measureCfBbaExpRst.getExpcIacfOut()
      .add(measureCfBbaExpRst.getExpcClmOutInv())
      .add(measureCfBbaExpRst.getRaBasisChg())
      .add(measureCfBbaExpRst.getGpvBasisChg())
      .add(measureCfBbaExpRst.getChgGpvNop())
      .add(measureCfBbaExpRst.getChgRaNop())
      .subtract(measureCfBbaExpRst.getExpcPremInc())
      .add(calcRstSumAmt)
      .add(gachaSumAmt));
  }

  /**
   * 损失后续确认和转回RA占比	csm_adj_ra_prop
   * =(根据合同分组编码及当期评估时点汇总表a(39.ra_basis_chg + 43.chg_ra_nop)+对应合同分组编码及当前评估时点取表c(check_ra))/9.csm_adj_tot
   *
   */
  private void getCsmAdjRaProp(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst, Map<String, ConfMeasureBbaNetting> bbaNettingMap) {
    if(measureResultBbaCore.getCsmAdjTot().compareTo(BigDecimal.ZERO)==0){
      measureResultBbaCore.setCsmAdjRaProp(BigDecimal.ZERO);
      return;
    }
    BigDecimal gacaSumamt = BigDecimal.ZERO;
    //对应合同分组编码及当前评估时点取表c(check_ra), 取不到默认为0
    ConfMeasureBbaNetting confMeasureBbaNetting = bbaNettingMap.get(measureCfBbaExpRst.getGroupId());
    if(null != confMeasureBbaNetting){
      gacaSumamt = Optional.ofNullable(confMeasureBbaNetting.getCheckRa()).orElse(BigDecimal.ZERO);
    }
    //'(根据合同分组编码及当期评估时点汇总表a(39.ra_basis_chg + 43.chg_ra_nop)+对应合同分组编码及当前评估时点取表c(check_ra))/9.csm_adj_tot
    measureResultBbaCore.setCsmAdjRaProp(
      (measureCfBbaExpRst.getRaBasisChg().add(measureCfBbaExpRst.getChgRaNop())
        .add(gacaSumamt)
        .divide(measureResultBbaCore.getCsmAdjTot(), 10, RoundingMode.HALF_UP)));
  }

  private void getCsmAdjBelProp(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //'1-10.csm_adj_ra_prop
    measureResultBbaCore.setCsmAdjBelProp(BigDecimal.ONE.subtract(measureResultBbaCore.getCsmAdjRaProp()));
  }

  private void getLcIf(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst,Map<String, MeasureResultBbaCore> lastValMonthCoreMap) {
    //根据合同分组编码取核心计量表上期评估时点的期末lc，如果没有则为0
    MeasureResultBbaCore lastBbaExpRst = lastValMonthCoreMap.get(measureCfBbaExpRst.getGroupId());
    if(null != lastBbaExpRst){
      measureResultBbaCore.setLcIf(Optional.ofNullable(lastBbaExpRst.getLcIfEnd()).orElse(BigDecimal.ZERO));
    }else{
      measureResultBbaCore.setLcIf(BigDecimal.ZERO);
    }
  }

  private void getInitLcNb(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //根据合同分组编码,当前评估时点汇总表a(19.init_lc_nb)
    measureResultBbaCore.setInitLcNb(measureCfBbaExpRst.getInitLcNb());
  }

  private void getLcBfInv(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //12.lc_if+13.init_lc_nb
    measureResultBbaCore.setLcBfInv(measureResultBbaCore.getLcIf()
     .add(measureResultBbaCore.getInitLcNb()));
  }

  /**
   * =根据合同分组编码及当期评估时点汇总表a(36.lc_int_accret_pl)
   * +(12.lc_if/
   * (根据合同分组编码及当期评估时点及表a(6.是否当期新单=0)为条件汇总表a(23.expc_me_out+24.expc_clm_out_ins+25.expc_clm_out_inv+17.init_ra_nb)*26.expc_ifie_gpv_pl)
   *  )
   * @param measureResultBbaCore
   * @param measureCfBbaExpRst
   */
  private void getLcIntAccretPl(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst,Map<String, MeasureCfBbaExpRst> measureCfBbaExpRstByGroupAndPolicy) {
    BigDecimal expRstPolicyAmt = BigDecimal.ZERO;
    MeasureCfBbaExpRst measureCfBbaExpRstPolicy = measureCfBbaExpRstByGroupAndPolicy.get(StringUtils.joinWith("_",measureCfBbaExpRst.getGroupId(),"0"));
    if(null != measureCfBbaExpRstPolicy){
      //(23.expc_me_out+24.expc_clm_out_ins+25.expc_clm_out_inv+17.init_ra_nb) * 26.expc_ifie_gpv_pl)
      expRstPolicyAmt = Optional.ofNullable(measureCfBbaExpRstPolicy.getExpcMeOut()).orElse(BigDecimal.ZERO)
        .add(Optional.ofNullable(measureCfBbaExpRstPolicy.getExpcClmOutIns()).orElse(BigDecimal.ZERO))
        .add(Optional.ofNullable(measureCfBbaExpRstPolicy.getExpcClmOutInv()).orElse(BigDecimal.ZERO))
        .add(Optional.ofNullable(measureCfBbaExpRstPolicy.getInitRaNb()).orElse(BigDecimal.ZERO))
        .multiply(Optional.ofNullable(measureCfBbaExpRstPolicy.getExpcIfieGpvPl()).orElse(BigDecimal.ZERO));
    }
    // 如果分母为0，则只取根据合同分组编码及当期评估时点汇总表a(36.lc_int_accret_pl)
    if(expRstPolicyAmt.compareTo(BigDecimal.ZERO)==0){
      measureResultBbaCore.setLcIntAccretPl(measureCfBbaExpRst.getLcIntAccretPl());
    }
    else {
      //根据合同分组编码及当期评估时点汇总表a(36.lc_int_accret_pl)+(12.lc_if/expRstPolicyAmt)
      measureResultBbaCore.setLcIntAccretPl(measureCfBbaExpRst.getLcIntAccretPl()
        .add(measureResultBbaCore.getLcIf()
          .divide(expRstPolicyAmt,10,RoundingMode.HALF_UP)));
    }

  }

  private void getLcAfInv(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //14.lc_bf_inv+15.lc_int_accret_pl
    measureResultBbaCore.setLcAfInv(measureResultBbaCore.getLcBfInv()
     .add(measureResultBbaCore.getLcIntAccretPl()));
  }

  private void getCsmAdjAmt(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //max(-8.csm_af_inv,9.csm_adj_tot-16.lc_af_inv)
    BigDecimal rightAmt = measureResultBbaCore.getCsmAdjTot().subtract(measureResultBbaCore.getLcAfInv());
    if(measureResultBbaCore.getCsmAfInv().negate().compareTo(rightAmt) < 0){
      measureResultBbaCore.setCsmAdjAmt(rightAmt);
    }else {
      measureResultBbaCore.setCsmAdjAmt(measureResultBbaCore.getCsmAfInv().negate());
    }
  }

  private void getCsmBfAmort(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //8.csm_af_inv+17.csm_adj_amt
    measureResultBbaCore.setCsmBfAmort(measureResultBbaCore.getCsmAfInv().add(measureResultBbaCore.getCsmAdjAmt()));
  }

  private void getCsmReleaseRate(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //根据合同分组编码及当期评估时点汇总表a(13.当期服务量)/根据合同分组编码及当期评估时点汇总表a(14.当期及未来服务量)
    measureResultBbaCore.setCsmReleaseRate(measureCfBbaExpRst.getCurrServAmt()
      .divide(measureCfBbaExpRst.getOtherServAmt(),10,RoundingMode.HALF_UP));
  }

  private void getCsmRelease(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //18.csm_bf_amort*19.csm_release_rate
    measureResultBbaCore.setCsmRelease(measureResultBbaCore.getCsmBfAmort()
     .multiply(measureResultBbaCore.getCsmReleaseRate()));
  }

  private void getCsmAfAmort(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //18.csm_bf_amort-20.csm_release
    measureResultBbaCore.setCsmAfAmort(measureResultBbaCore.getCsmBfAmort()
      .subtract(measureResultBbaCore.getCsmRelease()));
  }

  private void getCsmIfEnd(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //'=21.csm_af_amort
    measureResultBbaCore.setCsmIfEnd(measureResultBbaCore.getCsmAfAmort());
  }

  /**
   * 27 损失后续确认和转回
   * =min(29.lc_af_amort,9.csm_adj_tot+8.csm_af_inv)
   */
  private void getLcAdjAmt(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    measureResultBbaCore.setLcAdjAmt(measureResultBbaCore.getLcAfAmort()
      .compareTo(measureResultBbaCore.getCsmAdjTot().add(measureResultBbaCore.getCsmAfInv())) < 0
      ? measureResultBbaCore.getLcAfAmort() : measureResultBbaCore.getCsmAdjTot().add(measureResultBbaCore.getCsmAfInv()));

  }

  private void getLcAdjAmtBel(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //23.lc_adj_amt*11.csm_adj_bel_prop
    measureResultBbaCore.setLcAdjAmtBel(measureResultBbaCore.getLcAdjAmt()
      .multiply(measureResultBbaCore.getCsmAdjBelProp()));
  }

  private void getLcAdjAmtRa(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //23.lc_adj_amt*10.csm_adj_ra_prop
    measureResultBbaCore.setLcAdjAmtRa(measureResultBbaCore.getLcAdjAmt()
     .multiply(measureResultBbaCore.getCsmAdjRaProp()));
  }

  /**
   * 26	分摊前的LC
   * =16.lc_af_inv
   */
  private void getLcBfAmort(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    measureResultBbaCore.setLcBfAmort(measureResultBbaCore.getLcAfInv());
  }

  /**
   * 27 当期LC分摊比例
   * =根据合同分组编码及当期评估时点汇总表a(13.当期服务量)/根据合同分组编码及当期评估时点汇总表a(14.当期及未来服务量)
   */
  private void getLcAmortRate(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    measureResultBbaCore.setLcAmortRate(measureCfBbaExpRst.getCurrServAmt()
     .divide(measureCfBbaExpRst.getOtherServAmt(),10,RoundingMode.HALF_UP));
  }

  private void getLcAmortAmt(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //26.lc_bf_amort*27.lc_amort_rate
    measureResultBbaCore.setLcAmortAmt(measureResultBbaCore.getLcBfAmort()
      .multiply(measureResultBbaCore.getLcAmortRate()));
  }

  private void getLcAfAmort(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //26.lc_bf_amort-28.lc_amort_amt
    measureResultBbaCore.setLcAfAmort(measureResultBbaCore.getLcBfAmort()
     .subtract(measureResultBbaCore.getLcAmortAmt()));
  }

  private void getExpcIfieGpvOci(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //根据合同分组编码及当期评估时点汇总表a(41.oci_inc_gpv)
    measureResultBbaCore.setExpcIfieGpvOci(measureCfBbaExpRst.getOciIncGpv());
  }

  private void getExpcIfieRaOci(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //根据合同分组编码及当期评估时点汇总表a(38.expc_ifie_ra_oci)
    measureResultBbaCore.setExpcIfieRaOci(measureCfBbaExpRst.getExpcIfieRaOci());
  }

  /**
   * '--如果根据合同分组编码及当期评估时点汇总表a(44.gpv_actl_bs+45.ra_actl_bs)=0,则lc_int_oci_alloc_rate=0
   *
   * --如果根据合同分组编码及当期评估时点汇总表a(44.gpv_actl_bs+45.ra_actl_bs)<>0,则lc_int_oci_alloc_rate=29.lc_af_amort
   * /根据合同分组编码及当期评估时点汇总表a(44.gpv_actl_bs+45.ra_actl_bs)
   * @param measureResultBbaCore
   * @param measureCfBbaExpRst
   */
  private void getLcIntOciAllocRate(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    measureResultBbaCore.setLcIntOciAllocRate(BigDecimal.ZERO);
    if(measureCfBbaExpRst.getGpvActlBs().add(measureCfBbaExpRst.getRaActlBs()).compareTo(BigDecimal.ZERO) != 0){
      measureResultBbaCore.setLcIntOciAllocRate(measureResultBbaCore.getLcAfAmort()
        .divide(measureCfBbaExpRst.getGpvActlBs().add(measureCfBbaExpRst.getRaActlBs()),10,RoundingMode.HALF_UP));
    }
  }

  /**
   * 33 计入其他综合收益的保险财务损益-LC部分
   * =max(-62.lc_amort,(30.expc_ifie_gpv_oci+31.expc_ifie_ra_oci)*32.lc_int_oci_alloc_rate)
   */
  private void getLcIntAccretOci(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    measureResultBbaCore.setLcIntAccretOci(measureResultBbaCore.getLcAmort().negate()
     .compareTo((measureResultBbaCore.getExpcIfieGpvOci().add(measureResultBbaCore.getExpcIfieRaOci())).multiply(measureResultBbaCore.getLcIntOciAllocRate()))
      > 0 ? measureResultBbaCore.getLcAmort().negate() : (measureResultBbaCore.getExpcIfieGpvOci().add(measureResultBbaCore.getExpcIfieRaOci())).multiply(measureResultBbaCore.getLcIntOciAllocRate()));
  }

  /**
   * 34 LC期末分摊调整
   * "--如果27.lc_amort_rate = 1 ,则lc_amort_end = max(0,62.lc_amort+33.lc_int_accret_oci)
   * --如果27.lc_amort_rate<>1,则lc_amort_end =0"
   */
  private void getLcAmortEnd(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    measureResultBbaCore.setLcAmortEnd(BigDecimal.ZERO);
    //如果27.lc_amort_rate = 1 ,则lc_amort_end = max(0,29.lc_af_amort+33.lc_int_accret_oci)
    if(BigDecimal.ONE.compareTo(measureResultBbaCore.getLcAmortRate()) == 0) {
      measureResultBbaCore.setLcAmortEnd(BigDecimal.ZERO.compareTo
        (measureResultBbaCore.getLcAmort().add(measureResultBbaCore.getLcIntAccretOci())) < 0
        ? measureResultBbaCore.getLcAmort().add(measureResultBbaCore.getLcIntAccretOci()) : BigDecimal.ZERO);
    }else {
      measureResultBbaCore.setLcAmortEnd(BigDecimal.ZERO);
    }
  }

  private void getLcAmortTot(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //28.lc_amort_amt+34.lc_amort_end
    measureResultBbaCore.setLcAmortTot(measureResultBbaCore.getLcAmortAmt()
      .add(measureResultBbaCore.getLcAmortEnd()));
  }

  /**
   * 36 LC期末余额
   * =max(0,62.lc_amort+33.lc_int_accret_oci-34.lc_amort_end)
   */
  private void getLcIfEnd(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    measureResultBbaCore.setLcIfEnd(BigDecimal.ZERO.compareTo
      (measureResultBbaCore.getLcAmort().add(measureResultBbaCore.getLcIntAccretOci()).subtract(measureResultBbaCore.getLcAmortEnd()))
      < 0 ? measureResultBbaCore.getLcAmort().add(measureResultBbaCore.getLcIntAccretOci()).subtract(measureResultBbaCore.getLcAmortEnd()) : BigDecimal.ZERO);
  }

  private void getIacfIf(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst,Map<String, MeasureResultBbaCore> lastValMonthCore) {
    //根据合同分组编码取核心计量表上期评估时点的期末48.iacf_if_end，如果没有则为0
    MeasureResultBbaCore lastResultBbaCore = lastValMonthCore.get(measureResultBbaCore.getGroupId());
    if (null == lastResultBbaCore) {
      measureResultBbaCore.setIacfIf(BigDecimal.ZERO);
    } else {
      measureResultBbaCore.setIacfIf(Optional.ofNullable(lastResultBbaCore.getIacfIfEnd()).orElse(BigDecimal.ZERO));
    }
  }

  private void getInitIacfNb(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //根据合同分组编码,当前评估时点汇总表a(20.init_iacf_nb)
    measureResultBbaCore.setInitIacfNb(measureCfBbaExpRst.getInitIacfNb());
  }

  private void getIacfBfInv(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //37.iacf_if + 38.init_iacf_nb
    measureResultBbaCore.setIacfBfInv(measureResultBbaCore.getIacfIf()
      .add(measureResultBbaCore.getInitIacfNb()));
  }

  private void getIacfIntAccret(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //暂定为0
    measureResultBbaCore.setIacfIntAccret(BigDecimal.ZERO);
  }

  private void getIacfAfInv(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //39.iacf_bf_inv+40.iacf_int_accret
    measureResultBbaCore.setIacfAfInv(measureResultBbaCore.getIacfBfInv()
     .add(measureResultBbaCore.getIacfIntAccret()));
  }

  private void getExpcIacfOut(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //根据合同分组编码及当期评估时点汇总表a(22.expc_iacf_out)
    measureResultBbaCore.setExpcIacfOut(measureCfBbaExpRst.getExpcIacfOut());
  }

  private void getActlIacfOut(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst,Map<String, MeasureCfBbaBasicCalcRst> bbaBasicCalcRstMap) {
    //根据合同分组编码及当期评估时点汇总表b(actl_iacf_out)
    MeasureCfBbaBasicCalcRst measureCfBbaBasicCalcRst = bbaBasicCalcRstMap.get(measureResultBbaCore.getGroupId());
    if (null == measureCfBbaBasicCalcRst) {
      measureResultBbaCore.setActlIacfOut(BigDecimal.ZERO);
    } else {
      measureResultBbaCore.setActlIacfOut(Optional.ofNullable(measureCfBbaBasicCalcRst.getActlIacfOut()).orElse(BigDecimal.ZERO));
    }
  }

  private void getIacfBfAmort(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //41.iacf_af_inv-42.expc_iacf_out+43.actl_iacf_out
    measureResultBbaCore.setIacfBfAmort(measureResultBbaCore.getIacfAfInv()
     .subtract(measureResultBbaCore.getExpcIacfOut())
      .add(measureResultBbaCore.getActlIacfOut()));
  }

  private void getIacfReleaseRate(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //根据合同分组编码及当期评估时点汇总表a(13.当期服务量)/根据合同分组编码及当期评估时点汇总表a(14.当期及未来服务量)
    measureResultBbaCore.setIacfReleaseRate(measureCfBbaExpRst.getCurrServAmt()
      .divide(measureCfBbaExpRst.getOtherServAmt(),10,RoundingMode.HALF_UP));
  }

  private void getIacfRelease(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //44.iacf_bf_amort*45.iacf_release_rate
    measureResultBbaCore.setIacfRelease(measureResultBbaCore.getIacfBfAmort()
      .multiply(measureResultBbaCore.getIacfReleaseRate()));
  }

  private void getIacfAfAmort(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //44.iacf_bf_amort-46.iacf_release
    measureResultBbaCore.setIacfAfAmort(measureResultBbaCore.getIacfBfAmort()
     .subtract(measureResultBbaCore.getIacfRelease()));
  }

  private void getIacfIfEnd(MeasureResultBbaCore measureResultBbaCore,MeasureCfBbaExpRst measureCfBbaExpRst) {
    //47.iacf_af_amort
    measureResultBbaCore.setIacfIfEnd(measureResultBbaCore.getIacfAfAmort());
  }

  /**
   * 49	上一期期末ra	ra_if
   * 根据合同分组编码取核心计量表上期评估时点的期末59.ra_if_end，如果没有则为0
   */
  private void getRaIf(MeasureResultBbaCore measureResultBbaCore, MeasureCfBbaExpRst measureCfBbaExpRst, Map<String, MeasureResultBbaCore> lastValMonthCoreMap) {
    MeasureResultBbaCore lastValMontCore = lastValMonthCoreMap.get(measureCfBbaExpRst.getGroupId());
    BigDecimal lastRaIfEnd = BigDecimal.ZERO;
    if (null != lastValMontCore) {
      lastRaIfEnd = Optional.ofNullable(lastValMontCore.getRaIfEnd()).orElse(BigDecimal.ZERO);
    }
    measureResultBbaCore.setRaIf(lastRaIfEnd);
  }

  /**
   * 50 当期新单初始确认的ra
   * 根据合同分组编码,当前评估时点汇总表a(17.init_ra_nb)
   */
  private void getInitRaNb(MeasureResultBbaCore measureResultBbaCore, MeasureCfBbaExpRst measureCfBbaExpRst) {
    measureResultBbaCore.setInitRaNb(measureCfBbaExpRst.getInitRaNb());
  }


  /**
   * 51 计息前的ra
   * =49.ra_if+50.init_ra_nb
   */
  private void getRaBfInv(MeasureResultBbaCore measureResultBbaCore) {
    measureResultBbaCore.setRaBfInv(measureResultBbaCore.getRaIf().add(measureResultBbaCore.getInitRaNb()));
  }


  /**
   * 52 ra的计息
   * =49.ra_if*(取表e.评估月度为当期评估时点，预测月度为((year(当期评估时点)-year(2.上期评估时点))*12+month(当期评估时点)-month(2.上期评估时点)+1)^((1.当前评估时点-2.上期评估时点)/365)  -1)+根据合同分组编码汇总取表a(51.ra_int_accret)
   */
  private void getRaIntAccret(MeasureResultBbaCore measureResultBbaCore, MeasureCfBbaExpRst measureCfBbaExpRst) {

    String lastValDateStr = DateUtils.endMonth(measureResultBbaCore.getLastValMonth(), YYYYMMDD);
    String curValDateStr = DateUtils.endMonth(measureResultBbaCore.getValMonth(), YYYYMMDD);

    int termMonths = DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(lastValDateStr), DateUtils.parseDate(curValDateStr)) + 1;
    int diffDays = DateUtils.differentDaysByMillisecond(DateUtils.parseDate(lastValDateStr), DateUtils.parseDate(curValDateStr)) ;

    //表e.评估月度为当期评估时点，，预测月度为((year(当期评估时点)-year(上期评估时点))*12+month(当期评估时点)-month(上期评估时点)+1)* ^((1.当前评估时点-2.上期评估时点)/365)
    BigDecimal disRate =  confMeasureCommonDisrateCacheService.getConfMeasureCommonDisRate(
      EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_7.getCode(), measureResultBbaCore.getValMonth(),
      StringConstant.STRING_NA, StringConstant.STRING_NA, (long) termMonths
    );

    double disRatePow = Math.pow(disRate.doubleValue(), BigDecimal.valueOf(diffDays).divide(new BigDecimal(365), 10, RoundingMode.HALF_UP).doubleValue());
    measureResultBbaCore.setRaIntAccret(measureResultBbaCore.getRaIf().multiply(BigDecimal.valueOf(disRatePow).subtract(BigDecimal.ONE)).add(measureCfBbaExpRst.getRaIntAccret()));
  }


  /**
   * 54	预期RA 损益表IFIE
   * expc_ifie_ra_pl	=52.ra_int_accret-53.expc_ifie_ra_oci
   *
   */
  private void getExpcIfieRaPl(MeasureResultBbaCore measureResultBbaCore) {
    measureResultBbaCore.setExpcIfieRaPl(measureResultBbaCore.getRaIntAccret().subtract(measureResultBbaCore.getExpcIfieRaOci()));
  }




  /**
   * 55	计息后的ra
   * ra_af_inv	=51.ra_bf_inv+52.ra_int_accret
   */
  private void getRaAfInv(MeasureResultBbaCore measureResultBbaCore) {
    measureResultBbaCore.setRaAfInv(measureResultBbaCore.getRaBfInv().add(measureResultBbaCore.getRaIntAccret()));
  }


  /**
   * 56	计算	ra当期摊销比例
   * 	=根据合同分组编码及当期评估时点汇总表a(13.当期服务量)/根据合同分组编码及当期评估时点汇总表a(14.当期及未来服务量)
   *
   */
  private void getRaReleaseRate(MeasureResultBbaCore measureResultBbaCore, MeasureCfBbaExpRst measureCfBbaExpRst) {
    measureResultBbaCore.setRaReleaseRate(
      measureCfBbaExpRst.getCurrServAmt().divide(measureCfBbaExpRst.getOtherServAmt(),10,RoundingMode.HALF_UP));

  }


  /**
   * 57	ra当期摊销
   * =55.ra_af_inv*56.ra_release_rate
   */
  private void getRaRelease(MeasureResultBbaCore measureResultBbaCore) {
    measureResultBbaCore.setRaRelease(measureResultBbaCore.getRaAfInv().multiply(measureResultBbaCore.getRaReleaseRate()));

  }


  /**
   * 58	ra摊后余额
   * =55.ra_af_inv-57.ra_release
   */
  private void getRaAfAmort(MeasureResultBbaCore measureResultBbaCore) {
    measureResultBbaCore.setRaAfAmort(measureResultBbaCore.getRaAfInv().subtract(measureResultBbaCore.getRaRelease()));
  }

  /**
   * 59	ra的吸收项
   * =根据合同分组编码及当期评估时点汇总表a -(39.ra_basis_chg+43.chg_ra_nop)
   */
  private void getraAdjTot(MeasureResultBbaCore measureResultBbaCore, MeasureCfBbaExpRst measureCfBbaExpRst, Map<String, ConfMeasureBbaNetting> bbaNettingMap) {
    measureResultBbaCore.setRaAdjTot((measureCfBbaExpRst.getRaBasisChg().add(measureCfBbaExpRst.getChgRaNop())).negate());
  }

  /**
   * 60	调整后的ra
   * ra_bf_amort	=58.ra_af_amort+59.ra_adj_tot
   */
  private void getRaBfAmort(MeasureResultBbaCore measureResultBbaCore) {
    measureResultBbaCore.setRaBfAmort(measureResultBbaCore.getRaAfAmort().add(measureResultBbaCore.getRaAdjTot()));
  }

  /**
   * 61	ra期末值
   * =60.ra_bf_amort
   */
  private void getRaIfEnd(MeasureResultBbaCore measureResultBbaCore) {
    measureResultBbaCore.setRaIfEnd(measureResultBbaCore.getRaBfAmort());
  }

}
