<template>
  <div class="row" :class="msg.role">
    <!-- 助手头像 -->
    <div v-if="msg.role === 'assistant'" class="avatar agent" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
           stroke-linecap="round" stroke-linejoin="round">
        <ellipse cx="12" cy="5.5" rx="7.5" ry="2.8"/>
        <path d="M4.5 5.5v13c0 1.55 3.36 2.8 7.5 2.8s7.5-1.25 7.5-2.8v-13"/>
        <path d="M4.5 12c0 1.55 3.36 2.8 7.5 2.8s7.5-1.25 7.5-2.8"/>
      </svg>
    </div>

    <div class="bubble" :class="[`bubble-${msg.type}`, { wide: msg.type === 'table' }]">
      <!-- 纯文本 -->
      <p v-if="msg.type === 'text'" class="text">{{ msg.content }}</p>

      <!-- 处理步骤 -->
      <div v-else-if="msg.type === 'steps'" class="steps">
        <!-- 首个进度事件到达前的等待态 -->
        <div v-if="!msg.steps.length" class="thinking">
          <span class="dot"></span><span class="dot"></span><span class="dot"></span>
          <span class="thinking-text">正在理解问题…</span>
        </div>

        <template v-else>
          <button type="button" class="steps-head" @click="stepsOpen = !stepsOpen">
            <span class="steps-title">处理过程</span>
            <span class="steps-count">{{ doneCount }}/{{ msg.steps.length }}</span>
            <svg class="chevron" :class="{ folded: !stepsOpen }" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M6 9l6 6 6-6"/>
            </svg>
          </button>

          <ol v-show="stepsOpen" class="step-list">
            <li v-for="(step, sIdx) in msg.steps" :key="sIdx" class="step" :class="step.status">
              <span class="marker">
                <svg v-if="step.status === 'success'" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M5 12.5l4.5 4.5L19 7.5"/>
                </svg>
                <svg v-else-if="step.status === 'error'" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     stroke-width="3" stroke-linecap="round">
                  <path d="M7 7l10 10M17 7L7 17"/>
                </svg>
                <span v-else class="spinner"></span>
              </span>
              <span class="step-text">{{ step.text }}</span>
            </li>
          </ol>
        </template>
      </div>

      <!-- 结果表格 -->
      <ResultTable
          v-else-if="msg.type === 'table'"
          :columns="msg.columns"
          :rows="msg.rows"
      />

      <!-- 错误 -->
      <div v-else-if="msg.type === 'error'" class="error">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"
             stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="9"/>
          <path d="M12 7.5v5M12 16.2v.1"/>
        </svg>
        <span>{{ msg.content }}</span>
      </div>
    </div>

    <!-- 用户头像 -->
    <div v-if="msg.role === 'user'" class="avatar user" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"
           stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="8.5" r="3.8"/>
        <path d="M4.8 20.2a7.4 7.4 0 0 1 14.4 0"/>
      </svg>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from "vue";
import ResultTable from "./ResultTable.vue";

const props = defineProps({
  msg: { type: Object, required: true },
});

const stepsOpen = ref(true);

const doneCount = computed(() =>
  (props.msg.steps || []).filter((s) => s.status !== "running").length
);
</script>

<style scoped>
.row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 18px;
  animation: rise 0.34s cubic-bezier(0.22, 0.8, 0.3, 1) both;
}

.row.user {
  justify-content: flex-end;
}

@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

/* ---------- 头像 ---------- */
.avatar {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border-radius: 10px;
  margin-top: 2px;
}

.avatar svg {
  width: 18px;
  height: 18px;
}

.avatar.agent {
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  color: var(--on-accent);
  box-shadow: 0 4px 14px var(--accent-soft);
}

.avatar.user {
  background: var(--surface-3);
  color: var(--text-muted);
  border: 1px solid var(--border);
}

/* ---------- 气泡 ---------- */
.bubble {
  max-width: min(760px, 78%);
  min-width: 0;
  padding: 11px 15px;
  border-radius: 14px;
  border: 1px solid var(--border);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}

.bubble.wide {
  max-width: min(1000px, 88%);
}

.row.user .bubble {
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  border-color: transparent;
  color: var(--on-accent);
  border-bottom-right-radius: 5px;
}

.row.assistant .bubble {
  border-bottom-left-radius: 5px;
}

.text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ---------- 处理步骤 ---------- */
.steps {
  min-width: 220px;
}

.steps-head {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 0 0 8px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.steps-title {
  color: var(--text);
}

.steps-count {
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--surface-3);
  color: var(--text-muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.chevron {
  width: 14px;
  height: 14px;
  margin-left: auto;
  transition: transform 0.25s ease;
}

.chevron.folded {
  transform: rotate(-90deg);
}

.step-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.step {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 13.5px;
  color: var(--text-muted);
  animation: rise 0.28s ease both;
}

.marker {
  display: grid;
  place-items: center;
  width: 17px;
  height: 17px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--surface-3);
}

.marker svg {
  width: 11px;
  height: 11px;
}

.step.success .marker {
  background: var(--success-soft);
  color: var(--success);
}

.step.success .step-text {
  color: var(--text);
}

.step.error .marker {
  background: var(--danger-soft);
  color: var(--danger);
}

.step.error .step-text {
  color: var(--danger);
}

.step.running .marker {
  background: var(--accent-soft);
}

.spinner {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  border: 2px solid var(--border-strong);
  border-top-color: var(--accent);
  animation: spin 0.7s linear infinite;
}

/* 等待首个进度事件 */
.thinking {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 3px 0;
}

.thinking .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  animation: bounce 1.25s ease-in-out infinite;
}

.thinking .dot:nth-child(2) {
  animation-delay: 0.16s;
}

.thinking .dot:nth-child(3) {
  animation-delay: 0.32s;
}

.thinking-text {
  margin-left: 5px;
  font-size: 13px;
  color: var(--text-muted);
}

@keyframes bounce {
  0%,
  60%,
  100% {
    opacity: 0.3;
    transform: translateY(0);
  }
  30% {
    opacity: 1;
    transform: translateY(-4px);
  }
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* ---------- 错误 ---------- */
.error {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  color: var(--danger);
  font-size: 13.5px;
  line-height: 1.55;
}

.error svg {
  width: 17px;
  height: 17px;
  flex-shrink: 0;
  margin-top: 2px;
}

/* ---------- 窄屏 ---------- */
@media (max-width: 720px) {
  .bubble,
  .bubble.wide {
    max-width: 100%;
  }

  .row {
    gap: 8px;
  }

  .avatar {
    width: 28px;
    height: 28px;
  }
}
</style>
