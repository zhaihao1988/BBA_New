package com.jdyx.cx.measure.pipeline;

import com.google.common.collect.Maps;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;
import org.springframework.beans.BeansException;
import org.springframework.context.ApplicationContext;
import org.springframework.context.ApplicationContextAware;
import org.springframework.context.annotation.Bean;

/**
 * 管道路由的配置
 *
 * @author kevin.
 * @date 2024/11/4.
 */
//@Configuration
public class PipelineRouteConfig implements ApplicationContextAware {

  /**
   * 数据类型->管道中处理器类型列表 的路由
   */
  private static final Map<Class<? extends PipelineContext>, List<Class<? extends ContextHandler<? extends PipelineContext>>>> PIPELINE_ROUTE_MAP = Maps.newHashMap();


  /*
   * 在这里配置各种上下文类型对应的处理管道：键为上下文类型，值为处理器类型的列表
   */
  static {
    PIPELINE_ROUTE_MAP.put(InstanceBuildContext.class, Arrays.asList(
        //InputDataPreChecker.class,
        //ModelInstanceCreator.class,
        //ModelInstanceSaver.class
      )
    );
  }

  // 上下文
  private ApplicationContext appContext;

  /**
   * 生成管道映射关系
   *
   * @return Map
   */
  @Bean("pipelineRouteMap")
  public Map<Class<? extends PipelineContext>, List<? extends ContextHandler<? extends PipelineContext>>> getHandlerPipelineMap() {
    return PIPELINE_ROUTE_MAP.entrySet().stream().collect(Collectors.toMap(Map.Entry::getKey, this::toPipeline));
  }

  /**
   * 构建管道
   *
   * @param entry 键值对
   * @return 管道
   */
  private List<? extends ContextHandler<? extends PipelineContext>> toPipeline(
    Map.Entry<Class<? extends PipelineContext>, List<Class<? extends ContextHandler<? extends PipelineContext>>>> entry) {
    return entry.getValue().stream().map(appContext::getBean).collect(Collectors.toList());
  }

  /**
   * Set the ApplicationContext that this object runs in.
   *
   * @param applicationContext the ApplicationContext object to be used by this object
   * @throws BeansException if the ApplicationContext object cannot be used
   */
  @Override
  public void setApplicationContext(ApplicationContext applicationContext) throws BeansException {
    appContext = applicationContext;
  }

}
