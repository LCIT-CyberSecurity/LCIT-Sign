import { expect, test, type Browser, type Page } from "@playwright/test";

// Fictional CrashTest identities of the mock OIDC provider. The stack must
// hold the CrashTests dataset (scripts/integration-seed.sh).
async function loginAs(page: Page, name: string) {
  await page.goto("/");
  await page.getByRole("link", { name: /Se connecter avec le SSO/ }).click();
  await page.getByRole("link", { name: new RegExp(name) }).click();
  // The login page also says "LCIT Sign": wait for something only a session shows.
  await expect(page.getByLabel("Compte et réglages")).toBeVisible();
}

test("a signer sees nothing of the operator and admin areas", async ({ page }) => {
  await loginAs(page, "Erwan");
  await expect(page.getByRole("link", { name: "Mes signatures" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Mes documents" })).toHaveCount(0); // one page, not two
  await expect(page.getByText("Administration")).toHaveCount(0);
  await page.goto("/admin/diagnostics");
  await expect(page).toHaveURL(/\/$/); // bounced back by the route guard
});

// A one-page PDF generated with pypdf (the server validates PDF structure).
const MINIMAL_PDF = Buffer.from(
  "JVBERi0xLjMKJeLjz9MKMSAwIG9iago8PAovUHJvZHVjZXIgKHB5cGRmKQo+PgplbmRvYmoKMiAwIG9iago8PAovVHlwZSAvUGFnZXMKL0NvdW50IDEKL0tpZHMgWyA0IDAgUiBdCj4+CmVuZG9iagozIDAgb2JqCjw8Ci9UeXBlIC9DYXRhbG9nCi9QYWdlcyAyIDAgUgo+PgplbmRvYmoKNCAwIG9iago8PAovVHlwZSAvUGFnZQovUmVzb3VyY2VzIDw8Cj4+Ci9NZWRpYUJveCBbIDAuMCAwLjAgMjAwIDIwMCBdCi9QYXJlbnQgMiAwIFIKPj4KZW5kb2JqCnhyZWYKMCA1CjAwMDAwMDAwMDAgNjU1MzUgZiAKMDAwMDAwMDAxNSAwMDAwMCBuIAowMDAwMDAwMDU0IDAwMDAwIG4gCjAwMDAwMDAxMTMgMDAwMDAgbiAKMDAwMDAwMDE2MiAwMDAwMCBuIAp0cmFpbGVyCjw8Ci9TaXplIDUKL1Jvb3QgMyAwIFIKL0luZm8gMSAwIFIKPj4Kc3RhcnR4cmVmCjI1NgolJUVPRgo=",
  "base64",
);

/** As an operator, publish a fresh document and ask `signerEmail` to sign it,
 *  so the test never depends on what earlier runs already signed. */
async function askToSign(browser: Browser, signerEmail: string, title: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await loginAs(page, "Diane");
  const api = context.request;

  const created = await api.post("/api/documents", {
    multipart: {
      title,
      version_label: "1.0",
      file: { name: "e2e.pdf", mimeType: "application/pdf", buffer: MINIMAL_PDF },
    },
  });
  expect(created.status()).toBe(201);
  const versionId = (await created.json()).versions[0].id as string;
  expect((await api.post(`/api/documents/versions/${versionId}/publish`)).status()).toBe(200);

  const users = (await (await api.get("/api/campaigns/_meta/users")).json()) as {
    id: string;
    email: string;
  }[];
  const signer = users.find((u) => u.email === signerEmail);
  expect(signer, `${signerEmail} must exist (run the seed first)`).toBeTruthy();

  const campaign = await (await api.post("/api/campaigns", { data: { name: title } })).json();
  await api.post(`/api/campaigns/${campaign.id}/documents`, {
    data: { document_version_id: versionId },
  });
  const launch = await api.post(`/api/campaigns/${campaign.id}/launch`, {
    data: { user_ids: [signer!.id] },
  });
  expect(launch.status()).toBe(200);
  await context.close();
}

test("a signer reads a document, consents and signs", async ({ page, browser }) => {
  const title = `E2E ${Date.now()}`;
  await askToSign(browser, "bob.dupont@lcit-test.local", title);

  await loginAs(page, "Bob");
  await page.getByRole("link", { name: new RegExp(title) }).click();

  const sign = page.getByRole("button", { name: /^Signer/ });
  await expect(sign).toBeDisabled(); // no signature without consent
  await page.getByRole("checkbox").check();
  await expect(sign).toBeEnabled();
  await sign.click();
  await expect(page.getByText("Document signé")).toBeVisible();
  await expect(page.getByTestId("signature-id")).toHaveText(/^SIG-[0-9A-F]{12}$/);
});

test("an administrator reaches the diagnostics page", async ({ page }) => {
  await loginAs(page, "Alice");
  await page.getByRole("link", { name: "Diagnostic" }).click();
  await expect(page.getByRole("heading", { name: /Diagnostic/ })).toBeVisible();
  await expect(page.getByTestId("check-database")).toBeVisible();
});

test("an operator sees the dashboard and can filter a campaign's follow-up", async ({ page }) => {
  await loginAs(page, "Diane");
  await page.getByRole("link", { name: "Suivi", exact: true }).click();
  await expect(page.getByRole("region", { name: "Tableau de bord" })).toBeVisible();
  await expect(page.getByTestId("stat-Signatures attendues")).not.toHaveText("0");

  await page.getByRole("link", { name: /Campagne sécurité 2026/ }).first().click();
  const table = page.locator("table.simple-table").first();
  await expect(table.getByRole("row")).not.toHaveCount(1);
  await page.getByLabel("Statut").selectOption("SIGNED");
  await expect(table.getByText("SIGNED").first()).toBeVisible();
  await expect(table.getByText("PENDING")).toHaveCount(0);
});

/** A draft request, ready to be worked on in the browser. */
async function newRequest(page: Page, name: string) {
  const campaign = await (await page.context().request.post("/api/campaigns", { data: { name } })).json();
  return campaign as { id: string };
}

async function userIdOf(page: Page, email: string) {
  const users = (await (await page.context().request.get("/api/campaigns/_meta/users")).json()) as {
    id: string;
    email: string;
  }[];
  const found = users.find((u) => u.email === email);
  expect(found, `${email} must exist (seed)`).toBeTruthy();
  return found!.id;
}

test("an operator targets a whole directory group in one click", async ({ page }) => {
  await loginAs(page, "Diane");
  const request = await newRequest(page, `Ciblage ${Date.now()}`);

  await page.goto(`/sign/${request.id}?step=1`);
  await page.getByLabel("Rechercher un groupe").fill("IT");
  await page.getByRole("button", { name: /^IT/ }).click();
  // The IT group of the CrashTests directory has four members.
  await expect(page.getByTestId("recipient-count")).toContainText("4 destinataire(s)");
});

test("the documents already in the library are offered alphabetically, drafts included", async ({
  page,
}) => {
  await loginAs(page, "Diane");
  const api = page.context().request;
  const stamp = Date.now();
  const upload = async (title: string, publish: boolean) => {
    const res = await api.post("/api/documents", {
      multipart: {
        title,
        version_label: "1.0",
        file: { name: "p.pdf", mimeType: "application/pdf", buffer: MINIMAL_PDF },
      },
    });
    const versionId = (await res.json()).versions[0].id as string;
    if (publish) await api.post(`/api/documents/versions/${versionId}/publish`);
  };
  await upload(`Zzz ordre ${stamp}`, true);
  await upload(`Aaa ordre ${stamp}`, true);
  await upload(`Mmm brouillon ${stamp}`, false);
  const request = await newRequest(page, `Ordre ${stamp}`);

  await page.goto(`/sign/${request.id}?step=2`);
  const picker = page.getByLabel("Document existant");
  await expect(picker.locator("option", { hasText: `Zzz ordre ${stamp}` })).toHaveCount(1);
  const ours = (await picker.locator("option").allTextContents()).filter((o) => o.includes(`${stamp}`));
  // A before M before Z; a draft is offered like the others (it is prepared in the flow).
  expect(ours).toEqual([
    `Aaa ordre ${stamp} — v1.0`,
    `Mmm brouillon ${stamp} — v1.0`,
    `Zzz ordre ${stamp} — v1.0`,
  ]);
});

test("an operator deletes an unused document but not a signed one", async ({ page }) => {
  await loginAs(page, "Diane");
  const api = page.context().request;
  const stamp = Date.now();
  const upload = async (title: string) => {
    const res = await api.post("/api/documents", {
      multipart: {
        title,
        version_label: "1.0",
        file: { name: "d.pdf", mimeType: "application/pdf", buffer: MINIMAL_PDF },
      },
    });
    return (await res.json()).versions[0].id as string;
  };
  const doomed = `Jetable ${stamp}`;
  await upload(doomed);

  await page.goto("/documents");
  await page.getByLabel("Rechercher un document").fill(doomed);
  const card = page.locator(".card", { hasText: doomed });
  await card.getByRole("button", { name: /Supprimer le document/ }).click();
  await expect(card).toBeVisible(); // the first click only asks
  await card.getByRole("button", { name: "Confirmer la suppression" }).click();
  await expect(page.locator(".card", { hasText: doomed })).toHaveCount(0);

  // A document that has been signed stays, with the reason, and cannot be deleted.
  await page.getByLabel("Rechercher un document").fill("Charte informatique 2026");
  const signed = page.locator(".card", { hasText: "Charte informatique 2026" }).first();
  await expect(signed.getByText(/Conservée/).first()).toBeVisible();
  await expect(signed.getByRole("button", { name: /Supprimer/ })).toHaveCount(0);
});

test("an operator sends a request through the screens; the RSSI signs first, then the recipient", async ({
  page,
  browser,
}) => {
  // Tall enough to drop onto the page without scrolling mid-drag.
  await page.setViewportSize({ width: 1500, height: 1100 });
  await loginAs(page, "Diane");
  const title = `Politique ${Date.now()}`;

  // The way in: a name, then the first screen.
  await page.goto("/sign");
  await page.getByLabel("Nom de la demande").fill(title);
  await page.getByRole("button", { name: "Commencer" }).click();

  // 1. Who signs, in order: Erwan (the RSSI) first, then every recipient; the recipients are Bob.
  await expect(page.getByTestId("signers-card")).toBeVisible();
  await page.getByRole("button", { name: /^Ajouter une personne$/ }).click();
  const first = page.getByLabel("Qui signe en position 1 ?");
  const erwanOption = first.locator("option", { hasText: "Erwan Petit" });
  await first.selectOption((await erwanOption.getAttribute("value")) as string);
  await expect(page.getByTestId("signers-status")).toContainText("Enregistré");
  await page.getByRole("button", { name: "Bob Dupont" }).click();
  await expect(page.getByTestId("recipient-count")).toContainText("1 destinataire(s)");
  await page.getByRole("button", { name: /Suivant : les documents/ }).click();

  // 2. The document: dropped here, then straight on to preparing it.
  await page.getByTestId("dropzone-input").setInputFiles({
    name: `${title}.pdf`,
    mimeType: "application/pdf",
    buffer: MINIMAL_PDF,
  });
  await expect(page.getByTestId("pending-files")).toContainText(title);
  await page.getByRole("button", { name: "Ajouter le document" }).click();

  // 3. Preparing: the editor is in the flow, with the signers of step 1 to give elements to.
  const overlay = page.getByTestId("overlay-1");
  await expect(overlay).toBeVisible();
  await expect(page.getByRole("tab", { name: new RegExp(title.slice(0, 10)) })).toBeVisible();
  await page.getByTestId("tool-SIGNATURE").dragTo(overlay, { targetPosition: { x: 200, y: 500 } });
  await page.getByTestId("tool-DATE").dragTo(overlay, { targetPosition: { x: 520, y: 500 } });
  await expect(page.getByTestId("role-1")).toContainText("Erwan Petit");
  await page.getByTestId("role-2").click();
  await expect(page.getByTestId("role-2")).toHaveAttribute("aria-pressed", "true");
  await page.getByTestId("tool-SIGNATURE").dragTo(overlay, { targetPosition: { x: 200, y: 300 } });
  const signatures = page.getByTestId("field-SIGNATURE");
  await expect(signatures).toHaveCount(2);
  await expect(signatures.nth(0)).toHaveAttribute("data-role", "1");
  await expect(signatures.nth(1)).toHaveAttribute("data-role", "2");
  await expect(page.getByTestId("prep-status")).toContainText("non enregistrées");

  // Move the first signature with the mouse, then save.
  const before = await signatures.nth(0).boundingBox();
  await page.mouse.move(before!.x + before!.width / 2, before!.y + before!.height / 2);
  await page.mouse.down();
  await page.mouse.move(before!.x + before!.width / 2 + 60, before!.y + before!.height / 2 - 40, { steps: 6 });
  await page.mouse.up();
  const after = await signatures.nth(0).boundingBox();
  expect(after!.x).toBeGreaterThan(before!.x + 40);
  await page.getByRole("button", { name: "Enregistrer" }).click();
  await expect(page.getByTestId("prep-status")).toContainText("Enregistré — 3 élément(s)");

  // It persists across a reload, and the keyboard deletes.
  await page.reload();
  await expect(page.getByTestId("field-SIGNATURE")).toHaveCount(2);
  await page.getByTestId("field-DATE").click();
  await page.keyboard.press("Delete");
  await expect(page.getByTestId("field-DATE")).toHaveCount(0);
  await page.getByRole("button", { name: /Terminer : vérifier et envoyer/ }).click();

  // 4. Review, then a confirmation: the first click only asks.
  const recap = page.getByTestId("recap-card");
  await expect(recap).toContainText("Erwan Petit");
  await expect(recap).toContainText("Chaque destinataire");
  await expect(recap).toContainText("2 élément(s) placé(s)");
  await page.getByRole("button", { name: "Envoyer pour signature" }).click();
  await expect(page.getByTestId("recap-card")).toBeVisible();
  await page.getByRole("button", { name: "Oui, envoyer maintenant" }).click();

  // 5. Sent: the signed documents come back here; nothing is signed yet.
  await expect(page.getByTestId("signed-step")).toBeVisible();
  await expect(page.getByTestId("outstanding-table")).toContainText("Erwan Petit");
  await expect(page.getByTestId("total-signed")).toHaveText("0");

  // Bob is not asked before Erwan has signed ("À venir"); Erwan, the RSSI, signs first.
  const bob = await browser.newContext();
  const bobPage = await bob.newPage();
  await loginAs(bobPage, "Bob");
  await expect(bobPage.getByTestId("upcoming")).toContainText(title);
  const erwan = await browser.newContext();
  const erwanPage = await erwan.newPage();
  await loginAs(erwanPage, "Erwan");
  await erwanPage.getByRole("link", { name: new RegExp(title) }).click();
  await erwanPage.getByRole("checkbox").check();
  await erwanPage.getByRole("button", { name: "Signer", exact: true }).click();
  await expect(erwanPage.getByTestId("signature-id")).toHaveText(/^SIG-[0-9A-F]{12}$/);

  // Now it is Bob's turn, with Erwan's signature already on his copy.
  await bobPage.reload();
  await bobPage.getByRole("link", { name: new RegExp(title) }).click();
  await bobPage.getByRole("checkbox").check();
  await bobPage.getByRole("button", { name: "Signer", exact: true }).click();
  await expect(bobPage.getByTestId("signature-id")).toHaveText(/^SIG-[0-9A-F]{12}$/);
  // The frame now shows his signed copy, not the bare original; and the signed PDF is one click away
  // on his list of documents.
  await expect(bobPage.locator(".pdf-viewer iframe")).toHaveAttribute("src", /\/preview\?v=[0-9a-f-]{36}/);
  await bobPage.goto("/");
  const signedCard = bobPage.getByTestId(`signed-${title}`);
  await expect(signedCard.getByRole("link", { name: "PDF signé" })).toHaveAttribute("href", /signed-pdf$/);
  await expect(signedCard.getByRole("link", { name: "Ouvrir" })).toHaveAttribute("href", /signed-pdf\?inline=true/);
  await bob.close();
  await erwan.close();

  // The operator sees both signed documents in the last step, with the proof and the export.
  await page.getByRole("button", { name: "Actualiser" }).click();
  await expect(page.getByTestId("total-signed")).toHaveText("2");
  await expect(page.getByTestId("signed-table")).toContainText("Erwan Petit");
  await expect(page.getByTestId("signed-table")).toContainText("Bob Dupont");
  await expect(page.getByRole("link", { name: /ZIP/ })).toHaveAttribute("href", /export\.zip\?campaign_ids=/);
  await expect(page.getByTestId("outstanding-table")).toContainText("Personne n'a de document en attente");
});

test("a signer fills the text the operator asked for, and it is stamped on the signed PDF", async ({
  page,
  browser,
}) => {
  const title = `Champ texte ${Date.now()}`;
  const context = await browser.newContext();
  const op = await context.newPage();
  await loginAs(op, "Diane");
  const api = context.request;
  const created = await api.post("/api/documents", {
    multipart: {
      title,
      version_label: "1.0",
      file: { name: "p.pdf", mimeType: "application/pdf", buffer: MINIMAL_PDF },
    },
  });
  const versionId = (await created.json()).versions[0].id as string;
  const placed = await api.put(`/api/documents/versions/${versionId}/fields`, {
    data: {
      fields: [
        { page: 1, x: 0.1, y: 0.7, width: 0.3, height: 0.06, kind: "SIGNATURE", role: 1 },
        { page: 1, x: 0.5, y: 0.7, width: 0.2, height: 0.04, kind: "DATE", role: 1 },
        { page: 1, x: 0.1, y: 0.5, width: 0.4, height: 0.04, kind: "TEXT", role: 1, label: "Fonction" },
      ],
    },
  });
  expect(placed.status()).toBe(200);
  await api.post(`/api/documents/versions/${versionId}/publish`);
  const users = (await (await api.get("/api/campaigns/_meta/users")).json()) as { id: string; email: string }[];
  const bob = users.find((u) => u.email === "bob.dupont@lcit-test.local")!;
  const campaign = await (await api.post("/api/campaigns", { data: { name: title } })).json();
  await api.post(`/api/campaigns/${campaign.id}/documents`, { data: { document_version_id: versionId } });
  await api.post(`/api/campaigns/${campaign.id}/launch`, { data: { user_ids: [bob.id] } });
  await context.close();

  await loginAs(page, "Bob");
  await page.getByRole("link", { name: new RegExp(title) }).click();
  const sign = page.getByRole("button", { name: "Signer", exact: true });
  await page.getByRole("checkbox").check();
  await expect(sign).toBeDisabled(); // "Fonction" is required and still empty
  await expect(page.getByText(/votre signature, la date de signature/)).toBeVisible();
  await page.getByLabel(/Fonction/).fill("Directeur général");
  await expect(sign).toBeEnabled();
  await sign.click();
  await expect(page.getByTestId("signature-id")).toHaveText(/^SIG-[0-9A-F]{12}$/);

  const signatureId = (await page.getByTestId("signature-id").textContent()) as string;
  expect(signatureId).toBeTruthy();
  const list = (await (await page.context().request.get("/api/signatures/me")).json()) as {
    id: string;
    display_id: string;
  }[];
  const mine = list.find((s) => s.display_id === signatureId)!;
  const evidence = await (await page.context().request.get(`/api/signatures/${mine.id}/evidence`)).json();
  expect(evidence.field_values.map((v: { kind: string }) => v.kind).sort()).toEqual(["DATE", "SIGNATURE", "TEXT"]);
  expect(evidence.field_values.find((v: { kind: string }) => v.kind === "TEXT").value).toBe("Directeur général");
  const verdict = await (await page.context().request.get(`/api/signatures/${mine.id}/verify`)).json();
  expect(verdict.valid).toBe(true);
});

test("the system account signs in with the default password and is reminded to change it", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByText("Compte système (administrateur local)").click();
  await page.getByLabel("Identifiant").fill("admin");
  await page.getByLabel("Mot de passe").fill("wrong-password");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("incorrect");

  await page.getByLabel("Mot de passe").fill("SecretPassword");
  await page.getByRole("button", { name: "Se connecter", exact: true }).click();
  await expect(page.getByLabel("Compte et réglages")).toBeVisible();

  // The reminder is there on every page, and the change dialog opens by itself.
  await expect(page.getByTestId("password-reminder")).toContainText("n'a pas été changé");
  await expect(page.getByRole("dialog", { name: /Changer le mot de passe/ })).toBeVisible();
  await page.getByRole("button", { name: "Plus tard" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByTestId("password-reminder")).toBeVisible(); // still nagging
  await page.goto("/admin/users");
  await expect(page.getByTestId("password-reminder")).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0); // not re-opened by a page load

  // A weak new password is refused (the account is left as it was).
  await page.getByRole("button", { name: "Le changer maintenant" }).click();
  await page.getByLabel("Mot de passe actuel").fill("SecretPassword");
  await page.getByLabel("Nouveau mot de passe", { exact: true }).fill("password1234");
  await page.getByLabel("Confirmer le nouveau mot de passe").fill("password1234");
  await page.getByRole("button", { name: "Changer le mot de passe" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "refusé" })).toBeVisible();
});

test("an administrator adds, disables and deletes a user from the interface", async ({ page }) => {
  await loginAs(page, "Alice");
  const email = `e2e.${Date.now()}@lcit-test.local`;
  await page.goto("/admin/users");
  const form = page.getByRole("form", { name: "Ajouter un utilisateur" });
  await form.getByLabel("Adresse e-mail").fill(email);
  await form.getByLabel("Prénom").fill("Essai");
  await form.getByLabel("Nom", { exact: true }).fill("Navigateur");
  await form.getByRole("button", { name: "Ajouter" }).click();
  const row = page.getByTestId(`user-${email}`);
  await expect(row).toContainText("Essai Navigateur");
  await expect(row).toContainText("Ajouté à la main");
  await expect(row).toContainText("Actif");

  await row.getByRole("button", { name: "Désactiver" }).click();
  await row.getByRole("button", { name: "Confirmer la désactivation" }).click();
  await expect(row).toContainText("Désactivé");
  await row.getByRole("button", { name: "Réactiver" }).click();
  await expect(row).toContainText("Actif");

  await row.getByRole("button", { name: /Supprimer/ }).click();
  await row.getByRole("button", { name: "Confirmer la suppression" }).click();
  await expect(page.getByTestId(`user-${email}`)).toHaveCount(0);

  // People who signed are kept, with the reason.
  await page.getByLabel("Rechercher un utilisateur").fill("erwan.petit");
  const erwan = page.getByTestId("user-erwan.petit@lcit-test.local");
  await expect(erwan).toContainText("Conservé");
  await expect(erwan.getByRole("button", { name: /Supprimer/ })).toHaveCount(0);
});

test("directory settings explain themselves with a bubble and an example", async ({ page }) => {
  await loginAs(page, "Alice");
  await page.goto("/admin/directory");
  await page.getByTestId("source-entra").getByRole("button", { name: "Configurer" }).click();
  const hint = page.getByRole("button", { name: "Aide : ID du tenant" });
  await hint.hover();
  await expect(page.getByRole("tooltip").filter({ hasText: "ID de locataire" })).toBeVisible();
  await expect(page.getByRole("tooltip").filter({ hasText: "73405479-f042" })).toBeVisible();
});

test("an operator drops several PDFs on the documents page", async ({ page }) => {
  await loginAs(page, "Diane");
  const stamp = Date.now();
  await page.goto("/documents");
  await page.getByTestId("dropzone-input").setInputFiles([
    { name: `contrat_alpha-${stamp}.pdf`, mimeType: "application/pdf", buffer: MINIMAL_PDF },
    { name: `contrat_beta-${stamp}.pdf`, mimeType: "application/pdf", buffer: MINIMAL_PDF },
    { name: `notes-${stamp}.txt`, mimeType: "text/plain", buffer: Buffer.from("not a pdf") },
  ]);
  // Nothing is sent until the operator confirms with "Importer".
  await expect(page.getByTestId("pending-files")).toContainText(`contrat_beta-${stamp}.pdf`);
  await page.getByRole("button", { name: "Importer 3 documents" }).click();
  const results = page.getByTestId("upload-results");
  await expect(results).toContainText(`contrat_alpha-${stamp}.pdf`);
  await expect(results.locator("li").nth(0)).toContainText("ajouté à la bibliothèque");
  await expect(results.locator("li").nth(1)).toContainText("ajouté à la bibliothèque");
  await expect(results.locator("li").nth(2)).toContainText("Formats acceptés");

  // Each became its own draft document, titled from its file name.
  await page.getByLabel("Rechercher un document").fill(`${stamp}`);
  await expect(page.locator(".card", { hasText: `Contrat alpha ${stamp}` })).toHaveCount(1);
  await expect(page.locator(".card", { hasText: `Contrat beta ${stamp}` })).toHaveCount(1);
});

test("a signer asked for several documents of one campaign signs them all in one click", async ({
  page,
  browser,
}) => {
  const stamp = Date.now();
  const context = await browser.newContext();
  const op = await context.newPage();
  await loginAs(op, "Diane");
  const api = context.request;
  const erwan = await userIdOf(op, "erwan.petit@lcit-test.local");
  const campaign = await (await api.post("/api/campaigns", { data: { name: `Toutes ${stamp}` } })).json();
  for (const name of ["Alpha", "Beta", "Gamma"]) {
    const created = await api.post("/api/documents", {
      multipart: {
        title: `${name} ${stamp}`,
        version_label: "1.0",
        file: { name: "p.pdf", mimeType: "application/pdf", buffer: MINIMAL_PDF },
      },
    });
    const versionId = (await created.json()).versions[0].id as string;
    // The same question on every document: asked once.
    await api.put(`/api/documents/versions/${versionId}/fields`, {
      data: {
        fields: [
          { page: 1, x: 0.1, y: 0.7, width: 0.3, height: 0.06, kind: "SIGNATURE", role: 1 },
          { page: 1, x: 0.1, y: 0.5, width: 0.4, height: 0.04, kind: "TEXT", role: 1, label: "Fonction", group_key: "fonction" },
        ],
      },
    });
    await api.post(`/api/campaigns/${campaign.id}/documents`, { data: { document_version_id: versionId } });
  }
  expect((await api.post(`/api/campaigns/${campaign.id}/launch`, { data: { user_ids: [erwan] } })).status()).toBe(200);
  await context.close();

  await loginAs(page, "Erwan");
  await page.getByTestId("sign-all-link").filter({ hasText: `Toutes ${stamp}` }).click();
  await expect(page.getByTestId("sign-all-documents")).toContainText("3 document(s) à signer");
  // "Fonction" is on all three documents but asked once.
  await expect(page.getByTestId("sign-all-inputs").locator("input")).toHaveCount(1);
  const button = page.getByRole("button", { name: /Signer les 3 documents/ });
  await page.getByRole("checkbox").check();
  await expect(button).toBeDisabled(); // the required answer is missing
  await page.getByLabel(/^Fonction/).fill("RSSI");
  await button.click();
  await expect(page.getByTestId("sign-all-done")).toContainText("3 document(s) signé(s)");
});

test("the signed documents are in Suivi, for one campaign or several, with the export", async ({ page }) => {
  await loginAs(page, "Diane");
  await page.goto("/campaigns?tab=signed");
  await expect(page.getByRole("tab", { name: "Documents signés" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("signed-table")).toBeVisible();
  const total = Number(await page.getByTestId("total-signed").textContent());
  expect(total).toBeGreaterThan(0);
  await expect(page.getByRole("link", { name: /ZIP/ })).toHaveAttribute("href", /export\.zip/);

  // Narrowing to one campaign changes the list and the export with it.
  await page.getByRole("button", { name: "Campagne sécurité 2026" }).click();
  await expect(page.getByRole("link", { name: /ZIP/ })).toHaveAttribute("href", /campaign_ids=/);
  await page.getByLabel("Rechercher").fill("zzz-personne-inconnue");
  await expect(page.getByText("Aucun document signé pour cette sélection.")).toBeVisible();

  // The old address still leads there, and the menu has no separate entry any more.
  await page.goto("/signed");
  await expect(page).toHaveURL(/\/campaigns\?tab=signed/);
  await expect(page.getByRole("link", { name: "Documents signés" })).toHaveCount(0);
});

test("an administrator replaces the logo, and goes back to the LCIT one", async ({ page }) => {
  await loginAs(page, "Alice");
  const lcit = page.locator(".brand-logo");
  await expect(lcit).toHaveAttribute("src", "/lcit-mark.png");

  await page.goto("/admin/branding");
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAJklEQVR4nO3OMQEAAAgDoK1/aM3g4QcFmJTJ4XBYLBaLxWKxWCwWiwXx0AJ1AAGV1GJKAAAAAElFTkSuQmCC",
    "base64",
  );
  await page.getByTestId("logo-input").setInputFiles({ name: "logo.png", mimeType: "image/png", buffer: png });
  await expect(page.getByText(/dès maintenant en haut à gauche/)).toBeVisible();
  // Top left, without a reload.
  await expect(page.locator(".brand-logo")).toHaveAttribute("src", /\/api\/branding\/logo\?v=/);

  // The sign-in page (before anyone is signed in) shows it too.
  const visitor = await page.context().browser()!.newContext();
  const login = await visitor.newPage();
  await login.goto("/");
  await expect(login.locator(".auth-company img")).toHaveAttribute("src", /\/api\/branding\/logo\?v=/);
  await visitor.close();

  await page.getByRole("button", { name: /Revenir au logo LCIT/ }).click();
  await page.getByRole("button", { name: /Oui, revenir au logo LCIT/ }).click();
  await expect(page.locator(".brand-logo")).toHaveAttribute("src", "/lcit-mark.png");
});

test("a person from outside the company is added by address and marked as such", async ({ page }) => {
  await loginAs(page, "Diane");
  const request = await newRequest(page, `Externe ${Date.now()}`);
  await page.goto(`/sign/${request.id}?step=1`);
  await page.getByRole("button", { name: /Ajouter une personne extérieure/ }).first().click();
  const email = `jean.${Date.now()}@partenaire.test`;
  await page.getByLabel("Prénom").fill("Jean");
  await page.getByLabel("Nom", { exact: true }).fill("Client");
  await page.getByLabel("Adresse e-mail").fill(email);
  await page.getByRole("button", { name: "Ajouter", exact: true }).click();
  // He joins the signers at once, marked as outside.
  await expect(page.getByLabel("Qui signe en position 1 ?")).toContainText("Jean Client");
  await expect(page.getByLabel("Qui signe en position 1 ?").locator("option:checked")).toContainText("(externe)");
  await expect(page.getByTestId("signers-status")).toContainText("Enregistré");
});

test("the sign-in page offers Entra, Google and LDAP, and says which are not set up here", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: /Se connecter avec le SSO/ }).click();
  await expect(page.getByRole("link", { name: /Erwan/ })).toBeVisible(); // the test identities stay
  await expect(page.getByText("Microsoft Entra ID — non configuré sur ce serveur")).toBeVisible();
  await expect(page.getByText("Google — non configuré sur ce serveur")).toBeVisible();
  await expect(page.getByText("LDAP / Active Directory — non configuré sur ce serveur")).toBeVisible();
  await expect(page.locator('input[type="password"]')).toHaveCount(0);
});

test("a Word document is refused in words when the converter is not there", async ({ page }) => {
  await loginAs(page, "Diane");
  await page.goto("/documents");
  await page.getByTestId("dropzone-input").setInputFiles({
    name: `rapport-${Date.now()}.docx`,
    mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    buffer: Buffer.from("PK\u0003\u0004 not really a document"),
  });
  await page.getByRole("button", { name: "Importer le document" }).click();
  // Refused in words (here it is not even a real document); never a blank failure.
  await expect(page.getByTestId("upload-results")).toContainText(/pas un document|pas activée/);
});
