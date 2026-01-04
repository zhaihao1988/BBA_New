package com.bba.model;

import lombok.Data;
import java.math.BigDecimal;

@Data
public class CohortState {
    
    private String cohortId;
    
    private BigDecimal weightedLockedRate = BigDecimal.ZERO;
    private BigDecimal totalWrittenPremium = BigDecimal.ZERO;
    
    // Beginning of Period (BOP)
    private BigDecimal bopCsm = BigDecimal.ZERO;
    private BigDecimal bopLc = BigDecimal.ZERO;
    private BigDecimal bopIacf = BigDecimal.ZERO;
    
    // New Business
    private BigDecimal newCsm = BigDecimal.ZERO;
    private BigDecimal newLc = BigDecimal.ZERO;
    private BigDecimal newIacf = BigDecimal.ZERO;
    
    // Interest Accretion
    private BigDecimal csmInterest = BigDecimal.ZERO;
    private BigDecimal iacfInterest = BigDecimal.ZERO;
    
    // Absorbed Changes
    private BigDecimal csmAbsorbedChanges = BigDecimal.ZERO;
    private BigDecimal lcAbsorbedChanges = BigDecimal.ZERO;
    
    // Amortization
    private BigDecimal csmAmortization = BigDecimal.ZERO;
    private BigDecimal iacfAmortization = BigDecimal.ZERO;
    
    // End of Period (EOP)
    private BigDecimal eopCsm = BigDecimal.ZERO;
    private BigDecimal eopLc = BigDecimal.ZERO;
    private BigDecimal eopIacf = BigDecimal.ZERO;
    
    // IFIE (Cumulative)
    private BigDecimal ifiePlTotal = BigDecimal.ZERO;
    private BigDecimal ifieOciTotal = BigDecimal.ZERO;
    
    // Status
    private boolean isProfitable = true;
    private BigDecimal netTrial = BigDecimal.ZERO;
    
    private int monthsSinceInitial = 0;
    
    public void calculateEopBalances() {
        // EOP_CSM = BOP_CSM + New_CSM + CSM_Interest + CSM_Absorbed_Changes + CSM_Amortization
        this.eopCsm = bopCsm.add(newCsm).add(csmInterest)
                .add(csmAbsorbedChanges).add(csmAmortization);
        
        // EOP_LC logic from Python:
        // if eop_lc is 0 (not set by context yet) and bop_lc != 0, calculate simplified
        if (this.eopLc.compareTo(BigDecimal.ZERO) == 0 && this.bopLc.compareTo(BigDecimal.ZERO) != 0) {
             this.eopLc = bopLc.add(newLc).add(lcAbsorbedChanges);
        }
        
        // EOP_IACF
        if (this.eopIacf.compareTo(BigDecimal.ZERO) == 0) {
            this.eopIacf = bopIacf.add(newIacf).add(iacfAmortization);
        }
        
        this.netTrial = this.eopCsm.add(this.eopLc);
        this.isProfitable = this.netTrial.compareTo(BigDecimal.ZERO) >= 0;
    }
    
    public void rollForward() {
        this.bopCsm = this.eopCsm;
        this.bopLc = this.eopLc;
        this.bopIacf = this.eopIacf;
        
        this.newCsm = BigDecimal.ZERO;
        this.newLc = BigDecimal.ZERO;
        this.newIacf = BigDecimal.ZERO;
        this.csmInterest = BigDecimal.ZERO;
        this.iacfInterest = BigDecimal.ZERO;
        this.csmAbsorbedChanges = BigDecimal.ZERO;
        this.lcAbsorbedChanges = BigDecimal.ZERO;
        this.csmAmortization = BigDecimal.ZERO;
        this.iacfAmortization = BigDecimal.ZERO;
    }
}
