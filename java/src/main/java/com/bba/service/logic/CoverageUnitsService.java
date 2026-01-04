package com.bba.service.logic;

import com.bba.model.PolicyState;
import com.bba.util.CalculationLogger;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.MathContext;
import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
public class CoverageUnitsService {

    public BigDecimal calculateCoverageUnitsReleased(
            List<PolicyState> policies,
            LocalDate valuationDate,
            LocalDate startOfYear,
            CalculationLogger logger,
            boolean isInitialYear
    ) {
        BigDecimal cuReleased = BigDecimal.ZERO;

        for (PolicyState policy : policies) {
            if (policy.getEndDate().isBefore(startOfYear) || policy.getStartDate().isAfter(valuationDate)) {
                continue;
            }

            LocalDate warrantyEnd = policy.getWarrantyEndDate() != null ? policy.getWarrantyEndDate() : policy.getStartDate();
            boolean isInWarranty = valuationDate.isBefore(warrantyEnd);

            LocalDate serviceStart;
            if (isInitialYear) {
                serviceStart = warrantyEnd;
            } else {
                serviceStart = warrantyEnd.isAfter(startOfYear) ? warrantyEnd : startOfYear;
            }

            LocalDate serviceEnd = policy.getEndDate().isBefore(valuationDate) ? policy.getEndDate() : valuationDate;

            long serviceDays = 0;
            String note = "";

            if (isInWarranty) {
                serviceDays = 0;
                serviceStart = warrantyEnd;
                serviceEnd = valuationDate;
                note = String.format("评估日期（%s）在保修期内（保修结束日期：%s），服务天数为0", valuationDate, warrantyEnd);
            } else if (serviceEnd.isBefore(serviceStart)) {
                serviceDays = 0;
                note = String.format("服务止期（%s）早于服务起期（%s），服务天数为0", serviceEnd, serviceStart);
            } else {
                serviceDays = ChronoUnit.DAYS.between(serviceStart, serviceEnd) + 1; // Inclusive
                note = String.format("服务期间：%s 至 %s", serviceStart, serviceEnd);
            }

            BigDecimal coverageBase = policy.getWrittenPremium();
            BigDecimal policyCu = coverageBase.multiply(new BigDecimal(serviceDays));
            cuReleased = cuReleased.add(policyCu);

            if (logger != null) {
                Map<String, Object> meta = new HashMap<>();
                meta.put("保单号", policy.getPolicyNo());
                meta.put("签单保费", coverageBase);
                meta.put("服务天数", serviceDays);
                meta.put("服务起期", serviceStart);
                meta.put("服务止期", serviceEnd);
                meta.put("保修结束日期", warrantyEnd);
                meta.put("评估日期", valuationDate);

                logger.logItem(
                        "保单 " + policy.getPolicyNo() + " 覆盖单元释放",
                        "[Sec 8.2] 本期释放的覆盖单元",
                        "保额（或签单保费）× 服务天数",
                        meta,
                        policyCu,
                        note
                );
            }
        }

        if (logger != null) {
            Map<String, Object> meta = new HashMap<>();
            meta.put("保单数量", policies.size());
            logger.logItem(
                    "本期释放的覆盖单元合计",
                    "[Sec 8.2] CU_released = Σ(保额或签单保费 × 服务天数)",
                    "合同组内所有有效保单的覆盖单元之和",
                    meta,
                    cuReleased,
                    isInitialYear ? "首年包含起保日至评估日的累计服务（含追溯月份）" : "本期（当月）该合同组内所有有效保单释放的覆盖单元之和"
            );
        }

        return cuReleased;
    }

    public BigDecimal calculateCoverageUnitsRemaining(
            List<PolicyState> policies,
            LocalDate valuationDate,
            CalculationLogger logger
    ) {
        BigDecimal cuRemaining = BigDecimal.ZERO;

        for (PolicyState policy : policies) {
            if (!policy.getEndDate().isAfter(valuationDate)) {
                continue;
            }

            LocalDate warrantyEnd = policy.getWarrantyEndDate() != null ? policy.getWarrantyEndDate() : policy.getStartDate();
            boolean isInWarranty = valuationDate.isBefore(warrantyEnd);

            long remainingDays = 0;
            LocalDate serviceStartNote;
            String note;

            if (isInWarranty) {
                remainingDays = ChronoUnit.DAYS.between(warrantyEnd, policy.getEndDate()); // Inclusive? Python: (end - warranty).days
                // Python logic: (policy.end_date - warranty_end).days
                // If warranty_end is 2023-01-01 and end_date is 2023-01-02, days is 1.
                // Java between is exclusive of end date?
                // ChronoUnit.DAYS.between(start, end) calculates days between.
                // e.g. 1st to 2nd is 1 day. Matches Python.
                serviceStartNote = warrantyEnd;
                note = String.format("评估日期（%s）在保修期内（保修结束日期：%s），剩余服务天数从保修结束日期开始计算", valuationDate, warrantyEnd);
            } else {
                remainingDays = ChronoUnit.DAYS.between(valuationDate, policy.getEndDate());
                serviceStartNote = valuationDate;
                note = String.format("评估日期（%s）在保修期后，剩余服务天数从评估日期开始计算", valuationDate);
            }

            if (remainingDays <= 0) {
                continue;
            }

            BigDecimal coverageBase = policy.getWrittenPremium();
            BigDecimal policyCu = coverageBase.multiply(new BigDecimal(remainingDays));
            cuRemaining = cuRemaining.add(policyCu);

            if (logger != null) {
                Map<String, Object> meta = new HashMap<>();
                meta.put("保单号", policy.getPolicyNo());
                meta.put("签单保费", coverageBase);
                meta.put("剩余服务天数", remainingDays);
                meta.put("保单止期", policy.getEndDate());
                meta.put("评估日期", valuationDate);
                meta.put("保修结束日期", warrantyEnd);
                meta.put("服务起算日期", serviceStartNote);

                logger.logItem(
                        "保单 " + policy.getPolicyNo() + " 剩余覆盖单元",
                        "[Sec 8.2] 期末剩余服务期的覆盖单元",
                        "保额（或签单保费）× 剩余服务天数",
                        meta,
                        policyCu,
                        note
                );
            }
        }

        if (logger != null) {
            Map<String, Object> meta = new HashMap<>();
            meta.put("保单数量", policies.size());
            logger.logItem(
                    "期末剩余服务期的覆盖单元合计",
                    "[Sec 8.2] CU_remaining = Σ(保额或签单保费 × 剩余服务天数)",
                    "合同组内所有有效保单的剩余覆盖单元之和",
                    meta,
                    cuRemaining,
                    "期末时点，该合同组内所有有效保单剩余服务期的覆盖单元之和"
            );
        }

        return cuRemaining;
    }
}
