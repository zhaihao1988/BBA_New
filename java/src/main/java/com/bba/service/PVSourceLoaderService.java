package com.bba.service;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONObject;
import com.bba.entity.PolicyContract;
import com.bba.model.pv.PVSourceData;
import com.bba.model.pv.PVSourceDataCollection;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.Map;

@Service
@Slf4j
@RequiredArgsConstructor
public class PVSourceLoaderService {

    private final DataLoaderService dataLoaderService;
    private final PVGeneratorService pvGeneratorService;

    /**
     * Generates PV Source Data for a policy by simulating the entire lifecycle.
     * Replicates the Python script's logic of generating PV data for each month.
     * 
     * @param policyNo The policy number
     * @param runDate The run date (YYYY-MM-DD) used for fetching policy data
     * @return A collection of PVSourceData for each month
     */
    public PVSourceDataCollection generatePvSourceData(String policyNo, String runDate) {
        log.info("Generating PV Source Data Collection for Policy: {}", policyNo);

        // 1. Load Policy
        PolicyContract policy = dataLoaderService.getPolicyData(policyNo, null, "BBA", runDate);
        if (policy == null) {
            log.error("❌ Policy not found: {}", policyNo);
            return null;
        }

        PVSourceDataCollection collection = new PVSourceDataCollection(policyNo);

        // 2. Determine Simulation Range
        // Start from Underwrite Date
        LocalDate startDate = policy.getUnderWriteDate();
        // End at Policy End Date (or extend if needed for runoff)
        // For now, we simulate until End Date.
        // In Python simulation, it runs for fixed years (e.g. 10 years).
        // Here we use End Date as a safe default for coverage period.
        LocalDate endDate = policy.getEndDate();
        
        // Ensure we cover the full range
        long monthsBetween = ChronoUnit.MONTHS.between(
            startDate.withDayOfMonth(1), 
            endDate.withDayOfMonth(1)
        ) + 1; // Inclusive

        log.info("Simulating {} months from {} to {}", monthsBetween, startDate, endDate);

        // 3. Loop and Generate
        for (int i = 0; i < monthsBetween; i++) {
            LocalDate valDate = startDate.plusMonths(i);
            // Adjust to End of Month?
            // Python simulation usually evaluates at month end.
            // But PVGeneratorService handles date logic.
            // Usually valuation is at EOP (e.g. 2023-01-31).
            LocalDate valDateEop = valDate.withDayOfMonth(valDate.lengthOfMonth());
            
            log.info("DEBUG: Generating PV data for date: {}", valDateEop);
            try {
                if (pvGeneratorService == null) {
                    log.error("FATAL: pvGeneratorService is null");
                    throw new NullPointerException("pvGeneratorService is null");
                }
                PVSourceData pvData = pvGeneratorService.generatePVSourceData(policy, valDateEop);
                if (pvData == null) {
                     log.error("DEBUG: pvData returned is null for {}", valDateEop);
                } else {
                     log.info("DEBUG: pvData generated for {}", valDateEop);
                }
                collection.addData(pvData);
            } catch (Exception e) {
                log.error("❌ Error generating PV data for {}: {}", valDateEop, e.getMessage(), e);
                // Continue or fail?
            }
        }
        
        log.info("✅ Generated {} PV records for Policy {}", collection.getDataByMonth().size(), policyNo);
        return collection;
    }

    /**
     * Legacy method to load from JSON file.
     * Kept for backward compatibility and testing.
     * 旧版方法：从 JSON 文件加载 PV 数据。
     * 保留此方法用于向后兼容和测试。
     */
    public PVSourceDataCollection loadPvSourceData(String policyNo, String jsonFilePath) {
        Path path;
        if (jsonFilePath == null) {
            // Default path: logs/pv_source_data_{policy_no}.json
            // 默认路径：logs/pv_source_data_{policy_no}.json
            path = Paths.get("logs", "pv_source_data_" + policyNo + ".json");
        } else {
            path = Paths.get(jsonFilePath);
        }

        if (!Files.exists(path)) {
             path = Paths.get(System.getProperty("user.dir"), "logs", "pv_source_data_" + policyNo + ".json");
             if (!Files.exists(path)) {
                 log.warn("⚠️ Warning: PV source data file not found at {}", path);
                 return null;
             }
        }

        try {
            // JDK 8 Compatible file reading
            // JDK 8 兼容的文件读取方式
            byte[] bytes = Files.readAllBytes(path);
            String content = new String(bytes, java.nio.charset.StandardCharsets.UTF_8);
            JSONObject jsonObject = JSON.parseObject(content);
            
            PVSourceDataCollection collection = new PVSourceDataCollection(jsonObject.getString("policy_no"));
            JSONObject dataByMonth = jsonObject.getJSONObject("data_by_month");
            
            for (String month : dataByMonth.keySet()) {
                JSONObject monthData = dataByMonth.getJSONObject(month);
                PVSourceData pvData = new PVSourceData();
                pvData.setPolicyNo(monthData.getString("policy_no"));
                pvData.setValuationMonth(monthData.getString("valuation_month"));
                pvData.setValuationDate(LocalDate.parse(monthData.getString("valuation_date")));
                pvData.setUnderWriteDate(LocalDate.parse(monthData.getString("under_write_date")));
                
                JSONObject pvFields = monthData.getJSONObject("pv_fields");
                for (String field : pvFields.keySet()) {
                    pvData.getPvFields().put(field, new BigDecimal(pvFields.getString(field)));
                }
                // Unpack fields to entity properties
                pvData.unpack();
                
                pvData.setMetadata(monthData.getJSONObject("metadata"));
                collection.addData(pvData);
            }
            
            return collection;
        } catch (IOException e) {
            log.error("❌ Error loading PV source data: {}", e.getMessage());
            return null;
        }
    }
}
