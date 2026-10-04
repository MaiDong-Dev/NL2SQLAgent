<template>
  <div class="app">
    <!-- 背景装饰：两团辉光 + 网格，纯装饰不参与交互 -->
    <div class="backdrop" aria-hidden="true">
      <span class="glow glow-a"></span>
      <span class="glow glow-b"></span>
      <span class="grid"></span>
    </div>

    <header class="topbar">
      <div class="brand">
        <span class="brand-mark">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
               stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <ellipse cx="12" cy="5.5" rx="7.5" ry="2.8"/>
            <path d="M4.5 5.5v13c0 1.55 3.36 2.8 7.5 2.8s7.5-1.25 7.5-2.8v-13"/>
            <path d="M4.5 12c0 1.55 3.36 2.8 7.5 2.8s7.5-1.25 7.5-2.8"/>
          </svg>
        </span>
        <span class="brand-text">
          <strong>掌柜问数</strong>
          <small>NL2SQL · 自然语言转 SQL 智能体</small>
        </span>
      </div>

      <div class="topbar-right">
        <span class="status" :class="{ busy: loading }">
          <span class="pulse"></span>
          {{ loading ? "查询中" : "已就绪" }}
        </span>
        <ThemeToggle/>
      </div>
    </header>

    <main ref="scrollEl" class="messages">
      <div class="messages-inner">
        <!-- 空态：欢迎页 + 示例问题 -->
        <section v-if="!messages.length" class="welcome">
          <span class="welcome-badge">
            <span class="pulse"></span>
            数据仓库已连接
          </span>

          <h1>
            用一句话，向数据<span class="grad">提个问题</span>
          </h1>
          <p class="welcome-sub">
            系统依次完成关键词抽取、字段召回、SQL 生成与校验，最后在数据仓库上实际执行并返回结果。
          </p>

          <div class="examples">
            <button
                v-for="example in examples"
                :key="example"
                type="button"
                class="example"
                @click="askExample(example)"
            >
              <span>{{ example }}</span>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                   stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M5 12h13M13 6l6 6-6 6"/>
              </svg>
            </button>
          </div>
        </section>

        <MessageBubble v-for="(msg, index) in messages" :key="index" :msg="msg"/>
      </div>
    </main>

    <footer class="composer">
      <div class="composer-inner">
        <div class="input-shell" :class="{ focused, busy: loading }">
          <textarea
              ref="textareaEl"
              v-model="question"
              rows="1"
              placeholder="输入你的问题，例如：统计各大区的销售总额"
              @input="autoGrow"
              @focus="focused = true"
              @blur="focused = false"
              @keydown="onKeydown"
          ></textarea>

          <button
              v-if="!loading"
              type="button"
              class="send"
              :disabled="!question.trim()"
              title="发送 (Enter)"
              @click="sendQuestion"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3"
                 stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M12 19V5M6 11l6-6 6 6"/>
            </svg>
          </button>

          <button v-else type="button" class="stop" title="停止本次查询" @click="stop">
            <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <rect x="7" y="7" width="10" height="10" rx="2"/>
            </svg>
          </button>
        </div>

        <p class="hint">Enter 发送 · Shift + Enter 换行</p>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { nextTick, reactive, ref } from "vue";
import MessageBubble from "./components/MessageBubble.vue";
import ThemeToggle from "./components/ThemeToggle.vue";

const API_URL = "/api/query";

// 示例问题取自 eval/dataset.jsonl，均落在数仓真实数据范围（2025 年 Q1）内，保证有结果
const examples = [
  "统计各大区的销售总额",
  "2025年每个月的订单量是多少",
  "各会员等级客户的客单价是多少",
  "销量前三名的商品有哪些",
  "广东省男性客户的订单数是多少",
  "2025年3月各品牌的销售额排名是怎样的",
];

const question = ref("");
const loading = ref(false);
const focused = ref(false);
const messages = ref([]);
const scrollEl = ref(null);
const textareaEl = ref(null);

/** 用于中断进行中的流式请求 */
let controller = null;

function scrollToBottom() {
  const el = scrollEl.value;
  if (el) el.scrollTop = el.scrollHeight;
}

function autoGrow() {
  const el = textareaEl.value;
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, 150)}px`;
}

function resetTextarea() {
  const el = textareaEl.value;
  if (el) el.style.height = "auto";
}

/** Enter 发送、Shift + Enter 换行；isComposing 用于避开中文输入法选词时的回车 */
function onKeydown(event) {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  sendQuestion();
}

/** 把仍在 running 的步骤落定，避免请求中断后状态一直转圈 */
function settleRunningSteps(stepMsg, status) {
  stepMsg.steps.forEach((step) => {
    if (step.status === "running") step.status = status;
  });
}

/** 处理一个 SSE 事件（后端约定：progress / result / error 三种） */
function handleEvent(data, stepMsg) {
  if (data.type === "progress") {
    const step = stepMsg.steps.find((s) => s.text === data.step);
    if (step) step.status = data.status;
    else stepMsg.steps.push({ text: data.step, status: data.status });
    return;
  }

  if (data.type === "result" && Array.isArray(data.data)) {
    messages.value.push({
      role: "assistant",
      type: "table",
      columns: Object.keys(data.data[0] || {}),
      rows: data.data,
    });
    // 后端对结果集做了行数上限截断（app_config.sql.max_result_rows），提示用户看到的是部分数据
    if (data.truncated) {
      messages.value.push({
        role: "assistant",
        type: "text",
        content: `结果行数超过上限，仅显示前 ${data.data.length} 行。可补充过滤条件或缩小时间范围后再查。`,
      });
    }
    return;
  }

  if (data.type === "error") {
    settleRunningSteps(stepMsg, "error");
    messages.value.push({
      role: "assistant",
      type: "error",
      content: data.message || "发生错误",
    });
  }
}

async function sendQuestion() {
  const text = question.value.trim();
  if (!text || loading.value) return;

  question.value = "";
  resetTextarea();
  loading.value = true;

  messages.value.push({ role: "user", type: "text", content: text });

  // 持有对象引用而不是下标：后续 push 表格/错误消息时下标会失效
  const stepMsg = reactive({ role: "assistant", type: "steps", steps: [] });
  messages.value.push(stepMsg);

  await nextTick();
  scrollToBottom();

  controller = new AbortController();

  try {
    const response = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: text }),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`服务返回 ${response.status} ${response.statusText}`);
    }
    if (!response.body) {
      throw new Error("服务器未返回流式响应");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop();

      for (const chunk of chunks) {
        const line = chunk.trim();
        if (!line.startsWith("data:")) continue;

        let data;
        try {
          data = JSON.parse(line.replace(/^data:\s*/, ""));
        } catch {
          // 半个包或心跳行，跳过即可
          continue;
        }

        handleEvent(data, stepMsg);
        await nextTick();
        scrollToBottom();
      }
    }
  } catch (error) {
    settleRunningSteps(stepMsg, "error");
    messages.value.push({
      role: "assistant",
      type: "error",
      content: error?.name === "AbortError" ? "已取消本次查询" : error?.message || "请求失败",
    });
  } finally {
    loading.value = false;
    controller = null;
    await nextTick();
    scrollToBottom();
    textareaEl.value?.focus();
  }
}

function stop() {
  controller?.abort();
}

async function askExample(example) {
  if (loading.value) return;
  question.value = example;
  await sendQuestion();
}
</script>

<style scoped>
.app {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100vh; /* 老浏览器回退 */
  height: 100dvh; /* 移动端地址栏收起时不留白 */
  overflow: hidden;
}

/* ---------- 背景 ---------- */
.backdrop {
  position: absolute;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  pointer-events: none;
}

.glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(90px);
  transition: background 0.32s ease;
}

.glow-a {
  top: -16vw;
  left: -8vw;
  width: 48vw;
  height: 48vw;
  background: var(--bg-glow-1);
}

.glow-b {
  right: -8vw;
  bottom: -18vw;
  width: 42vw;
  height: 42vw;
  background: var(--bg-glow-2);
}

.grid {
  position: absolute;
  inset: 0;
  background-image: linear-gradient(var(--grid-line) 1px, transparent 1px),
  linear-gradient(90deg, var(--grid-line) 1px, transparent 1px);
  background-size: 44px 44px;
  -webkit-mask-image: radial-gradient(ellipse 78% 62% at 50% 26%, #000 28%, transparent 76%);
  mask-image: radial-gradient(ellipse 78% 62% at 50% 26%, #000 28%, transparent 76%);
}

/* ---------- 顶栏 ---------- */
.topbar {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 13px 24px;
  border-bottom: 1px solid var(--border);
  background: var(--glass);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
}

.brand {
  display: flex;
  align-items: center;
  gap: 11px;
  min-width: 0;
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  border-radius: 11px;
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  color: var(--on-accent);
  box-shadow: 0 6px 18px var(--accent-soft);
}

.brand-mark svg {
  width: 19px;
  height: 19px;
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}

.brand-text strong {
  font-size: 15px;
  font-weight: 650;
  letter-spacing: 0.01em;
}

.brand-text small {
  font-size: 11.5px;
  color: var(--text-faint);
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.status {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 5px 12px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text-muted);
  font-size: 12px;
  white-space: nowrap;
}

.pulse {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--success);
  animation: pulse 2.2s ease-in-out infinite;
}

.status.busy .pulse {
  background: var(--warning);
}

@keyframes pulse {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.35;
    transform: scale(0.75);
  }
}

/* ---------- 消息区 ---------- */
.messages {
  position: relative;
  z-index: 1;
  flex: 1;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.messages-inner {
  max-width: 1000px;
  margin: 0 auto;
  padding: 28px 24px 36px;
}

/* ---------- 欢迎页 ---------- */
.welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 7vh 0 0;
  text-align: center;
  animation: rise 0.5s cubic-bezier(0.22, 0.8, 0.3, 1) both;
}

@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

.welcome-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 5px 13px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text-muted);
  font-size: 12px;
}

.welcome h1 {
  margin: 20px 0 0;
  font-size: clamp(24px, 3.4vw, 34px);
  font-weight: 700;
  letter-spacing: -0.015em;
  line-height: 1.3;
}

.grad {
  background: linear-gradient(120deg, var(--accent), var(--accent-2));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.welcome-sub {
  max-width: 580px;
  margin: 14px 0 0;
  color: var(--text-muted);
  font-size: 14px;
}

.examples {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(238px, 1fr));
  gap: 10px;
  width: 100%;
  margin-top: 34px;
}

.example {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 13px 15px;
  border-radius: 12px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  font-size: 13.5px;
  text-align: left;
  box-shadow: var(--shadow-sm);
  transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}

.example:hover {
  transform: translateY(-2px);
  border-color: var(--accent);
  box-shadow: var(--shadow);
}

.example:focus-visible {
  outline: none;
  box-shadow: var(--ring);
}

.example svg {
  width: 15px;
  height: 15px;
  flex-shrink: 0;
  color: var(--text-faint);
  transition: transform 0.2s ease, color 0.2s ease;
}

.example:hover svg {
  color: var(--accent);
  transform: translateX(3px);
}

/* ---------- 输入区 ---------- */
.composer {
  position: relative;
  z-index: 2;
  padding: 0 24px 18px;
}

.composer-inner {
  max-width: 1000px;
  margin: 0 auto;
}

.input-shell {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  padding: 9px 9px 9px 16px;
  border-radius: 18px;
  border: 1px solid var(--border-strong);
  background: var(--glass);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  box-shadow: var(--shadow);
  transition: border-color 0.22s ease, box-shadow 0.22s ease;
}

.input-shell.focused {
  border-color: var(--accent);
  box-shadow: var(--shadow), var(--ring);
}

.input-shell textarea {
  flex: 1;
  min-width: 0;
  max-height: 150px;
  padding: 7px 0;
  border: none;
  outline: none;
  resize: none;
  background: transparent;
  color: var(--text);
  font-family: inherit;
  font-size: 15px;
  line-height: 1.55;
  overflow-y: auto;
}

.input-shell textarea::placeholder {
  color: var(--text-faint);
}

.send,
.stop {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  flex-shrink: 0;
  border: none;
  border-radius: 12px;
  transition: transform 0.18s ease, filter 0.18s ease, opacity 0.18s ease,
  border-color 0.18s ease, color 0.18s ease;
}

.send {
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  color: var(--on-accent);
}

.send:hover:not(:disabled) {
  transform: translateY(-1px);
  filter: brightness(1.08);
}

.send:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.send:focus-visible,
.stop:focus-visible {
  outline: none;
  box-shadow: var(--ring);
}

.stop {
  background: var(--surface-3);
  border: 1px solid var(--border);
  color: var(--text-muted);
}

.stop:hover {
  color: var(--danger);
  border-color: var(--danger);
}

.send svg {
  width: 17px;
  height: 17px;
}

.stop svg {
  width: 15px;
  height: 15px;
}

.hint {
  margin: 9px 0 0;
  text-align: center;
  font-size: 11.5px;
  color: var(--text-faint);
}

/* ---------- 窄屏 ---------- */
@media (max-width: 720px) {
  .topbar {
    padding: 11px 16px;
  }

  .brand-text small,
  .status {
    display: none;
  }

  .messages-inner {
    padding: 20px 14px 26px;
  }

  .composer {
    padding: 0 14px 14px;
  }

  .welcome {
    padding-top: 5vh;
  }

  .examples {
    grid-template-columns: 1fr;
  }
}
</style>
