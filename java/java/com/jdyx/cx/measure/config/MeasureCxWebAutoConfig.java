package com.jdyx.cx.measure.config;

import com.jdyx.cx.measure.handler.CxDynamicDatasourceInterceptor;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * 拦截
 *
 * @author kevin.
 * @date 2024/1/26.
 */
@Configuration
public class MeasureCxWebAutoConfig implements WebMvcConfigurer {

  @Override
  public void addInterceptors(InterceptorRegistry registry) {
    registry.addInterceptor(new CxDynamicDatasourceInterceptor()).addPathPatterns("/measure/**");
  }
}
