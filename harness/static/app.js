(function () {
  var authGate = document.getElementById("auth-gate");
  var workspace = document.getElementById("workspace");
  var authForm = document.getElementById("auth-form");
  var authError = document.getElementById("auth-error");
  var signupButton = document.getElementById("signup-button");
  var logoutButton = document.getElementById("logout-button");
  var whoami = document.getElementById("whoami");
  var repoSelect = document.getElementById("repo-select");
  var historyList = document.getElementById("history-list");
  var historyEmpty = document.getElementById("history-empty");
  var composer = document.getElementById("composer");
  var objectiveInput = document.getElementById("objective");
  var composerError = document.getElementById("composer-error");
  var stopButton = document.getElementById("stop-button");
  var emptyState = document.getElementById("empty-state");
  var runView = document.getElementById("run-view");
  var pollTimer = null;
  var currentRunId = null;

  function api(path, options) {
    return fetch(path, Object.assign({ credentials: "same-origin" }, options || {})).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        if (!body || typeof body !== "object") body = {};
        body.ok = response.ok;
        body.httpStatus = response.status;
        return body;
      });
    });
  }

  function showAuth() {
    authGate.hidden = false;
    authGate.classList.add("is-visible");
    workspace.hidden = true;
    workspace.classList.remove("is-visible");
  }

  function showWorkspace(username) {
    authGate.hidden = true;
    authGate.classList.remove("is-visible");
    workspace.hidden = false;
    workspace.classList.add("is-visible");
    whoami.textContent = username || "";
  }

  function enterWorkspace(username) {
    showWorkspace(username);
    loadRepos();
    loadHistory();
  }

  function setAuthError(message) {
    authError.textContent = message || "";
  }

  authForm.addEventListener("submit", function (event) {
    event.preventDefault();
    submitAuth("/api/login");
  });
  signupButton.addEventListener("click", function () {
    submitAuth("/api/signup");
  });
  logoutButton.addEventListener("click", function () {
    api("/api/logout", { method: "POST" }).then(function () {
      currentRunId = null;
      showAuth();
    });
  });

  function submitAuth(path) {
    setAuthError("");
    var payload = JSON.stringify({
      username: document.getElementById("auth-username").value.trim(),
      password: document.getElementById("auth-password").value
    });
    api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload
    }).then(function (body) {
      if (!body.ok) {
        setAuthError(body.error || "Could not authenticate");
        return;
      }
      enterWorkspace(body.username);
    });
  }

  composer.addEventListener("submit", function (event) {
    event.preventDefault();
    composerError.textContent = "";
    var repoId = repoSelect.value;
    if (!repoId) {
      composerError.textContent = "Select a repository.";
      return;
    }
    api("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo_id: repoId, objective: objectiveInput.value.trim() })
    }).then(function (body) {
      if (!body.ok) {
        composerError.textContent = body.error || "Could not start the run.";
        return;
      }
      objectiveInput.value = "";
      watchRun(body.id);
      loadHistory();
    });
  });

  stopButton.addEventListener("click", function () {
    if (!currentRunId) return;
    api("/api/runs/" + currentRunId + "/stop", { method: "POST" }).then(function (body) {
      if (body.id) renderRun(body);
    });
  });

  document.getElementById("publish-button").addEventListener("click", function () {
    if (!currentRunId) return;
    api("/api/runs/" + currentRunId + "/publish", { method: "POST" }).then(function (body) {
      if (!body.ok) {
        composerError.textContent = body.error || "Publish failed.";
        return;
      }
      renderRun(body);
    });
  });

  document.querySelectorAll(".tabs [data-tab]").forEach(function (tab) {
    tab.addEventListener("click", function () {
      document.querySelectorAll(".tabs [data-tab]").forEach(function (other) {
        other.setAttribute("aria-selected", other === tab ? "true" : "false");
      });
      var selected = tab.getAttribute("data-tab");
      document.getElementById("plan-view").hidden = selected !== "plan";
      document.getElementById("changes-view").hidden = selected !== "changes";
      document.getElementById("proof-view").hidden = selected !== "proof";
    });
  });

  function loadRepos() {
    api("/api/repos").then(function (body) {
      if (!body.ok) return;
      repoSelect.innerHTML = "";
      (body.repos || []).forEach(function (repo) {
        var option = document.createElement("option");
        option.value = repo.id;
        option.textContent = repo.name;
        repoSelect.appendChild(option);
      });
    });
  }

  function boot() {
    api("/api/me").then(function (me) {
      if (!me.ok) {
        showAuth();
        return;
      }
      enterWorkspace(me.username);
    });
  }

  function loadHistory() {
    api("/api/runs").then(function (body) {
      if (!body.ok) return;
      historyList.innerHTML = "";
      var runs = body.runs || [];
      historyEmpty.hidden = runs.length > 0;
      runs.forEach(function (run) {
        var button = document.createElement("button");
        button.type = "button";
        button.textContent = (run.status || "run") + " · " + (run.objective || "").slice(0, 48);
        button.className = run.id === currentRunId ? "active" : "";
        button.addEventListener("click", function () { watchRun(run.id); });
        historyList.appendChild(button);
      });
    });
  }

  function watchRun(runId) {
    currentRunId = runId;
    if (pollTimer) window.clearInterval(pollTimer);
    fetchRun();
    pollTimer = window.setInterval(fetchRun, 400);
  }

  function fetchRun() {
    if (!currentRunId) return;
    api("/api/runs/" + currentRunId).then(function (run) {
      if (!run.ok) return;
      renderRun(run);
      if (run.status === "completed" || run.status === "failed" || run.status === "stopped") {
        window.clearInterval(pollTimer);
        pollTimer = null;
        loadHistory();
      }
    });
  }

  function renderRun(run) {
    emptyState.hidden = true;
    runView.hidden = false;
    document.getElementById("run-status-label").textContent = run.status || "running";
    document.getElementById("run-title").textContent = (run.objective || "Objective").slice(0, 72);
    document.getElementById("objective-text").textContent = run.objective || "";
    document.getElementById("investigating").textContent = run.investigating || "";
    document.getElementById("active-work").textContent = run.active_work || "";
    stopButton.hidden = !(run.status === "running" || run.status === "queued" || run.status === "stopping");

    var events = document.getElementById("event-list");
    events.innerHTML = "";
    (run.events || []).forEach(function (event) {
      var item = document.createElement("li");
      var kind = document.createElement("span");
      kind.className = "kind";
      kind.textContent = event.kind || "action";
      item.appendChild(kind);
      item.appendChild(document.createTextNode(event.detail || ""));
      events.appendChild(item);
    });

    var resultCard = document.getElementById("result-card");
    if (run.result) {
      resultCard.hidden = false;
      document.getElementById("result-heading").textContent = run.status === "completed" ? "Completed" : "Result";
      document.getElementById("result-text").textContent = run.result;
    } else {
      resultCard.hidden = true;
    }

    var blockers = run.blockers || [];
    document.getElementById("blocker-card").hidden = blockers.length === 0;
    var blockerList = document.getElementById("blocker-list");
    blockerList.innerHTML = "";
    blockers.forEach(function (blocker) {
      var item = document.createElement("li");
      item.textContent = blocker;
      blockerList.appendChild(item);
    });

    var plan = run.plan || [];
    document.getElementById("plan-empty").hidden = plan.length > 0;
    var planList = document.getElementById("plan-list");
    planList.innerHTML = "";
    plan.forEach(function (step) {
      var item = document.createElement("li");
      item.textContent = step;
      planList.appendChild(item);
    });

    var files = run.files_changed || [];
    document.getElementById("changes-empty").hidden = files.length > 0 || !!(run.diff);
    var fileList = document.getElementById("file-list");
    fileList.innerHTML = "";
    files.forEach(function (name) {
      var item = document.createElement("li");
      item.textContent = name;
      fileList.appendChild(item);
    });
    document.getElementById("diff-view").textContent = run.diff || "";

    var verification = run.verification || {};
    document.getElementById("check-command").textContent = verification.command || "";
    document.getElementById("check-output").textContent = verification.output || "";
    var badge = document.getElementById("check-badge");
    if (verification.passed === true) badge.textContent = "Passed";
    else if (verification.passed === false) badge.textContent = "Failed";
    else badge.textContent = "";
    document.getElementById("review-summary").textContent = (run.review && run.review.summary) || "";
    var findingsList = document.getElementById("review-findings");
    findingsList.innerHTML = "";
    ((run.review && run.review.findings) || []).forEach(function (finding) {
      var item = document.createElement("li");
      item.textContent = finding;
      findingsList.appendChild(item);
    });
    document.getElementById("proof-empty").hidden = !!(verification.output || (run.review && run.review.summary));
    var publishButton = document.getElementById("publish-button");
    publishButton.hidden = !(run.status === "completed" && verification.passed);
  }

  boot();
})();
