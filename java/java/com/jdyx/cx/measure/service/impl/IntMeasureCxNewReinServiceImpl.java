package com.jdyx.cx.measure.service.impl;

import cn.hutool.core.lang.Opt;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.CollectionUtils;
import com.baomidou.mybatisplus.core.toolkit.IdWorker;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.jdyx.common.measure.constant.StringConstant;
import com.jdyx.cx.measure.service.IntMeasureCxNewReinService;
import com.jdyx.measure.api.measure.domain.ConfMeasureActuarialAssumption;
import com.jdyx.measure.api.measure.domain.ConfMeasureClaimModelNew;
import com.jdyx.measure.api.measure.domain.ConfMeasureMonthDisrate;
import com.jdyx.measure.api.measure.domain.IntMeasureCxUnexpiredRein;
import com.jdyx.measure.api.measure.mapper.*;
import com.jdyx.measureprepare.api.domain.IntTPpReMonArrNew;
import com.jdyx.measureprepare.api.domain.dto.IntTPpReMonArrInNewCombine;
import com.jdyx.measureprepare.api.domain.dto.IntTPpReMonArrNewCombine;
import com.jdyx.measureprepare.api.mapper.IntTPpReMonArrInNewMapper;
import com.jdyx.measureprepare.api.mapper.IntTPpReMonArrNewMapper;
import com.kevin.common.core.domain.R;
import com.kevin.common.utils.DateUtils;
import com.kevin.common.utils.StringUtils;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.time.DateFormatUtils;
import org.apache.ibatis.cursor.Cursor;
import org.springframework.jdbc.core.BatchPreparedStatementSetter;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import javax.annotation.Resource;
import java.io.IOException;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.LocalDate;
import java.time.YearMonth;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.time.temporal.TemporalAdjusters;
import java.util.*;
import java.util.stream.Collectors;

/**
 * LRC计量服务实现类
 */
@Slf4j
@RequiredArgsConstructor
@Service
public class IntMeasureCxNewReinServiceImpl implements IntMeasureCxNewReinService {

  // --- 常量定义 ---
  private static final int SCALE = 10; // 统一的计算精度
  private static final RoundingMode ROUNDING_MODE = RoundingMode.HALF_UP; // 统一的舍入模式
  private static final int MAX_MONTH_COUNT = 720; // 最大月数限制
  private static final long BATCH_SIZE = 10000L; // 分批处理大小（按ID游标分页）

  private static final DateTimeFormatter YYYYMM_FORMATTER = DateTimeFormatter.ofPattern("yyyyMM");
  private static final DateTimeFormatter YYYYMMDD_FORMATTER = DateTimeFormatter.ofPattern("yyyyMMdd");
  public static final String YYYYMMDD = "yyyyMMdd";

  @Resource
  private ConfMeasureActuarialAssumptionMapper confMeasureActuarialAssumptionMapper;
  @Resource
  private ConfMeasureClaimModelNewMapper measureClaimModelNewMapper;
  @Resource
  private IntMeasureCxUnexpiredReinMapper intMeasureCxUnexpiredReinMapper;
  @Resource
  private ConfMeasureMonthDisrateMapper measureMonthDisrateMapper;

  @Resource
  private JdbcTemplate jdbcTemplate;

  @Resource
  private IntTPpReMonArrInNewMapper intTPpReMonArrInNewMapper;

  @Resource
  private IntTPpReMonArrNewMapper intTPpReMonArrNewMapper;

  @Resource
  private MeasureResultAccountingScenarioAccountMapper accountingScenarioAccountMapper;


  @Override
  @Transactional(rollbackFor = Exception.class)
  public R<?> getGdqLrcReinInMeasureResult(String valMethod, String valMonth) {
    log.info("开始LRC计量计算（简化版），评估方法: {}, 评估月份: {}", valMethod, valMonth);
    long startTime = System.currentTimeMillis();

    // ==================== 1. 读取和处理配置数据 ====================
    // 1.1 加载精算假设数据
    LambdaQueryWrapper<ConfMeasureActuarialAssumption> assumptionQuery = Wrappers.lambdaQuery();
    assumptionQuery.eq(ConfMeasureActuarialAssumption::getValMethod, valMethod);
    List<ConfMeasureActuarialAssumption> assumptions = confMeasureActuarialAssumptionMapper.selectList(assumptionQuery);
    Map<String, Map<String, ConfMeasureActuarialAssumption>> assumptionMap = assumptions.stream()
      .collect(Collectors.groupingBy(
        ConfMeasureActuarialAssumption::getValMonth,
        Collectors.toMap(
          ConfMeasureActuarialAssumption::getClassCode,
          item -> item,
          (existing, replacement) -> replacement // 处理重复键：保留新值
        )
      ));
    log.info("加载精算假设数据 {} 条", assumptions.size());

    // 1.2 加载赔付模式数据
    List<ConfMeasureClaimModelNew> claimModels = measureClaimModelNewMapper.selectList(null);
    Map<String, BigDecimal[]> discountFactor = claimModels.stream()
      .collect(Collectors.groupingBy(
        ConfMeasureClaimModelNew::getClassCode,
        Collectors.collectingAndThen(
          Collectors.toList(),
          list -> {
            list.sort(Comparator.comparingInt(ConfMeasureClaimModelNew::getMonthId));
            return list.stream()
              .map(ConfMeasureClaimModelNew::getPaidRatio)
              .toArray(BigDecimal[]::new);
          }
        )
      ));
    log.info("加载赔付模式数据 {} 条", claimModels.size());

    // 1.3 加载月度远期利率
    List<ConfMeasureMonthDisrate> disrates = measureMonthDisrateMapper.selectList(null);
    Map<String, Map<Integer, BigDecimal>> disRateMap = disrates.stream()
      .collect(Collectors.groupingBy(ConfMeasureMonthDisrate::getValMonth,
        Collectors.toMap(ConfMeasureMonthDisrate::getTermMonth, ConfMeasureMonthDisrate::getForwardDisrateValue, (v1, v2) -> v1)));

    log.info("加载月度远期利率数据 {} 条", disRateMap.size());
    long configTime = System.currentTimeMillis();
    log.info("读取和处理配置数据完成，耗时: {} 秒", (configTime - startTime) / 1000.0);


    List<IntTPpReMonArrInNewCombine> allContracts = intTPpReMonArrInNewMapper.selectCombineUnExpried(valMonth, valMethod);
    long readDataTime = System.currentTimeMillis();
    log.info("读取源数据 {} 条，耗时: {} 秒", allContracts.size(), (readDataTime - configTime) / 1000.0);
    if (allContracts.isEmpty()) {
      log.warn("未找到需要处理的源数据，计算提前结束。");
      return R.ok("未找到需要处理的源数据");
    }

    List<IntMeasureCxUnexpiredRein> allResults = new ArrayList<>(allContracts.size());
    for (IntTPpReMonArrInNewCombine contract : allContracts) {
      IntMeasureCxUnexpiredRein result = calculateLrcReinInWithMonthlyRolling(contract, valMonth, assumptionMap, discountFactor, disRateMap);
      if (result != null) {
        allResults.add(result);
      }
    }
    long logicTime = System.currentTimeMillis();
    log.info("业务逻辑处理完成，耗时: {} 秒", (logicTime - readDataTime) / 1000.0);

    // ==================== 4. 插入数据 ====================
    // 4.1 清空当期数据
    intMeasureCxUnexpiredReinMapper.delete(new LambdaQueryWrapper<IntMeasureCxUnexpiredRein>()
      .eq(IntMeasureCxUnexpiredRein::getValMonth, valMonth)
      .eq(IntMeasureCxUnexpiredRein::getValMethod, valMethod));

    // 4.2 计算分摊到单的亏损
    if (CollectionUtils.isNotEmpty(allResults)) {
      calculateLossComponentAllocation(allResults);
    }

    // 4.3 批量插入结果
    if (CollectionUtils.isNotEmpty(allResults)) {
      insertBatchWithJdbcTemplate(allResults);
    }
    long insertTime = System.currentTimeMillis();
    log.info("批量插入数据 {} 条，耗时: {} 秒", allResults.size(), (insertTime - logicTime) / 1000.0);
    log.info("LRC计量计算全部完成，总耗时: {} 秒", (System.currentTimeMillis() - startTime) / 1000.0);
    return R.ok();
  }

  @Override
  @Transactional(rollbackFor = Exception.class)
  public R<?> getGdqLrcReinOutMeasureResult(String valMethod, String valMonth) throws IOException {
    log.info("开始LRC计量计算（简化版），评估方法: {}, 评估月份: {}", valMethod, valMonth);
    long startTime = System.currentTimeMillis();

    // ==================== 0. 先清空当期数据 ====================
    intMeasureCxUnexpiredReinMapper.delete(new LambdaQueryWrapper<IntMeasureCxUnexpiredRein>()
      .eq(IntMeasureCxUnexpiredRein::getValMonth, valMonth)
      .eq(IntMeasureCxUnexpiredRein::getValMethod, valMethod));
    log.info("已清空当期数据: valMonth={}, valMethod={}", valMonth, valMethod);

    // ==================== 1. 读取和处理配置数据 ====================

    // 1.1 加载月度远期利率
    List<ConfMeasureMonthDisrate> disrates = measureMonthDisrateMapper.selectList(null);
    Map<String, Map<Integer, BigDecimal>> disRateMap = disrates.stream()
      .collect(Collectors.groupingBy(ConfMeasureMonthDisrate::getValMonth,
        Collectors.toMap(ConfMeasureMonthDisrate::getTermMonth, ConfMeasureMonthDisrate::getForwardDisrateValue, (v1, v2) -> v1)));
    log.info("加载月度远期利率数据 {} 条", disRateMap.size());

    // 1.2 加载历史亏损分摊数据
    List<Map<String, Object>> resultAllocationList = intMeasureCxUnexpiredReinMapper.getMeasureAllocationCache(valMonth);
    Map<String, Map<String, BigDecimal>> resultAllocationMapMap = resultAllocationList.stream()
      .filter(map -> map.get("lossComponentAllocation") != null) // 关键：过滤掉值为null的条目
      .filter(map -> map.get("premium") != null) // 新增：过滤premium为null
      .collect(Collectors.toMap(
        row -> (String) row.get("groupKey"),
        row -> {
          Map<String, BigDecimal> innerMap = new HashMap<>();
          innerMap.put("lossComponentAllocation", (BigDecimal) row.get("lossComponentAllocation"));
          innerMap.put("premium", (BigDecimal) row.get("premium"));
          return innerMap;
        }
      ));
    log.info("加载历史亏损分摊数据 {} 条", resultAllocationList.size());

    long configTime = System.currentTimeMillis();
    log.info("读取和处理配置数据完成，耗时: {} 秒", (configTime - startTime) / 1000.0);

    LambdaQueryWrapper<IntTPpReMonArrNew> countQuery = Wrappers.lambdaQuery();
    countQuery.eq(IntTPpReMonArrNew::getValMethod, valMethod)
      .eq(IntTPpReMonArrNew::getValMonth, valMonth);
    Long totalCount = intTPpReMonArrNewMapper.selectCount(countQuery);

    // ==================== 2. 准备流式查询 ====================
    log.info("源数据总量 {} 条，准备开始流式处理...", totalCount);
    long readDataTime = System.currentTimeMillis();

// ==================== 3. 流式处理与分批插入 ====================
    long processed = 0L;
    long totalInserted = 0L;
    List<IntMeasureCxUnexpiredRein> batchResults = new ArrayList<>((int) BATCH_SIZE);
    try (Cursor<IntTPpReMonArrNewCombine> cursor = intTPpReMonArrNewMapper.streamQuery(valMonth, valMethod)) {
      for (IntTPpReMonArrNewCombine contract : cursor) {
        IntMeasureCxUnexpiredRein result = calculateLrcReinOutWithMonthlyRolling(contract, valMonth, disRateMap, resultAllocationMapMap);
        if (result != null) {
          batchResults.add(result);
        }

        if (batchResults.size() >= BATCH_SIZE) {
          int currentBatchSize = batchResults.size();
          log.info("--> 批次已满 ({} 条)，准备执行插入...", currentBatchSize);
          insertBatchWithJdbcTemplate(batchResults);
          totalInserted += currentBatchSize;
          batchResults.clear();
          log.info("==> 插入批次成功：插入 {} 条数据，累计已插入 {} 条。", currentBatchSize, totalInserted);
        }

        processed++; // processed 自增

        if (processed % 100000 == 0) {
          log.info("--> 已流式处理 {} / {} 条数据。", processed, totalCount);
        }
      }
    } // try-with-resources 语法会确保cursor在这里被自动关闭

    // 处理最后一批不足 BATCH_SIZE 的数据
    if (CollectionUtils.isNotEmpty(batchResults)) {
      insertBatchWithJdbcTemplate(batchResults);
      totalInserted += batchResults.size();
      batchResults.clear();
    }

    long insertTime = System.currentTimeMillis();
    log.info("全部批次处理与插入完成，总计处理 {} 条，插入 {} 条，耗时: {} 秒", processed, totalInserted, (insertTime - readDataTime) / 1000.0);
    log.info("LRC计量计算全部完成，总耗时: {} 秒", (System.currentTimeMillis() - startTime) / 1000.0);
    return R.ok();
  }

  @Override
  @Transactional(rollbackFor = Exception.class)
  public R<?> getLrcReinInMeasureByMonthResult(String valMethod, String valMonth) {
    log.info("开始LRC计量计算（简化版），评估方法: {}, 评估月份: {}", valMethod, valMonth);
    long startTime = System.currentTimeMillis();

    // ==================== 1. 读取和处理配置数据 ====================
    // 1.1 加载精算假设数据
    LambdaQueryWrapper<ConfMeasureActuarialAssumption> assumptionQuery = Wrappers.lambdaQuery();
    assumptionQuery.eq(ConfMeasureActuarialAssumption::getValMethod, valMethod);
    List<ConfMeasureActuarialAssumption> assumptions = confMeasureActuarialAssumptionMapper.selectList(assumptionQuery);
    Map<String, Map<String, ConfMeasureActuarialAssumption>> assumptionMap = assumptions.stream()
      .collect(Collectors.groupingBy(
        ConfMeasureActuarialAssumption::getValMonth,
        Collectors.toMap(
          ConfMeasureActuarialAssumption::getClassCode,
          item -> item,
          (existing, replacement) -> replacement // 处理重复键：保留新值
        )
      ));
    log.info("加载精算假设数据 {} 条", assumptions.size());

    // 1.2 加载赔付模式数据
    List<ConfMeasureClaimModelNew> claimModels = measureClaimModelNewMapper.selectList(null);
    Map<String, BigDecimal[]> discountFactor = claimModels.stream()
      .collect(Collectors.groupingBy(
        ConfMeasureClaimModelNew::getClassCode,
        Collectors.collectingAndThen(
          Collectors.toList(),
          list -> {
            list.sort(Comparator.comparingInt(ConfMeasureClaimModelNew::getMonthId));
            return list.stream()
              .map(ConfMeasureClaimModelNew::getPaidRatio)
              .toArray(BigDecimal[]::new);
          }
        )
      ));
    log.info("加载赔付模式数据 {} 条", claimModels.size());

    // 1.3 加载月度远期利率
    List<ConfMeasureMonthDisrate> disrates = measureMonthDisrateMapper.selectList(null);
    Map<String, Map<Integer, BigDecimal>> disRateMap = disrates.stream()
      .collect(Collectors.groupingBy(ConfMeasureMonthDisrate::getValMonth,
        Collectors.toMap(ConfMeasureMonthDisrate::getTermMonth, ConfMeasureMonthDisrate::getForwardDisrateValue, (v1, v2) -> v1)));
    log.info("加载月度远期利率数据 {} 条", disRateMap.size());
    long configTime = System.currentTimeMillis();
    log.info("读取和处理配置数据完成，耗时: {} 秒", (configTime - startTime) / 1000.0);


    // ==================== 2. 读取源数据 ====================
    List<IntTPpReMonArrInNewCombine> allContracts = intTPpReMonArrInNewMapper.selectCombineUnExpried(valMonth, valMethod);
    long readDataTime = System.currentTimeMillis();
    log.info("读取源数据 {} 条，耗时: {} 秒", allContracts.size(), (readDataTime - configTime) / 1000.0);
    if (allContracts.isEmpty()) {
      log.warn("未找到需要处理的源数据，计算提前结束。");
      return R.ok("未找到需要处理的源数据");
    }

    // ==================== 3. For循环处理业务逻辑 ====================
    List<IntMeasureCxUnexpiredRein> allResults = new ArrayList<>(allContracts.size());
    for (IntTPpReMonArrInNewCombine contract : allContracts) {
      IntMeasureCxUnexpiredRein result = calculateLrcReinInByMonth(contract, valMonth, assumptionMap, discountFactor, disRateMap);
      if (result != null) {
        allResults.add(result);
      }
    }
    long logicTime = System.currentTimeMillis();
    log.info("业务逻辑处理完成，耗时: {} 秒", (logicTime - readDataTime) / 1000.0);


    // ==================== 4. 插入数据 ====================
    // 4.1 清空当期数据
    intMeasureCxUnexpiredReinMapper.delete(new LambdaQueryWrapper<IntMeasureCxUnexpiredRein>()
      .eq(IntMeasureCxUnexpiredRein::getValMonth, valMonth)
      .eq(IntMeasureCxUnexpiredRein::getValMethod, valMethod));

    // 4.2 计算分摊到单的亏损
    if (CollectionUtils.isNotEmpty(allResults)) {
      calculateLossComponentAllocation(allResults);
    }

    // 4.3 批量插入结果
    if (CollectionUtils.isNotEmpty(allResults)) {
      insertBatchWithJdbcTemplate(allResults);
    }
    long insertTime = System.currentTimeMillis();
    log.info("批量插入数据 {} 条，耗时: {} 秒", allResults.size(), (insertTime - logicTime) / 1000.0);
    log.info("LRC计量计算全部完成，总耗时: {} 秒", (System.currentTimeMillis() - startTime) / 1000.0);
    return R.ok();
  }

  private IntMeasureCxUnexpiredRein calculateLrcReinInByMonth(IntTPpReMonArrInNewCombine contract, String valMonth,
                                                              Map<String, Map<String, ConfMeasureActuarialAssumption>> assumptionMap,
                                                              Map<String, BigDecimal[]> discountFactor,
                                                              Map<String, Map<Integer, BigDecimal>> disRateMap) {
    // --- 0. 数据提取与校验 ---
    LocalDate contractStartDate;
    LocalDate contractEndDate;
    LocalDate iniConfirmDate;
    LocalDate confirmDate;
    try {
      contractStartDate = LocalDate.parse(contract.getStartDate(), YYYYMMDD_FORMATTER);
      contractEndDate = LocalDate.parse(contract.getEndDate(), YYYYMMDD_FORMATTER);
      iniConfirmDate = LocalDate.parse(contract.getIniConfirm(), YYYYMMDD_FORMATTER);
      confirmDate = contract.getConfirmDate().toInstant().atZone(ZoneId.systemDefault()).toLocalDate();
    } catch (Exception e) {
      System.err.println("跳过合同（日期格式错误）: 源数据id=" + contract.getId());
      return null;
    }

    //确定计息起点 初始确认日 和 confirmDate 孰晚
    LocalDate interestStartDate = iniConfirmDate.isAfter(confirmDate) ? iniConfirmDate : confirmDate;

    if (YearMonth.parse(valMonth, YYYYMM_FORMATTER).isBefore(YearMonth.from(interestStartDate))) {
      System.err.println("跳过合同（评估时点在计息日之前）: 源数据id=" + contract.getId());
      return null;
    }

    if (contractEndDate.isBefore(contractStartDate)) {
      System.err.println("跳过合同（责任止期在责任起期之前）: 源数据id=" + contract.getId());
      return null;
    }

    //评估月月末日期，用于后续计算。
    LocalDate valDate = YearMonth.parse(valMonth, YYYYMM_FORMATTER).atEndOfMonth();

    // --- 1. 初始化状态 (从上期结果字段继承) ---
    BigDecimal openingBalance;
    BigDecimal prevCumulativeIfieAmt;
    BigDecimal prevCumulativeNoIacf;
    BigDecimal prevNetPremiumAmortization;
    BigDecimal prevCumulativeIfieAmtAmortization;
    BigDecimal prevBaseInvestmentAmortization;
    BigDecimal prevCumulativeNoIacfAmortization;
    //int prevMonthCount;

    BigDecimal prevPremiumAmortization;

    // 关键：判断是否为第一期
    //boolean isFirstPeriod = (contract.getPrevMonthCount() == null || contract.getPrevMonthCount() == 0);
    boolean isFirstPeriod = contract.getPrevId() == null;

    if (isFirstPeriod) {
      // 如果是第一期（上个月没有数据），所有状态从0开始
      openingBalance = BigDecimal.ZERO;
      prevCumulativeIfieAmt = BigDecimal.ZERO;
      prevCumulativeNoIacf = BigDecimal.ZERO;
      prevNetPremiumAmortization = BigDecimal.ZERO;
      prevCumulativeIfieAmtAmortization = BigDecimal.ZERO;
      prevBaseInvestmentAmortization = BigDecimal.ZERO;
      prevCumulativeNoIacfAmortization = BigDecimal.ZERO;
      //prevMonthCount = 0;

      prevPremiumAmortization = BigDecimal.ZERO;
    } else {
      // 如果不是第一期，直接从 DTO 的 prev... 字段中继承状态！
      openingBalance = contract.getPrevClosingBalance();
      prevCumulativeIfieAmt = contract.getPrevCumulativeIfieAmt();
      prevCumulativeNoIacf = contract.getPrevCumulativeNoIacf();
      prevNetPremiumAmortization = contract.getPrevNetPremiumAmortization();
      prevCumulativeIfieAmtAmortization = contract.getPrevCumulativeIfieAmtAmortization();
      prevBaseInvestmentAmortization = contract.getPrevBaseInvestmentAmortization();
      prevCumulativeNoIacfAmortization = contract.getPrevCumulativeNoIacfAmortization();
      //prevMonthCount = contract.getPrevMonthCount();

      prevPremiumAmortization = contract.getPrevPremiumAmortization();
    }

    // --- 2. 执行单次计算
    //各种配置数据
    String iniConfirmMonthStr = iniConfirmDate.format(YYYYMM_FORMATTER);
    //初始确认日利率曲线
    Map<Integer, BigDecimal> startMonthRateMap = disRateMap.getOrDefault(iniConfirmMonthStr, Collections.emptyMap());
    //当期利率曲线
    Map<Integer, BigDecimal> currentMonthRateMap = disRateMap.getOrDefault(valMonth, Collections.emptyMap());
    //当期精算假设
    ConfMeasureActuarialAssumption assumption = assumptionMap.getOrDefault(valMonth, Collections.emptyMap())
      .getOrDefault(contract.getClassCode(), new ConfMeasureActuarialAssumption());

    // 非亏部分
    //a.各种现金流，需要摊销的预期数(可直接确定的)
    //a.1预收预付
    //预付跟单获取费用 (手续费+经纪费，分入使用精算假设) (用于摊销) 又不用精算假设了
/*    BigDecimal firstDayAcquisitionExpenseRatio = Optional.ofNullable(assumptionMap.getOrDefault(iniConfirmMonthStr, Collections.emptyMap())
      .getOrDefault(contract.getClassCode(), new ConfMeasureActuarialAssumption()).getFirstDayAcquisitionExpenseRatio()).orElse(BigDecimal.ZERO);
    BigDecimal iacf = contract.getPremium().multiply(firstDayAcquisitionExpenseRatio);*/
    BigDecimal iacf = contract.getCommission().add(contract.getBrokerage()).setScale(SCALE, ROUNDING_MODE);

    //实际预收净保费 = 保费 - （手续费 + 经纪费）(分入非跟单计算假设)(用于摊销)
    BigDecimal netPremium = contract.getPremium().subtract(iacf).setScale(SCALE, ROUNDING_MODE);

    //投资成分(用于摊销)
    BigDecimal baseInvestment = contract.getPremium().multiply(Optional.ofNullable(contract.getInvestProp()).orElse(BigDecimal.ZERO)).setScale(SCALE, ROUNDING_MODE);

    //a.2现金流
    //毛保费现金流
    BigDecimal premiumCashFlow = isFirstPeriod ? contract.getPremium() : BigDecimal.ZERO;

    //净保费现金流
    BigDecimal netPremiumCashFlow = isFirstPeriod ? netPremium : BigDecimal.ZERO;

    //跟单获取费用现金流
    BigDecimal iacfCashFlow = isFirstPeriod ? iacf : BigDecimal.ZERO;

    //非跟单获取费用现金流
    BigDecimal noIacfCashFlow = contract.getIacfUnfol();


    //b.需要摊销的实际累积数(需要计算的，一般是累积数,记录当月数和累积数)
    //b.1当月利息，累积利息
    LocalDate periodEnd = valDate; // 当前计算期间的结束日期
    LocalDate prevPeriodEnd = valDate.minusMonths(1).with(TemporalAdjusters.lastDayOfMonth()); // 上一期间的结束日期

    // 确定当前期间的有效天数（用于计息）
    LocalDate effectiveStart = interestStartDate.isAfter(prevPeriodEnd) ? interestStartDate : prevPeriodEnd.plusDays(1);
    LocalDate effectiveEnd = contractEndDate.isBefore(periodEnd) ? contractEndDate : periodEnd;
    long daysInThisPeriod = ChronoUnit.DAYS.between(effectiveStart, effectiveEnd) + 1;
    if (daysInThisPeriod <= 0) {
      daysInThisPeriod = 0;
    }

    //该合同计量/计息到第几个月
    //int monthCount = prevMonthCount + 1;
    int monthCount = DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(contract.getIniConfirm()), DateUtils.parseDate(valMonth)) + 1;

    BigDecimal ifieAmt;
    if (daysInThisPeriod == 0) {
      ifieAmt = BigDecimal.ZERO;
    } else {
      int monthCountStr = Math.min(monthCount, MAX_MONTH_COUNT);
      BigDecimal periodInterestRate = startMonthRateMap.getOrDefault(monthCountStr, BigDecimal.ZERO);

      //当月计息
      // (A) 期初余额产生的利息 (计息一整个周期)
      BigDecimal interestFromOpening = openingBalance.multiply(periodInterestRate).setScale(SCALE, ROUNDING_MODE);
      // (B) 期间净现金流产生的利息 (假设期中流入/流出，计息半个周期)
      BigDecimal netCashFlow = netPremiumCashFlow.subtract(noIacfCashFlow);
      BigDecimal interestFromCashFlow = netCashFlow.multiply(periodInterestRate).multiply(BigDecimal.valueOf(0.5)).setScale(SCALE, ROUNDING_MODE);
      // (C) 总利息 = A + B
      ifieAmt = interestFromOpening.add(interestFromCashFlow).setScale(SCALE, ROUNDING_MODE);
    }

    //累积计息
    BigDecimal cumulativeIfieAmt = prevCumulativeIfieAmt.add(ifieAmt).setScale(SCALE, ROUNDING_MODE);

    //b.2累积非跟单获取费用
    BigDecimal cumulativeNoIacf = prevCumulativeNoIacf.add(noIacfCashFlow).setScale(SCALE, ROUNDING_MODE);

    //c.开始摊销，开始计算当期确认
    // 计算合同总天数 算摊销比例
    long totalDaysInContract = ChronoUnit.DAYS.between(contractStartDate, contractEndDate) + 1;
    BigDecimal totalDaysInContractBD = new BigDecimal(totalDaysInContract);

    //累积有效天数
    long cumulativeDays = 0;
    if (!periodEnd.isBefore(contractStartDate)) {
      LocalDate capEnd = contractEndDate.isBefore(periodEnd) ? contractEndDate : periodEnd;
      cumulativeDays = ChronoUnit.DAYS.between(contractStartDate, capEnd) + 1;
    }

    //摊销比例
    BigDecimal cumulativeProportion = (totalDaysInContractBD.compareTo(BigDecimal.ZERO) == 0)
      ? BigDecimal.ZERO
      : new BigDecimal(cumulativeDays).divide(totalDaysInContractBD, SCALE, ROUNDING_MODE);

    //c.1 保险服务收入 = 预收保费(净)摊销 + 累积计息摊销
    //预收毛保费摊销
    BigDecimal premiumAmortization = contract.getPremium().multiply(cumulativeProportion).setScale(SCALE, ROUNDING_MODE);

    //当期预收毛保费摊销
    BigDecimal premiumAmortizationThisPeriod = premiumAmortization.subtract(prevPremiumAmortization).setScale(SCALE, ROUNDING_MODE);

    //预付跟单获取费用摊销
    BigDecimal iacfAmortization = iacf.multiply(cumulativeProportion).setScale(SCALE, ROUNDING_MODE);

    //预收保费(净)摊销
    BigDecimal netPremiumAmortization = premiumAmortization.subtract(iacfAmortization).setScale(SCALE, ROUNDING_MODE);

    //当期预收保费(净)摊销
    BigDecimal netPremiumAmortizationThisPeriod = netPremiumAmortization.subtract(prevNetPremiumAmortization).setScale(SCALE, ROUNDING_MODE);

    //当期跟单获取费用摊销
    BigDecimal iacfAmortizationThisPeriod = premiumAmortizationThisPeriod.subtract(netPremiumAmortizationThisPeriod).setScale(SCALE, ROUNDING_MODE);

    //累积计息摊销
    BigDecimal cumulativeIfieAmtAmortization = cumulativeIfieAmt.multiply(cumulativeProportion).setScale(SCALE, ROUNDING_MODE);

    //当期累积计息摊销
    BigDecimal cumulativeIfieAmtAmortizationThisPeriod = cumulativeIfieAmtAmortization.subtract(prevCumulativeIfieAmtAmortization).setScale(SCALE, ROUNDING_MODE);

    //保险服务收入(分解投资成分前)
    BigDecimal incomeThisPeriodBeforeSplitting = netPremiumAmortizationThisPeriod.add(cumulativeIfieAmtAmortizationThisPeriod).setScale(SCALE, ROUNDING_MODE);

    //投资成分摊销
    BigDecimal baseInvestmentAmortization = baseInvestment.multiply(cumulativeProportion).setScale(SCALE, ROUNDING_MODE);

    //当期投资成分摊销
    BigDecimal baseInvestmentAmortizationThisPeriod = baseInvestmentAmortization.subtract(prevBaseInvestmentAmortization).setScale(SCALE, ROUNDING_MODE);

    //保险服务收入
    BigDecimal incomeThisPeriod = incomeThisPeriodBeforeSplitting.subtract(baseInvestmentAmortizationThisPeriod).setScale(SCALE, ROUNDING_MODE);


    //c.2当期非跟单获取费用摊销
    //累积非跟单获取费用摊销
    BigDecimal cumulativeNoIacfAmortization = cumulativeNoIacf.multiply(cumulativeProportion).setScale(SCALE, ROUNDING_MODE);

    //当期非跟单获取费用摊销
    BigDecimal cumulativeNoIacfAmortizationThisPeriod = cumulativeNoIacfAmortization.subtract(prevCumulativeNoIacfAmortization).setScale(SCALE, ROUNDING_MODE);

    //非亏
    BigDecimal closingBalance = openingBalance
      .add(netPremiumCashFlow).subtract(noIacfCashFlow).add(ifieAmt)
      .subtract(incomeThisPeriod).add(cumulativeNoIacfAmortizationThisPeriod).subtract(baseInvestmentAmortizationThisPeriod)
      .setScale(SCALE, ROUNDING_MODE);


    //亏损部分
    //合同参与计量的总月数
    int totalMonths = (int) ChronoUnit.MONTHS.between(iniConfirmDate.withDayOfMonth(1), contractEndDate.withDayOfMonth(1)) + 1;
    //需要参与亏损折现的剩余月份数
    int n = totalMonths - monthCount;

    // 计算未来服务量比例
    BigDecimal futureProportion = BigDecimal.ONE.subtract(cumulativeProportion).setScale(SCALE, ROUNDING_MODE).max(BigDecimal.ZERO);
    //a.未满期保费
    BigDecimal futurePremiums = contract.getPremium().multiply(futureProportion).setScale(SCALE, ROUNDING_MODE);

    //b.预期未来现金流现值 = 预期未来维持费用现值,预期未来赔付费用现值
    //b.1预期未来维持费用 = 未满期保费*精算假设维持费用率
    BigDecimal futureMaintenance = futurePremiums.multiply(assumption.getMaintenanceExpenseRatio());
    //b.2预期未来维持费用现值
    BigDecimal pvFutureMaintenance = getPvMaintenance(futureMaintenance, n, currentMonthRateMap);

    BigDecimal indirectFactor = assumption.getIndirectClaimsExpenseRatio().add(BigDecimal.ONE);
    //b.3预期未来赔付费用
    BigDecimal futureLoss = futurePremiums.multiply(assumption.getLossRatio()).multiply(indirectFactor);
    //b.4预期未来赔付费用现值
    BigDecimal pvFutureLoss = getPvLoss(futureLoss, n, currentMonthRateMap, contract.getClassCode(), discountFactor);

    //c.风险调整
    BigDecimal riskAdjustment = pvFutureMaintenance.add(pvFutureLoss).multiply(assumption.getRa()).setScale(SCALE, ROUNDING_MODE);

    //d.预期未来现金流 = 预期未来维持费用现值 + 预期未来赔付费用现值 + 风险调整
    BigDecimal futureCashFlow = pvFutureLoss.add(pvFutureMaintenance).add(riskAdjustment).setScale(SCALE, ROUNDING_MODE);

    BigDecimal netFutureCashFlow = futureCashFlow
      .subtract(closingBalance)
      .setScale(SCALE, ROUNDING_MODE);

    //亏损部分
    BigDecimal lossComponent;
    if (contract.getPremium().compareTo(BigDecimal.ZERO) == -1) {
      lossComponent = netFutureCashFlow.compareTo(BigDecimal.ZERO) > 0 ? BigDecimal.ZERO : netFutureCashFlow;
    } else {
      lossComponent = netFutureCashFlow.compareTo(BigDecimal.ZERO) > 0 ? netFutureCashFlow : BigDecimal.ZERO;
    }

    //未到期责任负债
    BigDecimal lrcDebt = closingBalance.add(lossComponent).setScale(SCALE, ROUNDING_MODE);

    //返回评估时点的明细结果
    //Date转string格式入库 jdbcTemplate 处理 date数据不太行 效率影响很大
    String confirmDateStr = (contract.getConfirmDate() == null) ? null : DateFormatUtils.format(contract.getConfirmDate(), YYYYMMDD);
    String piStartDateStr = (contract.getPiStartDate() == null) ? null : DateFormatUtils.format(contract.getPiStartDate(), YYYYMMDD);
    String PiEndDateStr = (contract.getPiEndDate() == null) ? null : DateFormatUtils.format(contract.getPiEndDate(), YYYYMMDD);
    String modifyDateStr = (contract.getModifyDate() == null) ? null : DateFormatUtils.format(contract.getModifyDate(), YYYYMMDD);
    String modifyStartDateStr = (contract.getModifyStartDate() == null) ? null : DateFormatUtils.format(contract.getModifyStartDate(), YYYYMMDD);
    String modifyEndDateStr = (contract.getModifyEndDate() == null) ? null : DateFormatUtils.format(contract.getModifyEndDate(), YYYYMMDD);

    IntMeasureCxUnexpiredRein intMeasureCxUnexpiredRein = new IntMeasureCxUnexpiredRein();
    intMeasureCxUnexpiredRein.setSourceId(contract.getId());
    intMeasureCxUnexpiredRein.setContractFlag(contract.getContractFlag());
    intMeasureCxUnexpiredRein.setContractType(contract.getContractType());
    intMeasureCxUnexpiredRein.setEnquiryType(contract.getEnquiryType());
    intMeasureCxUnexpiredRein.setContractId(contract.getContractId());
    intMeasureCxUnexpiredRein.setSectionNo(contract.getSectionNo());
    intMeasureCxUnexpiredRein.setPolicyNo(contract.getPolicyNo());
    intMeasureCxUnexpiredRein.setCertiNo(contract.getCertiNo());
    intMeasureCxUnexpiredRein.setClassCode(contract.getClassCode());
    intMeasureCxUnexpiredRein.setRiskCode(contract.getRiskCode());
    intMeasureCxUnexpiredRein.setComCode(contract.getComCode());
    intMeasureCxUnexpiredRein.setCarKindCode(contract.getCarKindCode());
    intMeasureCxUnexpiredRein.setUseNatureCode(contract.getUseNatureCode());
    intMeasureCxUnexpiredRein.setConfirmDate(confirmDateStr);
    intMeasureCxUnexpiredRein.setPiStartDate(piStartDateStr);
    intMeasureCxUnexpiredRein.setPiEndDate(PiEndDateStr);
    intMeasureCxUnexpiredRein.setModifyDate(modifyDateStr);
    intMeasureCxUnexpiredRein.setModifyStartDate(modifyStartDateStr);
    intMeasureCxUnexpiredRein.setModifyEndDate(modifyEndDateStr);
    intMeasureCxUnexpiredRein.setPremium(contract.getPremium());
    intMeasureCxUnexpiredRein.setCurrency(contract.getCurrency());
    //分入手续费经纪费 跟单获取费用 使用精算假设 又不用精算假设了
    intMeasureCxUnexpiredRein.setCommission(contract.getCommission());
    intMeasureCxUnexpiredRein.setBrokerage(contract.getBrokerage());
    intMeasureCxUnexpiredRein.setInvestProp(contract.getInvestProp());
    intMeasureCxUnexpiredRein.setUnitId(contract.getUnitId());
    intMeasureCxUnexpiredRein.setMinUnitId(contract.getMinUnitId());
    intMeasureCxUnexpiredRein.setPortfolioId(contract.getPortfolioId());
    intMeasureCxUnexpiredRein.setGroupId(contract.getGroupId());
    intMeasureCxUnexpiredRein.setValMonth(contract.getValMonth());
    intMeasureCxUnexpiredRein.setValMethod(contract.getValMethod());
    intMeasureCxUnexpiredRein.setStartDate(contract.getStartDate());
    intMeasureCxUnexpiredRein.setEndDate(contract.getEndDate());
    intMeasureCxUnexpiredRein.setIniConfirm(contract.getIniConfirm());

    //计量结果
    intMeasureCxUnexpiredRein.setOpeningBalance(openingBalance);
    intMeasureCxUnexpiredRein.setNetPremium(netPremium);
    intMeasureCxUnexpiredRein.setBaseInvestment(baseInvestment);
    intMeasureCxUnexpiredRein.setIacf(iacf);
    intMeasureCxUnexpiredRein.setPremiumCashFlow(premiumCashFlow);
    intMeasureCxUnexpiredRein.setNetPremiumCashFlow(netPremiumCashFlow);
    intMeasureCxUnexpiredRein.setIacfCashFlow(iacfCashFlow);
    intMeasureCxUnexpiredRein.setNoIacfCashFlow(noIacfCashFlow);
    intMeasureCxUnexpiredRein.setIfieAmt(ifieAmt);
    intMeasureCxUnexpiredRein.setCumulativeIfieAmt(cumulativeIfieAmt);
    intMeasureCxUnexpiredRein.setCumulativeNoIacf(cumulativeNoIacf);
    intMeasureCxUnexpiredRein.setCumulativeDays(BigDecimal.valueOf(cumulativeDays));
    intMeasureCxUnexpiredRein.setCumulativeProportion(cumulativeProportion);
    intMeasureCxUnexpiredRein.setPremiumAmortization(premiumAmortization);
    intMeasureCxUnexpiredRein.setIacfAmortization(iacfAmortization);
    intMeasureCxUnexpiredRein.setNetPremiumAmortization(netPremiumAmortization);
    intMeasureCxUnexpiredRein.setCumulativeIfieAmtAmortization(cumulativeIfieAmtAmortization);
    intMeasureCxUnexpiredRein.setIncomeThisPeriodBeforeSplitting(incomeThisPeriodBeforeSplitting);
    intMeasureCxUnexpiredRein.setBaseInvestmentAmortization(baseInvestmentAmortization);
    intMeasureCxUnexpiredRein.setBaseInvestmentAmortizationThisPeriod(baseInvestmentAmortizationThisPeriod);
    intMeasureCxUnexpiredRein.setIncomeThisPeriod(incomeThisPeriod);
    intMeasureCxUnexpiredRein.setCumulativeNoIacfAmortization(cumulativeNoIacfAmortization);
    intMeasureCxUnexpiredRein.setCumulativeNoIacfAmortizationThisPeriod(cumulativeNoIacfAmortizationThisPeriod);
    intMeasureCxUnexpiredRein.setClosingBalance(closingBalance);
    intMeasureCxUnexpiredRein.setFuturePremiums(futurePremiums);
    intMeasureCxUnexpiredRein.setPvFutureMaintenance(pvFutureMaintenance);
    intMeasureCxUnexpiredRein.setPvFutureLoss(pvFutureLoss);
    intMeasureCxUnexpiredRein.setRiskAdjustment(riskAdjustment);
    intMeasureCxUnexpiredRein.setFutureCashFlow(futureCashFlow);
    intMeasureCxUnexpiredRein.setLossComponent(lossComponent);
    intMeasureCxUnexpiredRein.setLrcDebt(lrcDebt);
    //intMeasureCxUnexpiredRein.setMonthCount(monthCount);
    intMeasureCxUnexpiredRein.setNetPremiumAmortizationThisPeriod(netPremiumAmortizationThisPeriod);
    intMeasureCxUnexpiredRein.setCumulativeIfieAmtAmortizationThisPeriod(cumulativeIfieAmtAmortizationThisPeriod);

    intMeasureCxUnexpiredRein.setPremiumAmortizationThisPeriod(premiumAmortizationThisPeriod);
    intMeasureCxUnexpiredRein.setIacfAmortizationThisPeriod(iacfAmortizationThisPeriod);

    return intMeasureCxUnexpiredRein;
  }

  @Override
  @Transactional(rollbackFor = Exception.class)
  public R<?> getLrcReinOutMeasureByMonthResult(String valMethod, String valMonth) throws IOException {
    log.info("开始LRC计量计算（简化版），评估方法: {}, 评估月份: {}", valMethod, valMonth);
    long startTime = System.currentTimeMillis();

    // ==================== 0. 先清空当期数据 ====================
    intMeasureCxUnexpiredReinMapper.delete(new LambdaQueryWrapper<IntMeasureCxUnexpiredRein>()
      .eq(IntMeasureCxUnexpiredRein::getValMonth, valMonth)
      .eq(IntMeasureCxUnexpiredRein::getValMethod, valMethod));
    log.info("已清空当期数据: valMonth={}, valMethod={}", valMonth, valMethod);

    // ==================== 1. 读取和处理配置数据 ====================
    // 1.1 加载月度远期利率
    List<ConfMeasureMonthDisrate> disrates = measureMonthDisrateMapper.selectList(null);
    Map<String, Map<Integer, BigDecimal>> disRateMap = disrates.stream()
      .collect(Collectors.groupingBy(ConfMeasureMonthDisrate::getValMonth,
        Collectors.toMap(ConfMeasureMonthDisrate::getTermMonth, ConfMeasureMonthDisrate::getForwardDisrateValue, (v1, v2) -> v1)));
    log.info("加载月度远期利率数据 {} 条", disRateMap.size());

    // 1.2 加载历史亏损分摊数据
    List<Map<String, Object>> resultAllocationList = intMeasureCxUnexpiredReinMapper.getMeasureAllocationCache(valMonth);
    Map<String, Map<String, BigDecimal>> resultAllocationMapMap = resultAllocationList.stream()
      .filter(map -> map.get("lossComponentAllocation") != null) // 关键：过滤掉值为null的条目
      .filter(map -> map.get("premium") != null) // 新增：过滤premium为null
      .collect(Collectors.toMap(
        row -> (String) row.get("groupKey"),
        row -> {
          Map<String, BigDecimal> innerMap = new HashMap<>();
          innerMap.put("lossComponentAllocation", (BigDecimal) row.get("lossComponentAllocation"));
          innerMap.put("premium", (BigDecimal) row.get("premium"));
          return innerMap;
        }
      ));
    log.info("加载历史亏损分摊数据 {} 条", resultAllocationList.size());
    long configTime = System.currentTimeMillis();
    log.info("读取和处理配置数据完成，耗时: {} 秒", (configTime - startTime) / 1000.0);

    LambdaQueryWrapper<IntTPpReMonArrNew> countQuery = Wrappers.lambdaQuery();
    countQuery.eq(IntTPpReMonArrNew::getValMethod, valMethod)
      .eq(IntTPpReMonArrNew::getValMonth, valMonth);
    Long totalCount = intTPpReMonArrNewMapper.selectCount(countQuery);

    // ==================== 2. 准备流式查询 ====================
    log.info("源数据总量 {} 条，准备开始流式处理...", totalCount);
    long readDataTime = System.currentTimeMillis();

// ==================== 3. 流式处理与分批插入 ====================
    long processed = 0L;
    long totalInserted = 0L;
    List<IntMeasureCxUnexpiredRein> batchResults = new ArrayList<>((int) BATCH_SIZE);
    try (Cursor<IntTPpReMonArrNewCombine> cursor = intTPpReMonArrNewMapper.streamQuery(valMonth, valMethod)) {
      for (IntTPpReMonArrNewCombine contract : cursor) {
        IntMeasureCxUnexpiredRein result = calculateLrcReinOutByMonth(contract, valMonth, disRateMap, resultAllocationMapMap);
        if (result != null) {
          batchResults.add(result);
        }

        if (batchResults.size() >= BATCH_SIZE) {
          int currentBatchSize = batchResults.size();
          log.info("--> 批次已满 ({} 条)，准备执行插入...", currentBatchSize);
          insertBatchWithJdbcTemplate(batchResults);
          totalInserted += currentBatchSize;
          batchResults.clear();
          log.info("==> 插入批次成功：插入 {} 条数据，累计已插入 {} 条。", currentBatchSize, totalInserted);
        }

        processed++; // processed 自增

        if (processed % 100000 == 0) {
          log.info("--> 已流式处理 {} / {} 条数据。", processed, totalCount);
        }
      }
    } // try-with-resources 语法会确保cursor在这里被自动关闭

    // 处理最后一批不足 BATCH_SIZE 的数据
    if (CollectionUtils.isNotEmpty(batchResults)) {
      insertBatchWithJdbcTemplate(batchResults);
      totalInserted += batchResults.size();
      batchResults.clear();
    }

    long insertTime = System.currentTimeMillis();
    log.info("全部批次处理与插入完成，总计处理 {} 条，插入 {} 条，耗时: {} 秒", processed, totalInserted, (insertTime - readDataTime) / 1000.0);
    log.info("LRC计量计算全部完成，总耗时: {} 秒", (System.currentTimeMillis() - startTime) / 1000.0);
    return R.ok();
  }

  private IntMeasureCxUnexpiredRein calculateLrcReinOutByMonth(IntTPpReMonArrNewCombine contract, String valMonth,
                                                               Map<String, Map<Integer, BigDecimal>> disRateMap,
                                                               Map<String, Map<String, BigDecimal>> resultAllocationMapMap) {

    // --- 0. 数据提取与校验 ---
    LocalDate contractStartDate;
    LocalDate contractEndDate;
    LocalDate iniConfirmDate;
    LocalDate compareDate;
    try {
      contractStartDate = LocalDate.parse(contract.getStartDate(), YYYYMMDD_FORMATTER);
      contractEndDate = LocalDate.parse(contract.getEndDate(), YYYYMMDD_FORMATTER);
      iniConfirmDate = LocalDate.parse(contract.getIniConfirm(), YYYYMMDD_FORMATTER);

      // 2. 【核心精简逻辑】：直接选出 Date 对象
      // 判断是否为批单 (有批单号且不为空)
      boolean isCerti = contract.getCertiNo() != null && !contract.getCertiNo().trim().isEmpty();

      // 是批单取 CertiWriteDate，否则取 UnderWriteDate
      Date targetDate = isCerti ? contract.getCertiWriteDate() : contract.getUnderWriteDate();

      // 3. 【判空】：如果取出来的日期是 null，直接报错跳过
      if (targetDate == null) {
        throw new NullPointerException(isCerti ? "批单日期(CertiWriteDate)为NULL" : "签单日期(UnderWriteDate)为NULL");
      }

      // 4. 【转换】：Date -> LocalDate (使用默认时区转换)
      compareDate = targetDate.toInstant().atZone(java.time.ZoneId.systemDefault()).toLocalDate();

    } catch (Exception e) {
      // 日期格式错误则跳过该合同
      System.err.println("跳过合同(数据异常): ID=" + contract.getId() + " 原因: " + e.getMessage());
      return null;
    }

    //确定计息起点 初始确认日 和 confirmDate 孰晚
    LocalDate interestStartDate = iniConfirmDate.isAfter(compareDate) ? iniConfirmDate : compareDate;

    if (YearMonth.parse(valMonth, YYYYMM_FORMATTER).isBefore(YearMonth.from(interestStartDate))) {
      System.err.println("跳过合同（评估时点在计息日之前）: 源数据id=" + contract.getId());
      return null;
    }

    if (contractEndDate.isBefore(contractStartDate)) {
      System.err.println("跳过合同（责任止期在责任起期之前）: 源数据id=" + contract.getId());
      return null;
    }

    //评估月月末日期，用于后续计算。
    LocalDate valDate = YearMonth.parse(valMonth, YYYYMM_FORMATTER).atEndOfMonth();

    // --- 1. 初始化状态 (从上期结果字段继承) ---
    BigDecimal openingBalance;
    BigDecimal prevCumulativeIfieAmt;
    BigDecimal prevNetPremiumAmortization;
    BigDecimal prevCumulativeIfieAmtAmortization;
    BigDecimal prevBaseInvestmentAmortization;
    //int prevMonthCount;

    BigDecimal prevPremiumAmortization;

    // 关键：判断是否为第一期
    //boolean isFirstPeriod = (contract.getPrevMonthCount() == null || contract.getPrevMonthCount() == 0);
    boolean isFirstPeriod = contract.getPrevId() == null;

    if (isFirstPeriod) {
      // 如果是第一期（上个月没有数据），所有状态从0开始
      openingBalance = BigDecimal.ZERO;
      prevCumulativeIfieAmt = BigDecimal.ZERO;
      prevNetPremiumAmortization = BigDecimal.ZERO;
      prevCumulativeIfieAmtAmortization = BigDecimal.ZERO;
      prevBaseInvestmentAmortization = BigDecimal.ZERO;
      //prevMonthCount = 0;

      prevPremiumAmortization = BigDecimal.ZERO;
    } else {
      // 如果不是第一期，直接从 DTO 的 prev... 字段中继承状态！
      openingBalance = contract.getPrevClosingBalance();
      prevCumulativeIfieAmt = contract.getPrevCumulativeIfieAmt();
      prevNetPremiumAmortization = contract.getPrevNetPremiumAmortization();
      prevCumulativeIfieAmtAmortization = contract.getPrevCumulativeIfieAmtAmortization();
      prevBaseInvestmentAmortization = contract.getPrevBaseInvestmentAmortization();
      //prevMonthCount = contract.getPrevMonthCount();

      prevPremiumAmortization = contract.getPrevPremiumAmortization();
    }

    // --- 2. 执行单次计算
    //各种配置数据
    String iniConfirmMonthStr = iniConfirmDate.format(YYYYMM_FORMATTER);
    //初始确认日利率曲线
    Map<Integer, BigDecimal> startMonthRateMap = disRateMap.getOrDefault(iniConfirmMonthStr, Collections.emptyMap());

    // 非亏部分
    //a.各种现金流，需要摊销的预期数(可直接确定的)
    //a.1预收预付
    //预付跟单获取费用 (手续费) (用于摊销)
    BigDecimal iacf = contract.getCommission();

    //实际预收净保费 = 保费 - (手续费) (用于摊销)
    BigDecimal netPremium = contract.getPremium().subtract(iacf).setScale(SCALE, ROUNDING_MODE);

    //投资成分(用于摊销)
    BigDecimal baseInvestment = contract.getPremium().multiply(Optional.ofNullable(contract.getInvestProp()).orElse(BigDecimal.ZERO)).setScale(SCALE, ROUNDING_MODE);

    //a.2现金流
    //毛保费现金流
    BigDecimal premiumCashFlow = isFirstPeriod ? contract.getPremium() : BigDecimal.ZERO;

    //净保费现金流
    BigDecimal netPremiumCashFlow = isFirstPeriod ? netPremium : BigDecimal.ZERO;

    //跟单获取费用现金流
    BigDecimal iacfCashFlow = isFirstPeriod ? iacf : BigDecimal.ZERO;


    //b.需要摊销的实际累积数(需要计算的，一般是累积数,记录当月数和累积数)
    //b.1当月利息，累积利息
    LocalDate periodEnd = valDate; // 当前计算期间的结束日期
    LocalDate prevPeriodEnd = valDate.minusMonths(1).with(TemporalAdjusters.lastDayOfMonth()); // 上一期间的结束日期

    // 确定当前期间的有效天数（用于计息）
    LocalDate effectiveStart = interestStartDate.isAfter(prevPeriodEnd) ? interestStartDate : prevPeriodEnd.plusDays(1);
    LocalDate effectiveEnd = contractEndDate.isBefore(periodEnd) ? contractEndDate : periodEnd;
    long daysInThisPeriod = ChronoUnit.DAYS.between(effectiveStart, effectiveEnd) + 1;
    if (daysInThisPeriod <= 0) {
      daysInThisPeriod = 0;
    }

    //该合同计量/计息到第几个月
    //int monthCount = prevMonthCount + 1;
    int monthCount = DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(contract.getIniConfirm()), DateUtils.parseDate(valMonth)) + 1;

    BigDecimal ifieAmt;
    if (daysInThisPeriod == 0) {
      ifieAmt = BigDecimal.ZERO;
    } else {
      int monthCountStr = Math.min(monthCount, MAX_MONTH_COUNT);
      BigDecimal periodInterestRate = startMonthRateMap.getOrDefault(monthCountStr, BigDecimal.ZERO);

      //当期计息
      // (A) 期初余额产生的利息 (计息一整个周期)
      BigDecimal interestFromOpening = openingBalance.multiply(periodInterestRate).setScale(SCALE, ROUNDING_MODE);
      // (B) 期间净保费现金流产生的利息 (假设期中流入/流出，计息半个周期)
      BigDecimal interestFromCashFlow = netPremiumCashFlow.multiply(periodInterestRate).multiply(BigDecimal.valueOf(0.5)).setScale(SCALE, ROUNDING_MODE);
      // (C) 总利息 = A + B
      ifieAmt = interestFromOpening.add(interestFromCashFlow).setScale(SCALE, ROUNDING_MODE);
    }

    //累积计息
    BigDecimal cumulativeIfieAmt = prevCumulativeIfieAmt.add(ifieAmt).setScale(SCALE, ROUNDING_MODE);

    //c.开始摊销，开始计算当期确认
    // 计算合同总天数 算摊销比例
    long totalDaysInContract = ChronoUnit.DAYS.between(contractStartDate, contractEndDate) + 1;
    BigDecimal totalDaysInContractBD = new BigDecimal(totalDaysInContract);

    //累积有效天数
    long cumulativeDays = 0;
    if (!periodEnd.isBefore(contractStartDate)) {
      LocalDate capEnd = contractEndDate.isBefore(periodEnd) ? contractEndDate : periodEnd;
      cumulativeDays = ChronoUnit.DAYS.between(contractStartDate, capEnd) + 1;
    }

    //摊销比例
    BigDecimal cumulativeProportion = (totalDaysInContractBD.compareTo(BigDecimal.ZERO) == 0)
      ? BigDecimal.ZERO
      : new BigDecimal(cumulativeDays).divide(totalDaysInContractBD, SCALE, ROUNDING_MODE);

    //c.1 保险服务收入 = 预收保费(净)摊销 + 累积计息摊销
    //预收毛保费摊销
    BigDecimal premiumAmortization = contract.getPremium().multiply(cumulativeProportion).setScale(SCALE, ROUNDING_MODE);

    //当期预收毛保费摊销
    BigDecimal premiumAmortizationThisPeriod = premiumAmortization.subtract(prevPremiumAmortization).setScale(SCALE, ROUNDING_MODE);

    //预付跟单获取费用摊销
    BigDecimal iacfAmortization = iacf.multiply(cumulativeProportion).setScale(SCALE, ROUNDING_MODE);

    //预收保费(净)摊销
    BigDecimal netPremiumAmortization = premiumAmortization.subtract(iacfAmortization).setScale(SCALE, ROUNDING_MODE);

    //当期预收保费(净)摊销
    BigDecimal netPremiumAmortizationThisPeriod = netPremiumAmortization.subtract(prevNetPremiumAmortization).setScale(SCALE, ROUNDING_MODE);

    //当期跟单获取费用摊销
    BigDecimal iacfAmortizationThisPeriod = premiumAmortizationThisPeriod.subtract(netPremiumAmortizationThisPeriod).setScale(SCALE, ROUNDING_MODE);

    //累积计息摊销
    BigDecimal cumulativeIfieAmtAmortization = cumulativeIfieAmt.multiply(cumulativeProportion).setScale(SCALE, ROUNDING_MODE);

    //当期累积计息摊销
    BigDecimal cumulativeIfieAmtAmortizationThisPeriod = cumulativeIfieAmtAmortization.subtract(prevCumulativeIfieAmtAmortization).setScale(SCALE, ROUNDING_MODE);

    //保险服务收入(分解投资成分前)
    BigDecimal incomeThisPeriodBeforeSplitting = netPremiumAmortizationThisPeriod.add(cumulativeIfieAmtAmortizationThisPeriod).setScale(SCALE, ROUNDING_MODE);

    //投资成分摊销
    BigDecimal baseInvestmentAmortization = baseInvestment.multiply(cumulativeProportion).setScale(SCALE, ROUNDING_MODE);

    //当期投资成分摊销
    BigDecimal baseInvestmentAmortizationThisPeriod = baseInvestmentAmortization.subtract(prevBaseInvestmentAmortization).setScale(SCALE, ROUNDING_MODE);

    //保险服务收入
    BigDecimal incomeThisPeriod = incomeThisPeriodBeforeSplitting.subtract(baseInvestmentAmortizationThisPeriod).setScale(SCALE, ROUNDING_MODE);

    //非亏
    BigDecimal closingBalance = openingBalance
      .add(netPremiumCashFlow).add(ifieAmt)
      .subtract(incomeThisPeriod).subtract(baseInvestmentAmortizationThisPeriod)
      .setScale(SCALE, ROUNDING_MODE);

    //亏损部分
    // 计算未来服务量比例
    BigDecimal futureProportion = BigDecimal.ONE.subtract(cumulativeProportion).setScale(SCALE, ROUNDING_MODE).max(BigDecimal.ZERO);

    //未满期保费
    BigDecimal futurePremiums = contract.getPremium().multiply(futureProportion).setScale(SCALE, ROUNDING_MODE);

    // 根据保单号和批单号查找历史亏损分摊数据
    String key = StringUtils.joinWith("_", Opt.ofBlankAble(contract.getPolicyNo()).orElse(StringConstant.STRING_NA), Opt.ofBlankAble(contract.getCertiNo()).orElse(StringConstant.STRING_NA),
      Opt.ofBlankAble(contract.getRiskCode()).orElse(StringConstant.STRING_NA));
/*    BigDecimal lossAllocation = resultAllocationMap.getOrDefault(key, BigDecimal.ZERO);
    BigDecimal shareRate = contract.getShareRate() != null ? contract.getShareRate() : BigDecimal.ZERO;

    // 计算亏损部分：历史亏损分摊 * 分保份额
    BigDecimal lossComponent = lossAllocation.multiply(shareRate).setScale(SCALE, ROUNDING_MODE);*/

    // 获取 premium
    BigDecimal premium = Optional.ofNullable(resultAllocationMapMap.get(key))
      .map(innerMap -> innerMap.get("premium"))
      .orElse(BigDecimal.ZERO);

    //loss_component_allocation
    BigDecimal lossComponentAllocation = Optional.ofNullable(resultAllocationMapMap.get(key))
      .map(innerMap -> innerMap.get("lossComponentAllocation"))
      .orElse(BigDecimal.ZERO);

    // 计算亏损部分：历史亏损分摊 * 分保份额
    BigDecimal lossComponent;
    if (premium.compareTo(BigDecimal.ZERO) == 0) {
      lossComponent = BigDecimal.ZERO;
    } else {
      BigDecimal shareRate = contract.getPremium().divide(premium, SCALE, ROUNDING_MODE).setScale(SCALE, ROUNDING_MODE);
      lossComponent = lossComponentAllocation.multiply(shareRate).setScale(SCALE, ROUNDING_MODE);
    }

    //未到期责任负债
    BigDecimal lrcDebt = closingBalance.add(lossComponent).setScale(SCALE, ROUNDING_MODE);

    //返回评估时点的明细结果
    //Date转string格式入库 jdbcTemplate 处理 date数据不太行 效率影响很大
    String underWriteDateStr = (contract.getUnderWriteDate() == null) ? null : DateFormatUtils.format(contract.getUnderWriteDate(), YYYYMMDD);
    String certiWriteDateStr = (contract.getCertiWriteDate() == null) ? null : DateFormatUtils.format(contract.getCertiWriteDate(), YYYYMMDD);
    String validDateStr = (contract.getValidDate() == null) ? null : DateFormatUtils.format(contract.getValidDate(), YYYYMMDD);
    String piStartDateStr = (contract.getPiStartDate() == null) ? null : DateFormatUtils.format(contract.getPiStartDate(), YYYYMMDD);
    String PiEndDateStr = (contract.getPiEndDate() == null) ? null : DateFormatUtils.format(contract.getPiEndDate(), YYYYMMDD);

    IntMeasureCxUnexpiredRein intMeasureCxUnexpiredRein = new IntMeasureCxUnexpiredRein();
    intMeasureCxUnexpiredRein.setSourceId(contract.getId());
    intMeasureCxUnexpiredRein.setContractFlag(contract.getContractFlag());
    intMeasureCxUnexpiredRein.setReinType(contract.getReinType());
    intMeasureCxUnexpiredRein.setContractType(contract.getContractType());
    intMeasureCxUnexpiredRein.setEnquiryType(contract.getEnquiryType());
    intMeasureCxUnexpiredRein.setContractId(contract.getContractId());
    intMeasureCxUnexpiredRein.setSectionNo(contract.getSectionNo());
    intMeasureCxUnexpiredRein.setShareRate(contract.getShareRate());
    intMeasureCxUnexpiredRein.setPolicyNo(contract.getPolicyNo());
    intMeasureCxUnexpiredRein.setCertiNo(contract.getCertiNo());
    intMeasureCxUnexpiredRein.setUnderWriteDate(underWriteDateStr);
    intMeasureCxUnexpiredRein.setCertiWriteDate(certiWriteDateStr);
    intMeasureCxUnexpiredRein.setValidDate(validDateStr);
    intMeasureCxUnexpiredRein.setPiStartDate(piStartDateStr);
    intMeasureCxUnexpiredRein.setPiEndDate(PiEndDateStr);
    intMeasureCxUnexpiredRein.setPremium(contract.getPremium());
    intMeasureCxUnexpiredRein.setCurrency(contract.getCurrency());
    intMeasureCxUnexpiredRein.setCommission(contract.getCommission());
    intMeasureCxUnexpiredRein.setClassCode(contract.getClassCode());
    intMeasureCxUnexpiredRein.setRiskCode(contract.getRiskCode());
    intMeasureCxUnexpiredRein.setComCode(contract.getComCode());
    intMeasureCxUnexpiredRein.setCarKindCode(contract.getCarKindCode());
    intMeasureCxUnexpiredRein.setUseNatureCode(contract.getUseNatureCode());
    intMeasureCxUnexpiredRein.setUnitId(contract.getUnitId());
    intMeasureCxUnexpiredRein.setMinUnitId(contract.getMinUnitId());
    intMeasureCxUnexpiredRein.setPortfolioId(contract.getPortfolioId());
    intMeasureCxUnexpiredRein.setGroupId(contract.getGroupId());
    intMeasureCxUnexpiredRein.setValMonth(contract.getValMonth());
    intMeasureCxUnexpiredRein.setValMethod(contract.getValMethod());
    intMeasureCxUnexpiredRein.setReinSystemCode(contract.getReinSystemCode());
    intMeasureCxUnexpiredRein.setStartDate(contract.getStartDate());
    intMeasureCxUnexpiredRein.setEndDate((contract.getEndDate()));
    intMeasureCxUnexpiredRein.setIniConfirm(contract.getIniConfirm());
    intMeasureCxUnexpiredRein.setInvestProp(contract.getInvestProp());

    ////未到期字段
    intMeasureCxUnexpiredRein.setOpeningBalance(openingBalance);
    intMeasureCxUnexpiredRein.setNetPremium(netPremium);
    intMeasureCxUnexpiredRein.setBaseInvestment(baseInvestment);
    intMeasureCxUnexpiredRein.setIacf(iacf);
    intMeasureCxUnexpiredRein.setPremiumCashFlow(premiumCashFlow);
    intMeasureCxUnexpiredRein.setNetPremiumCashFlow(netPremiumCashFlow);
    intMeasureCxUnexpiredRein.setIacfCashFlow(iacfCashFlow);
    intMeasureCxUnexpiredRein.setIfieAmt(ifieAmt);
    intMeasureCxUnexpiredRein.setCumulativeIfieAmt(cumulativeIfieAmt);
    intMeasureCxUnexpiredRein.setCumulativeDays(BigDecimal.valueOf(cumulativeDays));
    intMeasureCxUnexpiredRein.setCumulativeProportion(cumulativeProportion);
    intMeasureCxUnexpiredRein.setPremiumAmortization(premiumAmortization);
    intMeasureCxUnexpiredRein.setIacfAmortization(iacfAmortization);
    intMeasureCxUnexpiredRein.setNetPremiumAmortization(netPremiumAmortization);
    intMeasureCxUnexpiredRein.setCumulativeIfieAmtAmortization(cumulativeIfieAmtAmortization);
    intMeasureCxUnexpiredRein.setIncomeThisPeriodBeforeSplitting(incomeThisPeriodBeforeSplitting);
    intMeasureCxUnexpiredRein.setBaseInvestmentAmortization(baseInvestmentAmortization);
    intMeasureCxUnexpiredRein.setBaseInvestmentAmortizationThisPeriod(baseInvestmentAmortizationThisPeriod);
    intMeasureCxUnexpiredRein.setIncomeThisPeriod(incomeThisPeriod);
    intMeasureCxUnexpiredRein.setClosingBalance(closingBalance);
    intMeasureCxUnexpiredRein.setFuturePremiums(futurePremiums);
    intMeasureCxUnexpiredRein.setLossComponent(lossComponent);
    intMeasureCxUnexpiredRein.setLrcDebt(lrcDebt);
    //intMeasureCxUnexpiredRein.setMonthCount(monthCount);
    intMeasureCxUnexpiredRein.setNetPremiumAmortizationThisPeriod(netPremiumAmortizationThisPeriod);
    intMeasureCxUnexpiredRein.setCumulativeIfieAmtAmortizationThisPeriod(cumulativeIfieAmtAmortizationThisPeriod);

    intMeasureCxUnexpiredRein.setPremiumAmortizationThisPeriod(premiumAmortizationThisPeriod);
    intMeasureCxUnexpiredRein.setIacfAmortizationThisPeriod(iacfAmortizationThisPeriod);

    return intMeasureCxUnexpiredRein;


  }


  private IntMeasureCxUnexpiredRein calculateLrcReinOutWithMonthlyRolling(IntTPpReMonArrNewCombine contract, String valMonth,
                                                                          Map<String, Map<Integer, BigDecimal>> disRateMap,
                                                                          Map<String, Map<String, BigDecimal>> resultAllocationMapMap) {
    // 获取合同基本信息需处理的基本数据
    LocalDate contractStartDate;
    LocalDate contractEndDate;
    LocalDate iniConfirmDate;
    LocalDate compareDate;
    try {
      // 获取合同基本信息并解析日期
      contractStartDate = LocalDate.parse(contract.getStartDate(), YYYYMMDD_FORMATTER);
      contractEndDate = LocalDate.parse(contract.getEndDate(), YYYYMMDD_FORMATTER);
      iniConfirmDate = LocalDate.parse(contract.getIniConfirm(), YYYYMMDD_FORMATTER);

      // 2. 【核心精简逻辑】：直接选出 Date 对象
      // 判断是否为批单 (有批单号且不为空)
      boolean isCerti = contract.getCertiNo() != null && !contract.getCertiNo().trim().isEmpty();

      // 是批单取 CertiWriteDate，否则取 UnderWriteDate
      Date targetDate = isCerti ? contract.getCertiWriteDate() : contract.getUnderWriteDate();

      // 3. 【判空】：如果取出来的日期是 null，直接报错跳过
      if (targetDate == null) {
        throw new NullPointerException(isCerti ? "批单日期(CertiWriteDate)为NULL" : "签单日期(UnderWriteDate)为NULL");
      }

      // 4. 【转换】：Date -> LocalDate (使用默认时区转换)
      compareDate = targetDate.toInstant().atZone(java.time.ZoneId.systemDefault()).toLocalDate();

    } catch (Exception e) {
      // 日期格式错误则跳过该合同
      System.err.println("跳过合同(数据异常): ID=" + contract.getId() + " 原因: " + e.getMessage());
      return null;
    }

    //确定计息起点 初始确认日 和 confirmDate 孰晚
    LocalDate interestStartDate = iniConfirmDate.isAfter(compareDate) ? iniConfirmDate : compareDate;

    if (YearMonth.parse(valMonth, YYYYMM_FORMATTER).isBefore(YearMonth.from(interestStartDate))) {
      System.err.println("跳过合同（评估时点在计息日之前）: 源数据id=" + contract.getId());
      return null;
    }

    if (contractEndDate.isBefore(contractStartDate)) {
      System.err.println("跳过合同（责任止期在责任起期之前）: 源数据id=" + contract.getId());
      return null;
    }

    // 评估月月末日期
    LocalDate valDate = YearMonth.parse(valMonth, YYYYMM_FORMATTER).atEndOfMonth();

    boolean isFirstPeriod = true;

    // --- 1. 初始化状态 (从上期结果字段继承) ---
    BigDecimal prevCumulativeIfieAmt = BigDecimal.ZERO;
    BigDecimal prevNetPremiumAmortization = BigDecimal.ZERO;
    BigDecimal prevCumulativeIfieAmtAmortization = BigDecimal.ZERO;
    BigDecimal prevBaseInvestmentAmortization = BigDecimal.ZERO;

    BigDecimal prevPremiumAmortization = BigDecimal.ZERO;

    //当期数
    //期初非亏
    BigDecimal openingBalance = BigDecimal.ZERO;
    //毛保费现金流
    BigDecimal premiumCashFlow = BigDecimal.ZERO;
    //净保费现金流
    BigDecimal netPremiumCashFlow = BigDecimal.ZERO;
    //跟单获取费用现金流
    BigDecimal iacfCashFlow = BigDecimal.ZERO;
    //当期计息
    BigDecimal ifieAmt = BigDecimal.ZERO;
    //累积计息
    BigDecimal cumulativeIfieAmt = BigDecimal.ZERO;
    //累积有效天数
    long cumulativeDays = 0;
    //摊销比例
    BigDecimal cumulativeProportion = BigDecimal.ZERO;
    //预收毛保费摊销
    BigDecimal premiumAmortization = BigDecimal.ZERO;
    //预付跟单获取费用摊销
    BigDecimal iacfAmortization = BigDecimal.ZERO;
    //预收净保费摊销
    BigDecimal netPremiumAmortization = BigDecimal.ZERO;
    //累积计息摊销
    BigDecimal cumulativeIfieAmtAmortization = BigDecimal.ZERO;
    //保险服务收入(分解投资成分前)
    BigDecimal incomeThisPeriodBeforeSplitting = BigDecimal.ZERO;
    //投资成分摊销
    BigDecimal baseInvestmentAmortization = BigDecimal.ZERO;
    //当期投资成分摊销
    BigDecimal baseInvestmentAmortizationThisPeriod = BigDecimal.ZERO;
    //保险服务收入
    BigDecimal incomeThisPeriod = BigDecimal.ZERO;
    //期末非亏
    BigDecimal closingBalance = BigDecimal.ZERO;
    //未满期保费
    BigDecimal futurePremiums;
    //亏损
    BigDecimal lossComponent;
    //未到期责任负债
    BigDecimal lrcDebt;
    //当期预收净保费摊销
    BigDecimal netPremiumAmortizationThisPeriod = BigDecimal.ZERO;
    //当期累积计息摊销
    BigDecimal cumulativeIfieAmtAmortizationThisPeriod = BigDecimal.ZERO;


    BigDecimal premiumAmortizationThisPeriod = BigDecimal.ZERO;

    BigDecimal iacfAmortizationThisPeriod = BigDecimal.ZERO;


    //预付跟单获取费用(预定手续费率 + 预定经纪费率)
    BigDecimal iacf = contract.getCommission();

    //实际预收净保费 = 保费 - 手续费 - 经纪费
    BigDecimal netPremium = contract.getPremium().subtract(iacf).setScale(SCALE, ROUNDING_MODE);

    //投资成分 = 毛保费 * 保底赔付率
    BigDecimal baseInvestment = contract.getPremium().multiply(Optional.ofNullable(contract.getInvestProp()).orElse(BigDecimal.ZERO)).setScale(SCALE, ROUNDING_MODE);

    // 计算合同总天数 算摊销比例
    long totalDaysInContract = ChronoUnit.DAYS.between(contractStartDate, contractEndDate) + 1;
    BigDecimal totalDaysInContractBD = new BigDecimal(totalDaysInContract);

    // 实际循环范围 (从计息起点 -> 评估月)
    LocalDate iterStart = interestStartDate.withDayOfMonth(1); // 从初始确认月的第一天开始
    LocalDate iterEnd = valDate.withDayOfMonth(1);   // 到评估月的第一天结束

    // 初始确认日对应的月利率曲线 算计息 - 移到循环外，因为不会变化
    String iniConfirmMonthStr = iniConfirmDate.format(YYYYMM_FORMATTER);
    Map<Integer, BigDecimal> startMonthRateMap = disRateMap.getOrDefault(iniConfirmMonthStr, Collections.emptyMap());

    //当期月份
    int monthCount = 0; // 月份计数器，用于查找利率

    for (LocalDate monthIter = iterStart; !monthIter.isAfter(iterEnd); monthIter = monthIter.plusMonths(1)) {
      monthCount++;
      LocalDate periodEnd = monthIter.with(TemporalAdjusters.lastDayOfMonth()); // 当前计算期间的结束日期
      LocalDate prevPeriodEnd = monthIter.minusMonths(1).with(TemporalAdjusters.lastDayOfMonth()); // 上一期间的结束日期

      // 确定当前期间在合同内的有效起止日期（用于计息）
      LocalDate effectiveStart = interestStartDate.isAfter(prevPeriodEnd) ? interestStartDate : prevPeriodEnd.plusDays(1);
      LocalDate effectiveEnd = contractEndDate.isBefore(periodEnd) ? contractEndDate : periodEnd;

      // 确定当前期间的有效天数（用于计息）
      long daysInThisPeriod = ChronoUnit.DAYS.between(effectiveStart, effectiveEnd) + 1;
      if (daysInThisPeriod <= 0) {
        daysInThisPeriod = 0;
      }

      // 计算累计摊销天数：当月月底 >= start_date 时，累计天数 = start_date 到 当月月底（封顶到 end_date）
      if (!periodEnd.isBefore(contractStartDate)) {
        LocalDate capEnd = contractEndDate.isBefore(periodEnd) ? contractEndDate : periodEnd;
        cumulativeDays = ChronoUnit.DAYS.between(contractStartDate, capEnd) + 1;
      }

      // 计算累计摊销比例
      cumulativeProportion = new BigDecimal(cumulativeDays).divide(totalDaysInContractBD, SCALE, ROUNDING_MODE);

      //需要后续计算使用的 现金流数据
      // 净保费现金流仅在第一个期间发生(过渡期 起期)
      netPremiumCashFlow = isFirstPeriod ? netPremium : BigDecimal.ZERO;

      // 毛保费现金流仅在第一个期间发生(过渡期 起期)
      premiumCashFlow = isFirstPeriod ? contract.getPremium() : BigDecimal.ZERO;

      //跟单获取费用现金流仅在第一个期限发生(过渡期 起期)
      iacfCashFlow = isFirstPeriod ? iacf : BigDecimal.ZERO;

      //计算
      //非亏部分
      //1.1 期初未到期责任负债_非亏部分 for循环外已经定义 openingBalance
      //1.2 现金流_收到的保费 premiumCashflow
      //1.3 现金流_支付的获取费用 iacfCashflow
      //1.4 IFIE_未到期计息
      //取起期利率曲线的monthCount个月的利率
      if (daysInThisPeriod == 0) {
        ifieAmt = BigDecimal.ZERO;
      } else {
        int monthCountStr = Math.min(monthCount + (int) ChronoUnit.MONTHS.between(iniConfirmDate, interestStartDate), MAX_MONTH_COUNT);
        BigDecimal periodInterestRate = startMonthRateMap.getOrDefault(monthCountStr, BigDecimal.ZERO);

        //1.4 IFIE_未到期计息
        // (A) 期初余额产生的利息 (计息一整个周期)
        BigDecimal interestFromOpening = openingBalance.multiply(periodInterestRate).setScale(SCALE, ROUNDING_MODE);
        // (B) 期间净保费现金流产生的利息 (假设期中流入/流出，计息半个周期)
        BigDecimal interestFromCashFlow = netPremiumCashFlow.multiply(periodInterestRate).multiply(BigDecimal.valueOf(0.5)).setScale(SCALE, ROUNDING_MODE);
        // (C) 总利息 = A + B
        ifieAmt = interestFromOpening.add(interestFromCashFlow).setScale(SCALE, ROUNDING_MODE);
      }

      cumulativeIfieAmt = prevCumulativeIfieAmt.add(ifieAmt).setScale(SCALE, ROUNDING_MODE);
      cumulativeIfieAmtAmortization = cumulativeIfieAmt.multiply(cumulativeProportion).setScale(SCALE, ROUNDING_MODE);

      //当期累积计息摊销
      cumulativeIfieAmtAmortizationThisPeriod = cumulativeIfieAmtAmortization.subtract(prevCumulativeIfieAmtAmortization).setScale(SCALE, ROUNDING_MODE);

      //保险服务收入 = 预收保费(净)摊销 + 累积计息摊销
      //预收毛保费摊销
      premiumAmortization = contract.getPremium().multiply(cumulativeProportion).setScale(SCALE, ROUNDING_MODE);

      //当期预收毛保费摊销
      premiumAmortizationThisPeriod = premiumAmortization.subtract(prevPremiumAmortization).setScale(SCALE, ROUNDING_MODE);

      //预付跟单获取费用摊销
      iacfAmortization = iacf.multiply(cumulativeProportion).setScale(SCALE, ROUNDING_MODE);

      //预收保费(净)摊销
      netPremiumAmortization = premiumAmortization.subtract(iacfAmortization).setScale(SCALE, ROUNDING_MODE);

      //当期预收保费(净)摊销
      netPremiumAmortizationThisPeriod = netPremiumAmortization.subtract(prevNetPremiumAmortization).setScale(SCALE, ROUNDING_MODE);

      //当期跟单获取费用摊销
      iacfAmortizationThisPeriod = premiumAmortizationThisPeriod.subtract(netPremiumAmortizationThisPeriod).setScale(SCALE, ROUNDING_MODE);

      //保险服务收入(分解投资成分前)
      incomeThisPeriodBeforeSplitting = netPremiumAmortizationThisPeriod.add(cumulativeIfieAmtAmortizationThisPeriod).setScale(SCALE, ROUNDING_MODE);

      //投资成分摊销
      baseInvestmentAmortization = baseInvestment.multiply(cumulativeProportion).setScale(SCALE, ROUNDING_MODE);

      //当期投资成分摊销
      baseInvestmentAmortizationThisPeriod = baseInvestmentAmortization.subtract(prevBaseInvestmentAmortization).setScale(SCALE, ROUNDING_MODE);

      //保险服务收入
      incomeThisPeriod = incomeThisPeriodBeforeSplitting.subtract(baseInvestmentAmortizationThisPeriod).setScale(SCALE, ROUNDING_MODE);

      //非亏
      closingBalance = openingBalance
        .add(netPremiumCashFlow).add(ifieAmt)
        .subtract(incomeThisPeriod).subtract(baseInvestmentAmortizationThisPeriod)
        .setScale(SCALE, ROUNDING_MODE);

      if (!monthIter.plusMonths(1).isAfter(iterEnd)) {
        openingBalance = closingBalance;
        prevCumulativeIfieAmt = cumulativeIfieAmt;
        prevNetPremiumAmortization = netPremiumAmortization;
        prevCumulativeIfieAmtAmortization = cumulativeIfieAmtAmortization;
        prevBaseInvestmentAmortization = baseInvestmentAmortization;

        prevPremiumAmortization = premiumAmortization;
      }
      isFirstPeriod = false;
    }

    //亏损部分
    // 计算未来服务量比例
    BigDecimal futureProportion = BigDecimal.ONE.subtract(cumulativeProportion).setScale(SCALE, ROUNDING_MODE).max(BigDecimal.ZERO);
    //未满期保费
    futurePremiums = contract.getPremium().multiply(futureProportion).setScale(SCALE, ROUNDING_MODE);

    // 根据保单号和批单号查找历史亏损分摊数据
    String key = StringUtils.joinWith("_", Opt.ofBlankAble(contract.getPolicyNo()).orElse(StringConstant.STRING_NA), Opt.ofBlankAble(contract.getCertiNo()).orElse(StringConstant.STRING_NA),
      Opt.ofBlankAble(contract.getRiskCode()).orElse(StringConstant.STRING_NA));
   /* BigDecimal lossAllocation = resultAllocationMap.getOrDefault(key, BigDecimal.ZERO);
    BigDecimal shareRate = contract.getShareRate() != null ? contract.getShareRate() : BigDecimal.ZERO;

    // 计算亏损部分：历史亏损分摊 * 分保份额
    lossComponent = lossAllocation.multiply(shareRate).setScale(SCALE, ROUNDING_MODE);*/
    // 获取 premium
    BigDecimal premium = Optional.ofNullable(resultAllocationMapMap.get(key))
      .map(innerMap -> innerMap.get("premium"))
      .orElse(BigDecimal.ZERO);

    //loss_component_allocation
    BigDecimal lossComponentAllocation = Optional.ofNullable(resultAllocationMapMap.get(key))
      .map(innerMap -> innerMap.get("lossComponentAllocation"))
      .orElse(BigDecimal.ZERO);

    // 计算亏损部分：历史亏损分摊 * 分保份额
    if (premium.compareTo(BigDecimal.ZERO) == 0) {
      lossComponent = BigDecimal.ZERO;
    } else {
      BigDecimal shareRate = contract.getPremium().divide(premium, SCALE, ROUNDING_MODE).setScale(SCALE, ROUNDING_MODE);
      lossComponent = lossComponentAllocation.multiply(shareRate).setScale(SCALE, ROUNDING_MODE);
    }

    //未到期责任负债
    lrcDebt = closingBalance.add(lossComponent).setScale(SCALE, ROUNDING_MODE);

    //返回评估时点的明细结果
    //Date转string格式入库 jdbcTemplate 处理 date数据不太行 效率影响很大
    String underWriteDateStr = (contract.getUnderWriteDate() == null) ? null : DateFormatUtils.format(contract.getUnderWriteDate(), YYYYMMDD);
    String certiWriteDateStr = (contract.getCertiWriteDate() == null) ? null : DateFormatUtils.format(contract.getCertiWriteDate(), YYYYMMDD);
    String validDateStr = (contract.getValidDate() == null) ? null : DateFormatUtils.format(contract.getValidDate(), YYYYMMDD);
    String piStartDateStr = (contract.getPiStartDate() == null) ? null : DateFormatUtils.format(contract.getPiStartDate(), YYYYMMDD);
    String PiEndDateStr = (contract.getPiEndDate() == null) ? null : DateFormatUtils.format(contract.getPiEndDate(), YYYYMMDD);

    IntMeasureCxUnexpiredRein intMeasureCxUnexpiredRein = new IntMeasureCxUnexpiredRein();
    intMeasureCxUnexpiredRein.setSourceId(contract.getId());
    intMeasureCxUnexpiredRein.setContractFlag(contract.getContractFlag());
    intMeasureCxUnexpiredRein.setReinType(contract.getReinType());
    intMeasureCxUnexpiredRein.setContractType(contract.getContractType());
    intMeasureCxUnexpiredRein.setEnquiryType(contract.getEnquiryType());
    intMeasureCxUnexpiredRein.setContractId(contract.getContractId());
    intMeasureCxUnexpiredRein.setSectionNo(contract.getSectionNo());
    intMeasureCxUnexpiredRein.setShareRate(contract.getShareRate());
    intMeasureCxUnexpiredRein.setPolicyNo(contract.getPolicyNo());
    intMeasureCxUnexpiredRein.setCertiNo(contract.getCertiNo());
    intMeasureCxUnexpiredRein.setUnderWriteDate(underWriteDateStr);
    intMeasureCxUnexpiredRein.setCertiWriteDate(certiWriteDateStr);
    intMeasureCxUnexpiredRein.setValidDate(validDateStr);
    intMeasureCxUnexpiredRein.setPiStartDate(piStartDateStr);
    intMeasureCxUnexpiredRein.setPiEndDate(PiEndDateStr);
    intMeasureCxUnexpiredRein.setPremium(contract.getPremium());
    intMeasureCxUnexpiredRein.setCurrency(contract.getCurrency());
    intMeasureCxUnexpiredRein.setCommission(contract.getCommission());
    intMeasureCxUnexpiredRein.setClassCode(contract.getClassCode());
    intMeasureCxUnexpiredRein.setRiskCode(contract.getRiskCode());
    intMeasureCxUnexpiredRein.setComCode(contract.getComCode());
    intMeasureCxUnexpiredRein.setCarKindCode(contract.getCarKindCode());
    intMeasureCxUnexpiredRein.setUseNatureCode(contract.getUseNatureCode());
    intMeasureCxUnexpiredRein.setUnitId(contract.getUnitId());
    intMeasureCxUnexpiredRein.setMinUnitId(contract.getMinUnitId());
    intMeasureCxUnexpiredRein.setPortfolioId(contract.getPortfolioId());
    intMeasureCxUnexpiredRein.setGroupId(contract.getGroupId());
    intMeasureCxUnexpiredRein.setValMonth(contract.getValMonth());
    intMeasureCxUnexpiredRein.setValMethod(contract.getValMethod());
    intMeasureCxUnexpiredRein.setReinSystemCode(contract.getReinSystemCode());
    intMeasureCxUnexpiredRein.setStartDate(contract.getStartDate());
    intMeasureCxUnexpiredRein.setEndDate((contract.getEndDate()));
    intMeasureCxUnexpiredRein.setIniConfirm(contract.getIniConfirm());
    intMeasureCxUnexpiredRein.setInvestProp(contract.getInvestProp());

    ////未到期字段
    intMeasureCxUnexpiredRein.setOpeningBalance(openingBalance);
    intMeasureCxUnexpiredRein.setNetPremium(netPremium);
    intMeasureCxUnexpiredRein.setBaseInvestment(baseInvestment);
    intMeasureCxUnexpiredRein.setIacf(iacf);
    intMeasureCxUnexpiredRein.setPremiumCashFlow(premiumCashFlow);
    intMeasureCxUnexpiredRein.setNetPremiumCashFlow(netPremiumCashFlow);
    intMeasureCxUnexpiredRein.setIacfCashFlow(iacfCashFlow);
    intMeasureCxUnexpiredRein.setIfieAmt(ifieAmt);
    intMeasureCxUnexpiredRein.setCumulativeIfieAmt(cumulativeIfieAmt);
    intMeasureCxUnexpiredRein.setCumulativeDays(BigDecimal.valueOf(cumulativeDays));
    intMeasureCxUnexpiredRein.setCumulativeProportion(cumulativeProportion);
    intMeasureCxUnexpiredRein.setPremiumAmortization(premiumAmortization);
    intMeasureCxUnexpiredRein.setIacfAmortization(iacfAmortization);
    intMeasureCxUnexpiredRein.setNetPremiumAmortization(netPremiumAmortization);
    intMeasureCxUnexpiredRein.setCumulativeIfieAmtAmortization(cumulativeIfieAmtAmortization);
    intMeasureCxUnexpiredRein.setIncomeThisPeriodBeforeSplitting(incomeThisPeriodBeforeSplitting);
    intMeasureCxUnexpiredRein.setBaseInvestmentAmortization(baseInvestmentAmortization);
    intMeasureCxUnexpiredRein.setBaseInvestmentAmortizationThisPeriod(baseInvestmentAmortizationThisPeriod);
    intMeasureCxUnexpiredRein.setIncomeThisPeriod(incomeThisPeriod);
    intMeasureCxUnexpiredRein.setClosingBalance(closingBalance);
    intMeasureCxUnexpiredRein.setFuturePremiums(futurePremiums);
    intMeasureCxUnexpiredRein.setLossComponent(lossComponent);
    intMeasureCxUnexpiredRein.setLrcDebt(lrcDebt);
    //intMeasureCxUnexpiredRein.setMonthCount(monthCount);
    intMeasureCxUnexpiredRein.setNetPremiumAmortizationThisPeriod(netPremiumAmortizationThisPeriod);
    intMeasureCxUnexpiredRein.setCumulativeIfieAmtAmortizationThisPeriod(cumulativeIfieAmtAmortizationThisPeriod);

    intMeasureCxUnexpiredRein.setPremiumAmortizationThisPeriod(premiumAmortizationThisPeriod);
    intMeasureCxUnexpiredRein.setIacfAmortizationThisPeriod(iacfAmortizationThisPeriod);

    return intMeasureCxUnexpiredRein;
  }


  /**
   * 过渡期从保险责任起期滚动计量到评估时点
   */
  private IntMeasureCxUnexpiredRein calculateLrcReinInWithMonthlyRolling(IntTPpReMonArrInNewCombine contract, String valMonth,
                                                                         Map<String, Map<String, ConfMeasureActuarialAssumption>> assumptionMap,
                                                                         Map<String, BigDecimal[]> discountFactor,
                                                                         Map<String, Map<Integer, BigDecimal>> disRateMap) {
    // 获取合同基本信息需处理的基本数据
    LocalDate contractStartDate;
    LocalDate contractEndDate;
    LocalDate iniConfirmDate;
    LocalDate confirmDate;
    try {
      // 获取合同基本信息并解析日期
      contractStartDate = LocalDate.parse(contract.getStartDate(), YYYYMMDD_FORMATTER);
      contractEndDate = LocalDate.parse(contract.getEndDate(), YYYYMMDD_FORMATTER);
      iniConfirmDate = LocalDate.parse(contract.getIniConfirm(), YYYYMMDD_FORMATTER);
      confirmDate = contract.getConfirmDate().toInstant().atZone(ZoneId.systemDefault()).toLocalDate();
    } catch (Exception e) {
      // 日期格式错误则跳过该合同
      System.err.println("跳过合同（日期格式错误）: 源数据id=" + contract.getId());
      return null;
    }

    //确定计息起点 初始确认日 和 confirmDate 孰晚
    LocalDate interestStartDate = iniConfirmDate.isAfter(confirmDate) ? iniConfirmDate : confirmDate;

    if (YearMonth.parse(valMonth, YYYYMM_FORMATTER).isBefore(YearMonth.from(interestStartDate))) {
      System.err.println("跳过合同（评估时点在计息日之前）: 源数据id=" + contract.getId());
      return null;
    }

    if (contractEndDate.isBefore(contractStartDate)) {
      System.err.println("跳过合同（责任止期在责任起期之前）: 源数据id=" + contract.getId());
      return null;
    }

    // 评估月月末日期
    LocalDate valDate = YearMonth.parse(valMonth, YYYYMM_FORMATTER).atEndOfMonth();

    boolean isFirstPeriod = true;

    // --- 1. 初始化状态 (从上期结果字段继承) ---
    BigDecimal prevCumulativeIfieAmt = BigDecimal.ZERO;
    BigDecimal prevCumulativeNoIacf = BigDecimal.ZERO;
    BigDecimal prevNetPremiumAmortization = BigDecimal.ZERO;
    BigDecimal prevCumulativeIfieAmtAmortization = BigDecimal.ZERO;
    BigDecimal prevBaseInvestmentAmortization = BigDecimal.ZERO;
    BigDecimal prevCumulativeNoIacfAmortization = BigDecimal.ZERO;

    BigDecimal prevPremiumAmortization = BigDecimal.ZERO;

    //当期数
    //期初非亏
    BigDecimal openingBalance = BigDecimal.ZERO;
    //毛保费现金流
    BigDecimal premiumCashFlow = BigDecimal.ZERO;
    //净保费现金流
    BigDecimal netPremiumCashFlow = BigDecimal.ZERO;
    //跟单获取费用现金流
    BigDecimal iacfCashFlow = BigDecimal.ZERO;
    //非跟单获取费用现金流
    BigDecimal noIacfCashFlow = BigDecimal.ZERO;
    //当期计息
    BigDecimal ifieAmt = BigDecimal.ZERO;
    //累积计息
    BigDecimal cumulativeIfieAmt = BigDecimal.ZERO;
    //累积非跟单获取费用
    BigDecimal cumulativeNoIacf = BigDecimal.ZERO;
    //累积有效天数
    long cumulativeDays = 0;
    //摊销比例
    BigDecimal cumulativeProportion = BigDecimal.ZERO;
    //预收毛保费摊销
    BigDecimal premiumAmortization = BigDecimal.ZERO;
    //预付跟单获取费用摊销
    BigDecimal iacfAmortization = BigDecimal.ZERO;
    //预收净保费摊销
    BigDecimal netPremiumAmortization = BigDecimal.ZERO;
    //累积计息摊销
    BigDecimal cumulativeIfieAmtAmortization = BigDecimal.ZERO;
    //保险服务收入(分解投资成分前)
    BigDecimal incomeThisPeriodBeforeSplitting = BigDecimal.ZERO;
    //投资成分摊销
    BigDecimal baseInvestmentAmortization = BigDecimal.ZERO;
    //当期投资成分摊销
    BigDecimal baseInvestmentAmortizationThisPeriod = BigDecimal.ZERO;
    //保险服务收入
    BigDecimal incomeThisPeriod = BigDecimal.ZERO;
    //累积非跟单获取费用摊销
    BigDecimal cumulativeNoIacfAmortization = BigDecimal.ZERO;
    //当期非跟单获取费用摊销
    BigDecimal cumulativeNoIacfAmortizationThisPeriod = BigDecimal.ZERO;
    //期末非亏
    BigDecimal closingBalance = BigDecimal.ZERO;
    //未满期保费
    BigDecimal futurePremiums = BigDecimal.ZERO;
    //预期未来维持费用现值
    BigDecimal pvFutureMaintenance = BigDecimal.ZERO;
    //预期未来赔付费用现值
    BigDecimal pvFutureLoss = BigDecimal.ZERO;
    //风险调整
    BigDecimal riskAdjustment = BigDecimal.ZERO;
    //预期未来现金流
    BigDecimal futureCashFlow = BigDecimal.ZERO;
    //亏损
    BigDecimal lossComponent = BigDecimal.ZERO;
    //未到期责任负债
    BigDecimal lrcDebt = BigDecimal.ZERO;
    //当期预收净保费摊销
    BigDecimal netPremiumAmortizationThisPeriod = BigDecimal.ZERO;
    //当期累积计息摊销
    BigDecimal cumulativeIfieAmtAmortizationThisPeriod = BigDecimal.ZERO;


    BigDecimal premiumAmortizationThisPeriod = BigDecimal.ZERO;

    BigDecimal iacfAmortizationThisPeriod = BigDecimal.ZERO;


    //非跟单获取费用 (保费 * 精算假设获取费用率 - 保费 * 精算假设首日获取费用率)
    /*BigDecimal acquisitionExpenseRatio = Optional.ofNullable(assumptionMap.getOrDefault(iniConfirmDate.format(YYYYMM_FORMATTER), Collections.emptyMap())
      .getOrDefault(contract.getClassCode(), new ConfMeasureActuarialAssumption()).getAcquisitionExpenseRatio()).orElse(BigDecimal.ZERO);
    BigDecimal firstDayAcquisitionExpenseRatio = Optional.ofNullable(assumptionMap.getOrDefault(iniConfirmDate.format(YYYYMM_FORMATTER), Collections.emptyMap())
      .getOrDefault(contract.getClassCode(), new ConfMeasureActuarialAssumption()).getFirstDayAcquisitionExpenseRatio()).orElse(BigDecimal.ZERO);*/

    BigDecimal noIacf = contract.getIacfUnfol();
/*    if (contract.getIniConfirm().compareTo("20240101") >= 0) {
      noIacf = contract.getIacfUnfol();
    } else {
      //过渡期旧单不要非跟单获取费用，因为用精算假设算出来的，太大
*//*
      noIacf = contract.getPremium().multiply((acquisitionExpenseRatio.subtract(firstDayAcquisitionExpenseRatio)));
*//*

    }*/

    //预付跟单获取费用(预定手续费率 + 预定经纪费率) 又不用精算假设了
/*
    BigDecimal iacf = contract.getPremium().multiply(firstDayAcquisitionExpenseRatio);
*/
    BigDecimal iacf = contract.getCommission().add(contract.getBrokerage()).setScale(SCALE, ROUNDING_MODE);

    //实际预收净保费 = 保费 - 手续费 - 经纪费
    BigDecimal netPremium = contract.getPremium().subtract(iacf).setScale(SCALE, ROUNDING_MODE);

    //投资成分 = 毛保费 * 保底赔付率
    BigDecimal baseInvestment = contract.getPremium().multiply(Optional.ofNullable(contract.getInvestProp()).orElse(BigDecimal.ZERO)).setScale(SCALE, ROUNDING_MODE);

    // 计算合同总天数 算摊销比例
    long totalDaysInContract = ChronoUnit.DAYS.between(contractStartDate, contractEndDate) + 1;
    BigDecimal totalDaysInContractBD = new BigDecimal(totalDaysInContract);

    // 计算合同总月数
    int totalMonths = 0; //计算投资成分 折现 ，亏损折现
/*    LocalDate monthCountStart = iniConfirmDate.withDayOfMonth(1); // 从初始确认月的第一天开始
    LocalDate monthCountEnd = contractEndDate.withDayOfMonth(1);   // 到合同结束月的第一天结束
    for (LocalDate iter = monthCountStart; !iter.isAfter(monthCountEnd); iter = iter.plusMonths(1)) {
      totalMonths++;
    }*/
    LocalDate monthCountStart = interestStartDate.withDayOfMonth(1); // 从计息起点的第一天开始
    LocalDate monthCountEnd = contractEndDate.withDayOfMonth(1);   // 到合同结束月的第一天结束
    for (LocalDate iter = monthCountStart; !iter.isAfter(monthCountEnd); iter = iter.plusMonths(1)) {
      totalMonths++;
    }

    // 实际循环范围 (从计息起点 -> 评估月)
    LocalDate iterStart = interestStartDate.withDayOfMonth(1); // 从初始确认月的第一天开始
    LocalDate iterEnd = valDate.withDayOfMonth(1);   // 到评估月的第一天结束

    // 初始确认日对应的月利率曲线 算计息 - 移到循环外，因为不会变化
    String iniConfirmMonthStr = iniConfirmDate.format(YYYYMM_FORMATTER);
    Map<Integer, BigDecimal> startMonthRateMap = disRateMap.getOrDefault(iniConfirmMonthStr, Collections.emptyMap());

    int monthCount = 0; // 月份计数器，用于查找利率

    for (LocalDate monthIter = iterStart; !monthIter.isAfter(iterEnd); monthIter = monthIter.plusMonths(1)) {
      monthCount++;
      LocalDate periodEnd = monthIter.with(TemporalAdjusters.lastDayOfMonth()); // 当前计算期间的结束日期
      LocalDate prevPeriodEnd = monthIter.minusMonths(1).with(TemporalAdjusters.lastDayOfMonth()); // 上一期间的结束日期

      // 确定当前期间在合同内的有效起止日期（用于计息）
      LocalDate effectiveStart = interestStartDate.isAfter(prevPeriodEnd) ? interestStartDate : prevPeriodEnd.plusDays(1);
      LocalDate effectiveEnd = contractEndDate.isBefore(periodEnd) ? contractEndDate : periodEnd;

      // 确定当前期间的有效天数（用于计息）
      long daysInThisPeriod = ChronoUnit.DAYS.between(effectiveStart, effectiveEnd) + 1;
      if (daysInThisPeriod <= 0) {
        daysInThisPeriod = 0;
      }

      // 计算累计摊销天数：当月月底 >= start_date 时，累计天数 = start_date 到 当月月底（封顶到 end_date）
      if (!periodEnd.isBefore(contractStartDate)) {
        LocalDate capEnd = contractEndDate.isBefore(periodEnd) ? contractEndDate : periodEnd;
        cumulativeDays = ChronoUnit.DAYS.between(contractStartDate, capEnd) + 1;
      }

      // 计算累计摊销比例
      cumulativeProportion = new BigDecimal(cumulativeDays).divide(totalDaysInContractBD, SCALE, ROUNDING_MODE);

      // 需要后续计算使用的基础数据准备配置数据
      // 当前期间精算假设
      String currentMonthStr = monthIter.format(YYYYMM_FORMATTER);
      ConfMeasureActuarialAssumption assumption = assumptionMap.getOrDefault(currentMonthStr, Collections.emptyMap())
        .getOrDefault(contract.getClassCode(), new ConfMeasureActuarialAssumption());

      //当前期间对应的月利率曲线 算折现
      Map<Integer, BigDecimal> currentMonthRateMap = disRateMap.getOrDefault(currentMonthStr, Collections.emptyMap());

      //需要后续计算使用的 现金流数据
      // 净保费现金流仅在第一个期间发生(过渡期 起期)
      netPremiumCashFlow = isFirstPeriod ? netPremium : BigDecimal.ZERO;

      // 毛保费现金流仅在第一个期间发生(过渡期 起期)
      premiumCashFlow = isFirstPeriod ? contract.getPremium() : BigDecimal.ZERO;

      // 非跟单获取费用现金流仅在第一个期限发生(过渡期 起期)
      noIacfCashFlow = isFirstPeriod ? noIacf : BigDecimal.ZERO;

      //跟单获取费用现金流仅在第一个期限发生(过渡期 起期)
      iacfCashFlow = isFirstPeriod ? iacf : BigDecimal.ZERO;

      //计算
      //非亏部分
      //1.1 期初未到期责任负债_非亏部分 for循环外已经定义 openingBalance
      //1.2 现金流_收到的保费 premiumCashflow
      //1.3 现金流_支付的获取费用 iacfCashflow
      //1.4 IFIE_未到期计息
      //取起期利率曲线的monthCount个月的利率
      if (daysInThisPeriod == 0) {
        ifieAmt = BigDecimal.ZERO;
      } else {
        int monthCountStr = Math.min(monthCount + (int) ChronoUnit.MONTHS.between(iniConfirmDate, interestStartDate), MAX_MONTH_COUNT);
        BigDecimal periodInterestRate = startMonthRateMap.getOrDefault(monthCountStr, BigDecimal.ZERO);

        //1.4 IFIE_未到期计息
        // (A) 期初余额产生的利息 (计息一整个周期)
        BigDecimal interestFromOpening = openingBalance.multiply(periodInterestRate).setScale(SCALE, ROUNDING_MODE);
        // (B) 期间净现金流产生的利息 (假设期中流入/流出，计息半个周期)
        BigDecimal netCashFlow = netPremiumCashFlow.subtract(noIacfCashFlow);
        BigDecimal interestFromCashFlow = netCashFlow.multiply(periodInterestRate).multiply(BigDecimal.valueOf(0.5)).setScale(SCALE, ROUNDING_MODE);
        // (C) 总利息 = A + B
        ifieAmt = interestFromOpening.add(interestFromCashFlow).setScale(SCALE, ROUNDING_MODE);
      }

      cumulativeIfieAmt = prevCumulativeIfieAmt.add(ifieAmt).setScale(SCALE, ROUNDING_MODE);
      cumulativeIfieAmtAmortization = cumulativeIfieAmt.multiply(cumulativeProportion).setScale(SCALE, ROUNDING_MODE);

      //当期累积计息摊销
      cumulativeIfieAmtAmortizationThisPeriod = cumulativeIfieAmtAmortization.subtract(prevCumulativeIfieAmtAmortization).setScale(SCALE, ROUNDING_MODE);

      //保险服务收入 = 预收保费(净)摊销 + 累积计息摊销
      //预收毛保费摊销
      premiumAmortization = contract.getPremium().multiply(cumulativeProportion).setScale(SCALE, ROUNDING_MODE);

      //当期预收毛保费摊销
      premiumAmortizationThisPeriod = premiumAmortization.subtract(prevPremiumAmortization).setScale(SCALE, ROUNDING_MODE);

      //预付跟单获取费用摊销
      iacfAmortization = iacf.multiply(cumulativeProportion).setScale(SCALE, ROUNDING_MODE);

      //预收保费(净)摊销
      netPremiumAmortization = premiumAmortization.subtract(iacfAmortization).setScale(SCALE, ROUNDING_MODE);

      //当期预收保费(净)摊销
      netPremiumAmortizationThisPeriod = netPremiumAmortization.subtract(prevNetPremiumAmortization).setScale(SCALE, ROUNDING_MODE);

      //当期跟单获取费用摊销
      iacfAmortizationThisPeriod = premiumAmortizationThisPeriod.subtract(netPremiumAmortizationThisPeriod).setScale(SCALE, ROUNDING_MODE);

      //保险服务收入(分解投资成分前)
      incomeThisPeriodBeforeSplitting = netPremiumAmortizationThisPeriod.add(cumulativeIfieAmtAmortizationThisPeriod).setScale(SCALE, ROUNDING_MODE);

      //投资成分摊销
      baseInvestmentAmortization = baseInvestment.multiply(cumulativeProportion).setScale(SCALE, ROUNDING_MODE);

      //当期投资成分摊销
      baseInvestmentAmortizationThisPeriod = baseInvestmentAmortization.subtract(prevBaseInvestmentAmortization).setScale(SCALE, ROUNDING_MODE);

      //保险服务收入
      incomeThisPeriod = incomeThisPeriodBeforeSplitting.subtract(baseInvestmentAmortizationThisPeriod).setScale(SCALE, ROUNDING_MODE);

      //1.6 赔付与费用_摊销的保险获取现金流（非跟单）
      cumulativeNoIacf = prevCumulativeNoIacf.add(noIacfCashFlow).setScale(SCALE, ROUNDING_MODE);
      cumulativeNoIacfAmortization = cumulativeNoIacf.multiply(cumulativeProportion).setScale(SCALE, ROUNDING_MODE);
      cumulativeNoIacfAmortizationThisPeriod = cumulativeNoIacfAmortization.subtract(prevCumulativeNoIacfAmortization).setScale(SCALE, ROUNDING_MODE);

      //非亏
      closingBalance = openingBalance
        .add(netPremiumCashFlow).subtract(noIacfCashFlow).add(ifieAmt)
        .subtract(incomeThisPeriod).add(cumulativeNoIacfAmortizationThisPeriod).subtract(baseInvestmentAmortizationThisPeriod)
        .setScale(SCALE, ROUNDING_MODE);

      if (!monthIter.plusMonths(1).isAfter(iterEnd)) {
        openingBalance = closingBalance;
        prevCumulativeIfieAmt = cumulativeIfieAmt;
        prevCumulativeNoIacf = cumulativeNoIacf;
        prevNetPremiumAmortization = netPremiumAmortization;
        prevCumulativeIfieAmtAmortization = cumulativeIfieAmtAmortization;
        prevBaseInvestmentAmortization = baseInvestmentAmortization;
        prevCumulativeNoIacfAmortization = cumulativeNoIacfAmortization;

        prevPremiumAmortization = premiumAmortization;
      }
      isFirstPeriod = false;

      //亏损部分
      //合同参与计量的总月数
      //需要参与亏损折现的剩余月份数
      int n = totalMonths - monthCount;

      // 计算未来服务量比例
      BigDecimal futureProportion = BigDecimal.ONE.subtract(cumulativeProportion).setScale(SCALE, ROUNDING_MODE).max(BigDecimal.ZERO);
      //a.未满期保费
      futurePremiums = contract.getPremium().multiply(futureProportion).setScale(SCALE, ROUNDING_MODE);

      //b.预期未来现金流现值 = 预期未来维持费用现值,预期未来赔付费用现值
      //b.1预期未来维持费用 = 未满期保费*精算假设维持费用率
      BigDecimal futureMaintenance = futurePremiums.multiply(assumption.getMaintenanceExpenseRatio());
      //b.2预期未来维持费用现值
      pvFutureMaintenance = getPvMaintenance(futureMaintenance, n, currentMonthRateMap);

      BigDecimal indirectFactor = assumption.getIndirectClaimsExpenseRatio().add(BigDecimal.ONE);
      //b.3预期未来赔付费用
      BigDecimal futureLoss = futurePremiums.multiply(assumption.getLossRatio()).multiply(indirectFactor);
      //b.4预期未来赔付费用现值
      pvFutureLoss = getPvLoss(futureLoss, n, currentMonthRateMap, contract.getClassCode(), discountFactor);

      //c.风险调整
      riskAdjustment = pvFutureMaintenance.add(pvFutureLoss).multiply(assumption.getRa()).setScale(SCALE, ROUNDING_MODE);

      //d.预期未来现金流 = 预期未来维持费用现值 + 预期未来赔付费用现值 + 风险调整
      futureCashFlow = pvFutureLoss.add(pvFutureMaintenance).add(riskAdjustment).setScale(SCALE, ROUNDING_MODE);

      BigDecimal netFutureCashFlow = futureCashFlow
        .subtract(closingBalance)
        .setScale(SCALE, ROUNDING_MODE);

      //亏损部分
      if (contract.getPremium().compareTo(BigDecimal.ZERO) == -1) {
        lossComponent = netFutureCashFlow.compareTo(BigDecimal.ZERO) > 0 ? BigDecimal.ZERO : netFutureCashFlow;
      } else {
        lossComponent = netFutureCashFlow.compareTo(BigDecimal.ZERO) > 0 ? netFutureCashFlow : BigDecimal.ZERO;
      }

      //未到期责任负债
      lrcDebt = closingBalance.add(lossComponent).setScale(SCALE, ROUNDING_MODE);
    }

    //返回评估时点的明细结果
    //Date转string格式入库 jdbcTemplate 处理 date数据不太行 效率影响很大
    String confirmDateStr = (contract.getConfirmDate() == null) ? null : DateFormatUtils.format(contract.getConfirmDate(), YYYYMMDD);
    String piStartDateStr = (contract.getPiStartDate() == null) ? null : DateFormatUtils.format(contract.getPiStartDate(), YYYYMMDD);
    String PiEndDateStr = (contract.getPiEndDate() == null) ? null : DateFormatUtils.format(contract.getPiEndDate(), YYYYMMDD);
    String modifyDateStr = (contract.getModifyDate() == null) ? null : DateFormatUtils.format(contract.getModifyDate(), YYYYMMDD);
    String modifyStartDateStr = (contract.getModifyStartDate() == null) ? null : DateFormatUtils.format(contract.getModifyStartDate(), YYYYMMDD);
    String modifyEndDateStr = (contract.getModifyEndDate() == null) ? null : DateFormatUtils.format(contract.getModifyEndDate(), YYYYMMDD);

    IntMeasureCxUnexpiredRein intMeasureCxUnexpiredRein = new IntMeasureCxUnexpiredRein();
    intMeasureCxUnexpiredRein.setSourceId(contract.getId());
    intMeasureCxUnexpiredRein.setContractFlag(contract.getContractFlag());
    intMeasureCxUnexpiredRein.setContractType(contract.getContractType());
    intMeasureCxUnexpiredRein.setEnquiryType(contract.getEnquiryType());
    intMeasureCxUnexpiredRein.setContractId(contract.getContractId());
    intMeasureCxUnexpiredRein.setSectionNo(contract.getSectionNo());
    intMeasureCxUnexpiredRein.setPolicyNo(contract.getPolicyNo());
    intMeasureCxUnexpiredRein.setCertiNo(contract.getCertiNo());
    intMeasureCxUnexpiredRein.setClassCode(contract.getClassCode());
    intMeasureCxUnexpiredRein.setRiskCode(contract.getRiskCode());
    intMeasureCxUnexpiredRein.setComCode(contract.getComCode());
    intMeasureCxUnexpiredRein.setCarKindCode(contract.getCarKindCode());
    intMeasureCxUnexpiredRein.setUseNatureCode(contract.getUseNatureCode());
    intMeasureCxUnexpiredRein.setConfirmDate(confirmDateStr);
    intMeasureCxUnexpiredRein.setPiStartDate(piStartDateStr);
    intMeasureCxUnexpiredRein.setPiEndDate(PiEndDateStr);
    intMeasureCxUnexpiredRein.setModifyDate(modifyDateStr);
    intMeasureCxUnexpiredRein.setModifyStartDate(modifyStartDateStr);
    intMeasureCxUnexpiredRein.setModifyEndDate(modifyEndDateStr);
    intMeasureCxUnexpiredRein.setPremium(contract.getPremium());
    intMeasureCxUnexpiredRein.setCurrency(contract.getCurrency());
    //分入手续费经纪费 跟单获取费用 使用精算假设 又不用精算假设了
    intMeasureCxUnexpiredRein.setCommission(contract.getCommission());
    intMeasureCxUnexpiredRein.setBrokerage(contract.getBrokerage());
    intMeasureCxUnexpiredRein.setInvestProp(contract.getInvestProp());
    intMeasureCxUnexpiredRein.setUnitId(contract.getUnitId());
    intMeasureCxUnexpiredRein.setMinUnitId(contract.getMinUnitId());
    intMeasureCxUnexpiredRein.setPortfolioId(contract.getPortfolioId());
    intMeasureCxUnexpiredRein.setGroupId(contract.getGroupId());
    intMeasureCxUnexpiredRein.setValMonth(contract.getValMonth());
    intMeasureCxUnexpiredRein.setValMethod(contract.getValMethod());
    intMeasureCxUnexpiredRein.setStartDate(contract.getStartDate());
    intMeasureCxUnexpiredRein.setEndDate(contract.getEndDate());
    intMeasureCxUnexpiredRein.setIniConfirm(contract.getIniConfirm());

    //计量结果
    intMeasureCxUnexpiredRein.setOpeningBalance(openingBalance);
    intMeasureCxUnexpiredRein.setNetPremium(netPremium);
    intMeasureCxUnexpiredRein.setBaseInvestment(baseInvestment);
    intMeasureCxUnexpiredRein.setIacf(iacf);
    intMeasureCxUnexpiredRein.setPremiumCashFlow(premiumCashFlow);
    intMeasureCxUnexpiredRein.setNetPremiumCashFlow(netPremiumCashFlow);
    intMeasureCxUnexpiredRein.setIacfCashFlow(iacfCashFlow);
    intMeasureCxUnexpiredRein.setNoIacfCashFlow(noIacfCashFlow);
    intMeasureCxUnexpiredRein.setIfieAmt(ifieAmt);
    intMeasureCxUnexpiredRein.setCumulativeIfieAmt(cumulativeIfieAmt);
    intMeasureCxUnexpiredRein.setCumulativeNoIacf(cumulativeNoIacf);
    intMeasureCxUnexpiredRein.setCumulativeDays(BigDecimal.valueOf(cumulativeDays));
    intMeasureCxUnexpiredRein.setCumulativeProportion(cumulativeProportion);
    intMeasureCxUnexpiredRein.setPremiumAmortization(premiumAmortization);
    intMeasureCxUnexpiredRein.setIacfAmortization(iacfAmortization);
    intMeasureCxUnexpiredRein.setNetPremiumAmortization(netPremiumAmortization);
    intMeasureCxUnexpiredRein.setCumulativeIfieAmtAmortization(cumulativeIfieAmtAmortization);
    intMeasureCxUnexpiredRein.setIncomeThisPeriodBeforeSplitting(incomeThisPeriodBeforeSplitting);
    intMeasureCxUnexpiredRein.setBaseInvestmentAmortization(baseInvestmentAmortization);
    intMeasureCxUnexpiredRein.setBaseInvestmentAmortizationThisPeriod(baseInvestmentAmortizationThisPeriod);
    intMeasureCxUnexpiredRein.setIncomeThisPeriod(incomeThisPeriod);
    intMeasureCxUnexpiredRein.setCumulativeNoIacfAmortization(cumulativeNoIacfAmortization);
    intMeasureCxUnexpiredRein.setCumulativeNoIacfAmortizationThisPeriod(cumulativeNoIacfAmortizationThisPeriod);
    intMeasureCxUnexpiredRein.setClosingBalance(closingBalance);
    intMeasureCxUnexpiredRein.setFuturePremiums(futurePremiums);
    intMeasureCxUnexpiredRein.setPvFutureMaintenance(pvFutureMaintenance);
    intMeasureCxUnexpiredRein.setPvFutureLoss(pvFutureLoss);
    intMeasureCxUnexpiredRein.setRiskAdjustment(riskAdjustment);
    intMeasureCxUnexpiredRein.setFutureCashFlow(futureCashFlow);
    intMeasureCxUnexpiredRein.setLossComponent(lossComponent);
    intMeasureCxUnexpiredRein.setLrcDebt(lrcDebt);
    //intMeasureCxUnexpiredRein.setMonthCount(monthCount);
    intMeasureCxUnexpiredRein.setNetPremiumAmortizationThisPeriod(netPremiumAmortizationThisPeriod);
    intMeasureCxUnexpiredRein.setCumulativeIfieAmtAmortizationThisPeriod(cumulativeIfieAmtAmortizationThisPeriod);

    intMeasureCxUnexpiredRein.setPremiumAmortizationThisPeriod(premiumAmortizationThisPeriod);
    intMeasureCxUnexpiredRein.setIacfAmortizationThisPeriod(iacfAmortizationThisPeriod);

    return intMeasureCxUnexpiredRein;
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
   * @param amt            预期未来赔付费用
   * @param classCode      险类代码
   * @param n              均摊次数
   * @param monthsRateMap  当前评估时点对应的月度远期利率
   * @param discountFactor 赔付模式数据
   * @return
   */

  private BigDecimal getPvLoss(BigDecimal amt, int n, Map<Integer, BigDecimal> monthsRateMap, String classCode, Map<String, BigDecimal[]> discountFactor) {
    if (n <= 0 || amt.equals(BigDecimal.ZERO)) {
      return BigDecimal.ZERO;
    }
    BigDecimal[] claimFactorArr = discountFactor.get(classCode);
    BigDecimal[] claimFactor = Arrays.copyOf(claimFactorArr, claimFactorArr.length);
    BigDecimal avgAmt = amt.divide(new BigDecimal(n), SCALE, ROUNDING_MODE);
    for (int i = 0; i < claimFactor.length; i++) {
      claimFactor[i] = avgAmt.multiply(claimFactor[i]).setScale(SCALE, ROUNDING_MODE);
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
      prefix[i + 1] = prefix[i].add(claimFactor[i]).setScale(SCALE, ROUNDING_MODE);
    }

    // 计算每个位置的累加和
    for (int j = 0; j < resultLength; j++) {
      int start = Math.max(0, j - k); // 起始索引
      int end = Math.min(j, claimFactor.length - 1);   // 结束索引
      result[j] = prefix[end + 1].subtract(prefix[start]).setScale(SCALE, ROUNDING_MODE);
    }
    //折现到当前评估时点
    BigDecimal product = BigDecimal.ONE;
    BigDecimal pvLoss = BigDecimal.ZERO;
    for (int i = 0; i < result.length; i++) {
      int month = (i + 1) > MAX_MONTH_COUNT ? MAX_MONTH_COUNT : (i + 1);
      product = product.multiply(monthsRateMap.get(month).add(BigDecimal.ONE)).setScale(SCALE, ROUNDING_MODE);
      result[i] = result[i].divide(product, SCALE, ROUNDING_MODE);
      pvLoss = pvLoss.add(result[i]).setScale(SCALE, ROUNDING_MODE);
    }
    return pvLoss;
  }

  /**
   * 未来维持费用折现
   *
   * @param amt           预期未来维持费用
   * @param n             均摊次数
   * @param monthsRateMap 评估时点的月度远期利率
   * @return
   */
  private BigDecimal getPvMaintenance(BigDecimal amt, int n, Map<Integer, BigDecimal> monthsRateMap) {
    if (n <= 0 || amt.equals(BigDecimal.ZERO)) {
      return BigDecimal.ZERO;
    }
    BigDecimal arr[] = new BigDecimal[n];
    for (int i = 0; i < n; i++) {
      arr[i] = amt.divide(new BigDecimal(n), SCALE, ROUNDING_MODE);
    }
    //折现到当前评估时点
    BigDecimal product = BigDecimal.ONE;
    BigDecimal pvMaintenance = BigDecimal.ZERO;
    for (int i = 0; i < arr.length; i++) {
      int month = (i + 1) > MAX_MONTH_COUNT ? MAX_MONTH_COUNT : (i + 1);
      product = product.multiply(monthsRateMap.get(month).add(BigDecimal.ONE)).setScale(SCALE, ROUNDING_MODE);
      arr[i] = arr[i].divide(product, SCALE, ROUNDING_MODE);
      pvMaintenance = pvMaintenance.add(arr[i]).setScale(SCALE, ROUNDING_MODE);
    }
    return pvMaintenance;
  }

  /**
   * 计算分摊到单的亏损
   *
   * @param allResults 所有计算结果
   */
  private void calculateLossComponentAllocation(List<IntMeasureCxUnexpiredRein> allResults) {
    if (CollectionUtils.isEmpty(allResults)) {
      return;
    }

    // 按groupId分组
    Map<String, List<IntMeasureCxUnexpiredRein>> groupedResults = allResults.stream()
      .collect(Collectors.groupingBy(
        item -> item.getGroupId() != null ? item.getGroupId() : "NULL_GROUP",
        Collectors.toList()
      ));

    // 对每一组数据进行计算
    groupedResults.forEach((groupId, groupList) -> {
      // 计算合并到组的亏损：max(0, sum(futureCashFlow) - sum(closingBalance))
      BigDecimal sumFutureCashFlow = groupList.stream()
        .map(item -> item.getFutureCashFlow() != null ? item.getFutureCashFlow() : BigDecimal.ZERO)
        .reduce(BigDecimal.ZERO, BigDecimal::add);

      BigDecimal sumClosingBalance = groupList.stream()
        .map(item -> item.getClosingBalance() != null ? item.getClosingBalance() : BigDecimal.ZERO)
        .reduce(BigDecimal.ZERO, BigDecimal::add);

      BigDecimal groupLoss = sumFutureCashFlow.subtract(sumClosingBalance).max(BigDecimal.ZERO);

      // 计算lossComponent的总和
      BigDecimal sumLossComponent = groupList.stream()
        .map(item -> item.getLossComponent() != null ? item.getLossComponent() : BigDecimal.ZERO)
        .reduce(BigDecimal.ZERO, BigDecimal::add);

      // 为每行数据计算分摊到单的亏损
      if (sumLossComponent.compareTo(BigDecimal.ZERO) != 0) {
        // 有lossComponent时，按比例分摊
        groupList.forEach(item -> {
          BigDecimal itemLossComponent = item.getLossComponent() != null ? item.getLossComponent() : BigDecimal.ZERO;
          BigDecimal allocationRatio = itemLossComponent.divide(sumLossComponent, SCALE, ROUNDING_MODE);
          BigDecimal allocation = groupLoss.multiply(allocationRatio).setScale(SCALE, ROUNDING_MODE);
          item.setLossComponentAllocation(allocation);
        });
      } else {
        groupList.forEach(item -> item.setLossComponentAllocation(BigDecimal.ZERO));
      }
    });
  }

  /**
   * 使用JdbcTemplate进行批量插入
   *
   * @param allResults 待插入的数据列表
   */
  private void insertBatchWithJdbcTemplate(List<IntMeasureCxUnexpiredRein> allResults) {
    if (CollectionUtils.isEmpty(allResults)) {
      return;
    }

    List<String> columnNames = Arrays.asList(
      "id", "source_id", "contract_flag", "contract_type", "enquiry_type", "contract_id", "section_no",
      "policy_no", "certi_no", "class_code", "risk_code", "com_code", "car_kind_code",
      "use_nature_code", "confirm_date", "pi_start_date", "pi_end_date", "modify_date", "modify_start_date",
      "modify_end_date", "premium", "currency", "commission", "brokerage",
      "invest_prop", "unit_id", "min_unit_id", "portfolio_id", "group_id", "val_month", "val_method",
      "start_date", "end_date", "ini_confirm", "rein_type", "share_rate",
      "under_write_date", "certi_write_date", "valid_date", "rein_system_code", "opening_balance", "net_premium",
      "base_investment", "iacf", "premium_cash_flow", "net_premium_cash_flow", "iacf_cash_flow",
      "no_iacf_cash_flow", "ifie_amt", "cumulative_ifie_amt", "cumulative_no_iacf", "cumulative_days",
      "cumulative_proportion", "premium_amortization", "iacf_amortization", "net_premium_amortization",
      "cumulative_ifie_amt_amortization", "income_this_period_before_splitting", "base_investment_amortization",
      "base_investment_amortization_this_period", "income_this_period", "cumulative_no_iacf_amortization",
      "cumulative_no_iacf_amortization_this_period", "closing_balance", "future_premiums", "pv_future_maintenance",
      "pv_future_loss", "risk_adjustment", "future_cash_flow", "loss_component", "lrc_debt", "loss_component_allocation",
      "is_status", "remark", "create_time", "update_time", "create_by", "update_by", "net_premium_amortization_this_period",
      "cumulative_ifie_amt_amortization_this_period", "premium_amortization_this_period", "iacf_amortization_this_period"
    );


    // 2. 动态构建 SQL
    String columnsPart = columnNames.stream()
      .map(name -> "\"" + name + "\"")
      .collect(Collectors.joining(", "));

    String placeholdersPart = columnNames.stream()
      .map(name -> "?")
      .collect(Collectors.joining(", "));

    String sql = String.format("INSERT INTO measure_platform.int_measure_cx_unexpired_rein (%s) VALUES (%s)", columnsPart, placeholdersPart);
    jdbcTemplate.batchUpdate(sql, new BatchPreparedStatementSetter() {
      @Override
      public void setValues(PreparedStatement ps, int i) throws SQLException {
        IntMeasureCxUnexpiredRein item = allResults.get(i);
        int index = 1;

        ps.setLong(index++, IdWorker.getId());
        ps.setString(index++, item.getSourceId());
        ps.setString(index++, item.getContractFlag());
        ps.setString(index++, item.getContractType());
        ps.setString(index++, item.getEnquiryType());
        ps.setString(index++, item.getContractId());
        ps.setString(index++, item.getSectionNo());
        ps.setString(index++, item.getPolicyNo());
        ps.setString(index++, item.getCertiNo());
        ps.setString(index++, item.getClassCode());
        ps.setString(index++, item.getRiskCode());
        ps.setString(index++, item.getComCode());
        ps.setString(index++, item.getCarKindCode());
        ps.setString(index++, item.getUseNatureCode());
        ps.setString(index++, item.getConfirmDate());
        ps.setString(index++, item.getPiStartDate());
        ps.setString(index++, item.getPiEndDate());
        ps.setString(index++, item.getModifyDate());
        ps.setString(index++, item.getModifyStartDate());
        ps.setString(index++, item.getModifyEndDate());
        ps.setBigDecimal(index++, item.getPremium());
        ps.setString(index++, item.getCurrency());
        ps.setBigDecimal(index++, item.getCommission());
        ps.setBigDecimal(index++, item.getBrokerage());
        ps.setBigDecimal(index++, item.getInvestProp());
        ps.setString(index++, item.getUnitId());
        ps.setString(index++, item.getMinUnitId());
        ps.setString(index++, item.getPortfolioId());
        ps.setString(index++, item.getGroupId());
        ps.setString(index++, item.getValMonth());
        ps.setString(index++, item.getValMethod());
        ps.setString(index++, item.getStartDate());
        ps.setString(index++, item.getEndDate());
        ps.setString(index++, item.getIniConfirm());
        ps.setString(index++, item.getReinType());
        ps.setBigDecimal(index++, item.getShareRate());
        ps.setString(index++, item.getUnderWriteDate());
        ps.setString(index++, item.getCertiWriteDate());
        ps.setString(index++, item.getValidDate());
        ps.setString(index++, item.getReinSystemCode());
        ps.setBigDecimal(index++, item.getOpeningBalance());
        ps.setBigDecimal(index++, item.getNetPremium());
        ps.setBigDecimal(index++, item.getBaseInvestment());
        ps.setBigDecimal(index++, item.getIacf());
        ps.setBigDecimal(index++, item.getPremiumCashFlow());
        ps.setBigDecimal(index++, item.getNetPremiumCashFlow());
        ps.setBigDecimal(index++, item.getIacfCashFlow());
        ps.setBigDecimal(index++, item.getNoIacfCashFlow());
        ps.setBigDecimal(index++, item.getIfieAmt());
        ps.setBigDecimal(index++, item.getCumulativeIfieAmt());
        ps.setBigDecimal(index++, item.getCumulativeNoIacf());
        ps.setBigDecimal(index++, item.getCumulativeDays());
        ps.setBigDecimal(index++, item.getCumulativeProportion());
        ps.setBigDecimal(index++, item.getPremiumAmortization());
        ps.setBigDecimal(index++, item.getIacfAmortization());
        ps.setBigDecimal(index++, item.getNetPremiumAmortization());
        ps.setBigDecimal(index++, item.getCumulativeIfieAmtAmortization());
        ps.setBigDecimal(index++, item.getIncomeThisPeriodBeforeSplitting());
        ps.setBigDecimal(index++, item.getBaseInvestmentAmortization());
        ps.setBigDecimal(index++, item.getBaseInvestmentAmortizationThisPeriod());
        ps.setBigDecimal(index++, item.getIncomeThisPeriod());
        ps.setBigDecimal(index++, item.getCumulativeNoIacfAmortization());
        ps.setBigDecimal(index++, item.getCumulativeNoIacfAmortizationThisPeriod());
        ps.setBigDecimal(index++, item.getClosingBalance());
        ps.setBigDecimal(index++, item.getFuturePremiums());
        ps.setBigDecimal(index++, item.getPvFutureMaintenance());
        ps.setBigDecimal(index++, item.getPvFutureLoss());
        ps.setBigDecimal(index++, item.getRiskAdjustment());
        ps.setBigDecimal(index++, item.getFutureCashFlow());
        ps.setBigDecimal(index++, item.getLossComponent());
        ps.setBigDecimal(index++, item.getLrcDebt());
        ps.setBigDecimal(index++, item.getLossComponentAllocation());
        ps.setString(index++, item.getIsStatus());
        ps.setString(index++, item.getRemark());
        ps.setTimestamp(index++, new Timestamp(System.currentTimeMillis()));
        ps.setTimestamp(index++, new Timestamp(System.currentTimeMillis()));
        ps.setString(index++, item.getCreateBy());
        ps.setString(index++, item.getUpdateBy());
        //ps.setInt(index++, item.getMonthCount());
        ps.setBigDecimal(index++, item.getNetPremiumAmortizationThisPeriod());
        ps.setBigDecimal(index++, item.getCumulativeIfieAmtAmortizationThisPeriod());

        ps.setBigDecimal(index++, item.getPremiumAmortizationThisPeriod());
        ps.setBigDecimal(index++, item.getIacfAmortizationThisPeriod());

      }

      @Override
      public int getBatchSize() {
        return allResults.size();
      }
    });
  }

//  /**
//   * 再保分入分出LRC分录月结(再保分入未到期分录)
//   *
//   * @param valMonth 评估月
//   * @return r
//   */
//  @Override
//  @Transactional(rollbackFor = Exception.class)
//  public R<?> setMeasureLrcLeReinByMonthResult(String valMonth) {
//    log.info("再保分入分出LRC分录月结开始, 评估月份: {}", valMonth);
//    long startTime = System.currentTimeMillis();
//    //插入再保分入 未到期 分录数据
//    accountingScenarioAccountMapper.insertMeasureLrcLeReinInByMonthResult(valMonth);
//
//    //插入再保分出 未到期 直保转分出 分录数据
//    accountingScenarioAccountMapper.insertMeasureLrcLeReinOutReinType1ByMonthResult(valMonth);
//
//    //插入再保分出 未到期 分入转分出 分录数据
//    accountingScenarioAccountMapper.insertMeasureLrcLeReinOutReinType2ByMonthResult(valMonth);
//    log.info("再保分入分出LRC分录月结完成，总耗时: {} 秒", (System.currentTimeMillis() - startTime) / 1000.0);
//    return R.ok();
//  }

}
