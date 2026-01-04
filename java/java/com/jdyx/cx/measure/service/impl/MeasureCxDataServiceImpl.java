package com.jdyx.cx.measure.service.impl;

import cn.hutool.core.bean.BeanUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.jdyx.cx.measure.service.MeasureCxDataService;
import com.jdyx.measure.api.measure.domain.*;
import com.jdyx.measure.api.measure.mapper.*;
import com.jdyx.measureprepare.api.domain.IntTPpJlContractNew;
import com.jdyx.measureprepare.api.domain.IntTPpJlIacfFolNew;
import com.jdyx.measureprepare.api.domain.IntTPpJlIacfUnfolNew;
import com.jdyx.measureprepare.api.mapper.IntTPpJlContractNewMapper;
import com.jdyx.measureprepare.api.mapper.IntTPpJlIacfFolNewMapper;
import com.jdyx.measureprepare.api.mapper.IntTPpJlIacfUnfolNewMapper;
import com.kevin.common.core.domain.R;
import com.kevin.common.utils.DateUtils;
import com.kevin.common.utils.reflect.ReflectUtils;
import com.kevin.common.utils.uuid.IdUtils;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.BatchPreparedStatementSetter;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.util.CollectionUtils;

import javax.annotation.Resource;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Collectors;

/**
 * LRC计量源数据加工
 *
 * @author 陈佳能
 * 日期：2025/10/12 17:50
 */
@Slf4j
@RequiredArgsConstructor
@Service
public class MeasureCxDataServiceImpl implements MeasureCxDataService {
  @Resource
  private PiShouldRecPayOffMonMapper piShouldRecPayOffMonMapper;
  @Resource
  private IntTPpJlIacfFolNewMapper tPpJlIacfFolNewMapper;
  @Resource
  private IntTPpJlContractNewMapper intTPpJlContractNewMapper;
  @Resource
  private IntTPpJlIacfUnfolNewMapper tPpJlIacfUnfolNewMapper;

  @Resource
  private MeasureCfBasicDataNewMapper measureCfBasicDataNewMapper;

  @Resource
  private MeasureCfBasicDateLapseMapper measureCfBasicDateLapseMapper;



  @Autowired
  private JdbcTemplate jdbcTemplate;
  // 常量定义
  private static final int BATCH_SIZE = 100000;
  private final Map<String, BigDecimal> payOffMonthCache = new ConcurrentHashMap<>();
  private final Map<String, Map<String,BigDecimal>> tPpJlIacfFolCache = new ConcurrentHashMap<>();
  private final Map<String, BigDecimal>  tPpJlIacfUnfolCache = new ConcurrentHashMap<>();


  @Override
  public R<?> setUnexpiredMeasureData(String valMethod, String valMonth) {
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
  private void preloadCacheData(String valMethod,String valMonth){
    //1.应收应付核销表
//    piShouldRecPayOffMonMapper.setPiShouldRecPayOffMonUnitId(DateUtils.endMonth(valMonth, DateUtils.YYYY_MM_DD));
    LambdaQueryWrapper<PiShouldRecPayOffMon>payOffMonQuery = Wrappers.lambdaQuery();
    payOffMonQuery.select(PiShouldRecPayOffMon::getPolicyNo, PiShouldRecPayOffMon::getCertiNo, PiShouldRecPayOffMon::getCancelDate, PiShouldRecPayOffMon::getCancelAmount)
      .eq(PiShouldRecPayOffMon::getStatDate, DateUtils.endMonth(DateUtils.parseDate(valMonth)))
      .eq(PiShouldRecPayOffMon::getBizType, "1");
    List<PiShouldRecPayOffMon> payOffMons = piShouldRecPayOffMonMapper.selectList(payOffMonQuery);
    Map<String, BigDecimal> payOffMonthMap = payOffMons.stream()
      .collect(Collectors.groupingBy(
        payOffMon -> payOffMon.getPolicyNo()+"_" + Objects.toString(payOffMon.getCertiNo(), "NA"),
        Collectors.reducing(
          // 求和的初始值，如果某个分组没有元素，则结果为 BigDecimal.ZERO
          BigDecimal.ZERO,
          PiShouldRecPayOffMon::getCancelAmount,
          BigDecimal::add
        )
      ));

    //2.获取费用（跟单）
    LambdaQueryWrapper<IntTPpJlIacfFolNew> tPpJlIacfFolNewQuery = Wrappers.lambdaQuery();
    tPpJlIacfFolNewQuery.select(IntTPpJlIacfFolNew::getIacfFolCny,IntTPpJlIacfFolNew::getIacfFolTax,IntTPpJlIacfFolNew::getUnitId)
      .eq(IntTPpJlIacfFolNew::getValMonth,valMonth);
    List<IntTPpJlIacfFolNew> tPpJlIacfFolNewList = tPpJlIacfFolNewMapper.selectList(tPpJlIacfFolNewQuery);
    Map<String, Map<String, BigDecimal>> tPpJlIacfFolMap = tPpJlIacfFolNewList.stream().collect(Collectors.groupingBy(e -> e.getUnitId(),
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

    //3.获取费用（非跟单）
    LambdaQueryWrapper<IntTPpJlIacfUnfolNew> tPpJlIacfUnfolNewQuery = Wrappers.lambdaQuery();
    tPpJlIacfUnfolNewQuery.select(IntTPpJlIacfUnfolNew::getIacfAmount,IntTPpJlIacfUnfolNew::getUnitId)
      .eq(IntTPpJlIacfUnfolNew::getValMonth,valMonth);
    List<IntTPpJlIacfUnfolNew> tPpJlIacfUnfolList = tPpJlIacfUnfolNewMapper.selectList(tPpJlIacfUnfolNewQuery);
    //4.获取费用（非跟单上月）
    LambdaQueryWrapper<IntTPpJlIacfUnfolNew> tPpJlIacfUnfolNewLastQuery = Wrappers.lambdaQuery();
    tPpJlIacfUnfolNewLastQuery.select(IntTPpJlIacfUnfolNew::getIacfAmount,IntTPpJlIacfUnfolNew::getUnitId)
      .eq(IntTPpJlIacfUnfolNew::getValMonth,DateUtils.lastEndMonth(valMonth, DateUtils.YYYYMM));
    List<IntTPpJlIacfUnfolNew> tPpJlIacfUnfolLastList = tPpJlIacfUnfolNewMapper.selectList(tPpJlIacfUnfolNewLastQuery);
    Map<String, BigDecimal> tPpJlIacfUnfolLastMap = tPpJlIacfUnfolLastList.stream()
      .collect(Collectors.groupingBy(
        IntTPpJlIacfUnfolNew::getUnitId,
        Collectors.reducing(
          // 求和的初始值，如果某个分组没有元素，则结果为 BigDecimal.ZERO
          BigDecimal.ZERO,
          IntTPpJlIacfUnfolNew::getIacfAmount,
          BigDecimal::add
        )
      ));
    //5.计算费用（非跟单）差值,因为费用分摊是YTD年累计，所以当期累计值-上期累计值=当期新增值
    Map<String, BigDecimal> differenceMap = tPpJlIacfUnfolList.stream()
      .collect(Collectors.toMap(
        IntTPpJlIacfUnfolNew::getUnitId,
        current -> {
          // 从上期 Map 中查找相同 unitId 的金额
          BigDecimal lastAmount = tPpJlIacfUnfolLastMap.get(current.getUnitId());
          // 如果找到了上期金额，则计算差值；否则，差值就是当期金额
          if (lastAmount != null) {
            return current.getIacfAmount().subtract(lastAmount);
          } else {
            return current.getIacfAmount();
          }
        },
        (diff1, diff2) -> diff1
      ));

    //放入缓存
    payOffMonthCache.putAll(payOffMonthMap);
    tPpJlIacfFolCache.putAll(tPpJlIacfFolMap);
    tPpJlIacfUnfolCache.putAll(differenceMap);

    //生成失效保单数据
    measureCfBasicDateLapseMapper.delete(
      new LambdaQueryWrapper<MeasureCfBasicDateLapse>().eq(MeasureCfBasicDateLapse::getValMonth, valMonth));

    if (valMonth.substring(4, 6).equals("01")) {
      measureCfBasicDateLapseMapper.createExpiredData(valMonth, valMethod);
    } else {
      measureCfBasicDateLapseMapper.createExpiredMonthData(valMonth, valMethod,DateUtils.lastEndMonth(valMonth, DateUtils.YYYYMM));
    }

    log.info("预加载完成 - 实收保费: {} 条, 获取费用_跟单: {}条，获取费用_非跟单:{}条",
      payOffMonthMap.size(), tPpJlIacfFolMap.size(),differenceMap.size());
  }

  /**
   * 使用游标分页+并行处理数据
   */
  private void processDataWithCursorPagination(String valMethod, String valMonth)
    throws InterruptedException {
    //清空当期数据
    measureCfBasicDataNewMapper.delete(new LambdaQueryWrapper<MeasureCfBasicDataNew>()
      .eq(MeasureCfBasicDataNew::getValMonth, valMonth));

    long maxId = 0; // 游标
    int x = 1;

    while (true) {
      Long startTime = System.currentTimeMillis();
      // 使用游标方式分页查询
      LambdaQueryWrapper<IntTPpJlContractNew> lqw = new LambdaQueryWrapper<>();
      lqw.eq(IntTPpJlContractNew::getValMonth, valMonth)
        .gt(IntTPpJlContractNew::getId, maxId)
        .orderByAsc(IntTPpJlContractNew::getId)
        .last("LIMIT " + BATCH_SIZE);
      List<IntTPpJlContractNew> records = intTPpJlContractNewMapper.selectList(lqw);
      if (records.isEmpty()) {
        break;
      }
      log.debug("页数:{},耗时: {}ms", x++, System.currentTimeMillis() - startTime);
      //
      processBatch(records, valMonth,valMethod);
      // 更新游标
      maxId = records.get(records.size() - 1).getId();
    }
  }

  /**
   * 异步处理批次数据
   */
  private void processBatch(List<IntTPpJlContractNew> batchData, String valMonth,String valMethod) {

    // 将参数声明为final，避免lambda表达式中的变量引用问题
    final String finalValMonth = valMonth;
    final String finalValMethod = valMethod;
    final List<IntTPpJlContractNew> finalBatchData = batchData;

    try {
      long startTime = System.currentTimeMillis();
      List<MeasureCfBasicDataNew> batchResults = finalBatchData.stream()
        .map(contract -> calculateLrcWithMonthlyRolling(contract, finalValMonth,finalValMethod))
        .collect(Collectors.toList());
      long startTime2 = System.currentTimeMillis();
      insertBatchWithJdbcTemplate(batchResults);

      log.debug("批次处理完成，数据插入耗时: {}, 批次整体耗时: {} ms",
        System.currentTimeMillis() - startTime2, System.currentTimeMillis() - startTime);
    } catch (Exception e) {
      log.error("批次处理异常", e);
    }
  }



  private void insertBatchWithJdbcTemplate(List<MeasureCfBasicDataNew> allResults) {
    if (CollectionUtils.isEmpty(allResults)) {
      return;
    }
    // 1. 定义所有要插入的字段名
    List<String> columnNames = Arrays.asList(
      "id", "val_month", "policy_no", "certi_no", "risk_code", "com_code", "business_nature", "car_kind_code", "use_nature_code",
      "unit_id", "start_date", "end_date", "under_write_date", "ini_confirm", "term", "acc_service", "portfolio_id", "group_id",
      "val_method", "class_code", "currency", "premium_cny", "iacf_fol_cny", "iacf_unfol_cny", "iacf_amount", "premium_received",
      "premium_impairment", "service_proportion", "create_by", "update_by", "create_time", "update_time"
    );
    // 2. 动态构建 SQL
    String columnsPart = columnNames.stream()
      .map(name -> "\"" + name + "\"")
      .collect(Collectors.joining(", "));

    String placeholdersPart = columnNames.stream()
      .map(name -> "?")
      .collect(Collectors.joining(", "));

    String sql = String.format("INSERT INTO measure_platform.measure_cf_basic_data_new (%s) VALUES (%s)", columnsPart, placeholdersPart);

    jdbcTemplate.batchUpdate(sql, new BatchPreparedStatementSetter() {
      @Override
      public void setValues(PreparedStatement ps, int i) throws SQLException {
        MeasureCfBasicDataNew item = allResults.get(i);
        int index = 1;
        ps.setLong(index++, item.getId());
        ps.setString(index++, item.getValMonth());
        ps.setString(index++, item.getPolicyNo());
        ps.setString(index++, item.getCertiNo());
        ps.setString(index++, item.getRiskCode());
        ps.setString(index++, item.getComCode());
        ps.setString(index++, item.getBusinessNature());
        ps.setString(index++, item.getCarKindCode());
        ps.setString(index++, item.getUseNatureCode());
        ps.setString(index++, item.getUnitId());
        ps.setString(index++, item.getStartDate());
        ps.setString(index++, item.getEndDate());
        ps.setString(index++, item.getUnderWriteDate());
        ps.setString(index++, item.getIniConfirm());
        ps.setInt(index++, item.getTerm());
        ps.setLong(index++, item.getAccService());
        ps.setString(index++, item.getPortfolioId());
        ps.setString(index++, item.getGroupId());
        ps.setString(index++, item.getValMethod());
        ps.setString(index++, item.getClassCode());
        ps.setString(index++, item.getCurrency());
        ps.setBigDecimal(index++, item.getPremiumCny());
        ps.setBigDecimal(index++, item.getIacfFolCny());
        ps.setBigDecimal(index++, item.getIacfUnfolCny());
        ps.setBigDecimal(index++, item.getIacfAmount());
        ps.setBigDecimal(index++, item.getPremiumReceived());
        ps.setBigDecimal(index++, item.getPremiumImpairment());
        ps.setBigDecimal(index++, item.getServiceProportion());
        ps.setString(index++, "system");
        ps.setString(index++, "system");
        ps.setTimestamp(index++, new Timestamp(System.currentTimeMillis()));
        ps.setTimestamp(index++, new Timestamp(System.currentTimeMillis()));
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
  private MeasureCfBasicDataNew calculateLrcWithMonthlyRolling(IntTPpJlContractNew contract, String valMonth ,String valMethod) {
//    try {
      MeasureCfBasicDataNew measureCfBasicDataNew = new MeasureCfBasicDataNew();
      measureCfBasicDataNew.setId(IdUtils.getSnowFlakeLongId());
      measureCfBasicDataNew.setValMonth(valMonth);
      measureCfBasicDataNew.setValMethod(valMethod);
      measureCfBasicDataNew.setPolicyNo(contract.getPolicyNo());
      measureCfBasicDataNew.setCertiNo(contract.getCertiNo());
      measureCfBasicDataNew.setClassCode(contract.getClassCode());
      measureCfBasicDataNew.setRiskCode(contract.getRiskCode());
      measureCfBasicDataNew.setUnitId(contract.getUnitId());
      measureCfBasicDataNew.setComCode(contract.getComCode());
      measureCfBasicDataNew.setBusinessNature(contract.getBusinessNature());
      measureCfBasicDataNew.setCarKindCode(contract.getCarKindCode());
      measureCfBasicDataNew.setUseNatureCode(contract.getUseNatureCode());
      measureCfBasicDataNew.setStartDate(DateUtils.parseDateToStr(DateUtils.YYYY_MM_DD,contract.getStartDate()));
      measureCfBasicDataNew.setEndDate(DateUtils.parseDateToStr(DateUtils.YYYY_MM_DD,contract.getEndDate()));
      measureCfBasicDataNew.setUnderWriteDate(DateUtils.parseDateToStr(DateUtils.YYYY_MM_DD,contract.getUnderWriteDate()));
      //TODO 暂时用签单日期代替i17初始确认日
      measureCfBasicDataNew.setIniConfirm(DateUtils.parseDateToStr(DateUtils.YYYY_MM_DD,contract.getUnderWriteDate()));
      measureCfBasicDataNew.setGroupId(contract.getGroupId());
      measureCfBasicDataNew.setPortfolioId(contract.getPortfolioId());
      measureCfBasicDataNew.setGroupId(contract.getGroupId());
      measureCfBasicDataNew.setCurrency(contract.getCurrency());
      //保障期限
      measureCfBasicDataNew.setTerm(DateUtils.differentDaysByMillisecond(contract.getStartDate(),contract.getEndDate())+1);
      //累计服务量
      LocalDate valMonthLocal = LocalDate.parse(DateUtils.parseDateToStr(DateUtils.YYYY_MM_DD, DateUtils.endMonth(valMonth)));
      LocalDate endDateLocal = LocalDate.parse(DateUtils.parseDateToStr(DateUtils.YYYY_MM_DD, contract.getEndDate()));
      LocalDate startDateLocal = LocalDate.parse(DateUtils.parseDateToStr(DateUtils.YYYY_MM_DD, contract.getStartDate()));
      LocalDate minDate = valMonthLocal.isBefore(endDateLocal) ? valMonthLocal : endDateLocal;
      // 计算min(评估月末，保险责任止期)与startDate之间的天数差，同时要考虑倒签单的情况，即评估月末在startDate之前的情况
      long accService;
      if (minDate.isBefore(startDateLocal)) {
        accService = 0;
      } else {
        accService = ChronoUnit.DAYS.between(startDateLocal, minDate) + 1;
      }
      BigDecimal serviceProportion = BigDecimal.valueOf(accService).divide(BigDecimal.valueOf(measureCfBasicDataNew.getTerm()), 10, RoundingMode.HALF_UP);
      measureCfBasicDataNew.setAccService(accService);
      measureCfBasicDataNew.setServiceProportion(serviceProportion);

      //获取费用跟单
      Map<String, BigDecimal> tPpJlIacfFolMap = tPpJlIacfFolCache.getOrDefault(contract.getUnitId(),new HashMap<>());
      BigDecimal iacfFolCny = tPpJlIacfFolMap.getOrDefault(ReflectUtils.getFieldName(IntTPpJlIacfFolNew::getIacfFolCny), BigDecimal.ZERO);
      BigDecimal iacfTaxCny = tPpJlIacfFolMap.getOrDefault(ReflectUtils.getFieldName(IntTPpJlIacfFolNew::getIacfFolTax), BigDecimal.ZERO);
      measureCfBasicDataNew.setIacfFolCny(iacfFolCny.add(iacfTaxCny));
      //获取费用非跟单
      measureCfBasicDataNew.setIacfUnfolCny(tPpJlIacfUnfolCache.getOrDefault(contract.getUnitId(),BigDecimal.ZERO));
      //总获取费用=获取费用跟单+获取费用非跟单
      measureCfBasicDataNew.setIacfAmount(measureCfBasicDataNew.getIacfFolCny().add(measureCfBasicDataNew.getIacfUnfolCny()));
      measureCfBasicDataNew.setPremiumCny(contract.getPremiumCny());
      String key=contract.getPolicyNo()+"_"+contract.getCertiNo();
      measureCfBasicDataNew.setPremiumReceived(payOffMonthCache.getOrDefault(key,BigDecimal.ZERO));
      return  measureCfBasicDataNew;
//    }catch (Exception e){
//      log.error("未到期计量计算异常:{},保单数据:{}",e,JSON.toJSONString(contract));
//    }
//    return null;
  }

  /**
   * 清理缓存
   */
  private void clearCache() {
    tPpJlIacfFolCache.clear();
    tPpJlIacfUnfolCache.clear();
    payOffMonthCache.clear();
    log.info("缓存清理完成");
  }
}

