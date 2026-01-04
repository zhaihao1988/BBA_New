package com.bba.cli;

import com.bba.service.BatchAssumptionService;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;

/**
 * Batch runner for assumption branch.
 * Usage examples:
 *   java -cp target/bba-lifecycle-simulation-0.0.1-SNAPSHOT.jar com.bba.cli.AssumptionBatchRunner --limit 10 --valMonth 202412 --out batch.csv
 *   java -cp target/... com.bba.cli.AssumptionBatchRunner --policy mock1 --valMonth 202412 --out single.csv
 */
public class AssumptionBatchRunner {
    public static void main(String[] args) {
        String policyNo = null;
        int limit = -1;
        String valMonth = "202412";
        String out = "batch_assumption.csv";

        for (int i = 0; i < args.length; i++) {
            if ("--policy".equalsIgnoreCase(args[i]) && i + 1 < args.length) {
                policyNo = args[++i];
            } else if ("--limit".equalsIgnoreCase(args[i]) && i + 1 < args.length) {
                limit = Integer.parseInt(args[++i]);
            } else if ("--valMonth".equalsIgnoreCase(args[i]) && i + 1 < args.length) {
                valMonth = args[++i];
            } else if ("--out".equalsIgnoreCase(args[i]) && i + 1 < args.length) {
                out = args[++i];
            }
        }

        ConfigurableApplicationContext ctx = new SpringApplicationBuilder(com.bba.BbaSimulationApplication.class)
                .web(WebApplicationType.NONE)
                .run("--spring.main.web-application-type=none");
        try {
            BatchAssumptionService batchService = ctx.getBean(BatchAssumptionService.class);
            batchService.run(policyNo, limit, valMonth, out);
        } finally {
            ctx.close();
        }
    }
}

