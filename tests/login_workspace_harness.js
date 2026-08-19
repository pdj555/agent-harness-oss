const fs = require("fs");

function el(id, extras) {
  const listeners = {};
  const item = {
    id,
    hidden: true,
    className: extras.className || "",
    classList: {
      _set: new Set(),
      add: function (name) { item.classList._set.add(name); item.className = Array.from(item.classList._set).join(" "); },
      remove: function (name) { item.classList._set.delete(name); item.className = Array.from(item.classList._set).join(" "); },
      contains: function (name) { return item.classList._set.has(name); }
    },
    textContent: "",
    innerHTML: "",
    value: extras.value || "",
    children: [],
    addEventListener: function (type, fn) {
      listeners[type] = listeners[type] || [];
      listeners[type].push(fn);
    },
    dispatch: function (type, event) {
      (listeners[type] || []).forEach(function (fn) { fn(event || { preventDefault: function () {} }); });
    },
    appendChild: function (child) { item.children.push(child); },
    setAttribute: function (name, value) { if (name === "hidden") item.hidden = true; },
    removeAttribute: function (name) { if (name === "hidden") item.hidden = false; },
    getAttribute: function (name) { return name === "hidden" && item.hidden ? "" : null; }
  };
  if (extras.className) extras.className.split(/\s+/).forEach(function (n) { if (n) item.classList.add(n); });
  return item;
}

const nodes = {
  "auth-gate": el("auth-gate", { className: "auth-gate" }),
  workspace: el("workspace", { className: "workspace" }),
  "auth-form": el("auth-form", {}),
  "auth-error": el("auth-error", {}),
  "signup-button": el("signup-button", {}),
  "logout-button": el("logout-button", {}),
  whoami: el("whoami", {}),
  "repo-select": el("repo-select", {}),
  "history-list": el("history-list", {}),
  "history-empty": el("history-empty", {}),
  composer: el("composer", {}),
  objective: el("objective", {}),
  "composer-error": el("composer-error", {}),
  "stop-button": el("stop-button", {}),
  "empty-state": el("empty-state", {}),
  "run-view": el("run-view", {}),
  "publish-button": el("publish-button", {}),
  "auth-username": el("auth-username", { value: "ada" }),
  "auth-password": el("auth-password", { value: "correct-horse" })
};

global.document = {
  getElementById: function (id) { return nodes[id] || el(id, {}); },
  querySelectorAll: function () { return []; },
  createElement: function (tag) { return el(tag, {}); }
};
global.window = global;

const calls = [];
global.fetch = function (path, options) {
  calls.push({ path: path, method: (options && options.method) || "GET" });
  const method = (options && options.method) || "GET";
  if (path === "/api/me" && method === "GET") {
    return Promise.resolve({
      ok: false,
      status: 401,
      json: function () { return Promise.resolve({ error: "authentication required" }); }
    });
  }
  if (path === "/api/login" && method === "POST") {
    return Promise.resolve({
      ok: true,
      status: 200,
      json: function () { return Promise.resolve({ username: "ada" }); }
    });
  }
  if (path === "/api/repos") {
    return Promise.resolve({
      ok: true,
      status: 200,
      json: function () { return Promise.resolve({ repos: [{ id: "sample", name: "sample-repo" }] }); }
    });
  }
  if (path === "/api/runs") {
    return Promise.resolve({
      ok: true,
      status: 200,
      json: function () { return Promise.resolve({ runs: [] }); }
    });
  }
  return Promise.resolve({
    ok: false,
    status: 404,
    json: function () { return Promise.resolve({ error: "not found" }); }
  });
};

const source = fs.readFileSync(process.argv[2], "utf8");
eval(source);

Promise.resolve().then(function () {
  return new Promise(function (resolve) { setTimeout(resolve, 20); });
}).then(function () {
  if (!nodes["auth-gate"].hidden && nodes.workspace.hidden) {
    // expected before login
  }
  nodes["auth-form"].dispatch("submit", { preventDefault: function () {} });
  return new Promise(function (resolve) { setTimeout(resolve, 40); });
}).then(function () {
  const result = {
    authHidden: nodes["auth-gate"].hidden,
    workspaceHidden: nodes.workspace.hidden,
    authVisibleClass: nodes["auth-gate"].classList.contains("is-visible"),
    workspaceVisibleClass: nodes.workspace.classList.contains("is-visible"),
    whoami: nodes.whoami.textContent,
    calls: calls.map(function (c) { return c.method + " " + c.path; })
  };
  if (nodes.workspace.hidden || !result.workspaceVisibleClass || nodes["auth-gate"].hidden === false && result.authVisibleClass) {
    console.error(JSON.stringify(result));
    process.exit(1);
  }
  if (nodes["auth-gate"].hidden !== true) {
    console.error(JSON.stringify(result));
    process.exit(2);
  }
  if (nodes.whoami.textContent !== "ada") {
    console.error(JSON.stringify(result));
    process.exit(3);
  }
  console.log(JSON.stringify(result));
}).catch(function (err) {
  console.error(String(err && err.stack || err));
  process.exit(4);
});
