package com.bba.service;

import com.bba.entity.PolicyContract;
import com.bba.entity.RateCurve;
import com.bba.model.*;
import com.bba.model.pv.PVSourceDataCollection;
import com.bba.service.logic.CsmLcMeasurementService;
import com.bba.service.logic.FulfillmentCashflowChangesService;
import com.bba.service.logic.InitialRecognitionService;
import com.bba.service.logic.RatesManagerService;
import com.bba.service.logic.RevenueService;
import com.bba.util.CalculationLogger;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.Period;
import java.time.format.DateTimeFormatter;
import java.util.*;

@Service
@Slf4j
public class LifecycleSimulationService {

    private final DataLoaderService dataLoaderService;
    private final RatesManagerService ratesManagerService;
    private final PVSourceLoaderService pvSourceLoaderService;
    private final InitialRecognitionService initialRecognitionService;
    private final FulfillmentCashflowChangesService fulfillmentCashflowChangesService;
    private final CsmLcMeasurementService csmLcMeasurementService;
    private final RevenueService revenueService;

    // 最近一次 runSimulation 的上下文，用于批量导出
    private CalculationContext lastContext;

    private static final DateTimeFormatter YYYYMM = DateTimeFormatter.ofPattern("yyyyMM");
    private static final String VAL_METHOD = "BBA"; // Default

    public LifecycleSimulationService(
            DataLoaderService dataLoaderService,
            RatesManagerService ratesManagerService,
            PVSourceLoaderService pvSourceLoaderService,
            InitialRecognitionService initialRecognitionService,
            FulfillmentCashflowChangesService fulfillmentCashflowChangesService,
            CsmLcMeasurementService csmLcMeasurementService,
            RevenueService revenueService) {
        this.dataLoaderService = dataLoaderService;
        this.ratesManagerService = ratesManagerService;
        this.pvSourceLoaderService = pvSourceLoaderService;
        this.initialRecognitionService = initialRecognitionService;
        this.fulfillmentCashflowChangesService = fulfillmentCashflowChangesService;
        this.csmLcMeasurementService = csmLcMeasurementService;
        this.revenueService = revenueService;
        System.out.println("DEBUG: LifecycleSimulationService initialized. dataLoaderService=" + dataLoaderService);
    }

    public void runSimulation(String policyNo, String certiNo, String runDate) {
        System.out.println("DEBUG: runSimulation called with " + policyNo);
        if (dataLoaderService == null) System.out.println("DEBUG: dataLoaderService is NULL inside runSimulation");
        
        CalculationLogger logger = null;
        try {
            // Create logger for this run
            logger = new CalculationLogger("logs/simulation_" + policyNo + ".md");
            logger.logSection("IFRS 17 BBA 生命周期仿真器 - 初始化");
            logger.logText("**保单号**: " + policyNo);

            // 1. Initialize
            PolicyContract policyContract = dataLoaderService.getPolicyData(policyNo, certiNo, VAL_METHOD, runDate);
            if (policyContract == null) {
                throw new IllegalArgumentException("未找到保单号 " + policyNo + " 的数据");
            }
            
            logPolicyInfo(logger, policyContract);

            // Determine contract type
            LocalDate underWriteDate = policyContract.getUnderWriteDate();
            int valYear = underWriteDate.getYear();
            if (valYear < LocalDate.now().getYear()) { // Simplified check
                logger.logText("- ℹ️  **合同类型判定**：签单日期(" + valYear + ")早于当前年度，认定为存量合同");
                logger.logText("  注意：本仿真器从初始确认日开始模拟，因此按新业务处理");
            } else {
                logger.logText("- ℹ️  **合同类型判定**：签单日期(" + valYear + ")与评估基准日同年，认定为新业务");
            }

            // Create States
            PolicyState policyState = createPolicyState(policyContract);
            CohortState cohortState = createCohortState(policyContract.getClassCode());

            // Load Initial Assumptions and Rates
            String initValMonthStr = underWriteDate.format(YYYYMM);
            Assumptions initialAssumptions = loadAssumptions(logger, policyContract.getClassCode(), initValMonthStr);
            List<RateCurve> initialRates = loadRates(logger, initValMonthStr);

            // Generate In-Memory PV Data (Replacing JSON loading)
            logger.logText("### [Step 0] 生成 PV 原材料数据 (内存计算)");
            PVSourceDataCollection pvCollection = pvSourceLoaderService.generatePvSourceData(policyNo, runDate);
            if (pvCollection == null || pvCollection.getDataByMonth().isEmpty()) {
                throw new RuntimeException("无法生成 PV 原材料数据");
            }
            logger.logText("✅ 成功生成 " + pvCollection.getDataByMonth().size() + " 条 PV 数据记录");

            // 2. Initial Recognition
            CalculationContext context = runInitialRecognition(
                    logger, policyState, cohortState, initialAssumptions, initialRates, policyContract, pvCollection
            );

            // 3. Yearly Loop
            int startYear = underWriteDate.getYear();
            int endYear = policyContract.getEndDate().getYear();
            
            // Map to store history of assumptions if needed for previous year lookups
            Map<String, Assumptions> assumptionsHistory = new HashMap<>();
            assumptionsHistory.put(initValMonthStr, initialAssumptions);

            for (int year = startYear; year <= endYear; year++) {
                boolean isInitialYear = (year == startYear);
                
                // Prepare context for the year
                if (!isInitialYear) {
                    context = buildRollforwardContext(context, year, cohortState, policyState, initialRates);
                } else {
                    prepareInitialYearContext(context, policyState);
                }

                runYearlyMeasurement(
                        year, context, logger, policyState, cohortState, 
                        isInitialYear, initialRates, assumptionsHistory
                );
                
                // TODO: Save results/logs
            }
            
            logger.close();

        } catch (Throwable e) {
            System.err.println("FATAL ERROR IN runSimulation:");
            e.printStackTrace();
            if (logger != null) {
                logger.logText("❌ 仿真过程发生错误: " + e.getMessage());
                logger.close();
            }
            log.error("Simulation failed", e);
            if (e instanceof RuntimeException) throw (RuntimeException) e;
            throw new RuntimeException(e);
        }
    }

    private void runYearlyMeasurement(
            int year,
            CalculationContext context,
            CalculationLogger logger,
            PolicyState policyState,
            CohortState cohortState,
            boolean isInitialYear,
            List<RateCurve> initialRates,
            Map<String, Assumptions> assumptionsHistory
    ) {
        logger.logSection("Year " + year + " 年度计量");

        LocalDate evalDate = LocalDate.of(year, 12, 31);
        String valMonthStr = evalDate.format(YYYYMM);

        logger.logText("### [Step 1] 确定评估时点");
        logger.logText("- **评估日期**: " + evalDate);
        logger.logText("- **评估月份**: " + valMonthStr);

        // Load latest data
        logger.logText("### [Step 2] 读取最新数据（动态假设更新）");
        
        // Rates
        List<RateCurve> currentRates = ratesManagerService.getRates(valMonthStr);
        if (currentRates.isEmpty()) {
            logger.logText("⚠️  **警告**: 未找到 " + valMonthStr + " 的利率曲线，使用上一年利率曲线");
            currentRates = context.getRatesDf(); // Use previous year's
        } else {
            logger.logText("✅ 成功获取 " + valMonthStr + " 利率曲线 (" + currentRates.size() + " 条记录)");
        }
        context.setRatesDfEop(currentRates);
        
        // Assumptions
        Assumptions currentAssumptions = loadAssumptions(logger, cohortState.getCohortId(), valMonthStr);
        assumptionsHistory.put(valMonthStr, currentAssumptions);
        
        // Update Context
        context.setEopDate(evalDate);
        context.setEndDate(evalDate); // For the context of this year's run
        context.setValMonthStr(valMonthStr);
        context.setYear(year);
        if (context.getTotalMonths() == 0) {
            context.setTotalMonths(calculateTotalContractMonths(policyState));
        }

        // Ensure PV Data
        boolean isNewBusinessYear = (year == context.getUnderWriteDate().getYear());
        List<String> monthsToLoad = new ArrayList<>();
        if (isNewBusinessYear) {
            monthsToLoad.add(valMonthStr);
        } else {
            monthsToLoad.add(LocalDate.of(year, 1, 1).format(YYYYMM));
            monthsToLoad.add(valMonthStr);
        }
        ensurePvDataForContext(context, monthsToLoad);

        // Calculate months passed
        LocalDate periodStart;
        if (isInitialYear) {
             // Logic to handle backdated policies if needed, simplified here
             periodStart = context.getUnderWriteDate(); 
             if (policyState.getStartDate().isBefore(periodStart)) {
                 periodStart = policyState.getStartDate();
             }
             // Or ensure it's within the year
             if (periodStart.getYear() < year) {
                 periodStart = LocalDate.of(year, 1, 1);
             }
        } else {
            periodStart = LocalDate.of(year, 1, 1);
        }
        context.setStartDate(periodStart);
        context.setWarrantyEndDate(policyState.getWarrantyEndDate());
        
        context.setMonthsPassed(calculateMonthsBetween(periodStart, evalDate));
        context.setCumulativeMonthsStart(cohortState.getMonthsSinceInitial());
        context.setCumulativeMonthsEnd(context.getCumulativeMonthsStart() + context.getMonthsPassed());
        context.setInitialYear(isInitialYear);

        // Update Policy State temporary view
        policyState.setValuationDate(evalDate);
        policyState.setMonthsPassed(context.getMonthsPassed());

        // Run Logic Pipeline
        logger.logText("### [Step 4] 执行计量流水线");
        
        List<PolicyState> policies = Collections.singletonList(policyState);
        context.setPolicies(policies);

        // [Assumption分支逻辑] 在进入 FulfillmentCashflowChanges 之前准备实际IACF：
        // - 若 context.actualIacfIncurred 已经由外部传入，则保留不覆盖
        // - 否则使用当期精算假设 acquisition_expense_ratio * actualPremium 计算
        if (context.getActualIacfIncurred() == null) {
            BigDecimal actualPremium = context.getActualPremium();
            if (actualPremium == null && context.getPolicyData() != null) {
                actualPremium = context.getPolicyData().getSumPremiumNoTax();
                context.setActualPremium(actualPremium);
            }
            BigDecimal acqRatio = (currentAssumptions != null && currentAssumptions.getAcquisitionExpenseRatio() != null)
                    ? currentAssumptions.getAcquisitionExpenseRatio()
                    : BigDecimal.ZERO;
            BigDecimal actualIacf = (actualPremium != null ? actualPremium : BigDecimal.ZERO).multiply(acqRatio);
            context.setActualIacfIncurred(actualIacf);
        }

        // 1. Fulfillment Cashflow Changes
        fulfillmentCashflowChangesService.run(context, logger, currentAssumptions, cohortState, policies, isNewBusinessYear);
        
        // 2. CSM/LC Measurement
        csmLcMeasurementService.run(context, logger, cohortState, policyState, policies);

        // 3. Revenue (signs aligned with Python: CSM/IACF amort keep negative)
        revenueService.run(context, logger);

            // 缓存最近一次运行的上下文，供批量导出使用
            this.lastContext = context;
        
        // Update Cohort State for next year rollforward
        // In a real system, we might save state to DB here
        cohortState.calculateEopBalances(); // Calculate EOP first
        cohortState.rollForward(); // Prepare for next year (move EOP to BOP)
        cohortState.setMonthsSinceInitial(context.getCumulativeMonthsEnd());
    }

    private CalculationContext runInitialRecognition(
            CalculationLogger logger, 
            PolicyState policyState, 
            CohortState cohortState, 
            Assumptions assumptions, 
            List<RateCurve> rates,
            PolicyContract policyContract,
            PVSourceDataCollection pvCollection
    ) {
        logger.logSection("Part 1: 初始确认 (Initial Recognition) - Year " + policyState.getValuationDate().getYear());
        
        CalculationContext context = new CalculationContext();
        context.setPolicyData(policyContract);
        context.setPolicyNo(policyContract.getPolicyNo());
        context.setCertiNo(policyContract.getCertiNo());
        context.setUnderWriteDate(policyState.getValuationDate());
        context.setStartDate(policyState.getStartDate());
        context.setEndDate(policyState.getEndDate());
        context.setWarrantyEndDate(policyState.getWarrantyEndDate());
        context.setYear(policyState.getValuationDate().getYear());
        context.setValMonthStr(policyState.getValuationDate().format(YYYYMM));
        context.setTotalMonths(policyState.getMonthsPassed() + policyState.getMonthsRemaining());
        context.setRatesDf(rates);
        context.setRatesDfLocked(rates); // Initially same
        context.setPvSourceData(pvCollection); // Set generated PV data

        ensurePvDataForContext(context, Collections.singletonList(context.getValMonthStr()));
        
        initialRecognitionService.run(context, logger, assumptions, cohortState);
        
        // Update states
        policyState.setInitialCsm(context.getNbInitialCsm() != null ? context.getNbInitialCsm() : BigDecimal.ZERO);
        policyState.setInitialLc(context.getNbInitialLc() != null ? context.getNbInitialLc() : BigDecimal.ZERO);
        
        cohortState.setNewCsm(policyState.getInitialCsm());
        cohortState.setNewLc(policyState.getInitialLc());
        
        context.setPolicies(Collections.singletonList(policyState));
        
        return context;
    }

    private void prepareInitialYearContext(CalculationContext context, PolicyState policyState) {
        context.setBopCsm(BigDecimal.ZERO);
        context.setBopLc(BigDecimal.ZERO);
        context.setBopIacf(BigDecimal.ZERO);
        context.setStartDate(context.getUnderWriteDate());
        context.setEndDate(LocalDate.of(context.getYear(), 12, 31));
        context.setWarrantyEndDate(policyState.getWarrantyEndDate());
        
        if (context.getTotalMonths() == 0) {
            context.setTotalMonths(calculateTotalContractMonths(policyState));
        }
    }

    public CalculationContext getLastContext() {
        return lastContext;
    }
    
    private CalculationContext buildRollforwardContext(
            CalculationContext prevContext, 
            int targetYear, 
            CohortState cohortState, 
            PolicyState policyState,
            List<RateCurve> initialRates
    ) {
        CalculationContext context = new CalculationContext();
        
        // Copy static/persistent attributes
        context.setPolicyData(prevContext.getPolicyData());
        context.setPolicyNo(prevContext.getPolicyNo());
        context.setCertiNo(prevContext.getCertiNo());
        context.setUnderWriteDate(prevContext.getUnderWriteDate());
        context.setTotalMonths(prevContext.getTotalMonths());
        context.setRatesDf(prevContext.getRatesDf()); // Carry over BOP rates (usually) or Initial rates? 
        // Python: context.rates_df = self.initial_rates_df (reset to initial for locking logic usually, or carry over?)
        // Python code says: if context.rates_df is None: context.rates_df = self.initial_rates_df
        // In rollforward, we typically want locked rates to persist.
        context.setRatesDfLocked(prevContext.getRatesDfLocked());
        
        // Persistent PV Source Data
        context.setPvSourceData(prevContext.getPvSourceData());
        
        context.setYear(targetYear);
        context.setStartDate(LocalDate.of(targetYear, 1, 1));
        context.setEndDate(LocalDate.of(targetYear, 12, 31));
        context.setWarrantyEndDate(policyState.getWarrantyEndDate());
        
        context.setBopCsm(cohortState.getBopCsm());
        context.setBopLc(cohortState.getBopLc());
        context.setBopIacf(cohortState.getBopIacf()); // Need to ensure CohortState tracks this
        
        context.setNbInitialCsm(BigDecimal.ZERO);
        context.setNbInitialLc(BigDecimal.ZERO);
        context.setNbIacfAddition(BigDecimal.ZERO);
        
        if (context.getTotalMonths() == 0) {
            context.setTotalMonths(calculateTotalContractMonths(policyState));
        }
        
        return context;
    }

    private void ensurePvDataForContext(CalculationContext context, List<String> months) {
        if (context.getPvSourceData() == null) {
            throw new RuntimeException("PV Source Data is missing in context. Ensure it is generated before simulation.");
        }
        
        for (String month : months) {
            if (context.getPvSourceData().getData(month) == null) {
                throw new RuntimeException("Missing PV Data for " + month + " in generated collection");
            }
        }
    }

    // --- Helpers ---

    private void logPolicyInfo(CalculationLogger logger, PolicyContract policy) {
        logger.logText("- ✅ **签单日期**: " + policy.getUnderWriteDate());
        logger.logText("- ✅ **起保日期**: " + policy.getStartDate());
        logger.logText("- ✅ **终保日期**: " + policy.getEndDate());
        logger.logText("- ✅ **保修结束日期**: " + policy.getWarrantyEndDate());
        logger.logText("- ✅ **签单保费**: " + policy.getSumPremiumNoTax());
        logger.logText("- ✅ **险类代码**: " + policy.getClassCode());
    }

    private PolicyState createPolicyState(PolicyContract policy) {
        PolicyState state = new PolicyState();
        state.setPolicyNo(policy.getPolicyNo());
        state.setStartDate(policy.getStartDate());
        state.setEndDate(policy.getEndDate());
        state.setWarrantyEndDate(policy.getWarrantyEndDate());
        state.setWrittenPremium(policy.getSumPremiumNoTax());
        state.setValuationDate(policy.getUnderWriteDate()); // Initial date
        return state;
    }

    private CohortState createCohortState(String classCode) {
        CohortState state = new CohortState();
        state.setCohortId(classCode);
        state.setWeightedLockedRate(BigDecimal.ZERO);
        state.setTotalWrittenPremium(BigDecimal.ZERO);
        return state;
    }

    private Assumptions loadAssumptions(CalculationLogger logger, String classCode, String valMonthStr) {
        Assumptions assumptions = dataLoaderService.getAssumptions(classCode, valMonthStr, VAL_METHOD);
        if (assumptions == null) {
            throw new RuntimeException("未找到险类 " + classCode + " 在 " + valMonthStr + " 的精算假设");
        }
        logger.logText("✅ 精算假设 (" + valMonthStr + "):");
        logger.logText("   - 赔付率: " + assumptions.getLossRatio());
        logger.logText("   - 非金融风险调整率: " + assumptions.getRaRatio());
        return assumptions;
    }

    private List<RateCurve> loadRates(CalculationLogger logger, String valMonthStr) {
        List<RateCurve> rates = ratesManagerService.getRates(valMonthStr);
        if (rates.isEmpty()) {
            throw new RuntimeException("未找到 " + valMonthStr + " 的利率曲线");
        }
        logger.logText("✅ 成功获取 " + valMonthStr + " 利率曲线 (" + rates.size() + " 条记录)");
        return rates;
    }
    
    private int calculateTotalContractMonths(PolicyState policyState) {
        if (policyState.getStartDate() == null || policyState.getEndDate() == null) return 1;
        Period diff = Period.between(policyState.getStartDate(), policyState.getEndDate());
        int months = diff.getYears() * 12 + diff.getMonths();
        if (months == 0 && policyState.getEndDate().isAfter(policyState.getStartDate())) {
            months = 1;
        }
        return Math.max(months, 1);
    }
    
    private int calculateMonthsBetween(LocalDate start, LocalDate end) {
        if (start == null || end == null || start.isAfter(end)) return 0;
        Period diff = Period.between(start, end);
        int months = diff.getYears() * 12 + diff.getMonths();
        if (end.getDayOfMonth() >= start.getDayOfMonth()) {
            months += 1;
        }
        return Math.max(months, 0);
    }
}
