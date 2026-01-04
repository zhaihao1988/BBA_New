package com.bba.service;

import com.baomidou.dynamic.datasource.annotation.DS;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.bba.entity.ActuarialAssumption;
import com.bba.entity.PolicyContract;
import com.bba.entity.RateCurve;
import com.bba.mapper.ActuarialAssumptionMapper;
import com.bba.mapper.PolicyContractMapper;
import com.bba.mapper.RateCurveMapper;
import com.bba.model.Assumptions;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

@Service
@Slf4j
@RequiredArgsConstructor
@DS("pg_measure_platform") // Use measure platform as default, but tables in zh schema will be accessed via qualified name
public class DataLoaderService {

    private final PolicyContractMapper policyContractMapper;
    private final RateCurveMapper rateCurveMapper;
    private final ActuarialAssumptionMapper actuarialAssumptionMapper;

    // Caches
    private final Map<String, List<RateCurve>> ratesCache = new ConcurrentHashMap<>();
    private final Map<String, Assumptions> assumptionsCache = new ConcurrentHashMap<>();

    public PolicyContract getPolicyData(String policyNo, String certiNo, String valMethod, String runDate) {
        LambdaQueryWrapper<PolicyContract> query = new LambdaQueryWrapper<>();
        query.eq(PolicyContract::getPolicyNo, policyNo)
             .eq(PolicyContract::getValMethod, valMethod)
             .eq(PolicyContract::getRunDate, runDate);
        
        if (certiNo != null && !certiNo.isEmpty()) {
            query.eq(PolicyContract::getCertiNo, certiNo);
        } else {
            // certi_no IS NULL OR certi_no = ''
            query.and(w -> w.isNull(PolicyContract::getCertiNo).or().eq(PolicyContract::getCertiNo, ""));
        }
        
        query.last("LIMIT 1");
        
        return policyContractMapper.selectOne(query);
    }

    public List<RateCurve> getRates(String valMonthStr) {
        if (ratesCache.containsKey(valMonthStr)) {
            return ratesCache.get(valMonthStr);
        }

        LambdaQueryWrapper<RateCurve> query = new LambdaQueryWrapper<>();
        query.eq(RateCurve::getValMonth, valMonthStr)
             .orderByAsc(RateCurve::getTermMonth);
        
        List<RateCurve> rates = rateCurveMapper.selectList(query);
        if (rates.isEmpty()) {
            log.warn("⚠️ Warning: No rate curve data found for {}", valMonthStr);
        } else {
            ratesCache.put(valMonthStr, rates);
        }
        return rates;
    }

    public Assumptions getAssumptions(String classCode, String valMonthStr, String valMethod) {
        String cacheKey = classCode + "_" + valMonthStr + "_" + valMethod;
        if (assumptionsCache.containsKey(cacheKey)) {
            return assumptionsCache.get(cacheKey);
        }

        LambdaQueryWrapper<ActuarialAssumption> query = new LambdaQueryWrapper<>();
        query.eq(ActuarialAssumption::getClassCode, classCode)
             .eq(ActuarialAssumption::getValMonth, valMonthStr)
             .eq(ActuarialAssumption::getValMethod, valMethod)
             .last("LIMIT 1");

        ActuarialAssumption entity = actuarialAssumptionMapper.selectOne(query);
        if (entity == null) {
            log.warn("⚠️ Warning: No assumption data found for class {}, month {}, method {}", classCode, valMonthStr, valMethod);
            return null;
        }

        Assumptions assumptions = new Assumptions();
        assumptions.setValMonth(valMonthStr);
        assumptions.setClassCode(classCode);
        assumptions.setLossRatio(entity.getLossRatio());
        assumptions.setIndirectClaimsExpenseRatio(entity.getIndirectClaimsExpenseRatio());
        assumptions.setMaintenanceExpenseRatio(entity.getMaintenanceExpenseRatio());
        assumptions.setRaRatio(entity.getRaRatio());
        if (entity.getAcquisitionExpenseRatio() != null) {
            assumptions.setAcquisitionExpenseRatio(entity.getAcquisitionExpenseRatio());
        }

        assumptionsCache.put(cacheKey, assumptions);
        return assumptions;
    }

    /**
     * 简单批量获取前N条保单（用于批处理），按 policy_no 升序。
     */
    public List<PolicyContract> listPolicyLimited(int limit) {
        LambdaQueryWrapper<PolicyContract> query = new LambdaQueryWrapper<>();
        query.orderByAsc(PolicyContract::getPolicyNo);
        if (limit > 0) {
            query.last("LIMIT " + limit);
        }
        return policyContractMapper.selectList(query);
    }
}
