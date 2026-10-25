import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';

// D2/D3 browser acceptance against explicit MSW, not the D4 real-backend gate.
test('report → evidence → copy → diagnosis → safe Markdown download', async ({ page }, info) => {
  await page.goto('/');
  await expect(page.getByText(/Демонстрация MSW/)).toBeVisible();
  await page.getByLabel('URL публичного GitHub-репозитория').fill('https://github.com/repodoctor-fixtures/python-cli-demo');
  await page.getByRole('button', { name: 'Анализировать', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'python-cli-demo' })).toBeVisible();
  await page.getByRole('region', { name: 'Сведения о репозитории' }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath('report-desktop.png') });
  await page.getByRole('link', { name: 'requirements.txt:1–3', exact: true }).first().click();
  await expect(page.locator('details[open]').filter({ hasText: 'requirements.txt' }).first()).toBeVisible();
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.getByRole('button', { name: 'Скопировать команду' }).first().click();
  await expect(page.getByText('Команда скопирована.', { exact: true })).toBeVisible();
  await page.getByLabel('Лог ошибки', { exact: true }).fill('RAW_LOG_PRIVATE_SENTINEL');
  await page.getByLabel('Команда, вызвавшая ошибку (необязательно)').fill('RAW_COMMAND_PRIVATE_SENTINEL');
  await page.getByRole('button', { name: 'Разобрать ошибку', exact: true }).click();
  const result = page.getByRole('region', { name: 'Результат диагностики' });
  await expect(result.getByRole('heading', { name: 'Диагностика ошибки', exact: true })).toBeVisible();
  await expect(result).toContainText('python-dotenv');
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Скачать Markdown' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('repodoctor-repodoctor-fixtures-python-cli-demo.md');
  const markdown = await readFile((await download.path())!, 'utf8');
  expect(markdown).toContain('## Диагностика');
  expect(markdown).toContain('Источник: fixture');
  expect(markdown).not.toContain('RAW_LOG_PRIVATE_SENTINEL');
  expect(markdown).not.toContain('RAW_COMMAND_PRIVATE_SENTINEL');
  await page.setViewportSize({ width: 375, height: 812 });
  await page.getByRole('region', { name: 'План запуска' }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath('plan-mobile.png') });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('new analysis clears the log and received diagnosis', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('URL публичного GitHub-репозитория').fill('https://github.com/repodoctor-fixtures/python-cli-demo');
  await page.getByRole('button', { name: 'Анализировать', exact: true }).click();
  await page.getByLabel('Лог ошибки', { exact: true }).fill('first raw log');
  await page.getByRole('button', { name: 'Разобрать ошибку', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Результат диагностики' })).toBeVisible();
  await page.getByRole('button', { name: 'Анализировать', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('Ответ получен');
  await expect(page.getByLabel('Лог ошибки', { exact: true })).toHaveValue('');
  await expect(page.getByRole('region', { name: 'Результат диагностики' })).toHaveCount(0);
});
