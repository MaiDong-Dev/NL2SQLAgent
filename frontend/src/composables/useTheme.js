// =============================================================================
// 主题状态（模块级单例）
// 优先级：用户上次手动选择 > 系统偏好。选择结果写入 localStorage 持久化。
// 页面首帧由 index.html 里的内联脚本先落一次 data-theme，避免刷新时闪白。
// =============================================================================

import { ref, computed } from "vue";

const STORAGE_KEY = "nl2sql-agent-theme";
const THEMES = ["light", "dark"];

const darkQuery =
  typeof window !== "undefined" && window.matchMedia
    ? window.matchMedia("(prefers-color-scheme: dark)")
    : null;

function readStored() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return THEMES.includes(saved) ? saved : null;
  } catch {
    // 隐私模式等场景下 localStorage 不可用，退回系统偏好即可
    return null;
  }
}

/** 系统当前偏好：无法探测时按深色处理（本项目的默认观感） */
export function systemTheme() {
  return darkQuery && !darkQuery.matches ? "light" : "dark";
}

const theme = ref(readStored() || systemTheme());

/** 把主题落到 DOM 上，并同步浏览器 UI（表单控件、地址栏颜色） */
function apply(value) {
  const root = document.documentElement;
  root.dataset.theme = value;
  root.style.colorScheme = value;

  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", value === "dark" ? "#05080e" : "#eef1f8");
}

/** 应用启动时调用一次，确保 JS 状态与 DOM 一致 */
export function initTheme() {
  apply(theme.value);
}

/**
 * 组件内使用：
 *   const { theme, isDark, toggle, setTheme } = useTheme()
 */
export function useTheme() {
  function setTheme(value) {
    if (!THEMES.includes(value) || value === theme.value) return;
    theme.value = value;
    apply(value);
    try {
      localStorage.setItem(STORAGE_KEY, value);
    } catch {
      // 存不下就算了，不影响本次会话内的切换
    }
  }

  function toggle() {
    setTheme(theme.value === "dark" ? "light" : "dark");
  }

  return {
    theme,
    isDark: computed(() => theme.value === "dark"),
    setTheme,
    toggle,
  };
}

// 用户没有手动选择过时，跟随系统在明暗之间实时切换
darkQuery?.addEventListener?.("change", (event) => {
  if (readStored()) return;
  const next = event.matches ? "dark" : "light";
  theme.value = next;
  apply(next);
});
