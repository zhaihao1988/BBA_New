package com.jdyx.cx.measure.service.impl;

import cn.hutool.core.date.DateUtil;
import com.google.common.collect.Lists;
import com.jdyx.common.measure.constant.NumberConstant;
import com.jdyx.common.measure.tools.UtilsCommon;
import com.jdyx.cx.measure.service.MeasureBbaPeriodService;
import com.jdyx.measure.api.measure.domain.MeasureCfBasicData;
import com.jdyx.measure.api.measure.domain.MeasureConfBbaBeginPeriod;
import com.jdyx.measure.api.measure.domain.MeasureConfBbaCurrentPeriod;
import com.kevin.common.constant.StringConstant;
import com.kevin.common.utils.DateUtils;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Optional;

import static com.kevin.common.utils.DateUtils.YYYYMMDD;

/**
 * 直保Bba经过天数配置表_当期/期初Service实现类业务层处理
 */
@Slf4j
@RequiredArgsConstructor
@Service
public class MeasureBbaPeriodServiceImpl implements MeasureBbaPeriodService {
  /**
   * @param measureCfBasicDataList 计量基础数据
   * @return 期初经过天数配置list
   * @Author hzh
   * @date 2024/11/5
   */
  @Override
  public List<MeasureConfBbaBeginPeriod> setCxZbMeasureBbaBeginPeriod(List<MeasureCfBasicData> measureCfBasicDataList) {
    List<MeasureConfBbaBeginPeriod> measureConfBbaBeginPeriodList = Lists.newArrayList();
    Optional.ofNullable(measureCfBasicDataList).orElse(Lists.newArrayList()).forEach(entity -> {
      List<MeasureConfBbaBeginPeriod> measureConfBbaBeginPeriods = doBeginEvaluate(entity);
      measureConfBbaBeginPeriodList.addAll(measureConfBbaBeginPeriods);
    });
    return measureConfBbaBeginPeriodList;
  }

  /**
   * @param measureCfBasicDataList 计量基础数据
   * @return 当期经过天数配置list
   * @Author hzh
   * @date 2024/11/5
   */
  @Override
  public List<MeasureConfBbaCurrentPeriod> setCxZbMeasureBbaCurrentPeriod(List<MeasureCfBasicData> measureCfBasicDataList) {
    List<MeasureConfBbaCurrentPeriod> measureConfBbaCurrentPeriodList = Lists.newArrayList();
    Optional.ofNullable(measureCfBasicDataList).orElse(Lists.newArrayList()).forEach(entity -> {
      List<MeasureConfBbaCurrentPeriod> measureConfBbaCurrentPeriods = doCurrentEvaluate(entity);
      measureConfBbaCurrentPeriodList.addAll(measureConfBbaCurrentPeriods);
    });
    return measureConfBbaCurrentPeriodList;
  }

  /**
   * @param basicData 计量基础数据（单个计量单元编号）
   * @return 当期经过天数配置list（单个计量单元编号）
   * @Author hzh
   * @date 2024/11/5
   */
  public List<MeasureConfBbaCurrentPeriod> doCurrentEvaluate(MeasureCfBasicData basicData) {
    ArrayList<MeasureConfBbaCurrentPeriod> resList = new ArrayList<>();
    String valMonth = basicData.getValMonth();
    String unitId = basicData.getUnitId();
    String riskCode = basicData.getRiskCode();
    String evaluateDate = basicData.getEvaluateDate();
    String endDate = basicData.getEndDate();
    Long term = basicData.getTerm();

    //=((year(5.保险责任止期)-year(1.当期评估时点))*12+month(5.保险责任止期)-month(1.当期评估时点)
    int dutyMonth = DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(valMonth), DateUtils.parseDate(endDate));

    //=max(((year(4.保险评估起期)-year(1.当期评估时点))*12+month(4.保险评估起期)-month(1.当期评估时点),0)
    int warrantyPeriod = DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(valMonth), DateUtils.parseDate(evaluateDate)) >= NumberConstant.LONG_ZERO ?
      DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(valMonth), DateUtils.parseDate(evaluateDate)) : NumberConstant.LONG_ZERO.intValue();

    //=max(5.保险评估起期,1.当期评估时点)
    Date curValMonthEndDayAddOneDay = DateUtils.addDays(DateUtils.endMonth(valMonth), 1);
    String judgeMonth = DateUtil.compare(DateUtils.parseDate(evaluateDate), curValMonthEndDayAddOneDay) > NumberConstant.LONG_ZERO ?
        evaluateDate : DateUtils.parseDateToStr(YYYYMMDD, curValMonthEndDayAddOneDay);

    String currentValDate = DateUtils.parseDateToStr(YYYYMMDD,DateUtils.endMonth(valMonth));

    for (int i = 1; i <= dutyMonth + 1; i++) {
      MeasureConfBbaCurrentPeriod entity = new MeasureConfBbaCurrentPeriod();
      entity.setValMonth(valMonth);
      entity.setUnitId(unitId);
      entity.setRiskCode(riskCode);
      entity.setEvaluateDate(evaluateDate);
      entity.setEndDate(endDate);
      entity.setTerm(term);
      entity.setDutyMonth(dutyMonth);
      entity.setWarrantyPeriod(warrantyPeriod);
      entity.setJudgeMonth(judgeMonth);
      entity.setDutyPeriod(i);
      entity.setDutyPeriodValue(getDutyPeriodValue(i, dutyMonth, warrantyPeriod, judgeMonth, endDate, currentValDate));
      resList.add(entity);
    }
    return resList;
  }

  /**
   * @param basicData 计量基础数据（单个计量单元编号）
   * @return 期初经过天数配置list（单个计量单元编号）
   * @Author hzh
   * @date 2024/11/5
   */
  public List<MeasureConfBbaBeginPeriod> doBeginEvaluate(MeasureCfBasicData basicData) {
    ArrayList<MeasureConfBbaBeginPeriod> resList = new ArrayList<>();
    String valMonth = basicData.getValMonth();
    String unitId = basicData.getUnitId();
    String riskCode = basicData.getRiskCode();
    String startDate = basicData.getStartDate();
    String evaluateDate = basicData.getEvaluateDate();
    String endDate = basicData.getEndDate();
    String iniConfirm = basicData.getIniConfirm();
    Long term = basicData.getTerm();
    String whetherCurPolicy = basicData.getWhetherCurPolicy();

    //"如果是否当期新单=1,则=4.保险责任起期  min(4.保险责任起期,13.I17初始确认日期)
    //如果是否当期新单=0,则=date(year(1.当期评估时点),1,1)"
    String firstValMonth = whetherCurPolicy.equals(StringConstant.STRING_ONE) ?
      startDate.compareTo(iniConfirm) < 0 ? startDate : iniConfirm
      : whetherCurPolicy.equals(StringConstant.STRING_ZERO) ? DateUtils.beginYearMonth(valMonth, YYYYMMDD) : "";

    //((year(5.保险责任止期)-year(7.当期评估时点的期初评估时点))*12+month(5.保险责任止期)-month(7.当期评估时点的期初评估时点)
    int dutyMonth = DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(firstValMonth), DateUtils.parseDate(endDate));

    //max(((year(5.保险评估起期)-year(9.当期评估时点的期初评估时点))*12)+month(5.保险评估起期)-month(9.当期评估时点的期初评估时点),0)
    int warrantyPeriod = DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(firstValMonth), DateUtils.parseDate(evaluateDate)) >= NumberConstant.LONG_ZERO ?
      DateUtils.differenceMonthsMillisecond(DateUtils.parseDate(firstValMonth), DateUtils.parseDate(evaluateDate)) : NumberConstant.LONG_ZERO.intValue();

    // 如果8.是否当期新单=1.5.保险评估起期，否则 date(year(1.当期评估时点),1,1))
    String judgeMonth = whetherCurPolicy.equals(StringConstant.STRING_ONE) ? evaluateDate : DateUtils.beginYearMonth(valMonth, YYYYMMDD);

    for (int i = 1; i <= dutyMonth + 1; i++) {
      MeasureConfBbaBeginPeriod entity = new MeasureConfBbaBeginPeriod();
      entity.setValMonth(valMonth);
      entity.setUnitId(unitId);
      entity.setRiskCode(riskCode);
      entity.setStartDate(startDate);
      entity.setEvaluateDate(evaluateDate);
      entity.setEndDate(endDate);
      entity.setTerm(term);
      entity.setWhetherCurPolicy(whetherCurPolicy);
      entity.setFirstValMonth(firstValMonth);
      entity.setDutyMonth(dutyMonth);
      entity.setWarrantyPeriod(warrantyPeriod);
      entity.setJudgeMonth(judgeMonth);
      entity.setDutyPeriod(i);
      entity.setDutyPeriodValue(getDutyPeriodValue(i, dutyMonth, warrantyPeriod, judgeMonth, endDate, firstValMonth));
      resList.add(entity);
    }
    return resList;
  }

  /**
   * @param judgeMonth     判断时点
   * @param warrantyPeriod 保修期
   * @param dutyPeriod     责任期间
   * @param dutyMonth      责任月份
   * @param endDate        保险责任止期
   * @param evaluateDateString 评估时点 (起初或当期)
   * @return 该经过天数的值
   * @Author hzh
   * @date 2024/11/5
   *
   * "如果13.责任期间.>10.责任月份+1或13.责任期间<11.保修期+1，则为0
   * 如果11.保修期+1<=13.责任期间<=10.责任月份+1，则走以下逻辑：
   * ---如果10.责任月份=11.保修期，则直接为1；
   * ---如果10.责任月份>11.保修期，则走以下逻辑：
   * --------如果13.责任期间=11.保修期+1，等于((date(year(12.判断时点),month(12.判断时点)+13.责任期间,1))-12.判断时点)/(6.保险责任止期-12.判断时点+1)
   * --------如果11.保修期+1<13.责任期间<10.责任月份+1，等于((date(year(12.判断时点),month(12.判断时点)+13.责任期间,1)-1)-(date(year(12.判断时点),month(12.判断时点)+13.责任期间-1,1)-1))/(6.保险责任止期-12.判断时点+1)
   * --------如果13.责任期间=10.责任月份+1，等于(6.保险责任止期 - (date(year(6.保险责任止期),month(6.保险责任止期),1)-1))/(6.保险责任止期-12.判断时点+1)"
   *
   * "如果13.责任期间.>10.责任月份+1或13.责任期间<11.保修期+1，则为0
   * 如果11.保修期+1<=13.责任期间<=10.责任月份+1，则走以下逻辑：
   * ---如果10.责任月份=11.保修期，则直接为1；
   * ---如果10.责任月份>11.保修期，则走以下逻辑：
   * --------如果13.责任期间=11.保修期+1，等于((date(year(9.当期评估时点的期初评估时点),month(9.当期评估时点的期初评估时点)+13.责任期间,1))-12.判断时点)/(6.保险责任止期-12.判断时点+1)
   * --------如果11.保修期+1<13.责任期间<10.责任月份+1，等于((date(year(9.当期评估时点的期初评估时点),month(9.当期评估时点的期初评估时点)+13.责任期间,1)-1)-(date(year(9.当期评估时点的期初评估时点),month(9.当期评估时点的期初评估时点)+13.责任期间-1,1)-1))/(6.保险责任止期-12.判断时点+1)
   * --------如果13.责任期间=10.责任月份+1，等于(6.保险责任止期 - (date(year(6.保险责任止期),month(6.保险责任止期),1)-1))/(6.保险责任止期-12.判断时点+1)"
   */
  public String getDutyPeriodValue(int dutyPeriod, int dutyMonth, int warrantyPeriod, String judgeMonth, String endDate, String evaluateDateString) {
    // 评估时点 (起初或当期)
    Date evaluateDate = DateUtils.parseDate(evaluateDateString);
    int evaluateDateYear = DateUtil.year(evaluateDate);
    int evaluateDateMonth = DateUtil.month(evaluateDate);


    //下面新的日期计算，目的提前算出 求值公式中的 中间的日期值，便于后续求值公式简洁
    //旧判断时点 年，月，日
    int judgeMonthYear = DateUtil.year(DateUtils.parseDate(judgeMonth));
    int judgeMonthMonth = DateUtil.month(DateUtils.parseDate(judgeMonth)) + 1;


    Date now = DateUtils.parseDate(DateUtil.format(new Date(), YYYYMMDD));



    //新的判断时点 （为求值公式计算的中间值）
    //date(year(12.评估时点),month(12.评估时点)+责任期间,1)
    int newJudgeDateMonth1 = (evaluateDateMonth + dutyPeriod) % 12;
    int newJudgeDateYear1 = evaluateDateYear + (evaluateDateMonth + dutyPeriod) / 12;
    // Date newJudgeDate1 = DateUtils.setDays(DateUtils.setMonths(DateUtils.setYears(now, newJudgeDateYear1), newJudgeDateMonth1), 1);
    Date newJudgeDate1 = DateUtils.toDate( LocalDate.of(newJudgeDateYear1, newJudgeDateMonth1 + 1 , 1) );

    //date(year(12.评估时点),month(12.评估时点)+责任期间,1) -1
    Date newJudgeDate2 = DateUtils.addDays(newJudgeDate1, -1);

    //date(year(12.评估时点),month(12.评估时点)+责任期间-1,1)
    int newJudgeDateMonth4 = (evaluateDateMonth + dutyPeriod - 1) % 12;
    int newJudgeDateYear4 = evaluateDateYear + (evaluateDateMonth + dutyPeriod - 1) / 12;
    // Date newJudgeDate4 = DateUtils.setDays(DateUtils.setMonths(DateUtils.setYears(now, newJudgeDateYear4), newJudgeDateMonth4), 1);
    Date newJudgeDate4 = DateUtils.toDate( LocalDate.of(newJudgeDateYear4, newJudgeDateMonth4 + 1 , 1) );
    //date(year(12.评估时点),month(12.评估时点)+责任期间-1,1) -1
    Date newJudgeDate5 = DateUtils.addDays(newJudgeDate4, -1);


    //date(year(12.判断时点),month(12.判断时点)+责任期间,1)
    // int newJudgeMonthMonth2 = (judgeMonthMonth -1 + dutyPeriod) % 12;
    // int newJudgeMonthYear2 = judgeMonthYear + (judgeMonthMonth -1 + dutyPeriod) / 12;
    // Date newJudgeMonth2 = DateUtils.setDays(DateUtils.setMonths(DateUtils.setYears(now, newJudgeMonthYear2), newJudgeMonthMonth2), 1);
    // //date(year(12.判断时点),month(12.判断时点)+责任期间,1) - 1
    // Date newJudgeMonth5 = DateUtils.addDays(newJudgeMonth2, -1);

    //date(year(12.判断时点),month(12.判断时点)+责任期间-1,1)
    // int newJudgeMonthMonth3 = (judgeMonthMonth -1 + dutyPeriod - 1) % 12;
    // int newJudgeMonthYear3 = judgeMonthYear + (judgeMonthMonth -1 + dutyPeriod - 1) / 12;
    // Date newJudgeMonth3 = DateUtils.setDays(DateUtils.setMonths(DateUtils.setYears(now, newJudgeMonthYear3), newJudgeMonthMonth3), 1);
    // //date(year(12.判断时点),month(12.判断时点)+责任期间-1,1) -1
    // Date newJudgeMonth6 = DateUtils.addDays(newJudgeMonth3, -1);



    //新的保险责任止期 （为求值公式计算的中间值）
    //date(year(6.保险责任止期),month(6.保险责任止期),1) - 1
    Date newEndDate = DateUtils.addDays(DateUtils.beginMonth(DateUtils.parseDate(endDate)), -1);

    //保修期+1 <= 责任期间 <= 责任月份+1
    if (dutyPeriod >= warrantyPeriod + 1 && dutyPeriod <= dutyMonth + 1) {
      //保修期 = 责任月份
      if (dutyMonth == warrantyPeriod) {
        return StringConstant.STRING_ONE;
      }
      //责任期间 = 保修期 + 1
      if (dutyPeriod == warrantyPeriod + 1) {
        // ((date(year(9.评估时点),month(9.评估时点)+13.责任期间,1))-12.判断时点)/(6.保险责任止期-12.判断时点+1)
        int diff1 = UtilsCommon.differentDaysByMillisecond(newJudgeDate1, DateUtils.parseDate(judgeMonth));
        int diff2 = UtilsCommon.differentDaysByMillisecond(DateUtils.parseDate(endDate), DateUtils.parseDate(judgeMonth)) + 1;
        return String.valueOf(BigDecimal.valueOf(diff1).divide(BigDecimal.valueOf(diff2), 10, RoundingMode.HALF_UP));
      }
      //责任期间 = 责任月份 + 1
      if (dutyPeriod == dutyMonth + 1) {
        // (6.保险责任止期 - (date(year(6.保险责任止期),month(6.保险责任止期),1)-1))/(6.保险责任止期-12.判断时点+1)
        int diff1 = UtilsCommon.differentDaysByMillisecond(DateUtils.parseDate(endDate), newEndDate);
        int diff2 = UtilsCommon.differentDaysByMillisecond(DateUtils.parseDate(endDate), DateUtils.parseDate(judgeMonth)) + 1;
        return String.valueOf(BigDecimal.valueOf(diff1).divide(BigDecimal.valueOf(diff2), 10, RoundingMode.HALF_UP));
      }
      //保修期+1 < 责任期间 < 责任月份+1
      if (dutyPeriod > warrantyPeriod + 1 && dutyPeriod < dutyMonth + 1) {
        // ((date(year(9.评估时点),month(9.评估时点)+13.责任期间,1)-1)-(date(year(9.评估时点),month(9.评估时点)+13.责任期间-1,1)-1))/(6.保险责任止期-12.判断时点+1)
        int diff1 = UtilsCommon.differentDaysByMillisecond(newJudgeDate2, newJudgeDate5);
        int diff2 = UtilsCommon.differentDaysByMillisecond(DateUtils.parseDate(endDate), DateUtils.parseDate(judgeMonth)) + 1;
        return String.valueOf(BigDecimal.valueOf(diff1).divide(BigDecimal.valueOf(diff2), 10, RoundingMode.HALF_UP));
      }
    }
    return StringConstant.STRING_ZERO;
  }
}
