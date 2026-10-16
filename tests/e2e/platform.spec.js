const path = require("node:path");
const { test, expect, devices } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#runtime-status")).not.toContainText("正在核验运行环境");
});

test("居民预筛可保存并用一次性凭证删除", async ({ page }) => {
  await page.locator('[data-nav="screening"]').click();
  await page.locator("#load-demo").click();
  await page.locator("#screening-consent").check();
  await page.locator("#persist-screening").check();
  const created = page.waitForResponse(
    (response) => response.url().includes("/api/v1/screenings?persist=true")
      && response.request().method() === "POST",
  );
  await page.locator("#screen-submit").click();
  expect((await created).status()).toBe(200);
  await expect(page.locator("#results-zone")).toBeVisible();
  await expect(page.locator("#results-zone")).toContainText("政策");

  page.once("dialog", (dialog) => dialog.accept());
  const deleted = page.waitForResponse(
    (response) => response.url().includes("/api/v1/screenings/HM-")
      && response.request().method() === "DELETE",
  );
  await page.locator("#delete-screening").click();
  expect((await deleted).status()).toBe(200);
  await expect(page.locator("#toast-region")).toContainText("本次预筛记录已删除");
});

test("UNKNOWN案例保留未知并给出人工核验路径", async ({ page }) => {
  await page.locator('[data-portal-role="staff"]').click();
  await page.locator('[data-nav="demo"]').click();
  await page.locator('[data-demo-case="B"]').click();
  await expect(page.locator("#demo-output")).toContainText("UNKNOWN");
  await expect(page.locator("#demo-output")).toContainText(/人工|核验|确认/);
});

test("政策证据支持键盘回车检索并显示原文锚点", async ({ page }) => {
  await page.locator('[data-nav="evidence"]').click();
  const query = page.locator("#evidence-query");
  await query.focus();
  await query.fill("最低生活保障收入");
  await query.press("Enter");
  await expect(page.locator("#evidence-results .evidence-card").first()).toBeVisible();
  await expect(page.locator("#evidence-results")).toContainText("政策逐字原文");
});

test("材料包执行真实图片预检", async ({ page }) => {
  await page.locator('[data-nav="documents"]').click();
  await page.locator("#document-file").setInputFiles(
    path.join(__dirname, "..", "..", "demo_assets", "合成_医疗支出凭据_清晰.png"),
  );
  await page.locator("#document-consent").check();
  await page.locator("#check-document").click();
  await expect(page.locator("#document-result")).toContainText("已检查 1 份材料", {
    timeout: 45_000,
  });
  await expect(page.locator("#document-result")).toContainText(/质量|分/);
});

test("治理接口默认拒绝匿名访问并接受正确令牌", async ({ page }) => {
  await page.locator('[data-portal-role="staff"]').click();
  await page.locator('[data-nav="admin"]').click();
  await expect(page.locator("#toast-region .error")).toContainText("管理员令牌");
  await page.locator("#admin-token").fill("e2e-admin-token-32-characters-long");
  const response = page.waitForResponse(
    (item) => item.url().endsWith("/api/v1/admin/dashboard") && item.status() === 200,
  );
  await page.locator("#apply-admin-token").click();
  await response;
  await expect(page.locator("#admin-metrics")).not.toContainText("—");
});

test("核心页面通过WCAG A/AA自动扫描", async ({ page }) => {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(results.violations).toEqual([]);
});

test.describe("移动端与键盘", () => {
  const pixel = devices["Pixel 7"];
  test.use({
    viewport: pixel.viewport,
    userAgent: pixel.userAgent,
    deviceScaleFactor: pixel.deviceScaleFactor,
    isMobile: pixel.isMobile,
    hasTouch: pixel.hasTouch,
  });

  test("移动端导航可由键盘打开并关闭", async ({ page }) => {
    const menu = page.locator("#mobile-menu");
    await menu.focus();
    await page.keyboard.press("Enter");
    await expect(menu).toHaveAttribute("aria-expanded", "true");
    await page.keyboard.press("Escape");
    await expect(menu).toHaveAttribute("aria-expanded", "false");
    await expect(page.locator("#view-overview")).toBeVisible();
  });
});
