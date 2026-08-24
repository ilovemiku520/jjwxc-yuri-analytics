import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const ownerEmail = "ilovemiku520@outlook.com";

test("shows JJWXC product identity, ownership, and research boundary", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "百合小说的 近实时脉搏" }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: ownerEmail })).toHaveAttribute(
    "href",
    `mailto:${ownerEmail}`,
  );
  await expect(
    page.getByText("不采集正文、评论内容", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: "JJWXC 百合小说书评与收藏趋势图" }),
  ).toBeVisible();
});

test("keeps the novel index search-first without rendering the full catalog", async ({
  page,
}) => {
  await page.goto("/novels");
  await expect(
    page.getByRole("heading", { name: "找作品，也看见趋势" }),
  ).toBeVisible();
  await expect(page.getByText("页面不再铺开全部已采集作品")).toHaveCount(0);
  await expect(page.getByText("她从长夜来")).toHaveCount(0);
  await page.getByLabel("搜索晋江百合作品").fill("长夜");
  await page.getByRole("button", { name: "搜索索引" }).click();
  await expect(page).toHaveURL(/\/novels\?q=%E9%95%BF%E5%A4%9C/u);
  await expect(page.getByText("她从长夜来")).toBeVisible();
  await expect(page.getByText("向晚潮声")).toHaveCount(0);
});

test("navigates novel and author aggregate details", async ({ page }) => {
  await page.goto("/novels/90000002");
  await expect(page.getByRole("heading", { name: "她从长夜来" })).toBeVisible();
  await expect(page.getByText("总书评数")).toBeVisible();
  await page.getByRole("link", { name: "折春枝" }).click();
  await expect(page).toHaveURL(/\/authors\/700002$/u);
  await expect(page.getByRole("heading", { name: "折春枝" })).toBeVisible();
  await expect(page.getByText("公开聚合快照").first()).toBeVisible();
});

test("publishes consistent JJWXC source and non-commercial statements", async ({
  page,
}) => {
  await page.goto("/about/data-policy");
  await expect(
    page.getByRole("heading", { name: "数据使用与来源说明" }),
  ).toBeVisible();
  await expect(
    page.getByText("严禁商业用途、二次分发", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText("与晋江文学城不存在隶属、合作、背书或授权关系", {
      exact: false,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("长期库仅保留文案长度", { exact: false }),
  ).toBeVisible();
});

test("explores multi-metric history, adjustable ratings, and the correlation matrix", async ({
  page,
}) => {
  await page.goto("/analytics");
  await expect(
    page.getByRole("heading", { name: "时间与变量 交互分析" }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: "JJWXC 多指标时间轴图" }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: "作品指标 Pearson 相关矩阵热力图" }),
  ).toBeVisible();
  await expect(
    page
      .getByLabel("矩阵指标，至少选择两个")
      .getByRole("button", { name: "V 章均点击", exact: true }),
  ).toHaveCount(0);
  await expect(
    page
      .getByLabel("矩阵指标，至少选择两个")
      .getByRole("button", { name: "V/非 V 点击留存比（代理）", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "作品与作者公开数据表现评级" }),
  ).toBeVisible();
  await expect(page.getByLabel("作品评分排行")).toBeVisible();
  await page.getByLabel("收藏权重", { exact: true }).fill("5000");
  await expect(page.getByText("41.3%", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "恢复数据校准权重" }).click();
  await expect(page.getByText("29.0%", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "作者", exact: true }).click();
  await expect(page.getByLabel("作者评分排行")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "切换为基准指数" }),
  ).toBeVisible();
  await expect(page.getByText("左轴 · 总收藏 · 求和统计 · 万次")).toBeVisible();
  await page.getByRole("button", { name: "平均每部作品" }).click();
  await expect(
    page.getByText("左轴 · 每部作品平均收藏 · 每部作品均值 · 万次/部"),
  ).toBeVisible();
  await page.getByText("统计要求说明").click();
  await expect(
    page.getByText("缺失值保持为空且不补零", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "总量统计" }).click();
  const timelinePicker = page.getByLabel("时间轴指标，最多选择三个");
  await timelinePicker.getByRole("button", { name: "书评" }).click();
  await timelinePicker.getByRole("button", { name: "非 V 章均点击" }).click();
  await expect(page.getByText("右轴 · 总书评 · 求和统计 · 千条")).toBeVisible();
  await expect(
    page.getByText("右轴（外侧） · 非 V 章均点击 · 跨作品章均值 · 万次/章"),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "V 章均点击" }).first(),
  ).toBeVisible();
  await expect(page.getByText("V 章点击覆盖：1/2 部作品")).toBeVisible();
  await expect(page.getByText("留存代理覆盖：1/2 部作品", { exact: false })).toBeVisible();
  await expect(page.getByLabel("统计时间范围")).toBeVisible();
  await page.getByLabel("开始日期").fill("2026-08-23");
  await expect(page.getByText(/1个快照日/u)).toBeVisible();
  await page.getByLabel("开始日期").fill("2026-08-22");
  await expect(
    page.getByRole("img", { name: /可调样本作品相关系数比较图/u }),
  ).toBeVisible();
  await expect(page.getByLabel("分析样本量")).toBeDisabled();
  await expect(page.getByLabel("样本量精确值")).toBeDisabled();
  await expect(
    page.getByText(/当前没有变量对达到 30 个共同有效样本/u),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "双方法校验" }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByText("查看一阶矩、二阶矩与估计区间").click();
  await expect(
    page.getByRole("columnheader", { name: "协方差" }),
  ).toBeVisible();
  await expect(
    page.getByRole("columnheader", { name: "Spearman ρ" }),
  ).toBeVisible();
  await expect(page.getByText("单量，多时间窗口")).toHaveCount(0);
  await expect(page.getByText("高维统计特性")).toHaveCount(0);
  await page.getByLabel("搜索作品名或作者名后加入统计").fill("长夜");
  await page.getByRole("button", { name: "搜索可统计作品" }).click();
  await page.getByRole("link", { name: "加入统计" }).click();
  await expect(page).toHaveURL(/novels=90000002/u);
  await expect(page.getByLabel("已选择作品")).toContainText("她从长夜来");
  await expect(page.getByText("V 章点击覆盖：0/1 部作品")).toBeVisible();
});

test("imports a local cohort table and excludes invalid or failed rows", async ({
  page,
}) => {
  await page.goto("/analytics");
  await page.getByLabel("导入作品 ID 表").setInputFiles({
    name: "cohort.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(
      "novel_id,title\n90000001,可用\n90000001,重复\n1.2E8,错误类型\n99999999,采集失败\n",
    ),
  });
  await expect(page.getByText(/合法唯一 ID 2 个/u)).toBeVisible();
  await expect(page.getByText(/本机排除 2 行/u)).toBeVisible();
  await page.getByRole("button", { name: "校验并排队采集" }).click();
  await expect(
    page.getByText(/已采集 1.*排队 0.*采集中 0.*采集失败\/未排队 1/u),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "必须是 1–12 位正整数字符串" }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "collection_failed" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "用 1 部成功作品进行比较" }),
  ).toHaveAttribute("href", "/analytics?novels=90000001");
  await expect(
    page.getByRole("button", { name: "下载排除/失败清单（3）" }),
  ).toBeEnabled();
});

test("shows one-request candidate status without mutation controls", async ({
  page,
}) => {
  await page.goto("/operations/imports");
  await expect(
    page.getByRole("heading", { name: "真实样本候选" }),
  ).toBeVisible();
  await expect(page.getByText("公开元数据候选已生成")).toBeVisible();
  await expect(page.getByText("1 / 1")).toBeVisible();
  await expect(page.getByText("BLOCKED")).toBeVisible();
  await expect(
    page.getByRole("button", { name: /采集|入库|重试|删除/u }),
  ).toHaveCount(0);
});

test("has no serious or critical accessibility violations on JJWXC routes", async ({
  page,
}) => {
  for (const route of [
    "/",
    "/novels",
    "/novels/90000001",
    "/authors",
    "/authors/700001",
    "/analytics",
    "/about/data-policy",
    "/operations/imports",
  ]) {
    await page.goto(route);
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    const blocking = results.violations.filter(
      (item) => item.impact === "critical" || item.impact === "serious",
    );
    expect(
      blocking,
      `${route}: ${blocking.map((item) => item.id).join(", ")}`,
    ).toEqual([]);
  }
});
