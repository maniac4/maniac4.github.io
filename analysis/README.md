# 알파벳(GOOGL) 재무 구조 분석

SEC EDGAR 10-K XBRL 공시자료(Company Facts API, CIK 0001652044)를 받아 연도별 재무 구조를 분석합니다.

```bash
pip install -r requirements.txt
export SEC_USER_AGENT="이름 이메일주소"   # SEC 요구사항
python alphabet_financial_structure.py --years 5
python alphabet_financial_structure.py --offline   # 네트워크 없이 내장 참고 데이터로 실행
```

분석 항목: 자본 구조(부채비율·순현금), 유동성, 수익성(마진·ROE·ROA), 현금흐름(FCF·CapEx·주주환원), 자산 구성.
결과: `output/alphabet_raw.csv`, `output/alphabet_ratios.csv`, `output/alphabet_structure.png`
