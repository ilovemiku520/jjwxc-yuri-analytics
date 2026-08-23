import Link from "next/link";

const ITEMS = [
  ["概览", "/operations"],
  ["部署就绪", "/operations/readiness"],
  ["JJWXC 探针", "/operations/imports"],
  ["Schema", "/operations/schemas"],
  ["运行", "/operations/runs"],
  ["任务", "/operations/tasks"],
  ["安全状态", "/operations/security"],
  ["隔离队列", "/operations/quarantine"],
] as const;

export function OperationsNav() {
  return (
    <nav className="operations-nav" aria-label="运维导航">
      {ITEMS.map(([label, href]) => (
        <Link href={href} key={href}>
          {label}
        </Link>
      ))}
    </nav>
  );
}
