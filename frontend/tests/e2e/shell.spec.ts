import { expect, test } from '@playwright/test';

test('D1 mocked browser flow and narrow layout', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText(/Демонстрация MSW/)).toBeVisible();
  await page.getByLabel('URL публичного GitHub-репозитория').fill('https://github.com/repodoctor-fixtures/python-cli-demo');
  await page.getByRole('button', { name: 'Анализировать', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('Ответ получен');
  await expect(page.getByRole('heading', { name: 'python-cli-demo' })).toBeVisible();
  await expect(page.getByText(/Источник: fixture/)).toBeVisible();
  await page.setViewportSize({ width: 375, height: 812 });
  await expect(page.getByLabel('URL публичного GitHub-репозитория')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('unknown API endpoints fail rather than returning a mock success', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText(/Демонстрация MSW/)).toBeVisible();
  const result = await page.evaluate(async () => {
    try { const response = await fetch('/api/v1/analysis', { method: 'POST' }); return response.ok ? 'unexpected success' : 'rejected'; }
    catch { return 'rejected'; }
  });
  expect(result).toBe('rejected');
});
