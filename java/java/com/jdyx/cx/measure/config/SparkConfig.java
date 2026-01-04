/*

package com.jdyx.cx.measure.config;


import com.baomidou.mybatisplus.core.toolkit.AES;
import org.apache.spark.SparkConf;
import org.apache.spark.api.java.JavaSparkContext;
import org.apache.spark.sql.SparkSession;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.support.PropertySourcesPlaceholderConfigurer;

*/
/**
 * SparkConfig 配置
 *
 * @author 刘瑞奎.
 * @date 2024/10/22.
 *//*


//Configuration
public class SparkConfig {

  @Value("${spark.app.name}")
  private String appName;
  @Value("${spark.home}")
  private String sparkHome;
  @Value("${spark.master.uri}")
  private String sparkMasterUri;
  @Value("${spark.driver.memory}")
  private String sparkDriverMemory;
  @Value("${spark.worker.memory}")
  private String sparkWorkerMemory;
  @Value("${spark.executor.memory}")
  private String sparkExecutorMemory;
  @Value("${spark.executor.cores}")
  private String sparkExecutorCores;
  @Value("${spark.num.executors}")
  private String sparkExecutorsNum;
  @Value("${spark.network.timeout}")
  private String networkTimeout;
  @Value("${spark.executor.heartbeatInterval}")
  private String heartbeatIntervalTime;
  @Value("${spark.driver.maxResultSize}")
  private String maxResultSize;
  @Value("${spark.rpc.message.maxSize}")
  private String sparkRpcMessageMaxSize;

  @Bean
  public SparkConf sparkConf() {
    SparkConf sparkConf = new SparkConf()
      .setAppName(appName)
      .setMaster(sparkMasterUri)
      .set("spark.driver.memory", sparkDriverMemory)
      .set("spark.driver.maxResultSize", maxResultSize)
      .set("spark.worker.memory", sparkWorkerMemory) //"26g"
      .set("spark.executor.memory", sparkExecutorMemory)
      .set("spark.executor.cores", sparkExecutorCores)
      .set("spark.executor.heartbeatInterval", heartbeatIntervalTime)
      .set("spark.num.executors", sparkExecutorsNum)
      .set("spark.network.timeout", networkTimeout)
      .set("spark.rpc.message.maxSize", sparkRpcMessageMaxSize);
    //                .set("spark.shuffle.memoryFraction","0") //默认0.2
    return sparkConf;
  }

  @Bean
  @ConditionalOnMissingBean(JavaSparkContext.class)
  public JavaSparkContext javaSparkContext() {
    return new JavaSparkContext(sparkConf());
  }

  @Bean
  public SparkSession sparkSession() {
    return SparkSession
      .builder()
      .sparkContext(javaSparkContext().sc())
      .appName(appName)
      .getOrCreate();
  }

  @Bean
  public static PropertySourcesPlaceholderConfigurer propertySourcesPlaceholderConfigurer() {
    return new PropertySourcesPlaceholderConfigurer();
  }

  public static void main(String[] args) {
    String encryptedData = AES.encrypt("TestQAZ123", "6f01f24c2030837a");
    System.out.println(encryptedData);

  }
}

*/
