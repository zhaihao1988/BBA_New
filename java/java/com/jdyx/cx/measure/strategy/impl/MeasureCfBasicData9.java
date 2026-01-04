package com.jdyx.cx.measure.strategy.impl;

import cn.hutool.core.date.DateUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.google.common.collect.Lists;
import com.jdyx.common.dataplatform.service.CxPublicDbService;
import com.jdyx.common.enums.EvaluateMethodTypeEnum;
import com.jdyx.common.measure.constant.NumberConstant;
import com.jdyx.common.measure.constant.StringConstant;
import com.jdyx.common.measure.service.SuperBaseService;
import com.jdyx.cx.measure.strategy.MeasureCfBasicStrategy;
import com.jdyx.measure.api.measure.domain.ConfSlidingScaleCommission;
import com.jdyx.measure.api.measure.domain.MeasureCfBasicData;
import com.jdyx.measureprepare.api.domain.TPpReMonArr;
import com.jdyx.measureprepare.api.mapper.TPpReMonArrMapper;
import com.kevin.common.utils.DateUtils;
import com.kevin.common.utils.StringUtils;
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
 * 产险-再保分出-BBA-9
 * 产险-再保分出-PAA-10
 *
 * @author 刘瑞奎.
 * @date 2024/10/21.
 */
@SuppressWarnings("DuplicatedCode")
@Slf4j
@RequiredArgsConstructor
@Service
public class MeasureCfBasicData9 extends SuperBaseService implements MeasureCfBasicStrategy {

  /** 7.public库取数服务 */
  private final CxPublicDbService publicDbService;
  private final TPpReMonArrMapper tppReMonArrMapper;
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
    Map<String, ConfSlidingScaleCommission> confSlidingScaleCommissionMap = getConfSlidingScaleCommissionMap();
//一.获取 计量源数据(从计量数据准备输出数据中获取)
    //构建参数
    LambdaQueryWrapper<TPpReMonArr> lambdaQueryWrapper = Wrappers.lambdaQuery();
    //1.评估时点
    lambdaQueryWrapper.eq(TPpReMonArr::getValMonth, valMonth);
    //2.评估方法
    lambdaQueryWrapper.eq(TPpReMonArr::getValMethod, evaluateMethod.getCode());
    //如果(6.签单日期,25.批单生效日)>2.当期评估日期，则该条数据有错，不应放在当前评估
    lambdaQueryWrapper.apply("COALESCE(to_char(certi_write_date,'YYYYMM'),case when certi_no is not null then to_char(modify_date,'YYYYMM') else to_char(pi_start_date,'YYYYMM') end)<={0}",valMonth);
    long selectCount = tppReMonArrMapper.selectCount(lambdaQueryWrapper);
    log.info("selectCount={}",selectCount);
    tppReMonArrMapper.selectList(lambdaQueryWrapper, new ResultHandler<TPpReMonArr>() {
      final List<TPpReMonArr> tPpReMonArrList = Lists.newLinkedList();
      @Override
      public void handleResult(ResultContext<? extends TPpReMonArr> resultContext) {
        tPpReMonArrList.add(resultContext.getResultObject());
        if(tPpReMonArrList.size()==10000){
          generateMeasureCfBasic(tPpReMonArrList,evaluateMethod,valMonth,confSlidingScaleCommissionMap);
          tPpReMonArrList.clear();
          log.info("当前已处理={}",resultContext.getResultCount());
        }
        if(selectCount== resultContext.getResultCount()&& StringUtils.isNotEmpty(tPpReMonArrList)){
          generateMeasureCfBasic(tPpReMonArrList,evaluateMethod,valMonth,confSlidingScaleCommissionMap);
          tPpReMonArrList.clear();
          log.info("当前已处理={}",resultContext.getResultCount());
        }
      }
    });
  }

  private void generateMeasureCfBasic(List<TPpReMonArr> tPpReMonArrList, EvaluateMethodTypeEnum evaluateMethod, String valMonth, Map<String, ConfSlidingScaleCommission> confSlidingScaleCommissionMap) {
    List<MeasureCfBasicData> measureCfBasicDataList = tPpReMonArrList.stream().map(e->{
      MeasureCfBasicData cfBasicData = new MeasureCfBasicData();
      //当期评估月(YYYYmm) = 当前评估日期
      cfBasicData.setValMonth(valMonth);
      //上期评估时点（YYYYmm)=上年末月
      cfBasicData.setLastValMonth(DateUtils.lastEndYear(valMonth, DateUtils.YYYYMM));
      //计量层级编号 = 再保险合同计算单元编号
      cfBasicData.setUnitId(Optional.ofNullable(e.getUnitId()).orElse(StringConstant.STRING_NA));
      //合约临分标识
      cfBasicData.setContractFlag(Optional.ofNullable(e.getContractFlag()).orElse(StringConstant.STRING_NA));
      //分出类型
      cfBasicData.setReinType(Optional.ofNullable(e.getReinType()).orElse(StringConstant.STRING_NA));
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
      //分出比例
      cfBasicData.setShareRate(Optional.ofNullable(e.getShareRate()).orElse(BigDecimal.ZERO));
      //临分保单号
      cfBasicData.setPolicyNo(e.getPolicyNo());
      //批单号
      cfBasicData.setCertiNo(e.getCertiNo());
      cfBasicData.setClassCode(e.getClassCode());
      cfBasicData.setRiskCode(Optional.ofNullable(e.getRiskCode()).orElse(StringConstant.STRING_NA));
      Optional.ofNullable(e.getCertiWriteDate()).ifPresent(d-> cfBasicData.setCertiWriteDate(DateUtils.parseDateToStr(DateUtils.YYYYMMDD,d)));
      //批单生效日
      Optional.ofNullable(e.getModifyDate()).ifPresent(d-> cfBasicData.setModifyDate(DateUtils.parseDateToStr(DateUtils.YYYYMMDD,d)));
      //保险责任止期
      cfBasicData.setEndDate(DateUtils.parseDateToStr(DateUtils.YYYYMMDD, e.getPiEndDate()));
      //再保险合同责任起期
      if(!StringUtils.isBlank(cfBasicData.getCertiNo())){
        if(DateUtils.getDateDiff(cfBasicData.getModifyDate(),cfBasicData.getEndDate())>=NumberConstant.LONG_ZERO){
          cfBasicData.setStartDate(cfBasicData.getEndDate());
        }else {
          cfBasicData.setStartDate(cfBasicData.getModifyDate());
        }
      }else{
        cfBasicData.setStartDate(DateUtils.parseDateToStr(DateUtils.YYYYMMDD, e.getPiStartDate()));
      }
      //签单日期
      Optional.ofNullable(e.getUnderWriteDate()).ifPresent(d-> cfBasicData.setUnderWriteDate(DateUtils.parseDateToStr(DateUtils.YYYYMMDD,d)));

      //保费-本币 = premium - 减值数据（暂未提供）
      cfBasicData.setPremiumCny(Optional.ofNullable(e.getPremium()).orElse(BigDecimal.ZERO));
      //合同组合编码
      cfBasicData.setPortfolioId(Optional.ofNullable(e.getPortfolioId()).orElse(StringConstant.STRING_NA));
      //合同分组编码
      cfBasicData.setGroupId(Optional.ofNullable(e.getGroupId()).orElse(StringConstant.STRING_NA));
      //不含税净分出保费
      BigDecimal commission = Optional.ofNullable(e.getCommission()).orElse(BigDecimal.ZERO);
      cfBasicData.setCommission(commission);
      cfBasicData.setNetPremiumCny(cfBasicData.getPremiumCny().subtract(commission));
      //避免计量明细报错
      cfBasicData.setCoverageSegment(StringConstant.STRING_NA);
      cfBasicData.setBusinessNature(StringConstant.STRING_NA);
      //币种
      cfBasicData.setCurrency(e.getCurrencyEpi());
      //设置是否当期新单（按“签单日期/批单签单日期 与 保险责任起期、上期评估日期”的规则判定）

      //获取上期评估日期
      String lastMonthEndDate = DateUtils.endMonth(cfBasicData.getLastValMonth(), DateUtils.YYYYMMDD);
      String signDate = (StringUtils.isNotBlank(cfBasicData.getCertiNo()) && StringUtils.isNotBlank(cfBasicData.getCertiWriteDate()))
        ? cfBasicData.getCertiWriteDate()
        : cfBasicData.getUnderWriteDate();
      // (14.签单日期,32批单签单日期)<=保险责任起期
      if (DateUtils.getDateDiff(signDate, cfBasicData.getStartDate()) <= NumberConstant.LONG_ZERO) {
        if (DateUtils.getDateDiff(cfBasicData.getStartDate(), lastMonthEndDate) <= NumberConstant.LONG_ZERO) {
//        (16.保险责任起期)<=2.上期评估日期，则=0
          cfBasicData.setWhetherCurPolicy(StringConstant.STRING_ZERO);
        } else {
//        ----如果(16.保险责任起期)>2.上期评估日期,则=1
          cfBasicData.setWhetherCurPolicy(StringConstant.STRING_ONE);
        }
      } else {
//        (14.签单日期,32批单签单日期)>保险责任起期
        if (DateUtils.getDateDiff(signDate, lastMonthEndDate) <= NumberConstant.LONG_ZERO) {
//          1.如果(14.签单日期,32批单签单日期)<=2.上期评估日期，则=0
          cfBasicData.setWhetherCurPolicy(StringConstant.STRING_ZERO);
        } else {
//          如果(14.签单日期,32批单签单日期)>2.上期评估日期,则=1
          cfBasicData.setWhetherCurPolicy(StringConstant.STRING_ONE);
        }
      }


      //保障期限
      cfBasicData.setTerm(computeTerm(cfBasicData));
      //归属机构
      cfBasicData.setComCode(Optional.ofNullable(e.getComCode()).orElse(StringConstant.STRING_NA));
      //车辆种类
      cfBasicData.setCarKindCode(Optional.ofNullable(e.getCarKindCode()).orElse(StringConstant.STRING_NA));
      //使用性质代码
      cfBasicData.setUseNatureCode(Optional.ofNullable(e.getUseNatureCode()).orElse(StringConstant.STRING_NA));
      //评估方法
      cfBasicData.setValMethod(evaluateMethod.getCode());
      //浮动手续费率 取浮动手续费率配置表 暂未提供
      cfBasicData.setFloatingHandlingFeeRate(getFloatingHandlingFeeRate(confSlidingScaleCommissionMap, cfBasicData.getContractId()));
      return cfBasicData;
    }).collect(Collectors.toList());
    batchesSaveCommit(measureCfBasicDataList);
  }

  /**
   * 计算保障期限
   *
   * @param cfBasicData 计量源数据
   * @return java.lang.Long 保障期限
   * @author 郭文斌.
   * @date 2024/11/19.
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
