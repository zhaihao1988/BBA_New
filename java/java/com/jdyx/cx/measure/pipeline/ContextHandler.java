package com.jdyx.cx.measure.pipeline;

/**
 * 管道中的上下文处理器
 *
 * @author kevin.
 * @date 2024/11/4.
 */
public interface ContextHandler<T extends PipelineContext> {

  /**
   * 处理输入的上下文数据
   *
   * @param context 处理时的上下文数据
   * @return 返回 true 则表示由下一个 ContextHandler 继续处理，返回 false 则表示处理结束
   */
  boolean handle(T context);

}
