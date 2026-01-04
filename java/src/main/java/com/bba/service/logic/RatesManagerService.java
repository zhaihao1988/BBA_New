package com.bba.service.logic;

import com.bba.entity.RateCurve;
import com.bba.model.CohortState;
import com.bba.service.DataLoaderService;
import com.bba.util.CalculationLogger;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class RatesManagerService {

    private final DataLoaderService dataLoaderService;

    public List<RateCurve> getRates(String valMonthStr) {
        return dataLoaderService.getRates(valMonthStr);
    }

    public List<RateCurve> getRates(String valMonthStr, String curveType) {
        // Currently ignoring curveType as we only have one curve per month in this simplified version
        // 目前忽略 curveType，因为在这个简化版本中我们每个月只有一条曲线
        return getRates(valMonthStr);
    }

    public BigDecimal calculateSpotRate(List<RateCurve> ratesDf) {
        if (ratesDf == null || ratesDf.isEmpty()) {
            return BigDecimal.ZERO;
        }
        // Simplify: use the first term's rate
        return ratesDf.get(0).getForwardDisrateValue();
    }

    public BigDecimal updateWeightedLockedRate(CohortState cohortState, BigDecimal newSpotRate, BigDecimal newWrittenPremium, CalculationLogger logger) {
        BigDecimal rOld = cohortState.getWeightedLockedRate();
        BigDecimal wOld = cohortState.getTotalWrittenPremium();
        
        BigDecimal rSpot = newSpotRate;
        BigDecimal wNew = newWrittenPremium;
        
        BigDecimal rNew;
        
        if (wOld.compareTo(BigDecimal.ZERO) == 0) {
            rNew = rSpot;
            if (logger != null) {
                Map<String, Object> vars = new HashMap<>();
                vars.put("R_spot", rSpot);
                vars.put("W_new", wNew);
                logger.logItem(
                    "加权初始确认利率更新（首单）",
                    "[Sec 1.5.2] 第一张单，直接使用即期利率",
                    "R_new = R_spot",
                    vars,
                    rNew,
                    "期初权重为0，无需加权"
                );
            }
        } else {
            BigDecimal numerator = rOld.multiply(wOld).add(rSpot.multiply(wNew));
            BigDecimal denominator = wOld.add(wNew);
            
            if (denominator.compareTo(BigDecimal.ZERO) > 0) {
                rNew = numerator.divide(denominator, 10, RoundingMode.HALF_UP); // High precision for intermediate
            } else {
                rNew = BigDecimal.ZERO;
            }
            
            if (logger != null) {
                Map<String, Object> vars = new HashMap<>();
                vars.put("R_old", rOld);
                vars.put("W_old", wOld);
                vars.put("R_spot", rSpot);
                vars.put("W_new", wNew);
                vars.put("Numerator", numerator);
                vars.put("Denominator", denominator);
                
                logger.logItem(
                    "加权初始确认利率更新",
                    "[Sec 1.5.2] 递归更新公式：R_new = (R_old * W_old + R_spot * W_new) / (W_old + W_new)",
                    "加权平均",
                    vars,
                    rNew,
                    String.format("期初存量保单权重: %,.2f, 新单权重: %,.2f", wOld, wNew)
                );
            }
        }
        
        cohortState.setWeightedLockedRate(rNew);
        cohortState.setTotalWrittenPremium(wOld.add(wNew));
        
        return rNew;
    }
}
