package com.jdyx.cx.measure.strategy.impl;

import cn.hutool.core.date.DateField;
import cn.hutool.core.date.DateUtil;
import cn.hutool.core.util.ReUtil;
import cn.hutool.core.util.StrUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import com.jdyx.common.cache.measure.ConfMeasureActuarialAssumptionCacheService;
import com.jdyx.common.constants.ModuleConstants;
import com.jdyx.common.dataplatform.service.CxPublicDbService;
import com.jdyx.common.enums.CurrencyTypeEnum;
import com.jdyx.common.enums.EvaluateMethodTypeEnum;
import com.jdyx.common.measure.constant.GdqConstant;
import com.jdyx.common.measure.constant.NumberConstant;
import com.jdyx.common.measure.constant.StringConstant;
import com.jdyx.common.measure.service.SuperBaseService;
import com.jdyx.cx.measure.strategy.MeasureCfBasicStrategy;
import com.jdyx.measure.api.measure.domain.ConfMeasureActuarialAssumption;
import com.jdyx.measure.api.measure.domain.MeasureCfBasicData;
import com.jdyx.measureprepare.api.domain.TPpJlClmSettled;
import com.jdyx.measureprepare.api.domain.TPpJlContact;
import com.jdyx.measureprepare.api.domain.TPpJlIacfFol;
import com.jdyx.measureprepare.api.domain.TPpJlIacfUnfol;
import com.jdyx.measureprepare.api.domain.TPpJlUlaeSettled;
import com.jdyx.measureprepare.api.mapper.TPpJlContactMapper;
import com.kevin.common.utils.DateUtils;
import com.kevin.common.utils.StringUtils;
import com.kevin.common.utils.reflect.ReflectUtils;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.ibatis.session.ResultContext;
import org.apache.ibatis.session.ResultHandler;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.DefaultTransactionDefinition;

import java.math.BigDecimal;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.stream.Collectors;

import static com.kevin.common.utils.DateUtils.YYYYMMDD;

/**
 * 产险-直保-BBA-7
 * 产险-直保-PAA-8
 *
 * @author 刘瑞奎.
 * @date 2024/10/21.
 */
@SuppressWarnings("DuplicatedCode")
@Slf4j
@RequiredArgsConstructor
@Service
public class MeasureCfBasicData7 extends SuperBaseService implements MeasureCfBasicStrategy {

  /** 7.public库取数服务 */
  private final CxPublicDbService publicDbService;

  private final ConfMeasureActuarialAssumptionCacheService confMeasureActuarialAssumptionCacheService;
  private final TPpJlContactMapper tPpJlContactMapper;
  private final PlatformTransactionManager transactionManager;

  /**
   * 获取 计量模型基础数据策略方法
   *
   * @param evaluateMethod 评估方法 {@link EvaluateMethodTypeEnum}
   * @param valMonth 评估时点(yyyyMM)
   * @return java.util.List<com.jdyx.measure.api.measure.domain.MeasureCfBasicData>
   * @author kevin.
   * @date 2024/10/21.
   */
  @Override
  public void doOperation(EvaluateMethodTypeEnum evaluateMethod, String valMonth) {
    Map<String, BigDecimal> pJlIacfFolMap;
    Map<String, Map<String,Object>> getPpJlIacfUnfolMap;
    Map<String, Map<String, Object>> measureActuarialAssumptionMap = confMeasureActuarialAssumptionCacheService.getConfMeasureActuarialAssumptionFromValMethod(evaluateMethod.getCode());
    if(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_8.getCode().equals(evaluateMethod.getCode())
      || EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_7.getCode().equals(evaluateMethod.getCode())){
      //产险直保计量_保险获取现金流_跟单:iacfCny + iacfTax
      pJlIacfFolMap = getPpJlIacfFolMap(valMonth, evaluateMethod.getCode(), TPpJlIacfFol::getIacfFolCny, TPpJlIacfFol::getIacfTax, TPpJlIacfFol::getIacfTaxPolicy);
      //产险直保计量_保险获取现金流_非跟单
      getPpJlIacfUnfolMap = getPpJlIacfUnfolMap2(valMonth, evaluateMethod.getCode(), TPpJlIacfUnfol::getIacfOutUnfolCny,TPpJlIacfUnfol::getMaintenanceRealCny);
    }else {
      pJlIacfFolMap = null;
      getPpJlIacfUnfolMap = null;
    }
    //获取已决赔款数据
    Map<String, TPpJlClmSettled> clmSettledMap = getTPpJlClmSettledMap(valMonth, evaluateMethod.getCode(), TPpJlClmSettled::getSettledLossPastCny,TPpJlClmSettled::getSettledLossCurrCny);
    //获取已决间接理赔费用
    Map<String, TPpJlUlaeSettled> ulaeSettledMap = getTPpJlUlaeSettledMap(valMonth, evaluateMethod.getCode(), TPpJlUlaeSettled::getUlaeSettledPastCny,TPpJlUlaeSettled::getUlaeSettledCurrCny);
    //一.获取 计量源数据(从计量数据准备输出数据中获取)
    //构建参数
    LambdaQueryWrapper<TPpJlContact> lambdaQueryWrapper = Wrappers.lambdaQuery();
    //1.评估时点
    lambdaQueryWrapper.eq(TPpJlContact::getRunDate, valMonth);
    //2.评估方法
    lambdaQueryWrapper.eq(TPpJlContact::getValMethod, evaluateMethod.getCode());
    //如果(6.签单日期,25.批单生效日)>2.当期评估日期，则该条数据有错，不应放在当前评估
    lambdaQueryWrapper.apply("COALESCE(to_char(certi_write_date,'YYYYMM'),to_char(under_write_date,'YYYYMM'))<={0}",valMonth);
    long selectCount = tPpJlContactMapper.selectCount(lambdaQueryWrapper);
    log.info("selectCount={}",selectCount);
    tPpJlContactMapper.selectList(lambdaQueryWrapper, new ResultHandler<TPpJlContact>() {
      final List<TPpJlContact> tPpJlContactList = Lists.newLinkedList();
      @Override
      public void handleResult(ResultContext<? extends TPpJlContact> resultContext) {
        tPpJlContactList.add(resultContext.getResultObject());
        if(tPpJlContactList.size()==10000){
          generateMeasureCfBasic(tPpJlContactList,evaluateMethod,valMonth,pJlIacfFolMap,getPpJlIacfUnfolMap,measureActuarialAssumptionMap,clmSettledMap,ulaeSettledMap);
          tPpJlContactList.clear();
          log.info("当前已处理={}",resultContext.getResultCount());
        }
        if(selectCount== resultContext.getResultCount()&&StringUtils.isNotEmpty(tPpJlContactList)){
          generateMeasureCfBasic(tPpJlContactList,evaluateMethod,valMonth,pJlIacfFolMap,getPpJlIacfUnfolMap,measureActuarialAssumptionMap,clmSettledMap,ulaeSettledMap);
          tPpJlContactList.clear();
          log.info("当前已处理={}",resultContext.getResultCount());
        }
      }
    });
  }

  /**
   * 计算保障期限
   *
   * @param cfBasicData 计量源数据
   * @return 保障期限
   */
  private Long computeTerm(MeasureCfBasicData cfBasicData) {
    Date evaluateDate = DateUtil.parse(cfBasicData.getEvaluateDate());
    Date endDate = DateUtil.parse(cfBasicData.getEndDate());
    return DateUtil.betweenDay(endDate, evaluateDate, true) + 1;
  }

  private void generateMeasureCfBasic(List<TPpJlContact> tPpJlContactList,EvaluateMethodTypeEnum evaluateMethod, String valMonth,Map<String, BigDecimal> pJlIacfFolMap,Map<String, Map<String,Object>> getPpJlIacfUnfolMap,Map<String, Map<String, Object>> measureActuarialAssumptionMap, Map<String, TPpJlClmSettled> clmSettledMap, Map<String, TPpJlUlaeSettled> ulaeSettledMap){
    List<MeasureCfBasicData> measureCfBasicDataList = tPpJlContactList.stream().map(e->{
      MeasureCfBasicData cfBasicData = new MeasureCfBasicData();
      //当期评估月(YYYYmm)
      cfBasicData.setValMonth(valMonth);
      //上期评估月(YYYYmm)
      if(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_8.getCode().equals(evaluateMethod.getCode())&&GdqConstant.GDQ_DATE.equals(cfBasicData.getValMonth())){
        cfBasicData.setLastValMonth(GdqConstant.GDQ_DATE_SEVEN_YEARS_AGO);
      }else {
        cfBasicData.setLastValMonth(DateUtils.lastEndYear(valMonth, DateUtils.YYYYMM));
      }
      //评估方法
      cfBasicData.setValMethod(evaluateMethod.getCode());
      //计量单元编号
      cfBasicData.setUnitId(Optional.ofNullable(e.getUnitId()).orElse(StringConstant.STRING_NA));
      cfBasicData.setPolicyNo(Optional.ofNullable(e.getPolicyNo()).orElse(StringConstant.STRING_NA));
      cfBasicData.setCertiNo(Optional.ofNullable(e.getCertiNo()).orElse(StringConstant.STRING_NA));
      //赠险标签(1-是 0-否)
      cfBasicData.setPresentFlag(Optional.ofNullable(e.getPresentFlag()).orElse("0"));
      //I17险种代码
      cfBasicData.setRiskCode(Optional.ofNullable(e.getRiskCode()).orElse(StringConstant.STRING_NA));
      //签单日期
      cfBasicData.setUnderWriteDate(DateUtils.parseDateToStr(YYYYMMDD, DateUtils.toDate(e.getUnderWriteDate())));
      //保修期
      cfBasicData.setWarrantyPeriod(e.getWarrantyPeriod());
      //批单生效日
      Optional.ofNullable(e.getValidDate()).map(DateUtils::toDate).ifPresent(d-> cfBasicData.setValidDate(DateUtils.parseDateToStr(YYYYMMDD, d)));
      //批单签单日期
      Optional.ofNullable(e.getCertiWriteDate()).ifPresent(d->cfBasicData.setCertiWriteDate(DateUtils.parseDateToStr(YYYYMMDD, d)));

      //满期日期 = 保险责任止期(YYYYmmDD)
      cfBasicData.setEndDate(DateUtils.parseDateToStr(YYYYMMDD, DateUtils.toDate(e.getEndDate())));
      //保险责任起期
      if(!StringConstant.STRING_NA.equals(cfBasicData.getCertiNo())){
        if(DateUtils.getDateDiff(cfBasicData.getValidDate(),cfBasicData.getEndDate())>=NumberConstant.LONG_ZERO){
          cfBasicData.setStartDate(cfBasicData.getEndDate());
        }else {
          cfBasicData.setStartDate(cfBasicData.getValidDate());
        }
      }else {
      cfBasicData.setStartDate(DateUtils.parseDateToStr(YYYYMMDD, e.getStartDate()));
      }
      //保险评估起期
      if (StringUtils.isBlank(cfBasicData.getWarrantyPeriod())) {
        cfBasicData.setEvaluateDate(cfBasicData.getStartDate());
      } else {
        //保修期不为空，则取保险责任起期日期+保修期日期 备注：保修期数据可能为类似3年/10万里这样，所以需要取保险责任起期日期+3年
        int numYear = 0;
        if (ReUtil.isMatch("(\\d+)年.*", cfBasicData.getWarrantyPeriod())) {
          numYear = Integer.parseInt(ReUtil.getGroup1("(\\d+)年.*", cfBasicData.getWarrantyPeriod()));
        }
        String evaluateDate = DateUtils.parseDateToStr(YYYYMMDD, DateUtil.offset(DateUtils.parseDate(cfBasicData.getStartDate()), DateField.YEAR, numYear));
        cfBasicData.setEvaluateDate(evaluateDate);
      }
      //保费-本币
      cfBasicData.setPremiumCny(Optional.ofNullable(e.getPremiumCny()).orElse(BigDecimal.ZERO));
      //投资成分占比
        cfBasicData.setInvestProp(Optional.ofNullable(e.getInvestProp()).orElse(BigDecimal.ZERO));
      //合同组合编号(短)
      cfBasicData.setPortfolioId(Optional.ofNullable(e.getPortfolioId()).orElse(StringConstant.STRING_NA));
      //险类代码
      cfBasicData.setClassCode(Optional.ofNullable(e.getClassCode()).orElse(StringConstant.STRING_NA));
      //保费获取现金流本币
      cfBasicData.setIacfFolCny(getIacfFolCnyWithActuarialAssumption(cfBasicData,measureActuarialAssumptionMap,ConfMeasureActuarialAssumption::getAcquisitionExpenseRatio));
      //本币币种
      cfBasicData.setCurrency(CurrencyTypeEnum.CURRENCY_TYPE_CNY.getCode());
      //合同分组编号(长)
      cfBasicData.setGroupId(Optional.ofNullable(e.getGroupId()).orElse(StringConstant.STRING_NA));
      //是否新单
      Date underWriteDate = Optional.ofNullable(e.getCertiWriteDate())
          .orElse(DateUtils.toDate(e.getUnderWriteDate()));
      if (DateUtils.getDateDiff(DateUtils.parseDateToStr(YYYYMMDD, underWriteDate), DateUtils.endMonth(cfBasicData.getLastValMonth(), YYYYMMDD)) <= NumberConstant.LONG_ZERO) {
        cfBasicData.setWhetherCurPolicy(StringConstant.STRING_ZERO);
      } else if (DateUtils.getDateDiff(DateUtils.parseDateToStr(YYYYMMDD, underWriteDate), DateUtils.endMonth(cfBasicData.getLastValMonth(), YYYYMMDD)) > NumberConstant.LONG_ZERO
        && DateUtils.getDateDiff(DateUtils.parseDateToStr(YYYYMMDD, underWriteDate), DateUtils.endMonth(cfBasicData.getValMonth(), YYYYMMDD)) <= NumberConstant.LONG_ZERO) {
        cfBasicData.setWhetherCurPolicy(StringConstant.STRING_ONE);
      }

      // 保障期限
      cfBasicData.setTerm(computeTerm(cfBasicData));

      //归属机构
      cfBasicData.setComCode(Optional.ofNullable(e.getComCode()).orElse(StringConstant.STRING_NA));
      //业务渠道
      cfBasicData.setBusinessNature(Optional.ofNullable(e.getBusinessNature()).orElse(StringConstant.STRING_NA));
      if(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_8.getCode().equals(evaluateMethod.getCode())){
        cfBasicData.setCoverageSegment(Optional.ofNullable(e.getCoverageSegment()).orElse(StringConstant.STRING_NA));
      }
      //车辆种类
      cfBasicData.setCarKindCode(Optional.ofNullable(e.getCarKindCode()).orElse(StringConstant.STRING_NA));
      //使用性质
      cfBasicData.setUseNatureCode(Optional.ofNullable(e.getUseNatureCode()).orElse(StringConstant.STRING_NA));
      // 条款险别
      cfBasicData.setCoverageSegment(Optional.ofNullable(e.getCoverageSegment()).orElse(StringConstant.STRING_NA));

      //实际获取费用
      Map<String, Object> tPpJlIacfUnfolMap2 = Optional.ofNullable(getPpJlIacfUnfolMap.get(cfBasicData.getUnitId()))
          .orElse(Maps.newHashMap());
      cfBasicData.setIacfActual(Objects.requireNonNull(pJlIacfFolMap).getOrDefault(cfBasicData.getUnitId(),BigDecimal.ZERO).add((BigDecimal) tPpJlIacfUnfolMap2.getOrDefault(
          StrUtil.toUnderlineCase(ReflectUtils.getFieldName(TPpJlIacfUnfol::getIacfOutUnfolCny)),BigDecimal.ZERO)));

      if(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_8.getCode().equals(evaluateMethod.getCode())){
        //保险获取现金流_本币_再保
        cfBasicData.setIacfFolCnyRein(getIacfFolCnyWithActuarialAssumption(cfBasicData,measureActuarialAssumptionMap,
            ConfMeasureActuarialAssumption::getFirstDayAcquisitionExpenseRatio));
        //实际获取费用_再保
        cfBasicData.setIacfActualRein(Objects.requireNonNull(pJlIacfFolMap).getOrDefault(cfBasicData.getUnitId(),BigDecimal.ZERO));
      }

      if(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_7.getCode().equals(evaluateMethod.getCode())){
        //计划缴费日期
        if(StringConstant.STRING_NA.equals(cfBasicData.getCertiNo())){
          cfBasicData.setPlanDate(DateUtils.parseDateToStr(YYYYMMDD, DateUtils.toDate(e.getUnderWriteDate())));
        }else{
          cfBasicData.setPlanDate(DateUtils.parseDateToStr(YYYYMMDD, e.getCertiWriteDate()));
        }

        //批单签单日期
        if (e.getCertiWriteDate() != null){
          cfBasicData.setCertiWriteDate(DateUtils.parseDateToStr(YYYYMMDD, e.getCertiWriteDate()));
        }
          //I17初始确认日期
        cfBasicData.setIniConfirm(e.getIniConfirm().format(DateTimeFormatter.ofPattern(YYYYMMDD)));
      }

      if(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_8.getCode().equals(evaluateMethod.getCode())){
        Optional.ofNullable(clmSettledMap.get(cfBasicData.getUnitId())).ifPresent(
            tPpJlClmSettled -> {
              cfBasicData.setLossActual(tPpJlClmSettled.getSettledLossPastCny().add(tPpJlClmSettled.getSettledLossCurrCny()));
            }
        );
        Optional.ofNullable(ulaeSettledMap.get(cfBasicData.getUnitId())).ifPresent(
            tPpJlUlaeSettled -> {
              cfBasicData.setIndirectClaimsExpenseActual(tPpJlUlaeSettled.getUlaeSettledPastCny().add(tPpJlUlaeSettled.getUlaeSettledCurrCny()));
            }
        );
          BigDecimal sumMaintenanceRealCny = (BigDecimal) tPpJlIacfUnfolMap2.getOrDefault(
              StrUtil.toUnderlineCase(ReflectUtils.getFieldName(TPpJlIacfUnfol::getMaintenanceRealCny)),BigDecimal.ZERO);
          cfBasicData.setMaintenanceExpenseActual(sumMaintenanceRealCny);
      }
      //创建人
      cfBasicData.setCreateBy(ModuleConstants.MEASURE_CALCULATE);
      //修改人
      cfBasicData.setUpdateBy(ModuleConstants.MEASURE_CALCULATE);
      return cfBasicData;
    }).collect(Collectors.toList());
    batchesSaveCommit(measureCfBasicDataList);
  }

  /**
   * 提交数据到数据库
   *
   * @param measureCfBasicDataList 待存储数据
   */
  private void batchesSaveCommit(List<MeasureCfBasicData> measureCfBasicDataList) {
    DefaultTransactionDefinition def = new DefaultTransactionDefinition();
    def.setPropagationBehavior(DefaultTransactionDefinition.PROPAGATION_REQUIRES_NEW);
    // 获取事务状态
    TransactionStatus status = transactionManager.getTransaction(def);
    try {
      //存储明细数据
      boolean insertBatchStatus = measureCfBasicDataMapper.insertBatch(measureCfBasicDataList);
      log.info("本次存储计量源数据提取数据={}条", measureCfBasicDataList.size());
      // 手动提交事务
      transactionManager.commit(status);
    } catch (Exception e) {
      // 发生异常时回滚事务
      transactionManager.rollback(status);
      log.error(e.getMessage(), e);
    }
  }
}
