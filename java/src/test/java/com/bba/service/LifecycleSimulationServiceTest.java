package com.bba.service;

import com.bba.entity.PolicyContract;
import com.bba.entity.RateCurve;
import com.bba.model.Assumptions;
import com.bba.model.CashFlow;
import com.bba.service.logic.CoverageUnitsService;
import com.bba.service.logic.CsmLcMeasurementService;
import com.bba.service.logic.FulfillmentCashflowChangesService;
import com.bba.service.logic.InitialRecognitionService;
import com.bba.service.logic.RatesManagerService;
import com.bba.service.logic.RevenueService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;

import java.io.IOException;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.lenient;

public class LifecycleSimulationServiceTest {

    @Mock
    private DataLoaderService dataLoaderService;

    @Mock
    private RatesManagerService ratesManagerService;

    @Mock
    private CashFlowProjectorService cashFlowProjectorService;

    @Mock
    private PVCalculatorService pvCalculatorService;

    private LifecycleSimulationService lifecycleSimulationService;

    // @BeforeEach
    void manualSetUp() {
        System.out.println("DEBUG: manualSetUp started");
        try {
            MockitoAnnotations.openMocks(this);
            System.out.println("DEBUG: Mocks opened");
            
            Files.createDirectories(Paths.get("logs"));
            System.out.println("DEBUG: Logs dir created");

            // Real logic services
            CoverageUnitsService coverageUnitsService = new CoverageUnitsService();
            
            // InitialRecognitionService requires RatesManagerService (mocked)
            InitialRecognitionService initialRecognitionService = new InitialRecognitionService(ratesManagerService);
            
            // FulfillmentCashflowChangesService requires CoverageUnitsService (real)
            FulfillmentCashflowChangesService fulfillmentCashflowChangesService = new FulfillmentCashflowChangesService(coverageUnitsService);
            
            // CsmLcMeasurementService requires RatesManagerService (mocked) and CoverageUnitsService (real)
            CsmLcMeasurementService csmLcMeasurementService = new CsmLcMeasurementService(ratesManagerService, coverageUnitsService);
            RevenueService revenueService = new RevenueService();
            
            // PVGeneratorService is pure logic
            PVGeneratorService pvGeneratorService = new PVGeneratorService(dataLoaderService, cashFlowProjectorService, pvCalculatorService);
            
            // PVSourceLoaderService requires DataLoaderService (mocked) and PVGeneratorService (real)
            PVSourceLoaderService pvSourceLoaderService = new PVSourceLoaderService(dataLoaderService, pvGeneratorService);

            // Main Service
            lifecycleSimulationService = new LifecycleSimulationService(
                    dataLoaderService,
                    ratesManagerService,
                    pvSourceLoaderService,
                    initialRecognitionService,
                    fulfillmentCashflowChangesService,
                    csmLcMeasurementService,
                    revenueService
            );
            System.out.println("DEBUG: lifecycleSimulationService created: " + lifecycleSimulationService);

        } catch (Exception e) {
            e.printStackTrace();
            throw new RuntimeException("Setup failed", e);
        }
    }

    private void logDebug(String msg) {
        try {
            Files.write(Paths.get("debug_trace.txt"), (msg + "\n").getBytes(), java.nio.file.StandardOpenOption.CREATE, java.nio.file.StandardOpenOption.APPEND);
        } catch (IOException e) {
            e.printStackTrace();
        }
    }

    @Test
    void testRunSimulation() throws IOException {
        Files.deleteIfExists(Paths.get("debug_trace.txt"));
        logDebug("DEBUG: testRunSimulation started");
        
        try {
            manualSetUp();
            logDebug("DEBUG: manualSetUp returned");
        } catch (Throwable t) {
            logDebug("FATAL: manualSetUp failed: " + t);
            t.printStackTrace();
            throw t;
        }
        
        if (lifecycleSimulationService == null) {
            logDebug("FATAL: lifecycleSimulationService is null!");
            throw new NullPointerException("lifecycleSimulationService is null");
        }
        logDebug("DEBUG: lifecycleSimulationService is NOT null");

        String policyNo = "TEST_POLICY_001";
        String runDate = "2023-01-01";
        String certiNo = "CERT_001";

        // 1. Mock Policy Data
        PolicyContract policy = new PolicyContract();
        policy.setPolicyNo(policyNo);
        policy.setCertiNo(certiNo);
        policy.setUnderWriteDate(LocalDate.of(2023, 1, 1));
        policy.setStartDate(LocalDate.of(2023, 1, 1));
        policy.setEndDate(LocalDate.of(2023, 12, 31));
        policy.setWarrantyEndDate(LocalDate.of(2023, 3, 31));
        policy.setSumPremiumNoTax(new BigDecimal("1200.00"));
        policy.setClassCode("MOCK_CLASS");
        policy.setValMethod("GMM");
        
        logDebug("DEBUG: Mocking getPolicyData");
        lenient().when(dataLoaderService.getPolicyData(anyString(), any(), anyString(), anyString())).thenReturn(policy);

        // 2. Mock Assumptions
        Assumptions assumptions = new Assumptions();
        assumptions.setClassCode("MOCK_CLASS");
        assumptions.setLossRatio(new BigDecimal("0.60"));
        assumptions.setRaRatio(new BigDecimal("0.05"));
        assumptions.setMaintenanceExpenseRatio(new BigDecimal("0.10"));
        assumptions.setAcquisitionExpenseRatio(new BigDecimal("0.15"));
        assumptions.setIndirectClaimsExpenseRatio(BigDecimal.ZERO);
        
        logDebug("DEBUG: Mocking getAssumptions");
        lenient().when(dataLoaderService.getAssumptions(anyString(), anyString(), anyString())).thenReturn(assumptions);

        // 3. Mock Rates
        List<RateCurve> rates = new ArrayList<>();
        for (int i = 0; i <= 120; i++) {
            RateCurve rate = new RateCurve();
            rate.setTermMonth(i);
            rate.setForwardDisrateValue(new BigDecimal("0.03"));
            rates.add(rate);
        }
        
        logDebug("DEBUG: Mocking rates");
        lenient().when(ratesManagerService.getRates(anyString())).thenReturn(rates);
        lenient().when(ratesManagerService.calculateSpotRate(any())).thenReturn(new BigDecimal("0.03"));
        lenient().when(dataLoaderService.getRates(anyString())).thenReturn(rates);

        // 4. Mock Cash Flows
        List<CashFlow> cashFlows = new ArrayList<>();
        CashFlow cf = new CashFlow();
        cf.setYear(2023);
        cf.setMonth(1);
        cf.setYyyymm("202301");
        cf.setDate(LocalDate.of(2023, 1, 1));
        cf.setPremium(new BigDecimal("100.00"));
        cf.setClaims(new BigDecimal("50.00"));
        cf.setExpenses(new BigDecimal("10.00"));
        cashFlows.add(cf);
        
        logDebug("DEBUG: Mocking projectPolicyFlows");
        lenient().when(cashFlowProjectorService.projectPolicyFlows(any(), any())).thenReturn(cashFlows);
        
        // Mock PV Calculator
        logDebug("DEBUG: Mocking PV Calculator");
        lenient().when(pvCalculatorService.calculatePvInitialRecognition(anyList(), any(), anyBoolean(), anyList(), any(LocalDate.class), any(LocalDate.class)))
                .thenReturn(new BigDecimal("1000.00")); 
        lenient().when(pvCalculatorService.calculatePvBegLcu(anyList(), any(), anyList(), any(LocalDate.class)))
                .thenReturn(new BigDecimal("1000.00"));
        lenient().when(pvCalculatorService.calculatePvExact(anyList(), any(), anyList(), any(LocalDate.class), any(LocalDate.class)))
                .thenReturn(new BigDecimal("1000.00"));
        lenient().when(pvCalculatorService.calculatePvCurrentPeriodNoInterest(anyList(), any(), anyList(), any(LocalDate.class), any(LocalDate.class)))
                .thenReturn(new BigDecimal("1000.00"));

        // 5. Run Simulation
        logDebug("Starting Simulation Test for " + policyNo);
        try {
            lifecycleSimulationService.runSimulation(policyNo, certiNo, runDate);
            logDebug("Simulation call returned normally");
        } catch (Throwable e) {
            logDebug("CAUGHT EXCEPTION IN TEST: " + e);
            for (StackTraceElement ste : e.getStackTrace()) {
                logDebug("  at " + ste.toString());
            }
            e.printStackTrace(); // Print to stderr too
            throw e;
        }
        logDebug("Simulation Completed.");

        // 6. Output Log Content
        Path logPath = Paths.get("logs", "simulation_" + policyNo + ".md");
        if (Files.exists(logPath)) {
            logDebug("Log file exists");
            System.out.println("\n--- Simulation Log Output ---\n");
            List<String> lines = Files.readAllLines(logPath, java.nio.charset.StandardCharsets.UTF_8);
            lines.forEach(System.out::println);
            System.out.println("\n-----------------------------\n");
        } else {
            logDebug("Log file NOT found");
            System.err.println("Log file not found at: " + logPath.toAbsolutePath());
        }
    }
}
