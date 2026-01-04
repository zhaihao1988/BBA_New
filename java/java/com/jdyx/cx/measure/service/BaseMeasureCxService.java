package com.jdyx.cx.measure.service;

import cn.hutool.core.bean.BeanUtil;
import cn.hutool.core.date.DateUtil;
import cn.hutool.core.lang.Opt;
import cn.hutool.core.util.StrUtil;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.support.SFunction;
import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import com.jdyx.common.cache.measure.ConfMeasureActuarialAssumptionCacheService;
import com.jdyx.common.cache.measure.ConfMeasureClaimModelCacheService;
import com.jdyx.common.cache.measure.ConfMeasureCommonDisrateCacheService;
import com.jdyx.common.cache.measure.ConfMeasureDiscountRateCacheService;
import com.jdyx.common.enums.CurrencyTypeEnum;
import com.jdyx.common.enums.DataStateTypeEnum;
import com.jdyx.common.enums.EvaluateMethodTypeEnum;
import com.jdyx.common.measure.constant.NumberConstant;
import com.jdyx.common.measure.constant.StringConstant;
import com.jdyx.common.measure.service.Measure1CfInfoService;
import com.jdyx.common.measure.tools.UtilsCommon;
import com.jdyx.measure.api.measure.domain.*;
import com.jdyx.measureprepare.api.domain.TPpJlCase;
import com.jdyx.measureprepare.api.domain.TPpJlUlaeSettled;
import com.kevin.common.utils.DateUtils;
import com.kevin.common.utils.StringUtils;
import com.kevin.common.utils.reflect.ReflectUtils;
import com.kevin.common.utils.sql.SqlFunctionUtil;
import lombok.extern.slf4j.Slf4j;

import javax.annotation.Resource;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.*;
import java.util.stream.Collectors;

/**
 * 产险基类
 *
 * @author kevin.
 * @date 2024/4/2.
 */
@SuppressWarnings("Duplicated")
@Slf4j
public abstract class BaseMeasureCxService extends BaseMeasureInfoService {

  /** 11.计量明细统一接口 */
  @Resource
  private Measure1CfInfoService measure1CfInfoService;

  /** 精算假设配置缓存数据服务 */
  @Resource
  private ConfMeasureActuarialAssumptionCacheService confMeasureActuarialAssumptionCacheService;

  @Resource
  private ConfMeasureCommonDisrateCacheService confMeasureCommonDisrateCacheService;

  @Resource
  private ConfMeasureDiscountRateCacheService confMeasureDiscountRateCacheService;

  @Resource
  private ConfMeasureClaimModelCacheService confMeasureClaimModelCacheService;

  /**
   * 转换 到预期现金流
   *
   * @param valMonth 评估月
   * @param beamMap 待转换数据
   * @return list
   */
  protected static List<MeasureCfBasicExpRst> getMeasureCfBasicExpRsts(String evaluateMethod, String valMonth, String csmGroupNo, String portfolioNo, Map<String, Object> beamMap,
    MeasureCfBasicExpRst measureCfBasicExpRst) {
    //2. 转换到预期现金流
    List<MeasureCfBasicExpRst> measureCfBasicExpRsts = Lists.newArrayList();
    Optional.ofNullable(beamMap).orElse(Maps.newHashMap()).forEach((k, v) -> {
      if (v instanceof BigDecimal) {
        MeasureCfBasicExpRst mcRst = new MeasureCfBasicExpRst();
        mcRst.setValMonth(valMonth);
        mcRst.setGroupId(csmGroupNo);
        mcRst.setPortfolioId(portfolioNo);
        mcRst.setValMethod(evaluateMethod);
        mcRst.setVar(StrUtil.toUnderlineCase(k).toUpperCase());
        mcRst.setVarAmt(Optional.of((BigDecimal) v).orElse(BigDecimal.ZERO));
        mcRst.setProfitLevel(subProfitLevel(csmGroupNo));
        mcRst.setCurrency(CurrencyTypeEnum.CURRENCY_TYPE_CNY.getCode());
        mcRst.setIsStatus(DataStateTypeEnum.DATA_STATE_TYPE_2.getCode());
        mcRst.setComCode(measureCfBasicExpRst.getComCode());
        mcRst.setBusinessNature(measureCfBasicExpRst.getBusinessNature());
        mcRst.setCoverageSegment(measureCfBasicExpRst.getCoverageSegment());
        mcRst.setCarKindCode(measureCfBasicExpRst.getCarKindCode());
        mcRst.setUseNatureCode(measureCfBasicExpRst.getUseNatureCode());
        measureCfBasicExpRsts.add(mcRst);
      }
    });
    return measureCfBasicExpRsts;
  }

  /**
   * 转换 到预期现金流
   *
   * @param valMonth 评估月
   * @param beamMap 待转换数据
   * @return list
   */
  protected static List<MeasureCfBasicExpRst> getMeasureCfBasicExpRsts(String evaluateMethod, String valMonth, String csmGroupNo, String portfolioNo, Map<String, Object> beamMap) {
    //2. 转换 到实际现金流
    List<MeasureCfBasicExpRst> measureCfBasicExpRsts = Lists.newArrayList();
    Optional.ofNullable(beamMap).orElse(Maps.newHashMap()).forEach((k, v) -> {
      if (v instanceof BigDecimal) {
        MeasureCfBasicExpRst mcRst = new MeasureCfBasicExpRst();
        mcRst.setValMonth(valMonth);
        mcRst.setGroupId(csmGroupNo);
        mcRst.setPortfolioId(portfolioNo);
        mcRst.setValMethod(evaluateMethod);
        mcRst.setVar(StrUtil.toUnderlineCase(k).toUpperCase());
        mcRst.setVarAmt(Optional.of((BigDecimal) v).orElse(BigDecimal.ZERO));
        //盈亏水平
        mcRst.setProfitLevel(subProfitLevel(csmGroupNo));
        mcRst.setCurrency(CurrencyTypeEnum.CURRENCY_TYPE_CNY.getCode());
        mcRst.setIsStatus(DataStateTypeEnum.DATA_STATE_TYPE_2.getCode());
        measureCfBasicExpRsts.add(mcRst);
      }
    });
    return measureCfBasicExpRsts;
  }

  /**
   * 转换 到实际现金流
   *
   * @param valMonth 评估月
   * @param beamMap 待转换数据
   * @return list
   */
  protected static List<MeasureCfBasicCalcRst> getMeasureCfBasicCalcRsts(String evaluateMethod, String valMonth, String csmGroupNo, String portfolioNo, Map<String, Object> beamMap) {
    //2. 转换 到实际现金流
    List<MeasureCfBasicCalcRst> measureCfBasicCalcRst = Lists.newArrayList();
    Optional.ofNullable(beamMap).orElse(Maps.newHashMap()).forEach((k, v) -> {
      if (v instanceof BigDecimal) {
        MeasureCfBasicCalcRst mcRst = new MeasureCfBasicCalcRst();
        mcRst.setValMonth(valMonth);
        mcRst.setGroupId(csmGroupNo);
        mcRst.setPortfolioId(portfolioNo);
        mcRst.setValMethod(evaluateMethod);
        mcRst.setVar(StrUtil.toUnderlineCase(k).toUpperCase());
        mcRst.setVarAmt(Optional.of((BigDecimal) v).orElse(BigDecimal.ZERO));
        mcRst.setProfitLevel(subProfitLevel(csmGroupNo));
        mcRst.setCurrency(CurrencyTypeEnum.CURRENCY_TYPE_CNY.getCode());
        mcRst.setIsStatus(DataStateTypeEnum.DATA_STATE_TYPE_2.getCode());
        measureCfBasicCalcRst.add(mcRst);
      }
    });
    return measureCfBasicCalcRst;
  }

  /**
   * 转换 到实际现金流
   *
   * @param valMonth 评估月
   * @param beamMap 待转换数据
   * @return list
   */
  protected static List<MeasureCfBasicCalcRst> getMeasureCfBasicCalcRsts(String evaluateMethod, String valMonth, String csmGroupNo, String portfolioNo, Map<String, Object> beamMap,
    MeasureCfBasicCalcRst measureCfBasicCalcRstBean) {
    //2. 转换 到实际现金流
    List<MeasureCfBasicCalcRst> measureCfBasicCalcRst = Lists.newArrayList();
    Optional.ofNullable(beamMap).orElse(Maps.newHashMap()).forEach((k, v) -> {
      if (v instanceof BigDecimal) {
        MeasureCfBasicCalcRst mcRst = new MeasureCfBasicCalcRst();
        mcRst.setValMonth(valMonth);
        mcRst.setGroupId(csmGroupNo);
        mcRst.setPortfolioId(portfolioNo);
        mcRst.setValMethod(evaluateMethod);
        mcRst.setVar(StrUtil.toUnderlineCase(k).toUpperCase());
        mcRst.setVarAmt(Optional.of((BigDecimal) v).orElse(BigDecimal.ZERO));
        //盈亏水平
        mcRst.setProfitLevel(subProfitLevel(csmGroupNo));
        mcRst.setCurrency(CurrencyTypeEnum.CURRENCY_TYPE_CNY.getCode());
        mcRst.setIsStatus(DataStateTypeEnum.DATA_STATE_TYPE_2.getCode());
        mcRst.setComCode(measureCfBasicCalcRstBean.getComCode());
        mcRst.setBusinessNature(measureCfBasicCalcRstBean.getBusinessNature());
        mcRst.setCoverageSegment(measureCfBasicCalcRstBean.getCoverageSegment());
        mcRst.setCarKindCode(measureCfBasicCalcRstBean.getCarKindCode());
        mcRst.setUseNatureCode(measureCfBasicCalcRstBean.getUseNatureCode());
        measureCfBasicCalcRst.add(mcRst);
      }
    });
    return measureCfBasicCalcRst;
  }

  /**
   * 获取 产险直保计量_未决CASE部分
   *
   * @param evaluateMethod 评估方法
   * @param valMonth 评估月
   * @return List<MeasureCfBasicCalcRst>
   */
  protected List<MeasureCfBasicCalcRst> getPpJlCaseSum(String evaluateMethod, String valMonth) {
    List<TPpJlCase> tPpJlCaseList = publicDbService.getPpJlCaseSum(evaluateMethod, valMonth);
    //2. 转换 到实际现金流
    List<MeasureCfBasicCalcRst> measureCfBasicCalcRst = Lists.newArrayList();
    Optional.ofNullable(tPpJlCaseList).orElse(Lists.newArrayList()).forEach(e -> {
      Map<String, Object> beamMap = BeanUtil.beanToMap(e);
      MeasureCfBasicCalcRst measureCfBasicCalcRstBean = BeanUtil.copyProperties(e, MeasureCfBasicCalcRst.class);
      List<MeasureCfBasicCalcRst> measureCfBasicCalcRsts = getMeasureCfBasicCalcRsts(evaluateMethod, valMonth, e.getGroupId(), e.getPortfolioId(), beamMap, measureCfBasicCalcRstBean);
      measureCfBasicCalcRst.addAll(measureCfBasicCalcRsts);
    });

    return measureCfBasicCalcRst;
  }

  /**
   * 获取 产险直保计量_未决CASE_不需分摊部分
   *
   * @param evaluateMethod 评估方法
   * @param valMonth 评估月
   * @return List<MeasureCfBasicCalcRst>
   */
//  protected List<MeasureCfBasicCalcRst> getPpJlCaseNaSum(String evaluateMethod, String valMonth) {
//    List<TPpJlCaseNa> tPpJlCaseNaList = publicDbService.getPpJlCaseNaSum(evaluateMethod, valMonth);
//    //2. 转换 到实际现金流
//    List<MeasureCfBasicCalcRst> measureCfBasicCalcRst = Lists.newArrayList();
//    Optional.ofNullable(tPpJlCaseNaList).orElse(Lists.newArrayList()).forEach(e -> {
//      Map<String, Object> beamMap = BeanUtil.beanToMap(e);
//      MeasureCfBasicCalcRst measureCfBasicCalcRstBean = BeanUtil.copyProperties(e, MeasureCfBasicCalcRst.class);
//      List<MeasureCfBasicCalcRst> measureCfBasicCalcRsts = getMeasureCfBasicCalcRsts(evaluateMethod, valMonth, e.getGroupId(), e.getPortfolioId(), beamMap, measureCfBasicCalcRstBean);
//      measureCfBasicCalcRst.addAll(measureCfBasicCalcRsts);
//    });
//
//    return measureCfBasicCalcRst;
//  }

  /**
   * 获取 产险直保计量_未决IBNR_不需分摊
   *
   * @param evaluateMethod 评估方法
   * @param valMonth 评估月
   * @return List<MeasureCfBasicCalcRst>
   */
//  protected List<MeasureCfBasicCalcRst> getPpJlIbnrNaSum(String evaluateMethod, String valMonth) {
//    List<TPpJlIbnrNa> tPpJlIbnrNaList = publicDbService.getPpJlIbnrNaSum(evaluateMethod, valMonth);
//    //2. 转换 到实际现金流
//    List<MeasureCfBasicCalcRst> measureCfBasicCalcRst = Lists.newArrayList();
//    Optional.ofNullable(tPpJlIbnrNaList).orElse(Lists.newArrayList()).forEach(e -> {
//      Map<String, Object> beamMap = BeanUtil.beanToMap(e);
//      MeasureCfBasicCalcRst measureCfBasicCalcRstBean = BeanUtil.copyProperties(e, MeasureCfBasicCalcRst.class);
//      List<MeasureCfBasicCalcRst> measureCfBasicCalcRsts = getMeasureCfBasicCalcRsts(evaluateMethod, valMonth, e.getGroupId(), e.getPortfolioId(), beamMap, measureCfBasicCalcRstBean);
//      measureCfBasicCalcRst.addAll(measureCfBasicCalcRsts);
//    });
//
//    return measureCfBasicCalcRst;
//  }

  /**
   * 获取 产险直保计量_已决间接理赔费用  ulae_settled_past_cny + ulae_settled_curr_cny
   *
   * @param evaluateMethod 评估方法
   * @param valMonth 评估月
   * @return Map<String, BigDecimal>
   */
  protected Map<String, BigDecimal> getPpJlUlaeSettledSum(String evaluateMethod, String valMonth, SFunction<TPpJlUlaeSettled, BigDecimal> ... selectVar) {
    List<TPpJlUlaeSettled> tPpJlIbnrNaList = publicDbService.getPpJlUlaeSettledSum(evaluateMethod, valMonth, selectVar);
    Map<String, BigDecimal> collect = tPpJlIbnrNaList.stream().collect(Collectors.toMap(TPpJlUlaeSettled::getUnitId, item -> {
      BigDecimal total = BigDecimal.ZERO;
      for (SFunction<TPpJlUlaeSettled, BigDecimal> func : selectVar) {
        total = total.add(Optional.ofNullable(func.apply(item)).orElse(BigDecimal.ZERO));
      }
      return total;
    }));
    return collect;
  }

  /**
   * 获取 比例分出未决CASE表
   *
   * @param evaluateMethod 评估方法
   * @param valMonth 评估月
   * @return List<MeasureCfBasicCalcRst>
   */
//  protected List<MeasureCfBasicCalcRst> getTPpReinPrCaseSum(String evaluateMethod, String valMonth) {
//    List<TPpReinPrCase> tPpReinPrCaseList = publicDbService.getTPpReinPrCaseSum(evaluateMethod, valMonth);
//    //2. 转换 到实际现金流
//    List<MeasureCfBasicCalcRst> measureCfBasicCalcRst = Lists.newArrayList();
//    Optional.ofNullable(tPpReinPrCaseList).orElse(Lists.newArrayList()).forEach(e -> {
//      Map<String, Object> beamMap = BeanUtil.beanToMap(e);
//      List<MeasureCfBasicCalcRst> measureCfBasicCalcRsts = getMeasureCfBasicCalcRsts(evaluateMethod, valMonth, e.getGroupId(), e.getPortfolioId(), beamMap);
//      measureCfBasicCalcRst.addAll(measureCfBasicCalcRsts);
//    });
//    return measureCfBasicCalcRst;
//  }

  /**
   * 获取 超赔摊回IBNR_不需分摊表
   *
   * @param evaluateMethod 评估方法
   * @param valMonth 评估月
   * @return List<MeasureCfBasicCalcRst>
   */
//  protected List<MeasureCfBasicCalcRst> getTPpReinNrIbnrNaSum(String evaluateMethod, String valMonth) {
//    List<TPpReinNrIbnrNa> tPpReinPrCaseList = publicDbService.getTPpReinNrIbnrNaSum(evaluateMethod, valMonth);
//    //2. 转换 到实际现金流
//    List<MeasureCfBasicCalcRst> measureCfBasicCalcRst = Lists.newArrayList();
//    Optional.ofNullable(tPpReinPrCaseList).orElse(Lists.newArrayList()).forEach(e -> {
//      Map<String, Object> beamMap = BeanUtil.beanToMap(e);
//      List<MeasureCfBasicCalcRst> measureCfBasicCalcRsts = getMeasureCfBasicCalcRsts(evaluateMethod, valMonth, e.getGroupId(), e.getPortfolioId(), beamMap);
//      measureCfBasicCalcRst.addAll(measureCfBasicCalcRsts);
//    });
//    return measureCfBasicCalcRst;
//  }

  /**
   * 获取 产险直保计量_明细数据
   *
   * @param evaluateMethod 评估方法
   * @param valMonth 评估月
   * @return List<MeasureCfBasicCalcRst>
   */
  protected List<MeasureCfBasicCalcRst> getMeasureCfResultInfoSum(String evaluateMethod, String valMonth) {
    //1.获取 分组汇总
    SqlFunctionUtil<MeasureCfResultInfo> tPpJlCaseSqlFunctionUtil = new SqlFunctionUtil<>();
    QueryWrapper<MeasureCfResultInfo> lqw = new QueryWrapper<>();
    lqw.select(Lists.newArrayList(
      tPpJlCaseSqlFunctionUtil.getSumParamSql(MeasureCfResultInfo::getPvRepAmt, MeasureCfResultInfo::getCurrServAmt,
        MeasureCfResultInfo::getLrcRaAmt, MeasureCfResultInfo::getIsrAmt, MeasureCfResultInfo::getIacfAmortAmt,
        MeasureCfResultInfo::getPvRepAmt, MeasureCfResultInfo::getLrcNoLcAmt, MeasureCfResultInfo::getLrcIfieAmt,
        MeasureCfResultInfo::getIcPaidAmt),
      tPpJlCaseSqlFunctionUtil.getParamSql(MeasureCfResultInfo::getGroupId, MeasureCfResultInfo::getPortfolioId, MeasureCfResultInfo::getValMonth, MeasureCfResultInfo::getValMethod,
        MeasureCfResultInfo::getComCode, MeasureCfResultInfo::getBusinessNature, MeasureCfResultInfo::getCarKindCode, MeasureCfResultInfo::getUseNatureCode, MeasureCfResultInfo::getCoverageSegment)));
    lqw.eq(tPpJlCaseSqlFunctionUtil.getParamSql(MeasureCfResultInfo::getValMonth), valMonth);
    lqw.eq(tPpJlCaseSqlFunctionUtil.getParamSql(MeasureCfResultInfo::getValMethod), evaluateMethod);
    lqw.groupBy(
      tPpJlCaseSqlFunctionUtil.getParamSql(MeasureCfResultInfo::getGroupId, MeasureCfResultInfo::getPortfolioId, MeasureCfResultInfo::getValMonth, MeasureCfResultInfo::getValMethod,
        MeasureCfResultInfo::getComCode, MeasureCfResultInfo::getBusinessNature, MeasureCfResultInfo::getCarKindCode, MeasureCfResultInfo::getUseNatureCode, MeasureCfResultInfo::getCoverageSegment));
    List<MeasureCfResultInfo> measureCfResultInfoList = measureCfResultInfoMapper.selectList(lqw);

    //2. 转换 到实际现金流
    List<MeasureCfBasicCalcRst> measureCfBasicCalcRst = Lists.newArrayList();
    Optional.ofNullable(measureCfResultInfoList).orElse(Lists.newArrayList()).forEach(e -> {
      Map<String, Object> beamMap = BeanUtil.beanToMap(e);
      MeasureCfBasicCalcRst measureCfBasicCalcRstBean = BeanUtil.copyProperties(e, MeasureCfBasicCalcRst.class);
      List<MeasureCfBasicCalcRst> measureCfBasicCalcRsts = getMeasureCfBasicCalcRsts(evaluateMethod, valMonth, e.getGroupId(), e.getPortfolioId(), beamMap, measureCfBasicCalcRstBean);
      measureCfBasicCalcRst.addAll(measureCfBasicCalcRsts);
    });

    return measureCfBasicCalcRst;
  }

  /**
   * 产险直保BBA计量明细
   *
   * @param evaluateMethod 评估方法 {@link EvaluateMethodTypeEnum}
   * @param measureCfResultInfoLast 上期评估时点 计量明细数据
   * @param paaDisrateMap 折现利率
   * @param lossRatioMap 赔付率假设
   * @param expenseMap 维持费用假设
   * @param padMap 非金融风险调整
   * @param entity 计量源数据
   * @return measureCfResultInfo
   */
  protected MeasureCfResultInfo getCxPiBbaMeasureCfResultInfoRst(String evaluateMethod, MeasureCfResultInfo measureCfResultInfoLast,
    MeasureCfResultInfo measureCfResultInfoInit, Map<String, BigDecimal> paaDisrateMap,
    Map<String, BigDecimal> lossRatioMap, Map<String, MeasureCfResultInfo> lastMeasureCfResultInfoMap,
    Map<String, BigDecimal> expenseMap, Map<String, BigDecimal> padMap, MeasureCfBasicData entity) {
    //数据初始化
    MeasureCfResultInfo measureCfResultInfo = measure1CfInfoService.iniMeasureCfResultInfo();
//    //1.上期评估时点 = 上期评估时点
//    measure1CfInfoService.getLastValMonth(entity, measureCfResultInfo, evaluateMethod);
//    //2.当前评估时点 = 当前评估时点
//    measure1CfInfoService.getValMonth(entity, measureCfResultInfo, evaluateMethod);
//    //3.计量单元标号 = 计量单元标号
//    measure1CfInfoService.getUnitId(entity, measureCfResultInfo, evaluateMethod);
//    //4.赠险标签 = 赠险标签
//    measure1CfInfoService.getPresentFlag(entity, measureCfResultInfo, evaluateMethod);
//    //5.I17险种代码 =  I17险种代码
//    measure1CfInfoService.getRiskCode(entity, measureCfResultInfo, evaluateMethod);
//    //6.缴费频率 = 缴费频率
//    measure1CfInfoService.getPayFreq(entity, measureCfResultInfo, evaluateMethod);
//    //7.初始确认年月 = 初始确认年月
//    measure1CfInfoService.getInitCfmYm(entity, measureCfResultInfo, evaluateMethod);
//    //11.合同组合编号 = 合同组合编号
//    measure1CfInfoService.getPortfolioId(entity, measureCfResultInfo, evaluateMethod);
//    //14.币种 = 币种
//    measure1CfInfoService.getCurrency(entity, measureCfResultInfo, evaluateMethod);
//    //15.评估方法
//    measure1CfInfoService.getValMethod(entity, measureCfResultInfo, evaluateMethod);
//    //16.合同分组编号 = 合同组合编号
//    measure1CfInfoService.getGroupId(entity, measureCfResultInfo, evaluateMethod);
//    //17.保费总额 = 保费本币
//    measure1CfInfoService.getPremiumCny(entity, measureCfResultInfo, evaluateMethod);
//    //18.投资成分占比 = 投资成分占比
//    measure1CfInfoService.getInvestProp(entity, measureCfResultInfo, evaluateMethod);
//    //20.当期预期获取费用 = 当期预期获取费用_本币
//    measure1CfInfoService.getCurrIacf(entity, measureCfResultInfo, evaluateMethod);
//    //21.是否当期新单
//    measure1CfInfoService.getWhetherCurPolicy(entity,measureCfResultInfo, evaluateMethod);
//    //22.满期日期
//    measure1CfInfoService.getEndDate(entity, measureCfResultInfo, evaluateMethod);
//    //23.保障期限
//    measure1CfInfoService.getTerm(entity, measureCfResultInfo, evaluateMethod);
//    //24.当期服务量
//    measure1CfInfoService.getCurrServAmt(measureCfResultInfo, evaluateMethod);
//    //25.当期及未来服务量
//    measure1CfInfoService.getOtherServAmt(measureCfResultInfo, evaluateMethod);
//    //26.当期确认比例
//    measure1CfInfoService.getCurRecPct(measureCfResultInfo, evaluateMethod);
//    //27.期初未确认保费
//    measure1CfInfoService.getPremBopUnRecAmt(entity, measureCfResultInfoLast, measureCfResultInfo);
//    //28.期初保费计息
//    measure1CfInfoService.getPremInterestAmt(measureCfResultInfo);
//    //29.当期确认的保费
//    measure1CfInfoService.getPremCurRecAmt(measureCfResultInfo, evaluateMethod);
//    //30.期末未确认保费
//    measure1CfInfoService.getPremEopUnRecAmt(measureCfResultInfo, evaluateMethod);
//    //31.期初未确认的IACF
//    measure1CfInfoService.getIacfBopUnRecAmt(lastMeasureCfResultInfoMap, measureCfResultInfo, evaluateMethod);
//    //32.IACF计息
//    measure1CfInfoService.getIacfInterestAmt(measureCfResultInfo, evaluateMethod);
//    //33.当期确认的IACF
//    measure1CfInfoService.getIacfAmortAmt(measureCfResultInfo, evaluateMethod);
//    //34.期末未确认IACF
//    measure1CfInfoService.getIacfEopUnRec(measureCfResultInfo, evaluateMethod);
//    //35.期初未确认的投资成分 新增
//    measure1CfInfoService.getIcBopUnRecAmt(lastMeasureCfResultInfoMap, measureCfResultInfo, evaluateMethod);
//    //36.期初投资成分计息 新增
//    measure1CfInfoService.getIcInterestAmt(measureCfResultInfo, evaluateMethod);
//    //37.当期确认的投资成分 新增
//    measure1CfInfoService.getIcPaidAmt(measureCfResultInfo, evaluateMethod);
//    //38.期末未确认的投资成分 新增
//    measure1CfInfoService.getIcEopUnRecAmt(measureCfResultInfo, evaluateMethod);
//    //39.保险合同收入
//    measure1CfInfoService.getIsrAmt(measureCfResultInfo, evaluateMethod);
//    //42.未经保费
//    measure1CfInfoService.getUnRecPremAmt(measureCfResultInfo, evaluateMethod);
//    //48.经过保费
//    measure1CfInfoService.getRecPremAmt(paaDisrateMap, measureCfResultInfo, evaluateMethod);
//    //49.未来现金流量现值_期末
//    measure1CfInfoService.getPvEopRepAmt(expenseMap, lossRatioMap, measureCfResultInfo, evaluateMethod);
//    //50.预期赔付的现值
//    measure1CfInfoService.getPvLossAmt(lossRatioMap, measureCfResultInfo, evaluateMethod);
//    //51.预期维持费用
//    measure1CfInfoService.getPvMaintainAmt(expenseMap, measureCfResultInfo, evaluateMethod);
//    //52.预期总赔付的现值(再保-预期现金流量现值)
//    measure1CfInfoService.getPvLossTotAmt(expenseMap, lossRatioMap, measureCfResultInfo, evaluateMethod);
//    //55.预期未来现金流出现值_上期(若在 初始评估时点,则为初始)
//    measure1CfInfoService.getPvBelLast(expenseMap, lossRatioMap, measureCfResultInfo, evaluateMethod, measureCfResultInfoInit);
//    //56.预期未来现金流出_初始
//    measure1CfInfoService.getInitPvBel(expenseMap, lossRatioMap, measureCfResultInfo, evaluateMethod);
//    //58.预期未来非风险金融调整_初始
//    measure1CfInfoService.getInitPvRa(padMap, measureCfResultInfo, evaluateMethod);
//    //60.预期未来现金流入现值_初始
//    measure1CfInfoService.getInitPvBelIn(measureCfResultInfo, evaluateMethod);
//    //61.未到期责任负债_亏损部分_初始
//    measure1CfInfoService.getInitLrcLc(measureCfResultInfo, evaluateMethod);
//    //63.未来现金流(BEL)_初始
//    measure1CfInfoService.getInitBel(measureCfResultInfo, evaluateMethod);
//    //64.实际总赔付的现值(实际赔款)
//    measure1CfInfoService.getPvLossTotAmtAdj(expenseMap, lossRatioMap, measureCfResultInfo, evaluateMethod);
//    //65.预期赔付现值_期末(参数调整)
//    measure1CfInfoService.getPvEopRepAmtAdj(expenseMap, lossRatioMap, measureCfResultInfo, evaluateMethod);
//    //66.非金融风险调整_期末(参数调整)
//    measure1CfInfoService.getLrcEopRaAmtAdj(padMap, measureCfResultInfo, evaluateMethod);
//    //67.合同服务边际(参数调整)
//    measure1CfInfoService.getCsmAmtAdj(measureCfResultInfo, evaluateMethod);
//    //69.未到期_金融风险调整_上期(若在 初始评估时点,则为初始)
//    measure1CfInfoService.getLrcRaLast(measureCfResultInfo, evaluateMethod, measureCfResultInfoInit);
//    //71.合同服务边际_初始
//    measure1CfInfoService.getInitCsm(measureCfResultInfo, evaluateMethod);
//    //74.预期非金融风险调整的释放
//    measure1CfInfoService.getPvLrcRaReleaseAmt(paaDisrateMap, measureCfResultInfo, evaluateMethod);
//    //75.合同亏损情况
//    measure1CfInfoService.getIsrAttr(measureCfResultInfo, evaluateMethod);
//    //76.合同服务边际_上期
//    measure1CfInfoService.getCsmLast(measureCfResultInfoLast, measureCfResultInfo, evaluateMethod, measureCfResultInfoInit);
//    //77.合同服务边际的释放
//    measure1CfInfoService.getCsmRelease(paaDisrateMap, measureCfResultInfo, evaluateMethod);
//    //78.非金融风险调整_期末
//    measure1CfInfoService.getLrcEopRaAmt(measureCfResultInfo, evaluateMethod);
//    //79.合同服务边际_期末
//    measure1CfInfoService.getCsmEop(measureCfResultInfo, evaluateMethod);
//    //80.未来现金流量(BEL)_计息
//    measure1CfInfoService.getBelIfie(paaDisrateMap, measureCfResultInfo, evaluateMethod);
//    //81.非金融风险调整计息
//    measure1CfInfoService.getRaIfie(measureCfResultInfo, evaluateMethod);
//    //82.合同服务边际计息
//    measure1CfInfoService.getCsmIfie(measureCfResultInfo, evaluateMethod);
//    //84.未到期责任负债_亏损部分_上期
//    measure1CfInfoService.getLrcLcLast(measureCfResultInfo, evaluateMethod, measureCfResultInfoInit);
//    //85.亏损部分的释放
//    measure1CfInfoService.getLcRelease(measureCfResultInfo, evaluateMethod);
//    //88.未到期责任负债_亏损
//    measure1CfInfoService.getLrcLcAmt(measureCfResultInfo, evaluateMethod);
//    //89.未到期责任负债_其他部分_期末
//    measure1CfInfoService.getLrcEopOpex(measureCfResultInfo, evaluateMethod);
//    //90.未到期责任-其他部分(参数调整)
//    measure1CfInfoService.getLrcOpexAdj(measureCfResultInfo, evaluateMethod);
//    //91.未到期责任负债-亏损(参数调整)
//    measure1CfInfoService.getLrcLc(measureCfResultInfo, evaluateMethod);
//    //93.未到期_亏损部分计息
//    measure1CfInfoService.getLrcLcIfie(measureCfResultInfo, evaluateMethod);

    return new MeasureCfResultInfo();

  }

  /**
   * 产险再保BBA计量明细
   *
   * @param evaluateMethod 评估方法 {@link EvaluateMethodTypeEnum}
   * @param measureCfResultInfoLast 上期评估时点 计量明细数据
   * @param paaDisrateMap 折现利率
   * @param lossRatioMap 赔付率假设
   * @param expenseMap 维持费用假设
   * @param padMap 非金融风险调整
   * @param entity 计量源数据
   * @return measureCfResultInfo
   */
  protected MeasureCfResultInfo getCxRiBbaMeasureCfResultInfoRst(String evaluateMethod, MeasureCfResultInfo measureCfResultInfoLast,
    MeasureCfResultInfo measureCfResultInfoInit, Map<String, BigDecimal> paaDisrateMap,
    Map<String, BigDecimal> lossRatioMap, Map<String, MeasureCfResultInfo> lastMeasureCfResultInfoMap,
    Map<String, BigDecimal> expenseMap, Map<String, BigDecimal> padMap, MeasureCfBasicData entity) {
    //数据初始化
    MeasureCfResultInfo measureCfResultInfo = measure1CfInfoService.iniMeasureCfResultInfo();
//    //1.上期评估时点 = 上期评估时点
//    measure1CfInfoService.getLastValMonth(entity, measureCfResultInfo, evaluateMethod);
//    //2.当前评估时点 = 当前评估时点
//    measure1CfInfoService.getValMonth(entity, measureCfResultInfo, evaluateMethod);
//    //3.计量单元标号 = 计量单元标号
//    measure1CfInfoService.getUnitId(entity, measureCfResultInfo, evaluateMethod);
//    //4.赠险标签 = 赠险标签
//    measure1CfInfoService.getPresentFlag(entity, measureCfResultInfo, evaluateMethod);
//    //5.I17险种代码 =  I17险种代码
//    measure1CfInfoService.getRiskCode(entity, measureCfResultInfo, evaluateMethod);
//    //6.缴费频率 = 缴费频率
//    measure1CfInfoService.getPayFreq(entity, measureCfResultInfo, evaluateMethod);
//    //7.初始确认年月 = 初始确认年月
//    measure1CfInfoService.getInitCfmYm(entity, measureCfResultInfo, evaluateMethod);
//    //8.分出保费
//    measure1CfInfoService.getInitCededOutPrem(entity, measureCfResultInfo, evaluateMethod);
//    //9.再保互助比例
//    measure1CfInfoService.getReinPartRatio(entity, measureCfResultInfo, evaluateMethod);
//    //10.期调整因子
//    measure1CfInfoService.getPeriodAdjRatio(entity, measureCfResultInfo, evaluateMethod);
//    //11.盈余比例
//    measure1CfInfoService.getSurplusRatio(entity, measureCfResultInfo, evaluateMethod);
//    //12.投资成分
//    measure1CfInfoService.getInvComp(measureCfResultInfo, evaluateMethod);
//    //13.合同组合编号
//    measure1CfInfoService.getPortfolioId(entity, measureCfResultInfo, evaluateMethod);
//    //14.币种
//    measure1CfInfoService.getCurrency(entity, measureCfResultInfo, evaluateMethod);
//    //15.评估方法
//    measure1CfInfoService.getValMethod(entity, measureCfResultInfo, evaluateMethod);
//    //16.合同分组编号
//    measure1CfInfoService.getGroupId(entity, measureCfResultInfo, evaluateMethod);
//    //21.是否当期新单
//    measure1CfInfoService.getWhetherCurPolicy(entity,measureCfResultInfo, evaluateMethod);
//    //22.满期日期
//    measure1CfInfoService.getEndDate(entity, measureCfResultInfo, evaluateMethod);
//    //23.保障期限
//    measure1CfInfoService.getTerm(entity, measureCfResultInfo, evaluateMethod);
//    //24.当期服务量
//    measure1CfInfoService.getCurrServAmt(measureCfResultInfo, evaluateMethod);
//    //25.当期及未来服务量
//    measure1CfInfoService.getOtherServAmt(measureCfResultInfo, evaluateMethod);
//    //26.当期确认比例
//    measure1CfInfoService.getCurRecPct(measureCfResultInfo, evaluateMethod);
//    //27.期初未确认保费
//    measure1CfInfoService.getPremBopUnRecAmt(entity, measureCfResultInfoLast, measureCfResultInfo);
//    //28.期初保费计息
//    measure1CfInfoService.getPremInterestAmt(measureCfResultInfo);
//    //29.当期确认的保费
//    measure1CfInfoService.getPremCurRecAmt(measureCfResultInfo, evaluateMethod);
//    //30.期末未确认保费
//    measure1CfInfoService.getPremEopUnRecAmt(measureCfResultInfo, evaluateMethod);
//    //35.期初未确认的投资成分
//    measure1CfInfoService.getIcBopUnRecAmt(lastMeasureCfResultInfoMap, measureCfResultInfo, evaluateMethod);
//    //36.期初投资成分计息
//    measure1CfInfoService.getIcInterestAmt(measureCfResultInfo, evaluateMethod);
//    //37.当期确认的投资成分
//    measure1CfInfoService.getIcPaidAmt(measureCfResultInfo, evaluateMethod);
//    //38.期末未确认的投资成分
//    measure1CfInfoService.getIcEopUnRecAmt(measureCfResultInfo, evaluateMethod);
//    //42.未经保费
//    measure1CfInfoService.getUnRecPremAmt(measureCfResultInfo, evaluateMethod);
//    //48.经过保费
//    measure1CfInfoService.getRecPremAmt(paaDisrateMap, measureCfResultInfo, evaluateMethod);
//    //49.未来现金流量现值_期末
//    measure1CfInfoService.getPvEopRepAmt(expenseMap, lossRatioMap, measureCfResultInfo, evaluateMethod);
//    //50.预期赔付的现值
//    measure1CfInfoService.getPvLossAmt(lossRatioMap, measureCfResultInfo, evaluateMethod);
//    //51.预期维持费用
//    measure1CfInfoService.getPvMaintainAmt(expenseMap, measureCfResultInfo, evaluateMethod);
//    //52.预期现金流量现值
//    measure1CfInfoService.getPvLossTotAmt(expenseMap, lossRatioMap, measureCfResultInfo, evaluateMethod);
//    //53.再保人违约不履约
//    measure1CfInfoService.getReinDefaultAmt(measureCfResultInfo, evaluateMethod);
//    //54.未到期责任资产_摊回未到期_非亏_期末
//    measure1CfInfoService.getLrcRecoveryEopEnd(measureCfResultInfo, evaluateMethod);
//    //55.预期未来现金流出现值_上期(若在 初始评估时点,则为初始)
//    measure1CfInfoService.getPvBelLast(expenseMap, lossRatioMap, measureCfResultInfo, evaluateMethod, measureCfResultInfoInit);
//    //56.预期未来现金流出_初始
//    measure1CfInfoService.getInitPvBel(expenseMap, lossRatioMap, measureCfResultInfo, evaluateMethod);
//    //57.预期未来现金流入现值_期初2
//    measure1CfInfoService.getPvBelLast2(expenseMap, lossRatioMap, measureCfResultInfo, evaluateMethod);
//    //58.预期未来非风险金融调整_初始
//    measure1CfInfoService.getInitPvRa(padMap, measureCfResultInfo, evaluateMethod);
//    //59.未到期_金融风险调整_期初2
//    measure1CfInfoService.getLrcRaLast2(padMap, measureCfResultInfo, evaluateMethod);
//    //60.预期未来现金流入现值_初始
//    measure1CfInfoService.getInitPvBelIn(measureCfResultInfo, evaluateMethod);
//    //61.未到期责任负债_亏损部分_初始
//    measure1CfInfoService.getInitLrcLc(measureCfResultInfo, evaluateMethod);
//    //62.未到期责任负债_亏损部分_初始(再保互动)
//    measure1CfInfoService.getInitLrcLcRein(measureCfResultInfo, evaluateMethod);
//    //63.未来现金流(BEL)_初始
//    measure1CfInfoService.getInitBel(measureCfResultInfo, evaluateMethod);
//    //68.预期未来现金流入现值_期初1
//    measure1CfInfoService.getPvBelLast1(measureCfResultInfoLast, measureCfResultInfo, evaluateMethod);
//    //69.未到期_金融风险调整_上期(若在 初始评估时点,则为初始)
//    measure1CfInfoService.getLrcRaLast(measureCfResultInfo, evaluateMethod, measureCfResultInfoInit);
//    //70.未到期_金融风险调整_期初1
//    measure1CfInfoService.getLrcRaLast1(measureCfResultInfoLast, measureCfResultInfo, evaluateMethod);
//    //71.合同服务边际_初始
//    measure1CfInfoService.getInitCsm(measureCfResultInfo, evaluateMethod);
//    //72.合同服务边际_初始(考虑原保险合同亏损)
//    measure1CfInfoService.getInitCsmA(measureCfResultInfo, evaluateMethod);
//    //73.合同服务边际_初始(不考虑原保险合同亏损)
//    measure1CfInfoService.getInitCsmB(measureCfResultInfo, evaluateMethod);
//    //74.预期非金融风险调整的释放
//    measure1CfInfoService.getPvLrcRaReleaseAmt(paaDisrateMap, measureCfResultInfo, evaluateMethod);
//    //76.合同服务边际_上期
//    measure1CfInfoService.getCsmLast(measureCfResultInfoLast, measureCfResultInfo, evaluateMethod, measureCfResultInfoInit);
//    //77.合同服务边际的释放
//    measure1CfInfoService.getCsmRelease(paaDisrateMap, measureCfResultInfo, evaluateMethod);
//    //78.非金融风险调整_期末
//    measure1CfInfoService.getLrcEopRaAmt(measureCfResultInfo, evaluateMethod);
//    //79.合同服务边际_期末
//    measure1CfInfoService.getCsmEop(measureCfResultInfo, evaluateMethod);
//    //80.未来现金流量(BEL)_计息
//    measure1CfInfoService.getBelIfie(paaDisrateMap, measureCfResultInfo, evaluateMethod);
//    //81.非金融风险调整计息
//    measure1CfInfoService.getRaIfie(measureCfResultInfo, evaluateMethod);
//    //82.合同服务边际计息
//    measure1CfInfoService.getCsmIfie(measureCfResultInfo, evaluateMethod);
//    //83.未到期责任负债-亏损原保险合同
//    measure1CfInfoService.getLrcRecoveryEop(measureCfResultInfo, evaluateMethod);
//    //84.未到期责任负债_亏损部分_上期
//    measure1CfInfoService.getLrcLcLast(measureCfResultInfo, evaluateMethod, measureCfResultInfoInit);
//    //85.亏损部分的释放
//    measure1CfInfoService.getLcRelease(measureCfResultInfo, evaluateMethod);
//    //86.分出保费的分摊
//    measure1CfInfoService.getAmortCededOutPrem(measureCfResultInfo, evaluateMethod);
//    //87.未到期责任资产_摊回未到期_亏损_期末
//    measure1CfInfoService.getLrcLcRecoveryEop(measureCfResultInfo, evaluateMethod);
//    //88.未到期责任负债_亏损
//    measure1CfInfoService.getLrcLcAmt(measureCfResultInfo, evaluateMethod);
//    //89.未到期责任负债_其他部分_期末
//    measure1CfInfoService.getLrcEopOpex(measureCfResultInfo, evaluateMethod);
//    //92.未到期责任负债_摊回亏损部分_期初(再保互动)
//    measure1CfInfoService.getLrcLcLastRein(measureCfResultInfo, evaluateMethod);
//    //93.未到期_亏损部分计息
//    measure1CfInfoService.getLrcLcIfie(measureCfResultInfo, evaluateMethod);

    return measureCfResultInfo;

  }

  /**
   * @param basic 计量源数据
   * @return 当期服务量
   */
  public BigDecimal computeCurrServAmt(MeasureCfBasicData basic) {
    BigDecimal servAmt = BigDecimal.ZERO;
    Date valMonthDate = DateUtils.endMonth(basic.getValMonth());
    Date evaluateDate = DateUtils.parseDate(basic.getEvaluateDate());
    Date endDate = DateUtils.parseDate(basic.getEndDate());

    //max(9.保险评估起期，2.上期评估时点）
    Date date = DateUtil.compare(evaluateDate, DateUtils.addDays(DateUtils.endMonth(basic.getLastValMonth()),1))
      > NumberConstant.LONG_ZERO ? evaluateDate : DateUtils.addDays(DateUtils.endMonth(basic.getLastValMonth()),1);

    if (StringConstant.STRING_ONE.equals(basic.getWhetherCurPolicy())) {
      if (DateUtils.getDateDiff(valMonthDate, endDate) > NumberConstant.LONG_ZERO) {
        servAmt = servAmt.max(BigDecimal.valueOf(basic.getTerm()));
      } else {
        servAmt = servAmt.max(BigDecimal.valueOf(UtilsCommon.differentDaysByMillisecond(valMonthDate, evaluateDate)).add(BigDecimal.ONE));
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
   * @param confClaim 理赔配置信息
   * @param confMeasureClaimModelMap 赔付模式配置
   * @param confMeasureDiscountRateMap 赔付折现率
   * @return 预期赔付金额
   */
//  @TimeConsuming
  public BigDecimal computePvPaidLoss(MeasureConfCommonClaim confClaim, Map<String, Map<Long, BigDecimal>> confMeasureClaimModelMap, Map<String, BigDecimal> confMeasureDiscountRateMap) {
    Map<Long,BigDecimal> claimModePaidLossMap = Optional.ofNullable(confMeasureClaimModelMap.get(confClaim.getRiskCode())).orElse(Maps.newHashMap());
    if(!claimModePaidLossMap.isEmpty()&&!confMeasureDiscountRateMap.isEmpty()) {
      BigDecimal result = BigDecimal.ZERO;
      for (long i = NumberConstant.LONG_ONE; i <= claimModePaidLossMap.size(); i++) {
        BigDecimal claimModePaidLoss = claimModePaidLossMap.get(i) == null ? BigDecimal.ONE : claimModePaidLossMap.get(i);
        BigDecimal discountRate = confMeasureDiscountRateMap.get(String.valueOf(i))==null ? BigDecimal.ONE : confMeasureDiscountRateMap.get(String.valueOf(i));
        result = result.add(confClaim.getUltimatePaidLoss().multiply(claimModePaidLoss).multiply(discountRate));
      }
      return result;
    }
    return confClaim.getUltimatePaidLoss();
  }

  /**
   * 计算终极赔付金额
   * @param confClaim 理赔配置
   * @param actuarialAssumptionMap 精算假设
   * @return 最终赔付金额
   */
//  @TimeConsuming
  public BigDecimal computeUltimatePaidLoss(MeasureConfCommonClaim confClaim,Map<String,Map<String,Object>> actuarialAssumptionMap) {
    //32.未经过保费
    BigDecimal unRecPremAmt = confClaim.getUnRecPremAmt();
    //赔付率假设
    BigDecimal lossRatio;
    Map<String, Object> stringObjectMap = Optional.ofNullable(actuarialAssumptionMap.get(StringUtils.joinWith("_", Opt.ofBlankAble(confClaim.getClassCode()).orElse(StringConstant.STRING_NA),StringConstant.STRING_NA,
      StringConstant.STRING_NA, StringConstant.STRING_NA
    ))).orElse(Maps.newHashMap());
    lossRatio = (BigDecimal)Optional.ofNullable(stringObjectMap.get(StrUtil.toUnderlineCase(ReflectUtils.getFieldName(ConfMeasureActuarialAssumption::getLossRatio)))).orElse(BigDecimal.ZERO);

    //间接理赔费用率假设
    BigDecimal indirectClaimsExpenseRatio;
    indirectClaimsExpenseRatio = (BigDecimal)Optional.ofNullable(stringObjectMap.get(StrUtil.toUnderlineCase(ReflectUtils.getFieldName(ConfMeasureActuarialAssumption::getIndirectClaimsExpenseRatio)))).orElse(BigDecimal.ZERO);
    //32.未经过保费*b.对应险种代码的赔付率*(1+b.对应现在代码的间接理赔费用率)
    return unRecPremAmt.multiply(lossRatio).multiply(BigDecimal.ONE.add(indirectClaimsExpenseRatio));
  }

  /**
   * 53.未经过保费
   *
   * @param measureCommonClaim 理赔配置
   * @param evaluateMethodTypeEnum 评估方法
   * = 再保分入PAA/直保PAA (15.保费-本币 * (31.当期及未来服务量 - 30.当期服务量) / 31.当期及未来服务量) * (( e.当前评估月所对应的利率)^(30.当期服务量/365))
   * = 再保分出PAA  (32.期初未确认的保费 * (31.当期及未来服务量 - 30.当期服务量) / 31.当期及未来服务量) * ((e.当前评估月所对应的利率)^(30.当期服务量/365))
   */
//  @TimeConsuming
  public BigDecimal computeUnRecPremAmt(MeasureConfCommonClaim measureCommonClaim, EvaluateMethodTypeEnum evaluateMethodTypeEnum, Map<String,BigDecimal> disrateMap) {
    BigDecimal item1 = (Objects.equals(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_11, evaluateMethodTypeEnum) || Objects.equals(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_8, evaluateMethodTypeEnum))
      ? measureCommonClaim.getPremiumCny()
      : measureCommonClaim.getPremEopUnRecAmt();

    //当前评估月所对应的利率
    BigDecimal disrate = Optional.ofNullable(disrateMap.get(StringConstant.STRING_NA+"_"+StringConstant.STRING_NA+"_"+StringConstant.STRING_ONE)).orElse(BigDecimal.ONE);

    //(当前评估月所对应的利率^(35.当期服务量/365))
    double pow = Math.pow(disrate.doubleValue(), measureCommonClaim.getCurrServAmt().divide(new BigDecimal(365), 10, RoundingMode.HALF_UP).doubleValue());

    BigDecimal result = item1
      .multiply(measureCommonClaim.getOtherServAmt().subtract(measureCommonClaim.getCurrServAmt()))  // result1 = otherServAmt - currServAmt
      .divide(BigDecimal.valueOf(Long.parseLong(measureCommonClaim.getTerm())), 10, RoundingMode.HALF_UP)  // result1 / otherServAmt
      .multiply(BigDecimal.valueOf(pow))
      .setScale(10, RoundingMode.HALF_UP);  // 设置最终精度

    return Optional.ofNullable(result).orElse(BigDecimal.ZERO);
  }

  /**
   * @param confClaim 理赔配置
   * @return 期末未确认的保费
   */
  public BigDecimal computePremEopUnRecAmt(MeasureConfCommonClaim confClaim) {
    return confClaim.getPremBopUnRecAmt().add(confClaim.getPremInterestAmt()).subtract(confClaim.getPremCurRecAmt());
  }

  /**
   * @param confClaim 理赔配置
   * @return 当期确认的保费
   */
//  @TimeConsuming
  public BigDecimal computePremCurRecAmt(MeasureConfCommonClaim confClaim) {
    return (confClaim.getPremBopUnRecAmt().add(confClaim.getPremInterestAmt())).multiply(confClaim.getCurRecPct());
  }

  /**
   * @param measureCommonClaim 理赔配置
   * @param disrateMap 利率表
   * @return 期初保费计息
   */
//  @TimeConsuming
  public BigDecimal computePremInterestAmt(MeasureConfCommonClaim measureCommonClaim,Map<String,BigDecimal> disrateMap) {
    BigDecimal premBopUnRecAmt = measureCommonClaim.getPremBopUnRecAmt();
    BigDecimal currServAmt = measureCommonClaim.getCurrServAmt();
    BigDecimal computeDisrate = Optional.ofNullable(disrateMap.get(StringConstant.STRING_NA +"_"+StringConstant.STRING_NA+"_"+StringConstant.STRING_ONE)).orElse(BigDecimal.ONE);
    return premBopUnRecAmt.multiply(BigDecimal.valueOf(Math.pow(computeDisrate.doubleValue(),(currServAmt.divide(BigDecimal.valueOf(365), 10,
        RoundingMode.HALF_UP).doubleValue())))).subtract(premBopUnRecAmt);
  }

  /**
   * @param basic 计量源数据
   * @return 上期末当期确认的保费map
   * @return 期初未确认保费
   */
//  @TimeConsuming
  public BigDecimal computePremBopUnRecAmt(MeasureCfBasicData basic,Map<String,MeasureConfCommonClaim> lastMeasureCfCommonClaimMap) {
    BigDecimal premBopUnRecAmt;
    if (StringConstant.STRING_ONE.equals(basic.getPresentFlag())) {
      premBopUnRecAmt = BigDecimal.ZERO;
    } else {
      if (StringConstant.STRING_ONE.equals(basic.getWhetherCurPolicy())) {
        premBopUnRecAmt = basic.getPremiumCny();
      } else {
        premBopUnRecAmt = Optional.ofNullable(lastMeasureCfCommonClaimMap.get(basic.getUnitId())).map(MeasureConfCommonClaim::getPremEopUnRecAmt).orElse(BigDecimal.ZERO);
      }
    }
    return Optional.ofNullable(premBopUnRecAmt).orElse(BigDecimal.ZERO);
  }

  /**
   * @param basic 计量源数据
   * @return 当期及未来服务量
   */
  public BigDecimal computeOtherServAmt(MeasureCfBasicData basic) {
    BigDecimal otherServAmt;
    Date evaluateDate = DateUtils.parseDate(basic.getEvaluateDate());
    Date endDate = DateUtils.parseDate(basic.getEndDate());
    Date lastValMonthDate = DateUtils.addDays(DateUtils.endMonth(basic.getLastValMonth()),1);
    if (StringConstant.STRING_ONE.equals(basic.getWhetherCurPolicy())) {
      otherServAmt = BigDecimal.valueOf(UtilsCommon.differentDaysByMillisecond(endDate, evaluateDate));
    } else {
      Date lastValPeriodPoint = DateUtils.getDateDiff(lastValMonthDate, evaluateDate) > NumberConstant.LONG_ZERO ? lastValMonthDate : evaluateDate;
      otherServAmt = BigDecimal.valueOf(UtilsCommon.differentDaysByMillisecond(endDate, lastValPeriodPoint));
    }
    return otherServAmt.add(BigDecimal.ONE);
  }
}
