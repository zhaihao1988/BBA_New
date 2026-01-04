package com.bba.cli;

import com.bba.service.LifecycleSimulationService;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;

/**
 * CLI runner for assumption branch (single policy).
 * Usage:
 *   java -cp target/bba-lifecycle-simulation-0.0.1-SNAPSHOT.jar com.bba.cli.AssumptionRunner --policy mock1 --valMonth 202412
 * Falls back to BbaSimulationApplication context but disables web server.
 */
public class AssumptionRunner {
    public static void main(String[] args) {
        String policyNo = "mock1";
        String certiNo = null;
        String valMonth = "202412";
        for (int i = 0; i < args.length; i++) {
            if ("--policy".equalsIgnoreCase(args[i]) && i + 1 < args.length) {
                policyNo = args[++i];
            } else if ("--certi".equalsIgnoreCase(args[i]) && i + 1 < args.length) {
                certiNo = args[++i];
            } else if ("--valMonth".equalsIgnoreCase(args[i]) && i + 1 < args.length) {
                valMonth = args[++i];
            }
        }

        ConfigurableApplicationContext ctx = new SpringApplicationBuilder(com.bba.BbaSimulationApplication.class)
                .web(WebApplicationType.NONE)
                .run("--spring.main.web-application-type=none");
        try {
            LifecycleSimulationService service = ctx.getBean(LifecycleSimulationService.class);
            service.runSimulation(policyNo, certiNo, valMonth);
        } finally {
            ctx.close();
        }
    }
}

