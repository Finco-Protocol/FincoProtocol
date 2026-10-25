import React, { createContext, useContext, type ReactNode } from "react";
import type { FincoRoute } from "./routes";
import type { StatementRunStatus, StatementWorkbookSnapshot } from "../src/finco/_workbook/statementContract";

export type FincoTransferContextValue = {
  route: FincoRoute;
  project: {
    id: string;
    name: string;
    technology: string;
    mode: "reference" | "working-copy";
  };
  scenarioId: string;
  contractId: string;
  facilityId: string;
  statementSnapshot: StatementWorkbookSnapshot | null;
  statementStatus: StatementRunStatus;
  navigate: (href: string) => void;
};

const FincoTransferContext = createContext<FincoTransferContextValue | null>(null);

export function FincoTransferProvider({
  value,
  children,
}: {
  value: FincoTransferContextValue;
  children: ReactNode;
}) {
  return <FincoTransferContext.Provider value={value}>{children}</FincoTransferContext.Provider>;
}

export function useFincoTransferContext(): FincoTransferContextValue {
  const context = useContext(FincoTransferContext);
  if (!context) throw new Error("useFincoTransferContext must be used inside FincoTransferProvider.");
  return context;
}
