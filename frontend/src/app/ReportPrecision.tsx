import { createContext, useContext, useState, type ReactNode } from "react";
import { DEFAULT_REPORT_PRECISION } from "./reportFormatting";

const Precision = createContext<{ precision: number; setPrecision: (value: number) => void } | null>(null);
export function ReportPrecisionProvider({ children }: { children: ReactNode }) {
  const [precision, setPrecision] = useState(DEFAULT_REPORT_PRECISION);
  return <Precision.Provider value={{ precision, setPrecision }}>{children}</Precision.Provider>;
}
export function useReportPrecision() {
  const context = useContext(Precision);
  const [local, setLocal] = useState(DEFAULT_REPORT_PRECISION);
  return { ...(context ?? { precision: local, setPrecision: setLocal }), shared: context !== null };
}
export function ReportPrecisionControl() {
  const { precision, setPrecision } = useReportPrecision();
  return <label className="wsv2-precision">Report precision <select aria-label="Report precision" value={precision} onChange={(event) => setPrecision(Number(event.target.value))}>
    {[0, 1, 2, 3].map((value) => <option key={value} value={value}>{value} decimals</option>)}
  </select><span className="rx-note">Amounts only · ratios and rates retain dedicated precision</span></label>;
}
