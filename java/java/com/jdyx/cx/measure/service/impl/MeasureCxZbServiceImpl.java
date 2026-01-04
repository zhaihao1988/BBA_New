package com.jdyx.cx.measure.service.impl;

import cn.hutool.core.bean.BeanUtil;
import cn.hutool.core.util.StrUtil;
import com.baomidou.dynamic.datasource.annotation.DSTransactional;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.baomidou.mybatisplus.core.toolkit.support.SFunction;
import com.google.common.collect.ImmutableMap;
import com.google.common.collect.Lists;
import com.jdyx.common.cache.measure.ConfMeasureActuarialAssumptionCacheService;
import com.jdyx.common.enums.CurrencyTypeEnum;
import com.jdyx.common.enums.DataStateTypeEnum;
import com.jdyx.common.enums.EvaluateMethodTypeEnum;
import com.jdyx.common.measure.constant.StringConstant;
import com.jdyx.common.measure.service.MeasureCommonCacheService;
import com.jdyx.measure.api.measure.domain.MeasureResultCheckLic;
import com.jdyx.measure.api.measure.mapper.MeasureResultCheckLicMapper;
import com.jdyx.cx.measure.service.*;
import com.jdyx.cx.measure.strategy.ContextUtils;
import com.jdyx.measure.api.measure.domain.*;
import com.jdyx.measure.api.measure.mapper.*;
import com.jdyx.measureprepare.api.domain.*;
import com.jdyx.measureprepare.api.mapper.*;
import com.kevin.common.core.domain.R;
import com.kevin.common.utils.DateUtils;
import com.kevin.common.utils.StringUtils;
import com.kevin.common.utils.reflect.ReflectUtils;
import com.kevin.common.utils.spring.SpringUtils;
import com.kevin.common.utils.sql.SqlFunctionUtil;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.ObjectUtils;
import org.apache.ibatis.session.ResultContext;
import org.apache.ibatis.session.ResultHandler;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.DefaultTransactionDefinition;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.text.ParseException;
import java.util.*;
import java.util.concurrent.CountDownLatch;
import java.util.stream.Collectors;


/**
 * PAA模型 当期计量明细
 *
 * @author kevin.
 * @date 2024/2/6.
 */
@SuppressWarnings("DuplicatedCode")
@Slf4j
@RequiredArgsConstructor
@Service
public class MeasureCxZbServiceImpl extends BaseMeasureCxService implements MeasureCxZbService {
  /**
   * 11.计量明细统一接口
   */
  private final MeasureCfBbaExpRstMapper measureCfBbaExpRstMapper;
  private final MeasureConfCommonClaimMapper measureConfCommonClaimMapper;
  private final MeasureCfBasicCalcRstMapper measureCfBasicCalcRstMapper;
  private final MeasureCfBbaBasicCalcRstMapper measureCfBbaBasicCalcRstMapper;
  private final MeasureCommonCacheService measureCommonCacheService;
  private final ConfMeasureActuarialAssumptionCacheService confMeasureActuarialAssumptionCacheService;
  private final PlatformTransactionManager transactionManager;
  private final MeasureCfBasicDataMapper measureCfBasicDataMapper;
  private final MeasureResultCheckMapper measureResultCheckMapper;
  private final MeasureResultAllocationMapper measureResultAllocationMapper;
  private final MeasureActualExpenseMapper measureActualExpenseMapper;
  private final TPpJlCaseMapper tPpJlCaseMapper;
  private final TPpIbnrDirectInMapper tPpIbnrDirectInMapper;
  private final TPpIbnrReinOutMapper tPpIbnrReinOutMapper;
  private final TPpRiReCaseMonMapper tPpRiReCaseMonMapper;
  private final TPpIbnrReinInMapper tPpIbnrReinInMapper;
  private final TPpRiReCaseMonInMapper tPpRiReCaseMonInMapper;
  private final ConfMeasureActuarialAssumptionMapper confMeasureActuarialAssumptionMapper;
  private final MeasureResultCheckLicMapper measureResultCheckLicMapper;
  private static final int BATCH_SIZE = 1000;

    /**
     * 理赔配置表
     *
     * @param valMethod 评估方法
     * @param valMonth  评估月
     * @return {@link R }<{@link ? }>
     */
    @DSTransactional
    @Override
    public R<?> setCxZbMeasureConfCommonClaim(String valMethod, String valMonth) {
        // 一.获取 计量源数据(从计量数据准备输出数据中获取)
        // 构建参数
        LambdaQueryWrapper<MeasureCfBasicData> lambdaQueryWrapper = Wrappers.lambdaQuery();
        // 1.评估时点
        lambdaQueryWrapper.eq(MeasureCfBasicData::getValMonth, valMonth);
        // 2.评估方法
        lambdaQueryWrapper.eq(MeasureCfBasicData::getValMethod, valMethod);

        // 清理理赔配置表数据
        int numberOfBatch = measureConfCommonClaimMapper.delete(new LambdaQueryWrapper<MeasureConfCommonClaim>().eq(MeasureConfCommonClaim::getValMonth,
                valMonth).eq(MeasureConfCommonClaim::getValMethod, valMethod));
        log.info("清理理赔配置表数据 当期{} 评估方法{} 时点数据{}条", valMonth, valMethod, numberOfBatch);
        // 总数据
        long selectCount = measureCfBasicDataMapper.selectCount(lambdaQueryWrapper);
        log.info("selectCount={}", selectCount);
        measureCfBasicDataMapper.selectList(lambdaQueryWrapper, new ResultHandler<MeasureCfBasicData>() {
            final List<MeasureCfBasicData> measureCfBasicDataList = Lists.newArrayList();

            /**
             * @param resultContext resultContext
             */
            @Override
            public void handleResult(ResultContext<? extends MeasureCfBasicData> resultContext) {
                measureCfBasicDataList.add(resultContext.getResultObject());
                if (measureCfBasicDataList.size() == 10000) {
                    ContextUtils.executeStrategyCommonClaim(measureCfBasicDataList, EvaluateMethodTypeEnum.getEnumType(valMethod), valMonth);
                    measureCfBasicDataList.clear();
                    log.info("当前已处理={}", resultContext.getResultCount());
                }
                if (selectCount == resultContext.getResultCount() && StringUtils.isNotEmpty(measureCfBasicDataList)) {
                    ContextUtils.executeStrategyCommonClaim(measureCfBasicDataList, EvaluateMethodTypeEnum.getEnumType(valMethod), valMonth);
                    measureCfBasicDataList.clear();
                    log.info("当前已处理={}", resultContext.getResultCount());
                }
            }
        });
        // 更新计量源数据的预期赔付金额
        measureCfBasicDataMapper.updateDataByUnitId(valMonth, valMethod);
        return R.ok(selectCount);
    }

    @Override
    public R<?> setCxMeasureActualExpense(String valMethod, String valMonth) {
        // 清空当期历史数据
        int delete = measureActualExpenseMapper.delete(new LambdaQueryWrapper<MeasureActualExpense>().eq(MeasureActualExpense::getValMonth,
                valMonth).eq(MeasureActualExpense::getValMethod, valMethod));
        measureActualExpenseMapper.insertActualExpense(valMonth, valMethod);
        return R.ok();
    }

    /**
     * 计算(产险直保BBA)  经过天数配置_期初
     *
     * @param valMethod 评估方法
     * @param valMonth  评估时点
     * @return r
     */
    @Override
    @DSTransactional
    public R<?> setCxZbMeasureBbaBeginPeriod(String valMethod, String valMonth) {
        // 获取 计量源数据
        List<MeasureCfBasicData> measureCfBasicDataList = getMeasureCfBasicDataList(valMonth, valMethod, MeasureCfBasicData::getValMonth, MeasureCfBasicData::getUnitId, MeasureCfBasicData::getClassCode, MeasureCfBasicData::getRiskCode,
                MeasureCfBasicData::getStartDate, MeasureCfBasicData::getEvaluateDate, MeasureCfBasicData::getEndDate, MeasureCfBasicData::getTerm, MeasureCfBasicData::getWhetherCurPolicy, MeasureCfBasicData::getIniConfirm);

        // 生成 经过天数配置_期初
        List<MeasureConfBbaBeginPeriod> measureConfBbaBeginPeriods = SpringUtils.getBean(MeasureBbaPeriodService.class).setCxZbMeasureBbaBeginPeriod(measureCfBasicDataList);

        // 删除旧数据
        MeasureConfBbaBeginPeriodMapper measureConfBbaBeginPeriodMapper = SpringUtils.getBean(MeasureConfBbaBeginPeriodMapper.class);
        int numberOfBatch = measureConfBbaBeginPeriodMapper.delete(new LambdaQueryWrapper<MeasureConfBbaBeginPeriod>().eq(MeasureConfBbaBeginPeriod::getValMonth, valMonth));
        log.info("MeasureConfBbaBeginPeriod delete old Data {}-{}={}", valMonth, valMethod, numberOfBatch);

        measureConfBbaBeginPeriodMapper.insertBatch(measureConfBbaBeginPeriods);
        return R.ok();
    }

    /**
     * 计算(产险直保BBA)  经过天数配置_当期
     *
     * @param valMethod 评估方法
     * @param valMonth  评估时点
     * @return r
     */
    @Override
    @DSTransactional
    public R<?> setCxZbMeasureBbaCurrentPeriod(String valMethod, String valMonth) {
        // 获取 计量源数据
        List<MeasureCfBasicData> measureCfBasicDataList = getMeasureCfBasicDataList(valMonth, valMethod, MeasureCfBasicData::getValMonth, MeasureCfBasicData::getUnitId, MeasureCfBasicData::getClassCode, MeasureCfBasicData::getRiskCode,
                MeasureCfBasicData::getEvaluateDate, MeasureCfBasicData::getEndDate, MeasureCfBasicData::getTerm);

        // 生成 经过天数配置_当期
        List<MeasureConfBbaCurrentPeriod> measureConfBbaCurrentPeriods = SpringUtils.getBean(MeasureBbaPeriodService.class)
                .setCxZbMeasureBbaCurrentPeriod(measureCfBasicDataList);

        // 删除旧数据
        MeasureConfBbaCurrentPeriodMapper measureConfBbaCurrentPeriodMapper = SpringUtils.getBean(MeasureConfBbaCurrentPeriodMapper.class);
        int numberOfBatch = measureConfBbaCurrentPeriodMapper.delete(new LambdaQueryWrapper<MeasureConfBbaCurrentPeriod>().eq(MeasureConfBbaCurrentPeriod::getValMonth, valMonth));
        log.info("MeasureConfBbaCurrentPeriod delete old Data {}-{}={}", valMonth, valMethod, numberOfBatch);

        measureConfBbaCurrentPeriodMapper.insertBatch(measureConfBbaCurrentPeriods);
        return R.ok();

    }

    /**
     * 计算(产险直保BBA)  计息日期配置_期初
     *
     * @param valMethod 评估方法
     * @param valMonth  评估时点
     * @return r
     */
    @Override
    @DSTransactional
    public R<?> setCxZbMeasureBbaBeginInterestCalculation(String valMethod, String valMonth) {
        // 获取 计量源数据
        List<MeasureCfBasicData> measureCfBasicDataList = getMeasureCfBasicDataList(valMonth, valMethod, MeasureCfBasicData::getValMonth, MeasureCfBasicData::getUnitId, MeasureCfBasicData::getClassCode, MeasureCfBasicData::getRiskCode,
                MeasureCfBasicData::getStartDate, MeasureCfBasicData::getEvaluateDate, MeasureCfBasicData::getEndDate, MeasureCfBasicData::getWhetherCurPolicy, MeasureCfBasicData::getIniConfirm);

        // 生成 计息日期配置_期初
        List<MeasureConfBbaBeginInterestCalculation> measureConfBbaBeginInterestCalculations = SpringUtils.getBean(MeasureBbaInterestCalculationService.class)
                .setCxZbMeasureBbaBeginInterestCalculation(measureCfBasicDataList);

        // 删除旧数据
        MeasureConfBbaBeginInterestCalculationMapper mapper = SpringUtils.getBean(MeasureConfBbaBeginInterestCalculationMapper.class);
        int numberOfBatch = mapper.delete(new LambdaQueryWrapper<MeasureConfBbaBeginInterestCalculation>().eq(MeasureConfBbaBeginInterestCalculation::getValMonth, valMonth));
        log.info("MeasureConfBbaBeginInterestCalculation delete old Data {}-{}={}", valMonth, valMethod, numberOfBatch);

        mapper.insertBatch(measureConfBbaBeginInterestCalculations);
        return R.ok();
    }

    /**
     * 计算(产险直保BBA)  计息日期配置_当期
     *
     * @param valMethod 评估方法
     * @param valMonth  评估时点
     * @return r
     */
    @Override
    @DSTransactional
    public R<?> setCxZbMeasureBbaCurrentInterestCalculation(String valMethod, String valMonth) {
        // 获取 计量源数据
        List<MeasureCfBasicData> measureCfBasicDataList = getMeasureCfBasicDataList(valMonth, valMethod, MeasureCfBasicData::getValMonth, MeasureCfBasicData::getUnitId, MeasureCfBasicData::getClassCode, MeasureCfBasicData::getRiskCode,
                MeasureCfBasicData::getEvaluateDate, MeasureCfBasicData::getEndDate);

        // 生成 计息日期配置_当期
        List<MeasureConfBbaCurrentInterestCalculation> measureConfBbaCurrentInterestCalculations = SpringUtils.getBean(MeasureBbaInterestCalculationService.class)
                .setCxZbMeasureBbaCurrentInterestCalculation(measureCfBasicDataList);

        // 删除旧数据
        MeasureConfBbaCurrentInterestCalculationMapper mapper = SpringUtils.getBean(MeasureConfBbaCurrentInterestCalculationMapper.class);
        int numberOfBatch = mapper.delete(new LambdaQueryWrapper<MeasureConfBbaCurrentInterestCalculation>().eq(MeasureConfBbaCurrentInterestCalculation::getValMonth, valMonth));
        log.info("MeasureConfBbaCurrentInterestCalculation delete old Data {}-{}={}", valMonth, valMethod, numberOfBatch);

        mapper.insertBatch(measureConfBbaCurrentInterestCalculations);
        return R.ok();
    }

    /**
     * 计算(产险直保BBA)  维持费用相关_期初
     *
     * @param valMethod 评估方法
     * @param valMonth  评估时点
     * @return r
     */
    @Override
    @DSTransactional
    public R<?> setCxZbMeasureBbaBeginMaintenanceCost(String valMethod, String valMonth) {
        // 获取计量源数据
        List<MeasureCfBasicData> measureCfBasicDataList = getMeasureCfBasicDataList(valMonth, valMethod, MeasureCfBasicData::getValMonth, MeasureCfBasicData::getValMethod, MeasureCfBasicData::getUnitId, MeasureCfBasicData::getClassCode, MeasureCfBasicData::getRiskCode, MeasureCfBasicData::getLastValMonth,
                MeasureCfBasicData::getPremiumCny, MeasureCfBasicData::getWhetherCurPolicy, MeasureCfBasicData::getStartDate, MeasureCfBasicData::getEvaluateDate, MeasureCfBasicData::getEndDate, MeasureCfBasicData::getTerm, MeasureCfBasicData::getIniConfirm);

        // 获取经过天数配置表期初数据
        Map<String, List<MeasureConfBbaBeginPeriod>> measureConfBbaBeginPeriodMap = getMeasureConfBbaBeginPeriodMap(valMonth);

        // 生成维持费用相关_期初
        List<MeasureConfBbaBeginMaintenanceCost> measureConfBbaBeginMaintenanceCosts = SpringUtils.getBean(MeasureBbaMaintenanceCostService.class)
                .setCxZbMeasureBbaBeginMaintenanceCost(measureCfBasicDataList, measureConfBbaBeginPeriodMap);

        // 删除旧数据
        MeasureConfBbaBeginMaintenanceCostMapper mapper = SpringUtils.getBean(MeasureConfBbaBeginMaintenanceCostMapper.class);
        int numberOfBatch = mapper.delete(new LambdaQueryWrapper<MeasureConfBbaBeginMaintenanceCost>().eq(MeasureConfBbaBeginMaintenanceCost::getValMonth, valMonth));
        log.info("MeasureConfBbaBeginMaintenanceCost delete old Data {}-{}={}", valMonth, valMethod, numberOfBatch);

        mapper.insertBatch(measureConfBbaBeginMaintenanceCosts);
        return R.ok();
    }

    /**
     * 计算(产险直保BBA)  维持费用相关_当期
     *
     * @param valMethod 评估方法
     * @param valMonth  评估时点
     * @return r
     */
    @Override
    @DSTransactional
    public R<?> setCxZbMeasureBbaCurrentMaintenanceCost(String valMethod, String valMonth) {
        // 获取计量源数据
        List<MeasureCfBasicData> measureCfBasicDataList = getMeasureCfBasicDataList(valMonth, valMethod, MeasureCfBasicData::getValMonth, MeasureCfBasicData::getValMethod, MeasureCfBasicData::getUnitId, MeasureCfBasicData::getClassCode, MeasureCfBasicData::getRiskCode, MeasureCfBasicData::getLastValMonth,
                MeasureCfBasicData::getPremiumCny, MeasureCfBasicData::getWhetherCurPolicy, MeasureCfBasicData::getStartDate, MeasureCfBasicData::getEvaluateDate, MeasureCfBasicData::getEndDate, MeasureCfBasicData::getTerm);

        // 获取经过天数配置表当期数据
        Map<String, List<MeasureConfBbaCurrentPeriod>> measureConfBbaCurrentPeriodMap = getMeasureConfBbaCurrentPeriodMap(valMonth);

        // 生成维持费用相关_当期
        List<MeasureConfBbaCurrentMaintenanceCost> measureConfBbaCurrentMaintenanceCosts = SpringUtils.getBean(MeasureBbaMaintenanceCostService.class)
                .setCxZbMeasureBbaCurrentMaintenanceCost(measureCfBasicDataList, measureConfBbaCurrentPeriodMap);

        // 删除旧数据
        MeasureConfBbaCurrentMaintenanceCostMapper mapper = SpringUtils.getBean(MeasureConfBbaCurrentMaintenanceCostMapper.class);
        int numberOfBatch = mapper.delete(new LambdaQueryWrapper<MeasureConfBbaCurrentMaintenanceCost>().eq(MeasureConfBbaCurrentMaintenanceCost::getValMonth, valMonth));
        log.info("MeasureConfBbaCurrentMaintenanceCost delete old Data {}-{}={}", valMonth, valMethod, numberOfBatch);

        mapper.insertBatch(measureConfBbaCurrentMaintenanceCosts);
        return R.ok();
    }

    /**
     * 计算(产险直保BBA)  维持费用相关_当期计算假设变动数据
     *
     * @param valMethod 评估方法
     * @param valMonth  评估时点
     * @return r
     */
    @Override
    @DSTransactional
    public R<?> setCxZbMeasureBbaChangeCurrentMaintenanceCost(String valMethod, String valMonth) {
        // 获取计量源数据
        List<MeasureCfBasicData> measureCfBasicDataList = getMeasureCfBasicDataList(valMonth, valMethod, MeasureCfBasicData::getValMonth, MeasureCfBasicData::getValMethod, MeasureCfBasicData::getUnitId, MeasureCfBasicData::getClassCode, MeasureCfBasicData::getRiskCode, MeasureCfBasicData::getLastValMonth,
                MeasureCfBasicData::getPremiumCny, MeasureCfBasicData::getWhetherCurPolicy, MeasureCfBasicData::getStartDate, MeasureCfBasicData::getEvaluateDate, MeasureCfBasicData::getEndDate, MeasureCfBasicData::getTerm);

        // 获取经过天数配置表当期数据
        Map<String, List<MeasureConfBbaCurrentPeriod>> measureConfBbaCurrentPeriodMap = getMeasureConfBbaCurrentPeriodMap(valMonth);

        // 生成维持费用相关_当期计算假设变动
        List<MeasureConfBbaChangeCurrentMaintenanceCost> measureConfBbaChangeCurrentMaintenanceCosts = SpringUtils.getBean(MeasureBbaMaintenanceCostService.class)
                .setCxZbMeasureBbaChangeCurrentMaintenanceCost(measureCfBasicDataList, measureConfBbaCurrentPeriodMap);

        // 删除旧数据
        MeasureConfBbaChangeCurrentMaintenanceCostMapper mapper = SpringUtils.getBean(MeasureConfBbaChangeCurrentMaintenanceCostMapper.class);
        int numberOfBatch = mapper.delete(new LambdaQueryWrapper<MeasureConfBbaChangeCurrentMaintenanceCost>().eq(MeasureConfBbaChangeCurrentMaintenanceCost::getValMonth, valMonth));
        log.info("MeasureConfBbaChangeCurrentMaintenanceCost delete old Data {}-{}={}", valMonth, valMethod, numberOfBatch);

        mapper.insertBatch(measureConfBbaChangeCurrentMaintenanceCosts);
        return R.ok();
    }

    /**
     * 计算(产险直保BBA)  赔款相关_期初
     *
     * @param valMethod 评估方法
     * @param valMonth  评估月
     * @return r
     */
    @Override
    @DSTransactional
    public R<?> setCxZbMeasureBbaBeginCompensation(String valMethod, String valMonth) {
        // 获取计量源数据
        List<MeasureCfBasicData> measureCfBasicDataList = getMeasureCfBasicDataList(valMonth, valMethod, MeasureCfBasicData::getValMonth, MeasureCfBasicData::getValMethod, MeasureCfBasicData::getUnitId, MeasureCfBasicData::getClassCode, MeasureCfBasicData::getRiskCode, MeasureCfBasicData::getLastValMonth,
                MeasureCfBasicData::getPremiumCny, MeasureCfBasicData::getWhetherCurPolicy, MeasureCfBasicData::getStartDate, MeasureCfBasicData::getEvaluateDate, MeasureCfBasicData::getEndDate, MeasureCfBasicData::getTerm, MeasureCfBasicData::getIniConfirm);

        // 获取经过天数配置表期初数据
        Map<String, List<MeasureConfBbaBeginPeriod>> measureConfBbaBeginPeriodMap = getMeasureConfBbaBeginPeriodMap(valMonth);

        // 生成赔款相关_期初
        List<MeasureConfBbaBeginCompensation> measureConfBbaBeginCompensations = SpringUtils.getBean(MeasureBbaCompensationService.class)
                .setCxZbMeasureBbaBeginCompensation(measureCfBasicDataList, measureConfBbaBeginPeriodMap);

        // 删除旧数据
        MeasureConfBbaBeginCompensationMapper mapper = SpringUtils.getBean(MeasureConfBbaBeginCompensationMapper.class);
        int numberOfBatch = mapper.delete(new LambdaQueryWrapper<MeasureConfBbaBeginCompensation>()
                .eq(MeasureConfBbaBeginCompensation::getValMonth, valMonth));
        log.info("MeasureConfBbaBeginCompensation delete old Data {}-{}={}", valMonth, valMethod, numberOfBatch);

        mapper.insertBatch(measureConfBbaBeginCompensations);
        return R.ok();
    }

    /**
     * 计算(产险直保BBA)  赔款相关_当期
     *
     * @param valMethod 评估方法
     * @param valMonth  评估月
     * @return r
     */
    @Override
    @DSTransactional
    public R<?> setCxZbMeasureBbaCurrentCompensation(String valMethod, String valMonth) {
        // 获取计量源数据
        List<MeasureCfBasicData> measureCfBasicDataList = getMeasureCfBasicDataList(valMonth, valMethod, MeasureCfBasicData::getValMonth, MeasureCfBasicData::getValMethod, MeasureCfBasicData::getUnitId, MeasureCfBasicData::getClassCode, MeasureCfBasicData::getRiskCode, MeasureCfBasicData::getLastValMonth,
                MeasureCfBasicData::getPremiumCny, MeasureCfBasicData::getWhetherCurPolicy, MeasureCfBasicData::getStartDate, MeasureCfBasicData::getEvaluateDate, MeasureCfBasicData::getEndDate, MeasureCfBasicData::getTerm);

        // 获取经过天数配置表当期数据
        Map<String, List<MeasureConfBbaCurrentPeriod>> measureConfBbaCurrentPeriodMap = getMeasureConfBbaCurrentPeriodMap(valMonth);

        // 生成赔款相关_当期
        List<MeasureConfBbaCurrentCompensation> measureConfBbaCurrentCompensations = SpringUtils.getBean(MeasureBbaCompensationService.class)
                .setCxZbMeasureBbaCurrentCompensation(measureCfBasicDataList, measureConfBbaCurrentPeriodMap);

        // 删除旧数据
        MeasureConfBbaCurrentCompensationMapper mapper = SpringUtils.getBean(MeasureConfBbaCurrentCompensationMapper.class);
        int numberOfBatch = mapper.delete(new LambdaQueryWrapper<MeasureConfBbaCurrentCompensation>().eq(MeasureConfBbaCurrentCompensation::getValMonth, valMonth));
        log.info("MeasureConfBbaCurrentCompensation delete old Data {}-{}={}", valMonth, valMethod, numberOfBatch);

        mapper.insertBatch(measureConfBbaCurrentCompensations);
        return R.ok();
    }

    /**
     * 计算(产险直保BBA)  赔款相关_当期计算假设变动数据
     *
     * @param valMethod 评估方法
     * @param valMonth  评估月
     * @return r
     */
    @Override
    @DSTransactional
    public R<?> setCxZbMeasureBbaChangeCurrentCompensation(String valMethod, String valMonth) {
        // 获取计量源数据
        List<MeasureCfBasicData> measureCfBasicDataList = getMeasureCfBasicDataList(valMonth, valMethod, MeasureCfBasicData::getValMonth, MeasureCfBasicData::getValMethod, MeasureCfBasicData::getUnitId, MeasureCfBasicData::getClassCode, MeasureCfBasicData::getRiskCode, MeasureCfBasicData::getLastValMonth,
                MeasureCfBasicData::getPremiumCny, MeasureCfBasicData::getWhetherCurPolicy, MeasureCfBasicData::getStartDate, MeasureCfBasicData::getEvaluateDate, MeasureCfBasicData::getEndDate, MeasureCfBasicData::getTerm);

        // 获取经过天数配置表当期数据
        Map<String, List<MeasureConfBbaCurrentPeriod>> measureConfBbaCurrentPeriodMap = getMeasureConfBbaCurrentPeriodMap(valMonth);

        // 生成赔款相关_当期计算假设变动
        List<MeasureConfBbaChangeCurrentCompensation> measureConfBbaChangeCurrentCompensations = SpringUtils.getBean(MeasureBbaCompensationService.class)
                .setCxZbMeasureBbaChangeCurrentCompensation(measureCfBasicDataList, measureConfBbaCurrentPeriodMap);

        // 删除旧数据
        MeasureConfBbaChangeCurrentCompensationMapper mapper = SpringUtils.getBean(MeasureConfBbaChangeCurrentCompensationMapper.class);
        int numberOfBatch = mapper.delete(new LambdaQueryWrapper<MeasureConfBbaChangeCurrentCompensation>().eq(MeasureConfBbaChangeCurrentCompensation::getValMonth, valMonth));
        log.info("MeasureConfBbaChangeCurrentCompensation delete old Data {}-{}={}", valMonth, valMethod, numberOfBatch);

        mapper.insertBatch(measureConfBbaChangeCurrentCompensations);
        return R.ok();
    }


    /**
     * 1.获取(产险直/再保PAA/BBA) 获取基础数据
     *
     * @param valMethod 评估方法 {@link EvaluateMethodTypeEnum}
     * @param valMonth  评估月(yyyyMM)
     * @return r
     */
    @DSTransactional
    @Override
    public R<?> setCxPiMeasureCfBasicDataRst(String valMethod, String valMonth) {
        // 1.根据评估时点+评估方法 清理旧数据
        int numberOfBatch = measureCfBasicDataMapper.delete(new LambdaQueryWrapper<MeasureCfBasicData>().eq(MeasureCfBasicData::getValMonth,
                valMonth).eq(MeasureCfBasicData::getValMethod, valMethod));
        log.info("清理评估时点{}-评估方法{}={}条", valMonth, valMethod, numberOfBatch);
        // 2.获取数据
        ContextUtils.executeStrategyBasicData(EvaluateMethodTypeEnum.getEnumType(valMethod), valMonth);
        return R.ok();
    }

    /**
     * 2.计算(产险直保/再保PAA)  PAA当期计量明细
     *
     * @param valMethod 评估方法 {@link EvaluateMethodTypeEnum}
     * @param valMonth  评估时点(yyyyMM)
     * @return r
     */
    public void setCxPiPaaMeasureCfResultInfoRst(String valMethod, String valMonth) {
        try {
            // 一.获取 计量源数据(从计量数据准备输出数据中获取)
            // 构建参数
            LambdaQueryWrapper<MeasureCfBasicData> lambdaQueryWrapper = Wrappers.lambdaQuery();
            // 1.评估时点
            lambdaQueryWrapper.eq(MeasureCfBasicData::getValMonth, valMonth);
            // 2.评估方法
            lambdaQueryWrapper.eq(MeasureCfBasicData::getValMethod, valMethod);

            DefaultTransactionDefinition def = new DefaultTransactionDefinition();
            def.setPropagationBehavior(DefaultTransactionDefinition.PROPAGATION_REQUIRES_NEW);
            // 获取事务状态
            TransactionStatus status = transactionManager.getTransaction(def);
            try {
                // 清理明细旧数据
                int delete = measureCfResultInfoMapper.delete(new LambdaQueryWrapper<MeasureCfResultInfo>().eq(MeasureCfResultInfo::getValMonth,
                        valMonth).eq(MeasureCfResultInfo::getValMethod, valMethod));
                // 手动提交事务
                transactionManager.commit(status);
            } catch (Exception e) {
                // 发生异常时回滚事务
                transactionManager.rollback(status);
                log.error(e.getMessage(), e);
            }
            long startTime = System.currentTimeMillis();
            if (EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_10.getCode().equals(valMethod)) {
                // 提前查询数据，放入缓存
                measureCommonCacheService.getMeasureAllocationCache(valMonth);
                measureCommonCacheService.getMeasureInfoCache(valMethod, DateUtils.lastEndYear(valMonth, DateUtils.YYYYMM),
                        MeasureCfResultInfo::getIacfEopUnRec, MeasureCfResultInfo::getIcEopUnRecAmt, MeasureCfResultInfo::getPremEopUnRecAmt, MeasureCfResultInfo::getIacfEopUnRecRein);
            }
            if (EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_8.getCode().equals(valMethod)) {
                // 提前查询数据，放入缓存
                measureCommonCacheService.getMeasureInfoCache(valMethod, DateUtils.lastEndYear(valMonth, DateUtils.YYYYMM),
                        MeasureCfResultInfo::getPremEopUnRecAmt, MeasureCfResultInfo::getIacfEopUnRec, MeasureCfResultInfo::getIcEopUnRecAmt, MeasureCfResultInfo::getIacfEopUnRecRein);
            }
            if (EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_11.getCode().equals(valMethod)) {
                // 提前查询数据，放入缓存
                measureCommonCacheService.getMeasureInfoCache(valMethod, DateUtils.lastEndYear(valMonth, DateUtils.YYYYMM),
                        MeasureCfResultInfo::getIacfEopUnRec, MeasureCfResultInfo::getIcEopUnRecAmt, MeasureCfResultInfo::getPremEopUnRecAmt, MeasureCfResultInfo::getIacfEopUnRecRein);
            }
            log.error("===============评估方法;{},加载缓存内容:{}秒", valMethod, (System.currentTimeMillis() - startTime) / 1000);

            // 总数据
            long selectCount = measureCfBasicDataMapper.selectCount(lambdaQueryWrapper);
            long number = selectCount % BATCH_SIZE == 0 ? selectCount / BATCH_SIZE : selectCount / BATCH_SIZE + 1;
            CountDownLatch latch = new CountDownLatch((int) number);
            long maxId = 0;  // 用于优化分页的游标
            int page = 1;

            while (true) {
                // 使用游标方式分页查询（优化性能）
                List<MeasureCfBasicData> records = measureCfBasicDataMapper.selectList(new LambdaQueryWrapper<MeasureCfBasicData>()
                        .eq(MeasureCfBasicData::getValMonth, valMonth)
                        .eq(MeasureCfBasicData::getValMethod, valMethod)
                        .gt(MeasureCfBasicData::getId, maxId)
                        .orderByAsc(MeasureCfBasicData::getId)
                        .last("LIMIT " + BATCH_SIZE));
                if (records.isEmpty()) {
                    break;
                }
                // 异步处理
                ContextUtils.executeStrategyResultInfo(records, EvaluateMethodTypeEnum.getEnumType(valMethod), valMonth, latch);
                // 更新游标
                maxId = records.get(records.size() - 1).getId();
                page++;
            }
            // 等待全部线程执行完
            latch.await();
        } catch (Exception e) {
            log.error(e.getMessage(), e);
            throw new RuntimeException(e);
        } finally {
            // 清除本地缓存
            measureCommonCacheService.invalidate();
        }
    }


    /**
     * 3.计量(产险直保/再保PAA) 获取未决CASE等数据写入实际现金流表中
     *
     * @param valMethod 评估方法
     * @param valMonth  评估时点
     * @return r
     */
    @Override
    @DSTransactional
    public R<?> setCxPiPaaCfBasicCalcRst(String valMethod, String valMonth) {
        List<MeasureCfBasicCalcRst> allList = Lists.newArrayList();
        List<MeasureCfBasicCalcRst> getAllCaseSettledDataList = publicDbService.getAllCaseDataList(valMethod, valMonth);
        allList.addAll(getAllCaseSettledDataList);
        // 5产险直保计量_明细数据
//    List<MeasureCfBasicCalcRst> getMeasureCfResultInfoSumList = getMeasureCfResultInfoSum(valMethod, valMonth);
//    allList.addAll(getMeasureCfResultInfoSumList);

        // 批量删除当前评估月+评估方法的数
        int numberOfBatch = measureCfBasicCalcRstMapper.delete(new LambdaQueryWrapper<MeasureCfBasicCalcRst>().eq(MeasureCfBasicCalcRst::getValMonth,
                valMonth).eq(MeasureCfBasicCalcRst::getValMethod, valMethod));
        log.info("measureCfBasicCalcRst delete old Data {}-{}={}", valMonth, valMethod, numberOfBatch);

        // 5.新增数据
        boolean b = StringUtils.isNotEmpty(allList) ? measureCfBasicCalcRstMapper.insertBatch(allList.stream().distinct().collect(Collectors.toList())) : Boolean.TRUE;
        return R.ok(b);
    }

    @DSTransactional
    @Override
    public R<?> setCxZbResultAllocation(String evaluateMethod, String valMonth) {

        boolean isSuccess = true;

        if (Objects.equals(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_8, EvaluateMethodTypeEnum.getEnumType(evaluateMethod))
                || Objects.equals(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_11, EvaluateMethodTypeEnum.getEnumType(evaluateMethod))) {
            // 获取计量明细基础数据
            Map<String, MeasureCfResultInfo> baseDataMap = getMeasureCfResultInfoMap(valMonth, evaluateMethod, MeasureCfResultInfo::getValMonth,
                    MeasureCfResultInfo::getValMethod, MeasureCfResultInfo::getLastValMonth, MeasureCfResultInfo::getGroupId, MeasureCfResultInfo::getUnitId,
                    MeasureCfResultInfo::getComCode, MeasureCfResultInfo::getBusinessNature, MeasureCfResultInfo::getCoverageSegment, MeasureCfResultInfo::getCarKindCode,
                    MeasureCfResultInfo::getUseNatureCode, MeasureCfResultInfo::getUnRecPremAmt, MeasureCfResultInfo::getPortfolioId, MeasureCfResultInfo::getCurrency,
                    MeasureCfResultInfo::getClassCode, MeasureCfResultInfo::getUnderWriteDate, MeasureCfResultInfo::getCertiWriteDate, MeasureCfResultInfo::getConfirmDate,
                    MeasureCfResultInfo::getPolicyNo, MeasureCfResultInfo::getCertiNo, MeasureCfResultInfo::getRiskCode,
                    MeasureCfResultInfo::getPremiumCny, MeasureCfResultInfo::getShareFactor, MeasureCfResultInfo::getShareFactorRein);

            ArrayList<MeasureResultAllocation> resList = new ArrayList<>();
            baseDataMap.values().stream().forEach(entity -> {
                MeasureResultAllocation t = new MeasureResultAllocation();
                t.setValMonth(entity.getValMonth());
                t.setLastValMonth(entity.getLastValMonth());
                t.setUnitId(entity.getUnitId());
                t.setGroupId(entity.getGroupId());
                t.setComCode(entity.getComCode());
                t.setBusinessNature(entity.getBusinessNature());
                t.setCoverageSegment(entity.getCoverageSegment());
                t.setCarKindCode(entity.getCarKindCode());
                t.setUseNatureCode(entity.getUseNatureCode());
                t.setValMethod(entity.getValMethod());
                t.setUnRecPremAmt(entity.getUnRecPremAmt());
                t.setCurrency(entity.getCurrency());
                t.setPortfolioId(entity.getPortfolioId());
                t.setRiskCode(entity.getRiskCode());
                t.setPolicyNo(entity.getPolicyNo());
                t.setCertiNo(entity.getCertiNo());
                t.setClassCode(entity.getClassCode());
                t.setUnderWriteDate(entity.getUnderWriteDate());
                t.setConfirmDate(entity.getConfirmDate());
                t.setCertiWriteDate(entity.getCertiWriteDate());
                // 新增字段 - 2025/07/31
                t.setPremiumCny(entity.getPremiumCny());
                t.setShareFactor(entity.getShareFactor());
                t.setShareFactorRein(entity.getShareFactorRein());
                resList.add(t);
            });

            // 以合同分组编号分组计算未经过保费及亏损部分
            // 先计算当期数据
            SqlFunctionUtil<MeasureCfResultInfo> sqlFunctionUtil = new SqlFunctionUtil<>();
            QueryWrapper<MeasureCfResultInfo> wrapper = new QueryWrapper<>();

            wrapper.select(Lists.newArrayList(sqlFunctionUtil.getParamSql(MeasureCfResultInfo::getGroupId), sqlFunctionUtil.getSumParamSql(
                    MeasureCfResultInfo::getUnRecPremAmt, MeasureCfResultInfo::getPvRepAmt, MeasureCfResultInfo::getLrcRaAmt, MeasureCfResultInfo::getLrcNoLcAmt, MeasureCfResultInfo::getLrcNoLcAmtRein,
                    MeasureCfResultInfo::getShareFactor, MeasureCfResultInfo::getShareFactorRein)));
            wrapper.groupBy(sqlFunctionUtil.getParamSql(MeasureCfResultInfo::getGroupId));
            wrapper.eq(sqlFunctionUtil.getParamSql(MeasureCfResultInfo::getValMonth), valMonth);

            Map<String, MeasureCfResultInfo> currentGroupMap = measureCfResultInfoMapper.selectList(wrapper).stream().collect(Collectors.toMap(MeasureCfResultInfo::getGroupId, t -> t));

            // 计算上期期末数据
            wrapper.clear();
            wrapper.select(Lists.newArrayList(sqlFunctionUtil.getParamSql(MeasureCfResultInfo::getGroupId), sqlFunctionUtil.getSumParamSql(
                    MeasureCfResultInfo::getPvRepAmt, MeasureCfResultInfo::getLrcRaAmt, MeasureCfResultInfo::getLrcNoLcAmt, MeasureCfResultInfo::getLrcNoLcAmtRein,
                    MeasureCfResultInfo::getShareFactor, MeasureCfResultInfo::getShareFactorRein)));
            wrapper.groupBy(sqlFunctionUtil.getParamSql(MeasureCfResultInfo::getGroupId));
            wrapper.eq(sqlFunctionUtil.getParamSql(MeasureCfResultInfo::getValMonth), DateUtils.lastEndYear(valMonth, DateUtils.YYYYMM));
            Map<String, MeasureCfResultInfo> lastGroupMap = measureCfResultInfoMapper.selectList(wrapper).stream().collect(Collectors.toMap(
                    MeasureCfResultInfo::getGroupId, t -> t));

            resList.stream().forEach(t -> {
                String groupId = t.getGroupId();
                MeasureCfResultInfo entity = new MeasureCfResultInfo();
                if (currentGroupMap.containsKey(groupId)) {
                    entity = currentGroupMap.get(groupId);
                }
                // 12.未经过保费(合同组）un_rec_prem_amt_group = 根据合同分组编号汇总un_rec_prem_amt
                t.setUnRecPremAmtGroup(entity.getUnRecPremAmt());
                // 新增字段 - 2025/07/31
                // 分摊因子(合同组) = 根据合同分组编号汇总表a.share_factor
                t.setShareFactorGroup(entity.getShareFactor());
                // 分摊因子_再保(合同组) = 根据合同分组编号汇总表a.share_factor_rein
                t.setShareFactorReinGroup(entity.getShareFactorRein());


                // 13. 亏损部分(合同组）lrc_lc_change_amt_group = 根据合同分组编号汇总数据，max(0,a.pv_rep_amt + a.lrc_ra_amt - a.lrc_no_lc_amt)-上期期末的max(0,a.pv_rep_amt + a.lrc_ra_amt - a.lrc_no_lc_amt)
                // 19. 亏损部分(合同组)_再保  = 根据合同分组编号汇总表a数据，max(0,a.pv_rep_amt + a.lrc_ra_amt - a.lrc_no_lc_amt_rein)-上期期末的max(0,a.pv_rep_amt + a.lrc_ra_amt - a.lrc_no_lc_amt_rein)
                BigDecimal lrcLcChangeAmtGroup = entity.getPvRepAmt().add(entity.getLrcRaAmt()).subtract(entity.getLrcNoLcAmt());
                BigDecimal lrcLcChangeAmtGroupRein = entity.getPvRepAmt().add(entity.getLrcRaAmt()).subtract(entity.getLrcNoLcAmtRein()).max(BigDecimal.ZERO);
                t.setLrcLcChangeAmtGroup(lrcLcChangeAmtGroup.max(BigDecimal.ZERO));
                t.setLrcLcChangeAmtGroupRein(lrcLcChangeAmtGroupRein);
                if (lastGroupMap.containsKey(groupId)) {
                    entity = lastGroupMap.get(groupId);
                    BigDecimal lastLrcLcChangeAmtGroup = (entity.getPvRepAmt().add(entity.getLrcRaAmt()).subtract(entity.getLrcNoLcAmt())).max(BigDecimal.ZERO);
                    t.setLrcLcChangeAmtGroup(t.getLrcLcChangeAmtGroup().subtract(lastLrcLcChangeAmtGroup));

                    BigDecimal lastLrcLcChangeAmtGroupRein = entity.getPvRepAmt().add(entity.getLrcRaAmt()).subtract(entity.getLrcNoLcAmtRein()).max(BigDecimal.ZERO);
                    t.setLrcLcChangeAmtGroupRein(t.getLrcLcChangeAmtGroupRein().subtract(lastLrcLcChangeAmtGroupRein));
                }


                // 14 亏损部分 lrc_lc_change_amt = 11.分摊因子/12.分摊因子(合同组)*13.亏损部分(合同组)
                if (t.getShareFactorGroup().compareTo(BigDecimal.ZERO) == 0) {
                    t.setLrcLcChangeAmt(BigDecimal.ZERO);
                } else {
                    BigDecimal calculatedValue = t.getShareFactor().multiply(t.getLrcLcChangeAmtGroup()).divide(t.getShareFactorGroup(), 10, RoundingMode.HALF_UP);
                    t.setLrcLcChangeAmt(calculatedValue);
                }


                // 20 判断条件 = c.首日获取费用率+c.赔付率*(1+c.间接理赔费用率)
                // 赔付率，间接理赔费用率 (根据险类代码、当前评估时点及评估方法匹配)
                // 再保分入paa：首日获取费用率(通过险类代码，确认时间及评估方法匹配)
                // 直保paa: 首日获取费用率(通过险类代码，(签单日期,批单签单日期)及评估方法匹配，有批单号取批单签单日期，没有批单号取签单日期)

                // 赔付率
                BigDecimal lossRatio = confMeasureActuarialAssumptionCacheService.getConfMeasureActuarialAssumption(evaluateMethod, t.getValMonth(),
                        t.getClassCode(), StringConstant.STRING_NA, StringConstant.STRING_NA, StringConstant.STRING_NA, ConfMeasureActuarialAssumption::getLossRatio);
                // 间接理赔费用率
                BigDecimal indirectClaimsExpenseRatio = confMeasureActuarialAssumptionCacheService.getConfMeasureActuarialAssumption(evaluateMethod, t.getValMonth(),
                        t.getClassCode(), StringConstant.STRING_NA, StringConstant.STRING_NA, StringConstant.STRING_NA, ConfMeasureActuarialAssumption::getIndirectClaimsExpenseRatio);

                // 首日获取费用率
                BigDecimal acquisitionExpenseRatio;
                String matchDate;
                if (Objects.equals(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_8, EvaluateMethodTypeEnum.getEnumType(evaluateMethod))) {
                    matchDate = StringConstant.STRING_NA.equals(t.getCertiNo()) ? DateUtils.endMonth(t.getUnderWriteDate(), DateUtils.YYYYMM) : DateUtils.endMonth(t.getCertiWriteDate(), DateUtils.YYYYMM);
                } else {
                    matchDate = DateUtils.endMonth(t.getConfirmDate(), DateUtils.YYYYMM);
                }
                acquisitionExpenseRatio = confMeasureActuarialAssumptionCacheService.getConfMeasureActuarialAssumption(evaluateMethod, matchDate,
                        t.getClassCode(), StringConstant.STRING_NA, StringConstant.STRING_NA, StringConstant.STRING_NA, ConfMeasureActuarialAssumption::getFirstDayAcquisitionExpenseRatio);
                t.setJudgingCondition(acquisitionExpenseRatio.add(lossRatio.multiply(BigDecimal.ONE.add(indirectClaimsExpenseRatio))));

                // 21 亏损部分_再保
                // --如果17.判断条件>=1,则18.亏损部分_再保=22.分摊因子_再保/23.分摊因子_再保(合同组)*16.亏损部分(合同组)_再保
                // --如果17.判断条件<1,则18.亏损部分_再保=0
                if (t.getJudgingCondition().compareTo(BigDecimal.ONE) < 0) {
                    t.setLrcLcChangeAmtRein(BigDecimal.ZERO);
                } else if (t.getShareFactorReinGroup().compareTo(BigDecimal.ZERO) == 0) {
                    t.setLrcLcChangeAmtRein(BigDecimal.ZERO);
                } else {
                    BigDecimal calculatedValueRein = t.getShareFactorRein().multiply(t.getLrcLcChangeAmtGroupRein()).divide(t.getShareFactorReinGroup(), 10, RoundingMode.HALF_UP);;
                    t.setLrcLcChangeAmtRein(calculatedValueRein);
                }
            });

            // 批量删除当前评估月+评估方法的数
            int numberOfBatch = measureResultAllocationMapper.delete(new LambdaQueryWrapper<MeasureResultAllocation>().eq(MeasureResultAllocation::getValMonth,
                    valMonth).eq(MeasureResultAllocation::getValMethod, evaluateMethod));
            log.info("measureResultAllocation delete old Data{}-{}={}", valMonth, evaluateMethod, numberOfBatch);

            isSuccess = measureResultAllocationMapper.insertBatch(resList);
            log.info("measureResultAllocation insert new Data{}-{}={}", valMonth, evaluateMethod, resList.size());
        } else if (Objects.equals(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_7, EvaluateMethodTypeEnum.getEnumType(evaluateMethod))) {
            // 批量删除当前评估月+评估方法的数
            int numberOfBatch = measureResultAllocationMapper.delete(new LambdaQueryWrapper<MeasureResultAllocation>().eq(MeasureResultAllocation::getValMonth,
                    valMonth).eq(MeasureResultAllocation::getValMethod, evaluateMethod));
            log.info("measureResultAllocation delete old Data{}-{}={}", valMonth, evaluateMethod, numberOfBatch);

            int insertedRows = measureResultAllocationMapper.insertMeasureResultAllocation(valMonth, evaluateMethod);
            log.info("measureResultAllocation insert new Data{}-{}={}", valMonth, evaluateMethod, insertedRows);

    }
    return R.ok(isSuccess);
  }


  /**
   * 2.计算(产险直保/再保BBA)  当期计量明细
   *
   * @param valMethod 评估方法(1-BBA,2-PBBA,3-VFA,4-PAA)
   * @param valMonth 评估时点(yyyyMM)
   * @return r
   */
  @DSTransactional
  @Override
  public R<?> setCxPiBbaMeasureCfResultInfoRst(String valMethod, String valMonth) {

    // 1.获取 计量源数据(从计量数据准备输出数据中获取)
    List<MeasureCfBasicData> measureCfBasicDataList = getMeasureCfBasicDataList(valMonth, valMethod);


    int numberOfBatch = measureCfResultInfoMapper.delete(new LambdaQueryWrapper<MeasureCfResultInfo>()
      .eq(MeasureCfResultInfo::getValMonth, valMonth)
      .eq(MeasureCfResultInfo::getValMethod, valMethod));
    log.info("measureCfResultInfo delete old Data {}-{}={}", valMonth, valMethod, numberOfBatch);

    // 2.计算
    ContextUtils.executeStrategyResultInfo(measureCfBasicDataList, EvaluateMethodTypeEnum.getEnumType(valMethod), valMonth);

    return R.ok();
  }

  /**
   * 3.计算明细计量汇总写入预期现金流表
   *
   * @param valMethod 评估方法
   * @param valMonth  评估时点
   * @return r
   */
  @Override
  public void setCxInfoToCfBasicExpRst(String valMethod, String valMonth) {
    try {
      //将计量明细转成通用预期现金流表格式，用于计算计量分录
      List<MeasureCfBasicExpRst> allList= getMeasureCfBasicExpRstOne(valMethod, valMonth);

      //构建参数
      LambdaQueryWrapper<MeasureCfBasicExpRst> lambdaQueryWrapper = Wrappers.lambdaQuery();
      //1.评估时点
      lambdaQueryWrapper.eq(MeasureCfBasicExpRst::getValMonth, valMonth);
      //2.评估方法
      lambdaQueryWrapper.eq(MeasureCfBasicExpRst::getValMethod, valMethod);
      //清理当前评估月旧数据
      measureCfBasicExpRstMapper.delete(lambdaQueryWrapper);
      measureCfBasicExpRstMapper.insertBatch(allList);
    }catch (Exception e){
      log.error("计量明细转成通用预期现金流表失败"+e.getMessage(),e);
      throw new RuntimeException(e.getMessage(),e);
    }
  }

  /**
   * 计量核算表
   *
   * @param valMethod 评估方法
   * @param valMonth  评估时点
   * @return r
   */
  @Override
  public R<?> setCxMeasureResultCheck(String valMethod, String valMonth) {
    //清除当期核算表数据
    int delete = measureResultCheckMapper.delete(new LambdaQueryWrapper<MeasureResultCheck>().eq(MeasureResultCheck::getValMonth,
        valMonth).eq(MeasureResultCheck::getValMethod, valMethod));
    //数据异常标识
    Boolean dataExecetion = Boolean.FALSE;
    List<MeasureResultCheck> measureResultCheckList = new ArrayList<>();
    //获取计量明细+核心计量去重后的数据
    List<MeasureResultCore> groupIdList = measureCommonOtherMapper.getDistinctMeasureCfBasicExpCoreList(valMethod, valMonth);
    //获取当期计量明细按合同组汇总数据
    Map<String, MeasureCfResultInfo> measureCfResultInfoGroupIdMap =
      getMeasureCfResultInfoGroupIdMap(valMonth, valMethod,MeasureCfResultInfo::getPremBopUnRecAmt,MeasureCfResultInfo::getPremInterestAmt,
        MeasureCfResultInfo::getPremCurRecAmt,MeasureCfResultInfo::getPremEopUnRecAmt,MeasureCfResultInfo::getIacfBopUnRecAmt,
        MeasureCfResultInfo::getIacfInterestAmt,MeasureCfResultInfo::getIacfAmortAmt,MeasureCfResultInfo::getIacfEopUnRec,
        MeasureCfResultInfo::getIcBopUnRecAmt, MeasureCfResultInfo::getIcInterestAmt,MeasureCfResultInfo::getIcPaidAmt,
        MeasureCfResultInfo::getIcEopUnRecAmt, MeasureCfResultInfo::getIsrAmt,MeasureCfResultInfo::getLrcIfieAmt,
        MeasureCfResultInfo::getLrcNoLcAmt, MeasureCfResultInfo::getUnRecPremAmt,MeasureCfResultInfo::getPvRepAmt,
        MeasureCfResultInfo::getLrcRaAmt);
    //获取上期计量明细按合同组汇总数据
    Map<String, MeasureCfResultInfo> measureCfResultInfoGroupIdMapLast =
      getMeasureCfResultInfoGroupIdMap(DateUtils.lastEndYear(valMonth, DateUtils.YYYYMM), valMethod,
        MeasureCfResultInfo::getLrcNoLcAmt,MeasureCfResultInfo::getPvRepAmt, MeasureCfResultInfo::getLrcRaAmt);
    //获取当期分摊计量按合同组汇总后的亏损部分
    Map<String, MeasureResultAllocation> measureResultAllocationSumMap = Optional.ofNullable(measureResultAllocationMapper.getLrcLcChangeAmtGroupByGroupId(valMonth, valMethod))
      .orElse(Collections.emptyList())
      .stream().filter(e -> StringUtils.isNotBlank(e.getGroupId()))
      .collect(Collectors.toMap(MeasureResultAllocation::getGroupId, t -> t));
    //获取当期核心计量按合同组汇总数据
    Map<String, Map<String, BigDecimal>> measureResultCoreGroupMap = getMeasureResultCoreGroupMap(valMonth, valMethod);

    for(MeasureResultCore entity:groupIdList){
      MeasureCfResultInfo info = measureCfResultInfoGroupIdMap.getOrDefault(entity.getGroupId(), new MeasureCfResultInfo());
      MeasureCfResultInfo lastInfo = measureCfResultInfoGroupIdMapLast.getOrDefault(entity.getGroupId(), new MeasureCfResultInfo());
      MeasureResultAllocation allocation = measureResultAllocationSumMap.getOrDefault(entity.getGroupId(), new MeasureResultAllocation());
      Map<String, BigDecimal> coreMap = measureResultCoreGroupMap.getOrDefault(entity.getGroupId(), new HashMap<>());

      MeasureResultCheck t = new MeasureResultCheck();
      t.setValMonth(entity.getValMonth());
      t.setValMethod(entity.getValMethod());
      t.setLastValMonth(DateUtils.lastEndYear(entity.getValMonth(), DateUtils.YYYYMM));
      t.setGroupId(entity.getGroupId());
      if(valMethod.equals("10")){
        t.setComCode(info.getComCode());
        t.setCarKindCode(info.getCarKindCode());
        t.setUseNatureCode(info.getUseNatureCode());
        t.setClassCode(info.getClassCode());
        t.setRiskCode(info.getRiskCode());
        //期初未确认保费
        t.setPremBopUnRecAmt(Optional.ofNullable(info.getPremBopUnRecAmt()).orElse(BigDecimal.ZERO));
        //期初保费计息
        t.setPremInterestAmt(Optional.ofNullable(info.getPremInterestAmt()).orElse(BigDecimal.ZERO));
        //当期确认的保费
        t.setPremCurRecAmt(Optional.ofNullable(info.getPremCurRecAmt()).orElse(BigDecimal.ZERO));
        //期末未确认的保费
        t.setPremEopUnRecAmt(Optional.ofNullable(info.getPremEopUnRecAmt()).orElse(BigDecimal.ZERO));
        t.setIcBopUnRecAmt(Optional.ofNullable(info.getIcBopUnRecAmt()).orElse(BigDecimal.ZERO));
        t.setIcInterestAmt(Optional.ofNullable(info.getIcInterestAmt()).orElse(BigDecimal.ZERO));
        t.setIcPaidAmt(Optional.ofNullable(info.getIcPaidAmt()).orElse(BigDecimal.ZERO));
        t.setIcEopUnRecAmt(Optional.ofNullable(info.getIcEopUnRecAmt()).orElse(BigDecimal.ZERO));
        t.setIsrAmt(Optional.ofNullable(info.getIsrAmt()).orElse(BigDecimal.ZERO));
        t.setLrcIfieAmt(Optional.ofNullable(info.getLrcIfieAmt()).orElse(BigDecimal.ZERO));
        t.setLrcNoLcAmt(Optional.ofNullable(info.getLrcNoLcAmt()).orElse(BigDecimal.ZERO));
        MeasureResultCheck measureResultCheck = new MeasureResultCheck();
        measureResultCheck.setValMonth(DateUtils.lastEndYear(entity.getValMonth(), DateUtils.YYYYMM));
        measureResultCheck.setValMethod(entity.getValMethod());
        measureResultCheck.setGroupId(entity.getGroupId());
        MeasureResultCheck lastmeasureResultCheck = measureResultCheckMapper.selectOne(new QueryWrapper<>(measureResultCheck));
        //取上期lrc_eop_lc
        if(ObjectUtils.isNotEmpty(lastmeasureResultCheck)){
          t.setLrcBopLc(Optional.ofNullable(lastmeasureResultCheck.getLrcEopLc()).orElse(BigDecimal.ZERO));
        }else{
          t.setLrcBopLc(BigDecimal.ZERO);
        }
        t.setLrcLcChangeAmtGroup(Optional.ofNullable(allocation.getLrcLcChangeAmtGroup()).orElse(BigDecimal.ZERO));
        t.setLrcEopLc(t.getLrcBopLc().add(t.getLrcLcChangeAmtGroup()));
        t.setLrc(t.getLrcNoLcAmt().add(t.getLrcEopLc()));
        measureResultCheckList.add(t);
      }else {
        //期初未确认保费
        t.setPremBopUnRecAmt(Optional.ofNullable(info.getPremBopUnRecAmt()).orElse(BigDecimal.ZERO));
        //期初保费计息
        t.setPremInterestAmt(Optional.ofNullable(info.getPremInterestAmt()).orElse(BigDecimal.ZERO));
        //当期确认的保费
        t.setPremCurRecAmt(Optional.ofNullable(info.getPremCurRecAmt()).orElse(BigDecimal.ZERO));
        //期末未确认的保费
        t.setPremEopUnRecAmt(Optional.ofNullable(info.getPremEopUnRecAmt()).orElse(BigDecimal.ZERO));
        //期初未确认的IACF
        t.setIacfBopUnRecAmt(Optional.ofNullable(info.getIacfBopUnRecAmt()).orElse(BigDecimal.ZERO));
        //IACF计息
        t.setIacfInterestAmt(Optional.ofNullable(info.getIacfInterestAmt()).orElse(BigDecimal.ZERO));
        //当期确认的IACF
        t.setIacfAmortAmt(Optional.ofNullable(info.getIacfAmortAmt()).orElse(BigDecimal.ZERO));
        //期末未确认的IACF
        t.setIacfEopUnRec(Optional.ofNullable(info.getIacfEopUnRec()).orElse(BigDecimal.ZERO));
        //期初未确认的投资成分
        t.setIcBopUnRecAmt(Optional.ofNullable(info.getIcBopUnRecAmt()).orElse(BigDecimal.ZERO));
        //期初投资成分计息
        t.setIcInterestAmt(Optional.ofNullable(info.getIcInterestAmt()).orElse(BigDecimal.ZERO));
        //当期确认的投资成分
        t.setIcPaidAmt(Optional.ofNullable(info.getIcPaidAmt()).orElse(BigDecimal.ZERO));
        //期末未确认的投资成分
        t.setIcEopUnRecAmt(Optional.ofNullable(info.getIcEopUnRecAmt()).orElse(BigDecimal.ZERO));
        //保险合同收入
        t.setIsrAmt(Optional.ofNullable(info.getIsrAmt()).orElse(BigDecimal.ZERO));
        //IFIE未到期利息
        t.setLrcIfieAmt(Optional.ofNullable(info.getLrcIfieAmt()).orElse(BigDecimal.ZERO));
        //未到期责任负债-非亏损部分
        t.setLrcNoLcAmt(Optional.ofNullable(info.getLrcNoLcAmt()).orElse(BigDecimal.ZERO));
        //未经过保费
        t.setUnRecPremAmt(Optional.ofNullable(info.getUnRecPremAmt()).orElse(BigDecimal.ZERO));
        //预期未来现金流现值
        t.setPvRepAmt(Optional.ofNullable(info.getPvRepAmt()).orElse(BigDecimal.ZERO));
        //未到期-金融风险调整
        t.setLrcRaAmt(Optional.ofNullable(info.getLrcRaAmt()).orElse(BigDecimal.ZERO));
        //期初未到期-亏损
        BigDecimal lastpvRepAmt = Optional.ofNullable(lastInfo.getPvRepAmt()).orElse(BigDecimal.ZERO);
        BigDecimal lastLrcRaAmt = Optional.ofNullable(lastInfo.getLrcRaAmt()).orElse(BigDecimal.ZERO);
        BigDecimal lastLrcNoLCAmt = Optional.ofNullable(lastInfo.getLrcNoLcAmt()).orElse(BigDecimal.ZERO);
        BigDecimal lrcBopLcAmt = lastpvRepAmt.add(lastLrcRaAmt).subtract(lastLrcNoLCAmt).max(BigDecimal.ZERO);
        t.setLrcBopLc(lrcBopLcAmt);
        //期末未到期-亏损
        BigDecimal lrcEopLcAmt = (t.getPvRepAmt().add(t.getLrcRaAmt()).subtract(t.getLrcNoLcAmt())).max(BigDecimal.ZERO);
        t.setLrcEopLc(lrcEopLcAmt);
        //当期未到期-亏损
        t.setLrcLcChangeAmtGroup(Optional.ofNullable(allocation.getLrcLcChangeAmtGroup()).orElse(BigDecimal.ZERO));
        //未到期责任负债
        t.setLrc(t.getLrcNoLcAmt().add(t.getLrcLcChangeAmtGroup()));
        //如果29.lrc_eop_lc - 28.lrc_bop_lc- 30.lrc_lc_change_amt=0,则通过检查，否则不通过检查
        if (BigDecimal.ZERO.compareTo(t.getLrcEopLc().subtract(t.getLrcBopLc()).subtract(t.getLrcLcChangeAmtGroup())) != 0) {
          t.setIsStatus(DataStateTypeEnum.DATA_STATE_TYPE_3.getCode());
          t.setRemark(String.format("未到期亏损计算校验不通过，合同分组编码：%s，期末未到期亏损：%s,期初未到期亏损：%s,当期未到期亏损：%s",
            t.getGroupId(), t.getLrcEopLc(), t.getLrcBopLc(), t.getLrcLcChangeAmtGroup()));
          dataExecetion = Boolean.TRUE;
        }
        //赔付与费用_已发生已报告未决赔款负债提转差_预期现金流
        t.setRbnpBelCurrRecg(coreMap.getOrDefault("rbnp_bel_curr_recg", BigDecimal.ZERO));
        //赔付与费用_已发生未报告未决赔款负债提转差_预期现金流
        t.setIbnrBelCurrRecg(coreMap.getOrDefault("ibnr_bel_curr_recg", BigDecimal.ZERO));
        //赔付与费用_间接理赔费用负债提转差_预期现金流
        t.setCerBelCurrRecg(coreMap.getOrDefault("cer_bel_curr_recg", BigDecimal.ZERO));
        //往期赔付的调整_履约现金流
        t.setRbnpBelCurrRels(coreMap.getOrDefault("rbnp_bel_curr_rels", BigDecimal.ZERO));
        //往期赔付的调整_履约现金流
        t.setRbnpBelPrvChg(coreMap.getOrDefault("rbnp_bel_prv_chg", BigDecimal.ZERO));
        //赔付与费用_已发生已报告未决赔款负债提转差_非金融风险调整
        t.setRbnpRaCurrRecg(coreMap.getOrDefault("rbnp_ra_curr_recg", BigDecimal.ZERO));
        //赔付与费用_已发生未报告未决赔款负债提转差_非金融风险调整
        t.setIbnrRaCurrRecg(coreMap.getOrDefault("ibnr_ra_curr_recg", BigDecimal.ZERO));
        //赔付与费用_间接理赔费用负债提转差_非金融风险调整
        t.setCerRaCurrRecg(coreMap.getOrDefault("cer_ra_curr_recg", BigDecimal.ZERO));
        //往期赔付的调整_非金融风险调整
        t.setRbnpRaCurrRels(coreMap.getOrDefault("rbnp_ra_curr_rels", BigDecimal.ZERO));
        //往期赔付的调整_非金融风险调整
        t.setRbnpRaPrvChg(coreMap.getOrDefault("rbnp_ra_prv_chg", BigDecimal.ZERO));
        //IFIE_已发生_履约现金流
        t.setLicBelIfie(coreMap.getOrDefault("lic_bel_ifie", BigDecimal.ZERO));
        //IFIE_已发生_非金融风险调整
        t.setLicRaIfie(coreMap.getOrDefault("lic_ra_ifie", BigDecimal.ZERO));
        measureResultCheckList.add(t);
      }
    }
    measureResultCheckMapper.insertBatch(measureResultCheckList);
    if(dataExecetion){
      return R.fail("计量核算表明细汇总计算有误");
    }
    return R.ok();
  }

  /**
   * - 直保BBA 计算明细计量汇总写入预期现金流表（2.0）
   *
   * @Author hzh
   * @date 2024/11/7
   */
  @DSTransactional
  public R<?> setCxMeasureCfBbaExpRst(String valMethod, String valMonth) throws ParseException {

    ///获取计量明细数据
    Map<String, MeasureCfResultInfo> sourceMap = getMeasureCfResultInfoMap(valMonth, valMethod);
    //2.计算
    List<MeasureCfBbaExpRst> resList = ContextUtils.executeStrategyExpRst(new ArrayList<>(sourceMap.values()), EvaluateMethodTypeEnum.getEnumType(valMethod), valMonth);

    //4.清除旧数据
    int numberOfBatch = measureCfBbaExpRstMapper.delete(new LambdaQueryWrapper<MeasureCfBbaExpRst>()
        .eq(MeasureCfBbaExpRst::getValMonth, valMonth)
        .eq(MeasureCfBbaExpRst::getValMethod, valMethod));
    log.info("预期现金流 delete old Data {}-{}={}", valMonth, valMethod, numberOfBatch);

    boolean isSuccess = measureCfBbaExpRstMapper.insertBatch(resList, 2000);
    log.info("预期现金流【{}】...endInsert,total {} rows...{}", valMonth, resList.size(), isSuccess ? "success" : "fail");

    return R.ok(isSuccess);
  }



  /**
   * - 5.计量源数据写入实际现金流（2.0）
   *
   * @param valMethod 评估方法，默认BBA
   * @param valMonth 评估时点 (yyyyMM).
   * @return R<?>
   * @date 2024/12/19
   */
  @Override
  @DSTransactional
  public R<?> setCxZbMeasureCfBbaBasicCalcRst(String valMethod, String valMonth) {

    ///获取计量原数据
    List<MeasureCfBasicData> measureCfBasicDataList = getMeasureCfBasicDataList(valMonth, valMethod);
    //    2.计算
    List<MeasureCfBbaBasicCalcRst> resList = ContextUtils.executeActualStrategyExpRst(measureCfBasicDataList, EvaluateMethodTypeEnum.getEnumType(valMethod), valMonth);

    //4.清除旧数据
    int numberOfBatch = measureCfBbaBasicCalcRstMapper.delete(
        new LambdaQueryWrapper<MeasureCfBbaBasicCalcRst>().eq(MeasureCfBbaBasicCalcRst::getValMonth, valMonth)
            .eq(MeasureCfBbaBasicCalcRst::getValMethod, valMethod));
    log.info("实际现金流 delete old Data {}-{}={}", valMonth, valMethod, numberOfBatch);


    boolean isSuccess = measureCfBbaBasicCalcRstMapper.insertBatch(resList, 2000);
    log.info("实际现金流【{}】...endInsert,total {} rows...{}", valMonth, resList.size(), isSuccess ? "success" : "fail");

    return R.ok(isSuccess);
  }

  // 工具与模型
  private static String key(String m, String method, String gid){ return m + "|" + method + "|" + gid; }
  private static BigDecimal nz(BigDecimal x){ return x == null ? BigDecimal.ZERO : x; }
  private static final class CaseAgg { final BigDecimal caseCurr, casePast; CaseAgg(BigDecimal c, BigDecimal p){ caseCurr=c; casePast=p; } }
  private static final class IbnrAgg { final BigDecimal ibnrCurr, ibnrPast, cerCurr, cerPast; IbnrAgg(BigDecimal iC, BigDecimal iP, BigDecimal cC, BigDecimal cP){ ibnrCurr=iC; ibnrPast=iP; cerCurr=cC; cerPast=cP; } }
  private static final class Factors { final BigDecimal rR, iR, cR; Factors(BigDecimal rbnpr, BigDecimal ibnr, BigDecimal cer){ rR=rbnpr; iR=ibnr; cR=cer; } }
  @Override
  public R<?> setCxMeasureResultCheckLic(String valMethod, String valMonth) {
    measureResultCheckLicMapper.delete(new QueryWrapper<MeasureResultCheckLic>().eq("val_month", valMonth).eq("val_method", valMethod));

    // 分流到对应实现：8-直保PAA；10-再保分出PAA；11-再保分入PAA
    if (Objects.equals(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_8.getCode(), valMethod)) {
      return setCxMeasureResultCheckLicDirect(valMethod, valMonth);
    } else if (Objects.equals(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_10.getCode(), valMethod)) {
      return setCxMeasureResultCheckLicReout(valMethod, valMonth);
    } else if (Objects.equals(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_11.getCode(), valMethod)) {
      return setCxMeasureResultCheckLicRein(valMethod, valMonth);
    }
    return R.fail("不支持的评估方法:" + valMethod);
  }

  // 直保PAA（原实现内容迁移到此，不改变行为）
  private R<?> setCxMeasureResultCheckLicDirect(String valMethod, String valMonth) {
    measureResultCheckLicMapper.delete(new QueryWrapper<MeasureResultCheckLic>().eq("val_month", valMonth).eq("val_method", valMethod));
    // 1) 当期 A 表聚合（run_date = valMonth）
    List<TPpJlCase> aCurrList = tPpJlCaseMapper.selectList(
      new QueryWrapper<TPpJlCase>()
        .eq("run_date", valMonth)
        .select("run_date","val_method","group_id",
          "COALESCE(SUM(case_curr_cny),0) AS case_curr_cny",
          "COALESCE(SUM(case_past_cny),0) AS case_past_cny")
        .groupBy("run_date","val_method","group_id")
    );
    Map<String, CaseAgg> aCurrMap = aCurrList.stream().collect(Collectors.toMap(
      e -> key(e.getRunDate(), e.getValMethod(), e.getGroupId()),
      e -> new CaseAgg(nz(e.getCaseCurrCny()), nz(e.getCasePastCny()))
    ));
    // 2) 上期 A 表聚合（run_date = lastYearMm）
    String lastYearMm = DateUtils.lastEndYear(valMonth, DateUtils.YYYYMM);
    List<TPpJlCase> aLastList = tPpJlCaseMapper.selectList(
      new QueryWrapper<TPpJlCase>()
        .eq("run_date", lastYearMm)
        .select("run_date","val_method","group_id",
          "COALESCE(SUM(case_curr_cny),0) AS case_curr_cny",
          "COALESCE(SUM(case_past_cny),0) AS case_past_cny")
        .groupBy("run_date","val_method","group_id")
    );
    Map<String, CaseAgg> aLastMap = aLastList.stream().collect(Collectors.toMap(
      e -> key(e.getRunDate(), e.getValMethod(), e.getGroupId()),
      e -> new CaseAgg(nz(e.getCaseCurrCny()), nz(e.getCasePastCny()))
    ));

    //b表
    List<TPpIbnrDirectIn> bCurrList = tPpIbnrDirectInMapper.selectList(
      new QueryWrapper<TPpIbnrDirectIn>()
        .eq("val_month", valMonth)
        .select("val_month","val_method","group_id",
          "COALESCE(SUM(ibnr_curr_before_pi),0) AS ibnr_curr_before_pi",
          "COALESCE(SUM(ibnr_past_before_pi),0) AS ibnr_past_before_pi",
          "COALESCE(SUM(cer_curr_before_pi),0)  AS cer_curr_before_pi",
          "COALESCE(SUM(cer_past_before_pi),0)  AS cer_past_before_pi")
        .groupBy("val_month","val_method","group_id")
    );
    Map<String, IbnrAgg> bCurrMap = bCurrList.stream().collect(Collectors.toMap(
      e -> key(e.getValMonth(), e.getValMethod(), e.getGroupId()),
      e -> new IbnrAgg(nz(e.getIbnrCurrBeforePi()), nz(e.getIbnrPastBeforePi()),
        nz(e.getCerCurrBeforePi()),  nz(e.getCerPastBeforePi()))
    ));

    List<TPpIbnrDirectIn> bLastList = tPpIbnrDirectInMapper.selectList(
      new QueryWrapper<TPpIbnrDirectIn>()
        .eq("val_month", lastYearMm)
        .select("val_month","val_method","group_id",
          "COALESCE(SUM(ibnr_curr_before_pi),0) AS ibnr_curr_before_pi",
          "COALESCE(SUM(ibnr_past_before_pi),0) AS ibnr_past_before_pi",
          "COALESCE(SUM(cer_curr_before_pi),0)  AS cer_curr_before_pi",
          "COALESCE(SUM(cer_past_before_pi),0)  AS cer_past_before_pi")
        .groupBy("val_month","val_method","group_id")
    );
    Map<String, IbnrAgg> bLastMap = bLastList.stream().collect(Collectors.toMap(
      e -> key(e.getValMonth(), e.getValMethod(), e.getGroupId()),
      e -> new IbnrAgg(nz(e.getIbnrCurrBeforePi()), nz(e.getIbnrPastBeforePi()),
        nz(e.getCerCurrBeforePi()),  nz(e.getCerPastBeforePi()))
    ));

    //查询c表的因子数据
    List<TPpJlCase> aClass = tPpJlCaseMapper.selectList(
      new QueryWrapper<TPpJlCase>().eq("run_date", valMonth)
        .select("run_date","val_method","group_id","class_code").groupBy("run_date","val_method","group_id","class_code")
    );
    Map<String, String> grp2Class = aClass.stream().collect(Collectors.toMap(
      e -> key(e.getRunDate(), e.getValMethod(), e.getGroupId()),
      TPpJlCase::getClassCode,
      (x,y) -> x
    ));
// 若需要回退：
    if (grp2Class.isEmpty()) {
      List<TPpIbnrDirectIn> bClass = tPpIbnrDirectInMapper.selectList(
        new QueryWrapper<TPpIbnrDirectIn>().eq("val_month", valMonth)
          .select("val_month","val_method","group_id","class_code").groupBy("val_month","val_method","group_id","class_code")
      );
      grp2Class = bClass.stream().collect(Collectors.toMap(
        e -> key(e.getValMonth(), e.getValMethod(), e.getGroupId()),
        TPpIbnrDirectIn::getClassCode,
        (x,y) -> x
      ));
    }
    Set<String> classCodes = new HashSet<>(grp2Class.values());

// 拉取当期/上期因子表
    List<ConfMeasureActuarialAssumption> cCurr = confMeasureActuarialAssumptionMapper.selectList(
      new QueryWrapper<ConfMeasureActuarialAssumption>().eq("val_month", valMonth).in("class_code", classCodes)
    );
    Map<String, Factors> cCurrMap = cCurr.stream().collect(Collectors.toMap(
      ConfMeasureActuarialAssumption::getClassCode,
      e -> new Factors(nz(e.getRbnpRaFactor()), nz(e.getIbnrRaFactor()), nz(e.getCerRaFactor())),
      (x, y) -> x
    ));

    List<ConfMeasureActuarialAssumption> cLast = confMeasureActuarialAssumptionMapper.selectList(
      new QueryWrapper<ConfMeasureActuarialAssumption>().eq("val_month", lastYearMm).in("class_code", classCodes)
    );
    Map<String, Factors> cLastMap = cLast.stream().collect(Collectors.toMap(
      ConfMeasureActuarialAssumption::getClassCode,
      e -> new Factors(nz(e.getRbnpRaFactor()), nz(e.getIbnrRaFactor()), nz(e.getCerRaFactor())),
      (x, y) -> x
    ));

    //整合数据
    Set<String> keys = new HashSet<>();
    keys.addAll(aCurrMap.keySet());
    keys.addAll(bCurrMap.keySet());

    List<MeasureResultCheckLic> out = new ArrayList<>();

    for (String k : keys) {
      String[] p = k.split("\\|");
      String kMonth = p[0], kMethod = p[1], kGroup = p[2];

      CaseAgg aC = aCurrMap.getOrDefault(k, new CaseAgg(BigDecimal.ZERO, BigDecimal.ZERO));
      CaseAgg aL = aLastMap.getOrDefault(key(lastYearMm, kMethod, kGroup), new CaseAgg(BigDecimal.ZERO, BigDecimal.ZERO));
      IbnrAgg bC = bCurrMap.getOrDefault(k, new IbnrAgg(BigDecimal.ZERO,BigDecimal.ZERO,BigDecimal.ZERO,BigDecimal.ZERO));
      IbnrAgg bL = bLastMap.getOrDefault(key(lastYearMm, kMethod, kGroup), new IbnrAgg(BigDecimal.ZERO,BigDecimal.ZERO,BigDecimal.ZERO,BigDecimal.ZERO));

      // 因子
      String cls = grp2Class.get(k);
      Factors fCur = cls == null ? new Factors(BigDecimal.ZERO,BigDecimal.ZERO,BigDecimal.ZERO) : cCurrMap.getOrDefault(cls, new Factors(BigDecimal.ZERO,BigDecimal.ZERO,BigDecimal.ZERO));
      Factors fLst = cls == null ? new Factors(BigDecimal.ZERO,BigDecimal.ZERO,BigDecimal.ZERO) : cLastMap.getOrDefault(cls, new Factors(BigDecimal.ZERO,BigDecimal.ZERO,BigDecimal.ZERO));

      MeasureResultCheckLic r = new MeasureResultCheckLic();
      r.setValMonth(kMonth);
      r.setLastValMonth(lastYearMm);
      r.setValMethod(kMethod);
      r.setGroupId(kGroup);
      r.setIsStatus("1");

      // BOP Curr 初值
      r.setBopRbnpBelCurr(BigDecimal.ZERO);
      r.setBopIbnrBelCurr(BigDecimal.ZERO);
      r.setBopCerBelCurr(BigDecimal.ZERO);
      r.setBopRbnpRaCurr(BigDecimal.ZERO);
      r.setBopIbnrRaCurr(BigDecimal.ZERO);
      r.setBopCerRaCurr(BigDecimal.ZERO);
      r.setBopLicBelIfie(BigDecimal.ZERO);
      r.setBopLicRaIfie(BigDecimal.ZERO);

      // 当期提转（BEL）
      r.setRbnpBelCurrRecg(aC.caseCurr);
      r.setIbnrBelCurrRecg(bC.ibnrCurr);
      r.setCerBelCurrRecg(bC.cerCurr);

      // 当期提转（RA）
      r.setRbnpRaCurrRecg(r.getRbnpBelCurrRecg().multiply(fCur.rR));
      r.setIbnrRaCurrRecg(r.getIbnrBelCurrRecg().multiply(fCur.iR));
      r.setCerRaCurrRecg(r.getCerBelCurrRecg().multiply(fCur.cR));

      // 往期提转差（BEL）
      r.setRbnpBelPrvChg(aC.casePast.subtract(aL.caseCurr.add(aL.casePast)));
      r.setIbnrBelPrvChg(bC.ibnrPast.subtract(bL.ibnrCurr.add(bL.ibnrPast)));
      r.setCerBelPrvChg(bC.cerPast.subtract(bL.cerCurr.add(bL.cerPast)));

      // 往期提转差（RA）
      r.setRbnpRaPrvChg(r.getRbnpBelPrvChg().multiply(fLst.rR));
      r.setIbnrRaPrvChg(r.getIbnrBelPrvChg().multiply(fLst.iR));
      r.setCerRaPrvChg(r.getCerBelPrvChg().multiply(fLst.cR));

      // EOP = BOP + Curr/Prv
      r.setEopRbnpBelCurr(nz(r.getBopRbnpBelCurr()).add(nz(r.getRbnpBelCurrRecg())));
      r.setEopIbnrBelCurr(nz(r.getBopIbnrBelCurr()).add(nz(r.getIbnrBelCurrRecg())));
      r.setEopCerBelCurr(nz(r.getBopCerBelCurr()).add(nz(r.getCerBelCurrRecg())));
      r.setEopRbnpBelPrv(nz(r.getBopRbnpBelPrv()).add(r.getRbnpBelPrvChg()));
      r.setEopIbnrBelPrv(nz(r.getBopIbnrBelPrv()).add(r.getIbnrBelPrvChg()));
      r.setEopCerBelPrv(nz(r.getBopCerBelPrv()).add(r.getCerBelPrvChg()));

      r.setEopRbnpRaCurr(r.getBopRbnpRaCurr().add(r.getRbnpRaCurrRecg()));
      r.setEopIbnrRaCurr(r.getBopIbnrRaCurr().add(r.getIbnrRaCurrRecg())); // 注意这里用 IBNR
      r.setEopCerRaCurr(r.getBopCerRaCurr().add(r.getCerRaCurrRecg()));
      r.setEopRbnpRaPrv(nz(r.getBopRbnpRaPrv()).add(r.getRbnpRaPrvChg()));
      r.setEopIbnrRaPrv(nz(r.getBopIbnrRaPrv()).add(r.getIbnrRaPrvChg()));
      r.setEopCerRaPrv(nz(r.getBopCerRaPrv()).add(r.getCerRaPrvChg()));

      // 若需要把“上期 EOP 回填为本期 BOP(Prev)”，复用你已有的 resultLast 查询逻辑再赋值
      out.add(r);
    }

    // 写库前清理当期
    measureResultCheckLicMapper.delete(new QueryWrapper<MeasureResultCheckLic>().eq("val_month", valMonth).eq("val_method", valMethod));
    return measureResultCheckLicMapper.insertBatch(out)?R.ok():R.fail("lic计量核算插入出现异常了");
  }

  /**
   * 再保分出PAA的LIC计算
   */
  private R<?> setCxMeasureResultCheckLicReout(String valMethod, String valMonth) {
    measureResultCheckLicMapper.delete(new QueryWrapper<MeasureResultCheckLic>().eq("val_month", valMonth).eq("val_method", valMethod));

    String lastYearMm = DateUtils.lastEndYear(valMonth, DateUtils.YYYYMM);

    // A表：再保分出未决（当期/上期）
    List<TPpRiReCaseMon> aCurrList = tPpRiReCaseMonMapper.selectList(
      new QueryWrapper<TPpRiReCaseMon>()
        .eq("val_month", valMonth)
        .select("val_month","val_method","group_id",
          "COALESCE(SUM(case_curr_amount),0) AS case_curr_amount",
          "COALESCE(SUM(case_past_amount),0) AS case_past_amount")
        .groupBy("val_month","val_method","group_id")
    );
    Map<String, CaseAgg> aCurrMap = aCurrList.stream().collect(Collectors.toMap(
      e -> key(valMonth, e.getValMethod(), e.getGroupId()),
      e -> new CaseAgg(nz(e.getCaseCurrAmount()), nz(e.getCasePastAmount()))
    ));

    List<TPpRiReCaseMon> aLastList = tPpRiReCaseMonMapper.selectList(
      new QueryWrapper<TPpRiReCaseMon>()
        .eq("val_month", lastYearMm)
        .select("val_month","val_method","group_id",
          "COALESCE(SUM(case_curr_amount),0) AS case_curr_amount",
          "COALESCE(SUM(case_past_amount),0) AS case_past_amount")
        .groupBy("val_month","val_method","group_id")
    );
    Map<String, CaseAgg> aLastMap = aLastList.stream().collect(Collectors.toMap(
      e -> key(lastYearMm, e.getValMethod(), e.getGroupId()),
      e -> new CaseAgg(nz(e.getCaseCurrAmount()), nz(e.getCasePastAmount()))
    ));

    // B表：再保分出 IBNR
    // 说明：优先使用准备落地表 t_pp_ibnr_rein_out（已含 val_month/val_method/group_id 字段，避免实体缺字段导致编译失败）；
    // 后续如需切至 BI 表 ri_ibnr_rein_out，可将此段改为 selectReIbnrFromBi 并补充实体字段。
    List<TPpIbnrReinOut> bCurrList = tPpIbnrReinOutMapper.selectList(
      new QueryWrapper<TPpIbnrReinOut>()
        .eq("val_month", valMonth)
        .select("val_month","val_method","group_id",
          "COALESCE(SUM(ibnr_curr_before_pi),0) AS ibnr_curr_before_pi",
          "COALESCE(SUM(ibnr_past_before_pi),0) AS ibnr_past_before_pi")
        .groupBy("val_month","val_method","group_id")
    );
    Map<String, IbnrAgg> bCurrMap = bCurrList.stream().collect(Collectors.toMap(
      e -> key(e.getValMonth(), e.getValMethod(), e.getGroupId()),
      e -> new IbnrAgg(nz(e.getIbnrCurrBeforePi()), nz(e.getIbnrPastBeforePi()), BigDecimal.ZERO, BigDecimal.ZERO)
    ));

    List<TPpIbnrReinOut> bLastList = tPpIbnrReinOutMapper.selectList(
      new QueryWrapper<TPpIbnrReinOut>()
        .eq("val_month", lastYearMm)
        .select("val_month","val_method","group_id",
          "COALESCE(SUM(ibnr_curr_before_pi),0) AS ibnr_curr_before_pi",
          "COALESCE(SUM(ibnr_past_before_pi),0) AS ibnr_past_before_pi")
        .groupBy("val_month","val_method","group_id")
    );
    Map<String, IbnrAgg> bLastMap = bLastList.stream().collect(Collectors.toMap(
      e -> key(e.getValMonth(), e.getValMethod(), e.getGroupId()),
      e -> new IbnrAgg(nz(e.getIbnrCurrBeforePi()), nz(e.getIbnrPastBeforePi()), BigDecimal.ZERO, BigDecimal.ZERO)
    ));

    // 因子C：取当期A表的 class_code -> 精算假设
    List<TPpRiReCaseMon> aClass = tPpRiReCaseMonMapper.selectList(
      new QueryWrapper<TPpRiReCaseMon>().eq("val_month", valMonth)
        .select("val_month","val_method","group_id","class_code").groupBy("val_month","val_method","group_id","class_code")
    );
    Map<String, String> grp2Class = aClass.stream().collect(Collectors.toMap(
      e -> key(e.getValMonth(), e.getValMethod(), e.getGroupId()),
      TPpRiReCaseMon::getClassCode,
      (x,y) -> x
    ));
    Set<String> classCodes = new HashSet<>(grp2Class.values());
    List<ConfMeasureActuarialAssumption> cCurr = classCodes.isEmpty()?Collections.emptyList():confMeasureActuarialAssumptionMapper.selectList(
      new QueryWrapper<ConfMeasureActuarialAssumption>().eq("val_month", valMonth).in("class_code", classCodes)
    );
    Map<String, Factors> cCurrMap = cCurr.stream().collect(Collectors.toMap(
      ConfMeasureActuarialAssumption::getClassCode,
      e -> new Factors(nz(e.getRbnpRaFactor()), nz(e.getIbnrRaFactor()), nz(e.getCerRaFactor())),
      (x, y) -> x
    ));
    List<ConfMeasureActuarialAssumption> cLast = classCodes.isEmpty()?Collections.emptyList():confMeasureActuarialAssumptionMapper.selectList(
      new QueryWrapper<ConfMeasureActuarialAssumption>().eq("val_month", lastYearMm).in("class_code", classCodes)
    );
    Map<String, Factors> cLastMap = cLast.stream().collect(Collectors.toMap(
      ConfMeasureActuarialAssumption::getClassCode,
      e -> new Factors(nz(e.getRbnpRaFactor()), nz(e.getIbnrRaFactor()), nz(e.getCerRaFactor())),
      (x, y) -> x
    ));

    // 汇总
    Set<String> keys = new HashSet<>();
    keys.addAll(aCurrMap.keySet());
    keys.addAll(bCurrMap.keySet());

    // 获取上期数据用于设置本期期初值
    List<MeasureResultCheckLic> lastPeriodList = measureResultCheckLicMapper.selectList(
      new QueryWrapper<MeasureResultCheckLic>().eq("val_month", lastYearMm).eq("val_method", valMethod)
    );
    Map<String, MeasureResultCheckLic> lastPeriodMap = lastPeriodList.stream().collect(Collectors.toMap(
      e -> key(lastYearMm, e.getValMethod(), e.getGroupId()),
      e -> e,
      (x, y) -> x
    ));

    List<MeasureResultCheckLic> out = new ArrayList<>();
    for (String k : keys) {
      String[] p = k.split("\\|");
      String kMonth = p[0], kMethod = p[1], kGroup = p[2];
      CaseAgg aC = aCurrMap.getOrDefault(k, new CaseAgg(BigDecimal.ZERO, BigDecimal.ZERO));
      CaseAgg aL = aLastMap.getOrDefault(key(lastYearMm, kMethod, kGroup), new CaseAgg(BigDecimal.ZERO, BigDecimal.ZERO));
      IbnrAgg bC = bCurrMap.getOrDefault(k, new IbnrAgg(BigDecimal.ZERO,BigDecimal.ZERO,BigDecimal.ZERO,BigDecimal.ZERO));
      IbnrAgg bL = bLastMap.getOrDefault(key(lastYearMm, kMethod, kGroup), new IbnrAgg(BigDecimal.ZERO,BigDecimal.ZERO,BigDecimal.ZERO,BigDecimal.ZERO));

      String cls = grp2Class.get(k);
      Factors fCur = cls == null ? new Factors(BigDecimal.ZERO,BigDecimal.ZERO,BigDecimal.ZERO) : cCurrMap.getOrDefault(cls, new Factors(BigDecimal.ZERO,BigDecimal.ZERO,BigDecimal.ZERO));
      Factors fLst = cls == null ? new Factors(BigDecimal.ZERO,BigDecimal.ZERO,BigDecimal.ZERO) : cLastMap.getOrDefault(cls, new Factors(BigDecimal.ZERO,BigDecimal.ZERO,BigDecimal.ZERO));

      MeasureResultCheckLic r = new MeasureResultCheckLic();
      r.setValMonth(kMonth);
      r.setLastValMonth(lastYearMm);
      r.setValMethod(kMethod);
      r.setGroupId(kGroup);
      r.setClassCode(cls);
      r.setIsStatus("1");

      r.setBopRbnpBelCurr(BigDecimal.ZERO);
      r.setBopIbnrBelCurr(BigDecimal.ZERO);
      r.setBopRbnpRaCurr(BigDecimal.ZERO);
      r.setBopIbnrRaCurr(BigDecimal.ZERO);
      r.setBopLicBelIfie(BigDecimal.ZERO);
      r.setBopLicRaIfie(BigDecimal.ZERO);
      r.setLicBelIfie(BigDecimal.ZERO);
      r.setLicRaIfie(BigDecimal.ZERO);

      r.setRbnpBelCurrRecg(aC.caseCurr);
      r.setIbnrBelCurrRecg(bC.ibnrCurr);
      r.setCerBelCurrRecg(bC.cerCurr);

      MeasureResultCheckLic lastPeriod = lastPeriodMap.get(key(lastYearMm, kMethod, kGroup));
      if(lastPeriod != null){
        r.setBopRbnpBelPrv(nz(lastPeriod.getBopRbnpBelCurr()).add(nz(lastPeriod.getEopRbnpBelPrv())));
        r.setBopIbnrBelPrv(nz(lastPeriod.getBopIbnrBelCurr()).add(nz(lastPeriod.getEopIbnrBelPrv())));
        r.setBopRbnpRaPrv(nz(lastPeriod.getBopRbnpRaCurr()).add(nz(lastPeriod.getEopRbnpRaPrv())));
        r.setBopIbnrRaPrv(nz(lastPeriod.getBopIbnrRaCurr()).add(nz(lastPeriod.getEopRbnpRaPrv())));
      }

      r.setRbnpRaCurrRecg(r.getRbnpBelCurrRecg().multiply(fCur.rR));
      r.setIbnrRaCurrRecg(r.getIbnrBelCurrRecg().multiply(fCur.iR));
      r.setCerRaCurrRecg(r.getCerBelCurrRecg().multiply(fCur.cR));

      r.setRbnpBelPrvChg(aC.casePast.subtract(aL.caseCurr.add(aL.casePast)));
      r.setIbnrBelPrvChg(bC.ibnrPast.subtract(bL.ibnrCurr.add(bL.ibnrPast)));
      r.setCerBelPrvChg(bC.cerPast.subtract(bL.cerCurr.add(bL.cerPast)));

      r.setRbnpRaPrvChg(r.getRbnpBelPrvChg().multiply(fLst.rR));
      r.setIbnrRaPrvChg(r.getIbnrBelPrvChg().multiply(fLst.iR));
      r.setCerRaPrvChg(r.getCerBelPrvChg().multiply(fLst.cR));

      r.setEopRbnpBelCurr(nz(r.getBopRbnpBelCurr()).add(nz(r.getRbnpBelCurrRecg())));
      r.setEopIbnrBelCurr(nz(r.getBopIbnrBelCurr()).add(nz(r.getIbnrBelCurrRecg())));
      r.setEopRbnpBelPrv(nz(r.getBopRbnpBelPrv()).add(nz(r.getRbnpBelPrvChg())));
      r.setEopIbnrBelPrv(nz(r.getBopIbnrBelPrv()).add(nz(r.getIbnrBelPrvChg())));
      r.setEopCerBelCurr(nz(r.getBopCerBelCurr()).add(nz(r.getCerBelCurrRecg())));
      r.setEopCerBelPrv(nz(r.getBopCerBelPrv()).add(nz(r.getCerBelPrvChg())));

      r.setEopRbnpRaCurr(nz(r.getBopRbnpRaCurr()).add(nz(r.getRbnpRaCurrRecg())));
      r.setEopIbnrRaCurr(nz(r.getBopIbnrRaCurr()).add(nz(r.getIbnrRaCurrRecg())));
      r.setEopCerRaCurr(nz(r.getBopCerRaCurr()).add(nz(r.getCerRaCurrRecg())));
      r.setEopRbnpRaPrv(nz(r.getBopRbnpRaPrv()).add(nz(r.getRbnpRaPrvChg())));
      r.setEopIbnrRaPrv(nz(r.getBopIbnrRaPrv()).add(nz(r.getIbnrRaPrvChg())));
      r.setEopCerRaPrv(nz(r.getBopCerRaPrv()).add(nz(r.getCerRaPrvChg())));
      r.setEopLicBelIfie(nz(r.getEopLicBelIfie()).add(nz(r.getLicBelIfie())));
      r.setEopLicRaIfie(nz(r.getEopLicRaIfie()).add(nz(r.getLicRaIfie())));

      out.add(r);
    }

    measureResultCheckLicMapper.delete(new QueryWrapper<MeasureResultCheckLic>().eq("val_month", valMonth).eq("val_method", valMethod));
    return measureResultCheckLicMapper.insertBatch(out)?R.ok():R.fail("lic计量核算(再保分出)插入出现异常了");
  }

  /**
   * 再保分入PAA的LIC计算
   */
  private R<?> setCxMeasureResultCheckLicRein(String valMethod, String valMonth) {
    measureResultCheckLicMapper.delete(new QueryWrapper<MeasureResultCheckLic>().eq("val_month", valMonth).eq("val_method", valMethod));

    String lastYearMm = DateUtils.lastEndYear(valMonth, DateUtils.YYYYMM);
    // A表：再保分入未决（当期/上期）
    List<TPpRiReCaseMonIn> aCurrList = tPpRiReCaseMonInMapper.selectList(
      new QueryWrapper<TPpRiReCaseMonIn>()
        .eq("val_month", valMonth)
        .select("val_month","val_method","group_id",
          "COALESCE(SUM(case_curr_cny),0) AS case_curr_cny",
          "COALESCE(SUM(case_past_cny),0) AS case_past_cny")
        .groupBy("val_month","val_method","group_id")
    );
    Map<String, CaseAgg> aCurrMap = aCurrList.stream().collect(Collectors.toMap(
      e -> key(valMonth, e.getValMethod(), e.getGroupId()),
      e -> new CaseAgg(nz(e.getCaseCurrCny()), nz(e.getCasePastCny()))
    ));
    List<TPpRiReCaseMonIn> aLastList = tPpRiReCaseMonInMapper.selectList(
      new QueryWrapper<TPpRiReCaseMonIn>()
        .eq("val_month", lastYearMm)
        .select("val_month","val_method","group_id",
          "COALESCE(SUM(case_curr_cny),0) AS case_curr_cny",
          "COALESCE(SUM(case_past_cny),0) AS case_past_cny")
        .groupBy("val_month","val_method","group_id")
    );
    Map<String, CaseAgg> aLastMap = aLastList.stream().collect(Collectors.toMap(
      e -> key(lastYearMm, e.getValMethod(), e.getGroupId()),
      e -> new CaseAgg(nz(e.getCaseCurrCny()), nz(e.getCasePastCny()))
    ));

    // B表：再保分入 IBNR（当期/上期）
    List<TPpIbnrReinIn> bCurrList = tPpIbnrReinInMapper.selectList(
      new QueryWrapper<TPpIbnrReinIn>()
        .eq("val_month", valMonth)
        .select("val_month","val_method","group_id",
          "COALESCE(SUM(ibnr_curr_before_pi),0) AS ibnr_curr_before_pi",
          "COALESCE(SUM(ibnr_past_before_pi),0) AS ibnr_past_before_pi")
        .groupBy("val_month","val_method","group_id")
    );
    Map<String, IbnrAgg> bCurrMap = bCurrList.stream().collect(Collectors.toMap(
      e -> key(e.getValMonth(), e.getValMethod(), e.getGroupId()),
      e -> new IbnrAgg(nz(e.getIbnrCurrBeforePi()), nz(e.getIbnrPastBeforePi()), BigDecimal.ZERO, BigDecimal.ZERO)
    ));
    List<TPpIbnrReinIn> bLastList = tPpIbnrReinInMapper.selectList(
      new QueryWrapper<TPpIbnrReinIn>()
        .eq("val_month", lastYearMm)
        .select("val_month","val_method","group_id",
          "COALESCE(SUM(ibnr_curr_before_pi),0) AS ibnr_curr_before_pi",
          "COALESCE(SUM(ibnr_past_before_pi),0) AS ibnr_past_before_pi")
        .groupBy("val_month","val_method","group_id")
    );
    Map<String, IbnrAgg> bLastMap = bLastList.stream().collect(Collectors.toMap(
      e -> key(e.getValMonth(), e.getValMethod(), e.getGroupId()),
      e -> new IbnrAgg(nz(e.getIbnrCurrBeforePi()), nz(e.getIbnrPastBeforePi()), BigDecimal.ZERO, BigDecimal.ZERO)
    ));

    // 因子C：按当期A表获取 class_code（每个分组一条，避免同组多class_code导致取值不稳定）
    List<TPpRiReCaseMonIn> aClass = tPpRiReCaseMonInMapper.selectList(
      new QueryWrapper<TPpRiReCaseMonIn>().eq("val_month", valMonth)
        .select("val_month","val_method","group_id","MAX(class_code) AS class_code").groupBy("val_month","val_method","group_id")
    );
    Map<String, String> grp2Class = aClass.stream().collect(Collectors.toMap(
      e -> key(e.getValMonth(), e.getValMethod(), e.getGroupId()),
      TPpRiReCaseMonIn::getClassCode,
      (x,y) -> x
    ));
    Set<String> classCodes = new HashSet<>(grp2Class.values());
    List<ConfMeasureActuarialAssumption> cCurr = classCodes.isEmpty()?Collections.emptyList():confMeasureActuarialAssumptionMapper.selectList(
      new QueryWrapper<ConfMeasureActuarialAssumption>().eq("val_month", valMonth).in("class_code", classCodes)
    );
    Map<String, Factors> cCurrMap = cCurr.stream().collect(Collectors.toMap(
      ConfMeasureActuarialAssumption::getClassCode,
      e -> new Factors(nz(e.getRbnpRaFactor()), nz(e.getIbnrRaFactor()), nz(e.getCerRaFactor())),
      (x, y) -> x
    ));
    List<ConfMeasureActuarialAssumption> cLast = classCodes.isEmpty()?Collections.emptyList():confMeasureActuarialAssumptionMapper.selectList(
      new QueryWrapper<ConfMeasureActuarialAssumption>().eq("val_month", lastYearMm).in("class_code", classCodes)
    );
    Map<String, Factors> cLastMap = cLast.stream().collect(Collectors.toMap(
      ConfMeasureActuarialAssumption::getClassCode,
      e -> new Factors(nz(e.getRbnpRaFactor()), nz(e.getIbnrRaFactor()), nz(e.getCerRaFactor())),
      (x, y) -> x
    ));

    Set<String> keys = new HashSet<>();
    keys.addAll(aCurrMap.keySet());
    keys.addAll(bCurrMap.keySet());
    // 获取上期数据用于设置本期期初值
    List<MeasureResultCheckLic> lastPeriodList = measureResultCheckLicMapper.selectList(
      new QueryWrapper<MeasureResultCheckLic>().eq("val_month", lastYearMm).eq("val_method", valMethod)
    );
    Map<String, MeasureResultCheckLic> lastPeriodMap = lastPeriodList.stream().collect(Collectors.toMap(
      e -> key(lastYearMm, e.getValMethod(), e.getGroupId()),
      e -> e,
      (x, y) -> x
    ));

    List<MeasureResultCheckLic> out = new ArrayList<>();
    for (String k : keys) {
      String[] p = k.split("\\|");
      String kMonth = p[0], kMethod = p[1], kGroup = p[2];
      CaseAgg aC = aCurrMap.getOrDefault(k, new CaseAgg(BigDecimal.ZERO, BigDecimal.ZERO));
      CaseAgg aL = aLastMap.getOrDefault(key(lastYearMm, kMethod, kGroup), new CaseAgg(BigDecimal.ZERO, BigDecimal.ZERO));
      IbnrAgg bC = bCurrMap.getOrDefault(k, new IbnrAgg(BigDecimal.ZERO,BigDecimal.ZERO,BigDecimal.ZERO,BigDecimal.ZERO));
      IbnrAgg bL = bLastMap.getOrDefault(key(lastYearMm, kMethod, kGroup), new IbnrAgg(BigDecimal.ZERO,BigDecimal.ZERO,BigDecimal.ZERO,BigDecimal.ZERO));

      String cls = grp2Class.get(k);
      if (cls == null) {
        // 当期A表无class_code时，回退用上期记录的classCode（若存在）
        MeasureResultCheckLic lp = lastPeriodMap.get(key(lastYearMm, kMethod, kGroup));
        cls = lp == null ? null : lp.getClassCode();
      }
      Factors fCur = cls == null ? new Factors(BigDecimal.ZERO,BigDecimal.ZERO,BigDecimal.ZERO) : cCurrMap.getOrDefault(cls, new Factors(BigDecimal.ZERO,BigDecimal.ZERO,BigDecimal.ZERO));
      Factors fLst = cls == null ? new Factors(BigDecimal.ZERO,BigDecimal.ZERO,BigDecimal.ZERO) : cLastMap.getOrDefault(cls, new Factors(BigDecimal.ZERO,BigDecimal.ZERO,BigDecimal.ZERO));

      MeasureResultCheckLic r = new MeasureResultCheckLic();
      r.setValMonth(kMonth);
      r.setLastValMonth(lastYearMm);
      r.setValMethod(kMethod);
      r.setGroupId(kGroup);
      r.setClassCode(cls);
      r.setIsStatus("1");

      MeasureResultCheckLic lastPeriod = lastPeriodMap.get(key(lastYearMm, kMethod, kGroup));
      r.setBopRbnpBelCurr(BigDecimal.ZERO);
      r.setBopIbnrBelCurr(BigDecimal.ZERO);
      r.setBopCerBelCurr(BigDecimal.ZERO);
      r.setBopRbnpBelPrv(lastPeriod != null ? lastPeriod.getEopRbnpBelPrv() : BigDecimal.ZERO);
      r.setBopIbnrBelPrv(lastPeriod != null ? lastPeriod.getEopIbnrBelPrv() : BigDecimal.ZERO);
      r.setBopCerBelPrv(lastPeriod != null ? lastPeriod.getEopCerBelPrv() : BigDecimal.ZERO);
      r.setBopRbnpRaCurr(BigDecimal.ZERO);
      r.setBopIbnrRaCurr(BigDecimal.ZERO);
      r.setBopCerRaCurr(BigDecimal.ZERO);
      r.setBopRbnpRaPrv(lastPeriod != null ? lastPeriod.getEopRbnpRaPrv() : BigDecimal.ZERO);
      r.setBopIbnrRaPrv(lastPeriod != null ? lastPeriod.getEopIbnrRaPrv() : BigDecimal.ZERO);
      r.setBopCerRaPrv(lastPeriod != null ? lastPeriod.getEopCerRaPrv() : BigDecimal.ZERO);
      r.setBopLicBelIfie(BigDecimal.ZERO);
      r.setBopLicRaIfie(BigDecimal.ZERO);
      r.setLicBelIfie(BigDecimal.ZERO);
      r.setLicRaIfie(BigDecimal.ZERO);



      r.setRbnpBelCurrRecg(aC.caseCurr);
      r.setIbnrBelCurrRecg(bC.ibnrCurr);
      r.setCerBelCurrRecg(bC.cerCurr);

      r.setRbnpRaCurrRecg(aC.caseCurr.multiply(fCur.rR));
      r.setIbnrRaCurrRecg(bC.ibnrCurr.multiply(fCur.iR));
      r.setCerRaCurrRecg(bC.cerCurr.multiply(fCur.cR));

      r.setRbnpBelPrvChg(aC.casePast.subtract(aL.caseCurr.add(aL.casePast)));
      r.setIbnrBelPrvChg(bC.ibnrPast.subtract(bL.ibnrCurr.add(bL.ibnrPast)));
      r.setCerBelPrvChg(bC.cerPast.subtract(bL.cerCurr.add(bL.cerPast)));

      r.setRbnpRaPrvChg(aC.casePast.subtract((aL.caseCurr.add(aL.casePast)).multiply(fCur.rR)));
      r.setIbnrRaPrvChg(bC.ibnrPast.subtract((bL.ibnrCurr.add(bL.ibnrPast)).multiply(fCur.iR)));
      r.setCerRaPrvChg(bC.cerPast.subtract((bL.cerCurr.add(bL.cerPast))).multiply(fCur.cR));

      r.setEopRbnpBelCurr(nz(r.getBopRbnpBelCurr()).add(nz(r.getRbnpBelCurrRecg())));
      r.setEopIbnrBelCurr(nz(r.getBopIbnrBelCurr()).add(nz(r.getIbnrBelCurrRecg())));
      r.setEopCerBelCurr(nz(r.getBopCerBelCurr()).add(nz(r.getCerBelCurrRecg())));
      r.setEopRbnpBelPrv(nz(r.getBopRbnpBelPrv()).add(nz(r.getRbnpBelPrvChg())));
      r.setEopIbnrBelPrv(nz(r.getBopIbnrBelPrv()).add(nz(r.getIbnrBelPrvChg())));
      r.setEopCerBelPrv(nz(r.getBopCerBelPrv()).add(nz(r.getCerBelPrvChg())));

      r.setEopRbnpRaCurr(nz(r.getBopRbnpRaCurr()).add(nz(r.getRbnpRaCurrRecg())));
      r.setEopIbnrRaCurr(nz(r.getBopIbnrRaCurr()).add(nz(r.getIbnrRaCurrRecg())));
      r.setEopCerRaCurr(nz(r.getBopCerRaCurr()).add(nz(r.getCerRaCurrRecg())));
      r.setEopRbnpRaPrv(nz(r.getBopRbnpRaPrv()).add(nz(r.getRbnpRaPrvChg())));
      r.setEopIbnrRaPrv(nz(r.getBopIbnrRaPrv()).add(nz(r.getIbnrRaPrvChg())));
      r.setEopCerRaPrv(nz(r.getBopCerRaPrv()).add(nz(r.getCerRaPrvChg())));
      r.setEopLicBelIfie(nz(r.getEopLicBelIfie()).add(nz(r.getLicBelIfie())));
      r.setEopLicRaIfie(nz(r.getEopLicRaIfie()).add(nz(r.getLicRaIfie())));

      out.add(r);
    }

    measureResultCheckLicMapper.delete(new QueryWrapper<MeasureResultCheckLic>().eq("val_month", valMonth).eq("val_method", valMethod));
    return measureResultCheckLicMapper.insertBatch(out)?R.ok():R.fail("lic计量核算(再保分入)插入失败");
  }
  /**
   * 将计量明细转成通用预期现金流表格式，用于计算计量分录
   *
   * @param evaluateMethod 评估方法.
   * @param valMonth       评估月.
   */
  private List<MeasureCfBasicExpRst> getMeasureCfBasicExpRstOne(String evaluateMethod, String valMonth) {
    List<Map<String, Object>> measureCfResultInfoParams = Lists.newArrayList();
    if (EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_10.equals(EvaluateMethodTypeEnum.getEnumType(evaluateMethod))) {
      //分组查询计量明细匹配利率配置表、精算假设配置表，计算指定金额的利息、ra因子 以及分组汇总后的各金额
      measureCfResultInfoParams = measureCfResultInfoMapper.getMeasureCfResultInfoReinType(valMonth, evaluateMethod);
    } else {
      //分组查询计量明细分组汇总后的各金额
      measureCfResultInfoParams = measureCfResultInfoMapper.getMeasureCfResultInfointerestRate(valMonth, evaluateMethod);
    }
    //转换到预期现金流表
    List<MeasureCfBasicExpRst> measureCfBasicExpRst = Lists.newArrayList();
    Optional.ofNullable(measureCfResultInfoParams).orElse(Lists.newArrayList()).forEach(map -> {
      map.forEach((k, v) -> {
        if (v instanceof BigDecimal) {
          MeasureCfBasicExpRst mcExp = new MeasureCfBasicExpRst();
          //当期评估月(yyyymm)
          mcExp.setValMonth(valMonth);
          //合同分组编号(长) = 再保险合同组编号
          mcExp.setGroupId((String) Optional.ofNullable(map.get(ReflectUtils.getFieldName(MeasureCfBasicExpRst::getGroupId))).orElse(StringConstant.STRING_NA));
          //合同组合编号(短) = 再保险合同组合编号
          mcExp.setPortfolioId((String) Optional.ofNullable(map.get(ReflectUtils.getFieldName(MeasureCfBasicExpRst::getPortfolioId))).orElse(StringConstant.STRING_NA));
          //归属机构
          mcExp.setComCode((String) Optional.ofNullable(map.get(ReflectUtils.getFieldName(MeasureCfBasicExpRst::getComCode))).orElse(StringConstant.STRING_NA));
          //车辆种类
          mcExp.setCarKindCode((String) Optional.ofNullable(map.get(ReflectUtils.getFieldName(MeasureCfBasicExpRst::getCarKindCode))).orElse(StringConstant.STRING_NA));
          //使用性质代码
          mcExp.setUseNatureCode((String) Optional.ofNullable(map.get(ReflectUtils.getFieldName(MeasureCfBasicExpRst::getUseNatureCode))).orElse(StringConstant.STRING_NA));
          mcExp.setBusinessNature((String) Optional.ofNullable(map.get(ReflectUtils.getFieldName(MeasureCfBasicExpRst::getBusinessNature))).orElse(StringConstant.STRING_NA));
          mcExp.setCoverageSegment(StringConstant.STRING_NA);
          mcExp.setRiskCode((String) Optional.ofNullable(map.get(ReflectUtils.getFieldName(MeasureCfBasicExpRst::getRiskCode))).orElse(StringConstant.STRING_NA));

          //评估方法
          mcExp.setValMethod(evaluateMethod);
          //合同分组编码
          String groupId = String.valueOf(map.get(ReflectUtils.getFieldName(MeasureCfBasicExpRst::getGroupId)));
          //盈亏水平
          mcExp.setProfitLevel(subProfitLevel(mcExp.getGroupId()));
          //币种 = 默认给CNY
          mcExp.setCurrency(CurrencyTypeEnum.CURRENCY_TYPE_CNY.getCode());
          mcExp.setIsStatus(DataStateTypeEnum.DATA_STATE_TYPE_2.getCode());
          mcExp.setVar(StrUtil.toUnderlineCase(k).toUpperCase());
          mcExp.setVarAmt(Optional.of((BigDecimal) v).orElse(BigDecimal.ZERO));
          measureCfBasicExpRst.add(mcExp);
        }
      });
    });
    return measureCfBasicExpRst;
  }

  /**
   * 获取汇总数据.
   *
   * @param evaluateMethod 评估方法.
   * @param valMonth       评估月.
   * @return list
   */
  @SuppressWarnings("unchecked")
  private List<MeasureCfBasicExpRst> getMeasureCfBasicExpRstTwo(String evaluateMethod, String valMonth) {

    //1.定义sum部分
    SqlFunctionUtil<MeasureCfResultInfo> tPpJlCaseSqlFunctionUtil = new SqlFunctionUtil<>();
    String sumString = tPpJlCaseSqlFunctionUtil.getSumParamSql(
      ImmutableMap.<String, SFunction<MeasureCfResultInfo, ?>>builder()
        ////未到期责任负债-亏损部分_期初 = 未到期责任负债_亏损
        .put("init_pv_bel_adj", MeasureCfResultInfo::getLrcLcAmt)
        //非金融风险调整_期末
        .put("init_lrc_lc_amt_adj", MeasureCfResultInfo::getLrcLcAmt).build()
    );

    //2..定义分组数据
    String groupString = tPpJlCaseSqlFunctionUtil.getParamSql(
      //合同分组编号
      MeasureCfResultInfo::getGroupId,
      //合同组合编号
      MeasureCfResultInfo::getPortfolioId,
      //评估方法
      MeasureCfResultInfo::getValMethod);

    //3.获取 分组汇总
    QueryWrapper<MeasureCfResultInfo> lqw = new QueryWrapper<>();
    lqw.select(Lists.newArrayList(Lists.newArrayList(sumString, groupString)));
    //条件1：评估月 <= 当前评估月
    lqw.eq(tPpJlCaseSqlFunctionUtil.getParamSql(MeasureCfResultInfo::getValMonth), valMonth);
    //条件2：评估方法
    lqw.eq(tPpJlCaseSqlFunctionUtil.getParamSql(MeasureCfResultInfo::getValMethod), evaluateMethod);
    //条件3：初始确认年月 = 评估月
    lqw.last(String.format("%s = %s", tPpJlCaseSqlFunctionUtil.getParamSql(MeasureCfResultInfo::getInitCfm),
      tPpJlCaseSqlFunctionUtil.getParamSql(MeasureCfResultInfo::getValMonth)));
    lqw.groupBy(groupString);
    List<MeasureCfResultInfo> measureCfResultInfoList = measureCfResultInfoMapper.selectList(lqw);

    //4. 转换 到实际现金流
    List<MeasureCfBasicExpRst> measureCfBasicExpRst = Lists.newArrayList();
    Optional.ofNullable(measureCfResultInfoList).orElse(Lists.newArrayList()).forEach(e -> {
      Map<String, Object> beamMap = BeanUtil.beanToMap(e);
      List<MeasureCfBasicExpRst> measureCfBasicCalcRsts = getMeasureCfBasicExpRsts(evaluateMethod, valMonth,
        e.getGroupId(), e.getPortfolioId(), beamMap);
      measureCfBasicExpRst.addAll(measureCfBasicCalcRsts);
    });
    return measureCfBasicExpRst;
  }


}
