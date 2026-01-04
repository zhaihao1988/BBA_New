package com.jdyx.cx.measure.strategy.impl;

import cn.hutool.core.date.DateUtil;
import cn.hutool.core.util.StrUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import com.jdyx.common.cache.measure.ConfMeasureActuarialAssumptionCacheService;
import com.jdyx.common.dataplatform.service.CxPublicDbService;
import com.jdyx.common.enums.EvaluateMethodTypeEnum;
import com.jdyx.common.measure.constant.GdqConstant;
import com.jdyx.common.measure.constant.NumberConstant;
import com.jdyx.common.measure.constant.StringConstant;
import com.jdyx.common.measure.service.SuperBaseService;
import com.jdyx.cx.measure.strategy.MeasureCfBasicStrategy;
import com.jdyx.measure.api.measure.domain.ConfMeasureActuarialAssumption;
import com.jdyx.measure.api.measure.domain.MeasureCfBasicData;
import com.jdyx.measureprepare.api.domain.TPpJlClmSettled;
import com.jdyx.measureprepare.api.domain.TPpJlIacfUnfol;
import com.jdyx.measureprepare.api.domain.TPpJlUlaeSettled;
import com.jdyx.measureprepare.api.domain.TPpReMonArrIn;
import com.jdyx.measureprepare.api.mapper.TPpReMonArrInMapper;
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
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Collectors;

/**
 * 产险-再保分入-PAA-11
 *
 * @author 刘瑞奎.
 * @date 2024/10/21.
 */
@SuppressWarnings("DuplicatedCode")
@Slf4j
@RequiredArgsConstructor
@Service
public class MeasureCfBasicData11 extends SuperBaseService implements MeasureCfBasicStrategy {

  /** public库取数服务 */
  private final CxPublicDbService publicDbService;
  /**
   * 获取缓存精算假设配置
   */
  private final ConfMeasureActuarialAssumptionCacheService confMeasureActuarialAssumptionCacheService;

  private final TPpReMonArrInMapper tppReMonArrInMapper;

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
    //获取 产险-再保分入-PAA-精算假设表
    Map<String, Map<String, Object>> measureActuarialAssumptionMap = confMeasureActuarialAssumptionCacheService.getConfMeasureActuarialAssumptionFromValMethod(evaluateMethod.getCode());
    Map<String, Map<String,Object>> getPpJlIacfUnfolMap = getPpJlIacfUnfolMap2(valMonth, evaluateMethod.getCode(), TPpJlIacfUnfol::getIacfOutUnfolCny, TPpJlIacfUnfol::getMaintenanceRealCny);
    Map<String,MeasureCfBasicData> lastMeasureCfBasicData = getLastMeasureCfBasicData(DateUtils.lastEndYear(valMonth, DateUtils.YYYYMM), evaluateMethod.getCode(),MeasureCfBasicData::getIacfActualRein);
    //获取已决赔款数据
    Map<String, TPpJlClmSettled> clmSettledMap = getTPpJlClmSettledMap(valMonth, evaluateMethod.getCode(), TPpJlClmSettled::getSettledLossPastCny,TPpJlClmSettled::getSettledLossCurrCny);
//获取已决间接理赔费用
    Map<String, TPpJlUlaeSettled> ulaeSettledMap = getTPpJlUlaeSettledMap(valMonth, evaluateMethod.getCode(), TPpJlUlaeSettled::getUlaeSettledPastCny,TPpJlUlaeSettled::getUlaeSettledCurrCny);
    //一.获取 计量源数据(从计量数据准备输出数据中获取)
    //构建参数
    LambdaQueryWrapper<TPpReMonArrIn> lambdaQueryWrapper = Wrappers.lambdaQuery();
    //1.评估时点
    lambdaQueryWrapper.eq(TPpReMonArrIn::getValMonth, valMonth);
    //2.评估方法
    lambdaQueryWrapper.eq(TPpReMonArrIn::getValMethod, evaluateMethod.getCode());
    //如果(6.签单日期,25.批单生效日)>2.当期评估日期，则该条数据有错，不应放在当前评估
    lambdaQueryWrapper.apply("to_char(confirm_date,'YYYYMM')<={0}",valMonth);
    long selectCount = tppReMonArrInMapper.selectCount(lambdaQueryWrapper);
    log.info("selectCount={}",selectCount);
    tppReMonArrInMapper.selectList(lambdaQueryWrapper, new ResultHandler<TPpReMonArrIn>() {
      final List<TPpReMonArrIn> tPpReMonArrInList = Lists.newLinkedList();
      @Override
      public void handleResult(ResultContext<? extends TPpReMonArrIn> resultContext) {
        tPpReMonArrInList.add(resultContext.getResultObject());
        if(tPpReMonArrInList.size()==10000){
          generateMeasureCfBasic(tPpReMonArrInList,evaluateMethod,valMonth,measureActuarialAssumptionMap,getPpJlIacfUnfolMap,lastMeasureCfBasicData,clmSettledMap,ulaeSettledMap);
          tPpReMonArrInList.clear();
          log.info("当前已处理={}",resultContext.getResultCount());
        }
        if(selectCount== resultContext.getResultCount()&&StringUtils.isNotEmpty(tPpReMonArrInList)){
          generateMeasureCfBasic(tPpReMonArrInList,evaluateMethod,valMonth,measureActuarialAssumptionMap,getPpJlIacfUnfolMap,lastMeasureCfBasicData,clmSettledMap,ulaeSettledMap);
          tPpReMonArrInList.clear();
          log.info("当前已处理={}",resultContext.getResultCount());
        }
      }
    });
  }

  private void generateMeasureCfBasic(List<TPpReMonArrIn> tPpReMonArrInList, EvaluateMethodTypeEnum evaluateMethod, String valMonth,Map<String, Map<String, Object>> measureActuarialAssumptionMap,Map<String, Map<String,Object>> getPpJlIacfUnfolMap,Map<String,MeasureCfBasicData> lastMeasureCfBasicData,Map<String, TPpJlClmSettled> clmSettledMap,Map<String, TPpJlUlaeSettled> ulaeSettledMap) {
    List<MeasureCfBasicData> basicDataList = tPpReMonArrInList.stream().map(e->{
      MeasureCfBasicData cfBasicData = new MeasureCfBasicData();
      //当期评估月(YYYYmm) = 当前评估日期
      cfBasicData.setValMonth(valMonth);
      //上期评估时点（YYYYmm)=上年末月
      if(GdqConstant.GDQ_DATE.equals(cfBasicData.getValMonth())){
        cfBasicData.setLastValMonth(GdqConstant.GDQ_DATE_SEVEN_YEARS_AGO);
      }else {
        cfBasicData.setLastValMonth(DateUtils.lastEndYear(valMonth, DateUtils.YYYYMM));
      }
      //评估方法
      cfBasicData.setValMethod(evaluateMethod.getCode());
      //计量层级编号 = 再保险合同计算单元编号
      cfBasicData.setUnitId(e.getUnitId());
      //合约临分标识
      cfBasicData.setContractFlag(e.getContractFlag());
      //临分类型
      cfBasicData.setEnquiryType(e.getEnquiryType());
      //合约类型
      cfBasicData.setContractType(e.getContractType());
      //合约ID
      cfBasicData.setContractId(e.getContractId());
      //合约分项号
      cfBasicData.setSectionNo(e.getSectionNo());
      //超赔层
      cfBasicData.setSectionLayerNo(e.getSectionLayerNo());
      //临分保单号
      cfBasicData.setPolicyNo(e.getPolicyNo());
      //批单号
      cfBasicData.setCertiNo(Optional.ofNullable(e.getCertiNo()).orElse(StringConstant.STRING_NA));
      //险种代码
      cfBasicData.setRiskCode(e.getRiskCode());
      //确认时间
      cfBasicData.setConfirmDate(DateUtils.parseDateToStr(DateUtils.YYYYMMDD,e.getConfirmDate()));
      //签单日期
      cfBasicData.setUnderWriteDate(DateUtils.parseDateToStr(DateUtils.YYYYMMDD, e.getUnderWriteDate()));
      //批单生效日
      Optional.ofNullable(e.getModifyDate()).ifPresent(d->cfBasicData.setModifyDate(DateUtils.parseDateToStr(DateUtils.YYYYMMDD, e.getModifyDate())));
      //保险责任止期
      cfBasicData.setEndDate(DateUtils.parseDateToStr(DateUtils.YYYYMMDD, e.getPiEndDate()));
      // 再保险合同责任起期
      if(!StringConstant.STRING_NA.equals(cfBasicData.getCertiNo())){
        if(DateUtils.getDateDiff(cfBasicData.getModifyDate(),cfBasicData.getEndDate())>=NumberConstant.LONG_ZERO){
          cfBasicData.setStartDate(cfBasicData.getEndDate());
        }else {
          cfBasicData.setStartDate(cfBasicData.getModifyDate());
        }
      }else {
        cfBasicData.setStartDate(DateUtils.parseDateToStr(DateUtils.YYYYMMDD, e.getPiStartDate()));
      }

      //保费-本币
      cfBasicData.setPremiumCny(Optional.ofNullable(e.getPremium()).orElse(BigDecimal.ZERO));
      //合同组合编码
      cfBasicData.setPortfolioId(Optional.ofNullable(e.getPortfolioId()).orElse(StringConstant.STRING_NA));
      //合同分组编码
      cfBasicData.setGroupId(Optional.ofNullable(e.getGroupId()).orElse(StringConstant.STRING_NA));
      //险类代码
      cfBasicData.setClassCode(Optional.ofNullable(e.getClassCode()).orElse(StringConstant.STRING_NA));
      //保险获取现金流_本币
      cfBasicData.setIacfFolCny(getIacfFolCnyWithActuarialAssumption(cfBasicData,measureActuarialAssumptionMap,
          ConfMeasureActuarialAssumption::getAcquisitionExpenseRatio));
      //币种
      cfBasicData.setCurrency(e.getCurrencyEpi());
      //合同分组编码
      //是否当期新单
      if (DateUtils.getDateDiff(cfBasicData.getConfirmDate(), DateUtils.endMonth(cfBasicData.getLastValMonth(), DateUtils.YYYYMMDD)) <= NumberConstant.LONG_ZERO) {
        cfBasicData.setWhetherCurPolicy(StringConstant.STRING_ZERO);
      } else if (
        DateUtils.getDateDiff(cfBasicData.getConfirmDate(), DateUtils.endMonth(cfBasicData.getLastValMonth(), DateUtils.YYYYMMDD)) > NumberConstant.LONG_ZERO &&
          DateUtils.getDateDiff(cfBasicData.getConfirmDate(), DateUtils.endMonth(cfBasicData.getValMonth(), DateUtils.YYYYMMDD))
            <= NumberConstant.LONG_ZERO) {
        cfBasicData.setWhetherCurPolicy(StringConstant.STRING_ONE);
      }

      //保障期限
      cfBasicData.setTerm(computeTerm(cfBasicData));
      //归属机构
      cfBasicData.setComCode(Optional.ofNullable(e.getComCode()).orElse(StringConstant.STRING_NA));
      //车辆种类
      cfBasicData.setCarKindCode(Optional.ofNullable(e.getCarKindCode()).orElse(StringConstant.STRING_NA));
      //使用性质代码
      cfBasicData.setUseNatureCode(Optional.ofNullable(e.getUseNatureCode()).orElse(StringConstant.STRING_NA));
      //手续费_本币
      cfBasicData.setCommission(e.getCommission());
      //不含税经纪费_本币
      cfBasicData.setBrokerageFee(e.getBrokerage());
      //保底赔付率
      cfBasicData.setMinPayRate(e.getMinPayRate());
      // BigDecimal lastIacfActualRein = BigDecimal.ZERO;
      // if(null!=lastMeasureCfBasicData&&null!=lastMeasureCfBasicData.get(cfBasicData.getUnitId())){
      //   lastIacfActualRein = lastMeasureCfBasicData.get(cfBasicData.getUnitId()).getIacfActualRein();
      // }
      Map<String, Object> tPpJlIacfUnfolMap2 = Optional.ofNullable(getPpJlIacfUnfolMap.get(cfBasicData.getUnitId()))
          .orElse(Maps.newHashMap());
      // 实际获取费用 0828 删除固定手续费
      // 翟总:20250903再次修改，获取费用只剩非跟单了 g.保险获取现金流_非跟单_本币(根据当前评估日期=当期评估时点进行汇总)
      cfBasicData.setIacfActual((BigDecimal) tPpJlIacfUnfolMap2.getOrDefault(
          StrUtil.toUnderlineCase(ReflectUtils.getFieldName(TPpJlIacfUnfol::getIacfOutUnfolCny)),BigDecimal.ZERO));
      // 实际获取费用_再保 0828 删除固定手续费
      // 翟总:删除固定手续费20250903再次修改，算亏损的获取费用没有了,0
      cfBasicData.setIacfActualRein(BigDecimal.ZERO);
      Optional.ofNullable(clmSettledMap.get(cfBasicData.getUnitId())).ifPresent(
          tPpJlClmSettled -> {
            cfBasicData.setLossActual(tPpJlClmSettled.getSettledLossPastCny().add(tPpJlClmSettled.getSettledLossCurrCny()));
          }
      );
      cfBasicData.setIacfFolCnyRein(getIacfFolCnyWithActuarialAssumption(cfBasicData,measureActuarialAssumptionMap,ConfMeasureActuarialAssumption::getFirstDayAcquisitionExpenseRatio));
      Optional.ofNullable(ulaeSettledMap.get(cfBasicData.getUnitId())).ifPresent(
          tPpJlUlaeSettled -> {
            cfBasicData.setIndirectClaimsExpenseActual(tPpJlUlaeSettled.getUlaeSettledPastCny().add(tPpJlUlaeSettled.getUlaeSettledCurrCny()));
          }
      );
      BigDecimal sumMaintenanceRealCny = (BigDecimal) tPpJlIacfUnfolMap2.getOrDefault(
          StrUtil.toUnderlineCase(ReflectUtils.getFieldName(TPpJlIacfUnfol::getMaintenanceRealCny)),BigDecimal.ZERO);
      cfBasicData.setMaintenanceExpenseActual(sumMaintenanceRealCny);
      return cfBasicData;
    }).collect(Collectors.toList());
    batchesSaveCommit(basicDataList);
  }

  /**
   * 计算保险保障期限
   * @param cfBasicData 基本数据
   * @return 保险保障期限
   */
  private Long computeTerm(MeasureCfBasicData cfBasicData) {
    Date startDate = DateUtil.parse(cfBasicData.getStartDate());
    Date endDate = DateUtil.parse(cfBasicData.getEndDate());
    long days = DateUtil.betweenDay(endDate, startDate, true) + 1;
    return days;
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
