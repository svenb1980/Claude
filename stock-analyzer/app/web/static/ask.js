/* Vraag Claude: keeps the conversation in this browser tab and streams answers from /api/ask.
   Answers are built with DOM nodes only, so text from the model can never become HTML. */
(function () {
  "use strict";
  const root = document.getElementById("ask");
  if (!root) return;
  const text = root.dataset;
  const log = document.getElementById("ask-log");
  const form = document.getElementById("ask-form");
  const question = document.getElementById("ask-question");
  const scope = document.getElementById("ask-scope");
  const send = document.getElementById("ask-send");
  const errorBox = document.getElementById("ask-error");
  const examples = document.getElementById("ask-examples");
  const preview = document.getElementById("ask-preview");
  const previewText = document.getElementById("ask-preview-text");
  const maxMessages = Number(text.maxMessages);
  const RULE = /^\s*(-{3,}|\*{3,}|_{3,})\s*$/;

  let messages = [];
  let busy = false;
  try {
    messages = JSON.parse(sessionStorage.getItem(text.store) || "[]");
  } catch (e) {
    messages = [];
  }

  function save() {
    sessionStorage.setItem(text.store, JSON.stringify(messages));
  }

  function inline(parent, line) {
    const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
    let last = 0;
    for (const match of line.matchAll(pattern)) {
      if (match.index > last) parent.append(line.slice(last, match.index));
      const token = match[0];
      let node;
      if (token.startsWith("**")) {
        node = document.createElement("strong");
        node.textContent = token.slice(2, -2);
      } else if (token.startsWith("`")) {
        node = document.createElement("code");
        node.textContent = token.slice(1, -1);
      } else {
        node = document.createElement("em");
        node.textContent = token.slice(1, -1);
      }
      parent.append(node);
      last = match.index + token.length;
    }
    if (last < line.length) parent.append(line.slice(last));
  }

  function tableCells(line) {
    return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
  }

  function renderMarkdown(target, source) {
    target.replaceChildren();
    const lines = source.split("\n");
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) {
        i += 1;
      } else if (RULE.test(line)) {
        target.append(document.createElement("hr"));
        i += 1;
      } else if (/^#{1,6}\s/.test(line)) {
        const heading = document.createElement("h3");
        inline(heading, line.replace(/^#+\s*/, ""));
        target.append(heading);
        i += 1;
      } else if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1] || "")) {
        const table = document.createElement("table");
        const head = table.createTHead().insertRow();
        for (const cell of tableCells(line)) {
          const th = document.createElement("th");
          inline(th, cell);
          head.append(th);
        }
        const body = table.createTBody();
        i += 2;
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
          const row = body.insertRow();
          for (const cell of tableCells(lines[i])) inline(row.insertCell(), cell);
          i += 1;
        }
        target.append(table);
      } else if (/^\s*([-*•]|\d+[.)])\s+/.test(line)) {
        const ordered = /^\s*\d/.test(line);
        const list = document.createElement(ordered ? "ol" : "ul");
        while (i < lines.length && /^\s*([-*•]|\d+[.)])\s+/.test(lines[i])) {
          const item = document.createElement("li");
          inline(item, lines[i].replace(/^\s*([-*•]|\d+[.)])\s+/, ""));
          list.append(item);
          i += 1;
        }
        target.append(list);
      } else {
        const paragraph = document.createElement("p");
        const parts = [];
        while (i < lines.length && lines[i].trim() && !RULE.test(lines[i]) && !/^(#{1,6}\s|\s*([-*•]|\d+[.)])\s+|\s*\|)/.test(lines[i])) {
          parts.push(lines[i].trim());
          i += 1;
        }
        if (!parts.length) {
          // A line that only looks like the start of a table: show it as plain text.
          parts.push(line.trim());
          i += 1;
        }
        inline(paragraph, parts.join(" "));
        target.append(paragraph);
      }
    }
  }

  function addMessage(who) {
    const wrapper = document.createElement("div");
    wrapper.className = "ask-msg";
    const name = document.createElement("div");
    name.className = "ask-who";
    name.textContent = who;
    const body = document.createElement("div");
    body.className = "ask-body";
    wrapper.append(name, body);
    log.append(wrapper);
    return { wrapper, body };
  }

  function addUser(content) {
    const { body } = addMessage(text.textYou);
    body.classList.add("ask-user");
    body.textContent = content;
  }

  function answerText(blocks) {
    return blocks.filter((b) => b.type === "text").map((b) => b.text).join("");
  }

  function addMeta(wrapper, content) {
    const meta = document.createElement("div");
    meta.className = "ask-meta muted small";
    meta.textContent = content;
    wrapper.append(meta);
  }

  function showError(message) {
    errorBox.textContent = message || "";
    errorBox.hidden = !message;
  }

  function refreshControls() {
    examples.hidden = messages.length > 0;
    const full = messages.length + 1 > maxMessages;
    send.disabled = busy || full;
    if (full) showError(text.textFull);
  }

  function restore() {
    log.replaceChildren();
    for (const message of messages) {
      if (message.role === "user") {
        addUser(message.content);
      } else {
        renderMarkdown(addMessage(text.textClaude).body, answerText(message.content));
      }
    }
    refreshControls();
  }

  async function loadPreview() {
    if (!preview.open) return;
    try {
      const response = await fetch("/api/ask/context?scope=" + encodeURIComponent(scope.value));
      const data = await response.json();
      previewText.textContent = data.context || text.textPreviewEmpty;
    } catch (e) {
      previewText.textContent = text.textConnection;
    }
  }

  // Forgets a question that got no answer, so the conversation stays valid. It goes back in the box.
  function dropQuestion(userNode, answerNode, content) {
    messages.pop();
    save();
    userNode.remove();
    answerNode.remove();
    question.value = content;
    refreshControls();
  }

  async function ask(content) {
    if (busy) return;
    busy = true;
    showError("");
    messages.push({ role: "user", content });
    save();
    addUser(content);
    const userNode = log.lastElementChild;
    const { wrapper, body } = addMessage(text.textClaude);
    body.textContent = text.textThinking;
    body.classList.add("muted");
    question.value = "";
    refreshControls();

    let written = "";
    let frame = 0;
    const draw = () => {
      frame = 0;
      body.classList.remove("muted");
      renderMarkdown(body, written);
    };
    const handle = (event) => {
      if (event.text) {
        written += event.text;
        if (!frame) frame = requestAnimationFrame(draw);
      } else if (event.error) {
        throw new Error(event.error);
      } else if (event.done) {
        messages.push({ role: "assistant", content: event.content });
        save();
        if (frame) cancelAnimationFrame(frame);
        draw();
        if (event.truncated) addMeta(wrapper, text.textTruncated);
        if (event.tokens) addMeta(wrapper, text.textTokens.replace("{input}", event.tokens.input).replace("{output}", event.tokens.output));
      }
    };

    try {
      const response = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages, scope: scope.value }),
      });
      const type = response.headers.get("content-type") || "";
      if (response.redirected) throw new Error(text.textLogin);
      if (!response.ok || !type.includes("ndjson")) {
        const data = type.includes("json") ? await response.json() : {};
        throw new Error(data.error || text.textService);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let pending = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        pending += decoder.decode(value, { stream: true });
        const parts = pending.split("\n");
        pending = parts.pop();
        for (const part of parts) if (part) handle(JSON.parse(part));
      }
      if (messages[messages.length - 1].role !== "assistant") throw new Error(text.textConnection);
    } catch (e) {
      if (frame) cancelAnimationFrame(frame);
      dropQuestion(userNode, wrapper, content);
      showError(e instanceof TypeError ? text.textConnection : e.message);
    } finally {
      busy = false;
      refreshControls();
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const content = question.value.trim();
    if (content) ask(content);
  });
  question.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) form.requestSubmit();
  });
  examples.addEventListener("click", (event) => {
    const example = event.target.dataset.example;
    if (example) {
      question.value = example;
      question.focus();
    }
  });
  document.getElementById("ask-new").addEventListener("click", () => {
    if (busy) return;
    messages = [];
    save();
    showError("");
    restore();
    question.focus();
  });
  scope.addEventListener("change", loadPreview);
  preview.addEventListener("toggle", loadPreview);
  restore();
})();
