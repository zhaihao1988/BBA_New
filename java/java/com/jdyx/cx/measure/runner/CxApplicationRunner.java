package com.jdyx.cx.measure.runner;

import com.baomidou.dynamic.datasource.toolkit.CryptoUtils;
import com.kevin.common.config.ProjectInfoConfig;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

/**
 * 初始化模块对应业务数据
 *
 * @author 刘瑞奎
 */
@Slf4j
@RequiredArgsConstructor
@Component
public class CxApplicationRunner implements ApplicationRunner {

  /** 项目基本信息 */
  private final ProjectInfoConfig projectConfig;

  public static void main(String[] args) throws Exception {
    String[] arr = CryptoUtils.genKeyPair(520);
    System.out.println("privateKey:  " + arr[0]);
    System.out.println("publicKey:  " + arr[1]);
    //Java版本环境-产险
    //System.out.println("username:  " + CryptoUtils.encrypt(arr[0], "biz"));
    //System.out.println("password:  " + CryptoUtils.encrypt(arr[0], "Biz123!@#"));
    //System.out.println("username:  " + CryptoUtils.encrypt(arr[0], "root"));
    //System.out.println("password:  " + CryptoUtils.encrypt(arr[0], "bizQAZ123"));
    //演示环境
    //System.out.println("username:  " + CryptoUtils.encrypt(arr[0], "biz"));
    //System.out.println("password:  " + CryptoUtils.encrypt(arr[0], "QWEasd@123"));
    //System.out.println("username:  " + CryptoUtils.encrypt(arr[0], "root"));
    //System.out.println("password:  " + CryptoUtils.encrypt(arr[0], "bizQAZ123"));
    //
    //演示环境
    System.out.println("username:  " + CryptoUtils.encrypt(arr[0], "cas25"));
    System.out.println("password:  " + CryptoUtils.encrypt(arr[0], "Cas25QAZ123"));
  }

  @Override
  public void run(ApplicationArguments args) throws Exception {
    System.out.println("**************【初始化【CxApplicationRunner】模块业务数据】***************");
    //1.启用缓存懒加载
    if (!projectConfig.isCacheLazy()) {
      return;
    }
    System.out.println("**************【初始化【CxApplicationRunner】模块业务数据开始】***************");
    System.out.println("**************【初始化【CxApplicationRunner】模块对应业务数据完成】***************");
  }

}
