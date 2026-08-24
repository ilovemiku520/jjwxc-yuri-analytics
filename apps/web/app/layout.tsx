import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "晋江百合小说研析",
  description: "面向晋江文学城百合小说与作者公开聚合元数据的非商业研究网站。",
  authors: [{ name: "ilovemiku520@outlook.com" }],
  creator: "ilovemiku520@outlook.com",
  robots: { index: true, follow: true },
};

export default function RootLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <div className="site-shell">
          <header className="site-header">
            <Link className="brand" href="/">
              <span className="brand-mark" aria-hidden="true">
                晋
              </span>
              <span>
                <strong>晋江百合研析</strong>
                <small>JJWXC YURI RESEARCH</small>
              </span>
            </Link>
            <nav className="site-nav" aria-label="主导航">
              <Link href="/novels">小说</Link>
              <Link href="/authors">作者</Link>
              <Link href="/analytics">分析矩阵</Link>
              <Link href="/operations/readiness">采集状态</Link>
            </nav>
            <span className="boundary-badge">只读 · 近实时快照</span>
          </header>
          {children}
          <footer className="site-footer">
            <div className="site-footer-statements">
              <p>
                数据仅限个人学习或研究使用，严禁任何商业用途、二次分发或数据镜像。
              </p>
              <p>
                数据来源声明：页面可能展示明确标记的合成 Fixture，或从 JJWXC
                公开作品库、频道榜单与作品概览页保存的最小元数据索引和每日快照；不转载原文。
                晋江文学城及作品相关权利归平台与各权利人，本项目与晋江文学城无隶属或授权关系。
              </p>
            </div>
            <div className="site-footer-meta">
              <p className="project-owner">
                项目归属与作者：
                <a href="mailto:ilovemiku520@outlook.com">
                  ilovemiku520@outlook.com
                </a>
              </p>
              <Link href="/about/data-policy">数据使用与来源说明</Link>
            </div>
          </footer>
        </div>
      </body>
    </html>
  );
}
