package com.jdyx.cx.measure.service.impl;

import com.alibaba.fastjson2.JSON;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.jdyx.cx.measure.service.MeasureCxLrcService;
import com.jdyx.measure.api.measure.domain.*;
import com.jdyx.measure.api.measure.mapper.*;
import com.jdyx.measureprepare.api.domain.IntTPpJlContractNew;
import com.jdyx.measureprepare.api.mapper.IntTPpJlContractNewMapper;
import com.kevin.common.core.domain.R;
import com.kevin.common.utils.DateUtils;
import com.kevin.common.utils.uuid.IdUtils;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.BatchPreparedStatementSetter;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.DefaultTransactionDefinition;
import org.springframework.util.CollectionUtils;

import javax.annotation.Resource;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.text.ParseException;
import java.time.LocalDate;
import java.time.YearMonth;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
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
public class MeasureCxLrcServiceImpl implements MeasureCxLrcService {
  @Resource
  private ConfMeasureActuarialAssumptionMapper confMeasureActuarialAssumptionMapper;
  @Resource
  private ConfMeasureClaimModelNewMapper measureClaimModelNewMapper;
  @Resource
  private MeasureCxUnexpiredMapper measureCxUnexpiredMapper;
  @Resource
  private ConfMeasureMonthDisrateMapper measureMonthDisrateMapper;

  private final PlatformTransactionManager transactionManager;
  @Resource
  private PiShouldRecPayOffMonMapper piShouldRecPayOffMonMapper;
  @Resource
  private MeasureCfBasicDataNewMapper measureCfBasicDataNewMapper;
  @Resource
  private IntTPpJlContractNewMapper tPpJlContactNewMapper;


  @Autowired
  private JdbcTemplate jdbcTemplate;
  // 常量定义
  private static final int BATCH_SIZE = 100000;
  // 假设的投资成分占比
  private static final BigDecimal INVESTMENT_RATIO = new BigDecimal(0);
  //计息默认按月中
  private static final BigDecimal IFIE_RATIO = new BigDecimal(0.5);
  // 缓存优化 - 避免重复计算和查询
  private final Map<String, BigDecimal[]> discountFactorCache = new ConcurrentHashMap<>();
  private final Map<String, Map<String,ConfMeasureActuarialAssumption>> assumptionCache = new ConcurrentHashMap<>();
  private final Map<String, Map<Integer, BigDecimal>> disRateCache = new ConcurrentHashMap<>();

  private final Map<String, Map<String, BigDecimal>> payOffMonthCache = new ConcurrentHashMap<>();

  private static final DateTimeFormatter YYYYMM_FORMATTER = DateTimeFormatter.ofPattern("yyyyMM");


//  @Resource(name = "threadPoolExecutor")
//  private ThreadPoolExecutor threadPoolExecutor;

  @Override
  public R<?> getUnexpiredMeasureResult(String valMethod, String valMonth) {
    try {
      log.info("开始LRC计量计算，评估方法: {}, 评估月份: {}", valMethod, valMonth);
      long startTime = System.currentTimeMillis();

      // 1. 预加载缓存数据
      preloadCacheData(valMethod,valMonth);
      log.info("缓存预加载完成，耗时: {} 秒", (System.currentTimeMillis() - startTime) / 1000);

      // 2. 使用游标分页+并行处理（参考MeasureCxZbServiceImpl）
      processDataWithCursorPagination(valMethod, valMonth);

      // 3. 汇总结果
      log.info("LRC计量计算完成，总耗时: {} 秒", (System.currentTimeMillis() - startTime) / 1000);
      return R.ok();
    } catch (Exception e) {
      log.error("LRC计量计算失败", e);
      return R.fail("LRC计量计算失败: " + e.getMessage());
    } finally {
      // 清理缓存
      clearCache();
    }
  }

  /**
   * 预加载缓存数据
   */
  private void preloadCacheData(String valMethod,String valMonth) throws ParseException {
    // 1. 预加载精算假设数据到缓存
    LambdaQueryWrapper<ConfMeasureActuarialAssumption> assumptionQuery = Wrappers.lambdaQuery();
    assumptionQuery.eq(ConfMeasureActuarialAssumption::getValMethod, valMethod);
    List<ConfMeasureActuarialAssumption> assumptions = confMeasureActuarialAssumptionMapper.selectList(assumptionQuery);
    Map<String, ConcurrentHashMap<String, ConfMeasureActuarialAssumption>> collect =
      assumptions.stream()
        .collect(Collectors.groupingBy(
          ConfMeasureActuarialAssumption::getValMonth,  // 外层 key: valMonth
          Collectors.toMap(
            ConfMeasureActuarialAssumption::getClassCode,  // 内层 key: classCode
            assumption -> assumption,  // value: 对象本身
            (existing, replacement) -> existing,  // 冲突时保留现有值
            ConcurrentHashMap::new  // 内层 Map 使用 ConcurrentHashMap
          )
        ));

    // 2. 预加载赔付模式数据到缓存
    LambdaQueryWrapper<ConfMeasureClaimModelNew> claimModelQuery = Wrappers.lambdaQuery();
    claimModelQuery.orderByAsc(ConfMeasureClaimModelNew::getMonthId);
    List<ConfMeasureClaimModelNew> claimModels = measureClaimModelNewMapper.selectList(claimModelQuery);

    // 按 classCode 分组，并提取每个 classCode 对应的 paidRatio 数组
    Map<String, BigDecimal[]> claimModelMap = claimModels.stream()
      .collect(Collectors.groupingBy(
        ConfMeasureClaimModelNew::getClassCode,
        Collectors.mapping(
          ConfMeasureClaimModelNew::getPaidRatio,
          Collectors.collectingAndThen(
            Collectors.toList(),
            list -> list.toArray(new BigDecimal[0])
          )
        )
      ));

    //3.预加载月度远期利率
    LambdaQueryWrapper<ConfMeasureMonthDisrate> disrateQuery = Wrappers.lambdaQuery();
    disrateQuery.orderByAsc(ConfMeasureMonthDisrate::getTermMonth);
    List<ConfMeasureMonthDisrate> disrates = measureMonthDisrateMapper.selectList(disrateQuery);
    Map<String, Map<Integer, BigDecimal>> disrateMap = disrates.stream()
      .collect(Collectors.groupingBy(ConfMeasureMonthDisrate::getValMonth,
        Collectors.toMap(ConfMeasureMonthDisrate::getTermMonth, ConfMeasureMonthDisrate::getForwardDisrateValue)));

    //应收应付核销表
//    piShouldRecPayOffMonMapper.setPiShouldRecPayOffMonUnitId(DateUtils.endMonth(valMonth, DateUtils.YYYY_MM_DD));
    LambdaQueryWrapper<PiShouldRecPayOffMon>payOffMonQuery = Wrappers.lambdaQuery();
    payOffMonQuery.select(PiShouldRecPayOffMon::getPolicyNo,PiShouldRecPayOffMon::getCertiNo,
        PiShouldRecPayOffMon::getCancelDate, PiShouldRecPayOffMon::getCancelAmount)
      .eq(PiShouldRecPayOffMon::getStatDate, DateUtils.endMonth(DateUtils.parseDate(valMonth)))
      .eq(PiShouldRecPayOffMon::getBizType, "1");
    List<PiShouldRecPayOffMon> payOffMons = piShouldRecPayOffMonMapper.selectList(payOffMonQuery);
    Map<String, Map<String, BigDecimal>> payOffMonthMap = payOffMons.stream()
      .collect(Collectors.groupingBy(
        payOffMon -> payOffMon.getPolicyNo()+"_" +  Objects.toString(payOffMon.getCertiNo(), "NA"),
        Collectors.toMap(
          payOffMon -> DateUtils.parseDateToStr(DateUtils.YYYYMM,payOffMon.getCancelDate()),
          PiShouldRecPayOffMon::getCancelAmount,
          (existing, replacement) -> existing.add(replacement)
        )
      ));

    //放入缓存
    assumptionCache.putAll(collect);
    discountFactorCache.putAll(claimModelMap);
    disRateCache.putAll(disrateMap);
    payOffMonthCache.putAll(payOffMonthMap);

    //生成2312合同基础信息表
    tPpJlContactNewMapper.delete(new LambdaQueryWrapper<IntTPpJlContractNew>()
      .eq(IntTPpJlContractNew::getValMonth, valMonth));
    tPpJlContactNewMapper.createTPpJlContactByGdq();
    //生成2312计量源数据
    measureCfBasicDataNewMapper.delete(
      new LambdaQueryWrapper<MeasureCfBasicDataNew>().eq(MeasureCfBasicDataNew::getValMonth, valMonth));
    measureCfBasicDataNewMapper.createBasicDataByGdq23();

    log.info("预加载完成 - 精算假设: {} 条, 赔付模式: {} 个险类",
      assumptions.size(), claimModelMap.size());
  }

  /**
   * 使用游标分页+并行处理数据
   */
  private void processDataWithCursorPagination(String valMethod, String valMonth)
    throws InterruptedException {
    //清空当期数据
    measureCxUnexpiredMapper.delete(new LambdaQueryWrapper<MeasureCxUnexpired>().eq(MeasureCxUnexpired::getValMonth,
      valMonth).eq(MeasureCxUnexpired::getValMethod, valMethod));
    // 1. 获取总数据量
//    LambdaQueryWrapper<MeasureCfBasicDataNew> countQuery = Wrappers.lambdaQuery();
//    countQuery.eq(MeasureCfBasicDataNew::getValMethod, valMethod)
//      .eq(MeasureCfBasicDataNew::getValMonth, valMonth);
//    long selectCount = measureCfBasicDataNewMapper.selectCount(countQuery);
//
//    // 2. 计算批次数量
//    long batchCount = selectCount % BATCH_SIZE == 0 ?
//      selectCount / BATCH_SIZE : selectCount / BATCH_SIZE + 1;
//
//    // 3. 使用CountDownLatch进行并行处理
//    CountDownLatch latch = new CountDownLatch((int) batchCount);
//    final long MAX_TOTAL = 1500000L;
//    long processedTotal = 0; // 本次已处理数量

    long maxId = 0; // 游标
    int x = 1;

    while (true) {
      Long startTime = System.currentTimeMillis();
      // 使用游标方式分页查询
      LambdaQueryWrapper<MeasureCfBasicDataNew> lqw = new LambdaQueryWrapper<>();
      lqw.select(MeasureCfBasicDataNew::getId, MeasureCfBasicDataNew::getPolicyNo,MeasureCfBasicDataNew::getCertiNo, MeasureCfBasicDataNew::getGroupId,
          MeasureCfBasicDataNew::getClassCode,MeasureCfBasicDataNew::getRiskCode, MeasureCfBasicDataNew::getPremiumCny,MeasureCfBasicDataNew::getIniConfirm, MeasureCfBasicDataNew::getStartDate,
          MeasureCfBasicDataNew::getEndDate,MeasureCfBasicDataNew::getUnitId,MeasureCfBasicDataNew::getComCode,MeasureCfBasicDataNew::getTerm,
          MeasureCfBasicDataNew::getBusinessNature,MeasureCfBasicDataNew::getCarKindCode,MeasureCfBasicDataNew::getUseNatureCode)
        .eq(MeasureCfBasicDataNew::getValMonth, valMonth)
        .gt(MeasureCfBasicDataNew::getId, maxId)
        .orderByAsc(MeasureCfBasicDataNew::getId)
        .last("LIMIT " + BATCH_SIZE);
      List<MeasureCfBasicDataNew> records = measureCfBasicDataNewMapper.selectList(lqw);
      if (records.isEmpty()) {
        break;
      }
      log.debug("页数:{},耗时: {}ms", x++, System.currentTimeMillis() - startTime);
      // 异步处理批次数据
      processBatchAsync(records, valMonth,valMethod);
      // 更新游标
      maxId = records.get(records.size() - 1).getId();
//      processedTotal += records.size();
    }
    // 等待所有线程执行完成
//    latch.await();
    //按合同组维度分摊亏损部分到单
    int i = measureCxUnexpiredMapper.updateLossCost(valMonth, valMethod);
    log.debug("亏损分摊单，数量:{}", i);
//    log.debug("数据处理完成,数量:{}",processedTotal);
  }

  /**
   * 异步处理批次数据
   */
  private void processBatchAsync(List<MeasureCfBasicDataNew> batchData, String valMonth,String valMethod) {

    // 将参数声明为final，避免lambda表达式中的变量引用问题
    final String finalValMonth = valMonth;
    final String finalValMethod = valMethod;
    final List<MeasureCfBasicDataNew> finalBatchData = batchData;


//    threadPoolExecutor.execute(() -> {
      try {
//        log.debug("线程池队列长度: {}", threadPoolExecutor.getQueue().size());
        long startTime = System.currentTimeMillis();
        //并行流处理代替向量化计算
        List<MeasureCxUnexpired> batchResults = finalBatchData.stream()
          .map(contract -> calculateLrcWithMonthlyRolling(contract, finalValMonth,finalValMethod))
          .filter(Objects::nonNull)
          .collect(Collectors.toList());
        //批量插入结果，处理一批就提交一批事物
        long startTime2 = System.currentTimeMillis();
//        measureCxUnexpiredMapper.insertBatch(batchResults,BATCH_SIZE);
//        measureCxUnexpiredMapper.insertMyBatch(batchResults);
//        insertBatchWithJdbc(batchResults);
        insertBatchWithJdbcTemplate(batchResults);

        log.debug("批次处理完成，数据插入耗时: {}, 批次整体耗时: {} ms",
          System.currentTimeMillis() - startTime2, System.currentTimeMillis() - startTime);
      } catch (Exception e) {
        log.error("批次处理异常", e);
      } finally {
//        latch.countDown();
      }
//    });
  }

  public  void insetResult(List<MeasureCxUnexpired> batchResults){
    //批量插入数据库
    DefaultTransactionDefinition def = new DefaultTransactionDefinition();
    def.setPropagationBehavior(DefaultTransactionDefinition.PROPAGATION_REQUIRES_NEW);
    TransactionStatus status = transactionManager.getTransaction(def);
    try {
      measureCxUnexpiredMapper.insertBatch(batchResults,BATCH_SIZE);
      // 手动提交事务
      transactionManager.commit(status);
    } catch (Exception e) {
      // 发生异常时回滚事务
      transactionManager.rollback(status);
      log.error(e.getMessage(), e);
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
      "lrc_debt", "currency","create_time",
      "update_time", "is_status", "remark", "lrc_loss_direct_amt", "lrc_no_loss_direct_amt",
      "future_cash_flow", "ini_confirm", "acc_received_premiums", "risk_code","total_iacf_amt","total_iacf_direct_amt",
      "unit_id","com_code","business_nature","car_kind_code","use_nature_code",
      "acc_amortize_premiums","acc_amortize_ifie"
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
        ps.setTimestamp(index++,  new Timestamp(System.currentTimeMillis()));
        ps.setTimestamp(index++,  new Timestamp(System.currentTimeMillis()));
        ps.setString(index++, "0");
        ps.setString(index++, item.getRemark());
        ps.setBigDecimal(index++, item.getLrcLossDirectAmt());
        ps.setBigDecimal(index++, item.getLrcNoLossDirectAmt());
        ps.setBigDecimal(index++, item.getFutureCashFlow());
        ps.setString(index++, item.getIniConfirm());
        ps.setBigDecimal(index++, item.getAccReceivedPremiums());
        ps.setString(index++, item.getRiskCode());
        ps.setBigDecimal(index++, item.getTotalIacfAmt());
        ps.setBigDecimal(index++, item.getTotalIacfDirectAmt());
        ps.setString(index++, item.getUnitId());
        ps.setString(index++, item.getComCode());
        ps.setString(index++, item.getBusinessNature());
        ps.setString(index++, item.getCarKindCode());
        ps.setString(index++, item.getUseNatureCode());
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
  private MeasureCxUnexpired calculateLrcWithMonthlyRolling(MeasureCfBasicDataNew contract, String valMonth ,String valMethod) {
//    try {
      // 1. 生成签单日到评估期中，每个月有效的天数（保单起期后才有效）
      Map<String, Integer> periodMap = calculatePayments(contract.getIniConfirm(), contract.getStartDate(), valMonth, contract.getEndDate());
      //2.获取初始确认日该险类下的精算假设配置表
      Map<String, ConfMeasureActuarialAssumption> stringConfMeasureActuarialAssumptionMap = assumptionCache
        .get(DateUtils.parseDateToStr(DateUtils.YYYYMM,  DateUtils.parseDate(contract.getIniConfirm())));
      ConfMeasureActuarialAssumption iniConfirmAssumption = stringConfMeasureActuarialAssumptionMap.get(contract.getClassCode());
      if (iniConfirmAssumption == null) {
        log.error("初始确认日{}该险类{}下的精算假设配置表不存在", contract.getUnderWriteDate(), contract.getClassCode());
      }
      //获取评估时点该险类下的精算假设配置表
      Map<String, ConfMeasureActuarialAssumption> currentConfMeasureActuarialAssumptionMap = assumptionCache.get(valMonth);
      ConfMeasureActuarialAssumption assumption = currentConfMeasureActuarialAssumptionMap.get(contract.getClassCode());
      //3.定义变量存储滚动累计值
      //未满期保费
      BigDecimal futurePremiums = BigDecimal.ZERO;
      //累计实收保费
      BigDecimal cumulativeReceivedPremiums = BigDecimal.ZERO;
      // 累计确认的保费
      BigDecimal cumulativePremiums = BigDecimal.ZERO;
      //累计摊销的签单保费（不含利息）
      BigDecimal accAmortizePremiums = BigDecimal.ZERO;
      //累计摊销的IFIE
      BigDecimal accAmortizeIfie = BigDecimal.ZERO;
      //累计确认的获取费用（不含利息）
      BigDecimal cumulativeIacf = BigDecimal.ZERO;
      //TODO 累计确认的获取费用（跟单）
      BigDecimal cumulativeIacfDirect = BigDecimal.ZERO;
      //未到期累计利息
      BigDecimal cumulativeIfie = BigDecimal.ZERO;
      //TODO 未到期累计利息（跟单）
      BigDecimal cumulativeIfieDirect = BigDecimal.ZERO;
      //累计确认的投资成分
      BigDecimal cumulativeInvestment = BigDecimal.ZERO;
      //累计减值
      BigDecimal cumulativeLoss = BigDecimal.ZERO;
      //未到期期初余额
      BigDecimal openingBalance = BigDecimal.ZERO;
      //TODO 未到期期初余额（跟单）
      BigDecimal openingBalanceDirect = BigDecimal.ZERO;
      //期末非亏
      BigDecimal closingBalance = BigDecimal.ZERO;
      //TODO 期末非亏（跟单）
      BigDecimal closingBalanceDirect = BigDecimal.ZERO;
      //保单保障期限
      Integer term = contract.getTerm();
      //已服务天数
      int servedDays = 0;
      // 过渡期采用获取费用（跟单+非跟单） = 保费 * 精算假设获取费用率
      BigDecimal iacfCashflow = contract.getPremiumCny().multiply(iniConfirmAssumption.getAcquisitionExpenseRatio()).setScale(10, RoundingMode.HALF_UP);
      //TODO 前海特有，跟单获取费用=签单保费 * 精算假设首日获取费用率
      BigDecimal iacfCashflowDirect = contract.getPremiumCny().multiply(iniConfirmAssumption.getFirstDayAcquisitionExpenseRatio()).setScale(10, RoundingMode.HALF_UP);
      //下标记录记录当前滚动的月份数
      int x = 0;
      //I17初始确认日到止期经过的月份数
      int monthsNum = DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(contract.getIniConfirm()),
        DateUtils.parseDate(contract.getEndDate())) + 1;
      if(monthsNum >= 720){
        contract.setIsStatus("3");
        contract.setRemark("初始确认日到保单止期超过720个月");
        log.error("保单数据{}，初始确认日到保单止期超过720个月",contract);
        return null;
      }
      //初始确认日对应的月利率曲线
      Map<Integer, BigDecimal> initMonthRateMap = disRateCache.getOrDefault(DateUtils.parseDateToStr(DateUtils.YYYYMM,
        DateUtils.parseDate(contract.getIniConfirm())), new HashMap<>());
      // 从缓存中获取该保单的实收保费数据
      String key=contract.getPolicyNo()+"_"+contract.getCertiNo();
      Map<String, BigDecimal> payOffMonthData = payOffMonthCache.getOrDefault(key, new HashMap<>());
      // 5. 遍历确认确认日到评估时点经过天数数组，逐月滚动计量
      for (Map.Entry<String, Integer> entry : periodMap.entrySet()) {
        x++;
        //初始确认日到当前滚动的月份数对应的月度远期利率
        BigDecimal disRate = initMonthRateMap.getOrDefault(x, BigDecimal.ZERO);
        //当期支出的获取费用
        BigDecimal iacfCashflowCurrent = BigDecimal.ZERO;
        //TODO 当期支出的获取费用（跟单）
        BigDecimal iacfCashflowCurrentDirect = BigDecimal.ZERO;
        // 获取费用利息
        BigDecimal iacfCashflowIfie = BigDecimal.ZERO;
        BigDecimal iacfCashflowDirectIfie = BigDecimal.ZERO;
        //实收保费
        BigDecimal premiumCashflow = payOffMonthData.getOrDefault(entry.getKey(), BigDecimal.ZERO);
        //TODO 过渡期获取费用假设在第一期就全部支出
        if (x == 1) {
          iacfCashflowCurrent = iacfCashflow;
          iacfCashflowCurrentDirect = iacfCashflowDirect;
          //获取费用利息=预期支付获取费用总额 * 利率
          iacfCashflowIfie = iacfCashflow.multiply(disRate).multiply(INVESTMENT_RATIO).setScale(10, RoundingMode.HALF_UP);
          //TODO 前海特有 跟单获取费用利息=预期支付获取费用跟单 * 利率
          iacfCashflowDirectIfie = iacfCashflowDirect.multiply(INVESTMENT_RATIO).multiply(disRate).setScale(10, RoundingMode.HALF_UP);
          //TODO 前海特有，PACK开头的保单在核销表里面没有，默认在期初就全部收到保费
          if(contract.getPolicyNo().startsWith("PACK")){
            premiumCashflow = contract.getPremiumCny();
          }else {
            //如果是第一期，则找收到保费时间小于等于当前滚动期间的保费
            premiumCashflow = payOffMonthData.entrySet().stream()
              .filter(e -> e.getKey() != null && e.getKey().compareTo(entry.getKey()) <= 0)
              .map(Map.Entry::getValue)
              .reduce(BigDecimal.ZERO, BigDecimal::add);
          }
        }
        //累计实收保费
        cumulativeReceivedPremiums = cumulativeReceivedPremiums.add(premiumCashflow);

        //累计服务量=起期至当前评估时点经过天数
        servedDays += entry.getValue();
        BigDecimal cumulativeProportion = term > 0 ?
          new BigDecimal(servedDays).divide(new BigDecimal(term), 10, RoundingMode.HALF_UP) :
          BigDecimal.ZERO;
        // 确保比例不超过1
        if (cumulativeProportion.compareTo(BigDecimal.ONE) > 0) {
          log.error("错误，累计服务量比例不能大于1,contract:{}", JSON.toJSONString(contract));
        }

        //TODO 投资成分改成不折现
        //投资成分
        BigDecimal investmentValue = contract.getPremiumCny().multiply(INVESTMENT_RATIO).setScale(10, RoundingMode.HALF_UP);
        //当期确认的投资成分现值=投资成分月末现值*累计服务量比例-累计确认的投资成分月末现值
//      BigDecimal discountRate = getDiscountRate(initMonthRateMap, x+1, monthsNum);
        //投资成分现值
//      BigDecimal investmentAmt= investmentValue.multiply(discountRate).setScale(10, RoundingMode.HALF_UP);
        //当期确认的投资成分
        BigDecimal currentInvestment = investmentValue.multiply(cumulativeProportion).subtract(cumulativeInvestment).setScale(10, RoundingMode.HALF_UP);
        //累计确认的投资成分
        cumulativeInvestment = cumulativeInvestment.add(currentInvestment).setScale(10, RoundingMode.HALF_UP);

        //期初未到期计息=未到期期初余额 * 对应月度远期利率
        BigDecimal openingBalanceIfie = openingBalance.multiply(disRate).setScale(10, RoundingMode.HALF_UP);
        //TODO 前海特有 未到期期初余额（跟单）
        BigDecimal openingBalanceDirectIfie = openingBalanceDirect.multiply(disRate).multiply(IFIE_RATIO).setScale(10, RoundingMode.HALF_UP);
        //实收保费计息=实收保费 * 对应月度远期利率
        BigDecimal premiumCashflowIfie = premiumCashflow.multiply(disRate).multiply(IFIE_RATIO).setScale(10, RoundingMode.HALF_UP);
        //当期未到期计息=期初未到期计息+实收保费计息-获取费用利息
        BigDecimal currentIfie = openingBalanceIfie.add(premiumCashflowIfie).subtract(iacfCashflowIfie);
        //累计未到期计息
        cumulativeIfie = cumulativeIfie.add(currentIfie);
        //TODO 前海特有 未到期累计利息（跟单）
        BigDecimal currentIfieDirect = openingBalanceDirectIfie.add(premiumCashflowIfie).add(iacfCashflowDirectIfie);
        //累计未到期计息（跟单）
        cumulativeIfieDirect = cumulativeIfieDirect.add(currentIfieDirect);

        //当期确认保费收入=（总保费+累计未到期计息）* 累计服务比例 - 累计确认保费收入
        BigDecimal currentPremiums = (contract.getPremiumCny().add(cumulativeIfie)).multiply(cumulativeProportion).subtract(cumulativePremiums).setScale(10, RoundingMode.HALF_UP);
        //当期摊销的单单保费（不含利息）=总保费 * 累计服务比例 -累计摊销的单单保费（不含利息）
        BigDecimal currentAmortizePremiums = contract.getPremiumCny().multiply(cumulativeProportion).subtract(accAmortizePremiums).setScale(10, RoundingMode.HALF_UP);
        //当期摊销的IFIE=累计未到期计息 * 累计服务比例 -累计摊销的IFIE
        BigDecimal currentAmortizeIfie = cumulativeIfie.multiply(cumulativeProportion).subtract(accAmortizeIfie).setScale(10, RoundingMode.HALF_UP);

        //累计确认保费收入
        cumulativePremiums = cumulativePremiums.add(currentPremiums);
        //累计摊销的单单保费（不含利息）
        accAmortizePremiums = accAmortizePremiums.add(currentAmortizePremiums);
        //累计摊销的IFIE
        accAmortizeIfie = accAmortizeIfie.add(currentAmortizeIfie);

        //当期确认获取费用=预期支付获取费用总额 * 累计服务比例 -累计确认获取费用
        BigDecimal currentIacf = iacfCashflow.multiply(cumulativeProportion).subtract(cumulativeIacf).setScale(10, RoundingMode.HALF_UP);
        //累计确认获取费用
        cumulativeIacf = cumulativeIacf.add(currentIacf);

        //TODO 前海特有 当期确认获取费用（跟单）
        BigDecimal currentIacfDirect = iacfCashflowDirect.multiply(cumulativeProportion).subtract(cumulativeIacfDirect).setScale(10, RoundingMode.HALF_UP);
        //累计确认获取费用（跟单）
        cumulativeIacfDirect = cumulativeIacfDirect.add(currentIacfDirect);

        // LRC非亏损部分期末余额=未到期期初余额+实收保费-支付的获取费用（默认期初一次性支付）+未到期计息-当期确认的保费收入摊销+当期确认的获取费用摊销
        closingBalance = openingBalance
          .add(premiumCashflow)
          .subtract(iacfCashflowCurrent)
          .add(currentIfie)
          .subtract(currentPremiums)
          .add(currentIacf);
        // 更新期初余额
        openingBalance = closingBalance;

        //TODO 前海特有 LRC非亏损部分期末余额（跟单）
        closingBalanceDirect = openingBalanceDirect
          .add(premiumCashflow)
          .subtract(iacfCashflowCurrentDirect)
          .add(currentIfieDirect)
          .subtract(currentPremiums)
          .add(currentIacfDirect);
        //TODO 前海特有 未到期期初余额（跟单）
        openingBalanceDirect = closingBalanceDirect;

        // 未来服务量比例
        BigDecimal futureProportion = BigDecimal.ONE.subtract(cumulativeProportion).max(BigDecimal.ZERO);
        //未满期保费
        futurePremiums = contract.getPremiumCny().multiply(futureProportion).setScale(10, RoundingMode.HALF_UP);
//      log.debug("期间：{},实收保费:{},当期确认保费:{},支付获取费用:{},当期获取费用:{},,跟单获取费用：{}，当期跟单获取费用:{},利息：{},跟单利息：{},期初余额：{}，跟单期初余额：{},非亏:{},跟单非亏:{},未满期保费：{}",
//        entry.getKey(),premiumCashflow,currentPremiums,iacfCashflowCurrent,currentIacf,iacfCashflowCurrentDirect,currentIacfDirect,currentIfie,currentIfieDirect,openingBalance,openingBalanceDirect,closingBalance,closingBalanceDirect,futurePremiums);
      }
      //计算大于止期后收到的保费（保单失效后不计息）
//      BigDecimal expiredPremium = payOffMonthData.entrySet().stream()
//        .filter(e -> e.getKey() != null && e.getKey().compareTo(contract.getEndDate().substring(0, 6)) > 0)
//        .map(Map.Entry::getValue)
//        .reduce(BigDecimal.ZERO, BigDecimal::add);
//      closingBalance = closingBalance.add(expiredPremium);
//      closingBalanceDirect = closingBalanceDirect.add(expiredPremium);

      //5.计算亏损部分
      ArrayList<BigDecimal> lossCashFlowList = new ArrayList<>();
      ArrayList<BigDecimal> maintenanceCashFlowList = new ArrayList<>();
      //预期未来应收保费=签单保费-累计实收保费
      BigDecimal futureUnearned = contract.getPremiumCny().subtract(cumulativeReceivedPremiums);
      //预期未来赔付费用 = 未满期保费*精算假设赔付率*（1+间接理赔费用率）
      BigDecimal futureLoss = futurePremiums.multiply(assumption.getLossRatio()).multiply(assumption.getIndirectClaimsExpenseRatio().add(BigDecimal.ONE)).setScale(10, RoundingMode.HALF_UP);
      //预期未来赔付现值 = 预期未来赔付费用均摊到剩余期间，根据赔付模式配置表展开乘进展因子后再折现
      BigDecimal pvFutureLoss = getPvLoss(futureLoss, contract.getClassCode(), monthsNum - x, valMonth, lossCashFlowList, contract);
      //预期未来维持费用 = 未满期保费*精算假设维持费用率
      BigDecimal futureMaintenance = futurePremiums.multiply(assumption.getMaintenanceExpenseRatio()).setScale(10, RoundingMode.HALF_UP);
      //预期未来维持费用现值 = 预期未来维持费用均摊到剩余期间在折现
      BigDecimal pvFutureMaintenance = getPvMaintenance(futureMaintenance, monthsNum - x, valMonth, maintenanceCashFlowList);
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
      BigDecimal netFutureCashFlowDirect = futureCashFlow.subtract(closingBalanceDirect);
      // 亏损部分保费为正Max(0, netFutureCashFlow)，保费为负Min(0, netFutureCashFlow)
      BigDecimal lossComponentDirect = BigDecimal.ZERO;
      if (contract.getPremiumCny().compareTo(BigDecimal.ZERO) >= 0) {
        lossComponentDirect = netFutureCashFlowDirect.compareTo(BigDecimal.ZERO) > 0 ? netFutureCashFlowDirect : BigDecimal.ZERO;
      } else {
        lossComponentDirect = netFutureCashFlowDirect.compareTo(BigDecimal.ZERO) < 0 ? netFutureCashFlowDirect : BigDecimal.ZERO;
      }

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
      measureCxUnexpired.setTerm(Long.valueOf(term));
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
      //累计计息_跟单部分
      measureCxUnexpired.setAccIfieDirectAmt(cumulativeIfieDirect);
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
      measureCxUnexpired.setLrcNoLossDirectAmt(closingBalanceDirect);
      //未到期亏损部分
      measureCxUnexpired.setLrcLossAmt(lossComponent);
      //TODO 未到期亏损部分（跟单）
      measureCxUnexpired.setLrcLossDirectAmt(lossComponentDirect);
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
      //TODO 总跟单费用
      measureCxUnexpired.setTotalIacfDirectAmt(iacfCashflowDirect);
      //累计获取费用_跟单部分
      measureCxUnexpired.setAccIacfDirectAmt(cumulativeIacfDirect);
      //累计摊销的单单保费（不含利息）
      measureCxUnexpired.setAccAmortizePremiums(accAmortizePremiums);
      //累计摊销的IFIE
      measureCxUnexpired.setAccAmortizeIfie(accAmortizeIfie);
      return measureCxUnexpired;
//    }catch (Exception e){
//      log.error("未到期计量计算异常:{},保单数据:{}",e,JSON.toJSONString(contract));
//    }
//    return null;
  }

  /**
   *根据赔付模式进度因子数组计算
   * 例如赔付模式进度因子数组为[0.05, 0.95]，金额是600，均分成6期
   * [5, 95, 0, 0, 0, 0, 0]
   * [0, 5, 95, 0, 0, 0, 0]
   * [0, 0, 5, 95, 0, 0, 0]
   * [0, 0, 0, 5, 95, 0, 0]
   * [0, 0, 0, 0, 5, 95, 0]
   * [0, 0, 0, 0, 0, 5, 95]
   * 结果result[5,100,100,100,100,100,95],再对result折现
   *
   * @param amt 预期未来赔付费用
   * @param classCode 险类代码
   * @param n 均摊次数
   * @return
   */
  private BigDecimal getPvLoss(BigDecimal amt,String classCode,int n,String valMonth,List<BigDecimal> cashFlowList,MeasureCfBasicDataNew contract) {
    if(BigDecimal.ZERO.compareTo(amt) == 0) {
      return BigDecimal.ZERO;
    }
    if(n <= 0 ){
      log.error("==============剩余期间:{},未满期保费:{},保单数据:{}",n,amt,JSON.toJSONString(contract));
    }
    Map<Integer, BigDecimal> monthsRateMap = disRateCache.getOrDefault(valMonth,new HashMap<>());
    BigDecimal[] claimFactorArr = discountFactorCache.get(classCode);
    BigDecimal[] claimFactor = Arrays.copyOf(claimFactorArr, claimFactorArr.length);
    BigDecimal avgAmt = amt.divide(new BigDecimal(n), 10, RoundingMode.HALF_UP);
    for(int i=0;i<claimFactor.length;i++){
      claimFactor[i] = avgAmt.multiply(claimFactor[i]).setScale(10, RoundingMode.HALF_UP);
    }
    //右移次数
    int k = n-1;
    BigDecimal[] prefix = new BigDecimal[claimFactor.length + 1];
    int resultLength =  claimFactor.length + k; // 结果数组长度
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
      result[j] = prefix[end + 1].subtract(prefix[start]) ;
    }
    //折现到当前评估时点
    BigDecimal product = BigDecimal.ONE;
    BigDecimal pvLoss = BigDecimal.ZERO;
    for (int i = 0; i < result.length; i++) {
      product = product.multiply(monthsRateMap.get(i+1).add(BigDecimal.ONE)).setScale(10, RoundingMode.HALF_UP);
      result[i] = result[i].divide(product,10, RoundingMode.HALF_UP);
      pvLoss = pvLoss.add(result[i]);
//      cashFlowList.add(result[i].setScale(2, RoundingMode.HALF_UP));
    }
    return pvLoss;
  }

  /**
   * 未来维持费用折现
   * @param amt 预期未来维持费用
   * @param n 均摊次数
   * @return
   */
  private BigDecimal getPvMaintenance(BigDecimal amt,int n,String valMonth,List<BigDecimal> cashFlowList) {
    if(BigDecimal.ZERO.compareTo(amt) == 0) {
      return BigDecimal.ZERO;
    }
    Map<Integer, BigDecimal> monthsRateMap = disRateCache.getOrDefault(valMonth,new HashMap<>());
    BigDecimal arr[] = new BigDecimal[n];
    for(int i=0;i<n;i++){
      arr[i] = amt.divide(new BigDecimal(n), 10, RoundingMode.HALF_UP);
    }
    //折现到当前评估时点
    BigDecimal product = BigDecimal.ONE;
    BigDecimal pvMaintenance = BigDecimal.ZERO;
    for (int i = 0; i < arr.length; i++) {
      product = product.multiply(monthsRateMap.get(i+1).add(BigDecimal.ONE)).setScale(10, RoundingMode.HALF_UP);
      arr[i] = arr[i].divide(product,10, RoundingMode.HALF_UP);
      pvMaintenance = pvMaintenance.add(arr[i]);
//      cashFlowList.add(arr[i].setScale(2, RoundingMode.HALF_UP));
    }
    return pvMaintenance;
  }

  /**
   * 投资成分折现
   * @param startBigDecimalMap 保险责任起期对应的月度远期利率曲线
   * @param startId 起点期间
   * @param endId 终点期间
   * @return
   */
  private BigDecimal getDiscountRate(Map<Integer, BigDecimal> startBigDecimalMap,int startId,int endId) {
    BigDecimal discountRate = BigDecimal.ONE;
    for (int i = startId; i <= endId; i++) {
      discountRate = discountRate.multiply(BigDecimal.ONE.add(startBigDecimalMap.getOrDefault(i,BigDecimal.ZERO))).setScale(10, RoundingMode.HALF_UP);
    }
    return BigDecimal.ONE.divide(discountRate,10, RoundingMode.HALF_UP);
  }

  /**
   * 计算24年有效果的保单
   * @param iniConfirm 签单日期
   * @param start 保险责任起期
   * @param valMonth 评估日期
   * @param end 保证责任止期
   * @return 从签单日期到min（评估期，止期）每个月的有效服务天数
   */
  public static Map<String, Integer> calculatePayments(String iniConfirm, String start, String valMonth, String end) {
    LocalDate iniConfirmDate = LocalDate.parse(DateUtils.parseDateToStr(DateUtils.YYYY_MM_DD, DateUtils.parseDate(iniConfirm)));
    LocalDate startDate = LocalDate.parse(DateUtils.parseDateToStr(DateUtils.YYYY_MM_DD, DateUtils.parseDate(start)));
    LocalDate parseValMonth = LocalDate.parse(DateUtils.parseDateToStr(DateUtils.YYYY_MM_DD, DateUtils.endMonth(valMonth)));
    LocalDate parseEnd = LocalDate.parse(DateUtils.parseDateToStr(DateUtils.YYYY_MM_DD, DateUtils.parseDate(end)));
    //评估期和保险止期取早
    LocalDate effectiveEndDate = parseValMonth.isBefore(parseEnd) ? parseValMonth : parseEnd;

    YearMonth initMonth = YearMonth.from(iniConfirmDate);
    YearMonth startMonth = YearMonth.from(startDate);
    YearMonth endMonth = YearMonth.from(effectiveEndDate);
    Map<String, Integer> result = new LinkedHashMap<>();
    Boolean isFirst = true;

    for (YearMonth ym = initMonth; !ym.isAfter(endMonth); ym = ym.plusMonths(1)) {
      LocalDate monthStart = ym.atDay(1);
      LocalDate monthEnd = ym.atEndOfMonth();
      //取min(当前期间月末,结束日期)
      LocalDate monthEndDate = monthEnd.isBefore(effectiveEndDate) ? monthEnd : effectiveEndDate;
      long days = 0L;
      //如果签单日期早于起期
      if(ym.isBefore(startMonth)){
        days =  0L;
      }
      if(ym.isAfter(startMonth)){
        days =  ChronoUnit.DAYS.between(monthStart, monthEndDate) + 1;
      }
      //如果签单日期晚于起期
      if(ym.equals(startMonth) || (iniConfirmDate.isAfter(startDate))&&isFirst){
        days =  ChronoUnit.DAYS.between(startDate, monthEndDate) + 1;
        isFirst =false;
      }

      result.put(ym.format(YYYYMM_FORMATTER), (int) days);
    }

    return result;
  }

  /**
   * 计算指定月份在[startDate, endDate]区间内的天数
   */
  private static int calculateDaysInMonth(LocalDate startDate, LocalDate endDate, YearMonth month) {
    LocalDate monthStart = month.atDay(1);
    LocalDate monthEnd = month.atEndOfMonth();

    // 计算交集区间
    LocalDate intervalStart = monthStart.isBefore(startDate) ? startDate : monthStart;
    LocalDate intervalEnd = monthEnd.isAfter(endDate) ? endDate : monthEnd;

    // 如果没有交集，返回0
    if (intervalStart.isAfter(intervalEnd)) {
      return 0;
    }

    // 计算天数差（包含两端）
    return (int) (intervalEnd.toEpochDay() - intervalStart.toEpochDay() + 1);
  }

  public static String addMonths(String valMonth, int n) {
    if (valMonth == null || valMonth.length() != 6) {
      throw new IllegalArgumentException("输入日期格式不正确，应为 yyyymm 格式");
    }
    try {
      YearMonth date = YearMonth.parse(valMonth, YYYYMM_FORMATTER);
      YearMonth newDate = date.plusMonths(n);
      return newDate.format(YYYYMM_FORMATTER);
    } catch (Exception e) {
      throw new IllegalArgumentException("无法解析日期: " + valMonth, e);
    }
  }

  /**
   * 清理缓存
   */
  private void clearCache() {
    discountFactorCache.clear();
    assumptionCache.clear();
    disRateCache.clear();
    payOffMonthCache.clear();
    log.info("缓存清理完成");
  }
}

