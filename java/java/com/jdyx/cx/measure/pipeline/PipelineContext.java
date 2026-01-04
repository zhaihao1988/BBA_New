package com.jdyx.cx.measure.pipeline;


import java.time.LocalDateTime;
import lombok.Getter;
import lombok.Setter;

/**
 * 传递到管道的上下文
 *
 * @author kevin.
 * @date 2024/11/4.
 */
@Getter
@Setter
public class PipelineContext {

  /**
   * 处理开始时间
   */
  private LocalDateTime startTime;

  /**
   * 处理结束时间
   */
  private LocalDateTime endTime;

  /**
   * 获取数据名称
   */
  public String getName() {
    return this.getClass().getSimpleName();
  }

}
