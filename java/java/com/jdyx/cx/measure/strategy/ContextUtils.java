package com.jdyx.cx.measure.strategy;

import com.google.common.collect.Maps;
import com.jdyx.common.enums.EvaluateMethodTypeEnum;
import com.jdyx.cx.measure.strategy.impl.*;
import com.jdyx.measure.api.measure.domain.*;
import com.jdyx.measureprepare.api.domain.TPpJlClmSettled;
import com.jdyx.measureprepare.api.domain.vo.TPpJlActualRecPayPremFeeVo;
import com.kevin.common.utils.spring.SpringUtils;

import java.math.BigDecimal;
import java.text.ParseException;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;

/**
 * Context工具类
 *
 * @author 刘瑞奎.
 * @date 2024/10/21.
 */
public class ContextUtils {

  /**
   * 策略集合
   */
  private static final Map<EvaluateMethodTypeEnum, Class<? extends MeasureCfBasicStrategy>> STRATEGY_CF_BASIC_MAP = Maps.newHashMap();

  //初始化策略集合
  private static final Map<EvaluateMethodTypeEnum, Class<? extends MeasureConfCommonClaimStrategy>> STRATEGY_COMMON_CLAIM_MAP = Maps.newHashMap();
  /**
   * 策略集合
   */
  private static final Map<EvaluateMethodTypeEnum, Class<? extends MeasureCfResultInfoStrategy>> STRATEGY_RESULT_INFO_MAP = Maps.newHashMap();

  //预期现金流策略集合
  private static final Map<EvaluateMethodTypeEnum, Class<? extends MeasureCfBasicExpRstStrategy>> STRATEGY_EXP_MAP = Maps.newHashMap();

  //实际现金流策略集合
  private static final Map<EvaluateMethodTypeEnum, Class<? extends MeasureCfBbaBasicCalcRstStrategy>> STRATEGY_EXP_ACTUAL_MAP = Maps.newHashMap();

  //初始化策略集合
  static {
    STRATEGY_CF_BASIC_MAP.put(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_7, MeasureCfBasicData7.class);
    STRATEGY_CF_BASIC_MAP.put(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_8, MeasureCfBasicData7.class);
    STRATEGY_CF_BASIC_MAP.put(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_9, MeasureCfBasicData9.class);
    STRATEGY_CF_BASIC_MAP.put(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_10, MeasureCfBasicData9.class);
    STRATEGY_CF_BASIC_MAP.put(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_11, MeasureCfBasicData11.class);
    STRATEGY_CF_BASIC_MAP.put(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_12, MeasureCfBasicData12.class);


  }

  //初始化理赔配置集合
  static {
    STRATEGY_COMMON_CLAIM_MAP.put(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_8, MeasureConfCommonClaim8.class);
    STRATEGY_COMMON_CLAIM_MAP.put(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_11, MeasureConfCommonClaim11.class);
    STRATEGY_COMMON_CLAIM_MAP.put(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_10, MeasureConfCommonClaim11.class);
  }

  //初始化策略集合
  static {
    STRATEGY_RESULT_INFO_MAP.put(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_7, MeasureCfResultInfo7.class);
    STRATEGY_RESULT_INFO_MAP.put(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_8, MeasureCfResultInfo8.class);
    //PAA再保分入、分出都走MeasureCfResultInfo11.class
    STRATEGY_RESULT_INFO_MAP.put(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_10, MeasureCfResultInfo11.class);
    STRATEGY_RESULT_INFO_MAP.put(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_11, MeasureCfResultInfo11.class);
  }

  static {
    STRATEGY_EXP_MAP.put(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_7, MeasureCfBasicExpRst8.class);
  }

  static {
    STRATEGY_EXP_ACTUAL_MAP.put(EvaluateMethodTypeEnum.EVALUATE_METHOD_TYPE_7, MeasureCfBasicCalcRst7.class);
  }


  /**
   * 根据枚举类型执行对应的策略
   *
   * @param evaluateMethod 评估方法枚举类型
   * @param valMonth 评估时点(yyyyMM)
   * @return java.util.List<com.jdyx.measure.api.measure.domain.MeasureCfBasicData>
   * @author 刘瑞奎.
   * @date 2024/10/21.
   */
  public static void executeStrategyBasicData(EvaluateMethodTypeEnum evaluateMethod, String valMonth) {
    MeasureCfBasicStrategy measureCfBasicStrategy = SpringUtils.getBean(STRATEGY_CF_BASIC_MAP.get(evaluateMethod));
     measureCfBasicStrategy.doOperation(evaluateMethod, valMonth);
  }

  /**
   * 计量明细根据枚举类型执行对应的策略
   *
   * @param evaluateMethod 评估方法枚举类型
   * @param valMonth 评估时点(yyyyMM)
   * @param latch 信号量
   * @author 刘瑞奎.
   * @date 2024/10/21.
   */
  public static void executeStrategyResultInfo(List<MeasureCfBasicData> measureCfBasicDataList, EvaluateMethodTypeEnum evaluateMethod, String valMonth, CountDownLatch latch) {
    MeasureCfResultInfoStrategy measureCfBasicStrategy = SpringUtils.getBean(STRATEGY_RESULT_INFO_MAP.get(evaluateMethod));
    measureCfBasicStrategy.doOperation(measureCfBasicDataList, evaluateMethod, valMonth,latch);
  }

  /**
   * 计量明细根据枚举类型执行对应的策略
   *
   * @param evaluateMethod 评估方法枚举类型
   * @param valMonth 评估时点(yyyyMM)
   * @author 刘瑞奎.
   * @date 2024/10/21.
   */
  public static void executeStrategyResultInfo(List<MeasureCfBasicData> measureCfBasicDataList, EvaluateMethodTypeEnum evaluateMethod, String valMonth) {
    MeasureCfResultInfoStrategy measureCfBasicStrategy = SpringUtils.getBean(STRATEGY_RESULT_INFO_MAP.get(evaluateMethod));
    measureCfBasicStrategy.doOperation(measureCfBasicDataList, evaluateMethod, valMonth);
  }


  /**
   * 理赔配置根据枚举类型执行对应的策略
   * @param measureCfBasicDataList 计量源数据
   * @param evaluateMethod 评估方法枚举类型
   * @param valMonth 评估时点(yyyyMM)
   * @return java.util.List<com.jdyx.measure.api.measure.domain.MeasureConfCommonClaim>
   */
  public static List<MeasureConfCommonClaim> executeStrategyCommonClaim(List<MeasureCfBasicData> measureCfBasicDataList, EvaluateMethodTypeEnum evaluateMethod, String valMonth) {
    MeasureConfCommonClaimStrategy measureConfCommonClaimStrategy = SpringUtils.getBean(STRATEGY_COMMON_CLAIM_MAP.get(evaluateMethod));
    return measureConfCommonClaimStrategy.doOperation(measureCfBasicDataList, evaluateMethod, valMonth);
  }

  /**
   * -
   *
   * @return 返回值描述
   * @Author hzh
   * @date 2024/11/7
   */
  public static List<MeasureCfBbaExpRst> executeStrategyExpRst(List<MeasureCfResultInfo> list, EvaluateMethodTypeEnum evaluateMethod, String valMonth) throws ParseException {
    MeasureCfBasicExpRstStrategy strategy = SpringUtils.getBean(STRATEGY_EXP_MAP.get(evaluateMethod));
    return strategy.doOperation(list, evaluateMethod.getCode(), valMonth);
  }

  /**
   * -/实际现金流
   *
   * @return 返回值描述
   * @Author hzh
   * @date 2024/11/7
   */
  public static List<MeasureCfBbaBasicCalcRst> executeActualStrategyExpRst(List<MeasureCfBasicData> list, EvaluateMethodTypeEnum evaluateMethod, String valMonth) {
    MeasureCfBbaBasicCalcRstStrategy strategy = SpringUtils.getBean(STRATEGY_EXP_ACTUAL_MAP.get(evaluateMethod));
    return strategy.doOperation(list, evaluateMethod.getCode(), valMonth);
  }

  public static void main(String[] args) {
/*    SparkConf conf = new SparkConf()
      .setAppName("SpringBootSparkApp")
      //本例中使用了local[*]作为本地测试，在实际连接远程Spark集群时应使用spark://<spark-master-ip>:<port>
      .setMaster("local[*]");

    SparkSession spark = SparkSession.builder().config(conf).getOrCreate();

    JavaSparkContext javaSparkContext = new JavaSparkContext(conf);*/


/*    JavaRDD<Integer> processedNumbers = numberRDD.map(number -> number * 2);


    // 读取 PostgreSQL 数据表
    Dataset<Row> df = spark.read()
      .format("jdbc")
      .option("url", "jdbc:postgresql://127.0.0.1:5432/cas25_test?currentSchema=measure_platform&useUnicode=true&characterEncoding=utf8&useSSL=true&autoReconnect=true&reWriteBatchedInserts=true")
      .option("dbtable", "mytable")
      .option("user", "cas25")
      .option("password", "cas25")
      .load();

    df.foreach(row -> System.out.println(row.toString()));*/

  }

}

