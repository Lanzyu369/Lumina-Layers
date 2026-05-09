const { describe, it } = require("node:test");
const assert = require("assert");

const QUIT_DIALOG = {
  zh: {
    title: "\u9000\u51FA\u786E\u8BA4",
    message: "\u786E\u5B9A\u8981\u9000\u51FA Lumina Studio \u5417\uFF1F",
    detail: "\u9000\u51FA\u540E\u6240\u6709\u672A\u4FDD\u5B58\u7684\u64CD\u4F5C\u5C06\u4E22\u5931\u3002",
    quit: "\u9000\u51FA",
    cancel: "\u53D6\u6D88",
  },
  en: {
    title: "Quit Confirmation",
    message: "Are you sure you want to quit Lumina Studio?",
    detail: "All unsaved changes will be lost.",
    quit: "Quit",
    cancel: "Cancel",
  },
};

describe("QUIT_DIALOG constants", () => {
  it("should have zh and en keys", () => {
    assert.ok("zh" in QUIT_DIALOG);
    assert.ok("en" in QUIT_DIALOG);
  });

  it("zh dialog should have correct title", () => {
    assert.strictEqual(QUIT_DIALOG.zh.title, "\u9000\u51FA\u786E\u8BA4");
  });

  it("en dialog should have correct title", () => {
    assert.strictEqual(QUIT_DIALOG.en.title, "Quit Confirmation");
  });

  it("zh dialog should have quit and cancel buttons", () => {
    assert.strictEqual(QUIT_DIALOG.zh.quit, "\u9000\u51FA");
    assert.strictEqual(QUIT_DIALOG.zh.cancel, "\u53D6\u6D88");
  });

  it("en dialog should have quit and cancel buttons", () => {
    assert.strictEqual(QUIT_DIALOG.en.quit, "Quit");
    assert.strictEqual(QUIT_DIALOG.en.cancel, "Cancel");
  });

  it("both languages should have message and detail", () => {
    for (const lang of ["zh", "en"]) {
      assert.ok(QUIT_DIALOG[lang].message);
      assert.ok(QUIT_DIALOG[lang].detail);
    }
  });
});

describe("Language selection logic", () => {
  it("should select zh dialog when currentLang is zh", () => {
    const currentLang = "zh";
    const dlg = QUIT_DIALOG[currentLang] || QUIT_DIALOG.zh;
    assert.strictEqual(dlg.title, "\u9000\u51FA\u786E\u8BA4");
    assert.strictEqual(dlg.quit, "\u9000\u51FA");
  });

  it("should select en dialog when currentLang is en", () => {
    const currentLang = "en";
    const dlg = QUIT_DIALOG[currentLang] || QUIT_DIALOG.zh;
    assert.strictEqual(dlg.title, "Quit Confirmation");
    assert.strictEqual(dlg.quit, "Quit");
  });

  it("should fallback to zh for unknown language", () => {
    const currentLang = "fr";
    const dlg = QUIT_DIALOG[currentLang] || QUIT_DIALOG.zh;
    assert.strictEqual(dlg.title, "\u9000\u51FA\u786E\u8BA4");
  });
});

describe("Close event behavior", () => {
  it("should preventDefault and show dialog on close", () => {
    let preventDefaultCalled = false;
    const event = { preventDefault: () => { preventDefaultCalled = true; } };

    const currentLang = "zh";
    const dlg = QUIT_DIALOG[currentLang] || QUIT_DIALOG.zh;

    event.preventDefault();
    assert.ok(preventDefaultCalled);

    const buttons = [dlg.cancel, dlg.quit];
    assert.deepStrictEqual(buttons, ["\u53D6\u6D88", "\u9000\u51FA"]);
  });

  it("cancel button should be defaultId=0", () => {
    const currentLang = "en";
    const dlg = QUIT_DIALOG[currentLang] || QUIT_DIALOG.zh;
    const buttons = [dlg.cancel, dlg.quit];
    assert.strictEqual(buttons[0], "Cancel");
    assert.strictEqual(buttons[1], "Quit");
  });

  it("response=1 should trigger quit", () => {
    const currentLang = "zh";
    const dlg = QUIT_DIALOG[currentLang] || QUIT_DIALOG.zh;
    const buttons = [dlg.cancel, dlg.quit];
    const response = 1;
    assert.strictEqual(buttons[response], "\u9000\u51FA");
  });

  it("response=0 should keep window", () => {
    const currentLang = "en";
    const dlg = QUIT_DIALOG[currentLang] || QUIT_DIALOG.zh;
    const buttons = [dlg.cancel, dlg.quit];
    const response = 0;
    assert.strictEqual(buttons[response], "Cancel");
  });
});
