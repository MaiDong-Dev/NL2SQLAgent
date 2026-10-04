<template>
  <div class="result-table">
    <!-- 空结果：后端返回 []，既不是错误也不代表"查到了 0" -->
    <div v-if="!rows.length" class="empty">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"
           stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="11" cy="11" r="7"/>
        <path d="M20 20l-3.6-3.6"/>
      </svg>
      <div>
        <p class="empty-title">查询未返回数据</p>
        <p class="empty-hint">SQL 执行成功，但结果集为空，可尝试放宽时间或维度条件</p>
      </div>
    </div>

    <template v-else>
      <div class="table-scroll">
        <table>
          <thead>
          <tr>
            <th v-for="col in columns" :key="col" :class="{ numeric: isNumeric(col) }">
              {{ col }}
            </th>
          </tr>
          </thead>
          <tbody>
          <tr v-for="(row, rIdx) in rows" :key="rIdx">
            <td v-for="col in columns" :key="col" :class="{ numeric: isNumeric(col) }">
              <span v-if="row[col] === null || row[col] === undefined" class="null">—</span>
              <template v-else>{{ formatCell(row[col]) }}</template>
            </td>
          </tr>
          </tbody>
        </table>
      </div>

      <div class="table-foot">
        <span class="count">{{ rows.length }} 行 · {{ columns.length }} 列</span>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
  columns: { type: Array, default: () => [] },
  rows: { type: Array, default: () => [] },
});

/** 某列是否整体是数值列（用于右对齐；空值不参与判断） */
function isNumeric(col) {
  const values = props.rows.map((row) => row[col]).filter((v) => v !== null && v !== undefined);
  return values.length > 0 && values.every((v) => typeof v === "number");
}

/**
 * 数值列统一保留两位小数：AVG / 占比这类聚合会返回一长串浮点尾数，
 * 原样展示既难读也撑宽表格。整数保持原样，避免把 date_id 之类的编码格式化。
 */
function formatCell(value) {
  if (typeof value === "number" && !Number.isInteger(value)) return value.toFixed(2);
  return value;
}
</script>

<style scoped>
.result-table {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.table-scroll {
  overflow: auto;
  max-height: 440px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface);
}

table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 13.5px;
  font-variant-numeric: tabular-nums;
}

th,
td {
  padding: 9px 14px;
  text-align: left;
  white-space: nowrap;
  border-bottom: 1px solid var(--border);
}

th + th,
td + td {
  border-left: 1px solid var(--border);
}

th {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--surface-2);
  color: var(--text-muted);
  font-weight: 600;
  font-size: 12.5px;
  letter-spacing: 0.02em;
}

td {
  color: var(--text);
}

tbody tr {
  transition: background-color 0.15s ease;
}

tbody tr:hover td {
  background: var(--accent-soft);
}

tbody tr:last-child td {
  border-bottom: none;
}

th.numeric,
td.numeric {
  text-align: right;
}

.null {
  color: var(--text-faint);
}

/* 空结果 */
.empty {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 18px;
  border: 1px dashed var(--border-strong);
  border-radius: 12px;
  background: var(--surface-2);
}

.empty svg {
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  color: var(--text-faint);
}

.empty p {
  margin: 0;
}

.empty-title {
  color: var(--text);
  font-weight: 600;
  font-size: 14px;
}

.empty-hint {
  color: var(--text-muted);
  font-size: 12.5px;
}

/* 表尾统计 */
.table-foot {
  display: flex;
  justify-content: flex-end;
  padding-top: 8px;
}

.count {
  font-size: 12px;
  color: var(--text-faint);
  font-variant-numeric: tabular-nums;
}
</style>
