<template>
  <div class="theme-toggle" role="radiogroup" aria-label="主题切换">
    <span class="thumb" :class="theme"></span>

    <button
        type="button"
        class="option"
        :class="{ active: theme === 'light' }"
        role="radio"
        :aria-checked="theme === 'light'"
        title="浅色主题"
        @click="setTheme('light')"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"
           stroke-linecap="round" aria-hidden="true">
        <circle cx="12" cy="12" r="4"/>
        <path d="M12 2.6v2M12 19.4v2M4.6 4.6l1.4 1.4M18 18l1.4 1.4M2.6 12h2M19.4 12h2M4.6 19.4L6 18M18 6l1.4-1.4"/>
      </svg>
    </button>

    <button
        type="button"
        class="option"
        :class="{ active: theme === 'dark' }"
        role="radio"
        :aria-checked="theme === 'dark'"
        title="深色主题"
        @click="setTheme('dark')"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"
           stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M20.5 14.2A8.4 8.4 0 0 1 9.8 3.5a8.6 8.6 0 1 0 10.7 10.7z"/>
      </svg>
    </button>
  </div>
</template>

<script setup>
import { useTheme } from "../composables/useTheme.js";

const { theme, setTheme } = useTheme();
</script>

<style scoped>
.theme-toggle {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border-radius: 999px;
  background: var(--surface-3);
  border: 1px solid var(--border);
}

/* 滑动指示块 */
.thumb {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 30px;
  height: 30px;
  border-radius: 999px;
  background: var(--surface);
  box-shadow: var(--shadow-sm);
  transition: transform 0.32s cubic-bezier(0.34, 1.4, 0.5, 1);
}

.thumb.dark {
  transform: translateX(32px);
}

.option {
  position: relative;
  z-index: 1;
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  padding: 0;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: var(--text-faint);
  transition: color 0.25s ease;
}

.option svg {
  width: 17px;
  height: 17px;
}

.option:hover {
  color: var(--text-muted);
}

.option.active {
  color: var(--accent);
}

.option:focus-visible {
  outline: none;
  box-shadow: var(--ring);
}
</style>
