import type { StatementRow, StatementRunStatus, StatementWorkbookSnapshot } from "./statementContract.ts";

/**
 * Fixed synthetic-only statement fixtures for the existing FINCO Design preview.
 * These rows are display data, not calculated or reconciled financial statements.
 */
const annualPeriods = ["2027", "2028", "2029", "2030", "2031", "2032", "2033", "2034"];
const modelPeriods = ["2026 M10", "2026 M12", "2027 Q3", "2027 Q4", "2028 Q1", "2028 Q2", "2029 6M", "2030 6M"];
const periodBands = [
  { label: "Construction snapshots", span: 2 },
  { label: "Operating quarter snapshots", span: 4 },
  { label: "Operating half-year snapshots", span: 2 },
];

const row = (
  id: string,
  label: string,
  annual: string[],
  model: string[],
  kind: StatementRow["kind"] = "metric",
  children?: StatementRow[],
): StatementRow => ({ id, label, annual, model, kind, children });

const plRows: StatementRow[] = [
  row("revenue", "Revenue", ["13.1", "15.2", "15.4", "15.6", "15.7", "15.9", "16.0", "16.2"], ["—", "—", "3.8", "3.9", "4.0", "4.0", "8.1", "8.2"], "section", [
    row("ppa-revenue", "PPA revenue", ["10.8", "12.1", "12.2", "12.4", "12.5", "12.6", "12.7", "12.8"], ["—", "—", "3.1", "3.1", "3.2", "3.2", "6.4", "6.5"], "detail"),
    row("merchant-revenue", "Merchant revenue", ["2.3", "3.1", "3.2", "3.2", "3.2", "3.3", "3.3", "3.4"], ["—", "—", "0.7", "0.8", "0.8", "0.8", "1.7", "1.7"], "detail"),
  ]),
  row("opex", "Operating expenses", ["(1.8)", "(1.7)", "(1.8)", "(1.8)", "(1.9)", "(1.9)", "(2.0)", "(2.0)"], ["—", "—", "(0.5)", "(0.5)", "(0.5)", "(0.5)", "(1.0)", "(1.0)"], "section", [
    row("site-costs", "Site & lease costs", ["(0.6)", "(0.6)", "(0.6)", "(0.6)", "(0.6)", "(0.6)", "(0.7)", "(0.7)"], ["—", "—", "(0.2)", "(0.2)", "(0.2)", "(0.2)", "(0.3)", "(0.3)"], "detail"),
    row("service-costs", "Operations & maintenance", ["(1.2)", "(1.1)", "(1.2)", "(1.2)", "(1.3)", "(1.3)", "(1.3)", "(1.3)"], ["—", "—", "(0.3)", "(0.3)", "(0.3)", "(0.3)", "(0.7)", "(0.7)"], "detail"),
  ]),
  row("ebitda", "EBITDA", ["11.3", "13.5", "13.6", "13.8", "13.8", "14.0", "14.0", "14.2"], ["—", "—", "3.3", "3.4", "3.5", "3.5", "7.1", "7.2"], "metric"),
  row("depreciation", "Depreciation & amortisation", ["(4.8)", "(4.8)", "(4.9)", "(4.9)", "(4.9)", "(5.0)", "(5.0)", "(5.0)"], ["—", "—", "(1.2)", "(1.2)", "(1.2)", "(1.2)", "(2.5)", "(2.5)"], "section", [
    row("depreciation-detail", "Property, plant & equipment", ["(4.6)", "(4.6)", "(4.7)", "(4.7)", "(4.7)", "(4.8)", "(4.8)", "(4.8)"], ["—", "—", "(1.2)", "(1.2)", "(1.2)", "(1.2)", "(2.4)", "(2.4)"], "detail"),
    row("amortisation", "Intangible assets", ["(0.2)", "(0.2)", "(0.2)", "(0.2)", "(0.2)", "(0.2)", "(0.2)", "(0.2)"], ["—", "—", "(0.0)", "(0.0)", "(0.0)", "(0.0)", "(0.1)", "(0.1)"], "detail"),
  ]),
  row("ebit", "Operating profit (EBIT)", ["6.5", "8.7", "8.7", "8.9", "8.9", "9.0", "9.0", "9.2"], ["—", "—", "2.1", "2.2", "2.3", "2.3", "4.6", "4.7"], "metric"),
  row("finance-cost", "Finance costs", ["(4.1)", "(3.8)", "(3.5)", "(3.2)", "(2.9)", "(2.6)", "(2.3)", "(2.0)"], ["—", "—", "(1.0)", "(0.9)", "(0.9)", "(0.8)", "(1.7)", "(1.5)"], "section", [
    row("interest-expense", "Interest expense", ["(3.8)", "(3.5)", "(3.2)", "(2.9)", "(2.6)", "(2.4)", "(2.1)", "(1.8)"], ["—", "—", "(0.9)", "(0.8)", "(0.8)", "(0.7)", "(1.5)", "(1.3)"], "detail"),
    row("fees-amortised", "Fees amortised", ["(0.3)", "(0.3)", "(0.3)", "(0.3)", "(0.3)", "(0.2)", "(0.2)", "(0.2)"], ["—", "—", "(0.1)", "(0.1)", "(0.1)", "(0.1)", "(0.2)", "(0.2)"], "detail"),
  ]),
  row("pbt", "Profit before tax", ["2.4", "4.9", "5.2", "5.7", "6.0", "6.4", "6.7", "7.2"], ["—", "—", "1.1", "1.3", "1.4", "1.5", "2.9", "3.2"], "metric"),
  row("tax", "Income tax expense", ["(0.6)", "(1.2)", "(1.3)", "(1.4)", "(1.5)", "(1.6)", "(1.7)", "(1.8)"], ["—", "—", "(0.3)", "(0.3)", "(0.3)", "(0.4)", "(0.7)", "(0.8)"], "metric"),
  row("net-income", "Net income", ["1.8", "3.7", "3.9", "4.3", "4.5", "4.8", "5.0", "5.4"], ["—", "—", "0.8", "1.0", "1.1", "1.1", "2.2", "2.4"], "metric"),
];

const balanceRows: StatementRow[] = [
  row("assets", "Total assets", ["102.6", "98.9", "95.7", "92.8", "90.1", "87.7", "85.4", "83.3"], ["104.3", "106.8", "105.9", "104.8", "102.9", "101.3", "98.1", "95.4"], "section", [
    row("cash", "Cash & cash equivalents", ["4.3", "4.8", "5.1", "5.4", "5.8", "6.1", "6.5", "6.9"], ["12.8", "15.1", "14.7", "14.1", "13.9", "13.5", "12.6", "11.8"], "detail"),
    row("receivables", "Trade receivables", ["1.7", "1.9", "1.9", "2.0", "2.0", "2.1", "2.1", "2.2"], ["—", "—", "0.5", "0.5", "0.5", "0.5", "1.0", "1.0"], "detail"),
    row("ppe", "Property, plant & equipment", ["96.6", "92.2", "88.7", "85.4", "82.3", "79.5", "76.8", "74.2"], ["91.5", "91.7", "90.7", "89.6", "87.7", "86.1", "83.7", "81.5"], "detail"),
  ]),
  row("liabilities", "Total liabilities", ["69.8", "65.4", "60.6", "55.9", "51.1", "46.5", "41.9", "37.2"], ["58.1", "69.2", "68.5", "67.7", "65.2", "62.9", "58.6", "54.1"], "section", [
    row("debt-balance", "Borrowings", ["64.8", "60.2", "55.5", "50.8", "46.1", "41.5", "36.8", "32.1"], ["51.2", "62.0", "61.2", "60.3", "57.7", "55.2", "50.7", "46.1"], "detail"),
    row("payables", "Trade & other payables", ["5.0", "5.2", "5.1", "5.1", "5.0", "5.0", "5.1", "5.1"], ["6.9", "7.2", "7.3", "7.4", "7.5", "7.7", "7.9", "8.0"], "detail"),
  ]),
  row("equity", "Total shareholders’ equity", ["32.8", "33.5", "35.1", "36.9", "39.0", "41.2", "43.5", "46.1"], ["46.2", "37.6", "37.4", "37.1", "37.7", "38.4", "39.5", "41.3"], "section", [
    row("share-capital", "Share capital & premium", ["37.8", "37.8", "37.8", "37.8", "37.8", "37.8", "37.8", "37.8"], ["37.8", "37.8", "37.8", "37.8", "37.8", "37.8", "37.8", "37.8"], "detail"),
    row("retained", "Retained earnings", ["(5.0)", "(4.3)", "(2.7)", "(0.9)", "1.2", "3.4", "5.7", "8.3"], ["8.4", "(0.2)", "(0.4)", "(0.7)", "(0.1)", "0.6", "1.7", "3.5"], "detail"),
  ]),
  row("balance-check", "Balance check · NOT EVALUATED", Array(8).fill("NOT EVALUATED"), Array(8).fill("NOT EVALUATED"), "metric"),
];

const cashflowRows: StatementRow[] = [
  row("operating-cf", "Net cash from operating activities", ["8.9", "10.9", "11.1", "11.3", "11.4", "11.6", "11.7", "11.9"], ["—", "—", "2.7", "2.8", "2.9", "2.9", "5.9", "6.0"], "section", [
    row("cash-receipts", "Cash receipts from customers", ["13.0", "15.1", "15.3", "15.5", "15.6", "15.8", "15.9", "16.1"], ["—", "—", "3.8", "3.9", "4.0", "4.0", "8.0", "8.1"], "detail"),
    row("cash-operating", "Operating cash costs", ["(1.8)", "(1.7)", "(1.8)", "(1.8)", "(1.9)", "(1.9)", "(2.0)", "(2.0)"], ["—", "—", "(0.5)", "(0.5)", "(0.5)", "(0.5)", "(1.0)", "(1.0)"], "detail"),
    row("cash-tax-interest", "Tax & working capital movements", ["(2.3)", "(2.5)", "(2.4)", "(2.4)", "(2.3)", "(2.3)", "(2.2)", "(2.2)"], ["—", "—", "(0.6)", "(0.6)", "(0.6)", "(0.6)", "(1.1)", "(1.1)"], "detail"),
  ]),
  row("investing-cf", "Net cash from investing activities", ["—", "—", "—", "—", "—", "—", "—", "—"], ["(7.2)", "(3.1)", "—", "—", "—", "—", "—", "—"], "section", [
    row("capex", "Construction & capital expenditure", ["—", "—", "—", "—", "—", "—", "—", "—"], ["(7.0)", "(3.0)", "—", "—", "—", "—", "—", "—"], "detail"),
    row("reserve-funding", "Reserve funding & other", ["—", "—", "—", "—", "—", "—", "—", "—"], ["(0.2)", "(0.1)", "—", "—", "—", "—", "—", "—"], "detail"),
  ]),
  row("financing-cf", "Net cash from financing activities", ["(8.4)", "(10.4)", "(10.8)", "(11.0)", "(11.0)", "(11.2)", "(11.3)", "(11.5)"], ["15.4", "5.5", "(3.5)", "(3.7)", "(3.1)", "(3.3)", "(6.4)", "(6.6)"], "section", [
    row("debt-cf", "Debt draw / (repayment)", ["(4.6)", "(4.7)", "(4.7)", "(4.7)", "(4.7)", "(4.7)", "(4.7)", "(4.7)"], ["14.2", "5.2", "(2.4)", "(2.5)", "(2.2)", "(2.3)", "(4.5)", "(4.6)"], "detail"),
    row("equity-cf", "Sponsor contribution / (distribution)", ["(3.8)", "(5.7)", "(6.1)", "(6.3)", "(6.3)", "(6.5)", "(6.6)", "(6.8)"], ["1.2", "0.3", "(1.1)", "(1.2)", "(0.9)", "(1.0)", "(1.9)", "(2.0)"], "detail"),
  ]),
  row("net-change", "Net change in cash", ["0.5", "0.5", "0.3", "0.3", "0.4", "0.4", "0.4", "0.4"], ["8.2", "2.4", "(0.8)", "(0.9)", "(0.2)", "(0.4)", "(0.5)", "(0.6)"], "metric"),
  row("cash-opening", "Cash at beginning of period", ["3.8", "4.3", "4.8", "5.1", "5.4", "5.8", "6.1", "6.5"], ["4.6", "12.8", "15.1", "14.7", "14.1", "13.9", "13.5", "12.6"], "metric"),
  row("cash-closing", "Cash at end of period", ["4.3", "4.8", "5.1", "5.4", "5.8", "6.1", "6.5", "6.9"], ["12.8", "15.1", "14.7", "14.1", "13.9", "13.5", "12.6", "11.8"], "metric"),
];

const cfadsRows: StatementRow[] = [
  row("cfads-ebitda", "EBITDA", ["11.3", "13.5", "13.6", "13.8", "13.8", "14.0", "14.0", "14.2"], ["—", "—", "3.3", "3.4", "3.5", "3.5", "7.1", "7.2"], "section", [
    row("cfads-revenue", "Revenue", ["13.1", "15.2", "15.4", "15.6", "15.7", "15.9", "16.0", "16.2"], ["—", "—", "3.8", "3.9", "4.0", "4.0", "8.1", "8.2"], "detail"),
    row("cfads-costs", "Operating costs", ["(1.8)", "(1.7)", "(1.8)", "(1.8)", "(1.9)", "(1.9)", "(2.0)", "(2.0)"], ["—", "—", "(0.5)", "(0.5)", "(0.5)", "(0.5)", "(1.0)", "(1.0)"], "detail"),
  ]),
  row("cash-tax", "Cash tax", ["(0.6)", "(1.2)", "(1.3)", "(1.4)", "(1.5)", "(1.6)", "(1.7)", "(1.8)"], ["—", "—", "(0.3)", "(0.3)", "(0.3)", "(0.4)", "(0.7)", "(0.8)"], "metric"),
  row("working-capital", "Working capital movement", ["(0.2)", "(0.1)", "0.0", "0.0", "(0.1)", "0.0", "0.0", "(0.1)"], ["—", "—", "(0.1)", "0.0", "0.0", "(0.1)", "(0.1)", "0.0"], "metric"),
  row("reserve-movement", "Reserve movements", ["(2.1)", "(1.6)", "(1.4)", "(1.4)", "(1.0)", "(1.0)", "(0.7)", "(0.5)"], ["—", "—", "(0.3)", "(0.4)", "(0.3)", "(0.3)", "(0.4)", "(0.3)"], "section", [
    row("dsra", "Debt service reserve movement", ["(1.4)", "(0.8)", "(0.8)", "(0.8)", "(0.5)", "(0.5)", "(0.3)", "(0.2)"], ["—", "—", "(0.2)", "(0.2)", "(0.2)", "(0.2)", "(0.2)", "(0.1)"], "detail"),
    row("maintenance-reserve", "Maintenance reserve movement", ["(0.7)", "(0.8)", "(0.6)", "(0.6)", "(0.5)", "(0.5)", "(0.4)", "(0.3)"], ["—", "—", "(0.1)", "(0.2)", "(0.1)", "(0.1)", "(0.2)", "(0.2)"], "detail"),
  ]),
  row("cfads-total", "Cash flow available for debt service", ["8.4", "10.6", "10.9", "11.0", "11.2", "11.4", "11.6", "11.8"], ["—", "—", "2.6", "2.7", "2.8", "2.7", "5.9", "6.1"], "metric"),
  row("scheduled-service", "Scheduled debt service", ["(6.7)", "(8.4)", "(8.5)", "(8.6)", "(8.7)", "(8.9)", "(9.0)", "(9.2)"], ["—", "—", "(2.0)", "(2.1)", "(2.2)", "(2.2)", "(4.4)", "(4.6)"], "section", [
    row("principal-service", "Principal", ["(2.9)", "(4.6)", "(4.7)", "(4.7)", "(4.8)", "(4.9)", "(5.0)", "(5.2)"], ["—", "—", "(1.1)", "(1.2)", "(1.2)", "(1.3)", "(2.5)", "(2.6)"], "detail"),
    row("interest-service", "Interest & recurring fees", ["(3.8)", "(3.8)", "(3.8)", "(3.9)", "(3.9)", "(4.0)", "(4.0)", "(4.0)"], ["—", "—", "(0.9)", "(0.9)", "(1.0)", "(0.9)", "(1.9)", "(2.0)"], "detail"),
  ]),
  row("dscr", "Debt service coverage ratio (x)", ["1.25", "1.26", "1.28", "1.28", "1.29", "1.28", "1.29", "1.28"], ["—", "—", "1.30", "1.29", "1.27", "1.24", "1.34", "1.33"], "metric"),
  row("cash-equity", "Cash flow to equity", ["1.1", "1.7", "1.8", "1.8", "1.9", "1.9", "2.0", "2.0"], ["—", "—", "0.6", "0.6", "0.6", "0.5", "1.5", "1.5"], "metric"),
];

const seniorDebtRows: StatementRow[] = [
  row("senior-draw", "Senior facility drawdown", ["—", "—", "—", "—", "—", "—", "—", "—"], ["12.6", "6.1", "—", "—", "—", "—", "—", "—"], "section", [
    row("senior-construction-draw", "Construction draw", ["—", "—", "—", "—", "—", "—", "—", "—"], ["12.1", "5.8", "—", "—", "—", "—", "—", "—"], "detail"),
    row("senior-fee-draw", "Capitalised commitment fee", ["—", "—", "—", "—", "—", "—", "—", "—"], ["0.5", "0.3", "—", "—", "—", "—", "—", "—"], "detail"),
  ]),
  row("senior-opening", "Opening principal", ["64.8", "60.2", "55.5", "50.8", "46.1", "41.5", "36.8", "32.1"], ["—", "12.6", "18.7", "18.7", "18.7", "16.3", "14.0", "11.5"], "metric"),
  row("senior-idc", "Interest during construction", ["—", "—", "—", "—", "—", "—", "—", "—"], ["0.4", "0.6", "—", "—", "—", "—", "—", "—"], "section", [
    row("senior-idc-cap", "Capitalised interest", ["—", "—", "—", "—", "—", "—", "—", "—"], ["0.4", "0.6", "—", "—", "—", "—", "—", "—"], "detail"),
  ]),
  row("senior-fee", "Facility & agency fees", ["(0.3)", "(0.3)", "(0.3)", "(0.3)", "(0.3)", "(0.2)", "(0.2)", "(0.2)"], ["(0.1)", "(0.1)", "(0.1)", "(0.1)", "(0.1)", "(0.1)", "(0.1)", "(0.1)"], "metric"),
  row("senior-interest", "Cash interest", ["(3.8)", "(3.5)", "(3.2)", "(2.9)", "(2.6)", "(2.4)", "(2.1)", "(1.8)"], ["—", "—", "(0.9)", "(0.9)", "(0.8)", "(0.8)", "(1.5)", "(1.3)"], "metric"),
  row("senior-principal", "Scheduled principal repayment", ["(4.6)", "(4.7)", "(4.7)", "(4.7)", "(4.7)", "(4.7)", "(4.7)", "(4.7)"], ["—", "—", "(2.4)", "(2.5)", "(2.2)", "(2.3)", "(4.5)", "(4.6)"], "metric"),
  row("senior-service", "Total debt service", ["(8.7)", "(8.5)", "(8.5)", "(8.6)", "(8.6)", "(8.7)", "(8.7)", "(8.7)"], ["—", "—", "(3.4)", "(3.5)", "(3.1)", "(3.2)", "(6.1)", "(6.0)"], "metric"),
  row("senior-closing", "Closing principal", ["60.2", "55.5", "50.8", "46.1", "41.5", "36.8", "32.1", "27.4"], ["12.6", "18.7", "18.7", "18.7", "16.3", "14.0", "11.5", "6.9"], "metric"),
];

const mezzDebtRows: StatementRow[] = [
  row("mezz-draw", "Mezzanine facility drawdown", ["—", "—", "—", "—", "—", "—", "—", "—"], ["2.4", "1.1", "—", "—", "—", "—", "—", "—"], "section", [
    row("mezz-construction-draw", "Construction draw", ["—", "—", "—", "—", "—", "—", "—", "—"], ["2.3", "1.0", "—", "—", "—", "—", "—", "—"], "detail"),
    row("mezz-fee-draw", "Capitalised commitment fee", ["—", "—", "—", "—", "—", "—", "—", "—"], ["0.1", "0.1", "—", "—", "—", "—", "—", "—"], "detail"),
  ]),
  row("mezz-opening", "Opening principal", ["10.0", "9.6", "9.0", "8.3", "7.6", "6.8", "6.0", "5.2"], ["—", "2.4", "3.5", "3.5", "3.5", "3.2", "2.9", "2.5"], "metric"),
  row("mezz-idc", "Interest during construction", ["—", "—", "—", "—", "—", "—", "—", "—"], ["0.1", "0.2", "—", "—", "—", "—", "—", "—"], "section", [
    row("mezz-idc-cap", "Capitalised interest", ["—", "—", "—", "—", "—", "—", "—", "—"], ["0.1", "0.2", "—", "—", "—", "—", "—", "—"], "detail"),
  ]),
  row("mezz-fee", "Facility & agency fees", ["(0.1)", "(0.1)", "(0.1)", "(0.1)", "(0.1)", "(0.1)", "(0.1)", "(0.1)"], ["(0.0)", "(0.0)", "(0.0)", "(0.0)", "(0.0)", "(0.0)", "(0.0)", "(0.0)"], "metric"),
  row("mezz-interest", "Cash interest", ["(1.1)", "(1.0)", "(0.9)", "(0.8)", "(0.7)", "(0.6)", "(0.5)", "(0.4)"], ["—", "—", "(0.2)", "(0.2)", "(0.2)", "(0.2)", "(0.4)", "(0.3)"], "metric"),
  row("mezz-principal", "Scheduled principal repayment", ["(0.4)", "(0.6)", "(0.7)", "(0.7)", "(0.8)", "(0.8)", "(0.8)", "(0.8)"], ["—", "—", "(0.3)", "(0.3)", "(0.3)", "(0.3)", "(0.7)", "(0.7)"], "metric"),
  row("mezz-service", "Total debt service", ["(1.5)", "(1.6)", "(1.7)", "(1.7)", "(1.8)", "(1.8)", "(1.8)", "(1.8)"], ["—", "—", "(0.5)", "(0.5)", "(0.5)", "(0.5)", "(1.1)", "(1.0)"], "metric"),
  row("mezz-closing", "Closing principal", ["9.6", "9.0", "8.3", "7.6", "6.8", "6.0", "5.2", "4.4"], ["2.4", "3.5", "3.5", "3.5", "3.2", "2.9", "2.5", "1.8"], "metric"),
];

const sponsorRows: StatementRow[] = [
  row("sponsor-contributions", "Sponsor equity contributions", ["(37.8)", "—", "—", "—", "—", "—", "—", "—"], ["(22.4)", "(15.4)", "—", "—", "—", "—", "—", "—"], "section", [
    row("sponsor-construction-equity", "Construction funding", ["(37.8)", "—", "—", "—", "—", "—", "—", "—"], ["(22.0)", "(15.1)", "—", "—", "—", "—", "—", "—"], "detail"),
    row("sponsor-reserve-equity", "Initial reserves & fees", ["—", "—", "—", "—", "—", "—", "—", "—"], ["(0.4)", "(0.3)", "—", "—", "—", "—", "—", "—"], "detail"),
  ]),
  row("sponsor-distributions", "Cash distributions", ["—", "1.1", "1.7", "1.8", "1.8", "1.9", "1.9", "2.0"], ["—", "—", "0.4", "0.5", "0.5", "0.5", "1.0", "1.0"], "section", [
    row("sponsor-operating-distribution", "Operating distributions", ["—", "1.1", "1.7", "1.8", "1.8", "1.9", "1.9", "2.0"], ["—", "—", "0.4", "0.5", "0.5", "0.5", "1.0", "1.0"], "detail"),
    row("sponsor-exit-distribution", "Exit proceeds", ["—", "—", "—", "—", "—", "—", "—", "—"], ["—", "—", "—", "—", "—", "—", "—", "—"], "detail"),
  ]),
  row("sponsor-net-cash", "Net sponsor cash flow", ["(37.8)", "1.1", "1.7", "1.8", "1.8", "1.9", "1.9", "2.0"], ["(22.4)", "(15.4)", "0.4", "0.5", "0.5", "0.5", "1.0", "1.0"], "metric"),
  row("sponsor-irr", "Equity IRR · fixed example", ["12.46%", "—", "—", "—", "—", "—", "—", "—"], ["12.46%", "—", "—", "—", "—", "—", "—", "—"], "metric"),
  row("sponsor-moic", "Equity MOIC · fixed example", ["1.82x", "—", "—", "—", "—", "—", "—", "—"], ["1.82x", "—", "—", "—", "—", "—", "—", "—"], "metric"),
];

export const SYNTHETIC_STATEMENT_SNAPSHOT: StatementWorkbookSnapshot = {
  annualPeriods,
  modelPeriods,
  periodBands,
  sheets: [
    { id: "pl", label: "P&L", title: "Profit & loss", unit: "EUR millions, unless stated", rows: plRows },
    { id: "balance", label: "Balance sheet", title: "Balance sheet", unit: "EUR millions, unless stated", rows: balanceRows },
    { id: "cashflow", label: "Cash flow", title: "Cash flow statement", unit: "EUR millions, unless stated", rows: cashflowRows },
    { id: "cfads", label: "CFADS", title: "Cash flow available for debt service", unit: "EUR millions, unless stated", rows: cfadsRows },
    { id: "debt", label: "Debt schedule", title: "Debt schedule", unit: "EUR millions, unless stated", rows: seniorDebtRows },
    { id: "sponsor", label: "Sponsor returns", title: "Sponsor returns", unit: "EUR millions, unless stated", rows: sponsorRows },
  ],
  debtRowsByFacility: {
    senior: seniorDebtRows,
    mezzanine: mezzDebtRows,
  },
};

export const SYNTHETIC_STATEMENT_STATUS: StatementRunStatus = {
  label: "Illustrative run",
  runId: "DEMO-FIXED-018",
  freshness: "unknown",
  integrity: "not evaluated",
  engineVersion: null,
  dataOrigin: "synthetic-demo",
};
