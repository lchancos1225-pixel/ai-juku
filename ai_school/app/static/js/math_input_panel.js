(function () {
  const BUTTONS = [
    ["1/2", "1/2", "frac"], ["1/3", "1/3", "frac"], ["1/4", "1/4", "frac"],
    ["a/b", "/", "frac"],
    ["x\u00b2", "^2", "power"], ["x\u207f", "^", "power"],
    ["\u221a", "sqrt(", "root"],
    ["\u00d7", "*", "op"], ["\u00f7", "/", "op"], ["\uff0d", "-", "op"],
    ["()", "()", "bracket"],
    ["=", "=", "op"],
    ["\u232b", "__BS__", "ctrl"],
  ];

  function insertAtCursor(input, text) {
    if (text === "__BS__") {
      const s = input.selectionStart, e = input.selectionEnd;
      if (s !== e) {
        input.value = input.value.slice(0, s) + input.value.slice(e);
        input.selectionStart = input.selectionEnd = s;
      } else if (s > 0) {
        input.value = input.value.slice(0, s - 1) + input.value.slice(s);
        input.selectionStart = input.selectionEnd = s - 1;
      }
    } else {
      const s = input.selectionStart, e = input.selectionEnd;
      const before = input.value.slice(0, s);
      const after = input.value.slice(e);
      input.value = before + text + after;
      const cur = s + text.length;
      input.selectionStart = input.selectionEnd = cur;
    }
    input.dispatchEvent(new Event("input"));
    input.focus();
  }

  function buildPanel(targetInput) {
    const panel = document.createElement("div");
    panel.className = "math-input-panel";
    panel.style.cssText = [
      "display:flex",
      "flex-wrap:wrap",
      "gap:6px",
      "padding:8px",
      "background:var(--surface,#f5f5f5)",
      "border:1px solid var(--border,#ddd)",
      "border-radius:8px",
      "margin-top:6px",
    ].join(";");

    BUTTONS.forEach(([label, ins, grp]) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = label;
      btn.dataset.group = grp;
      btn.style.cssText = [
        "min-width:44px",
        "min-height:44px",
        "padding:4px 10px",
        "border-radius:6px",
        "border:1px solid var(--border,#ccc)",
        "background:var(--card-bg,#fff)",
        "font-size:1rem",
        "cursor:pointer",
      ].join(";");
      btn.addEventListener("click", () => insertAtCursor(targetInput, ins));
      panel.appendChild(btn);
    });

    return panel;
  }

  function init() {
    const input = document.getElementById("answer-input")
      || (() => {
        const el = document.getElementById("answer") || document.querySelector("input[name='answer']");
        return (el && el.type !== "hidden") ? el : null;
      })();
    if (!input) return;

    const panel = buildPanel(input);
    input.insertAdjacentElement("afterend", panel);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
