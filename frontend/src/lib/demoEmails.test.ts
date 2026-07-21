import { describe, expect, it } from "vitest";
import { makeTxn } from "@/test/factories";
import { buildDemoEmail } from "./demoEmails";

const mira = {
  forwarded_to: "mira.tidings@example.com",
  name: "Mira Lin Chen",
};

describe("buildDemoEmail", () => {
  it("RBC purchase carries merchant, amount, persona card, and spelled-out date", () => {
    const email = buildDemoEmail(
      makeTxn({
        ...mira,
        date_file_name: "2026.03.19_22.12_demo_a.eml",
        date: "03/19/2026 22:12 PST",
        amount: 7.63,
        company: "Tim Hortons King & Strachan",
        institution: "RBC",
        transaction_type: "purchase",
      })
    );
    expect(email.body).toContain("Tim Hortons King & Strachan");
    expect(email.body).toContain("$7.63");
    expect(email.body).toContain("************7126");
    expect(email.body).toContain("March 19, 2026");
    expect(email.from_email).toBe("alerts@rbc.com");
    expect(email.to_email).toBe("mira.tidings@example.com");
  });

  it("CIBC preauth reads as a pre-authorized payment notice", () => {
    const email = buildDemoEmail(
      makeTxn({
        ...mira,
        date: "03/02/2026 12:02 PST",
        amount: 2150,
        company: "Liberty Market Lofts",
        institution: "CIBC",
        transaction_type: "preauth",
        category: "rent",
      })
    );
    expect(email.subject).toContain("pre-authorized");
    expect(email.body).toContain("preauthorized payment of $2,150.00 to Liberty Market Lofts");
    expect(email.body).toContain("ending in 3308");
    expect(email.body).toContain("Dear Mira,");
  });

  it("income e-transfer is an incoming Interac auto-deposit notice", () => {
    const email = buildDemoEmail(
      makeTxn({
        ...mira,
        date: "03/01/2026 09:00 PST",
        amount: 2400,
        company: "Ridge Studio Retainer",
        institution: "CIBC",
        transaction_type: "e-transfer",
        category: "income",
      })
    );
    expect(email.from_email).toBe("notify@payments.interac.ca");
    expect(email.body).toContain("Ridge Studio Retainer has sent you a money transfer");
    expect(email.body).toContain("$2,400.00 (CAD)");
    expect(email.body).toContain("automatically deposited");
    expect(email.body).toContain("Interac Corp.");
  });

  it("non-income e-transfer is an outgoing transfer with the comment as message", () => {
    const email = buildDemoEmail(
      makeTxn({
        ...mira,
        amount: 180,
        company: "Dana Okafor",
        institution: "CIBC",
        transaction_type: "e-transfer",
        category: "miscellaneous",
        comment: "pottery class deposit",
      })
    );
    expect(email.body).toContain("you sent to Dana Okafor has been successfully deposited");
    expect(email.body).toContain("Message: pottery class deposit");
  });

  it("Simplii and Tangerine purchases carry their own card constants", () => {
    const simplii = buildDemoEmail(
      makeTxn({ ...mira, institution: "Simplii", company: "Metro Liberty Village", amount: 54.1 })
    );
    expect(simplii.body).toContain("ending in 9054");
    expect(simplii.body).toContain("Metro Liberty Village");

    const tangerine = buildDemoEmail(
      makeTxn({ ...mira, institution: "Tangerine", company: "Air Canada", amount: 612.4 })
    );
    expect(tangerine.subject).toContain("Orange Alert");
    expect(tangerine.body).toContain("ending in 6611");
    expect(tangerine.body).toContain("$612.40");
  });

  it("CIBC deposit reads as a credit to the account", () => {
    const email = buildDemoEmail(
      makeTxn({
        ...mira,
        amount: 2821.44,
        company: "Northwind Labs Retainer",
        institution: "CIBC",
        transaction_type: "deposit",
        category: "income",
      })
    );
    expect(email.body).toContain("deposit of $2,821.44 from Northwind Labs Retainer");
    expect(email.body).toContain("credited to your CIBC account");
  });

  it("rows without a known institution get the manual-entry stand-in", () => {
    const email = buildDemoEmail(
      makeTxn({
        ...mira,
        date_file_name: "2026.03.10_12.00.00_demo_manual_x.eml",
        institution: null,
        company: "Farmers market",
        amount: 23.5,
      })
    );
    expect(email.subject).toContain("Manual entry");
    expect(email.body).toContain("Farmers market");
    expect(email.body).toContain("$23.50");
    expect(email.body).toContain("added by hand");
  });

  it("is deterministic per row", () => {
    const tx = makeTxn({ ...mira, institution: "CIBC", transaction_type: "e-transfer" });
    expect(buildDemoEmail(tx)).toEqual(buildDemoEmail(tx));
  });

  it("never emits the old demo stub copy", () => {
    for (const institution of ["RBC", "CIBC", "Simplii", "Tangerine", null]) {
      for (const type of ["purchase", "preauth", "e-transfer", "deposit", "withdrawal"]) {
        const email = buildDemoEmail(makeTxn({ ...mira, institution, transaction_type: type }));
        expect(email.body).not.toContain("not available in the demo");
        expect(email.subject).not.toContain("[Demo]");
        expect(email.body).toBeTruthy();
      }
    }
  });
});
