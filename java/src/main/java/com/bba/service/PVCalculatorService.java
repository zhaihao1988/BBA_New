package com.bba.service;

import com.bba.entity.RateCurve;
import com.bba.model.CashFlow;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.MathContext;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Function;

@Service
@Slf4j
public class PVCalculatorService {

    private static final MathContext MC = MathContext.DECIMAL128;

    /**
     * Get forward rate for a specific term.
     * Extrapolate using the last available rate if term exceeds max_term.
     */
    private BigDecimal getMonthlyRate(Map<Integer, BigDecimal> ratesMap, int termMonth, int maxTerm) {
        if (termMonth <= 0) {
            return BigDecimal.ZERO;
        }
        if (termMonth > maxTerm) {
            return ratesMap.getOrDefault(maxTerm, BigDecimal.ZERO);
        }
        return ratesMap.getOrDefault(termMonth, BigDecimal.ZERO);
    }

    private Map<Integer, BigDecimal> prepareRatesMap(List<RateCurve> rates) {
        Map<Integer, BigDecimal> map = new HashMap<>();
        if (rates != null) {
            for (RateCurve rc : rates) {
                map.put(rc.getTermMonth(), rc.getForwardDisrateValue());
            }
        }
        return map;
    }

    private int getMaxTerm(List<RateCurve> rates) {
        if (rates == null || rates.isEmpty()) return 0;
        return rates.stream().mapToInt(RateCurve::getTermMonth).max().orElse(0);
    }

    private int getMonthDiff(LocalDate d1, LocalDate d2) {
        return (d1.getYear() - d2.getYear()) * 12 + (d1.getMonthValue() - d2.getMonthValue());
    }

    /**
     * Precise PV Calculation based on Date Differences.
     * Replicates Python's calculate_pv_exact
     */
    public BigDecimal calculatePvExact(
            List<CashFlow> cashFlows,
            Function<CashFlow, BigDecimal> valueExtractor,
            List<RateCurve> rates,
            LocalDate valuationDate,
            LocalDate curveBaseDate
    ) {
        BigDecimal totalPv = BigDecimal.ZERO;
        Map<Integer, BigDecimal> ratesMap = prepareRatesMap(rates);
        int maxTerm = getMaxTerm(rates);

        boolean isCurrentCurve = curveBaseDate.isEqual(valuationDate);

        // [FIX] Valuation Date Adjustment
        LocalDate valDateForCalc = valuationDate;
        if (valuationDate.getDayOfMonth() == 1) {
            valDateForCalc = valuationDate.minusDays(1);
        }

        for (CashFlow cf : cashFlows) {
            BigDecimal amount = valueExtractor.apply(cf);
            if (amount.compareTo(BigDecimal.ZERO) == 0) continue;

            // In CashFlow object, date is the first of the month.
            // Python cf_df['Date_Obj'] is also usually first of month (from projector).
            LocalDate cfDate = cf.getDate();

            if (cfDate.isEqual(valuationDate)) {
                totalPv = totalPv.add(amount);
                continue;
            }

            BigDecimal factor = BigDecimal.ONE;

            if (isCurrentCurve) {
                // Current curve: term_month starts from 1 (relative to valuation date)
                int monthsDiff = getMonthDiff(cfDate, valDateForCalc);

                if (monthsDiff > 0) {
                    // Discounting: Future -> Present
                    for (int t = 1; t <= monthsDiff; t++) {
                        BigDecimal r = getMonthlyRate(ratesMap, t, maxTerm);
                        factor = factor.divide(BigDecimal.ONE.add(r), MC);
                    }
                } else if (monthsDiff < 0) {
                    // Accumulation: Past -> Present
                    for (int t = 1; t <= Math.abs(monthsDiff); t++) {
                        BigDecimal r = getMonthlyRate(ratesMap, t, maxTerm);
                        factor = factor.multiply(BigDecimal.ONE.add(r), MC);
                    }
                }
            } else {
                // Locked curve: term_month = (cfDate - curveBaseDate) months
                int idxCf = getMonthDiff(cfDate, curveBaseDate);
                int idxVal = getMonthDiff(valDateForCalc, curveBaseDate);

                if (cfDate.isAfter(valuationDate)) {
                    // Discounting
                    if (idxCf == idxVal) {
                        // Same month
                        int term = idxCf + 1;
                        BigDecimal r = getMonthlyRate(ratesMap, term, maxTerm);
                        factor = factor.divide(BigDecimal.ONE.add(r), MC);
                    } else {
                        // Cross month
                        int startStep = Math.max(1, idxVal + 2);
                        int endStep = idxCf + 1;

                        for (int t = startStep; t <= endStep; t++) {
                            BigDecimal r = getMonthlyRate(ratesMap, t, maxTerm);
                            factor = factor.divide(BigDecimal.ONE.add(r), MC);
                        }
                    }
                } else if (cfDate.isBefore(valuationDate)) {
                    // Accumulation
                    int startStep = Math.max(1, idxCf + 1);
                    int endStep = idxVal;

                    for (int t = startStep; t <= endStep; t++) {
                        BigDecimal r = getMonthlyRate(ratesMap, t, maxTerm);
                        factor = factor.multiply(BigDecimal.ONE.add(r), MC);
                    }
                }
            }
            totalPv = totalPv.add(amount.multiply(factor, MC));
        }

        return totalPv;
    }

    /**
     * Initial Recognition PV Calculation (Discount to UW month mid).
     * Replicates Python's calculate_pv_initial_recognition
     */
    public BigDecimal calculatePvInitialRecognition(
            List<CashFlow> cashFlows,
            Function<CashFlow, BigDecimal> valueExtractor,
            boolean isPremiumOrIacf,
            List<RateCurve> rates,
            LocalDate curveBaseDate, // UW Date
            LocalDate uwDate // UW Date
    ) {
        BigDecimal totalPv = BigDecimal.ZERO;
        Map<Integer, BigDecimal> ratesMap = prepareRatesMap(rates);
        int maxTerm = getMaxTerm(rates);

        int uwYear = uwDate.getYear();
        int uwMonth = uwDate.getMonthValue();

        for (CashFlow cf : cashFlows) {
            BigDecimal amount = valueExtractor.apply(cf);
            if (amount.compareTo(BigDecimal.ZERO) == 0) continue;

            // [Assumption分支逻辑] 初始确认折现规则（对齐 pv_calculator_assumption.calculate_pv_initial_recognition）
            // - Premium/IACF：全程不折现（折现因子=1）
            // - Claims/Expenses：签单月及之后先折现半期（1/(1+r1/2)），之后每跨1个月再折现整期
            // - 签单月之前：视为已发生，取原值（不折现）

            if (isPremiumOrIacf) {
                totalPv = totalPv.add(amount);
                continue;
            }

            int monthsFromUw = (cf.getYear() - uwYear) * 12 + (cf.getMonth() - uwMonth);
            BigDecimal factor;

            if (monthsFromUw < 0) {
                factor = BigDecimal.ONE;
            } else {
                BigDecimal r1 = getMonthlyRate(ratesMap, 1, maxTerm);
                factor = BigDecimal.ONE.divide(BigDecimal.ONE.add(r1.divide(new BigDecimal("2"), MC)), MC);

                // monthsFromUw=0（签单月）：仅半期
                // monthsFromUw=1（下一月）：半期 + 第2期
                // monthsFromUw=n：半期 + 第2..(n+1)期
                for (int t = 2; t <= monthsFromUw + 1; t++) {
                    BigDecimal r = getMonthlyRate(ratesMap, t, maxTerm);
                    factor = factor.divide(BigDecimal.ONE.add(r), MC);
                }
            }

            totalPv = totalPv.add(amount.multiply(factor, MC));
        }
        return totalPv;
    }

    /**
     * Calculate PV for Current Period - End of Period (No Interest if occurred).
     * Replicates Python's calculate_pv_current_period_no_interest_after_occurrence
     */
    public BigDecimal calculatePvCurrentPeriodNoInterest(
            List<CashFlow> cashFlows,
            Function<CashFlow, BigDecimal> valueExtractor,
            List<RateCurve> rates,
            LocalDate valuationDate,
            LocalDate curveBaseDate
    ) {
        BigDecimal totalPv = BigDecimal.ZERO;
        Map<Integer, BigDecimal> ratesMap = prepareRatesMap(rates);
        int maxTerm = getMaxTerm(rates);
        boolean isCurrentCurve = curveBaseDate.isEqual(valuationDate);

        // [FIX] Valuation Date Adjustment
        LocalDate valDateForCalc = valuationDate;
        if (valuationDate.getDayOfMonth() == 1) {
            valDateForCalc = valuationDate.minusDays(1);
        }

        int valYear = valuationDate.getYear();
        int valMonth = valuationDate.getMonthValue();

        for (CashFlow cf : cashFlows) {
            BigDecimal amount = valueExtractor.apply(cf);
            if (amount.compareTo(BigDecimal.ZERO) == 0) continue;

            LocalDate cfDate = cf.getDate();
            
            // If CF occurred in or before valuation month, use original value
            if (cf.getYear() < valYear || (cf.getYear() == valYear && cf.getMonth() <= valMonth)) {
                totalPv = totalPv.add(amount);
            } else {
                // Future cash flow, discount to valuation date
                if (cfDate.isEqual(valuationDate)) {
                    totalPv = totalPv.add(amount);
                    continue;
                }

                BigDecimal factor = BigDecimal.ONE;

                if (isCurrentCurve) {
                    int monthsDiff = getMonthDiff(cfDate, valDateForCalc);
                    if (monthsDiff > 0) {
                        for (int t = 1; t <= monthsDiff; t++) {
                            BigDecimal r = getMonthlyRate(ratesMap, t, maxTerm);
                            factor = factor.divide(BigDecimal.ONE.add(r), MC);
                        }
                    }
                } else {
                    int idxCf = getMonthDiff(cfDate, curveBaseDate);
                    int idxVal = getMonthDiff(valDateForCalc, curveBaseDate);

                    if (idxCf < 0) {
                        factor = BigDecimal.ONE;
                    } else {
                        if (idxCf == idxVal) {
                            int term = idxCf + 1;
                            BigDecimal r = getMonthlyRate(ratesMap, term, maxTerm);
                            factor = factor.divide(BigDecimal.ONE.add(r), MC);
                        } else {
                            int startStep = Math.max(1, idxVal + 2);
                            int endStep = idxCf + 1;
                            for (int t = startStep; t <= endStep; t++) {
                                BigDecimal r = getMonthlyRate(ratesMap, t, maxTerm);
                                factor = factor.divide(BigDecimal.ONE.add(r), MC);
                            }
                        }
                    }
                }
                totalPv = totalPv.add(amount.multiply(factor, MC));
            }
        }
        return totalPv;
    }

    /**
     * Calculate Beg_Lcu PV (Discount to BOP using Locked Curve from Previous Year End).
     * Replicates Python's calculate_pv_beg_lcu
     */
    public BigDecimal calculatePvBegLcu(
            List<CashFlow> cashFlows,
            Function<CashFlow, BigDecimal> valueExtractor,
            List<RateCurve> rates,
            LocalDate bopDate
    ) {
        BigDecimal totalPv = BigDecimal.ZERO;
        Map<Integer, BigDecimal> ratesMap = prepareRatesMap(rates);
        int maxTerm = getMaxTerm(rates);

        // [FIX] BOP Date Adjustment
        // If bopDate is 1st of month, treat as end of previous month for diff calculation
        LocalDate bopDateForCalc = bopDate;
        if (bopDate.getDayOfMonth() == 1) {
            bopDateForCalc = bopDate.minusDays(1);
        }

        for (CashFlow cf : cashFlows) {
            BigDecimal amount = valueExtractor.apply(cf);
            if (amount.compareTo(BigDecimal.ZERO) == 0) continue;

            LocalDate cfDate = cf.getDate();

            // If cash flow date is BOP date, no discount
            if (cfDate.isEqual(bopDate)) {
                totalPv = totalPv.add(amount);
                continue;
            }

            int monthsDiff = getMonthDiff(cfDate, bopDateForCalc);
            BigDecimal factor = BigDecimal.ONE;

            if (monthsDiff > 0) {
                // Future: Discount
                for (int t = 1; t <= monthsDiff; t++) {
                    BigDecimal r = getMonthlyRate(ratesMap, t, maxTerm);
                    factor = factor.divide(BigDecimal.ONE.add(r), MC);
                }
            } else if (monthsDiff < 0) {
                // Past: Accumulate
                for (int t = 1; t <= Math.abs(monthsDiff); t++) {
                    BigDecimal r = getMonthlyRate(ratesMap, t, maxTerm);
                    factor = factor.multiply(BigDecimal.ONE.add(r), MC);
                }
            }

            totalPv = totalPv.add(amount.multiply(factor, MC));
        }

        return totalPv;
    }
}
