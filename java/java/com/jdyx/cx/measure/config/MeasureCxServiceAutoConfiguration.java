package com.jdyx.cx.measure.config;

import lombok.extern.slf4j.Slf4j;
import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.AutoConfiguration;
import org.springframework.context.annotation.ComponentScan;
import org.springframework.context.annotation.Configuration;

/**
 * 自动装载
 *
 * @author (kevin).
 * @date 2023/6/28.
 */
@ComponentScan(basePackages = "com.jdyx.cx.measure.**")
@MapperScan(basePackages = {"com.jdyx.cx.measure.**.mapper"})
@Slf4j
@AutoConfiguration
public class MeasureCxServiceAutoConfiguration implements ApplicationRunner {

  @Override
  public void run(ApplicationArguments args) {
    log.info("加载[MeasureServiceInitialization]SDK完成");
  }
}
