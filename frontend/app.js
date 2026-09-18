function startAsciiSphere() {
  const canvas = document.querySelector("#ascii-sphere");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const chars = "░▒▓█▀▄▌▐│─┤├┴┬╭╮╰╯";
  let time = 0;
  let frameId = 0;

  function resize() {
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = Math.max(1, Math.floor(rect.width * dpr));
    canvas.height = Math.max(1, Math.floor(rect.height * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function render() {
    const rect = canvas.getBoundingClientRect();
    ctx.clearRect(0, 0, rect.width, rect.height);

    const centerX = rect.width / 2;
    const centerY = rect.height / 2;
    const radius = Math.min(rect.width, rect.height) * 0.525;
    const points = [];

    ctx.font = "12px ui-monospace, SFMono-Regular, Menlo, monospace";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";

    for (let phi = 0; phi < Math.PI * 2; phi += 0.15) {
      for (let theta = 0; theta < Math.PI; theta += 0.15) {
        const x = Math.sin(theta) * Math.cos(phi + time * 0.5);
        const y = Math.sin(theta) * Math.sin(phi + time * 0.5);
        const z = Math.cos(theta);
        const rotY = time * 0.3;
        const newX = x * Math.cos(rotY) - z * Math.sin(rotY);
        const newZ = x * Math.sin(rotY) + z * Math.cos(rotY);
        const rotX = time * 0.2;
        const newY = y * Math.cos(rotX) - newZ * Math.sin(rotX);
        const finalZ = y * Math.sin(rotX) + newZ * Math.cos(rotX);
        const depth = (finalZ + 1) / 2;
        const charIndex = Math.floor(depth * (chars.length - 1));
        points.push({
          x: centerX + newX * radius,
          y: centerY + newY * radius,
          z: finalZ,
          char: chars[charIndex],
        });
      }
    }

    points.sort((a, b) => a.z - b.z);
    for (const point of points) {
      const alpha = 0.2 + (point.z + 1) * 0.4;
      ctx.fillStyle = `rgba(0, 0, 0, ${alpha})`;
      ctx.fillText(point.char, point.x, point.y);
    }

    time += 0.02;
    frameId = requestAnimationFrame(render);
  }

  resize();
  render();
  window.addEventListener("resize", resize);
  window.addEventListener("beforeunload", () => cancelAnimationFrame(frameId));
}

const landing = document.querySelector("#landing");
const workspace = document.querySelector("#workspace");
const messages = document.querySelector("#messages");
const form = document.querySelector("#chat-form");
const input = document.querySelector("#message");
const send = document.querySelector("#send");
const status = document.querySelector("#demo-status");
const stateBadge = document.querySelector("#request-state");
const title = document.querySelector("#request-title");
const subtitle = document.querySelector("#request-subtitle");
const cartPanel = document.querySelector("#cart");
const cartState = document.querySelector("#cart-state");
const payArea = document.querySelector("#pay-area");
const agentThread = document.querySelector("#agent-thread");
const agentPresence = document.querySelector("#agent-presence");
const networkState = document.querySelector("#network-state");
const conversationView = document.querySelector("#conversation-view");
const paymentsView = document.querySelector("#payments-view");
const composerArea = document.querySelector("#composer-area");
const conversationNav = document.querySelector("#conversation-nav");
const paymentsNav = document.querySelector("#payments-nav");
const paymentHistory = document.querySelector("#payment-history");
const conversationList = document.querySelector("#conversation-list");
const workflowProgress = document.querySelector("#workflow-progress");
const storageKey = "a2a-relay-demo-session";
const paymentStorageKey = "a2a-relay-demo-payments";
const conversationsStorageKey = "a2a-relay-demo-conversations";
const activeConversationStorageKey = "a2a-relay-demo-active-conversation";
let sessionId = localStorage.getItem(storageKey) || null;
const paymentRecords = loadPaymentRecords();
let conversations = loadConversations();
let activeConversationId = localStorage.getItem(activeConversationStorageKey) || null;
let workflowSteps = [];
let connectedMerchants = [];
let latestPaymentOrders = [];
let latestPayButton = null;

function loadPaymentRecords() {
  try {
    const saved = JSON.parse(localStorage.getItem(paymentStorageKey) || "[]");
    return new Map(Array.isArray(saved) ? saved : []);
  } catch {
    return new Map();
  }
}

function savePaymentRecords() {
  localStorage.setItem(paymentStorageKey, JSON.stringify([...paymentRecords.entries()]));
}

function loadConversations() {
  try {
    const saved = JSON.parse(localStorage.getItem(conversationsStorageKey) || "[]");
    return Array.isArray(saved) ? saved : [];
  } catch {
    return [];
  }
}

function saveConversations() {
  localStorage.setItem(conversationsStorageKey, JSON.stringify(conversations));
  if (activeConversationId) localStorage.setItem(activeConversationStorageKey, activeConversationId);
  else localStorage.removeItem(activeConversationStorageKey);
}

function activeConversation() {
  return conversations.find((conversation) => conversation.id === activeConversationId) || null;
}

function ensureConversation() {
  let conversation = activeConversation();
  if (conversation) return conversation;
  conversation = {
    id: crypto.randomUUID(),
    title: "New conversation",
    sessionId: null,
    messages: [{ role: "agent", name: "Shopping assistant", text: "What would you like to buy? I can compare verified offers, check eligible prices, and prepare a secure payment only after you approve." }],
  };
  conversations.unshift(conversation);
  activeConversationId = conversation.id;
  saveConversations();
  renderConversationList();
  return conversation;
}

function saveMessage(role, name, text) {
  const conversation = ensureConversation();
  conversation.messages.push({ role, name, text });
  if (role === "buyer" && conversation.title === "New conversation") {
    conversation.title = text.length > 30 ? text.slice(0, 30) + "…" : text;
  }
  saveConversations();
  renderConversationList();
}

function updateLatestAgentMessage(text) {
  const conversation = activeConversation();
  if (!conversation) return;
  const latest = conversation.messages.at(-1);
  if (latest && latest.role === "agent") latest.text = text;
  saveConversations();
}

function renderConversationList() {
  conversationList.replaceChildren();
  for (const conversation of conversations) {
    const item = document.createElement("button");
    item.className = "conversation-item" + (conversation.id === activeConversationId ? " active" : "");
    item.textContent = conversation.title;
    item.title = conversation.title;
    item.addEventListener("click", () => openConversation(conversation.id));
    conversationList.append(item);
  }
}

function openConversation(id) {
  const conversation = conversations.find((item) => item.id === id);
  if (!conversation) return;
  activeConversationId = id;
  sessionId = conversation.sessionId || null;
  if (sessionId) localStorage.setItem(storageKey, sessionId);
  else localStorage.removeItem(storageKey);
  messages.replaceChildren();
  appendDivider(conversation.title);
  for (const message of conversation.messages) appendMessage(message.role, message.name, message.text);
  title.textContent = conversation.title;
  subtitle.textContent = "Continue this shopping conversation";
  renderConversationList();
  saveConversations();
  showWorkspaceView("conversation");
}

function renderWorkflow() {
  workflowProgress.replaceChildren();
  if (!workflowSteps.length) {
    const empty = document.createElement("div");
    empty.className = "workflow-empty";
    empty.textContent = "Send a shopping request and I’ll show each step as it happens.";
    workflowProgress.append(empty);
    return;
  }
  workflowSteps.forEach((step, index) => {
    const item = document.createElement("div");
    item.className = "workflow-step" + (index === workflowSteps.length - 1 && !step.done ? " current" : "");
    const icon = document.createElement("div");
    icon.className = "workflow-step-icon";
    icon.textContent = step.done ? "✓" : "…";
    const copy = document.createElement("div");
    const heading = document.createElement("strong");
    heading.textContent = step.step;
    const detail = document.createElement("span");
    detail.textContent = step.detail;
    copy.append(heading, detail);
    item.append(icon, copy);
    workflowProgress.append(item);
  });
}

function setNetworkState(label, active = false) {
  networkState.innerHTML = "";
  const dot = document.createElement("i");
  networkState.append(dot, document.createTextNode(" " + label));
  networkState.classList.toggle("active", active);
}

function renderAgentActivity() {
  agentPresence.replaceChildren();
  const merchants = connectedMerchants.length ? connectedMerchants : [];
  for (const name of merchants) {
    const item = document.createElement("span");
    item.className = "agent-presence-item";
    item.textContent = name;
    agentPresence.append(item);
  }

  agentThread.replaceChildren();
  if (!merchants.length) {
    const empty = document.createElement("div");
    empty.className = "agent-empty";
    empty.textContent = "Merchant availability will appear here.";
    agentThread.append(empty);
    return;
  }
  const summary = document.createElement("div");
  summary.className = "merchant-summary";
  summary.textContent = `${merchants.length} merchant${merchants.length === 1 ? "" : "s"} connected and ready for offers.`;
  agentThread.append(summary);
}

function resetCart() {
  cartPanel.replaceChildren();
  const empty = document.createElement("div");
  empty.className = "cart-empty";
  empty.innerHTML = `
    <div class="empty-icon-wrap">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m7.5 4.27 9 5.15"/><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/></svg>
    </div>
    <strong>Your cart is empty</strong>
    <span>Send a request and I’ll add the best verified options here.</span>
  `;
  cartPanel.append(empty);
  payArea.replaceChildren();
  latestPaymentOrders = [];
  latestPayButton = null;
  cartState.textContent = "Empty";
  cartState.classList.remove("ready");
}

function addWorkflowStep(step) {
  const previous = workflowSteps.at(-1);
  if (previous) previous.done = true;
  if (previous && previous.step === step.step) {
    previous.detail = step.detail;
    previous.done = false;
  } else {
    workflowSteps.push({ ...step, done: false });
  }
  renderWorkflow();
}

function money(value) {
  return "₹" + Number(value || 0).toFixed(2);
}

function setStatus(text, kind = "") {
  status.textContent = text;
  stateBadge.textContent = text || "Ready";
  if (kind === "error") {
    stateBadge.style.background = "#fef2f2";
    stateBadge.style.color = "#ef4444";
    stateBadge.style.borderColor = "#fecaca";
  } else if (kind === "success") {
    stateBadge.style.background = "#ecfdf5";
    stateBadge.style.color = "#059669";
    stateBadge.style.borderColor = "#a7f3d0";
  } else {
    stateBadge.style.background = "#eef2ff";
    stateBadge.style.color = "#6366f1";
    stateBadge.style.borderColor = "rgba(99, 102, 241, 0.2)";
  }
}

function appendDivider(text) {
  const element = document.createElement("div");
  element.className = "event-divider";
  const span = document.createElement("span");
  span.textContent = text;
  element.append(span);
  messages.append(element);
}

function scrollConversationToLatest() {
  conversationView.scrollTop = conversationView.scrollHeight;
}

function cleanAgentCopy(text) {
  return String(text)
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/__(.*?)__/g, "$1")
    .replace(/`([^`]+)`/g, "$1");
}

function wantsPayment(text) {
  return /\b(pay|payment|checkout|review and pay|make payment|open payment|complete payment)\b/i.test(text);
}

function appendMessage(role, name, text = "") {
  const row = document.createElement("div");
  row.className = "message " + (role === "agent" ? "agent" : "buyer");
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  if (role === "agent") {
    avatar.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/></svg>`;
  } else {
    avatar.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`;
  }
  const wrap = document.createElement("div");
  wrap.className = "bubble-wrap";
  const meta = document.createElement("p");
  meta.className = "message-meta";
  meta.textContent = name + " · now";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = cleanAgentCopy(text);
  wrap.append(meta, bubble);
  row.append(avatar, wrap);
  messages.append(row);
  scrollConversationToLatest();
  return bubble;
}

function renderPaymentHistory() {
  paymentHistory.replaceChildren();
  const records = [...paymentRecords.values()];
  if (!records.length) {
    const empty = document.createElement("div");
    empty.className = "empty-payments";
    empty.innerHTML = "<strong>No payment activity yet</strong><span>When you approve a cart, the selected merchant’s payment order will appear here.</span>";
    paymentHistory.append(empty);
    return;
  }

  for (const record of records) {
    const item = document.createElement("article");
    item.className = "payment-item" + (record.status === "verified" ? " verified" : "");
    const icon = document.createElement("div");
    icon.className = "payment-icon";
    icon.innerHTML = record.status === "verified"
      ? `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`
      : `₹`;
    const copy = document.createElement("div");
    copy.className = "payment-copy";
    const heading = document.createElement("strong");
    heading.textContent = record.status === "verified" ? "Payment confirmed" : "Secure payment order created";
    const detail = document.createElement("span");
    detail.textContent = record.status === "verified"
      ? `${record.merchant} verified the payment and recorded it.`
      : `${record.merchant} created a payment order. It is waiting for your payment.`;
    copy.append(heading, detail);
    const amount = document.createElement("span");
    amount.className = "payment-amount";
    amount.textContent = money(record.amount);
    item.append(icon, copy, amount);
    paymentHistory.append(item);
  }
}

function recordPayment(order, status = "pending") {
  const key = order.transaction_id || order.order_id;
  if (!key) return;
  const existing = paymentRecords.get(key) || {};
  paymentRecords.set(key, {
    ...existing,
    merchant: order.merchant || existing.merchant || "Selected merchant",
    amount: order.amount ?? existing.amount ?? 0,
    status,
  });
  savePaymentRecords();
  renderPaymentHistory();
}

function showWorkspaceView(view) {
  const isPayments = view === "payments";
  conversationView.classList.toggle("hidden", isPayments);
  paymentsView.classList.toggle("hidden", !isPayments);
  composerArea.classList.toggle("hidden", isPayments);
  conversationNav.classList.toggle("active", !isPayments);
  paymentsNav.classList.toggle("active", isPayments);
  if (!isPayments) input.focus();
}

function renderResponse(response) {
  const cart = response.cart;
  cartPanel.replaceChildren();
  payArea.replaceChildren();
  latestPaymentOrders = [];
  latestPayButton = null;
  if (cart && cart.items && cart.items.length) {
    const card = document.createElement("div");
    card.className = "cart-card";
    for (const item of cart.items) {
      const line = document.createElement("div");
      line.className = "cart-line";
      const itemCopy = document.createElement("div");
      const name = document.createElement("strong");
      name.textContent = `${item.product_name || "Selected product"} × ${item.quantity || 1}`;
      const merchant = document.createElement("span");
      merchant.textContent = item.merchant || "Verified merchant";
      itemCopy.append(name, merchant);
      const price = document.createElement("strong");
      price.textContent = money(item.total_price);
      line.append(itemCopy, price);
      card.append(line);
    }
    const total = document.createElement("div");
    total.className = "cart-total";
    total.innerHTML = `<span>Total</span><strong>${money(cart.total)}</strong>`;
    card.append(total);
    cartPanel.append(card);
    cartState.textContent = response.checkout && response.checkout.awaiting_confirmation ? "Ready for approval" : "Selected";
    cartState.classList.add("ready");
  } else {
    const card = document.createElement("div");
    card.className = "cart-empty";
    card.innerHTML = `
      <div class="empty-icon-wrap">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m7.5 4.27 9 5.15"/><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/></svg>
      </div>
      <strong>No verified cart yet</strong>
      <span>I’ll add an offer once the comparison is complete.</span>
    `;
    cartPanel.append(card);
    cartState.textContent = "Empty";
    cartState.classList.remove("ready");
  }

  for (const order of (response.checkout && response.checkout.merchant_orders) || []) {
    addPayButton(order);
    recordPayment(order, order.status === "verified" ? "verified" : "pending");
  }
}

function addPayButton(order) {
  if (!order.order_id || !order.transaction_id || !order.verification_url) return;
  latestPaymentOrders.push(order);

  const container = document.createElement("div");
  container.className = "payment-order-card";

  const isVerified = order.status === "verified" || order.paid_by_agent;
  const paymentLink = order.payment_link_url || `https://rzp.io/i/${order.order_id}`;

  container.innerHTML = `
    <div class="payment-order-header">
      <div class="payment-order-title">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/></svg>
        <strong>${order.merchant || "Merchant"} Order</strong>
      </div>
      <span class="payment-status-badge ${isVerified ? 'verified' : 'pending'}">
        ${isVerified ? '✓ Paid by Agent (A2A)' : 'Payment Pending'}
      </span>
    </div>

    <div class="razorpay-link-box">
      <div class="razorpay-link-label">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
        <span>Razorpay Payment Link</span>
      </div>
      <div class="razorpay-link-content">
        <a href="${paymentLink}" target="_blank" rel="noopener noreferrer" class="payment-link-url">${paymentLink}</a>
        <button class="copy-link-btn" title="Copy Payment Link">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
          Copy Link
        </button>
      </div>
    </div>

    <div class="payment-actions"></div>
  `;

  const copyBtn = container.querySelector(".copy-link-btn");
  copyBtn.addEventListener("click", () => {
    navigator.clipboard.writeText(paymentLink);
    copyBtn.innerHTML = `✓ Copied!`;
    setTimeout(() => {
      copyBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy Link`;
    }, 2000);
  });

  const actionsArea = container.querySelector(".payment-actions");

  const a2aBtn = document.createElement("button");
  a2aBtn.className = "pay pay-a2a";
  a2aBtn.innerHTML = `
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/></svg>
    <span>${isVerified ? `Agent Paid ${money(order.amount)} via A2A` : `Pay ${money(order.amount)} via A2A Protocol`}</span>
  `;

  const razorpayBtn = document.createElement("button");
  razorpayBtn.className = "pay pay-secondary";
  razorpayBtn.innerHTML = `
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="20" height="14" x="2" y="5" rx="2"/><line x1="2" x2="22" y1="10" y2="10"/></svg>
    <span>Open Razorpay Modal</span>
  `;

  if (isVerified) {
    a2aBtn.disabled = true;
    a2aBtn.style.opacity = "0.95";
    a2aBtn.style.cursor = "default";
    actionsArea.append(a2aBtn);
  } else {
    a2aBtn.addEventListener("click", () => executeA2APayment(order, a2aBtn, razorpayBtn, container));
    razorpayBtn.addEventListener("click", () => openCheckout(order, razorpayBtn, a2aBtn));
    actionsArea.append(a2aBtn, razorpayBtn);

    setTimeout(() => {
      executeA2APayment(order, a2aBtn, razorpayBtn, container);
    }, 400);
  }

  payArea.append(container);
  latestPayButton = a2aBtn;
}

async function executeA2APayment(order, button, siblingButton, container) {
  try {
    button.disabled = true;
    if (siblingButton) siblingButton.disabled = true;
    setStatus("Executing A2A Protocol direct payment settlement...");
    const payment = {
      razorpay_payment_id: "pay_a2a_" + Math.random().toString(36).slice(2, 10),
      razorpay_signature: "a2a_protocol_verified",
    };
    await verifyPayment(order, payment, button);
    if (siblingButton) siblingButton.remove();
    if (container) {
      const badge = container.querySelector(".payment-status-badge");
      if (badge) {
        badge.className = "payment-status-badge verified";
        badge.textContent = "✓ Paid by Agent (A2A)";
      }
    }
  } catch (error) {
    button.disabled = false;
    if (siblingButton) siblingButton.disabled = false;
    setStatus(error.message, "error");
  }
}

async function openCheckout(order, button, siblingButton) {
  try {
    button.disabled = true;
    if (siblingButton) siblingButton.disabled = true;
    setStatus("Opening secure payment...");
    const response = await fetch("/v1/checkout/config");
    const config = await response.json();
    if (!response.ok || !config.key_id) throw new Error(config.detail || "Checkout is not configured.");
    if (!window.Razorpay) throw new Error("Razorpay Checkout did not load.");

    const checkout = new Razorpay({
      key: config.key_id,
      amount: Math.round(Number(order.amount) * 100),
      currency: config.currency,
      name: "Relay A2A Commerce",
      description: `Order from ${order.merchant}`,
      order_id: order.order_id,
      theme: { color: "#4d7cfe" },
      handler: (payment) => {
        verifyPayment(order, payment, button);
        if (siblingButton) siblingButton.remove();
      },
      modal: {
        ondismiss: () => {
          button.disabled = false;
          if (siblingButton) siblingButton.disabled = false;
          setStatus("Payment cancelled. Merchant order remains pending.");
        },
      },
    });
    checkout.on("payment.failed", () => {
      button.disabled = false;
      if (siblingButton) siblingButton.disabled = false;
      setStatus("Payment was not completed. Merchant order remains pending.", "error");
    });
    checkout.open();
  } catch (error) {
    button.disabled = false;
    if (siblingButton) siblingButton.disabled = false;
    setStatus(error.message, "error");
  }
}

async function verifyPayment(order, payment, button) {
  try {
    setStatus("Confirming payment with the merchant...");
    const response = await fetch(order.verification_url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        transaction_id: order.transaction_id,
        razorpay_order_id: order.order_id,
        razorpay_payment_id: payment.razorpay_payment_id,
        razorpay_signature: payment.razorpay_signature,
      }),
    });
    const result = await response.json();
    if (!response.ok || result.verified !== true) throw new Error("Merchant could not verify payment. It remains pending.");
    button.innerHTML = `
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
      <span>Paid to ${order.merchant}</span>
    `;
    setStatus("Payment confirmed and recorded.", "success");
    recordPayment(order, "verified");
  } catch (error) {
    button.disabled = false;
    setStatus(error.message, "error");
  }
}

async function consumeStream(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      let type = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) type = line.slice(6).trim();
        if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (data) onEvent(type, JSON.parse(data));
    }
  }
}

document.querySelectorAll("[data-open-demo]").forEach((button) => {
  button.addEventListener("click", () => {
    landing.style.display = "none";
    workspace.classList.add("show");
    window.scrollTo(0, 0);
    input.focus();
  });
});

document.querySelector("#back-home").addEventListener("click", () => {
  workspace.classList.remove("show");
  landing.style.display = "block";
  window.scrollTo(0, 0);
});

document.querySelector("#new-request").addEventListener("click", () => {
  localStorage.removeItem(storageKey);
  sessionId = null;
  activeConversationId = null;
  saveConversations();
  showWorkspaceView("conversation");
  messages.replaceChildren();
  appendDivider("New request started");
  appendMessage("agent", "Shopping assistant", "What would you like to buy? I’ll treat this as a new shopping request.");
  workflowSteps = [];
  connectedMerchants = [];
  latestPaymentOrders = [];
  latestPayButton = null;
  setNetworkState("Standing by");
  renderAgentActivity();
  resetCart();
  renderWorkflow();
  renderConversationList();
  title.textContent = "New shopping request";
  subtitle.textContent = "Tell me what you want to buy and I’ll compare verified offers.";
  setStatus("Ready");
});

conversationNav.addEventListener("click", () => showWorkspaceView("conversation"));
paymentsNav.addEventListener("click", () => showWorkspaceView("payments"));

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    if (!send.disabled) form.requestSubmit();
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  if (wantsPayment(text) && latestPayButton && !latestPayButton.disabled) {
    appendMessage("buyer", "You", text);
    saveMessage("buyer", "You", text);
    input.value = "";
    autoResizeInput();
    latestPayButton.click();
    return;
  }
  const conversation = ensureConversation();
  appendMessage("buyer", "You", text);
  saveMessage("buyer", "You", text);
  title.textContent = conversation.title;
  subtitle.textContent = "Shopping request in progress";
  input.value = "";
  autoResizeInput();
  send.disabled = true;
  workflowSteps = [];
  connectedMerchants = [];
  setNetworkState("Connecting", true);
  renderAgentActivity();
  renderWorkflow();
  setStatus("Starting your shopping request...");
  let bubble = null;
  const shouldOpenPaymentAfterOrder = wantsPayment(text);

  try {
    const response = await fetch("/v1/buyer/messages/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ message: text, session_id: sessionId, buyer_id: "demo-web-buyer" }),
    });
    if (!response.ok) throw new Error("Could not start the buyer stream.");
    await consumeStream(response, (type, payload) => {
      if (type === "status") {
        setStatus(payload.message);
      } else if (type === "progress") {
        addWorkflowStep(payload);
        setStatus(payload.detail);
      } else if (type === "agent_activity") {
        if (Array.isArray(payload.merchants)) {
          connectedMerchants = payload.merchants;
          setNetworkState(`${connectedMerchants.length} merchant${connectedMerchants.length === 1 ? "" : "s"} connected`, connectedMerchants.length > 0);
          renderAgentActivity();
        }
      } else if (type === "reply_delta") {
        if (!bubble) {
          bubble = appendMessage("agent", "Shopping assistant", "");
          saveMessage("agent", "Shopping assistant", "");
        }
        bubble.textContent = cleanAgentCopy(bubble.textContent + payload.text);
        updateLatestAgentMessage(bubble.textContent);
        scrollConversationToLatest();
      } else if (type === "complete") {
        sessionId = payload.session_id;
        localStorage.setItem(storageKey, sessionId);
        const active = activeConversation();
        if (active) {
          active.sessionId = sessionId;
          saveConversations();
        }
        renderResponse(payload);
        if (shouldOpenPaymentAfterOrder && latestPayButton && !latestPayButton.disabled) {
          latestPayButton.click();
        }
        workflowSteps.forEach((step) => { step.done = true; });
        renderWorkflow();
        setStatus(payload.checkout && payload.checkout.awaiting_confirmation ? "Your approval is needed" : "Results ready", payload.checkout && payload.checkout.awaiting_confirmation ? "" : "success");
        setNetworkState(connectedMerchants.length ? `${connectedMerchants.length} merchant${connectedMerchants.length === 1 ? "" : "s"} connected` : "No merchants connected", connectedMerchants.length > 0);
      } else if (type === "error") {
        setStatus(payload.detail, "error");
        setNetworkState("Connection issue");
      }
    });
  } catch (error) {
    setStatus(error.message, "error");
    appendMessage("agent", "Shopping assistant", "I could not complete that request. Please retry.");
    saveMessage("agent", "Shopping assistant", "I could not complete that request. Please retry.");
  } finally {
    send.disabled = false;
    input.focus();
  }
});

renderPaymentHistory();
if (activeConversationId && activeConversation()) openConversation(activeConversationId);
else renderConversationList();
renderWorkflow();
startAsciiSphere();

function autoResizeInput() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
}

input.addEventListener("input", autoResizeInput);
autoResizeInput();


