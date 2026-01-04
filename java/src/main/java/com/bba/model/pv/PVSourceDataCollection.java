package com.bba.model.pv;

import lombok.Data;
import lombok.NoArgsConstructor;
import java.util.HashMap;
import java.util.Map;

@Data
@NoArgsConstructor
public class PVSourceDataCollection {
    private String policyNo;
    private Map<String, PVSourceData> dataByMonth = new HashMap<>();
    
    public PVSourceDataCollection(String policyNo) {
        this.policyNo = policyNo;
    }
    
    public void addData(PVSourceData pvData) {
        if (!pvData.getPolicyNo().equals(this.policyNo)) {
            throw new IllegalArgumentException("Policy No mismatch: " + this.policyNo + " vs " + pvData.getPolicyNo());
        }
        this.dataByMonth.put(pvData.getValuationMonth(), pvData);
    }
    
    public PVSourceData getData(String valuationMonth) {
        return this.dataByMonth.get(valuationMonth);
    }
}
