package com.bba;

import com.bba.service.LifecycleSimulationService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
@Slf4j
public class BbaRunner implements CommandLineRunner {

    private final LifecycleSimulationService lifecycleSimulationService;

    @Override
    public void run(String... args) throws Exception {
        log.info("Starting BBA Lifecycle Simulation...");
        
        String policyNo = "mock1";
        String certiNo = null;
        String runDate = "202412";
        
        if (args.length > 0) {
            policyNo = args[0];
        }
        
        try {
            lifecycleSimulationService.runSimulation(policyNo, certiNo, runDate);
            log.info("Simulation completed successfully for policy: {}", policyNo);
        } catch (Exception e) {
            log.error("Simulation failed for policy: {}", policyNo, e);
        }
    }
}
