package com.bba;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
@MapperScan("com.bba.mapper")
public class BbaSimulationApplication {

    public static void main(String[] args) {
        SpringApplication.run(BbaSimulationApplication.class, args);
    }

}
