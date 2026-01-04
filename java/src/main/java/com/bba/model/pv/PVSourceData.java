package com.bba.model.pv;

import com.alibaba.fastjson.annotation.JSONField;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.Map;

/**
 * PV Source Data Container
 * Stores all Present Value metrics for a specific valuation month.
 */
@Data
public class PVSourceData {
    @JSONField(name = "policy_no")
    private String policyNo;

    @JSONField(name = "valuation_month")
    private String valuationMonth;

    @JSONField(name = "valuation_date", format = "yyyy-MM-dd")
    private LocalDate valuationDate;

    @JSONField(name = "under_write_date", format = "yyyy-MM-dd")
    private LocalDate underWriteDate;

    // --- New Business (Nb) Fields ---

    // Initial Recognition (Ini) - Locked Rate (Lkd)
    @JSONField(name = "Pvfl_Nb_Ini_Cfa_Rec_Lkd_Pre_Amt")
    private BigDecimal pvNbIniCfaRecLkdPreAmt; // Premium

    @JSONField(name = "Pvfl_Nb_Ini_Cfa_Rec_Lkd_Acq_Amt")
    private BigDecimal pvNbIniCfaRecLkdAcqAmt; // Acquisition Cost (IACF)

    @JSONField(name = "Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt")
    private BigDecimal pvNbIniCfaRecLkdClaAmt; // Claims

    @JSONField(name = "Pvfl_Nb_Ini_Cfa_Rec_Lkd_Mtn_Amt")
    private BigDecimal pvNbIniCfaRecLkdMtnAmt; // Maintenance

    @JSONField(name = "Pvfl_Nb_Ini_Cfa_Rec_Lkd_Rad_Amt")
    private BigDecimal pvNbIniCfaRecLkdRadAmt; // RA

    // EOP - Weighted Locked Rate (Wlk)
    @JSONField(name = "Pvfl_Nb_Eop_Cfa_Rep_Wlk_Pre_Amt")
    private BigDecimal pvNbEopCfaRepWlkPreAmt;

    @JSONField(name = "Pvfl_Nb_Eop_Cfa_Rep_Wlk_Cla_Amt")
    private BigDecimal pvNbEopCfaRepWlkClaAmt;

    @JSONField(name = "Pvfl_Nb_Eop_Cfa_Rep_Wlk_Mtn_Amt")
    private BigDecimal pvNbEopCfaRepWlkMtnAmt;

    @JSONField(name = "Pvfl_Nb_Eop_Cfa_Rep_Wlk_Rad_Amt")
    private BigDecimal pvNbEopCfaRepWlkRadAmt;
    
    // EOP - Current Rate (Cur)
    @JSONField(name = "Pvfl_Nb_Eop_Cfa_Rep_Cur_Pre_Amt")
    private BigDecimal pvNbEopCfaRepCurPreAmt;

    @JSONField(name = "Pvfl_Nb_Eop_Cfa_Rep_Cur_Cla_Amt")
    private BigDecimal pvNbEopCfaRepCurClaAmt;

    @JSONField(name = "Pvfl_Nb_Eop_Cfa_Rep_Cur_Mtn_Amt")
    private BigDecimal pvNbEopCfaRepCurMtnAmt;

    @JSONField(name = "Pvfl_Nb_Eop_Cfa_Rep_Cur_Rad_Amt")
    private BigDecimal pvNbEopCfaRepCurRadAmt;

    // EOP - Current Period (Cca) - Wlk
    @JSONField(name = "Pvfl_Nb_Eop_Cca_Rep_Wlk_Cla_Amt")
    private BigDecimal pvNbEopCcaRepWlkClaAmt;

    @JSONField(name = "Pvfl_Nb_Eop_Cca_Rep_Wlk_Mtn_Amt")
    private BigDecimal pvNbEopCcaRepWlkMtnAmt;

    @JSONField(name = "Pvfl_Nb_Eop_Cca_Rep_Wlk_Rad_Amt")
    private BigDecimal pvNbEopCcaRepWlkRadAmt;

    // Initial at EOP (for Exp Adj)
    @JSONField(name = "Pvfl_Nb_Ini_Cfa_Rep_Wlk_Pre_Amt")
    private BigDecimal pvNbIniCfaRepWlkPreAmt;

    @JSONField(name = "Pvfl_Nb_Ini_Cca_Rep_Wlk_Pre_Amt")
    private BigDecimal pvNbIniCcaRepWlkPreAmt;

    @JSONField(name = "Pvfl_Nb_Ini_Cfa_Rep_Wlk_Acq_Amt")
    private BigDecimal pvNbIniCfaRepWlkAcqAmt;

    @JSONField(name = "Pvfl_Nb_Ini_Cca_Rep_Wlk_Acq_Amt")
    private BigDecimal pvNbIniCcaRepWlkAcqAmt;

    @JSONField(name = "Pvfl_Nb_Ini_Cca_Rep_Wlk_Cla_Amt")
    private BigDecimal pvNbIniCcaRepWlkClaAmt;

    @JSONField(name = "Pvfl_Nb_Ini_Cca_Rep_Wlk_Mtn_Amt")
    private BigDecimal pvNbIniCcaRepWlkMtnAmt;

    @JSONField(name = "Pvfl_Nb_Ini_Cca_Rep_Wlk_Rad_Amt")
    private BigDecimal pvNbIniCcaRepWlkRadAmt;

    @JSONField(name = "Pvfl_Nb_Eop_Cfa_Rep_Wlk_Acq_Amt")
    private BigDecimal pvNbEopCfaRepWlkAcqAmt;

    @JSONField(name = "Pvfl_Nb_Ini_Cfa_Rep_Wlk_Cla_Amt")
    private BigDecimal pvNbIniCfaRepWlkClaAmt;

    @JSONField(name = "Pvfl_Nb_Ini_Cfa_Rep_Wlk_Mtn_Amt")
    private BigDecimal pvNbIniCfaRepWlkMtnAmt;

    @JSONField(name = "Pvfl_Nb_Ini_Cfa_Rep_Wlk_Rad_Amt")
    private BigDecimal pvNbIniCfaRepWlkRadAmt;

    // --- In-Force (If) Fields ---

    // BOP - Last Current Rate (Lcu) - Beg (Beginning)
    @JSONField(name = "Pvfl_If_Bop_Cfa_Beg_Lcu_Cla_Amt")
    private BigDecimal pvIfBopCfaBegLcuClaAmt;

    @JSONField(name = "Pvfl_If_Bop_Cfa_Beg_Lcu_Mtn_Amt")
    private BigDecimal pvIfBopCfaBegLcuMtnAmt;

    @JSONField(name = "Pvfl_If_Bop_Cfa_Beg_Lcu_Rad_Amt")
    private BigDecimal pvIfBopCfaBegLcuRadAmt;

    // BOP - Weighted Locked Rate (Wlk) - Rep (Reporting)
    @JSONField(name = "Pvfl_If_Bop_Cfa_Rep_Wlk_Pre_Amt")
    private BigDecimal pvIfBopCfaRepWlkPreAmt;

    @JSONField(name = "Pvfl_If_Bop_Cfa_Rep_Wlk_Acq_Amt")
    private BigDecimal pvIfBopCfaRepWlkAcqAmt;

    @JSONField(name = "Pvfl_If_Bop_Cfa_Rep_Wlk_Cla_Amt")
    private BigDecimal pvIfBopCfaRepWlkClaAmt;

    @JSONField(name = "Pvfl_If_Bop_Cfa_Rep_Wlk_Mtn_Amt")
    private BigDecimal pvIfBopCfaRepWlkMtnAmt;
    
    @JSONField(name = "Pvfl_If_Bop_Cfa_Rep_Wlk_Rad_Amt")
    private BigDecimal pvIfBopCfaRepWlkRadAmt;

    @JSONField(name = "Pvfl_If_Bop_Cca_Rep_Wlk_Pre_Amt")
    private BigDecimal pvIfBopCcaRepWlkPreAmt;

    @JSONField(name = "Pvfl_If_Bop_Cca_Rep_Wlk_Acq_Amt")
    private BigDecimal pvIfBopCcaRepWlkAcqAmt;

    @JSONField(name = "Pvfl_If_Bop_Cca_Rep_Wlk_Cla_Amt")
    private BigDecimal pvIfBopCcaRepWlkClaAmt;

    @JSONField(name = "Pvfl_If_Bop_Cca_Rep_Wlk_Mtn_Amt")
    private BigDecimal pvIfBopCcaRepWlkMtnAmt;
    
    @JSONField(name = "Pvfl_If_Bop_Cca_Rep_Wlk_Rad_Amt")
    private BigDecimal pvIfBopCcaRepWlkRadAmt;

    // BOP - Weighted Locked Rate (Wlk) - Beg (Beginning)
    @JSONField(name = "Pvfl_If_Bop_Cfa_Beg_Wlk_Cla_Amt")
    private BigDecimal pvIfBopCfaBegWlkClaAmt;

    @JSONField(name = "Pvfl_If_Bop_Cfa_Beg_Wlk_Mtn_Amt")
    private BigDecimal pvIfBopCfaBegWlkMtnAmt;

    @JSONField(name = "Pvfl_If_Bop_Cfa_Beg_Wlk_Rad_Amt")
    private BigDecimal pvIfBopCfaBegWlkRadAmt;

    // EOP - Weighted Locked Rate (Wlk) - Rep
    @JSONField(name = "Pvfl_If_Eop_Cfa_Rep_Wlk_Pre_Amt")
    private BigDecimal pvIfEopCfaRepWlkPreAmt;

    @JSONField(name = "Pvfl_If_Eop_Cfa_Rep_Wlk_Acq_Amt")
    private BigDecimal pvIfEopCfaRepWlkAcqAmt;

    @JSONField(name = "Pvfl_If_Eop_Cfa_Rep_Wlk_Cla_Amt")
    private BigDecimal pvIfEopCfaRepWlkClaAmt;

    @JSONField(name = "Pvfl_If_Eop_Cfa_Rep_Wlk_Mtn_Amt")
    private BigDecimal pvIfEopCfaRepWlkMtnAmt;

    @JSONField(name = "Pvfl_If_Eop_Cfa_Rep_Wlk_Rad_Amt")
    private BigDecimal pvIfEopCfaRepWlkRadAmt;

    // EOP - Current Rate (Cur) - Rep
    @JSONField(name = "Pvfl_If_Eop_Cfa_Rep_Cur_Cla_Amt")
    private BigDecimal pvIfEopCfaRepCurClaAmt;

    @JSONField(name = "Pvfl_If_Eop_Cfa_Rep_Cur_Mtn_Amt")
    private BigDecimal pvIfEopCfaRepCurMtnAmt;

    @JSONField(name = "Pvfl_If_Eop_Cfa_Rep_Cur_Rad_Amt")
    private BigDecimal pvIfEopCfaRepCurRadAmt;
    
    // Metadata
    private Map<String, Object> metadata = new HashMap<>();
    
    // Dynamic fields storage (fallback)
    @JSONField(name = "pv_fields")
    private Map<String, BigDecimal> pvFields = new HashMap<>();

    // Helper to get field with fallback to map
    public BigDecimal getField(String key) {
        // Try to reflectively find the field if needed, or just use the map if the user populated it.
        // However, for performance and type safety, we prefer direct field access.
        // This method is for backward compatibility or dynamic access.
        if (pvFields.containsKey(key)) {
            return pvFields.get(key);
        }
        return BigDecimal.ZERO;
    }
    
    public BigDecimal getField(String key, BigDecimal defaultValue) {
         BigDecimal val = getField(key);
         return val != null ? val : defaultValue;
    }

    /**
     * Unpacks values from the pvFields map into the explicit class fields.
     * This allows us to use strong typing while still loading from the dynamic JSON structure.
     */
    public void unpack() {
        if (this.pvFields == null || this.pvFields.isEmpty()) {
            return;
        }
        
        // Nb - Ini
        this.pvNbIniCfaRecLkdPreAmt = this.pvFields.get("Pvfl_Nb_Ini_Cfa_Rec_Lkd_Pre_Amt");
        this.pvNbIniCfaRecLkdAcqAmt = this.pvFields.get("Pvfl_Nb_Ini_Cfa_Rec_Lkd_Acq_Amt");
        this.pvNbIniCfaRecLkdClaAmt = this.pvFields.get("Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt");
        this.pvNbIniCfaRecLkdMtnAmt = this.pvFields.get("Pvfl_Nb_Ini_Cfa_Rec_Lkd_Mtn_Amt");
        this.pvNbIniCfaRecLkdRadAmt = this.pvFields.get("Pvfl_Nb_Ini_Cfa_Rec_Lkd_Rad_Amt");
        
        // Nb - Eop
        this.pvNbEopCfaRepWlkPreAmt = this.pvFields.get("Pvfl_Nb_Eop_Cfa_Rep_Wlk_Pre_Amt");
        this.pvNbEopCfaRepWlkClaAmt = this.pvFields.get("Pvfl_Nb_Eop_Cfa_Rep_Wlk_Cla_Amt");
        this.pvNbEopCfaRepWlkMtnAmt = this.pvFields.get("Pvfl_Nb_Eop_Cfa_Rep_Wlk_Mtn_Amt");
        this.pvNbEopCfaRepWlkRadAmt = this.pvFields.get("Pvfl_Nb_Eop_Cfa_Rep_Wlk_Rad_Amt");
        
        this.pvNbEopCfaRepCurPreAmt = this.pvFields.get("Pvfl_Nb_Eop_Cfa_Rep_Cur_Pre_Amt");
        this.pvNbEopCfaRepCurClaAmt = this.pvFields.get("Pvfl_Nb_Eop_Cfa_Rep_Cur_Cla_Amt");
        this.pvNbEopCfaRepCurMtnAmt = this.pvFields.get("Pvfl_Nb_Eop_Cfa_Rep_Cur_Mtn_Amt");
        this.pvNbEopCfaRepCurRadAmt = this.pvFields.get("Pvfl_Nb_Eop_Cfa_Rep_Cur_Rad_Amt");
        
        this.pvNbEopCcaRepWlkClaAmt = this.pvFields.get("Pvfl_Nb_Eop_Cca_Rep_Wlk_Cla_Amt");
        this.pvNbEopCcaRepWlkMtnAmt = this.pvFields.get("Pvfl_Nb_Eop_Cca_Rep_Wlk_Mtn_Amt");
        this.pvNbEopCcaRepWlkRadAmt = this.pvFields.get("Pvfl_Nb_Eop_Cca_Rep_Wlk_Rad_Amt");

        this.pvNbIniCfaRepWlkPreAmt = this.pvFields.get("Pvfl_Nb_Ini_Cfa_Rep_Wlk_Pre_Amt");
        this.pvNbIniCcaRepWlkPreAmt = this.pvFields.get("Pvfl_Nb_Ini_Cca_Rep_Wlk_Pre_Amt");
        this.pvNbIniCfaRepWlkAcqAmt = this.pvFields.get("Pvfl_Nb_Ini_Cfa_Rep_Wlk_Acq_Amt");
        this.pvNbIniCcaRepWlkAcqAmt = this.pvFields.get("Pvfl_Nb_Ini_Cca_Rep_Wlk_Acq_Amt");
        this.pvNbIniCcaRepWlkClaAmt = this.pvFields.get("Pvfl_Nb_Ini_Cca_Rep_Wlk_Cla_Amt");
        this.pvNbIniCcaRepWlkMtnAmt = this.pvFields.get("Pvfl_Nb_Ini_Cca_Rep_Wlk_Mtn_Amt");

        // If - Bop
        this.pvIfBopCfaBegLcuClaAmt = this.pvFields.get("Pvfl_If_Bop_Cfa_Beg_Lcu_Cla_Amt");
        this.pvIfBopCfaBegLcuMtnAmt = this.pvFields.get("Pvfl_If_Bop_Cfa_Beg_Lcu_Mtn_Amt");
        this.pvIfBopCfaBegLcuRadAmt = this.pvFields.get("Pvfl_If_Bop_Cfa_Beg_Lcu_Rad_Amt");
        
        this.pvIfBopCfaRepWlkPreAmt = this.pvFields.get("Pvfl_If_Bop_Cfa_Rep_Wlk_Pre_Amt");
        this.pvIfBopCfaRepWlkAcqAmt = this.pvFields.get("Pvfl_If_Bop_Cfa_Rep_Wlk_Acq_Amt");
        this.pvIfBopCfaRepWlkClaAmt = this.pvFields.get("Pvfl_If_Bop_Cfa_Rep_Wlk_Cla_Amt");
        this.pvIfBopCfaRepWlkMtnAmt = this.pvFields.get("Pvfl_If_Bop_Cfa_Rep_Wlk_Mtn_Amt");
        this.pvIfBopCfaRepWlkRadAmt = this.pvFields.get("Pvfl_If_Bop_Cfa_Rep_Wlk_Rad_Amt");
        
        this.pvIfBopCcaRepWlkPreAmt = this.pvFields.get("Pvfl_If_Bop_Cca_Rep_Wlk_Pre_Amt");
        this.pvIfBopCcaRepWlkAcqAmt = this.pvFields.get("Pvfl_If_Bop_Cca_Rep_Wlk_Acq_Amt");
        this.pvIfBopCcaRepWlkClaAmt = this.pvFields.get("Pvfl_If_Bop_Cca_Rep_Wlk_Cla_Amt");
        this.pvIfBopCcaRepWlkMtnAmt = this.pvFields.get("Pvfl_If_Bop_Cca_Rep_Wlk_Mtn_Amt");
        this.pvIfBopCcaRepWlkRadAmt = this.pvFields.get("Pvfl_If_Bop_Cca_Rep_Wlk_Rad_Amt");
        
        this.pvIfBopCfaBegWlkClaAmt = this.pvFields.get("Pvfl_If_Bop_Cfa_Beg_Wlk_Cla_Amt");
        this.pvIfBopCfaBegWlkMtnAmt = this.pvFields.get("Pvfl_If_Bop_Cfa_Beg_Wlk_Mtn_Amt");
        this.pvIfBopCfaBegWlkRadAmt = this.pvFields.get("Pvfl_If_Bop_Cfa_Beg_Wlk_Rad_Amt");

        // If - Eop
        this.pvIfEopCfaRepWlkPreAmt = this.pvFields.get("Pvfl_If_Eop_Cfa_Rep_Wlk_Pre_Amt");
        this.pvIfEopCfaRepWlkAcqAmt = this.pvFields.get("Pvfl_If_Eop_Cfa_Rep_Wlk_Acq_Amt");
        this.pvIfEopCfaRepWlkClaAmt = this.pvFields.get("Pvfl_If_Eop_Cfa_Rep_Wlk_Cla_Amt");
        this.pvIfEopCfaRepWlkMtnAmt = this.pvFields.get("Pvfl_If_Eop_Cfa_Rep_Wlk_Mtn_Amt");
        this.pvIfEopCfaRepWlkRadAmt = this.pvFields.get("Pvfl_If_Eop_Cfa_Rep_Wlk_Rad_Amt");
        
        this.pvIfEopCfaRepCurClaAmt = this.pvFields.get("Pvfl_If_Eop_Cfa_Rep_Cur_Cla_Amt");
        this.pvIfEopCfaRepCurMtnAmt = this.pvFields.get("Pvfl_If_Eop_Cfa_Rep_Cur_Mtn_Amt");
        this.pvIfEopCfaRepCurRadAmt = this.pvFields.get("Pvfl_If_Eop_Cfa_Rep_Cur_Rad_Amt");
    }
}
