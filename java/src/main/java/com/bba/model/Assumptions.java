package com.bba.model;

import lombok.Data;
import lombok.AllArgsConstructor;
import lombok.NoArgsConstructor;
import java.math.BigDecimal;

@Data
@AllArgsConstructor
@NoArgsConstructor
public class Assumptions {
    private String valMonth;
    private String classCode;
    
    private BigDecimal lossRatio;
    private BigDecimal indirectClaimsExpenseRatio;
    private BigDecimal maintenanceExpenseRatio;
    private BigDecimal raRatio;
    
    private BigDecimal acquisitionExpenseRatio = new BigDecimal("0.20");
}
