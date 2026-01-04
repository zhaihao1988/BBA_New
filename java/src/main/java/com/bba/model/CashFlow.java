package com.bba.model;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.LocalDate;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class CashFlow {
    private int year;
    private int month;
    private String yyyymm;
    private LocalDate date; // Added for convenience (first of month)
    
    private BigDecimal premium = BigDecimal.ZERO;
    private BigDecimal iacf = BigDecimal.ZERO;
    private BigDecimal claims = BigDecimal.ZERO;
    private BigDecimal expenses = BigDecimal.ZERO;
}
