import { test, expect } from "@playwright/test";

/**
 * Jornada crítica: registrar, logar, enfileirar e-mail, ver o job_id aparecer.
 * Exercita o caminho feliz end-to-end: UI -> Vite proxy -> API -> DB.
 */
test("registrar → login → enfileirar job aparece no Dashboard", async ({ page, request }) => {
  const email = `e2e-${Date.now()}@example.com`;
  const password = "supersecret123";

  // 1. Register via API (mais rápido que UI; UI tb testada no smoke)
  const reg = await request.post("/api/v1/auth/register", {
    data: { email, password, full_name: "E2E User" },
  });
  expect(reg.status()).toBe(201);

  // 2. Login pela UI
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Senha").fill(password);
  await page.getByRole("button", { name: /entrar/i }).click();

  // 3. Cai no /dashboard
  await expect(page).toHaveURL(/\/dashboard$/);

  // 4. Vê a saudação
  await expect(page.getByText(email)).toBeVisible();

  // 5. Clica em "Enfileirar e-mail"
  await page.getByRole("button", { name: /enfileirar/i }).click();

  // 6. UI mostra o job_id retornado
  const jobIdLocator = page.getByText(/Último job:/);
  await expect(jobIdLocator).toBeVisible({ timeout: 5_000 });
});