import { createApp } from 'vue'
import './style.css'
import App from './App.vue'
import { initTheme } from './composables/useTheme.js'

// 与 index.html 的首帧脚本对齐（用户在无 JS 服务端渲染等场景下也能拿到正确主题）
initTheme()

createApp(App).mount('#app')
