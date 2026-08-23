import Link from "next/link";

export function NextPageLink({ href }: { href: string | null }) {
  if (!href) {
    return <span className="page-end">已到末页</span>;
  }
  return (
    <Link className="page-next" href={href} rel="next">
      下一页 →
    </Link>
  );
}
