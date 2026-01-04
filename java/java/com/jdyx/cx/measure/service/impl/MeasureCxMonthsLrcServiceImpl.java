package com.jdyx.cx.measure.service.impl;

import cn.hutool.core.bean.BeanUtil;
import com.alibaba.fastjson2.JSON;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.baomidou.mybatisplus.core.toolkit.support.SFunction;
import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import com.jdyx.cx.measure.service.MeasureCxMonthsLrcService;
import com.jdyx.measure.api.measure.domain.*;
import com.jdyx.measure.api.measure.mapper.*;
import com.kevin.common.core.domain.R;
import com.kevin.common.utils.DateUtils;
import com.kevin.common.utils.StringUtils;
import com.kevin.common.utils.reflect.ReflectUtils;
import com.kevin.common.utils.sql.SqlFunctionUtil;
import com.kevin.common.utils.uuid.IdUtils;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.BatchPreparedStatementSetter;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.util.CollectionUtils;

import javax.annotation.Resource;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Collectors;

/**
 * LRC计量服务实现类
 * 基于Python版本的LRC计算逻辑转换为Java实现
 *
 * @author 陈佳能
 * 日期：2025/7/22 17:50
 */
@Slf4j
@RequiredArgsConstructor
@Service
public class MeasureCxMonthsLrcServiceImpl implements MeasureCxMonthsLrcService {

  @Resource
  private MeasureCfBasicDataNewMapper measureCfBasicDataNewMapper;
  @Resource
  private ConfMeasureActuarialAssumptionMapper confMeasureActuarialAssumptionMapper;
  @Resource
  private ConfMeasureClaimModelNewMapper measureClaimModelNewMapper;
  @Resource
  private MeasureCxUnexpiredMapper measureCxUnexpiredMapper;
  @Resource
  private ConfMeasureMonthDisrateMapper measureMonthDisrateMapper;

  @Autowired
  private JdbcTemplate jdbcTemplate;
  // 分批批次量
  private static final int BATCH_SIZE = 100000;
  //TODO 假设的投资成分占比，暂时不考虑投资成分
  private static final BigDecimal INVESTMENT_RATIO = new BigDecimal(0);
  //计息默认按月中
  private static final BigDecimal IFIE_RATIO = new BigDecimal(0.5);

  @Autowired
  private TransactionTemplate transactionTemplate;

  /**
   * 定义全局上下文，用于缓存计算过程中的中间结果
   */
  @lombok.Data
  public class MeasureContext {
    //赔付模式进展因子缓存对象
    private Map<String, BigDecimal[]> discountFactorCache;
    //精算假设缓存对象
    private Map<String, Map<String, ConfMeasureActuarialAssumption>> assumptionCache;
    //月利率缓存对象
    private Map<String, Map<Integer, BigDecimal>> disRateCache;
    //上个评估月未到期计量缓存对象
    private Map<String, Map<String, BigDecimal>> lastMeasureCxUnexpiredCache;
  }


  @Override
  public R<?> getUnexpiredMeasureResult(String valMethod, String valMonth) {
    try {
      log.info("开始LRC计量计算，评估方法: {}, 评估月份: {}", valMethod, valMonth);
      long startTime = System.currentTimeMillis();

      // 1. 预加载缓存数据
      MeasureContext context = preloadCacheData(valMethod, valMonth);
      log.info("缓存预加载完成，耗时: {} 秒", (System.currentTimeMillis() - startTime) / 1000);

      // 2. 使用游标分页
      processDataWithCursorPagination(valMethod, valMonth, context);

      // 3. 汇总结果
      log.info("LRC计量计算完成，总耗时: {} 秒", (System.currentTimeMillis() - startTime) / 1000);
      return R.ok();
    } catch (Exception e) {
      log.error("LRC计量计算失败", e);
      return R.fail("LRC计量计算失败: " + e.getMessage());
    }
  }

  /**
   * 预加载缓存数据
   */
  private MeasureContext preloadCacheData(String valMethod, String valMonth) {
    // 初始化缓存对象
    MeasureContext context = new MeasureContext();
    // 1. 预加载精算假设数据到缓存
    LambdaQueryWrapper<ConfMeasureActuarialAssumption> assumptionQuery = Wrappers.lambdaQuery();
    assumptionQuery.eq(ConfMeasureActuarialAssumption::getValMethod, valMethod);
    List<ConfMeasureActuarialAssumption> assumptions = confMeasureActuarialAssumptionMapper.selectList(assumptionQuery);
    Map<String, Map<String, ConfMeasureActuarialAssumption>> collect =
      assumptions.stream()
        .collect(Collectors.groupingBy(
          ConfMeasureActuarialAssumption::getValMonth,  // 外层 key: valMonth
          Collectors.toMap(
            ConfMeasureActuarialAssumption::getClassCode,  // 内层 key: classCode
            assumption -> assumption,  // value: 对象本身
            (existing, replacement) -> existing  // 冲突时保留现有值
          )
        ));

    // 2. 预加载赔付模式数据到缓存
    Map<String, BigDecimal[]> claimModelMap = new HashMap<>();
    LambdaQueryWrapper<ConfMeasureClaimModelNew> claimModelQuery = Wrappers.lambdaQuery();
    claimModelQuery.orderByAsc(ConfMeasureClaimModelNew::getMonthId);
    List<ConfMeasureClaimModelNew> claimModels = measureClaimModelNewMapper.selectList(claimModelQuery);

    // 按 classCode 分组，并提取每个 classCode 对应的 paidRatio 数组
    Map<String, List<ConfMeasureClaimModelNew>> groupedByClass = claimModels.stream()
      .collect(Collectors.groupingBy(ConfMeasureClaimModelNew::getClassCode));

    for (Map.Entry<String, List<ConfMeasureClaimModelNew>> entry : groupedByClass.entrySet()) {
      String classCode = entry.getKey();
      List<ConfMeasureClaimModelNew> modelsInClass = entry.getValue();

      List<BigDecimal> paidRatios = new ArrayList<>();
      BigDecimal currentSum = BigDecimal.ZERO;

      // 遍历该 险类 下每个月的赔付率，同时判断是否超过1，超过1的部分不添加进数组
      for (ConfMeasureClaimModelNew model : modelsInClass) {
        if (currentSum.compareTo(BigDecimal.ONE) >= 0) {
          break;
        }
        BigDecimal ratio = model.getPaidRatio();
        paidRatios.add(ratio);
        currentSum = currentSum.add(ratio);
      }
      claimModelMap.put(classCode, paidRatios.toArray(new BigDecimal[0]));
    }

    //3.预加载月度远期利率
    LambdaQueryWrapper<ConfMeasureMonthDisrate> disrateQuery = Wrappers.lambdaQuery();
    disrateQuery.orderByAsc(ConfMeasureMonthDisrate::getTermMonth);
    List<ConfMeasureMonthDisrate> disrates = measureMonthDisrateMapper.selectList(disrateQuery);
    Map<String, Map<Integer, BigDecimal>> disrateMap = disrates.stream()
      .collect(Collectors.groupingBy(ConfMeasureMonthDisrate::getValMonth,
        Collectors.toMap(ConfMeasureMonthDisrate::getTermMonth, ConfMeasureMonthDisrate::getForwardDisrateValue)));

    //TODO 上月未到期明细的总获取费用、跟单费用、期初未到期余额、期初未到期余额（跟单）、累计确认保费、累计利息、累计确认获取费用
//    Map<String, Map<String, BigDecimal>> lastMeasureCxUnexpired = getLastMeasureCxUnexpired(DateUtils.lastEndMonth(valMonth, DateUtils.YYYYMM),
//      MeasureCxUnexpired::getUnitId,MeasureCxUnexpired::getTotalIacfAmt, MeasureCxUnexpired::getTotalIacfDirectAmt,
//      MeasureCxUnexpired::getAccIacfDirectAmt,MeasureCxUnexpired::getInitLrcAmt,MeasureCxUnexpired::getLrcNoLossDirectAmt,
//      MeasureCxUnexpired::getAccConfirmedPremium,MeasureCxUnexpired::getIfieAmt,MeasureCxUnexpired::getAccIfieDirectAmt,
//      MeasureCxUnexpired::getAccIacfPremium,MeasureCxUnexpired::getAccReceivedPremiums);

    // 上月未到期明细的总获取费用、跟单费用、期初未到期余额、期初未到期余额（跟单）、累计确认保费、累计利息、累计确认获取费用、累计实收保费、累计摊销的签单保费(不含利息)、累计摊销的IFIE
    Map<String, Map<String, BigDecimal>> lastMeasureCxUnexpired = getLastMeasureCxUnexpired(DateUtils.lastEndMonth(valMonth, DateUtils.YYYYMM),
      MeasureCxUnexpired::getUnitId, MeasureCxUnexpired::getTotalIacfAmt, MeasureCxUnexpired::getInitLrcAmt,
      MeasureCxUnexpired::getLrcNoLossAmt, MeasureCxUnexpired::getAccConfirmedPremium, MeasureCxUnexpired::getIfieAmt,
      MeasureCxUnexpired::getAccIacfPremium, MeasureCxUnexpired::getAccReceivedPremiums,MeasureCxUnexpired::getAccAmortizePremiums,
      MeasureCxUnexpired::getAccAmortizeIfie);

    //放入缓存
    context.setAssumptionCache(collect);
    context.setDiscountFactorCache(claimModelMap);
    context.setDisRateCache(disrateMap);
    context.setLastMeasureCxUnexpiredCache(lastMeasureCxUnexpired);

    log.info("预加载完成 - 精算假设: {} 条, 赔付模式: {} 条, 月度远期利率: {} 条,上期未到期明细: {} 条",
      collect.size(), claimModelMap.size(), disrateMap.size(), lastMeasureCxUnexpired.size());

    return context;
  }

  /**
   * 使用游标分页+并行处理数据
   */
  private void processDataWithCursorPagination(String valMethod, String valMonth, MeasureContext context) {
    transactionTemplate.execute(status -> {
      //清空当期数据
      measureCxUnexpiredMapper.delete(new LambdaQueryWrapper<MeasureCxUnexpired>().eq(MeasureCxUnexpired::getValMonth,
        valMonth).eq(MeasureCxUnexpired::getValMethod, valMethod));
      return null;
    });

    //更新计量源数据统计信息，防止索引失效
    jdbcTemplate.execute("ANALYZE measure_cf_basic_data_new");

    long maxId = 0; // 游标
    int x = 1;

    while (true) {
      Long startTime = System.currentTimeMillis();
      // 使用游标方式分页查询
      LambdaQueryWrapper<MeasureCfBasicDataNew> lqw = new LambdaQueryWrapper<>();
      lqw.select(MeasureCfBasicDataNew::getId, MeasureCfBasicDataNew::getPolicyNo, MeasureCfBasicDataNew::getCertiNo, MeasureCfBasicDataNew::getGroupId,
          MeasureCfBasicDataNew::getClassCode, MeasureCfBasicDataNew::getRiskCode, MeasureCfBasicDataNew::getPremiumCny, MeasureCfBasicDataNew::getIniConfirm, MeasureCfBasicDataNew::getStartDate,
          MeasureCfBasicDataNew::getEndDate, MeasureCfBasicDataNew::getTerm, MeasureCfBasicDataNew::getIacfUnfolCny, MeasureCfBasicDataNew::getIacfFolCny,
          MeasureCfBasicDataNew::getUnitId, MeasureCfBasicDataNew::getComCode, MeasureCfBasicDataNew::getBusinessNature, MeasureCfBasicDataNew::getCarKindCode,
          MeasureCfBasicDataNew::getUseNatureCode, MeasureCfBasicDataNew::getIacfAmount, MeasureCfBasicDataNew::getPremiumReceived, MeasureCfBasicDataNew::getServiceProportion)
        .eq(MeasureCfBasicDataNew::getValMonth, valMonth)
        .gt(MeasureCfBasicDataNew::getId, maxId)
        .orderByAsc(MeasureCfBasicDataNew::getId)
        .last("LIMIT " + BATCH_SIZE);
      List<MeasureCfBasicDataNew> records = measureCfBasicDataNewMapper.selectList(lqw);
      if (records.isEmpty()) {
        break;
      }
      log.info("LRC计量，页数:{},耗时: {}ms", x++, System.currentTimeMillis() - startTime);
      //处理批次数据
      processBatch(records, valMonth, valMethod, context);
      // 更新游标
      maxId = records.get(records.size() - 1).getId();
    }
    //按合同组维度分摊亏损部分到单
    int i = measureCxUnexpiredMapper.updateLossCost(valMonth, valMethod);
    log.info("更新亏损分摊单，数量:{}", i);
  }

  /**
   * 异步处理批次数据
   */
  private void processBatch(List<MeasureCfBasicDataNew> batchData, String valMonth, String valMethod, MeasureContext context) {
    // 将参数声明为final，避免lambda表达式中的变量引用问题
    final String finalValMonth = valMonth;
    final String finalValMethod = valMethod;
    final List<MeasureCfBasicDataNew> finalBatchData = batchData;

    try {
      long startTime = System.currentTimeMillis();
      //并行流处理代替向量化计算
      List<MeasureCxUnexpired> batchResults = finalBatchData.stream()
        .map(contract -> calculateLrcWithMonthlyRolling(contract, finalValMonth, finalValMethod, context))
        .filter(Objects::nonNull)
        .collect(Collectors.toList());
      //批量插入结果，处理一批就提交一批事物
      long startTime2 = System.currentTimeMillis();
      insertBatchWithJdbcTemplate(batchResults);
      log.debug("批次处理完成，数据插入耗时: {}, 批次整体耗时: {} ms",
        System.currentTimeMillis() - startTime2, System.currentTimeMillis() - startTime);
    } catch (Exception e) {
      throw new RuntimeException("直保未到期批次处理异常", e);
    }
  }

  private void insertBatchWithJdbcTemplate(List<MeasureCxUnexpired> allResults) {
    if (CollectionUtils.isEmpty(allResults)) {
      return;
    }
    // 1. 定义所有要插入的字段名
    List<String> columnNames = Arrays.asList(
      "id", "val_month", "val_method", "policy_no", "certi_no", "class_code",
      "start_date", "end_date", "group_id", "portfolio_id", "term", "total_premium",
      "init_lrc_amt", "ifie_amt", "acc_confirmed_premium", "acc_iacf_premium",
      "unexpired_premium", "pv_future_compensation", "pv_future_maintenance",
      "future_receivable_premiums", "risk_adjustment", "lrc_loss_amt", "lrc_no_loss_amt",
      "lrc_debt", "currency", "create_time", "update_time", "is_status", "remark",
      "future_cash_flow", "ini_confirm", "acc_received_premiums", "risk_code", "total_iacf_amt",
      "unit_id", "com_code", "business_nature", "car_kind_code", "use_nature_code",
      "current_received_premiums", "current_iacf_amt", "current_ifie","acc_service_proportion",
      "current_amortize_premiums","current_amortize_ifie","acc_amortize_premiums","acc_amortize_ifie"
    );

    // 2. 动态构建 SQL
    String columnsPart = columnNames.stream()
      .map(name -> "\"" + name + "\"")
      .collect(Collectors.joining(", "));

    String placeholdersPart = columnNames.stream()
      .map(name -> "?")
      .collect(Collectors.joining(", "));

    String sql = String.format("INSERT INTO measure_platform.measure_cx_unexpired (%s) VALUES (%s)", columnsPart, placeholdersPart);

    jdbcTemplate.batchUpdate(sql, new BatchPreparedStatementSetter() {
      @Override
      public void setValues(PreparedStatement ps, int i) throws SQLException {
        MeasureCxUnexpired item = allResults.get(i);
        int index = 1;

        ps.setLong(index++, item.getId());
        ps.setString(index++, item.getValMonth());
        ps.setString(index++, item.getValMethod());
        ps.setString(index++, item.getPolicyNo());
        ps.setString(index++, item.getCertiNo());
        ps.setString(index++, item.getClassCode());
        ps.setString(index++, item.getStartDate());
        ps.setString(index++, item.getEndDate());
        ps.setString(index++, item.getGroupId());
        ps.setString(index++, item.getPortfolioId());
        ps.setLong(index++, item.getTerm());
        ps.setBigDecimal(index++, item.getTotalPremium());
        ps.setBigDecimal(index++, item.getInitLrcAmt());
        ps.setBigDecimal(index++, item.getIfieAmt());
        ps.setBigDecimal(index++, item.getAccConfirmedPremium());
        ps.setBigDecimal(index++, item.getAccIacfPremium());
        ps.setBigDecimal(index++, item.getUnexpiredPremium());
        ps.setBigDecimal(index++, item.getPvFutureCompensation());
        ps.setBigDecimal(index++, item.getPvFutureMaintenance());
        ps.setBigDecimal(index++, item.getFutureReceivablePremiums());
        ps.setBigDecimal(index++, item.getRiskAdjustment());
        ps.setBigDecimal(index++, item.getLrcLossAmt());
        ps.setBigDecimal(index++, item.getLrcNoLossAmt());
        ps.setBigDecimal(index++, item.getLrcDebt());
        ps.setString(index++, "CNY");
        ps.setTimestamp(index++, new Timestamp(System.currentTimeMillis()));
        ps.setTimestamp(index++, new Timestamp(System.currentTimeMillis()));
        ps.setString(index++, "0");
        ps.setString(index++, item.getRemark());
        ps.setBigDecimal(index++, item.getFutureCashFlow());
        ps.setString(index++, item.getIniConfirm());
        ps.setBigDecimal(index++, item.getAccReceivedPremiums());
        ps.setString(index++, item.getRiskCode());
        ps.setBigDecimal(index++, item.getTotalIacfAmt());
        ps.setString(index++, item.getUnitId());
        ps.setString(index++, item.getComCode());
        ps.setString(index++, item.getBusinessNature());
        ps.setString(index++, item.getCarKindCode());
        ps.setString(index++, item.getUseNatureCode());
        ps.setBigDecimal(index++, item.getCurrentReceivedPremiums());
        ps.setBigDecimal(index++, item.getCurrentIacfAmt());
        ps.setBigDecimal(index++, item.getCurrentIfie());
        ps.setBigDecimal(index++, item.getAccServiceProportion());
        ps.setBigDecimal(index++, item.getCurrentAmortizePremiums());
        ps.setBigDecimal(index++, item.getCurrentAmortizeIfie());
        ps.setBigDecimal(index++, item.getAccAmortizePremiums());
        ps.setBigDecimal(index++, item.getAccAmortizeIfie());
      }

      @Override
      public int getBatchSize() {
        return allResults.size();
      }
    });
  }

  /**
   * 过渡期从保险责任起期滚动计量到评估时点
   */
  private MeasureCxUnexpired calculateLrcWithMonthlyRolling(MeasureCfBasicDataNew contract, String valMonth, String valMethod, MeasureContext context) {
//    try {
    //获取初始确认日该险类下的精算假设配置表
    Map<String, ConfMeasureActuarialAssumption> stringConfMeasureActuarialAssumptionMap = context.getAssumptionCache()
      .getOrDefault(DateUtils.parseDateToStr(DateUtils.YYYYMM, DateUtils.parseDate(contract.getIniConfirm())), Collections.emptyMap());
    ConfMeasureActuarialAssumption iniConfirmAssumption = stringConfMeasureActuarialAssumptionMap.get(contract.getClassCode());
    if (iniConfirmAssumption == null) {
      log.error("初始确认日{},险类{}下的精算假设配置表不存在", contract.getIniConfirm(), contract.getClassCode());
    }
    //获取评估时点该险类下的精算假设配置表
    Map<String, ConfMeasureActuarialAssumption> currentConfMeasureActuarialAssumptionMap = context.getAssumptionCache()
      .getOrDefault(valMonth, Collections.emptyMap());
    ConfMeasureActuarialAssumption assumption = currentConfMeasureActuarialAssumptionMap.get(contract.getClassCode());
    if (assumption == null) {
      log.error("评估月{},险类{}下的精算假设配置表不存在", valMonth, contract.getClassCode());
    }
    //上期未到期明细的累计获取费用跟单、累计获取费用非跟单
    Map<String, BigDecimal> lastMeasureCxUnexpired = context.lastMeasureCxUnexpiredCache.getOrDefault(contract.getUnitId(), Collections.emptyMap());
    BigDecimal lastTotalIacfAmt = lastMeasureCxUnexpired.getOrDefault(ReflectUtils.getFieldName(MeasureCxUnexpired::getTotalIacfAmt), BigDecimal.ZERO);
//      BigDecimal lastTotalIacfDirectAmt = lastMeasureCxUnexpired.getOrDefault(ReflectUtils.getFieldName(MeasureCxUnexpired::getTotalIacfDirectAmt), BigDecimal.ZERO);
    // 获取费用=（跟单+非跟单）
    BigDecimal iacfCashflow = contract.getIacfAmount().add(lastTotalIacfAmt);
    //TODO 前海特有，跟单获取费用部分
//      BigDecimal iacfCashflowDirect = contract.getIacfFolCny().add(lastTotalIacfDirectAmt);
    //I17初始确认日（暂定为签单日期）到止期经过的月份数
    int monthsNum = DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(contract.getIniConfirm()),
      DateUtils.parseDate(contract.getEndDate())) + 1;
    //I17初始确认日（暂定为签单日期）到评估月经过的月份数
    int valMonthNum = DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(contract.getIniConfirm()),
      DateUtils.parseDate(valMonth)) + 1;
    //剩余期间=评估月到保单止期经过的月份数，如果评估月晚于保单止期，则剩余期间为0
    int remaining = Math.max(monthsNum - valMonthNum, 0);

    if (monthsNum >= 720) {
      contract.setIsStatus("3");
      contract.setRemark("初始确认日到保单止期超过720个月");
      log.error("保单数据{}，初始确认日到保单止期超过720个月", contract);
      return null;
    }
    //初始确认日对应的月利率曲线
    Map<Integer, BigDecimal> initMonthRateMap = context.disRateCache.getOrDefault(DateUtils.parseDateToStr(DateUtils.YYYYMM,
      DateUtils.parseDate(contract.getIniConfirm())), Collections.emptyMap());
    if (initMonthRateMap.isEmpty()) {
      log.error("初始确认日{}对应的月利率曲线不存在", contract.getIniConfirm());
    }
    //初始确认日到当前滚动的月份数对应的月度远期利率
    BigDecimal disRate = initMonthRateMap.getOrDefault(valMonthNum, BigDecimal.ZERO);
    //当期支出的获取费用
    BigDecimal iacfCashflowCurrent = contract.getIacfAmount();
    // 获取费用利息 = 获取费用 * 月利率 * 0.5 ,默认只计息半个月
    BigDecimal iacfCashflowIfie = iacfCashflowCurrent.multiply(disRate).multiply(IFIE_RATIO).setScale(10, RoundingMode.HALF_UP);
    //当期支出的获取费用（跟单）
//        BigDecimal iacfCashflowCurrentDirect = contract.getIacfFolCny();
//        BigDecimal iacfCashflowDirectIfie = iacfCashflowCurrentDirect.multiply(disRate).setScale(10, RoundingMode.HALF_UP);
    //实收保费
    BigDecimal premiumCashflow = contract.getPremiumReceived();
    //上期累计实收保费
    BigDecimal lastAccReceivedPremiums = lastMeasureCxUnexpired.getOrDefault(ReflectUtils.getFieldName(MeasureCxUnexpired::getAccReceivedPremiums), BigDecimal.ZERO);

    //TODO 前海特有，PACK开头的保单在核销表里面没有，默认在期初就全部收到保费,如果上期没有记录,则默认在当期全部收到
    if (contract.getPolicyNo().startsWith("PACK") && lastAccReceivedPremiums.compareTo(BigDecimal.ZERO) == 0) {
      premiumCashflow = contract.getPremiumCny();
    }
    //累计实收保费=当期新增+上期累计
    BigDecimal cumulativeReceivedPremiums = lastMeasureCxUnexpired.getOrDefault(ReflectUtils.getFieldName(MeasureCxUnexpired::getAccReceivedPremiums), BigDecimal.ZERO)
      .add(premiumCashflow);
    //累计服务量比例
    BigDecimal cumulativeProportion = contract.getServiceProportion();
    //TODO 投资成分改成不折现，前海暂时不考虑投资成分
    //投资成分
//        BigDecimal investmentValue = contract.getPremiumCny().multiply(INVESTMENT_RATIO).setScale(10, RoundingMode.HALF_UP);
    //当期确认的投资成分现值=投资成分月末现值*累计服务量比例-累计确认的投资成分月末现值
//      BigDecimal discountRate = getDiscountRate(initMonthRateMap, x+1, monthsNum);
    //投资成分现值
//      BigDecimal investmentAmt= investmentValue.multiply(discountRate).setScale(10, RoundingMode.HALF_UP);
    //当期确认的投资成分
//        BigDecimal currentInvestment = investmentValue.multiply(cumulativeProportion).subtract(cumulativeInvestment).setScale(10, RoundingMode.HALF_UP);
    //累计确认的投资成分
//        cumulativeInvestment = cumulativeInvestment.add(currentInvestment).setScale(10, RoundingMode.HALF_UP);
    //未到期期初余额=上期期末非亏部分
    BigDecimal openingBalance = lastMeasureCxUnexpired.getOrDefault(ReflectUtils.getFieldName(MeasureCxUnexpired::getLrcNoLossAmt), BigDecimal.ZERO);
    //未到期期初余额跟单部分
//    BigDecimal openingBalanceDirect = lastMeasureCxUnexpired.getOrDefault(ReflectUtils.getFieldName(MeasureCxUnexpired::getLrcNoLossDirectAmt), BigDecimal.ZERO);
    //期初未到期计息=未到期期初余额 * 对应月度远期利率
    BigDecimal openingBalanceIfie = openingBalance.multiply(disRate).setScale(10, RoundingMode.HALF_UP);
    //TODO 前海特有 未到期期初余额（跟单）
//        BigDecimal openingBalanceDirectIfie = openingBalanceDirect.multiply(disRate).multiply(IFIE_RATIO).setScale(10, RoundingMode.HALF_UP);
    //实收保费计息=实收保费 * 对应月度远期利率 * 0.5 ,默认只计息半个月
    BigDecimal premiumCashflowIfie = premiumCashflow.multiply(disRate).multiply(IFIE_RATIO).setScale(10, RoundingMode.HALF_UP);
    //当期未到期计息=期初未到期计息+实收保费计息-获取费用利息
    BigDecimal currentIfie = openingBalanceIfie.add(premiumCashflowIfie).subtract(iacfCashflowIfie);
    //累计未到期计息
    BigDecimal cumulativeIfie = lastMeasureCxUnexpired.getOrDefault(ReflectUtils.getFieldName(MeasureCxUnexpired::getIfieAmt), BigDecimal.ZERO)
      .add(currentIfie);
    //TODO 前海特有 未到期累计利息（跟单）
//        BigDecimal currentIfieDirect = openingBalanceDirectIfie.add(premiumCashflowIfie).subtract(iacfCashflowDirectIfie);
    //TODO 前海特有 累计确认保费收入（跟单）
//        BigDecimal cumulativePremiumsDirect = lastMeasureCxUnexpired.getOrDefault(ReflectUtils.getFieldName(MeasureCxUnexpired::getAccConfirmedPremium), BigDecimal.ZERO);
    //TODO 累计未到期计息（跟单）
//        BigDecimal cumulativeIfieDirect = lastMeasureCxUnexpired.getOrDefault(ReflectUtils.getFieldName(MeasureCxUnexpired::getAccIfieDirectAmt), BigDecimal.ZERO)
//          .add(currentIfieDirect);
    //累计确认保费收入（上期累计值）
    BigDecimal cumulativePremiums = lastMeasureCxUnexpired.getOrDefault(ReflectUtils.getFieldName(MeasureCxUnexpired::getAccConfirmedPremium), BigDecimal.ZERO);
    //上期累计摊销的签单保费(不含利息)
    BigDecimal accAmortizePremiums = lastMeasureCxUnexpired.getOrDefault(ReflectUtils.getFieldName(MeasureCxUnexpired::getAccAmortizePremiums), BigDecimal.ZERO);
    //上期累计摊销的IFIE
    BigDecimal accAmortizeIfie = lastMeasureCxUnexpired.getOrDefault(ReflectUtils.getFieldName(MeasureCxUnexpired::getAccAmortizeIfie), BigDecimal.ZERO);

    //当期确认保费收入（含利息）=（总保费+累计未到期计息）* 累计服务比例 - 累计确认保费收入
    BigDecimal currentPremiums = (contract.getPremiumCny().add(cumulativeIfie)).multiply(cumulativeProportion).subtract(cumulativePremiums).setScale(10, RoundingMode.HALF_UP);
    //当期摊销的签单费费（不含利息） = 总签单保费*累计服务比例 - 上期累计确认的签单保费(不含利息)
    BigDecimal currentAmortizePremiums = contract.getPremiumCny().multiply(cumulativeProportion).subtract(accAmortizePremiums).setScale(10, RoundingMode.HALF_UP);
    //当期摊销的IFIE（不含利息） = 累计未到期计息*累计服务比例 - 上期累计确认的IFIE
    BigDecimal currentAmortizeIfie = cumulativeIfie.multiply(cumulativeProportion).subtract(accAmortizeIfie).setScale(10, RoundingMode.HALF_UP);

    //累计摊销的签单保费(不含利息) = 上期累计摊销的签单保费(不含利息) + 当期摊销的签单费费（不含利息）
    accAmortizePremiums = accAmortizePremiums.add(currentAmortizePremiums);
    //累计摊销的IFIE = 上期累计摊销的IFIE + 当期摊销的IFIE
    accAmortizeIfie = accAmortizeIfie.add(currentAmortizeIfie);
    //累计确认保费收入 = 上期累计确认保费收入 + 当期确认的包肥收入（含利息）
    cumulativePremiums = cumulativePremiums.add(currentPremiums);

    //累计确认获取费用（上期累计值）
    BigDecimal cumulativeIacf = lastMeasureCxUnexpired.getOrDefault(ReflectUtils.getFieldName(MeasureCxUnexpired::getAccIacfPremium), BigDecimal.ZERO);
    //当期确认获取费用=预期支付获取费用总额 * 累计服务比例 -累计确认获取费用
    BigDecimal currentIacf = iacfCashflow.multiply(cumulativeProportion).subtract(cumulativeIacf).setScale(10, RoundingMode.HALF_UP);
    //累计确认获取费用
    cumulativeIacf = cumulativeIacf.add(currentIacf);

    //TODO 前海特有 当期确认获取费用（跟单）
//        BigDecimal cumulativeIacfDirect = lastMeasureCxUnexpired.getOrDefault(ReflectUtils.getFieldName(MeasureCxUnexpired::getAccIacfDirectAmt), BigDecimal.ZERO);
//        BigDecimal currentIacfDirect = iacfCashflowDirect.multiply(cumulativeProportion).subtract(cumulativeIacfDirect).setScale(10, RoundingMode.HALF_UP);
//        //累计确认获取费用（跟单）
//        cumulativeIacfDirect = cumulativeIacfDirect.add(currentIacfDirect);

    // LRC非亏损部分期末余额=未到期期初余额+实收保费-支付的获取费用（默认期初一次性支付）+未到期计息-当期确认的保费收入摊销+当期确认的获取费用摊销
    BigDecimal closingBalance = openingBalance
      .add(premiumCashflow)
      .subtract(iacfCashflowCurrent)
      .add(currentIfie)
      .subtract(currentPremiums)
      .add(currentIacf);

    //TODO 前海特有 LRC非亏损部分期末余额（跟单）
//        BigDecimal closingBalanceDirect = openingBalanceDirect
//          .add(premiumCashflow)
//          .subtract(iacfCashflowCurrentDirect)
//          .add(currentIfieDirect)
//          .subtract(currentPremiums)
//          .add(currentIacfDirect);

    // 未来服务量比例
    BigDecimal futureProportion = BigDecimal.ONE.subtract(cumulativeProportion).max(BigDecimal.ZERO);
    //未满期保费
    BigDecimal futurePremiums = contract.getPremiumCny().multiply(futureProportion).setScale(10, RoundingMode.HALF_UP);

    //5.计算亏损部分
    ArrayList<BigDecimal> lossCashFlowList = new ArrayList<>();
    ArrayList<BigDecimal> maintenanceCashFlowList = new ArrayList<>();
    //预期未来应收保费=签单保费-减值-实收保费
    BigDecimal futureUnearned = contract.getPremiumCny().subtract(cumulativeReceivedPremiums);
    //预期未来赔付费用 = 未满期保费*精算假设赔付率*（1+间接理赔费用率）
    BigDecimal futureLoss = futurePremiums.multiply(assumption.getLossRatio()).multiply(assumption.getIndirectClaimsExpenseRatio().add(BigDecimal.ONE)).setScale(10, RoundingMode.HALF_UP);
    //预期未来赔付现值 = 预期未来赔付费用均摊到剩余期间，根据赔付模式配置表展开乘进展因子后再折现
    BigDecimal pvFutureLoss = getPvLoss(futureLoss, contract.getClassCode(), remaining, valMonth, lossCashFlowList, contract,context);
    //预期未来维持费用 = 未满期保费*精算假设维持费用率
    BigDecimal futureMaintenance = futurePremiums.multiply(assumption.getMaintenanceExpenseRatio()).setScale(10, RoundingMode.HALF_UP);
    //预期未来维持费用现值 = 预期未来维持费用均摊到剩余期间在折现
    BigDecimal pvFutureMaintenance = getPvMaintenance(futureMaintenance, remaining, valMonth, maintenanceCashFlowList, context);
    //预期未来获取费用 = 默认没有
    BigDecimal futureAcquisition = BigDecimal.ZERO;
    //风险调整 = （预期未来赔付现值+预期未来维持费用现值）* 精算假设RA
    BigDecimal riskAdjustment = (pvFutureMaintenance.add(pvFutureLoss)).multiply(assumption.getRa()).setScale(10, RoundingMode.HALF_UP);
    //预期现金流:预期未来赔付现值 + 预期未来维持费用现值 + 预期未来获取费用现值 - 预期未来应收保费 + 风险调整
    BigDecimal futureCashFlow = pvFutureLoss.add(pvFutureMaintenance).add(futureAcquisition).add(riskAdjustment).subtract(futureUnearned);
    // 亏损测试：预期未来赔付现值 + 预期未来维持费用现值 + 预期未来获取费用现值 - 预期未来应收保费 + 风险调整 - 非亏部分
    BigDecimal netFutureCashFlow = futureCashFlow.subtract(closingBalance);
    //亏损部分保费为正Max(0, netFutureCashFlow)，保费为负Min(0, netFutureCashFlow)
    BigDecimal lossComponent = BigDecimal.ZERO;
    if (contract.getPremiumCny().compareTo(BigDecimal.ZERO) >= 0) {
      lossComponent = netFutureCashFlow.compareTo(BigDecimal.ZERO) > 0 ? netFutureCashFlow : BigDecimal.ZERO;
    } else {
      lossComponent = netFutureCashFlow.compareTo(BigDecimal.ZERO) < 0 ? netFutureCashFlow : BigDecimal.ZERO;
    }

    //TODO 亏损部分（跟单）
//      BigDecimal netFutureCashFlowDirect = futureCashFlow.subtract(closingBalanceDirect);
    // 亏损部分保费为正Max(0, netFutureCashFlow)，保费为负Min(0, netFutureCashFlow)
//      BigDecimal lossComponentDirect = BigDecimal.ZERO;
//      if (contract.getPremiumCny().compareTo(BigDecimal.ZERO) >= 0) {
//        lossComponentDirect = netFutureCashFlowDirect.compareTo(BigDecimal.ZERO) > 0 ? netFutureCashFlowDirect : BigDecimal.ZERO;
//      } else {
//        lossComponentDirect = netFutureCashFlowDirect.compareTo(BigDecimal.ZERO) < 0 ? netFutureCashFlowDirect : BigDecimal.ZERO;
//      }

    //返回评估时点的明细结果
    MeasureCxUnexpired measureCxUnexpired = new MeasureCxUnexpired();
    measureCxUnexpired.setIniConfirm(contract.getIniConfirm());
    measureCxUnexpired.setStartDate(contract.getStartDate());
    measureCxUnexpired.setEndDate(contract.getEndDate());
    measureCxUnexpired.setPolicyNo(contract.getPolicyNo());
    measureCxUnexpired.setCertiNo(contract.getCertiNo());
    measureCxUnexpired.setValMonth(valMonth);
    measureCxUnexpired.setValMethod(valMethod);
    measureCxUnexpired.setGroupId(contract.getGroupId());
    measureCxUnexpired.setClassCode(contract.getClassCode());
    measureCxUnexpired.setUpdateTime(new Date());
    measureCxUnexpired.setCreateTime(new Date());
    measureCxUnexpired.setId(IdUtils.getSnowFlakeLongId());
    measureCxUnexpired.setRiskCode(contract.getRiskCode());
    measureCxUnexpired.setUnitId(contract.getUnitId());
    measureCxUnexpired.setComCode(contract.getComCode());
    measureCxUnexpired.setBusinessNature(contract.getBusinessNature());
    measureCxUnexpired.setCarKindCode(contract.getCarKindCode());
    measureCxUnexpired.setUseNatureCode(contract.getUseNatureCode());

    //保障期限
    measureCxUnexpired.setTerm(Long.valueOf(contract.getTerm()));
    //签单保费
    measureCxUnexpired.setTotalPremium(contract.getPremiumCny());
    //未满期保费
    measureCxUnexpired.setUnexpiredPremium(futurePremiums);
    //累计确认保费
    measureCxUnexpired.setAccConfirmedPremium(cumulativePremiums);
    //累计确认的获取费用
    measureCxUnexpired.setAccIacfPremium(cumulativeIacf);
    //累计计息
    measureCxUnexpired.setIfieAmt(cumulativeIfie);
    //未到期期初余额
    measureCxUnexpired.setInitLrcAmt(openingBalance);
    //预期未来应收保费
    measureCxUnexpired.setFutureReceivablePremiums(futureUnearned);
    //预期未来赔付费用现值
    measureCxUnexpired.setPvFutureCompensation(pvFutureLoss);
    //预期未来维持费用现值
    measureCxUnexpired.setPvFutureMaintenance(pvFutureMaintenance);
    //风险调整
    measureCxUnexpired.setRiskAdjustment(riskAdjustment);
    //未到期非亏部分
    measureCxUnexpired.setLrcNoLossAmt(closingBalance);
    //TODO 未到期非亏部分（跟单）
//      measureCxUnexpired.setLrcNoLossDirectAmt(closingBalanceDirect);
    //未到期亏损部分
    measureCxUnexpired.setLrcLossAmt(lossComponent);
    //TODO 未到期亏损部分（跟单）
//      measureCxUnexpired.setLrcLossDirectAmt(lossComponentDirect);
    //未到期责任负债
    measureCxUnexpired.setLrcDebt(closingBalance.add(lossComponent));
    //预期未来现金流
    measureCxUnexpired.setFutureCashFlow(futureCashFlow);
    //PV预期未来赔付现金流
    measureCxUnexpired.setLossCashFlow(lossCashFlowList);
    //PV预期未来维持费用现金流
    measureCxUnexpired.setMaintenanceCashFlow(maintenanceCashFlowList);
    //累计实收保费
    measureCxUnexpired.setAccReceivedPremiums(cumulativeReceivedPremiums);
    //总获取费用
    measureCxUnexpired.setTotalIacfAmt(iacfCashflow);
    //当期确认的保费收入
    measureCxUnexpired.setCurrentReceivedPremiums(currentPremiums);
    //当期摊销的获取费用
    measureCxUnexpired.setCurrentIacfAmt(currentIacf);
    //当期未到期利息
    measureCxUnexpired.setCurrentIfie(currentIfie);
    //累计服务比例
    measureCxUnexpired.setAccServiceProportion(cumulativeProportion);
    //当期摊销的签单保费(不含利息)
    measureCxUnexpired.setCurrentAmortizePremiums(currentAmortizePremiums);
    //当期摊销的IFIE
    measureCxUnexpired.setCurrentAmortizeIfie(currentAmortizeIfie);
    //累计摊销的签单保费(不含利息)
    measureCxUnexpired.setAccAmortizePremiums(accAmortizePremiums);
    //累计摊销的IFIE
    measureCxUnexpired.setAccAmortizeIfie(accAmortizeIfie);
    return measureCxUnexpired;
//    }catch (Exception e){
//      log.error("未到期计量计算异常,保单数据:{}",JSON.toJSONString(contract),e);
//    }
//    return null;
  }

  /**
   * 根据赔付模式进度因子数组计算
   * 例如赔付模式进度因子数组为[0.05, 0.95]，金额是600，均分成6期
   * [5, 95, 0, 0, 0, 0, 0]
   * [0, 5, 95, 0, 0, 0, 0]
   * [0, 0, 5, 95, 0, 0, 0]
   * [0, 0, 0, 5, 95, 0, 0]
   * [0, 0, 0, 0, 5, 95, 0]
   * [0, 0, 0, 0, 0, 5, 95]
   * 结果result[5,100,100,100,100,100,95],再对result折现
   *
   * @param amt       预期未来赔付费用
   * @param classCode 险类代码
   * @param n         均摊次数
   * @return
   */
  private BigDecimal getPvLoss(BigDecimal amt, String classCode, int n, String valMonth, List<BigDecimal> cashFlowList, MeasureCfBasicDataNew contract,MeasureContext context) {
    if (BigDecimal.ZERO.compareTo(amt) == 0) {
      return BigDecimal.ZERO;
    }
    if (n <= 0) {
      log.error("==============剩余期间:{},未满期保费:{},保单数据:{}", n, amt, JSON.toJSONString(contract));
    }
    Map<Integer, BigDecimal> monthsRateMap = context.getDisRateCache().getOrDefault(valMonth, Collections.emptyMap());
    if (monthsRateMap.isEmpty()){
      throw new RuntimeException(String.format("评估月%s，对应的月利率曲线不存在", valMonth));
    }
    BigDecimal[] claimFactorArr = context.getDiscountFactorCache().getOrDefault(classCode, new BigDecimal[0]);
    if (claimFactorArr.length == 0){
      throw new RuntimeException(String.format("险类%s，对应的进度因子数组不存在", classCode));
    }
    BigDecimal[] claimFactor = Arrays.copyOf(claimFactorArr, claimFactorArr.length);
    BigDecimal avgAmt = amt.divide(new BigDecimal(n), 10, RoundingMode.HALF_UP);
    for (int i = 0; i < claimFactor.length; i++) {
      claimFactor[i] = avgAmt.multiply(claimFactor[i]).setScale(10, RoundingMode.HALF_UP);
    }
    //右移次数
    int k = n - 1;
    BigDecimal[] prefix = new BigDecimal[claimFactor.length + 1];
    int resultLength = claimFactor.length + k; // 结果数组长度
    BigDecimal[] result = new BigDecimal[resultLength];
    Arrays.fill(result, BigDecimal.ZERO);
    Arrays.fill(prefix, BigDecimal.ZERO);
    // 计算前缀和数组
    for (int i = 0; i < claimFactor.length; i++) {
      prefix[i + 1] = prefix[i].add(claimFactor[i]);
    }

    // 计算每个位置的累加和
    for (int j = 0; j < resultLength; j++) {
      int start = Math.max(0, j - k); // 起始索引
      int end = Math.min(j, claimFactor.length - 1);   // 结束索引
      result[j] = prefix[end + 1].subtract(prefix[start]);
    }
    //折现到当前评估时点
    BigDecimal product = BigDecimal.ONE;
    BigDecimal pvLoss = BigDecimal.ZERO;
    for (int i = 0; i < result.length; i++) {
      product = product.multiply(monthsRateMap.get(i + 1).add(BigDecimal.ONE)).setScale(10, RoundingMode.HALF_UP);
      result[i] = result[i].divide(product, 10, RoundingMode.HALF_UP);
      pvLoss = pvLoss.add(result[i]);
//      cashFlowList.add(result[i].setScale(2, RoundingMode.HALF_UP));
    }
    return pvLoss;
  }

  /**
   * 未来维持费用折现
   *
   * @param amt 预期未来维持费用
   * @param n   均摊次数
   * @return
   */
  private BigDecimal getPvMaintenance(BigDecimal amt, int n, String valMonth, List<BigDecimal> cashFlowList,MeasureContext context) {
    if (BigDecimal.ZERO.compareTo(amt) == 0) {
      return BigDecimal.ZERO;
    }
    Map<Integer, BigDecimal> monthsRateMap = context.getDisRateCache().getOrDefault(valMonth, Collections.emptyMap());
    if (monthsRateMap.isEmpty()){
      throw new RuntimeException(String.format("评估月%s，对应的月利率曲线不存在", valMonth));
    }
    BigDecimal arr[] = new BigDecimal[n];
    for (int i = 0; i < n; i++) {
      arr[i] = amt.divide(new BigDecimal(n), 10, RoundingMode.HALF_UP);
    }
    //折现到当前评估时点
    BigDecimal product = BigDecimal.ONE;
    BigDecimal pvMaintenance = BigDecimal.ZERO;
    for (int i = 0; i < arr.length; i++) {
      product = product.multiply(monthsRateMap.get(i + 1).add(BigDecimal.ONE)).setScale(10, RoundingMode.HALF_UP);
      arr[i] = arr[i].divide(product, 10, RoundingMode.HALF_UP);
      pvMaintenance = pvMaintenance.add(arr[i]);
//      cashFlowList.add(arr[i].setScale(2, RoundingMode.HALF_UP));
    }
    return pvMaintenance;
  }

  /**
   * 投资成分折现
   *
   * @param startBigDecimalMap 保险责任起期对应的月度远期利率曲线
   * @param startId            起点期间
   * @param endId              终点期间
   * @return
   */
  private BigDecimal getDiscountRate(Map<Integer, BigDecimal> startBigDecimalMap, int startId, int endId) {
    BigDecimal discountRate = BigDecimal.ONE;
    for (int i = startId; i <= endId; i++) {
      discountRate = discountRate.multiply(BigDecimal.ONE.add(startBigDecimalMap.getOrDefault(i, BigDecimal.ZERO))).setScale(10, RoundingMode.HALF_UP);
    }
    return BigDecimal.ONE.divide(discountRate, 10, RoundingMode.HALF_UP);
  }

  public Map<String, Map<String, BigDecimal>> getLastMeasureCxUnexpired(String valMonth, SFunction<MeasureCxUnexpired, ?>... selectVar) {
    SqlFunctionUtil<MeasureCxUnexpired> sqlFunctionUtil = new SqlFunctionUtil<>();
    QueryWrapper<MeasureCxUnexpired> lqw = new QueryWrapper<>();
    lqw = StringUtils.isNotEmpty(selectVar) ?
      lqw
        .select(sqlFunctionUtil.getParamSql(selectVar))
        //1.评估时点
        .eq(sqlFunctionUtil.getParamSql(MeasureCxUnexpired::getValMonth), valMonth) :
      lqw
        //1.评估时点
        .eq(sqlFunctionUtil.getParamSql(MeasureCxUnexpired::getValMonth), valMonth);
    List<MeasureCxUnexpired> infoList = measureCxUnexpiredMapper.selectList(lqw);
    Map<String, Map<String, BigDecimal>> collect = infoList.stream().collect(Collectors.groupingBy(e -> e.getUnitId(),
      Collectors.collectingAndThen(
        Collectors.toList(),
        list -> list.stream()
          .map(BeanUtil::beanToMap)
          .flatMap(k -> k.entrySet().stream())
          .filter(entry -> entry.getValue() != null && entry.getValue() instanceof BigDecimal)
          .collect(Collectors.toMap(
            Map.Entry::getKey,
            entry -> (BigDecimal) entry.getValue(),
            (v1, v2) -> v1 // 合并函数，如果有相同的key，保留第一个值
          ))
      )
    ));
    return collect;
  }
}

