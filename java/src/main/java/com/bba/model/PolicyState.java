package com.bba.model;

import lombok.Data;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.temporal.ChronoUnit;

@Data
public class PolicyState {
    
    // Policy Basic Info
    private String policyNo;
    private LocalDate startDate;
    private LocalDate endDate;
    private LocalDate warrantyEndDate;
    private BigDecimal writtenPremium = BigDecimal.ZERO;
    
    // Time Dimension
    private LocalDate valuationDate;
    private int monthsPassed = 0;
    private int monthsRemaining = 0;
    
    // UPR
    private BigDecimal upr = BigDecimal.ZERO;
    
    // PV Cash Flows (using weighted initial recognition rate)
    private BigDecimal pvPremium = BigDecimal.ZERO;
    private BigDecimal pvIacf = BigDecimal.ZERO;
    private BigDecimal pvClaims = BigDecimal.ZERO;
    private BigDecimal pvMaintenance = BigDecimal.ZERO;
    private BigDecimal pvRa = BigDecimal.ZERO;
    
    // Coverage Units
    private BigDecimal coverageUnitsReleased = BigDecimal.ZERO;
    private BigDecimal coverageUnitsRemaining = BigDecimal.ZERO;
    
    // Initial Recognition State
    private BigDecimal initialCsm = BigDecimal.ZERO;
    private BigDecimal initialLc = BigDecimal.ZERO;
    
    public void calculateMonths() {
        if (startDate != null && endDate != null && valuationDate != null) {
            // Calculate months passed: (val_year - start_year) * 12 + (val_month - start_month)
            // Python logic: if day >= start_day, +1
            long monthsDiff = ChronoUnit.MONTHS.between(
                startDate.withDayOfMonth(1), 
                valuationDate.withDayOfMonth(1)
            );
            
            if (valuationDate.getDayOfMonth() >= startDate.getDayOfMonth()) {
                monthsDiff += 1;
            }
            this.monthsPassed = Math.max(0, (int) monthsDiff);
            
            // Total months
            long totalMonthsDiff = ChronoUnit.MONTHS.between(
                startDate.withDayOfMonth(1),
                endDate.withDayOfMonth(1)
            );
             // Python logic: relativedelta gives years/months. 
             // If exactly same month, 0. But if days > 0, it might be 1?
             // Python: delta_total = relativedelta(end, start) -> years * 12 + months.
             // if total_months == 0 and (end-start).days > 0 -> 1.
             
             // Let's mimic python relativedelta roughly.
             // Actually, the best way is to implement logic similar to python's relativedelta or just simple month diff.
             // Let's stick to the logic:
             // total_months = (end.year - start.year)*12 + (end.month - start.month)
            
            int totalMonths = (endDate.getYear() - startDate.getYear()) * 12 + (endDate.getMonthValue() - startDate.getMonthValue());
            if (totalMonths == 0 && endDate.isAfter(startDate)) {
                totalMonths = 1;
            }
            
            this.monthsRemaining = Math.max(0, totalMonths - this.monthsPassed);
        }
    }
}
