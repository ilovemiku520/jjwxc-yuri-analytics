import type { ReactNode } from "react";

import { OperationsNav } from "../../../components/operations/operations-nav";

export default function OperationsLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <>
      <OperationsNav />
      {children}
    </>
  );
}
