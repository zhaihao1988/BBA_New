package com.jdyx.cx.measure.config;

import cn.hutool.extra.expression.engine.aviator.AviatorEngine;
import com.googlecode.aviator.AviatorEvaluatorInstance;
import com.googlecode.aviator.Expression;
import com.kevin.framework.config.AutoScanPgUpgradeScriptDdlConfig;
import java.util.HashMap;
import java.util.Map;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.annotation.Bean;
import org.springframework.stereotype.Component;

/**
 * 脚本自动维护（3.5.3 + 版本支持）
 * 数据库 DDL 表结构执行 SQL 自动维护功能
 *
 * @author kevin.
 * @date 2024/1/31.
 */
@Slf4j
@Component
public class MeasureCxBeanConfig {

  public static void main(String[] args) {
    Map<String, Object> map = new HashMap<>();
    map.put("type", "2");
    map.put("psiDescription", 3);
    //String expStr = "2 == bigint(type) ? 3*(10-10*psiDescription):1";
    //String expStr = " if(2 == bigint(type)) { 1 } else { 3*(10-10*psiDescription) }  ";

    String expStr = "double(1.1) == bigint(1.1) ? type : psiDescription";
    AviatorEvaluatorInstance aviatorEvaluatorInstance = new AviatorEngine().getEngine();
    Expression exp = aviatorEvaluatorInstance.compile(expStr);
    // Expression exp = SpringUtils.getBean(AviatorEngine.class).getEngine().compile(expStr, true);
    Object result = exp.execute(map);
    System.out.println(result);


  }

  /**
   * 注册默认库实例
   *
   * @return 自动升级bean
   */
  @Bean
  public AutoScanPgUpgradeScriptDdlConfig measureAutoScanPgUpgradeScriptDdlConfig() {
    return new AutoScanPgUpgradeScriptDdlConfig("pg_measure_platform", "measure_platform", "measure");
  }


}
