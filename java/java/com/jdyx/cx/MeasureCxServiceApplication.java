package com.jdyx.cx;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.metrics.buffering.BufferingApplicationStartup;

/**
 * measure启动程序
 *
 * @author kevin
 */
@MapperScan(basePackages = {"com.jdyx.cx.measure.**.mapper", "com.jdyx.preparation.propertyinsurance.mapper"})
@SpringBootApplication
public class MeasureCxServiceApplication {

  public static void main(String[] args) {
    //System.setProperty("spring.devtools.restart.enabled", "false");
    System.setProperty("java.util.concurrent.ForkJoinPool.common.parallelism", "10");
    SpringApplication application = new SpringApplication(MeasureCxServiceApplication.class);
    application.setApplicationStartup(new BufferingApplicationStartup(2048));
    application.run(args);
    System.out.println("(♥◠‿◠)ﾉﾞ  measure-service 启动成功   ლ(´ڡ`ლ)ﾞ");
  }

}
