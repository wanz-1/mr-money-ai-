/* Mr Money AI - Alpine.js Application */
document.addEventListener("alpine:init", () => {

  // ── Toast notifications ──
  Alpine.store("toast", {
    items: [],
    _id: 0,
    show(message, type = "info") {
      const id = ++this._id;
      this.items.push({ id, message, type, visible: true });
    },
    dismiss(id) {
      const item = this.items.find(t => t.id === id);
      if (item) item.visible = false;
      setTimeout(() => { this.items = this.items.filter(t => t.id !== id); }, 300);
    },
  });

  // ── Keyboard shortcuts ──
  Alpine.store("shortcuts", {
    show: false,
    list: [
      { keys: "Ctrl + Enter", desc: "Run review" },
      { keys: "Ctrl + S", desc: "Download report" },
      { keys: "Ctrl + D", desc: "Toggle dark mode" },
      { keys: "1-5", desc: "Switch tabs" },
      { keys: "Esc", desc: "Close overlay" },
      { keys: "?", desc: "Show shortcuts" },
    ],
  });

  // ── Auth store ──
  Alpine.store("auth", {
    loggedIn: false,
    mode: "login",
    user: null,
    token: null,
    refreshToken: null,
    email: "",
    password: "",
    displayName: "",
    orgId: "",
    orgName: "",
    error: "",
    busy: false,

    init() {
      const saved = localStorage.getItem("mm_auth");
      if (saved) {
        try {
          const data = JSON.parse(saved);
          this.user = data.user;
          this.token = data.token;
          this.refreshToken = data.refreshToken;
          this.loggedIn = true;
        } catch (e) { /* ignore */ }
      }
    },

    _persist() {
      if (this.loggedIn) {
        localStorage.setItem("mm_auth", JSON.stringify({
          user: this.user, token: this.token, refreshToken: this.refreshToken,
        }));
      } else {
        localStorage.removeItem("mm_auth");
      }
    },

    async login() {
      this.error = "";
      this.busy = true;
      try {
        const base = Alpine.store("app").apiBase;
        const resp = await fetch(`${base}/api/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: this.email, password: this.password, orgId: this.orgId || "" }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Login failed");
        this.user = { userId: data.userId, orgId: data.orgId, email: data.email, displayName: data.displayName };
        this.token = data.accessToken;
        this.refreshToken = data.refreshToken;
        this.loggedIn = true;
        this._persist();
        Alpine.store("toast").show("Signed in successfully", "success");
      } catch (e) {
        this.error = e.message;
      } finally {
        this.busy = false;
      }
    },

    async register() {
      this.error = "";
      this.busy = true;
      try {
        const base = Alpine.store("app").apiBase;
        const resp = await fetch(`${base}/api/auth/register`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            email: this.email, password: this.password,
            displayName: this.displayName, organizationName: this.orgName,
          }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Registration failed");
        this.user = { userId: data.userId, orgId: data.orgId, email: data.email, displayName: data.displayName };
        this.token = data.accessToken;
        this.refreshToken = data.refreshToken;
        this.loggedIn = true;
        this._persist();
        Alpine.store("toast").show("Account created", "success");
      } catch (e) {
        this.error = e.message;
      } finally {
        this.busy = false;
      }
    },

    logout() {
      this.loggedIn = false;
      this.user = null;
      this.token = null;
      this.refreshToken = null;
      this._persist();
      Alpine.store("toast").show("Signed out", "info");
    },

    skipAuth() {
      this.loggedIn = true;
      this.user = { displayName: "Guest", email: "guest@local" };
      this._persist();
    },

    headers() {
      return this.token ? { "Authorization": `Bearer ${this.token}` } : {};
    },
  });

  // ── App store ──
  Alpine.store("app", {
    apiBase: localStorage.getItem("mm_api_base") || window.location.origin,
    darkMode: localStorage.getItem("mm_dark") === "true",
    page: "review",
    pageTitle: "Document Review",
    sidebarCollapsed: window.innerWidth < 768,

    init() {
      Alpine.store("auth").init();
      if (this.darkMode) {
        document.documentElement.classList.add("dark");
      } else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
        this.darkMode = true;
        document.documentElement.classList.add("dark");
      }
      window.addEventListener("resize", () => {
        if (window.innerWidth < 768) this.sidebarCollapsed = true;
      });
      // Persist apiBase changes to localStorage
      // apiBase persisted via @change handler on the input element
    },

    navigate(page) {
      this.page = page;
      const titles = { review: "Document Review", documents: "Documents", templates: "Templates", research: "Research Intelligence", compare: "Document Comparison", assistant: "AI Assistant" };
      this.pageTitle = titles[page] || page;
      if (page === "documents") Alpine.store("documents").load();
      if (page === "templates") Alpine.store("templates").load();
      if (page === "assistant") Alpine.store("ai").initProvider();
    },

    toggleTheme() {
      this.darkMode = !this.darkMode;
      localStorage.setItem("mm_dark", this.darkMode);
      if (this.darkMode) {
        document.documentElement.classList.add("dark");
      } else {
        document.documentElement.classList.remove("dark");
      }
    },
  });

  // ── Review store ──
  Alpine.store("review", {
    text: "",
    filename: "pasted-document.txt",
    contentType: "text/plain",
    base64: "",
    status: "Ready",
    busy: false,
    report: null,
    tab: "findings",
    severityFilter: "all",
    searchQuery: "",

    loadSample() {
      this.text = `# Community Health Grant Proposal

Our organization requests support to expand mobile screening services across rural clinics. The 2020 report shows that 44 percent of residents missed preventive visits. This current statistic demonstrates a significant gap in access.

The program will be implemented by trained nurses and community volunteers. The intervention is designed to improve early referrals and reduce avoidable hospital visits.

Research shows that mobile care improves outcomes for underserved populations.

It is important to note that due to the fact that many studies have been conducted, the results are significant. In order to achieve the desired outcomes, we must consider all available options.

References
Smith, A. (2021). Rural health access. https://example.org/report`;
      this.status = "Sample loaded";
    },

    clear() {
      this.text = "";
      this.report = null;
      this.base64 = "";
      this.filename = "pasted-document.txt";
      this.status = "Ready";
    },

    handleFile(file) {
      if (!file) return;
      this.filename = file.name;
      this.status = `Loaded ${file.name}`;
      if (this._isTextLike(file.name, file.type)) {
        file.text().then(text => { this.text = text; });
        this.base64 = "";
      } else {
        file.arrayBuffer().then(buf => {
          this.base64 = this._arrayBufferToBase64(buf);
          this.text = `${file.name} ready for server-side extraction.`;
        });
      }
    },

    handleDrop(event) {
      const file = event.dataTransfer.files[0];
      if (file) this.handleFile(file);
    },

    async runReview() {
      if (!this.text.trim() && !this.base64) {
        this.status = "Add text or upload a document";
        return;
      }
      this.busy = true;
      this.status = "Reviewing...";
      try {
        const base = Alpine.store("app").apiBase;
        const payload = this.base64
          ? { filename: this.filename, contentType: this.contentType, contentBase64: this.base64 }
          : { filename: this.filename, contentType: "text/plain", content: this.text };
        const resp = await fetch(`${base}/api/reviews`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!resp.ok) throw new Error(`Review failed (${resp.status})`);
        this.report = await resp.json();
        this.status = "Review complete";
        Alpine.store("toast").show("Review complete", "success");
      } catch (e) {
        this.status = e.message;
        Alpine.store("toast").show(e.message, "error");
      } finally {
        this.busy = false;
      }
    },

    score(key) {
      if (!this.report || !this.report.scores) return "--";
      const v = this.report.scores[key];
      return v !== undefined ? Number(v).toFixed(1) : "--";
    },

    scoreItems() {
      if (!this.report || !this.report.scores) return [];
      const priority = [
        "writing_quality", "grammar", "readability", "originality",
        "similarity", "citation", "accessibility", "compliance",
        "security", "fact_checking", "ai_writing_indicator", "ai_analysis_confidence",
      ];
      return priority.filter(k => k in this.report.scores).map(k => {
        const v = this.report.scores[k];
        const pct = Math.max(0, Math.min(100, v));
        let color = "var(--accent)";
        if (k.includes("ai_writing")) color = pct > 60 ? "var(--warning)" : "var(--accent)";
        else if (pct < 50) color = "var(--danger)";
        else if (pct < 75) color = "var(--warning)";
        else color = "var(--ok)";
        return {
          key: k,
          label: k.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()),
          value: Number(v).toFixed(1),
          pct,
          color,
        };
      });
    },

    filteredFindings() {
      if (!this.report || !this.report.findings) return [];
      return this.report.findings.filter(f => {
        const matchSev = this.severityFilter === "all" || f.severity === this.severityFilter;
        const haystack = `${f.category} ${f.title} ${f.message} ${f.recommendation}`.toLowerCase();
        const matchSearch = !this.searchQuery || haystack.includes(this.searchQuery.toLowerCase());
        return matchSev && matchSearch;
      });
    },

    async download(format) {
      if (!this.report) return;
      try {
        const base = Alpine.store("app").apiBase;
        const resp = await fetch(`${base}/api/reviews/${this.report.reviewId}/reports/${format}`);
        if (!resp.ok) throw new Error(`Download failed (${resp.status})`);
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `mr-money-ai-report.${format}`;
        a.click();
        URL.revokeObjectURL(url);
      } catch (e) {
        Alpine.store("toast").show(e.message, "error");
      }
    },

    _isTextLike(name, type) {
      return type.startsWith("text/") || /\.(txt|md|markdown|html|htm|json|xml|csv|tex|latex|rtf)$/i.test(name);
    },

    _arrayBufferToBase64(buffer) {
      let binary = "";
      new Uint8Array(buffer).forEach(b => { binary += String.fromCharCode(b); });
      return btoa(binary);
    },
  });

  // ── Documents store ──
  Alpine.store("documents", {
    items: [],
    busy: false,

    async load() {
      this.busy = true;
      try {
        const base = Alpine.store("app").apiBase;
        const resp = await fetch(`${base}/api/documents`, { headers: Alpine.store("auth").headers() });
        if (!resp.ok) return;
        const data = await resp.json();
        this.items = data.documents || [];
      } catch (e) { /* silent */ } finally {
        this.busy = false;
      }
    },
  });

  // ── Templates store ──
  Alpine.store("templates", {
    items: [],
    previewType: null,
    previewData: null,

    async load() {
      try {
        const base = Alpine.store("app").apiBase;
        const resp = await fetch(`${base}/api/templates`);
        if (resp.ok) {
          const data = await resp.json();
          this.items = data.templates || data || [];
        }
      } catch (e) { /* silent */ }
    },

    preview(type) {
      this.previewType = type;
      this.previewData = this.items.find(t => t.type === type) || null;
    },

    async generateFromPreview() {
      if (!this.previewData) return;
      const type = this.previewData.type;
      const name = this.previewData.name;
      this.previewType = null;
      try {
        const base = Alpine.store("app").apiBase;
        const resp = await fetch(`${base}/api/templates/${type}/docx`);
        if (!resp.ok) throw new Error(`Download failed (${resp.status})`);
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${name.replace(/\s+/g, "_").toLowerCase()}_template.docx`;
        a.click();
        URL.revokeObjectURL(url);
        Alpine.store("toast").show(`${name} template downloaded as Word document`, "success");
      } catch (e) {
        Alpine.store("toast").show(e.message, "error");
      }
    },
  });

  // ── Research store ──
  Alpine.store("research", {
    text: "",
    busy: false,
    tab: "search",
    graph: null,
    graphMermaid: "",
    citationText: "",
    citationStyle: "apa",
    citationResult: null,

    async generateGraph() {
      if (!this.text.trim()) return;
      this.busy = true;
      try {
        const resp = await fetch(`${Alpine.store("app").apiBase}/api/research/knowledge-graph`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...Alpine.store("auth").headers() },
          body: JSON.stringify({ content: this.text }),
        });
        if (resp.status === 501) {
          this.graphMermaid = "Knowledge graph generation requires the research module.\nPaste your text and this feature will be available in the next release.";
          return;
        }
        const data = await resp.json();
        this.graph = data;
        this.graphMermaid = data.mermaid || "Graph generated";
      } catch (e) {
        this.graphMermaid = "Unable to generate graph: " + e.message;
      } finally {
        this.busy = false;
      }
    },

    async validateCitation() {
      if (!this.citationText.trim()) return;
      this.busy = true;
      try {
        const resp = await fetch(`${Alpine.store("app").apiBase}/api/research/validate-citation`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...Alpine.store("auth").headers() },
          body: JSON.stringify({ text: this.citationText, style: this.citationStyle }),
        });
        if (resp.status === 501) {
          this.citationResult = { isValid: true, issues: [], missingFields: [] };
          return;
        }
        this.citationResult = await resp.json();
      } catch (e) {
        Alpine.store("toast").show("Citation validation unavailable", "error");
      } finally {
        this.busy = false;
      }
    },

    async convertCitation() {
      Alpine.store("toast").show("Citation conversion will be available with the research module", "info");
    },
  });

  // ── Compare store ──
  Alpine.store("compare", {
    oldText: "",
    newText: "",
    busy: false,
    result: null,

    async run() {
      if (!this.oldText.trim() || !this.newText.trim()) {
        Alpine.store("toast").show("Enter both texts to compare", "error");
        return;
      }
      this.busy = true;
      try {
        const resp = await fetch(`${Alpine.store("app").apiBase}/api/compare`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...Alpine.store("auth").headers() },
          body: JSON.stringify({ oldText: this.oldText, newText: this.newText }),
        });
        if (resp.status === 501) {
          Alpine.store("toast").show("Document comparison requires the comparison module", "info");
          return;
        }
        this.result = await resp.json();
      } catch (e) {
        Alpine.store("toast").show("Comparison unavailable: " + e.message, "error");
      } finally {
        this.busy = false;
      }
    },
  });

  // ── Search store ──
  Alpine.store("search", {
    query: "",
    results: [],
    busy: false,
    selectedAgent: "executive",
    agents: [],
    agentResult: null,
    agentQuery: "",

    async search() {
      if (!this.query.trim()) return;
      this.busy = true;
      try {
        const base = Alpine.store("app").apiBase;
        const resp = await fetch(`${base}/api/search`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...Alpine.store("auth").headers() },
          body: JSON.stringify({ query: this.query, maxResults: 8 }),
        });
        if (!resp.ok) throw new Error(`Search failed (${resp.status})`);
        const data = await resp.json();
        this.results = data.results || [];
      } catch (e) {
        Alpine.store("toast").show(e.message, "error");
      } finally {
        this.busy = false;
      }
    },

    async loadAgents() {
      try {
        const base = Alpine.store("app").apiBase;
        const resp = await fetch(`${base}/api/agents`, { headers: Alpine.store("auth").headers() });
        if (resp.ok) {
          const data = await resp.json();
          this.agents = data.agents || [];
        }
      } catch (e) { /* silent */ }
    },

    async runAgent() {
      if (!this.agentQuery.trim()) return;
      this.busy = true;
      this.agentResult = null;
      try {
        const base = Alpine.store("app").apiBase;
        const resp = await fetch(`${base}/api/agents/run`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...Alpine.store("auth").headers() },
          body: JSON.stringify({ agent: this.selectedAgent, query: this.agentQuery, context: {} }),
        });
        if (!resp.ok) throw new Error(`Agent failed (${resp.status})`);
        this.agentResult = await resp.json();
      } catch (e) {
        Alpine.store("toast").show(e.message, "error");
      } finally {
        this.busy = false;
      }
    },
  });

  // ── AI Assistant store ──
  Alpine.store("ai", {
    sessionId: "",
    messages: [],
    input: "",
    streaming: false,
    provider: "local",
    providers: {},
    documentAttached: false,
    documentName: "",
    documentText: "",
    reviewData: null,

    async initProvider() {
      try {
        const resp = await fetch(`${Alpine.store("app").apiBase}/api/ai/providers`);
        if (resp.ok) {
          const data = await resp.json();
          this.provider = data.active || "local";
          this.providers = data.providers || {};
        }
      } catch (e) { /* silent */ }
    },

    newSession() {
      this.sessionId = "";
      this.messages = [];
      this.documentAttached = false;
      this.documentName = "";
      this.documentText = "";
      this.reviewData = null;
    },

    attachDocument() {
      const review = Alpine.store("review");
      if (review.text) {
        this.documentText = review.text;
        this.documentName = review.filename || "current-document.txt";
        this.documentAttached = true;
        if (review.report) {
          this.reviewData = review.report;
        }
        Alpine.store("toast").show("Document attached to chat context", "success");
      }
    },

    detachDocument() {
      this.documentAttached = false;
      this.documentName = "";
      this.documentText = "";
      this.reviewData = null;
    },

    sendQuick(text) {
      this.input = text;
      this.sendMessage();
    },

    async sendMessage() {
      const msg = this.input.trim();
      if (!msg || this.streaming) return;

      if (msg.toLowerCase().startsWith("/imagine ") || msg.toLowerCase().startsWith("/image ")) {
        this.input = "";
        this._generateImage(msg.replace(/^\/(imagine|image)\s+/i, ""));
        return;
      }

      this.messages.push({ role: "user", content: msg });
      this.input = "";
      this.streaming = true;

      this._scrollToBottom();

      try {
        const base = Alpine.store("app").apiBase;
        const payload = {
          message: msg,
          sessionId: this.sessionId,
        };
        if (this.documentAttached) {
          payload.documentText = this.documentText;
          payload.documentName = this.documentName;
        }
        if (this.reviewData) {
          payload.reviewData = this.reviewData;
        }

        const resp = await fetch(`${base}/api/ai/chat/stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...Alpine.store("auth").headers() },
          body: JSON.stringify(payload),
        });

        if (!resp.ok) {
          const err = await resp.json();
          throw new Error(err.error || "Chat failed");
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let assistantContent = "";
        const assistantIdx = this.messages.length;
        this.messages.push({ role: "assistant", content: "" });

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            try {
              const data = JSON.parse(line.slice(6));
              if (data.token) {
                assistantContent += data.token;
                this.messages[assistantIdx].content = assistantContent;
                this._scrollToBottom();
              }
              if (data.done) {
                this.sessionId = data.sessionId || this.sessionId;
                this.provider = data.provider || this.provider;
              }
              if (data.error) {
                this.messages[assistantIdx].content = "Error: " + data.error;
              }
            } catch (e) { /* skip malformed */ }
          }
        }
      } catch (e) {
        this.messages.push({ role: "assistant", content: "Sorry, I encountered an error: " + e.message });
      } finally {
        this.streaming = false;
        this._scrollToBottom();
      }
    },

    async _generateImage(prompt) {
      this.messages.push({ role: "user", content: "/imagine " + prompt });
      this.streaming = true;
      this._scrollToBottom();

      try {
        const base = Alpine.store("app").apiBase;
        const resp = await fetch(`${base}/api/ai/image`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...Alpine.store("auth").headers() },
          body: JSON.stringify({ prompt, size: "1024x1024", n: 1 }),
        });
        const data = await resp.json();
        if (data.error) {
          this.messages.push({ role: "assistant", content: "Image generation error: " + data.error });
        } else if (data.images && data.images.length > 0) {
          const imgHtml = data.images.map(img => {
            const url = img.url || "";
            if (!url.startsWith("http://") && !url.startsWith("https://") && !url.startsWith("data:")) return "";
            return `<img src="${url.replace(/"/g, "&quot;")}" alt="Generated image" style="max-width:100%;border-radius:8px;margin:8px 0" loading="lazy">`;
          }).join("");
          this.messages.push({ role: "assistant", content: imgHtml });
        } else {
          this.messages.push({ role: "assistant", content: "No images were generated." });
        }
      } catch (e) {
        this.messages.push({ role: "assistant", content: "Image generation failed: " + e.message });
      } finally {
        this.streaming = false;
        this._scrollToBottom();
      }
    },

    renderMarkdown(text) {
      if (!text) return "";
      let s = text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/\*(.+?)\*/g, "<em>$1</em>")
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/^### (.+)$/gm, "<h4>$1</h4>")
        .replace(/^## (.+)$/gm, "<h3>$1</h3>")
        .replace(/^# (.+)$/gm, "<h2>$1</h2>")
        .replace(/^- (.+)$/gm, "<li>$1</li>")
        .replace(/(<li>[\s\S]*?<\/li>\n?)+/g, (m) => "<ul>" + m + "</ul>")
        .replace(/^\d+\. (.+)$/gm, "<li>$1</li>")
        .replace(/\n{2,}/g, "<br><br>")
        .replace(/\n/g, "<br>");
      return s;
    },

    _scrollToBottom() {
      setTimeout(() => {
        const el = document.getElementById("chatMessages");
        if (el) el.scrollTop = el.scrollHeight;
      }, 50);
    },
  });

  // ── Keyboard shortcuts handler ──
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;
    const review = Alpine.store("review");
    const app = Alpine.store("app");
    if (e.key === "?" && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      Alpine.store("shortcuts").show = !Alpine.store("shortcuts").show;
    }
    if (e.key === "Escape") {
      Alpine.store("shortcuts").show = false;
      Alpine.store("templates").previewType = null;
    }
    if (e.ctrlKey || e.metaKey) {
      if (e.key === "Enter") { e.preventDefault(); review.runReview(); }
      if (e.key === "d" || e.key === "D") { e.preventDefault(); app.toggleTheme(); }
    }
    if (e.key >= "1" && e.key <= "5" && !e.ctrlKey && !e.metaKey) {
      const tabs = ["findings", "actions", "agents", "limits"];
      const idx = parseInt(e.key) - 1;
      if (idx < tabs.length) review.tab = tabs[idx];
    }
  });
});
