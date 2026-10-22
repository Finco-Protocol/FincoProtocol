import React, { useEffect, useMemo, useRef, useState } from "react";
import { fincoBasePath, readProjectContext } from "../_shared/FincoShell";
import { preferredScrollBehavior } from "../_shared/motion";
import { statementCellText, statementStatusText, type StatementFacilityId, type StatementRow, type StatementSheet, type StatementSheetId, type StatementViewId, type StatementWorkbookProps } from "./statementContract";
import "./statements.css";

type SheetId = StatementSheetId;
type ViewId = StatementViewId;
type FacilityId = StatementFacilityId;
type Row = StatementRow;
type Sheet = StatementSheet;

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
  kind: Row["kind"] = "metric",
  children?: Row[],
): Row => ({ id, label, annual, model, kind, children });

const plRows: Row[] = [
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

const balanceRows: Row[] = [
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

const cashflowRows: Row[] = [
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

const cfadsRows: Row[] = [
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

const seniorDebtRows: Row[] = [
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

const mezzDebtRows: Row[] = [
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

const sponsorRows: Row[] = [
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

const sheets: Sheet[] = [
  { id: "pl", label: "P&L", title: "Profit & loss", unit: "EUR millions, unless stated", rows: plRows },
  { id: "balance", label: "Balance sheet", title: "Balance sheet", unit: "EUR millions, unless stated", rows: balanceRows },
  { id: "cashflow", label: "Cash flow", title: "Cash flow statement", unit: "EUR millions, unless stated", rows: cashflowRows },
  { id: "cfads", label: "CFADS", title: "Cash flow available for debt service", unit: "EUR millions, unless stated", rows: cfadsRows },
  { id: "debt", label: "Debt schedule", title: "Debt schedule", unit: "EUR millions, unless stated", rows: seniorDebtRows },
  { id: "sponsor", label: "Sponsor returns", title: "Sponsor returns", unit: "EUR millions, unless stated", rows: sponsorRows },
];

const validSheetIds: SheetId[] = ["pl", "balance", "cashflow", "cfads", "debt", "sponsor"];
const initialSheet = (): SheetId => {
  const fromUrl = new URLSearchParams(window.location.search).get("statement");
  return validSheetIds.includes(fromUrl as SheetId) ? (fromUrl as SheetId) : "pl";
};
const initialView = (): ViewId => new URLSearchParams(window.location.search).get("statementView") === "model" ? "model" : "annual";
type UnitDisplay = "EUR" | "kEUR" | "mEUR";
const unitScale: Record<UnitDisplay, number> = { EUR: 1_000_000, kEUR: 1_000, mEUR: 1 };
function displayStatementValue(value: string, label: string, unit: UnitDisplay, precision: number) {
  const trimmed = value.trim();
  if (/^not evaluated$/i.test(trimmed)) return "NOT EVALUATED";
  if (/^not tested$/i.test(trimmed)) return "NOT TESTED";
  if (!trimmed || /^(—|–|-|n\/a|na)$/i.test(trimmed)) return "—";
  const formattedMetric = /irr|moic|dscr|coverage ratio|%|x$/i.test(label);
  const suffix = formattedMetric && /[%x]$/i.test(trimmed) ? trimmed.slice(-1) : "";
  const numericText = suffix ? trimmed.slice(0, -1) : trimmed;
  const negative = /^\(.*\)$/.test(numericText) || numericText.startsWith("-");
  const number = Number(numericText.replace(/[(),]/g, ""));
  if (!Number.isFinite(number)) return value;
  const formatted = new Intl.NumberFormat("en-GB", {
    minimumFractionDigits: precision,
    maximumFractionDigits: precision,
    useGrouping: true,
  }).format(Math.abs(number) * (formattedMetric ? 1 : unitScale[unit]));
  return `${negative ? `(${formatted})` : formatted}${suffix}`;
}

const traceSources: Record<string, { label: string; sheet: string }> = {
  revenue: { label: "Revenue / PPA", sheet: "revenue" },
  "ppa-revenue": { label: "Revenue / PPA", sheet: "revenue" },
  "merchant-revenue": { label: "Revenue / merchant residual", sheet: "revenue" },
  ebitda: { label: "Revenue / OPEX assumptions", sheet: "revenue" },
  ebit: { label: "OPEX / tax assumptions", sheet: "opex" },
  pbt: { label: "Tax & timing", sheet: "tax" },
  "net-income": { label: "Tax & timing", sheet: "tax" },
  "sponsor-contributions": { label: "Investor / sponsor equity", sheet: "investor" },
  opex: { label: "OPEX / operating profiles", sheet: "opex" },
  "site-costs": { label: "OPEX / operating profiles", sheet: "opex" },
  "service-costs": { label: "OPEX / operating profiles", sheet: "opex" },
  depreciation: { label: "CAPEX / Tax", sheet: "tax" },
  "depreciation-detail": { label: "CAPEX / Tax", sheet: "tax" },
  amortisation: { label: "CAPEX / Tax", sheet: "tax" },
  tax: { label: "Tax & timing", sheet: "tax" },
  "cash-tax": { label: "Tax & timing", sheet: "tax" },
  "cash-tax-interest": { label: "Tax & timing", sheet: "tax" },
  "working-capital": { label: "OPEX / operating profiles", sheet: "opex" },
  "net-change": { label: "Cash Flow statement fixture", sheet: "sources-uses" },
  "cash-opening": { label: "Sources & Uses / cash context", sheet: "sources-uses" },
  "cash-closing": { label: "Sources & Uses / cash context", sheet: "sources-uses" },
  "finance-cost": { label: "Financing / facilities", sheet: "senior-debt" },
  "interest-expense": { label: "Financing / facilities", sheet: "senior-debt" },
  "fees-amortised": { label: "Financing / facilities", sheet: "senior-debt" },
  "senior-interest": { label: "Financing / Senior facility", sheet: "senior-debt" },
  "senior-principal": { label: "Financing / Senior facility", sheet: "senior-debt" },
  "senior-closing": { label: "Financing / Senior facility", sheet: "senior-debt" },
  "senior-fee": { label: "Financing / Senior facility", sheet: "senior-debt" },
  "debt-balance": { label: "Financing / debt schedule", sheet: "senior-debt" },
  "debt-cf": { label: "Financing / debt schedule", sheet: "senior-debt" },
  "senior-draw": { label: "Financing / debt schedule", sheet: "senior-debt" },
  "senior-opening": { label: "Financing / debt schedule", sheet: "senior-debt" },
  "senior-service": { label: "Financing / debt schedule", sheet: "senior-debt" },
  "mezz-draw": { label: "Financing / debt schedule", sheet: "senior-debt" },
  "cfads-total": { label: "CFADS / fixed statement", sheet: "cfads" },
  "scheduled-service": { label: "Debt schedule / fixed statement", sheet: "debt" },
  "cash-equity": { label: "Investor / sponsor returns", sheet: "investor" },
  "sponsor-net-cash": { label: "Investor / sponsor returns", sheet: "investor" },
  "sponsor-distributions": { label: "Investor / sponsor returns", sheet: "investor" },
  "sponsor-irr": { label: "Investor / sponsor returns", sheet: "investor" },
  "sponsor-moic": { label: "Investor / sponsor returns", sheet: "investor" },
};
const traceParentByChild: Record<string, string> = {
  "ppa-revenue": "revenue", "merchant-revenue": "revenue", "site-costs": "opex", "service-costs": "opex",
  "depreciation-detail": "depreciation", amortisation: "depreciation", "interest-expense": "finance-cost",
  "fees-amortised": "finance-cost", "cash-receipts": "operating-cf", "cash-operating": "operating-cf",
  "cash-tax-interest": "operating-cf", capex: "investing-cf", "reserve-funding": "investing-cf",
  "debt-cf": "financing-cf", "equity-cf": "financing-cf", "cfads-revenue": "cfads-ebitda",
  "cfads-costs": "cfads-ebitda", dsra: "reserve-movement", "maintenance-reserve": "reserve-movement",
  "principal-service": "scheduled-service", "interest-service": "scheduled-service",
  "senior-construction-draw": "senior-draw", "senior-fee-draw": "senior-draw",
  "senior-idc-cap": "senior-idc", "mezz-construction-draw": "mezz-draw",
  "mezz-fee-draw": "mezz-draw", "mezz-idc-cap": "mezz-idc",
  "sponsor-operating-distribution": "sponsor-distributions", "sponsor-exit-distribution": "sponsor-distributions",
};
function initialExpandedState() {
  const params = new URLSearchParams(window.location.search);
  const sheet = initialSheet();
  const parent = traceParentByChild[params.get("traceRow") || ""];
  let restored: Record<string, boolean> = {};
  try {
    const raw = params.get("returnExpanded");
    if (raw) {
      const parsed = JSON.parse(raw) as Record<string, boolean>;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) restored = parsed;
    }
  } catch {
    restored = {};
  }
  return parent ? { ...restored, [`${sheet}:${parent}`]: true } : restored;
}

function formatExpressionLabel(label: string) {
  return label.toUpperCase().replace(/[^\w]+/g, "_").replace(/^_|_$/g, "");
}

function StatementTable({
  sheet,
  periods,
  view,
  expanded,
  onToggleGroup,
  traceId,
  setTraceId,
  tracePeriod,
  setTracePeriod,
  unit,
  precision,
  showInitialPeriod,
  facility,
  periodBands: visiblePeriodBands,
  regionRef,
}: {
  sheet: Sheet;
  periods: string[];
  view: ViewId;
  expanded: Record<string, boolean>;
  onToggleGroup: (id: string) => void;
  traceId: string | null;
  setTraceId: (id: string | null) => void;
  tracePeriod: number;
  setTracePeriod: (period: number) => void;
  unit: UnitDisplay;
  precision: number;
  showInitialPeriod: boolean;
  facility: FacilityId;
  periodBands: { label: string; span: number }[];
  regionRef: React.RefObject<HTMLDivElement>;
}) {
  const periodIndexes = periods.map((_, index) => view === "model" && !showInitialPeriod ? index + 1 : index);
  const rows = useMemo(() => {
    const visible: Row[] = [];
    sheet.rows.forEach((item) => {
      visible.push(item);
      if (item.children && expanded[`${sheet.id}:${item.id}`]) visible.push(...item.children);
    });
    return visible;
  }, [expanded, sheet]);
  return <div
    className="fm-sw-region"
    role="region"
    aria-label={`${sheet.title}, scrollable financial periods`}
    aria-describedby="fm-sw-scroll-help"
    tabIndex={0}
    ref={regionRef}
    onKeyDown={(event) => {
      if (event.target !== event.currentTarget) return;
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        event.preventDefault();
        event.currentTarget.scrollBy({ left: event.key === "ArrowRight" ? 120 : -120 });
      }
    }}
  >
    <table className="fm-sw-table">
      <caption className="fm-sr-only">{sheet.title}, fixed synthetic example rows, {view === "annual" ? "annual" : "model-period snapshots"}. Not a fully populated engine statement.</caption>
      <thead>
        {view === "annual" ? <tr><th scope="col">Statement line · {sheet.unit}</th><th scope="colgroup" colSpan={periods.length}>Operating years</th></tr> :
          <tr><th scope="col">Statement line · {sheet.unit}</th>{visiblePeriodBands.map((band, index) => {
            const span = index === 0 && !showInitialPeriod ? band.span - 1 : band.span;
            return span > 0 ? <th key={band.label} scope="colgroup" colSpan={span}>{band.label}</th> : null;
          })}</tr>}
        <tr><th scope="col">Fixed example rows</th>{periods.map((period) => <th scope="col" key={period}>{period}</th>)}</tr>
      </thead>
      <tbody>
          {rows.map((item, rowIndex) => {
          const isOpen = Boolean(item.children && expanded[`${sheet.id}:${item.id}`]);
          const values = view === "annual" ? item.annual : item.model;
          const traceOpen = traceId === item.id;
            const source = traceSources[item.id] || { label: "Workbook source category", sheet: "input-grid" };
            const inputParams = new URLSearchParams(window.location.search);
            inputParams.delete("statement");
            inputParams.set("sheet", source.sheet);
            inputParams.set("returnStatement", sheet.id);
            inputParams.set("returnView", view);
            inputParams.set("returnRow", item.id);
            inputParams.set("returnPeriod", String(tracePeriod));
            inputParams.set("returnShowInitial", showInitialPeriod ? "1" : "0");
            inputParams.set("returnFacility", facility);
            inputParams.set("returnExpanded", JSON.stringify(expanded));
            inputParams.set("returnScrollLeft", String(regionRef.current?.scrollLeft || 0));
            inputParams.set("returnScrollY", String(Math.round(window.scrollY)));
            const sourceHref = `${fincoBasePath()}ModelWorkspace?${inputParams.toString()}#workbook`;
          return <React.Fragment key={item.id}>
            <tr className={`${item.kind === "section" ? "fm-sw-section" : item.kind === "detail" ? "fm-sw-detail" : ""}${traceOpen ? " fm-sw-row-selected" : ""}`}>
              <th scope="row" className="fm-sw-label">
                <span className="fm-sw-row-select">
                  {item.children && <button
                    className="fm-sw-row-select"
                    type="button"
                    aria-label={`${isOpen ? "Collapse" : "Expand"} ${item.label} detail rows`}
                    aria-expanded={isOpen}
                    onClick={() => onToggleGroup(item.id)}
                  ><span className="fm-sw-chevron" aria-hidden="true">{isOpen ? "▾" : "▸"}</span></button>}
                  <button className="fm-sw-row-select" type="button" aria-expanded={traceOpen} onClick={() => setTraceId(traceOpen ? null : item.id)}>
                    {item.label}
                  </button>
                </span>
              </th>
              {periodIndexes.map((sourceIndex, index) => {
                const value = values[sourceIndex] || "—";
                return <td key={`${item.id}-${sourceIndex}`} className={`${traceOpen && tracePeriod === index ? "fm-sw-cell-selected" : traceId && tracePeriod === index ? "fm-sw-col-selected" : ""}${traceOpen ? " fm-sw-row-active-cell" : ""}`}>
                <button
                  type="button"
                  className="fm-sw-cell-button"
                  data-statement-row={item.id}
                  data-statement-col={index}
                  aria-label={`${item.label}, ${periods[index]}, ${displayStatementValue(value, item.label, unit, precision)} ${unit}. Open synthetic source trace.`}
                  onClick={() => { setTraceId(item.id); setTracePeriod(index); }}
                  onKeyDown={event => {
                    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
                    event.preventDefault();
                    const nextRow = Math.max(0, Math.min(rows.length - 1, rowIndex + (event.key === "ArrowUp" ? -1 : event.key === "ArrowDown" ? 1 : 0)));
                    const nextColumn = Math.max(0, Math.min(periods.length - 1, index + (event.key === "ArrowLeft" ? -1 : event.key === "ArrowRight" ? 1 : 0)));
                    const targetRowId = rows[nextRow].id;
                    setTraceId(targetRowId);
                    setTracePeriod(nextColumn);
                    event.currentTarget.closest("table")?.querySelector<HTMLButtonElement>(`button[data-statement-row="${targetRowId}"][data-statement-col="${nextColumn}"]`)?.focus();
                  }}
                >{displayStatementValue(value, item.label, unit, precision)}</button>
              </td>;
              })}
            </tr>
            {traceOpen && <tr className="fm-sw-trace-row">
              <th scope="row" className="fm-sw-trace-cell" colSpan={periods.length + 1}>
                <div className="fm-sw-trace">
                  <div className="fm-sw-trace-copy">
                    <strong>SYNTHETIC SOURCE TRACE · {item.label} · {periods[tracePeriod]}</strong>
                    <span className="fm-sw-trace-code">{formatExpressionLabel(item.label)} = fixed illustrative value · {displayStatementValue(values[periodIndexes[tracePeriod]] || "—", item.label, unit, precision)} {unit}</span>
                    <span>Associated section: {source.label} · Run DEMO-FIXED-018 · {view === "annual" ? "Annual example array" : "Model-period snapshot array"}.</span>
                    <span><strong>Calculation lineage unavailable.</strong> Navigation identifies a relevant design section only; it does not prove numerical dependency on its inputs.</span>
                  </div>
                  <a className="fm-sw-trace-open" href={sourceHref}>Open {source.label} →</a>
                  <button className="fm-sw-trace-close" type="button" onClick={() => setTraceId(null)}>Close trace</button>
                </div>
              </th>
            </tr>}
          </React.Fragment>;
        })}
      </tbody>
    </table>
  </div>;
}

const defaultStatementStatus = {
  label: "Illustrative run",
  runId: "DEMO-FIXED-018",
  freshness: "unknown" as const,
  integrity: "not evaluated" as const,
  engineVersion: null,
};

export default function StatementWorkbook({ onSheetChange, snapshot, status = defaultStatementStatus }: StatementWorkbookProps = {}) {
  const project = readProjectContext();
  const visibleSheets = snapshot?.sheets ?? sheets;
  const visibleAnnualPeriods = snapshot?.annualPeriods ?? annualPeriods;
  const visibleModelPeriods = snapshot?.modelPeriods ?? modelPeriods;
  const visiblePeriodBands = snapshot?.periodBands ?? periodBands;
  const runStatus = statementStatusText(status);
  const [sheetId, setSheetId] = useState<SheetId>(initialSheet);
  const [view, setView] = useState<ViewId>(initialView);
  const [facility, setFacility] = useState<FacilityId>(() => new URLSearchParams(window.location.search).get("returnFacility") === "mezzanine" ? "mezzanine" : "senior");
  const [showInitialPeriod, setShowInitialPeriod] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return (params.get("returnShowInitial") ?? params.get("statementShowInitial")) !== "0";
  });
  const [expanded, setExpanded] = useState<Record<string, boolean>>(initialExpandedState);
  const [traceId, setTraceId] = useState<string | null>(() => new URLSearchParams(window.location.search).get("traceRow"));
  const [tracePeriod, setTracePeriod] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    const candidate = Number(params.get("returnPeriod") || 0);
    const modelView = initialView() === "model";
    const hiddenInitial = (params.get("returnShowInitial") ?? params.get("statementShowInitial")) === "0";
    const count = modelView ? modelPeriods.length - (hiddenInitial ? 1 : 0) : annualPeriods.length;
    return Number.isFinite(candidate) ? Math.max(0, Math.min(count - 1, candidate)) : 0;
  });
  const [unit, setUnit] = useState<UnitDisplay>("mEUR");
  const [precision, setPrecision] = useState(1);
  const regionRef = useRef<HTMLDivElement>(null);
  const activeSheet = visibleSheets.find((item) => item.id === sheetId) || visibleSheets[0];
  const defaultDebtRows = { senior: seniorDebtRows, mezzanine: mezzDebtRows };
  const rows = sheetId === "debt" ? (snapshot?.debtRowsByFacility?.[facility] ?? defaultDebtRows[facility]) : activeSheet.rows;
  const displayedSheet = rows === activeSheet.rows ? activeSheet : { ...activeSheet, title: `${facility === "senior" ? "Senior" : "Mezzanine"} facility debt schedule`, rows };
  const periods = view === "annual" ? visibleAnnualPeriods : showInitialPeriod ? visibleModelPeriods : visibleModelPeriods.slice(1);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("returnTrace") !== "1") return;
    const scrollLeft = Number(params.get("returnScrollLeft") || 0);
    const scrollY = Number(params.get("returnScrollY") || 0);
    const timer = window.setTimeout(() => {
      regionRef.current?.scrollTo({ left: scrollLeft });
      if (scrollY > 0) window.scrollTo(0, scrollY);
    }, 40);
    return () => window.clearTimeout(timer);
  }, []);

  function chooseSheet(id: SheetId) {
    setSheetId(id);
    onSheetChange?.(id);
    setTraceId(null);
    const url = new URL(window.location.href);
    url.searchParams.set("statement", id);
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
  }
  function toggleGroup(id: string) {
    const key = `${sheetId}:${id}`;
    setExpanded((current) => ({ ...current, [key]: !current[key] }));
  }
  function toggleAllGroups(open: boolean) {
    const next: Record<string, boolean> = {};
    activeSheet.rows.forEach(item => { if (item.children) next[`${sheetId}:${item.id}`] = open; });
    setExpanded(current => ({ ...current, ...next }));
  }
  function scrollPeriods(direction: -1 | 1) {
    regionRef.current?.scrollBy({ left: direction * 240, behavior: preferredScrollBehavior() });
  }

  return <section id="statement-workbook" tabIndex={-1}>
      <section className="fm-sw" aria-label="Financial statement workbook">
        <header className="fm-sw-head">
          <div>
            <div className="fm-eyebrow">{project.id} · Financial statements</div>
            <h1 className="fm-sw-title">Statement workbook</h1>
            <div className="fm-sw-subtitle">{project.name} <span aria-hidden="true">·</span> {project.technology} <span aria-hidden="true">·</span> Illustrative EUR model view</div>
            <div className="fm-sw-tags">
              <span className="fm-sw-tag fm-sw-tag--demo">FIXED SYNTHETIC EXAMPLE</span>
              <span className="fm-sw-tag">Partial example rows</span>
              <span className="fm-sw-tag">No engine connection</span>
            </div>
          </div>
            <div className="fm-sw-run" aria-label="Illustrative run status">
            <span>{status.label}</span><strong>{status.runId}</strong>
            <span className="fm-sw-tag">{runStatus.freshness}</span>
            <span className="fm-sw-tag">{runStatus.integrity}</span>
            <span className="fm-sw-tag">{runStatus.engine}</span>
          </div>
        </header>

        <div className="fm-sw-warning" role="note">
          <strong>Display-only workbook.</strong> Fixed synthetic values are not linked to inputs and do not recalculate. Freshness is unknown because input linkage is absent; integrity has not been evaluated. These independent partial sheet samples are not complete or cross-sheet-reconciled engine statements.
        </div>

        <div className="fm-sw-toolbar">
          <div className="fm-sw-tabs" role="tablist" aria-label="Financial statement sheets">
            {visibleSheets.map((item) => <button
              key={item.id}
              type="button"
              role="tab"
              id={`fm-sw-tab-${item.id}`}
              aria-selected={sheetId === item.id}
              aria-controls="fm-sw-sheet"
              className="fm-sw-tab"
              onClick={() => chooseSheet(item.id)}
            >{item.label}</button>)}
          </div>
          <div className="fm-sw-controls">
            <label className="fm-sw-field" htmlFor="fm-sw-view">View
              <select id="fm-sw-view" className="fm-sw-select" value={view} onChange={(event) => {
                const next = event.target.value as ViewId;
                setView(next); setTraceId(null);
                const params = new URLSearchParams(window.location.search);
                params.set("statementView", next);
                window.history.replaceState(window.history.state, "", `${window.location.pathname}?${params}${window.location.hash}`);
              }}>
                <option value="annual">Annual</option>
                <option value="model">Model periods</option>
              </select>
            </label>
            <label className="fm-sw-field" htmlFor="fm-sw-unit">Units
              <select id="fm-sw-unit" className="fm-sw-select" value={unit} onChange={event => setUnit(event.target.value as UnitDisplay)}>
                <option value="EUR">EUR</option><option value="kEUR">kEUR</option><option value="mEUR">mEUR</option>
              </select>
            </label>
            <label className="fm-sw-field" htmlFor="fm-sw-precision">Precision
              <select id="fm-sw-precision" className="fm-sw-select" value={precision} onChange={event => setPrecision(Number(event.target.value))}>
                <option value={0}>0 decimals</option><option value={1}>1 decimal</option><option value={2}>2 decimals</option><option value={3}>3 decimals</option>
              </select>
            </label>
            {view === "model" && <button
              type="button"
              className="fm-sw-period-toggle"
              aria-pressed={showInitialPeriod}
              onClick={() => {
                const next = !showInitialPeriod;
                setShowInitialPeriod(next);
                setTracePeriod((current) => Math.max(0, Math.min(modelPeriods.length - (next ? 1 : 2), current)));
                setTraceId(null);
                const params = new URLSearchParams(window.location.search);
                params.set("statementShowInitial", next ? "1" : "0");
                window.history.replaceState(window.history.state, "", `${window.location.pathname}?${params}${window.location.hash}`);
              }}
            >Initial period: {showInitialPeriod ? "shown" : "hidden"}</button>}
            <div className="fm-sw-expand-controls" aria-label="Statement row groups">
              <button type="button" className="fm-sw-scroll-btn" onClick={() => toggleAllGroups(true)}>Expand all</button>
              <button type="button" className="fm-sw-scroll-btn" onClick={() => toggleAllGroups(false)}>Collapse all</button>
            </div>
            <span className="fm-sw-active-cell" aria-live="polite">
              {traceId ? (() => {
                const activeRow = rows.find(item => item.id === traceId);
                const activeValue = activeRow?.[view] ?? [];
                const address = `${String.fromCharCode(66 + tracePeriod)}${Math.max(2, rows.findIndex(item => item.id === traceId) + 2)}`;
                return `${address} · ${activeRow?.label || "Selected line"} · ${statementCellText(activeValue[tracePeriod])} ${activeSheet.unit} · fixed synthetic reference`;
              })() : "Select a cell to open its synthetic trace"}
            </span>
            {sheetId === "debt" && <label className="fm-sw-field" htmlFor="fm-sw-facility">Facility
              <select id="fm-sw-facility" className="fm-sw-select" aria-label="Statement facility" value={facility} onChange={(event) => { setFacility(event.target.value as FacilityId); setTraceId(null); }}>
                <option value="senior">Senior</option>
                <option value="mezzanine">Mezzanine</option>
              </select>
            </label>}
          </div>
        </div>

        <section id="fm-sw-sheet" role="tabpanel" aria-labelledby={`fm-sw-tab-${sheetId}`}>
          {sheetId === "sponsor" && <div className="fm-sw-subbar">
            <span><strong>Fixed sponsor outputs:</strong> Equity IRR 12.46% · Equity MOIC 1.82x</span>
            <span>Display values only · no return calculation</span>
          </div>}
          {sheetId !== "sponsor" && <div className="fm-sw-subbar">
            <span><strong>{displayedSheet.title}</strong> · Display units: {unit} · formatting only</span>
            <span>{view === "annual" ? "Annual view · 2027–2034" : "Selected period snapshots · not a full time series"}</span>
          </div>}
          {sheetId === "sponsor" && <div className="fm-sw-subbar">
            <span><strong>{displayedSheet.title}</strong> · Display units: {unit} · formatting only</span>
            <span>{view === "annual" ? "Annual view · 2027–2034" : "Selected period snapshots · not a full time series"}</span>
          </div>}
          <div className="fm-sw-subbar">
            <span id="fm-sw-scroll-help">Scroll periods horizontally · Focus table and use ← / →</span>
            <div className="fm-sw-scroll-controls">
              <button type="button" className="fm-sw-scroll-btn" aria-label="Scroll statement periods left" onClick={() => scrollPeriods(-1)}>←</button>
              <button type="button" className="fm-sw-scroll-btn" aria-label="Scroll statement periods right" onClick={() => scrollPeriods(1)}>→</button>
            </div>
          </div>
          <StatementTable
            sheet={displayedSheet}
            periods={periods}
            view={view}
            expanded={expanded}
            onToggleGroup={toggleGroup}
            traceId={traceId}
            setTraceId={setTraceId}
            tracePeriod={tracePeriod}
            setTracePeriod={setTracePeriod}
            unit={unit}
            precision={precision}
            showInitialPeriod={showInitialPeriod}
            facility={facility}
            periodBands={visiblePeriodBands}
            regionRef={regionRef}
          />
        </section>
        <footer className="fm-sw-footnote">
          <span><strong>Example coverage:</strong> selected statement lines and period snapshots only; no complete model time series.</span>
          <span>Frequency snapshots are illustrative and carry no production frequency-policy authority.</span>
        </footer>
      </section>
  </section>;
}
