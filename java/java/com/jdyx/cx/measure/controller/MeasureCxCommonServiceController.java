package com.jdyx.cx.measure.controller;

import cn.dev33.satoken.annotation.SaIgnore;
import cn.hutool.http.ContentType;
import cn.hutool.http.HttpRequest;
import cn.hutool.http.HttpResponse;
import cn.hutool.json.JSONUtil;
import com.beust.jcommander.internal.Maps;
import com.jdyx.common.api.anotation.ProcessAnnotation;
import com.jdyx.common.measure.service.MeasureCommonService;
import com.jdyx.cx.measure.domain.bo.Test1Bo;
import com.jdyx.cx.measure.service.MeasureCxZbService;
import com.kevin.common.core.domain.R;
import com.kevin.common.utils.DateUtils;
import com.kevin.common.utils.JsonUtils;
import java.lang.reflect.InvocationTargetException;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 公共计量服务
 *
 * @author kevin.
 * @date 2024/1/17.
 */
@Slf4j
@Validated
@RequiredArgsConstructor
@RestController
@RequestMapping("/measure")
public class MeasureCxCommonServiceController {

  private final MeasureCommonService measureService;
  private final MeasureCxZbService measureCxService;

  /**
   * 计算  当期核心计量(通用)
   *
   * @param valMethod 评估方法(1-BBA,2-PBBA,3-VFA,4-PAA)
   * @param valMonth 评估月(默认当月跑上月)
   * @return r
   */
  @SaIgnore
  @PostMapping("/core/setMeasureResultBbaCore")
  @ProcessAnnotation
  public R<?> setMeasureResultBbaCore(@RequestParam String valMethod, @RequestParam String valMonth,
                                      @RequestParam(defaultValue = "measure") String processCode) {
    log.info("valMethod={},valMonth={}", valMethod, valMonth);
    try {
      //计量准备数据插入通用实际现金流做转换
      measureCxService.setCxPiPaaCfBasicCalcRst(valMethod, valMonth);
      //根据计量核心配置表，遍历计算
      return measureService.setMeasureResultCore(valMethod, valMonth);
    } catch (InvocationTargetException | IllegalAccessException e) {
      throw new RuntimeException(e);
    }
  }


  /**
   * 计算  当期计量分录(通用)
   *
   * @param valMethod 评估方法(1-BBA,2-PBBA,3-VFA,4-PAA)
   * @param valMonth 评估月(默认当月跑上月)
   * @return r
   */
  @SaIgnore
  @PostMapping("/le/setResultAccountingScenarioAccount")
  @ProcessAnnotation
  public R<?> setResultAccountingScenarioAccount(@RequestParam String valMethod, @RequestParam String valMonth,
                                                 @RequestParam(defaultValue = "measure") String processCode,
                                                  @RequestParam(defaultValue = "") String varName) {
    log.info("valMethod={},valMonth={}", valMethod, valMonth);
    try {
      return measureService.setMeasureResultAccountingScenarioAccount(valMethod, valMonth, varName);
    } catch (InvocationTargetException | IllegalAccessException e) {
      throw new RuntimeException(e);
    }
  }

  @SaIgnore
  @PostMapping("/test")
  public R<?> test1(@RequestBody Test1Bo test1Bo) throws InterruptedException {
    log.info("执行耗时{}毫秒任务", JsonUtils.toJsonString(test1Bo));
    Thread.sleep(test1Bo.getTime());
    return R.ok(test1Bo);
  }

  public static void main(String[] args) {
    System.out.println(DateUtils.getTime());
    Map<String,Object>  body = Maps.newHashMap();
    //body.put("time",960002);
    body.put("time",1*60*1000);
    String str = JSONUtil.toJsonStr(body);
    HttpResponse response = HttpRequest.post("http://127.0.0.1:8091/measure/test")
      //.setProxy(new Proxy(Type.SOCKS,new InetSocketAddress("127.0.0.1", 1080)))
      .keepAlive(true)
      .setReadTimeout(2*60*1000)
      .body(str, ContentType.JSON.getValue())
      .execute();
    System.out.println(response);
    System.out.println("Response Headers: " + response.header("Connection"));
    System.out.println("Response Headers: " + response.headers());
    System.out.println(DateUtils.getTime());

/*      ScheduledExecutorService scheduler = Executors.newScheduledThreadPool(1);
    Runnable heartbeatTask = () -> {
      HttpRequest.get("http://10.128.21.132:8096/actuator/health")
        .setProxy(new Proxy(Type.SOCKS,new InetSocketAddress("127.0.0.1", 1080)))
        .execute();
      System.out.println("Heartbeat sent at " + System.currentTimeMillis());
    };
    scheduler.scheduleAtFixedRate(heartbeatTask, 0, 30, TimeUnit.SECONDS); */
  }


}
