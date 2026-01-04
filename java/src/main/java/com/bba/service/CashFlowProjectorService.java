package com.bba.service;

import com.bba.entity.PolicyContract;
import com.bba.model.Assumptions;
import com.bba.model.CashFlow;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.MathContext;
import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.List;

@Service
@Slf4j
public class CashFlowProjectorService {

    /**
     * Build monthly cash flow series for a single policy.
     * Replicates logic from Python's CashFlowProjector.project_policy_flows
     */
    public List<CashFlow> projectPolicyFlows(PolicyContract policy, Assumptions assumptions) {
        BigDecimal premium = policy.getSumPremiumNoTax() != null ? policy.getSumPremiumNoTax() : BigDecimal.ZERO;
        // [Assumption分支逻辑] 使用精算假设表的获取费用率计算IACF，而不是使用保单表字段 iacf_amount
        BigDecimal acqRatio = (assumptions != null && assumptions.getAcquisitionExpenseRatio() != null)
                ? assumptions.getAcquisitionExpenseRatio()
                : BigDecimal.ZERO;
        BigDecimal iacfAmount = premium.multiply(acqRatio);

        LocalDate startDate = policy.getStartDate();
        LocalDate endDate = policy.getEndDate();
        LocalDate uwDate = policy.getUnderWriteDate();
        LocalDate warrantyEnd = policy.getWarrantyEndDate();

        if (startDate == null || endDate == null || uwDate == null) {
            throw new IllegalArgumentException("Missing required dates: Start Date, End Date, or Underwrite Date.");
        }
        
        // If warrantyEnd is null, default to startDate (though logic says warrantyEnd OR startDate)
        if (warrantyEnd == null) {
            warrantyEnd = startDate;
        }

        // timeline start ensures we capture pre-risk months (e.g., manufacturing warranty)
        LocalDate timelineStart = startDate.isBefore(uwDate) ? startDate : uwDate;
        
        // Determine risk period: only after warranty_end_date
        // Python: risk_start = warranty_end or start_date
        LocalDate riskStart = warrantyEnd;
        LocalDate riskEnd = endDate;
        
        // Month start dates
        LocalDate riskStartMonth = riskStart.withDayOfMonth(1);
        LocalDate riskEndMonth = riskEnd.withDayOfMonth(1);
        
        long coverageMonths = 0;
        // Logic from Python: _months_between(start, end) + 1
        // _months_between: (end.year - start.year) * 12 + (end.month - start.month)
        long monthsBetween = ChronoUnit.MONTHS.between(riskStartMonth, riskEndMonth);
        // ChronoUnit.MONTHS.between is inclusive of start, exclusive of end? No, it's full months between.
        // Let's stick to (endY - startY)*12 + (endM - startM) logic
        monthsBetween = (riskEndMonth.getYear() - riskStartMonth.getYear()) * 12L + (riskEndMonth.getMonthValue() - riskStartMonth.getMonthValue());
        coverageMonths = monthsBetween + 1;
        
        BigDecimal monthlyEarned = BigDecimal.ZERO;
        if (coverageMonths > 0) {
            monthlyEarned = premium.divide(new BigDecimal(coverageMonths), MathContext.DECIMAL128);
        }

        BigDecimal lossRatio = assumptions.getLossRatio() != null ? assumptions.getLossRatio() : BigDecimal.ZERO;
        BigDecimal claimExpRatio = assumptions.getIndirectClaimsExpenseRatio() != null ? assumptions.getIndirectClaimsExpenseRatio() : BigDecimal.ZERO;
        BigDecimal maintRatio = assumptions.getMaintenanceExpenseRatio() != null ? assumptions.getMaintenanceExpenseRatio() : BigDecimal.ZERO;

        List<CashFlow> cashFlows = new ArrayList<>();

        // Generate range of months from timelineStart to endDate
        LocalDate currentMonth = timelineStart.withDayOfMonth(1);
        LocalDate endMonth = endDate.withDayOfMonth(1);

        while (!currentMonth.isAfter(endMonth)) {
            String yyyymm = String.format("%04d%02d", currentMonth.getYear(), currentMonth.getMonthValue());
            
            BigDecimal premiumInflow = BigDecimal.ZERO;
            BigDecimal iacfOutflow = BigDecimal.ZERO;

            // Premium and IACF occur in Underwrite Month
            if (currentMonth.getYear() == uwDate.getYear() && currentMonth.getMonthValue() == uwDate.getMonthValue()) {
                premiumInflow = premium;
                iacfOutflow = iacfAmount;
            }

            boolean inRiskPeriod = !currentMonth.isBefore(riskStartMonth) && !currentMonth.isAfter(riskEndMonth);
            
            BigDecimal claims = BigDecimal.ZERO;
            BigDecimal expenses = BigDecimal.ZERO;

            if (inRiskPeriod && monthlyEarned.compareTo(BigDecimal.ZERO) > 0) {
                // claims = monthly_earned * loss_ratio * (1 + claim_exp_ratio)
                claims = monthlyEarned.multiply(lossRatio).multiply(BigDecimal.ONE.add(claimExpRatio));
                // expenses = monthly_earned * maint_ratio
                expenses = monthlyEarned.multiply(maintRatio);
            }

            CashFlow cf = new CashFlow(
                currentMonth.getYear(),
                currentMonth.getMonthValue(),
                yyyymm,
                currentMonth,
                premiumInflow,
                iacfOutflow,
                claims,
                expenses
            );
            cashFlows.add(cf);

            currentMonth = currentMonth.plusMonths(1);
        }

        return cashFlows;
    }
}
