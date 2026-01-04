package com.jdyx.cx.measure.pipeline;

import com.jdyx.measure.api.measure.domain.MeasureCfBasicData;
import java.util.Map;

/**
 * 模型实例构建的上下文
 *
 * @author kevin.
 * @date 2024/11/4.
 */
public class InstanceBuildContext extends PipelineContext {

  /**
   * 模型 id
   */
  private Long modelId;

  /**
   * 用户 id
   */
  private long userId;

  /**
   * 表单输入
   */
  private Map<String, MeasureCfBasicData> formInput;

  /**
   * 保存模型实例完成后，记录下 id
   */
  private Long instanceId;

  /**
   * 模型创建出错时的错误信息
   */
  private String errorMsg;

  // 其他参数

  @Override
  public String getName() {
    return "模型实例构建上下文";
  }
}
